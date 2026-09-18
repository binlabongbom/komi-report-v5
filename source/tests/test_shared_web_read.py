from concurrent.futures import ThreadPoolExecutor, CancelledError
from contextlib import closing
from dataclasses import replace
from datetime import datetime, UTC
import sqlite3
from threading import Event

import pytest

import database
from services.shared_web_read import SharedWebRead
from services.web_observations import WebObservationStore
from test_reader_election import cluster
from test_subject_history import _reading


def network(tmp_path):
    elections, authorities, clients, online, ready, blocked, calls, scope, now, restart = cluster(tmp_path)
    stores = {member: WebObservationStore(authority.jobs.path) for member, authority in authorities.items()}
    def publish(authority, event, requested):
        return stores[authority].receive([event], expected_slot=requested.slot,
            expected_serial=requested.serial, expected_epoch=requested.epoch_id)
    def fetch(authority, event_id, requested):
        return next(event for event in stores[authority].page()["events"] if event["id"] == event_id)
    runtimes = {member: SharedWebRead(router=client, current_scope=lambda slot: scope[0],
        observations=stores[member], publish=publish, fetch=fetch, wait_seconds=3) for member, client in clients.items()}
    return runtimes, stores, authorities, scope, now


def reading():
    return _reading(301, collected_at=datetime(2026, 9, 18, 10, 10, tzinfo=UTC))


def collect(runtime, *, request_id="manual", read=reading, cancelled=lambda: False):
    return runtime.collect(0, manual=True, request_id=request_id, read=read, printer_name="Fixture", cancelled=cancelled)


def test_concurrent_members_execute_one_web_and_join_only_after_committed_result(tmp_path):
    runtimes, stores, authorities, scope, _ = network(tmp_path)
    entered, release, joined = Event(), Event(), Event()
    calls = []
    def printer():
        calls.append("Web")
        entered.set()
        assert release.wait(5)
        return reading()
    router = runtimes["C"].router
    original = router.request
    def request(*args, **kwargs):
        result = original(*args, **kwargs)
        assert not result.job["can_read"] and result.job["event_id"] is None
        joined.set()
        return result
    router.request = request
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(collect, runtimes["B"], read=printer)
        try:
            assert entered.wait(5)
            second = pool.submit(collect, runtimes["C"], read=lambda: pytest.fail("Joined peer must not read Web"))
            assert joined.wait(5)
            assert len(stores["C"].page()["events"]) == 1  # baseline only, no fabricated result
        finally:
            release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert calls == ["Web"]
    assert a.local and not b.local and a.event == b.event
    assert a.reading == b.reading
    assert all(len(store.page()["events"]) == 2 for store in stores.values())
    assert b.event["id"] not in {event["id"] for event in stores["C"].pending("A")}
    assert a.event["id"] not in {event["id"] for event in stores["B"].pending("A")}
    assert b.event["payload"]["observed_at"] == reading().collected_at
    assert runtimes["A"].scheduled_owner(0)
    assert not runtimes["B"].scheduled_owner(0)


def test_lost_publish_reply_reuses_persisted_event_without_rereading(tmp_path):
    runtimes, stores, _, _, _ = network(tmp_path)
    runtime = runtimes["B"]
    original = runtime.publish
    calls = []
    def lost(*args):
        original(*args)
        raise TimeoutError("Reply lost after authority import")
    runtime.publish = lost
    with pytest.raises(TimeoutError):
        collect(runtime, read=lambda: (calls.append("Web"), reading())[1])
    runtime.publish = original
    result = collect(runtime, read=lambda: pytest.fail("Retry must reuse committed result"))
    assert result.local and calls == ["Web"]
    assert len(stores["B"].page()["events"]) == 2


def test_completed_retry_fetches_same_result_without_new_read(tmp_path):
    runtimes, stores, _, _, _ = network(tmp_path)
    first = collect(runtimes["B"])
    second = collect(runtimes["B"], read=lambda: pytest.fail("Completed job must not reread"))
    assert first.event == second.event
    assert len(stores["B"].page()["events"]) == 2


def test_scope_change_during_web_rejects_commit(tmp_path):
    runtimes, stores, _, scope, _ = network(tmp_path)
    def changed():
        scope[0] = replace(scope[0], settings_revision="changed-in-flight")
        return reading()
    with pytest.raises(PermissionError, match="scope changed"):
        collect(runtimes["B"], read=changed)
    assert len(stores["B"].page()["events"]) == 1


