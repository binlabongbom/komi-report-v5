import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

from PyQt6.QtWidgets import QApplication

import database
from ui.reports import page as report_page
from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.subject_history import SubjectPeriodUsage
from ui.reports.page import PageHistoryV5


class _Repository:
    def list(self, *, enabled_only: bool = False):
        return [DeviceConfig(0, "Office", "192.0.2.10", connection_status="online")]


class _ThreeDeviceRepository:
    def list(self, *, enabled_only: bool = False):
        return [
            DeviceConfig(slot, name, f"192.0.2.{slot + 10}", connection_status="online")
            for slot, name in enumerate(("DMS Printer", "Sales Printer", "HR Printer"))
        ]


class _RolloverRepository:
    def list(self, *, enabled_only: bool = False):
        return [
            DeviceConfig(
                0,
                "Printer B",
                "192.0.2.20",
                serial="SER-B",
                connection_status="online",
            )
        ]


class _EmptyCache:
    def load(self, slot: int, day: date):
        return None


def _subject(
    *,
    usage: float,
    resets: int = 0,
    slot: int = 0,
    subject_id: str = "u-1",
    name: str = "alice",
    identity: str = "",
    device_name: str = "",
    serial: str = "",
) -> SubjectPeriodUsage:
    return SubjectPeriodUsage(
        device_slot=slot,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        subject_type="user",
        subject_id=subject_id,
        subject_name=name,
        latest_total=125,
        period_usage=usage,
        reset_count=resets,
        missing_baseline_days=0,
        incomplete_days=0,
        sample_count=3,
        latest_at="2026-07-16T10:00:00+07:00",
        warnings=(),
        device_identity=identity,
        device_name_snapshot=device_name,
        device_serial_snapshot=serial,
    )


def _monthly(
    total: float,
    *,
    slot: int = 0,
    identity: str = "",
    device_name: str = "",
    serial: str = "",
) -> MonthlyUsage:
    return MonthlyUsage(
        device_slot=slot,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        total=total,
        a3_color=0,
        a3_bw=0,
        a4_color=0,
        a4_bw=0,
        scan=0,
        gross_cost=0,
        net_cost=0,
        day_count=1,
        incomplete_days=0,
        device_identity=identity,
        device_name_snapshot=device_name,
        device_serial_snapshot=serial,
    )


