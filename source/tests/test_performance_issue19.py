"""Correctness and lifecycle checks for bounded background report reads."""
from datetime import date
from threading import Event, get_ident
from time import monotonic
from types import SimpleNamespace

import database
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget
from ui.background_read import LatestRead


def wait_until(predicate, seconds=5):
    deadline = monotonic() + seconds
    while not predicate() and monotonic() < deadline:
        QTest.qWait(5)
    assert predicate()


def test_latest_read_keeps_ui_responsive_and_discards_replaced_result():
    root = QWidget()
    reader = LatestRead(root)
    gate, started = Event(), Event()
    results, threads, beats = [], [], []
    timer = QTimer(root)
    timer.timeout.connect(lambda: beats.append(True))
    timer.start(10)
    reader.ready.connect(results.append)
    def old():
        threads.append(get_ident())
        started.set()
        assert gate.wait(3)
        return "old"
    try:
        reader.request(old)
        wait_until(started.is_set)
        QTest.qWait(70)
        assert len(beats) >= 3
        assert threads == [threads[0]] and threads[0] != get_ident()
        reader.request(lambda: "new")
        gate.set()
        wait_until(lambda: results == ["new"])
    finally:
        gate.set()
        reader.shutdown()


def test_worker_database_is_pinned_and_old_database_result_is_not_emitted(tmp_path):
    root = QWidget()
    reader = LatestRead(root)
    database.set_cfg("company_name", "first")
    path = database.get_db_path()
    gate, started = Event(), Event()
    actual, results = [], []
    reader.ready.connect(results.append)
    def read():
        started.set()
        assert gate.wait(3)
        actual.append(database.get_cfg("company_name"))
        return actual[-1]
    try:
        reader.request(read)
        wait_until(started.is_set)
        database.set_db_path(tmp_path / "other.db")
        database.init_db()
        database.set_cfg("company_name", "second")
        gate.set()
        wait_until(lambda: not reader.busy)
        assert actual == ["first"]
        assert results == []
    finally:
        gate.set()
        reader.shutdown()
        database.set_db_path(path)


def test_cancel_interrupts_a_long_sql_query_and_does_not_deliver_error():
    root = QWidget()
    reader = LatestRead(root)
    started = Event()
    results = []
    reader.ready.connect(results.append)
    reader.failed.connect(results.append)
    def read():
        with database._open(commit=False) as connection:
            started.set()
            return connection.execute("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n").fetchone()
    reader.request(read)
    wait_until(started.is_set)
    reader.cancel()
    wait_until(lambda: not reader._resources.jobs)
    assert results == []
    reader.shutdown()


def test_archive_metadata_is_lazy_and_error_never_looks_like_zero():
    from ui.archive_settings import ArchiveSettingsPanel
    calls = []
    def stats(**_):
        calls.append(get_ident())
        if len(calls) == 1:
            raise OSError("fixture metadata error")
        return dict(eligible=7, archived=12, files=2)
    panel = ArchiveSettingsPanel(archive=SimpleNamespace(stats=stats))
    assert calls == []
    assert not panel.start_button.isEnabled()
    panel.refresh()
    wait_until(lambda: not panel.metadata_reader.busy)
    assert "ไม่สำเร็จ" in panel.status.text()
    assert "0" not in panel.status.text()
    assert not panel.start_button.isEnabled()
    panel.refresh(force=True)
    wait_until(lambda: not panel.metadata_reader.busy)
    assert panel.start_button.isEnabled()
    assert "7" in panel.status.text()
    panel.refresh()
    assert len(calls) == 2  # same database revision uses the completed metadata
    database.set_cfg("fixture_revision", "changed")
    panel.refresh()
    wait_until(lambda: not panel.metadata_reader.busy)
    assert len(calls) == 3
    assert all(thread != get_ident() for thread in calls)
    panel.metadata_reader.shutdown()


