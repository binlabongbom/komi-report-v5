"""Report date-range regressions using real subject aggregation and an isolated DB."""

from datetime import date
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication

import database
from ui.reports import page as report_page
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import MonthlyUsage
from services.subject_history import SubjectDailyCacheStore
from ui.cloud_reports import CloudReportsWidget

CANONICAL = ("2026-09-01", "2026-09-30")
CUSTOM = ("2026-09-03", "2026-09-07")
EMPTY = ("2026-09-12", "2026-09-13")


def _usage(start, end, total, *, cost=0):
    return MonthlyUsage(
        device_slot=0, period_start=start, period_end=end, total=total,
        a3_color=0, a3_bw=0, a4_color=total, a4_bw=0, scan=0,
        gross_cost=cost, net_cost=cost, day_count=1, incomplete_days=0,
    )


@pytest.fixture
def report(tmp_path, monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    repository = DeviceConfigRepository()
    devices = [DeviceConfig(0, "Synthetic printer", "192.0.2.10")]
    repository.replace_all(devices)
    database.set_cfg("billing_day", "31")
    observations = (("2026-09-01", 75), ("2026-09-03", 10), ("2026-09-05", 8), ("2026-09-09", 200))
    with database._open() as connection:
        connection.executemany(
            """INSERT INTO daily_subject_records(
                device_slot,record_date,subject_type,subject_id,subject_name,
                opening_total,closing_total,delta_total,sample_count,created_at
            ) VALUES(0,?,'user','qa-user','Alice QA',0,?,?,2,?)""",
            [(day, total, total, f"{day}T17:00:00+07:00") for day, total in observations],
        )
    daily = tuple(_usage(date.fromisoformat(day), date.fromisoformat(day), total) for day, total in observations)
    monthly = _usage(date(2026, 9, 1), date(2026, 9, 30), 293, cost=42.75)
    usage_reads = []
    subject_reads = []
    subject_loader = report_page.load_subject_history

    def load_usage(*_args, **kwargs):
        usage_reads.append(kwargs.get("granularity"))
        return daily

    def load_subjects(*args, **kwargs):
        subject_reads.append(kwargs)
        return subject_loader(*args, **kwargs)

    monkeypatch.setattr(report_page, "load_usage_history", load_usage)
    monkeypatch.setattr(report_page, "load_subject_history", load_subjects)
    monkeypatch.setattr(report_page, "load_raw_counter_history", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(report_page, "report_slots", lambda: [0])
    cloud = CloudReportsWidget()
    host = SimpleNamespace(
        report_center=cloud,
        _report_records=(monthly,),
        _period_key=report_page.PageHistoryV5._period_key,
        _historical_devices=lambda: devices,
        cache=object(),
        subject_cache=SubjectDailyCacheStore(tmp_path / "subjects"),
    )

    def refresh(selected=None):
        report_page.PageHistoryV5._refresh_report_center(host, selected)

    cloud.period_changed.connect(refresh)
    refresh(CANONICAL)
    yield SimpleNamespace(
        cloud=cloud, refresh=refresh, monthly=monthly,
        usage_reads=usage_reads, subject_reads=subject_reads,
    )
    cloud.close()
    qt_app.processEvents()


def _select_period(cloud, selected):
    cloud.period_start_edit.setDate(QDate.fromString(selected[0], "yyyy-MM-dd"))
    cloud.period_end_edit.setDate(QDate.fromString(selected[1], "yyyy-MM-dd"))


@pytest.mark.parametrize("tab_index", [0, 1])
def test_custom_period_keeps_users_inside_selected_dates(report, tab_index):
    cloud = report.cloud
    cloud.tabs.setCurrentIndex(tab_index)
    _select_period(cloud, CUSTOM)

    assert [(row.subject_name, row.period_usage) for row in cloud._subjects] == [("Alice QA", 18)]
    assert [(row["name"], row["usage"]) for row in cloud._user_rows] == [("Alice QA", 18)]
    assert cloud.current_period() == CUSTOM
    if tab_index == 0:
        assert cloud.overview_users.item(0, 0).text() == "Alice QA"
        assert cloud.overview_users.item(0, 2).text() == "18"
    else:
        assert cloud.users_table.item(0, 12).text() == "18"
    report.refresh()
    assert cloud.current_period() == CUSTOM
    assert cloud._subjects[0].period_usage == 18


@pytest.mark.parametrize("tab_index", [0, 1, 2])
def test_empty_custom_period_clears_data_and_stays_selected(report, tab_index):
    cloud = report.cloud
    cloud.tabs.setCurrentIndex(tab_index)
    _select_period(cloud, EMPTY)
    report.refresh()

    assert cloud.current_period() == EMPTY
    assert cloud._subjects == ()
    assert cloud._records == ()
    assert cloud._user_rows == []
    assert cloud._printer_rows == []


def test_printers_custom_period_loads_daily_but_preserves_canonical_ledger(report):
    cloud = report.cloud
    cloud.tabs.setCurrentIndex(2)
    report.usage_reads.clear()
    report.refresh(CANONICAL)
    assert cloud._records == (report.monthly,)
    assert cloud._printer_rows[0]["cost"] == 42.75
    # The timeline now reads daily evidence even for a canonical month;
    # the visible totals must still come from its posted monthly ledger.
    assert report.usage_reads and set(report.usage_reads) == {"daily"}
    report.usage_reads.clear()

    _select_period(cloud, CUSTOM)
    assert cloud.current_period() == CUSTOM
    assert sum(row.total for row in cloud._records) == 18
    assert cloud._printer_rows[0]["total"] == 18
    assert report.usage_reads and set(report.usage_reads) == {"daily"}


def test_canonical_subject_period_keeps_frozen_aggregation_path(report):
    assert report.cloud._subjects[0].period_usage == 293
    assert all("period_start" not in call and "period_end" not in call for call in report.subject_reads)