def test_history_users_shows_exact_totals_without_cost_or_estimated_size(tmp_path, monkeypatch):
    original = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-users.sqlite3")
        database.init_db()
        monkeypatch.setattr(report_page, "load_subject_history", lambda slots, cache: (_subject(usage=25),))
        monkeypatch.setattr(report_page, "load_monthly_usage", lambda slots, cache: (_monthly(100),))
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(
            repository=_Repository(),
            cache=_EmptyCache(),
            subject_cache=_EmptyCache(),
        )

        page._populate_month_dropdown_users(0)

        headers = [page.tbl_users.horizontalHeaderItem(index).text() for index in range(page.tbl_users.columnCount())]
        assert headers == ["User / Account", "Office", "รวมทุกเครื่อง"]
        assert not any("ค่าใช้จ่าย" in header or "A3" in header or "A4" in header for header in headers)
        assert page.tbl_users.item(0, 0).text() == "alice"
        assert page.tbl_users.item(0, 1).text() == "25"
        assert page.tbl_users.item(0, 2).text() == "25"
        assert "Total Counter ล่าสุด: 125" in page.tbl_users.item(0, 1).toolTip()
        assert "สถานะ: OK" in page.tbl_users.item(0, 1).toolTip()
        assert "Coverage 25.0%" in page.users_reconciliation.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_history_users_warns_when_subject_sum_exceeds_device_meter(tmp_path, monkeypatch):
    original = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-users-warning.sqlite3")
        database.init_db()
        monkeypatch.setattr(report_page, "load_subject_history", lambda slots, cache: (_subject(usage=120),))
        monkeypatch.setattr(report_page, "load_monthly_usage", lambda slots, cache: (_monthly(100),))
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(
            repository=_Repository(),
            cache=_EmptyCache(),
            subject_cache=_EmptyCache(),
        )

        page._populate_month_dropdown_users(0)

        assert "Needs Review" in page.users_reconciliation.text()
        assert "มากกว่า Device Meter 100" in page.users_reconciliation.text()
        assert "(+20)" in page.users_reconciliation.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_history_users_exposes_counter_reset_in_row_and_banner(tmp_path, monkeypatch):
    original = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-users-reset.sqlite3")
        database.init_db()
        monkeypatch.setattr(
            report_page,
            "load_subject_history",
            lambda slots, cache: (_subject(usage=30, resets=1),),
        )
        monkeypatch.setattr(report_page, "load_monthly_usage", lambda slots, cache: (_monthly(100),))
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(
            repository=_Repository(),
            cache=_EmptyCache(),
            subject_cache=_EmptyCache(),
        )

        page._populate_month_dropdown_users(0)

        assert "Needs Review · reset 1" in page.tbl_users.item(0, 1).toolTip()
        assert "alice: reset 1" in page.users_reconciliation.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_history_users_pivots_one_user_across_three_machine_columns(tmp_path, monkeypatch):
    original = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-users-pivot.sqlite3")
        database.init_db()
        records = (
            _subject(usage=10, slot=0),
            _subject(usage=20, slot=1),
            _subject(usage=30, slot=2),
            _subject(usage=5, slot=1, subject_id="u-2", name="bob"),
        )
        monthly = tuple(_monthly(100, slot=slot) for slot in range(3))
        monkeypatch.setattr(report_page, "load_subject_history", lambda slots, cache: records)
        monkeypatch.setattr(report_page, "load_monthly_usage", lambda slots, cache: monthly)
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(
            repository=_ThreeDeviceRepository(),
            cache=_EmptyCache(),
            subject_cache=_EmptyCache(),
        )

        page._populate_month_dropdown_users(0)

        headers = [page.tbl_users.horizontalHeaderItem(index).text() for index in range(page.tbl_users.columnCount())]
        assert headers == [
            "User / Account",
            "DMS Printer",
            "Sales Printer",
            "HR Printer",
            "รวมทุกเครื่อง",
        ]
        assert [page.tbl_users.item(0, column).text() for column in range(5)] == [
            "alice",
            "10",
            "20",
            "30",
            "60",
        ]
        assert [page.tbl_users.item(1, column).text() for column in range(5)] == [
            "bob",
            "—",
            "5",
            "—",
            "5",
        ]
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_history_users_keeps_subject_usage_separate_by_frozen_device_identity(tmp_path, monkeypatch):
    original = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-users-rollover.sqlite3")
        database.init_db()
        records = (
            _subject(
                usage=10,
                identity="serial:SER-A",
                device_name="Printer A",
                serial="SER-A",
            ),
            _subject(
                usage=20,
                identity="serial:SER-B",
                device_name="Printer B",
                serial="SER-B",
            ),
        )
        monthly = (
            _monthly(
                100,
                identity="serial:SER-A",
                device_name="Printer A",
                serial="SER-A",
            ),
            _monthly(
                200,
                identity="serial:SER-B",
                device_name="Printer B",
                serial="SER-B",
            ),
        )
        monkeypatch.setattr(report_page, "load_subject_history", lambda slots, cache: records)
        monkeypatch.setattr(report_page, "load_monthly_usage", lambda slots, cache: monthly)
        monkeypatch.setattr(
            report_page,
            "load_usage_history",
            lambda slots, granularity, cache: monthly,
        )
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(
            repository=_RolloverRepository(),
            cache=_EmptyCache(),
            subject_cache=_EmptyCache(),
        )

        page._populate_month_dropdown_users(0)

        headers = [
            page.tbl_users.horizontalHeaderItem(index).text()
            for index in range(page.tbl_users.columnCount())
        ]
        assert headers == [
            "User / Account",
            "Printer A · SER-A",
            "Printer B · SER-B",
            "รวมทุกเครื่อง",
        ]
        assert [page.tbl_users.item(0, column).text() for column in range(4)] == [
            "alice",
            "10",
            "20",
            "30",
        ]
        assert "Serial: SER-A" in page.tbl_users.horizontalHeaderItem(1).toolTip()
        assert "Printer A · SER-A" in page.users_reconciliation.text()
        assert "Printer B · SER-B" in page.users_reconciliation.text()
        assert page.users_reconciliation.text().count("Coverage 10.0%") == 2

        page._populate_report_periods()
        assert page.report_users.rowCount() == 2
        assert page.report_users.columnCount() == 2
        assert page.report_users.horizontalHeaderItem(0).text() == "User / Account"
        assert page.report_users.horizontalHeaderItem(1).text() == "Total Counter"
        overview_rows = {
            page.report_users.item(row, 0).text(): page.report_users.item(row, 1).text()
            for row in range(page.report_users.rowCount())
        }
        assert overview_rows == {
            "alice\nPrinter A · SER-A": "125",
            "alice\nPrinter B · SER-B": "125",
        }
        assert all(
            "Identity: serial:SER-" in page.report_users.item(row, 0).toolTip()
            for row in range(page.report_users.rowCount())
        )
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)
