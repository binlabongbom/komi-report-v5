from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, UTC
import hashlib
import uuid

import pytest

import database
from database import _open
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.reader_jobs import ReadScope, ReaderJobs, VerifiedReader
from services.web_observations import WebObservationStore, _json
from test_subject_history import _reading


def fixture():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SER-A")])
    now = [100.0]
    scope = [ReadScope("fixture-company", 0, "SER-A", "fixture-settings", "fixture-reviewed-epoch")]
    origins = {member: str(uuid.uuid4()) for member in ("A", "B", "C")}
    def authorize(member, slot):
        if member not in origins or slot != scope[0].slot:
            raise PermissionError("Unknown member")
        return VerifiedReader(member, origins[member], scope[0])
    args = dict(authorize=authorize, current_scope=lambda slot: scope[0], clock=lambda: now[0])
    return ReaderJobs(**args), now, scope, origins, args


def committed_event(job_id, origin):
    store = WebObservationStore()
    event = store.record(0, _reading(100, collected_at=datetime(2026, 9, 18, 10, tzinfo=UTC)),
        serial="SER-A", printer_name="Fixture", read_id=str(uuid.uuid4()))
    # Simulate the already-authorized remote journal import. No membership or
    # Host trust is inferred from this fixture's arbitrary IDs.
    event["payload"]["origin"] = origin
    event["payload"]["read_id"] = job_id
    event["id"] = hashlib.sha256(_json(event["payload"]).encode()).hexdigest()
    store.receive([event], expected_slot=0, expected_serial="SER-A")
    return event["id"]


def test_manual_first_request_reads_and_other_requests_join_committed_web():
    jobs, _, scope, origins, _ = fixture()
    first = jobs.request("B", "manual-1010", scope[0])
    joined = jobs.request("C", "manual-simultaneous", scope[0])
    scheduled = jobs.request("A", "scheduled-1015", scope[0])
    assert first["granted"] and first["can_read"]
    assert first["job_id"] == joined["job_id"] == scheduled["job_id"]
    assert not joined["granted"] and not joined["can_read"] and joined["event_id"] is None
    with pytest.raises(ValueError, match="Committed"):
        jobs.complete("B", first["job_id"], scope[0], event_id="uncommitted")
    event_id = committed_event(first["job_id"], origins["B"])
    completed = jobs.complete("B", first["job_id"], scope[0], event_id=event_id)
    assert completed["phase"] == "complete"
    assert jobs.status("C", first["job_id"], scope[0])["event_id"] == event_id
    assert jobs.complete("B", first["job_id"], scope[0], event_id=event_id) == completed
    assert jobs.request("B", "manual-1010", scope[0])["job_id"] == first["job_id"]
    following = jobs.request("A", "scheduled-1030", scope[0])
    assert following["granted"] and following["job_id"] != first["job_id"]


def test_simultaneous_first_requests_have_one_durable_grant():
    jobs, _, scope, _, _ = fixture()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda member: jobs.request(member, "simultaneous", scope[0]), ("A", "B", "C")))
    assert sum(item["granted"] for item in results) == 1
    assert len({item["job_id"] for item in results}) == 1
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reader_jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM reader_job_requests").fetchone()[0] == 3


def test_lost_reply_retry_returns_original_job_and_permission_to_resume_once():
    jobs, _, scope, _, _ = fixture()
    original = jobs.request("B", "lost-reply", scope[0])
    retry = jobs.request("B", "lost-reply", scope[0])
    assert retry["job_id"] == original["job_id"] and retry["can_read"]
    assert not retry["granted"]  # No second job was created; worker deduplicates by job_id.


def test_dead_reader_expires_and_late_completion_cannot_complete_replacement_job():
    jobs, now, scope, origins, _ = fixture()
    old = jobs.request("A", "scheduled", scope[0], lease_seconds=20)
    now[0] += 20
    new = jobs.request("B", "manual", scope[0])
    assert new["granted"] and new["job_id"] != old["job_id"]
    old_event = committed_event(old["job_id"], origins["A"])
    with pytest.raises(ValueError, match="expired"):
        jobs.complete("A", old["job_id"], scope[0], event_id=old_event)
    with pytest.raises(PermissionError):
        jobs.complete("A", new["job_id"], scope[0], event_id=old_event)
    assert jobs.status("C", new["job_id"], scope[0])["phase"] == "reading"
    assert jobs.status("C", old["job_id"], scope[0])["phase"] == "expired"


def test_authority_restart_does_not_reuse_previous_monotonic_lease():
    old, now, scope, _, args = fixture()
    first = old.request("A", "old-process", scope[0])
    now[0] = 1.0  # A restarted process/OS clock has unrelated monotonic values.
    restarted = ReaderJobs(**args)
    second = restarted.request("B", "new-process", scope[0])
    assert second["granted"] and second["job_id"] != first["job_id"]
    assert restarted.status("C", first["job_id"], scope[0])["phase"] == "expired"
    with pytest.raises(ValueError, match="ownership"):
        old.request("A", "surviving-old-process", scope[0])
    assert restarted.status("C", second["job_id"], scope[0])["phase"] == "reading"


