from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

import database
from services.reader_election import ReaderElection, ReaderUnavailable
from services.reader_jobs import ReaderJobs
from services.shared_reader import ReaderAuthority, SharedReaderCoordinator
from test_reader_jobs import fixture


def test_offline_roster_cannot_exhaust_budget_before_checking_available_local_reader(tmp_path):
    elections, _, _, _, _, _, _, scope, _, _ = cluster(tmp_path)
    elapsed, calls = [0.0], []
    election = elections['C']  # Last in the old sequential candidate order.
    def offline(member, requested):
        calls.append(member)
        elapsed[0] += 8
        raise TimeoutError('Synthetic offline member')
    election.probe = offline
    selected = election.select(scope[0], timeout=15, clock=lambda: elapsed[0])
    assert selected.member_id == 'C'
    assert calls == ['A', 'A']
    assert election.partial(0)
    assert election.owns(scope[0])
    election.invalidate()
    assert not election.partial(0)


def cluster(tmp_path):
    _, now, scope, origins, args = fixture()
    elections, authorities, clients, paths = {}, {}, {}, {}
    online, ready, blocked, calls = set(origins), set(origins), set(), []
    def add(member):
        def probe(remote, requested):
            calls.append((member, remote))
            if remote not in online or (member, remote) in blocked:
                raise TimeoutError("synthetic partition")
            return elections[remote].presence(member, requested)
        election = elections[member] = ReaderElection(member_id=member,
            authorize=args["authorize"], members=lambda slot: tuple(origins),
            current_scope=args["current_scope"], ready=lambda slot: member in ready and member in online,
            probe=probe)
        jobs = ReaderJobs(**args, path=paths[member], authority_ready=election.owns)
        authorities[member] = ReaderAuthority(election=election, jobs=jobs)
        def endpoint(remote):
            if remote not in online or (member, remote) in blocked:
                raise TimeoutError("synthetic endpoint unavailable")
            return authorities[remote]
        clients[member] = SharedReaderCoordinator(election=election, endpoint=endpoint)
    for member in origins:
        path = paths[member] = tmp_path / f"{member}.sqlite3"
        with closing(sqlite3.connect(database.get_db_path())) as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
            target.execute("INSERT OR REPLACE INTO web_observation_state VALUES('origin',?)", (origins[member],))
            target.commit()
        add(member)
    return elections, authorities, clients, online, ready, blocked, calls, scope, now, add


