"""Behavioral Mac QA for V5.2.8; synthetic data and no device access."""

from datetime import date, datetime

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import database
from app import MainWindow
from komi_snmp_profiler.connectors import TlsPolicy
from komi_snmp_profiler.credential_store import SessionCredentialStore
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.meter_export import MeterExportTable
from komi_snmp_profiler.models import WebCounterValue
from services import summary_service
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import MonthlyUsage
from services.subject_history import SubjectPeriodUsage


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    view = MainWindow()
    view.show()
    yield view
    view._quitting = True
    view.close()
    app.processEvents()


def test_deferred_navigation_loads_all_pages_after_event_loop(window):
    from pages import PageManual
    from v5_pages import PageHistoryV5, PageSettingsV5

    for index, expected in zip((2, 3, 4), (PageHistoryV5, PageSettingsV5, PageManual), strict=True):
        window._nav(window.nav_btns[index])
        QTest.qWait(250)
        assert window.stack.currentIndex() == index
        assert isinstance(window._page_widgets[index], expected)


def test_settings_draft_survives_async_navigation(window, monkeypatch):
    import app as app_module

    window._nav(window.nav_btns[window._settings_index])
    QTest.qWait(250)
    settings = window.pg_settings
    settings.fleet_content._set_active_editor("billing")
    settings.fleet_content.waste.setValue(8.5)
    replies = iter((app_module.QMessageBox.StandardButton.No, app_module.QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(app_module.QMessageBox, "question", lambda *args, **kwargs: next(replies))
    window._nav(window.nav_btns[0])
    assert window.stack.currentIndex() == window._settings_index
    window._nav(window.nav_btns[0])
    QTest.qWait(250)
    assert window.stack.currentIndex() == 0
    assert settings.has_unsaved_changes()
    assert settings.fleet_content.waste.value() == 8.5
    settings.discard_unsaved_changes()


def test_rapid_report_tabs_coalesce_and_recover_after_error(window, monkeypatch):
    window._nav(window.nav_btns[2])
    QTest.qWait(300)
    page = window.pg_history
    original = page._refresh_report_center
    calls = []

    def counted_refresh():
        calls.append(page.report_center_tabs.currentIndex())
        original()

    monkeypatch.setattr(page, "_refresh_report_center", counted_refresh)
    for index in (4, 0, 1, 3, 2, 0, 1):
        page.report_center_tabs.setCurrentIndex(index)
    QTest.qWait(400)
    assert calls == [1]
    assert page.reports_error.isHidden()
    assert not page._report_refresh_busy

    def failed_refresh():
        raise RuntimeError("synthetic QA error")

    monkeypatch.setattr(page, "_refresh_report_center", failed_refresh)
    page.refresh_visible()
    assert "synthetic QA error" in page.reports_error.text()
    assert not page._report_refresh_busy
    monkeypatch.setattr(page, "_refresh_report_center", original)
    page.refresh_visible()
    assert page.reports_error.isHidden()


@pytest.mark.parametrize("subject_id", ["1", "001"])
def test_numeric_placeholder_enriches_without_changing_counter(subject_id):
    class Export:
        def read(self, host, kind):
            return MeterExportTable(kind, ("User Name", "Total"), (("Alice QA", "100"),), "", "utf-16", "\t")

    counter = WebCounterValue(
        canonical_field="user_total", label="User Total", count=100,
        category="user", source_path="synthetic", subject_type="user",
        subject_id=subject_id, subject_name="1",
    )
    reader = MeterReader(SessionCredentialStore(), export_reader=Export())
    counters, warnings = reader._enrich_subject_names("192.0.2.10", [counter], TlsPolicy())
    assert warnings == []
    assert counters[0].count == 100
    assert counters[0].subject_id == subject_id
    assert counters[0].subject_name == "Alice QA"


@pytest.mark.parametrize("names", [("39", "Alice QA"), ("Alice QA", "39"), ("²", "Alice QA")])
def test_top_users_resolves_name_and_preserves_total(names, monkeypatch):
    DeviceConfigRepository().replace_all([DeviceConfig(0, "QA Printer", "192.0.2.10", serial="QA-001")])
    database.set_cfg("billing_day", "31")
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    usage = MonthlyUsage(0, start, end, 30, 0, 0, 0, 30, 0, 3, 3, 2, 0, device_identity="serial:QA-001")
    subjects = tuple(
        SubjectPeriodUsage(
            device_slot=0, period_start=start, period_end=end, subject_type="user",
            subject_id="39", subject_name=name, latest_total=100 + index * 20,
            period_usage=10 + index * 10, reset_count=0, missing_baseline_days=0,
            incomplete_days=0, sample_count=2, latest_at=None, warnings=(),
            device_identity="serial:QA-001",
        )
        for index, name in enumerate(names)
    )
    monkeypatch.setattr(summary_service, "load_usage_history", lambda *args, **kwargs: (usage,))
    monkeypatch.setattr(summary_service, "load_subject_history", lambda *args, **kwargs: subjects)
    result = summary_service._build_v5_overview_summary("all", now=datetime(2026, 9, 7))
    expected_name = "²" if names[0] == "²" else "Alice QA"
    assert result["top_users"] == [(expected_name, 0.0, 0.0, 30)]


@pytest.mark.parametrize("tab_index", range(5))
def test_excel_export_available_from_every_report_tab(window, monkeypatch, tmp_path, tab_index):
    from openpyxl import load_workbook
    from PyQt6.QtCore import QDate

    import v5_pages

    period_start, period_end = date(2026, 9, 1), date(2026, 9, 30)
    start, end = date(2026, 9, 3), date(2026, 9, 7)
    monthly = MonthlyUsage(0, period_start, period_end, 375, 0, 0, 0, 375, 0, 10, 10, 3, 0)
    daily = tuple(
        MonthlyUsage(0, day, day, total, 0, 0, 0, total, 0, 10, 10, 1, 0)
        for day, total in ((period_start, 75), (start, 100), (date(2026, 9, 9), 200))
    )
    reads = []

    def load_usage(*_args, **kwargs):
        reads.append(kwargs.get("granularity"))
        return daily if kwargs.get("granularity") == "daily" else (monthly,)

    monkeypatch.setattr(v5_pages, "load_usage_history", load_usage)
    window._nav(window.nav_btns[2])
    QTest.qWait(300)
    page = window.pg_history
    page.refresh_visible()
    page.report_center_tabs.setCurrentIndex(tab_index)
    QTest.qWait(300)
    reads_before_date_change = reads.count("daily")
    page.report_center.period_start_edit.setDate(QDate(start.year, start.month, start.day))
    page.report_center.period_end_edit.setDate(QDate(end.year, end.month, end.day))
    if tab_index in {1, 4}:
        assert reads.count("daily") == reads_before_date_change
    output = tmp_path / "qa-export.xlsx"
    messages = []
    dialog_defaults = []

    def choose_range(_parent, default_start, default_end, **kwargs):
        dialog_defaults.append((default_start, default_end))
        assert kwargs["available_start"] == period_start
        assert kwargs["available_end"] == date(2026, 9, 9)
        return start, end

    monkeypatch.setattr(v5_pages.ReportExportPeriodDialog, "get_range", choose_range)
    monkeypatch.setattr(v5_pages.QFileDialog, "getSaveFileName", lambda *a, **k: (str(output), ""))
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(v5_pages.QMessageBox, kind, lambda *a, **k: messages.append(a[2]))
    daily_reads_before_export = reads.count("daily")
    page._export_report_center_excel()
    assert reads.count("daily") == daily_reads_before_export + 1
    assert dialog_defaults == [(start, end)]
    assert output.is_file(), messages
    workbook = load_workbook(output)
    # 75 pages before the chosen range and 200 pages after it must be excluded.
    assert workbook.worksheets[0]["Y5"].value == 100
    workbook.close()


def test_excel_export_reports_daily_history_read_failure(monkeypatch):
    from types import SimpleNamespace

    import v5_pages

    def failed_read(*_args, **_kwargs):
        raise RuntimeError("synthetic read failure")

    monkeypatch.setattr(v5_pages, "load_usage_history", failed_read)
    monkeypatch.setattr(v5_pages, "report_slots", lambda: [0])
    monkeypatch.setattr(
        v5_pages.ReportExportPeriodDialog, "get_range",
        lambda *_args, **_kwargs: pytest.fail("Do not open export dialogs after a failed read"),
    )
    errors = []
    monkeypatch.setattr(v5_pages.QMessageBox, "critical", lambda _parent, title, message: errors.append((title, message)))
    view = SimpleNamespace(report_center=object(), cache=object())
    v5_pages.PageHistoryV5._export_report_center_excel(view)
    assert len(errors) == 1
    assert errors[0][0] == "Export ไม่สำเร็จ"
    assert "synthetic read failure" in errors[0][1]
