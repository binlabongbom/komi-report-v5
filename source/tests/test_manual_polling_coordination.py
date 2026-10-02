from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from threading import Event
import time as clock_time

from PyQt6.QtWidgets import QApplication

from services.background_polling import BackgroundPollingCoordinator
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.polling import DevicePollState, PollingPolicy, PollingStateMachine, ScheduleWindow
from services.snmp_probe import SnmpTotalProbe
from test_background_polling import FakeProbe, FakeReader


def wait_until(predicate):
    deadline = clock_time.monotonic() + 10
    while not predicate() and clock_time.monotonic() < deadline:
        QApplication.processEvents()
        clock_time.sleep(.005)
    assert predicate()


def coordinator(monkeypatch, *, probe=None, reader=None):
    now = [datetime(2026, 9, 18, 10, tzinfo=UTC)]
    class Reader(FakeReader):
        calls = 0
        def read(self, host):
            self.calls += 1
            return replace(super().read(host), collected_at=now[0].isoformat())
    repository = DeviceConfigRepository()
    device = DeviceConfig(0, "Fixture", "192.0.2.10", serial="SERIAL-1")
    repository.replace_all([device])
    worker = BackgroundPollingCoordinator(repository, probe=probe or FakeProbe(), reader=reader or Reader(), clock=lambda: now[0])
    monkeypatch.setattr(worker, "_preferred_total_oid", lambda _: SnmpTotalProbe.PRIMARY_TOTAL_OID)
    worker.machine = PollingStateMachine(PollingPolicy(schedule_windows=(ScheduleWindow(
        time(8), time(17), timedelta(minutes=15), snmp_interval=timedelta(minutes=5)),)))
    worker.states[0] = DevicePollState(last_snmp_total=101, last_web_at=now[0] - timedelta(minutes=15))
    return worker, device, now


def test_manual_read_adds_point_without_delaying_1015_and_1030(monkeypatch):
    worker, device, now = coordinator(monkeypatch)
    try:
        worker._submit(device, force_web=False)
        wait_until(lambda: not worker.active)
        scheduled = worker.last_poll[0]
        now[0] = now[0].replace(minute=10)
        worker._submit(device, force_web=True)
        wait_until(lambda: not worker.active)
        assert worker.last_poll[0] == scheduled
        assert worker.states[0].last_web_at.minute == 10
        assert worker.states[0].last_scheduled_web_at.minute == 0
        for minute in (15, 30):
            now[0] = now[0].replace(minute=minute)
            worker.tick()
            wait_until(lambda: not worker.active)
        points = worker.observations.page()["events"]
        assert [datetime.fromisoformat(p["payload"]["observed_at"]).strftime("%H:%M") for p in points] == ["10:00", "10:10", "10:15", "10:30"]
        assert worker.reader.calls == 4
    finally:
        worker.stop(wait=True)


def test_manual_requests_promote_inflight_snmp_to_one_web_result(monkeypatch):
    entered, release = Event(), Event()
    class Probe(FakeProbe):
        calls = 0
        def read(self, host):
            self.calls += 1
            entered.set()
            assert release.wait(5)
            return super().read(host)
    worker, device, now = coordinator(monkeypatch, probe=Probe())
    worker.states[0].last_web_at = now[0]
    now[0] += timedelta(minutes=5)
    try:
        worker._submit(device, force_web=False)
        assert entered.wait(5)
        worker.poll_now()
        worker.poll_now()
        release.set()
        wait_until(lambda: not worker.active)
        assert worker.probe.calls == worker.reader.calls == 1
        assert len(worker.observations.page()["events"]) == 1
        assert worker.states[0].last_scheduled_web_at.minute == 0
    finally:
        release.set()
        worker.stop(wait=True)


def test_scheduled_round_joins_manual_job_without_fabricating_an_extra_point(monkeypatch):
    entered, release = Event(), Event()
    class Reader(FakeReader):
        calls = 0
        def read(self, host):
            self.calls += 1
            entered.set()
            assert release.wait(5)
            return super().read(host)
    worker, device, now = coordinator(monkeypatch, reader=Reader())
    worker.states[0].last_web_at = now[0]
    now[0] += timedelta(minutes=10)
    try:
        worker._submit(device, force_web=True)
        assert entered.wait(5)
        now[0] = now[0].replace(minute=15)
        worker._submit(device, force_web=False)
        worker.poll_now()
        release.set()
        wait_until(lambda: not worker.active)
        assert worker.reader.calls == 1
        assert len(worker.observations.page()["events"]) == 1
        assert worker.states[0].last_scheduled_web_at.minute == 15
        assert worker.machine.scheduled_web_due(worker.states[0], now[0].replace(minute=30))
    finally:
        release.set()
        worker.stop(wait=True)


def test_manual_request_at_snmp_skip_boundary_is_not_dropped(monkeypatch):
    entered, release = Event(), Event()
    worker, device, _ = coordinator(monkeypatch)
    calls = []
    def poll(_device, force):
        calls.append(force)
        if not force:
            entered.set()
            assert release.wait(5)
        return force
    monkeypatch.setattr(worker, "_poll_device", poll)
    try:
        worker._submit(device, force_web=False)
        assert entered.wait(5)
        worker.poll_now()
        release.set()
        wait_until(lambda: calls == [False, True] and not worker.active)
    finally:
        release.set()
        worker.stop(wait=True)


def test_manual_only_first_read_does_not_move_the_next_scheduled_baseline():
    machine = PollingStateMachine()
    state = DevicePollState()
    now = datetime(2026, 9, 18, 7, tzinfo=UTC)
    machine.web_success(state, now, scheduled=False)
    assert state.last_web_at == now
    assert state.last_scheduled_web_at is None
    assert machine.scheduled_web_due(state, now + timedelta(minutes=1))


def test_read_crossing_midnight_uses_real_web_day_and_keeps_schedule_anchor(monkeypatch):
    actual = datetime(2026, 9, 19, 0, 1, tzinfo=UTC)
    class Reader(FakeReader):
        def read(self, host):
            return replace(super().read(host), collected_at=actual.isoformat())
    worker, device, now = coordinator(monkeypatch, reader=Reader())
    now[0] = datetime(2026, 9, 18, 23, 59, tzinfo=UTC)
    worker.machine = PollingStateMachine(PollingPolicy(schedule_windows=(ScheduleWindow(
        time(23), time(23, 59), timedelta(minutes=15), snmp_interval=timedelta(minutes=5)),)))
    try:
        assert worker._poll_device(device, force_web=False)
        assert worker.states[0].last_web_at == actual
        assert worker.states[0].last_scheduled_web_at == now[0]
        assert worker.cache.load(0, actual.date())["last_success"] == actual.isoformat(timespec="seconds")
        assert not (worker.cache.load(0, now[0].date()) or {}).get("sample_count")
        assert worker.observations.page()["events"][0]["payload"]["observed_at"] == actual.isoformat()
    finally:
        worker.stop(wait=True)