def test_canonical_subject_periods_match_full_history_hot_and_archive(monkeypatch):
    from contextlib import contextmanager
    from services import subject_history
    from test_report_detail_archive import fixture, archive_all
    from services.subject_history import load_subject_history
    from services.report_detail_archive import ReportDetailArchive, TABLES, _anchor_condition
    _, _, archive = fixture()
    original = load_subject_history([0])
    periods = tuple(sorted({(r.period_start, r.period_end) for r in original})[:2])
    expected = tuple(r for r in original if (r.period_start, r.period_end) in periods)
    statements = []
    original_open = subject_history._open
    @contextmanager
    def traced_open(*args, **kwargs):
        with original_open(*args, **kwargs) as connection:
            connection.set_trace_callback(statements.append)
            yield connection
    monkeypatch.setattr(subject_history, '_open', traced_open)
    with database._open(commit=False) as connection:
        old_count = sum(connection.execute(f"SELECT COUNT(*) FROM {table} r WHERE r.record_date<? AND {_anchor_condition(kind)}", ("2025-09-18",)).fetchone()[0] for kind, table in TABLES.items())
    assert archive.stats(today=date(2026, 9, 18))["eligible"] == old_count
    assert load_subject_history([0], only_periods=periods) == expected
    subject_queries = [sql for sql in statements if 'FROM daily_subject_records WHERE' in sql]
    assert len(subject_queries) == 1
    assert f"record_date>='{min(p[0] for p in periods).isoformat()}'" in subject_queries[0].replace(' ', '')
    assert f"record_date<='{max(p[1] for p in periods).isoformat()}'" in subject_queries[0].replace(' ', '')
    archive_all(archive)
    monkeypatch.setattr(ReportDetailArchive, "_file", lambda *_: (_ for _ in ()).throw(AssertionError("Monthly view opened cold details")))
    assert load_subject_history([0], only_periods=periods) == expected
    assert load_subject_history([0], only_periods=()) == ()


def test_hidden_settings_do_not_poll_network_and_cancel_pending_status(monkeypatch):
    from v5_pages import PageSettingsV5
    from pages import PageSettings
    from services.web_service import WebServiceStatus
    settings = PageSettingsV5(PageSettings())
    page = settings.fleet_content
    gate, started = Event(), Event()
    calls = []
    def blocked():
        calls.append(get_ident())
        started.set()
        assert gate.wait(3)
        return WebServiceStatus('stopped', 'http://127.0.0.1:3000', 'http://192.0.2.10:3000', 'fixture', database.get_db_path().with_suffix('.log'))
    monkeypatch.setattr(page.web_service, 'status', blocked)
    assert not page._web_status_timer.isActive()
    page._refresh_web_status()
    assert calls == []
    try:
        settings.show()
        network_tab = next(i for i in range(settings.section_tabs.count())
                           if settings.section_tabs.tabText(i) == "การตั้งค่าเครือข่าย")
        settings.section_tabs.setCurrentIndex(network_tab)
        wait_until(started.is_set)
        assert calls[0] != get_ident()
        before = page.web_service_status.text()
        settings.hide()
        wait_until(lambda: not page._web_status_timer.isActive())
        assert not page._web_status_timer.isActive()
        gate.set()
        wait_until(lambda: not page._web_status_reader._resources.jobs)
        assert page.web_service_status.text() == before
    finally:
        gate.set()
        page._web_status_reader.shutdown()
        settings.close()


def test_overview_failure_offers_retry_and_close_discards_pending(monkeypatch):
    from ui.pages import overview as overview_page
    from services.summary_service import build_overview_summary
    page = overview_page.PageOverview(lambda: [])
    monkeypatch.setattr(overview_page, 'build_overview_summary', lambda *_: (_ for _ in ()).throw(OSError('fixture')))
    page.refresh()
    wait_until(lambda: not page.summary_reader.busy)
    assert not page.overview_retry.isHidden()
    monkeypatch.setattr(overview_page, 'build_overview_summary', build_overview_summary)
    page.overview_retry.click()
    wait_until(lambda: not page.summary_reader.busy)
    assert page.overview_retry.isHidden()
    started, gate = Event(), Event()
    def blocked(*_):
        started.set()
        gate.wait(3)
        return {'top_users': []}
    monkeypatch.setattr(overview_page, 'build_overview_summary', blocked)
    page.refresh()
    wait_until(started.is_set)
    before = page.overview_status.text()
    page.close()
    gate.set()
    wait_until(lambda: not page.summary_reader._resources.jobs)
    assert page.overview_status.text() == before
    page.summary_reader.shutdown()


def test_reparented_network_card_restarts_status_checks(monkeypatch):
    from v5_pages import PageSettingsV5
    from pages import PageSettings
    page = PageSettingsV5(PageSettings())
    fleet = page.fleet_content
    calls = []
    monkeypatch.setattr(fleet._web_status_reader, 'request', lambda *_: calls.append(True))
    page.show()
    network_tab = next(i for i in range(page.section_tabs.count())
                       if page.section_tabs.tabText(i) == "การตั้งค่าเครือข่าย")
    page.section_tabs.setCurrentIndex(network_tab)
    wait_until(lambda: calls)
    assert not fleet.isVisible() and fleet.web_service_status.isVisible()
    assert fleet._web_status_timer.isActive()
    page.close()
    wait_until(lambda: not fleet._web_status_timer.isActive())
    fleet._web_status_reader.shutdown()
