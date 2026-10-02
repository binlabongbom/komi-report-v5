from datetime import date
from threading import Event

from services.archive_maintenance import ArchiveMaintenance
from test_web_observation_archive import history


def test_start_is_delayed_and_busy_collection_wins():
    _, _, archive = history()
    busy = [True]
    service = ArchiveMaintenance(archive=archive, busy=lambda: busy[0], today=lambda: date(2026, 9, 18))
    service.start()
    assert service.future is None and service.timer.interval() == 60_000
    service.tick()
    assert service.future is None and archive.list() == []
    busy[0] = False
    service.tick()
    service.future.result(timeout=10)
    assert len(archive.list()) == 1
    service.stop(wait=True)
    service.tick()
    assert not service.timer.isActive()


def test_empty_archive_does_not_poll_files_or_network_every_tick():
    class Archive:
        calls = 0
        def archive_batch(self, **kwargs):
            self.calls += 1
            return None
    archive = Archive()
    service = ArchiveMaintenance(archive=archive, today=lambda: date(2026, 9, 18))
    service.start()
    service.tick()
    service.future.result(timeout=10)
    service.tick()
    assert service.completed_day == date(2026, 9, 18)
    service.tick()
    assert archive.calls == 1
    assert service.timer.interval() == 3_600_000
    service.stop(wait=True)


def test_stop_drains_atomic_chunk_and_never_starts_another():
    entered, release = Event(), Event()
    class Archive:
        def archive_batch(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return {"events": 1}
    service = ArchiveMaintenance(archive=Archive())
    service.start()
    service.tick()
    assert entered.wait(5)
    assert service.stop() == 1
    release.set()
    service.stop(wait=True)
    assert service.future.done()
    service.tick()
    assert not service.timer.isActive()


def test_failure_is_reported_once_then_waits_until_next_day(monkeypatch):
    entries = []
    monkeypatch.setattr("services.pipeline_log.pipeline_log.append", lambda **kw: entries.append(kw))
    class Archive:
        def archive_batch(self, **kwargs):
            raise OSError("fixture full disk")
    service = ArchiveMaintenance(archive=Archive(), today=lambda: date(2026, 9, 18))
    service.start()
    service.tick()
    import pytest
    with pytest.raises(OSError):
        service.future.result(timeout=10)
    service.tick()
    service.tick()
    assert len(entries) == 1 and entries[0]["status"] == "error"
    service.stop(wait=True)