def test_simultaneous_boot_has_one_owner_and_one_manual_job(tmp_path):
    elections, authorities, clients, _, _, _, _, scope, _, _ = cluster(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        reads = list(pool.map(lambda member: clients[member].request(scope[0], "same-moment", manual=True), "ABC"))
    assert {read.authority for read in reads} == {"A"}
    assert len({read.job["job_id"] for read in reads}) == 1
    assert sum(read.job["granted"] for read in reads) == 1
    for member in "BC":
        assert clients[member].request(scope[0], "scheduled", manual=False) is None
    assert all(item.owner(scope[0]) == "A" for item in elections.values())


def test_first_ready_stays_owner_when_lower_id_pc_arrives(tmp_path):
    elections, _, clients, online, _, _, _, scope, _, _ = cluster(tmp_path)
    online.clear()
    online.add("B")
    assert clients["B"].request(scope[0], "first", manual=False).authority == "B"
    online.update("AC")
    assert clients["A"].request(scope[0], "later", manual=False) is None
    assert elections["A"].owner(scope[0]) == "B"
    manual = clients["C"].request(scope[0], "manual", manual=True)
    assert manual.authority == "B" and manual.job["reader_id"] == "B"


def test_power_loss_takes_over_at_next_request_and_restart_does_not_steal(tmp_path):
    elections, authorities, clients, online, _, _, calls, scope, _, restart = cluster(tmp_path)
    first = clients["A"].request(scope[0], "ten", manual=False)
    online.remove("A")
    calls.clear()
    second = clients["B"].request(scope[0], "ten-fifteen", manual=False)
    assert second.authority == "B" and second.job["job_id"] != first.job["job_id"]
    assert calls.count(("B", "A")) == 4  # one bounded retry per selection, client + authority
    restart("A")
    online.add("A")
    assert clients["A"].request(scope[0], "returned", manual=False) is None
    assert elections["A"].owner(scope[0]) == "B"
    with pytest.raises(PermissionError, match="no longer owns"):
        authorities["A"].jobs.request("A", "stale-authority", scope[0])


def test_manual_reader_does_not_take_over_scheduled_owner(tmp_path):
    elections, authorities, clients, _, _, _, _, scope, _, _ = cluster(tmp_path)
    # Establish the normal owner without consuming a read job.
    elections["A"].select(scope[0])
    first = clients["B"].request(scope[0], "manual-1010", manual=True)
    simultaneous = clients["C"].request(scope[0], "manual-1010", manual=True)
    scheduled = clients["A"].request(scope[0], "scheduled-1015", manual=False)
    assert first.job["reader_id"] == "B" and first.job["can_read"]
    assert simultaneous.job["job_id"] == scheduled.job["job_id"] == first.job["job_id"]
    assert not simultaneous.job["can_read"] and not scheduled.job["can_read"]
    authorities["A"].fail("B", first.job["job_id"], scope[0], reason="web")
    following = clients["A"].request(scope[0], "scheduled-1030", manual=False)
    assert following.job["reader_id"] == "A" and following.job["granted"]
    assert elections["B"].owner(scope[0]) == "A"


def test_partition_may_read_twice_but_heals_to_one_authority_and_fences_loser(tmp_path):
    elections, authorities, clients, _, _, blocked, _, scope, _, _ = cluster(tmp_path)
    blocked.update({("A", "B"), ("A", "C"), ("B", "A"), ("C", "A")})
    a = clients["A"].request(scope[0], "partition-a", manual=False)
    b = clients["B"].request(scope[0], "partition-b", manual=False)
    assert (a.authority, b.authority) == ("A", "B")
    assert elections['A'].partial(0) and elections['B'].partial(0)
    blocked.clear()
    assert clients["B"].request(scope[0], "reconnected", manual=False) is None
    assert elections["B"].owner(scope[0]) == "A"
    assert not elections['B'].partial(0)
    with pytest.raises(PermissionError, match="no longer owns"):
        authorities["B"].status("B", b.job["job_id"], scope[0])
    assert clients["C"].request(scope[0], "manual", manual=True).job["job_id"] == a.job["job_id"]


def test_lost_reply_retries_same_request_at_same_authority(tmp_path):
    _, authorities, clients, _, _, _, _, scope, _, _ = cluster(tmp_path)
    real = authorities["A"]
    class LostReply:
        calls = 0
        def request(self, *args, **kwargs):
            result = real.request(*args, **kwargs)
            self.calls += 1
            if self.calls == 1:
                self.original = result
                raise TimeoutError("committed but reply lost")
            return result
    endpoint = LostReply()
    clients["B"].endpoint = lambda member: endpoint
    result = clients["B"].request(scope[0], "stable-request", manual=True)
    assert result.job["job_id"] == endpoint.original["job_id"]
    assert not result.job["granted"] and result.job["can_read"]
    assert endpoint.calls == 2


def test_revocation_or_malformed_reply_does_not_trigger_takeover(tmp_path):
    elections, _, _, _, _, _, calls, scope, _, _ = cluster(tmp_path)
    election = elections["A"]
    election.authorize = lambda member, slot: None
    with pytest.raises(PermissionError):
        election.select(scope[0])
    assert calls == []
    election.authorize = elections["B"].authorize
    election.probe = lambda member, requested: replace(elections[member].presence("A", requested), member_id="imposter")
    with pytest.raises(ValueError, match="presence"):
        election.select(scope[0])
    assert election.owner(scope[0]) is None


def test_cancellation_budget_and_lifecycle_change_publish_no_decision(tmp_path):
    elections, _, _, _, _, _, calls, scope, _, _ = cluster(tmp_path)
    election = elections["A"]
    with pytest.raises(CancelledError):
        election.select(scope[0], cancelled=lambda: True)
    assert calls == []
    # Expiry before any verified presence cannot publish an owner. Expiry
    # after finding a ready local reader is covered by the offline-roster case.
    ticks = iter([0, 100])
    with pytest.raises(ReaderUnavailable, match="budget"):
        election.select(scope[0], clock=lambda: next(ticks))
    original = election.probe
    def changing(member, requested):
        result = original(member, requested)
        election.invalidate()
        return result
    election.probe = changing
    with pytest.raises(ReaderUnavailable, match="lifecycle"):
        election.select(scope[0])
    assert election.owner(scope[0]) is None


def test_no_ready_members_and_scope_changes_cannot_reuse_old_owner(tmp_path):
    elections, _, _, _, ready, _, _, scope, _, _ = cluster(tmp_path)
    election = elections["A"]
    assert election.select(scope[0]).member_id == "A"
    ready.clear()
    with pytest.raises(ReaderUnavailable):
        election.select(scope[0])
    assert election.owner(scope[0]) is None
    ready.update("ABC")
    old = scope[0]
    scope[0] = replace(old, settings_revision="new-settings")
    with pytest.raises(PermissionError):
        election.select(old)
    assert election.select(scope[0]).member_id == "A"


def test_authority_loss_during_grant_rolls_back_job_and_request(tmp_path):
    elections, authorities, _, _, _, _, _, scope, _, _ = cluster(tmp_path)
    elections["A"].select(scope[0])
    jobs = authorities["A"].jobs
    checks = []
    def ready(requested):
        checks.append(requested)
        return len(checks) == 1
    jobs.authority_ready = ready
    with pytest.raises(PermissionError, match="during transaction"):
        jobs.request("B", "raced-grant", scope[0])
    with closing(sqlite3.connect(jobs.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reader_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM reader_job_requests").fetchone()[0] == 0
