from concurrent.futures import Future
from datetime import date
from PyQt6.QtTest import QTest

from ui.archive_settings import ArchiveSettingsPanel
from test_web_observation_archive import history


def ready(panel):
    panel.refresh()
    for _ in range(400):
        if not panel.metadata_reader.busy:
            return
        QTest.qWait(5)
    raise AssertionError("Metadata read did not finish")


def test_metadata_panel_never_opens_archive_files(monkeypatch):
    _, _, archive = history()
    monkeypatch.setattr(archive, "read_document", lambda *_: (_ for _ in ()).throw(AssertionError("eager load")))
    panel = ArchiveSettingsPanel(archive=archive, today=date(2026, 9, 18))
    ready(panel)
    assert panel.start_button.isEnabled()
    assert "3" in panel.status.text()
    assert panel.pool is None


def test_completed_background_job_updates_counts_without_second_worker():
    _, _, archive = history()
    panel = ArchiveSettingsPanel(archive=archive, today=date(2026, 9, 18))
    ready(panel)
    panel.start()
    first = panel.future
    panel.start()
    assert panel.future is first
    first.result(timeout=10)
    panel._collect()
    ready(panel)
    assert panel.future is None
    assert not panel.start_button.isEnabled()
    assert not panel.cancel_button.isEnabled()
    panel.pool.shutdown(wait=True)


def test_error_remains_visible_and_can_retry():
    _, _, archive = history()
    panel = ArchiveSettingsPanel(archive=archive, today=date(2026, 9, 18))
    panel.future = Future()
    panel.future.set_exception(OSError("fixture disk full"))
    panel._collect()
    ready(panel)
    assert panel.message.text()
    assert panel.start_button.isEnabled()
    assert archive.stats(today=date(2026, 9, 18))["eligible"] == 3