def test_storage_failure_never_publishes_and_preserves_previous_web(tmp_path):
    runtimes, stores, authorities, scope, _ = network(tmp_path)
    store = stores["B"]
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("CREATE TRIGGER broken BEFORE INSERT ON web_observations BEGIN SELECT RAISE(ABORT,'disk failed'); END")
        conn.commit()
    runtimes["B"].publish = lambda *args: pytest.fail("Uncommitted result must not be sent")
    with pytest.raises(sqlite3.Error):
        collect(runtimes["B"])
    assert all(len(store.page()["events"]) == 1 for store in stores.values())


def test_wrong_job_event_is_rejected_before_import(tmp_path):
    runtimes, stores, _, _, _ = network(tmp_path)
    original = collect(runtimes["B"])
    runtimes["B"].fetch = lambda *args: stores["A"].page()["events"][0]  # valid hash, wrong job
    with pytest.raises(ValueError, match="granted job"):
        collect(runtimes["B"], read=lambda: pytest.fail("No new read"))
    assert len(stores["B"].page()["events"]) == 2


def test_wait_is_bounded_and_cancellation_never_reads_or_changes_success(tmp_path):
    runtimes, stores, _, scope, _ = network(tmp_path)
    runtimes["B"].router.request(scope[0], "in-flight", manual=True)
    now = [1.0]
    runtime = runtimes["C"]
    runtime.clock = lambda: now[0]
    runtime.pause = lambda seconds: now.__setitem__(0, now[0] + seconds)
    runtime.wait_seconds = 1
    with pytest.raises(TimeoutError, match="waiting"):
        collect(runtime, read=lambda: pytest.fail("Must join"))
    with pytest.raises(CancelledError):
        collect(runtime, cancelled=lambda: True)
    assert all(len(store.page()["events"]) == 1 for store in stores.values())


def test_polling_worker_uses_shared_web_result_once_and_skips_foreign_schedule(tmp_path, monkeypatch):
    from services.background_polling import BackgroundPollingCoordinator
    from services.device_config import DeviceConfigRepository
    from test_background_polling import FakeProbe, FakeReader
    runtimes, stores, _, _, _ = network(tmp_path)
    original_path = database.get_db_path()
    workers = []
    try:
        database.set_db_path(stores["A"].path)
        class Probe(FakeProbe):
            calls = 0
            def read(self, host):
                self.calls += 1
                return replace(super().read(host), serial="SER-A")
        class Reader(FakeReader):
            calls = 0
            def read(self, host):
                self.calls += 1
                return replace(super().read(host), collected_at="2026-09-18T10:00:00+00:00")
        worker = BackgroundPollingCoordinator(probe=Probe(), reader=Reader(), observations=stores["A"], shared_reads=runtimes["A"])
        workers.append(worker)
        device = DeviceConfigRepository().get(0)
        assert worker._poll_device(device, True)
        assert worker.reader.calls == worker.probe.calls == 1
        assert len(stores["A"].page()["events"]) == 2  # baseline + one result, not a local echo
        database.set_db_path(stores["B"].path)
        secondary = BackgroundPollingCoordinator(probe=Probe(), reader=Reader(), observations=stores["B"], shared_reads=runtimes["B"])
        workers.append(secondary)
        assert not secondary._poll_device(DeviceConfigRepository().get(0), False)
        assert secondary.reader.calls == secondary.probe.calls == 0
    finally:
        for worker in workers:
            worker.stop(wait=True)
        database.set_db_path(original_path)


def test_scheduled_and_manual_points_keep_their_original_times(tmp_path):
    runtimes, stores, _, scope, _ = network(tmp_path)
    result_ids = []
    for member, minute, manual in (("A", 0, False), ("B", 10, True), ("A", 15, False), ("A", 30, False)):
        result = runtimes[member].collect(0, manual=manual, request_id=f"at-{minute}",
            read=lambda m=minute: _reading(1000 + m, collected_at=datetime(2026, 9, 18, 10, m, tzinfo=UTC)),
            printer_name="Fixture")
        result_ids.append(result.event["id"])
    actual = [event for event in stores["A"].page()["events"] if event["id"] in result_ids]
    assert [datetime.fromisoformat(event["payload"]["observed_at"]).strftime("%H:%M") for event in actual] == ["10:00", "10:10", "10:15", "10:30"]
    assert runtimes["A"].router.election.owner(scope[0]) == "A"


