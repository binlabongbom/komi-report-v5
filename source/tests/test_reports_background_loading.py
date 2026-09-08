from __future__ import annotations

import os
from threading import Event
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

import database
import v5_pages
from services.report_snapshot import ReportSnapshot

_APP = None


@pytest.fixture
def page(tmp_path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    old = database.get_db_path()
    database.set_db_path(tmp_path / "qa.db")
    database.init_db()
    widget = v5_pages.PageHistoryV5(staged=True)
    widget.resize(1100, 750)
    widget.show()
    yield widget
    widget.shutdown_report_loading()
    widget.close()
    _APP.processEvents()
    database.set_db_path(old)


def snapshot(marker="2026-09-08T12:00:00", period=("2026-09-01", "2026-09-30")):
    return ReportSnapshot((period,), dict(
        records=(), daily_records=(), usage_daily_records=(), monthly_records=(),
        subjects=(), devices=(), legacy_history=(), raw_counter_records=(),
        usage_meter_baselines=(), period=period, last_sync_at=marker,
    ))


def wait_until(predicate, timeout=2):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def test_first_shell_defers_legacy_and_menu_stays_responsive(page, monkeypatch):
    started, release = Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        release.wait(2)
        return snapshot()

    monkeypatch.setattr(v5_pages, "load_report_snapshot", slow)
    assert not hasattr(page, "plot_widget")
    assert not hasattr(page, "report_profile_combo")
    page.prepare_overview()
    wait_until(started.is_set)
    assert not page.report_center.has_data
    clicked = []
    button = QPushButton("Menu")
    button.clicked.connect(lambda: clicked.append(True))
    button.click()
    QTest.qWait(40)
    assert clicked
    assert not page.report_center.has_data
    release.set()
    wait_until(lambda: page.report_center.has_data)


def test_refresh_keeps_old_snapshot_and_ignores_stale_result(page, monkeypatch):
    monkeypatch.setattr(v5_pages, "load_report_snapshot", lambda *a, **kw: snapshot())
    page.prepare_overview()
    wait_until(lambda: page.report_center.has_data)
    blocked, release = Event(), Event()

    def stale(*args, **kwargs):
        blocked.set()
        release.wait(2)
        return snapshot("2026-09-08T10:00:00")

    monkeypatch.setattr(v5_pages, "load_report_snapshot", stale)
    page.refresh_visible()
    wait_until(blocked.is_set)
    assert page.report_center.has_data
    monkeypatch.setattr(v5_pages, "load_report_snapshot", lambda *a, **kw: snapshot("2026-09-08T14:00:00"))
    page.refresh_visible()
    wait_until(lambda: "14:00" in page.report_center.updated_label.text())
    release.set()
    QTest.qWait(80)
    assert "14:00" in page.report_center.updated_label.text()


def test_prewarm_does_not_select_tabs_and_cached_navigation_avoids_read(page, monkeypatch):
    reads = []
    def load(index, *args, **kwargs):
        reads.append(index)
        return snapshot()
    monkeypatch.setattr(v5_pages, "load_report_snapshot", load)
    page.prepare_overview()
    wait_until(lambda: page.report_center.has_data)
    page.prewarm_tab(1)
    wait_until(lambda: any(key[0] == 1 for key in page._snapshot_cache))
    assert page.report_center.tabs.currentIndex() == 0
    page.report_center.tabs.setCurrentIndex(1)
    page.refresh_visible_cached()
    QTest.qWait(180)
    assert page.report_center.has_data
    assert reads.count(1) == 1
    page.invalidate_data()
    page.refresh_visible_cached()
    wait_until(lambda: reads.count(1) == 2)


def test_failed_read_stops_loading_and_retry_succeeds(page, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("synthetic read failure")
    monkeypatch.setattr(v5_pages, "load_report_snapshot", fail)
    page.prepare_overview()
    wait_until(lambda: not page.report_center.error_label.isHidden())
    assert "synthetic read failure" in page.report_center.error_label.text()
    monkeypatch.setattr(v5_pages, "load_report_snapshot", lambda *a, **kw: snapshot())
    page.refresh_visible()
    wait_until(lambda: page.report_center.has_data)
    assert page.report_center.error_label.isHidden()


def test_database_switch_refreshes_cache_roots_before_background_reads(page, tmp_path):
    folder=tmp_path/'other';folder.mkdir()
    database.set_db_path(folder/'new.db');database.init_db()
    page.invalidate_data()
    assert str(page.cache.root).startswith(str(folder))
    assert str(page.subject_cache.root).startswith(str(folder))


def test_new_period_keeps_explicit_old_period_notice_until_loaded(page, monkeypatch):
    monkeypatch.setattr(v5_pages,"load_report_snapshot",lambda *a,**kw:snapshot())
    page.prepare_overview();wait_until(lambda:page.report_center.has_data)
    release=Event()
    def slow(index,period,**kwargs):
        release.wait(2)
        return snapshot(period=period)
    monkeypatch.setattr(v5_pages,"load_report_snapshot",slow)
    from PyQt6.QtCore import QDate
    page.report_center.period_edit_pairs[0][0].setDate(QDate(2026,9,5))
    assert not page.report_center.error_label.isHidden()
    assert "2026-09-01" in page.report_center.error_label.text()
    release.set()
    wait_until(lambda: page.report_center.error_label.isHidden())