def test_wrong_membership_scope_origin_or_job_cannot_publish_result():
    jobs, _, scope, origins, _ = fixture()
    with pytest.raises(PermissionError):
        jobs.request("unknown", "x", scope[0])
    with pytest.raises(PermissionError):
        jobs.request("A", "x", replace(scope[0], company_id="other-company"))
    with pytest.raises(PermissionError):
        jobs.request("A", "x", replace(scope[0], epoch_id="stale-epoch"))
    first = jobs.request("A", "x", scope[0])
    for origin, job_id in ((origins["B"], first["job_id"]), (origins["A"], "another-job")):
        event_id = committed_event(job_id, origin)
        with pytest.raises(ValueError, match="match"):
            jobs.complete("A", first["job_id"], scope[0], event_id=event_id)
    scope[0] = replace(scope[0], settings_revision="changed")
    with pytest.raises(ValueError, match="reused"):
        jobs.request("A", "x", scope[0])
    next_job = jobs.request("B", "new-scope", scope[0])
    assert next_job["granted"] and next_job["job_id"] != first["job_id"]


def test_failed_read_can_retry_without_fabricating_a_web_event():
    jobs, _, scope, _, _ = fixture()
    first = jobs.request("A", "first", scope[0])
    with pytest.raises(PermissionError):
        jobs.fail("B", first["job_id"], scope[0], reason="web")
    jobs.fail("A", first["job_id"], scope[0], reason="web")
    status = jobs.status("C", first["job_id"], scope[0])
    assert status["phase"] == "failed" and status["event_id"] is None
    assert jobs.request("B", "retry", scope[0])["granted"]


def test_request_and_grant_roll_back_together_and_reset_respects_foreign_keys():
    jobs, _, scope, origins, _ = fixture()
    with _open() as conn:
        conn.execute("CREATE TRIGGER fail_request BEFORE INSERT ON reader_job_requests BEGIN SELECT RAISE(ABORT,'request failed'); END")
    import sqlite3
    with pytest.raises(sqlite3.Error):
        jobs.request("A", "failed", scope[0])
    with _open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reader_jobs").fetchone()[0] == 0
        conn.execute("DROP TRIGGER fail_request")
    job = jobs.request("A", "retry", scope[0])
    event_id = committed_event(job["job_id"], origins["A"])
    jobs.complete("A", job["job_id"], scope[0], event_id=event_id)
    database.reset_usage_data()
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reader_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM web_observations").fetchone()[0] == 0


def test_three_separate_databases_join_one_read_and_receive_only_persisted_web(tmp_path):
    import sqlite3
    from contextlib import closing
    original = database.get_db_path()
    paths, stores, origins = {}, {}, {}
    try:
        for member in ("A", "B", "C"):
            path = tmp_path / member / "fixture.sqlite3"
            path.parent.mkdir()
            database.set_db_path(path)
            database.init_db()
            DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SER-A")])
            origin = str(uuid.uuid4())
            with _open() as conn:
                conn.execute("INSERT INTO web_observation_state VALUES('origin',?)", (origin,))
            paths[member], stores[member], origins[member] = path, WebObservationStore(path), origin
        scope = ReadScope("fixture-company", 0, "SER-A", "same-settings", "same-reviewed-epoch")
        jobs = ReaderJobs(path=paths["A"], authorize=lambda member, slot: VerifiedReader(member, origins[member], scope),
            current_scope=lambda slot: scope)
        first = jobs.request("B", "manual-first", scope)
        joined = jobs.request("C", "manual-second", scope)
        assert joined["job_id"] == first["job_id"] and joined["event_id"] is None
        assert stores["A"].page()["events"] == stores["C"].page()["events"] == []
        event = stores["B"].record(0, _reading(50100, collected_at=datetime(2026, 9, 18, 10, tzinfo=UTC)),
            serial="SER-A", printer_name="Fixture", read_id=first["job_id"])
        with pytest.raises(ValueError, match="Committed"):
            jobs.complete("B", first["job_id"], scope, event_id=event["id"])
        receipts = stores["A"].receive([event], expected_slot=0, expected_serial="SER-A")
        stores["B"].acknowledge("A", receipts)
        jobs.complete("B", first["job_id"], scope, event_id=event["id"])
        assert jobs.status("C", first["job_id"], scope)["event_id"] == event["id"]
        # Authorized transport forwards persisted parsed data, never printer
        # HTML, a whole database, or SNMP status represented as fresh Web.
        received = stores["A"].page()["events"]
        stores["C"].receive(received, expected_slot=0, expected_serial="SER-A")
        stores["C"].receive(received, expected_slot=0, expected_serial="SER-A")
        restarted_c = WebObservationStore(paths["C"])
        assert restarted_c.page()["events"] == stores["B"].page()["events"] == [event]
        assert restarted_c.pending("A") == []  # Incoming data does not become an echo outbox.
        assert stores["B"].pending("A") == []
        with closing(sqlite3.connect(paths["A"])) as conn:
            assert conn.execute("SELECT COUNT(*) FROM reader_jobs").fetchone()[0] == 1
    finally:
        database.set_db_path(original)