def test_invalid_receipt_keeps_evidence_pending_without_completing_job(tmp_path):
    runtimes, stores, authorities, scope, _ = network(tmp_path)
    runtimes["B"].publish = lambda *args: ["unrelated-event"]
    with pytest.raises(ValueError, match="acknowledge"):
        collect(runtimes["B"])
    event = stores["B"].page()["events"][-1]
    assert event in stores["B"].pending("A")
    status = authorities["A"].status("B", event["payload"]["read_id"], scope[0])
    assert status["phase"] == "reading" and status["event_id"] is None


def test_revoked_membership_after_publish_cannot_ack_or_complete(tmp_path):
    runtimes, stores, authorities, scope, _ = network(tmp_path)
    runtime = runtimes["B"]
    publish = runtime.publish
    def revoke(*args):
        receipts = publish(*args)
        runtime.router.election.authorize = lambda *args: None
        return receipts
    runtime.publish = revoke
    with pytest.raises(PermissionError):
        collect(runtime)
    event = stores["B"].page()["events"][-1]
    assert event in stores["B"].pending("A")
    assert authorities["A"].status("B", event["payload"]["read_id"], scope[0])["phase"] == "reading"


def test_invalid_can_read_response_cannot_trigger_printer_access(tmp_path):
    runtimes, stores, _, scope, _ = network(tmp_path)
    runtime = runtimes["B"]
    request = runtime.router.request
    def corrupt(*args, **kwargs):
        routed = request(*args, **kwargs)
        return replace(routed, job={**routed.job, "reader_id": "C"})
    runtime.router.request = corrupt
    with pytest.raises(ValueError, match="Inconsistent"):
        collect(runtime, read=lambda: pytest.fail("Unvalidated grant must not read"))
    assert len(stores["B"].page()["events"]) == 1


def test_expired_job_never_returns_old_web_as_new_success(tmp_path):
    runtimes, stores, _, scope, now = network(tmp_path)
    runtimes["B"].router.request(scope[0], "in-flight", manual=True)
    runtimes["C"].pause = lambda seconds: now.__setitem__(0, now[0] + 120)
    with pytest.raises(RuntimeError, match="failed or expired"):
        collect(runtimes["C"], read=lambda: pytest.fail("Joined job cannot start a read"))
    assert len(stores["C"].page()["events"]) == 1


def test_joined_manual_polling_worker_skips_both_snmp_and_web(tmp_path):
    from services.background_polling import BackgroundPollingCoordinator
    from services.device_config import DeviceConfigRepository
    from test_background_polling import FakeReader
    runtimes, stores, _, _, _ = network(tmp_path)
    original_path = database.get_db_path()
    entered, release, joined = Event(), Event(), Event()
    worker = None
    def printer():
        entered.set()
        assert release.wait(5)
        return replace(FakeReader().read("192.0.2.10"), collected_at="2026-09-18T10:10:00+00:00")
    class NoPrinterAccess:
        def read(self, *args, **kwargs):
            pytest.fail("Joined member must not contact the printer")
    prepare = runtimes["C"].prepare
    def prepared(*args, **kwargs):
        result = prepare(*args, **kwargs)
        assert not result.job["can_read"]
        joined.set()
        return result
    runtimes["C"].prepare = prepared
    try:
        database.set_db_path(stores["C"].path)
        worker = BackgroundPollingCoordinator(probe=NoPrinterAccess(), reader=NoPrinterAccess(),
            observations=stores["C"], shared_reads=runtimes["C"],
            clock=lambda: datetime(2026, 9, 18, 10, 10, tzinfo=UTC))
        device = DeviceConfigRepository().get(0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(collect, runtimes["B"], read=printer)
            try:
                assert entered.wait(5)
                waiting = pool.submit(worker._poll_device, device, True)
                assert joined.wait(5)
            finally:
                release.set()
            result = first.result(timeout=5)
            assert waiting.result(timeout=5)
        assert worker.states[0].last_web_at.isoformat() == result.reading.collected_at
        assert worker.states[0].last_scheduled_web_at is None
        assert len(stores["C"].page()["events"]) == 2
    finally:
        release.set()
        if worker:
            worker.stop(wait=True)
        database.set_db_path(original_path)
