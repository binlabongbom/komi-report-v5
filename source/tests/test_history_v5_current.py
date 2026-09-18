import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from pathlib import Path

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QScrollArea

import database
import v5_pages
from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from ui.cloud_reports import USAGE_METRICS
from v5_pages import PageHistoryV5, ReportExportPeriodDialog
from widgets import FrozenLeftTable, VisibleCheckBox


class _Repository:
    def __init__(self) -> None:
        self.devices = [
            DeviceConfig(
                slot=index,
                name=f"Printer {index + 1}",
                host=f"192.0.2.{index + 10}",
                connection_status="online",
                last_total=1_100 + index * 1_000,
            )
            for index in range(2)
        ]

    def list(self, *, enabled_only: bool = False):
        return self.devices


def test_report_export_period_dialog_validates_range_and_shows_available_dates():
    app = QApplication.instance() or QApplication([])
    dialog = ReportExportPeriodDialog(
        date(2026, 8, 1),
        date(2026, 8, 31),
        available_start=date(2026, 7, 1),
        available_end=date(2026, 8, 31),
    )

    assert dialog.selected_range() == (date(2026, 8, 1), date(2026, 8, 31))
    assert "ข้อมูลที่พบ 01/07/2026–31/08/2026" in dialog.status.text()
    assert dialog.export_button.isEnabled()

    dialog.start_date.setDate(QDate(2026, 9, 1))
    assert not dialog.export_button.isEnabled()
    assert "วันที่เริ่มต้นต้องไม่เกิน" in dialog.status.text()
    dialog.close()
    app.processEvents()


class _RolloverRepository:
    def list(self, *, enabled_only: bool = False):
        return [
            DeviceConfig(
                slot=0,
                name="Printer B",
                host="192.0.2.20",
                serial="SER-B",
                connection_status="online",
            )
        ]


class _DisabledHistoryRepository:
    def __init__(self) -> None:
        self.active = DeviceConfig(
            slot=0,
            name="Active Printer",
            host="192.0.2.20",
            serial="SER-ACTIVE",
            enabled=True,
            connection_status="online",
        )
        self.disabled = DeviceConfig(
            slot=1,
            name="Disabled Printer",
            host="192.0.2.21",
            serial="SER-OLD",
            enabled=False,
            connection_status="offline",
        )

    def list(self, *, enabled_only: bool = False):
        return [self.active] if enabled_only else [self.active, self.disabled]


class _Cache:
    def load(self, slot: int, day: date):
        offset = slot * 1_000
        return {
            "opening": {
                "counter.total.total": 1_000 + offset,
                "counter.print.full_color_total": 500 + offset,
                "counter.print.full_color_large": 90,
            },
            "latest": {
                "counter.total.total": 1_100 + offset,
                "counter.print.full_color_total": 600 + offset,
                "counter.print.full_color_large": 100,
            },
            "delta": {
                "counter.total.total": 100,
                "counter.print.full_color_total": 100,
                "counter.print.full_color_large": 10,
            },
            "last_snmp_total": 1_100 + offset,
            "last_success": "2026-07-16T17:01:00+07:00",
        }


class _DifferentSnmpCache(_Cache):
    def load(self, slot: int, day: date):
        state = super().load(slot, day)
        state["last_snmp_total"] = 9_999_999
        return state


class _ResetCache(_Cache):
    def load(self, slot: int, day: date):
        state = super().load(slot, day)
        state["opening"]["counter.total.total"] = 100
        state["latest"]["counter.total.total"] = 7
        state["delta"]["counter.total.total"] = 7
        return state


def test_history_current_uses_enabled_devices_and_daily_cache(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history.sqlite3")
        database.init_db()
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._refresh_current_all()

        table = page.tbl_current_all
        assert table.columnCount() == 3
        assert table.rowCount() == 15
        assert table.groupedHeaderItem(0, 0).text() == "รายการ"
        assert table.groupedHeaderItem(0, 1).text() == "Printer 1"
        assert table.groupedHeaderItem(0, 2).text() == "Printer 2"
        assert table.groupedHeaderItem(1, 1).text() == "ปัจจุบัน"
        assert table.item(0, 0).text() == "Total Meter"
        assert table.item(0, 1).text() == "1,100"
        assert table.item(2, 1).text() == "100"
        assert table.item(0, 1).foreground().color().name() == "#172033"
        assert "Printer 1 · Online · ค่ามิเตอร์ล่าสุด" in page.current_status.text()
        assert page.current_source_note.isHidden()
        assert page.chk_diff.text() == "รายละเอียดวันนี้"
        assert isinstance(page.chk_diff, VisibleCheckBox)
        assert isinstance(page.chk_hide_zero, VisibleCheckBox)
        assert not page.chk_diff.isChecked()
        assert not page.chk_diff.isHidden()
        assert not page.chk_hide_zero.isChecked()
        assert not page.chk_hide_zero.isHidden()

        page.chk_diff.setChecked(True)
        assert table.columnCount() == 7
        assert table.groupedHeaderItem(0, 1).text() == "Printer 1"
        assert table.groupedHeaderSpan(0, 1) == (1, 3)
        assert table.groupedHeaderItem(1, 1).text() == "ปัจจุบัน"
        assert table.groupedHeaderItem(1, 2).text() == "ต้นวัน"
        assert table.groupedHeaderItem(1, 3).text() == "+วันนี้"
        assert table.item(0, 1).text() == "1,100"
        assert table.item(0, 2).text() == "1,000"
        assert table.item(0, 3).text() == "+100"
        assert table.item(0, 3).foreground().color().name() == "#16a34a"
        assert table.item(2, 1).text() == "100"
        assert table.item(2, 2).text() == "90"
        assert table.item(2, 3).text() == "+10"
        assert table.groupSeparatorColumns() == (3,)
        assert "border-radius: 0px" in table._left.styleSheet()
        assert all(
            table._left.rowHeight(row) == table._right.rowHeight(row) == 30
            for row in range(table.rowCount())
        )
        table.setFixedHeight(240)
        page.show()
        app.processEvents()
        table._vsb.setValue(table._vsb.maximum())
        app.processEvents()
        assert table._left.rowAt(1) == table._right.rowAt(1), {
            "left_row": table._left.rowAt(1),
            "right_row": table._right.rowAt(1),
            "left_viewport_height": table._left.viewport().height(),
            "right_viewport_height": table._right.viewport().height(),
            "left_scroll": (
                table._left.verticalScrollBar().value(),
                table._left.verticalScrollBar().maximum(),
            ),
            "right_scroll": (
                table._right.verticalScrollBar().value(),
                table._right.verticalScrollBar().maximum(),
            ),
            "external_scroll": (table._vsb.value(), table._vsb.maximum()),
            "horizontal_scroll": (
                table._right.horizontalScrollBar().minimum(),
                table._right.horizontalScrollBar().maximum(),
                table._right.horizontalScrollBar().height(),
            ),
        }
        assert not page.chk_diff.isHidden()

        page.chk_diff.setChecked(False)
        assert table.columnCount() == 3
        assert not page.chk_diff.isHidden()

        page.chk_hide_zero.setChecked(True)
        assert table.rowCount() < 15
        visible_labels = {
            table.item(row, 0).text()
            for row in range(table.rowCount())
        }
        assert "Other size (Print)" not in visible_labels
        assert "Other size (Copy)" not in visible_labels
        assert not page.chk_hide_zero.isHidden()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_history_current_total_uses_web_meter_not_snmp_status(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-web-total.sqlite3")
        database.init_db()
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_DifferentSnmpCache())

        page._refresh_current_all()

        assert page.tbl_current_all.item(0, 1).text() == "1,100"
        assert "SNMP ใช้ตรวจสถานะ/trigger เท่านั้น" in page.current_source_note.text()
        assert page.current_source_note.isHidden()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_history_current_today_increase_uses_segmented_cache_delta_after_reset(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-reset.sqlite3")
        database.init_db()
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_ResetCache())

        page.chk_diff.setChecked(True)
        page._refresh_current_all()

        assert page.tbl_current_all.item(0, 1).text() == "7"
        assert page.tbl_current_all.item(0, 2).text() == "100"
        assert page.tbl_current_all.item(0, 3).text() == "+7"
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_history_monthly_defaults_to_usage_and_cost_columns(tmp_path, monkeypatch):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-monthly.sqlite3")
        database.init_db()
        records = tuple(
            MonthlyUsage(
                device_slot=slot,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                total=100 + slot * 50,
                a3_color=10,
                a3_bw=5,
                a4_color=60,
                a4_bw=25,
                scan=7,
                gross_cost=200 + slot * 100,
                net_cost=196 + slot * 98,
                day_count=1,
                incomplete_days=0,
            )
            for slot in range(2)
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda slots, granularity, cache: records,
        )
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._refresh_monthly(0)

        table = page.tbl_monthly
        assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == [
                "ภาพรวม",
                "ค่ามิเตอร์รายเครื่อง",
                "ยอดใช้งานและค่าใช้จ่าย",
            "รายผู้ใช้",
            "แนวโน้ม",
        ]
        assert page.tabs.currentWidget() is page.tab_overview
        assert page.history_view_combo.currentData() == "monthly"
        assert table.rowCount() == 1
        assert table.columnCount() == 10
        assert table.groupedHeaderItem(0, 0).text() == "รอบบิล"
        assert table.groupedHeaderItem(0, 1).text() == "Printer 1"
        assert table.groupedHeaderItem(1, 1).text() == "Color"
        assert table.groupedHeaderItem(1, 2).text() == "B&W"
        assert table.groupedHeaderItem(1, 3).text() == "Cost"
        assert table.groupedHeaderSpan(0, 0) == (2, 1)
        assert table.groupedHeaderSpan(0, 1) == (1, 3)
        assert table.item(0, 1).text() == "70"
        assert table.item(0, 2).text() == "30"
        assert table.item(0, 3).text() == "196.00"
        assert table.item(0, 4).text() == "70"
        assert table.item(0, 5).text() == "30"
        assert table.item(0, 6).text() == "294.00"
        assert table.item(0, 7).text() == "140"
        assert table.item(0, 8).text() == "60"
        assert table.item(0, 9).text() == "490.00"
        assert table.item(0, 1).background().color() != table.item(0, 4).background().color()
        assert (
            table.groupedHeaderItem(0, 1).background().color()
            != table.groupedHeaderItem(0, 4).background().color()
        )
        assert not page.chk_detail_monthly.isChecked()
        assert page.chk_detail_monthly.text() == "รายละเอียดเพิ่มเติม"
        assert page.chk_waste_monthly.text() == "ค่าใช้จ่ายสุทธิจาก Ledger"

        page.chk_detail_monthly.setChecked(True)
        assert table.rowCount() == 1
        assert table.columnCount() == 25
        assert table.groupedHeaderSpan(0, 1) == (1, 8)
        assert table.groupedHeaderItem(1, 4).text() == "A3 Color"
        assert table.groupedHeaderItem(1, 8).text() == "Scan"
        assert table.item(0, 4).text() == "10"
        assert table.item(0, 8).text() == "7"
        assert table.item(0, 20).text() == "20"

        page.history_view_combo.setCurrentIndex(1)
        assert page.history_view_combo.currentData() == "weekly"
        assert "รายสัปดาห์" in page.history_title.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_history_monthly_group_header_stays_visible_and_tracks_horizontal_scroll():
    """The period header is sticky; device values are never frozen."""
    app = QApplication.instance() or QApplication([])
    table = FrozenLeftTable()
    table.resize(900, 280)
    table.setColumnCount(7)
    table.setRowCount(24)
    table.setHorizontalHeaderLabels(["รอบบิล", *["Color"] * 6])
    table.setGroupedHeader(
        "รอบบิล",
        [("Printer 1", 3, "#EAF1FA"), ("Printer 2", 3, "#EAF1FA")],
        ["Color", "B&W", "Cost"] * 2,
    )
    table.setColumnWidth(0, 220)
    for column in range(1, 7):
        table.setColumnWidth(column, 160)
    table.show()
    app.processEvents()

    header_y = table._group_header.y()
    body_y = table._body.y()
    table._right.verticalScrollBar().setValue(table._right.verticalScrollBar().maximum())
    app.processEvents()

    assert table._group_header.height() == 70
    assert table._group_header.y() == header_y
    assert table._body.y() == body_y
    assert table._group_header.geometry().bottom() < table._body.geometry().top()

    horizontal_scroll = table._right.horizontalScrollBar()
    horizontal_scroll.setValue(horizontal_scroll.maximum())
    app.processEvents()
    assert table._group_right.horizontalScrollBar().value() == horizontal_scroll.value()
    assert table._left.columnWidth(0) == 220  # only the billing-period label is frozen
    table.close()


def test_reports_keep_periods_separate_when_start_matches_but_end_differs(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-period-identity.sqlite3")
        database.init_db()
        records = tuple(
            MonthlyUsage(
                device_slot=0,
                period_start=date(2026, 7, 1),
                period_end=period_end,
                total=total,
                a3_color=0,
                a3_bw=0,
                a4_color=total,
                a4_bw=0,
                scan=0,
                gross_cost=total,
                net_cost=total,
                day_count=1,
                incomplete_days=0,
                device_identity="serial:SER-A",
                device_name_snapshot="Printer 1",
                device_serial_snapshot="SER-A",
            )
            for period_end, total in (
                (date(2026, 7, 25), 10),
                (date(2026, 7, 31), 20),
            )
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda slots, granularity, cache: records,
        )
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._populate_report_periods()
        page._refresh_monthly(0)

        assert page.report_period_combo.count() == 2
        assert page.report_period_combo.itemData(0) != page.report_period_combo.itemData(1)
        assert page.tbl_monthly.rowCount() == 2
        assert {
            page.tbl_monthly.item(row, 1).text()
            for row in range(page.tbl_monthly.rowCount())
        } == {"10", "20"}
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_empty_state_does_not_present_zero_as_confirmed_data(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-empty.sqlite3")
        database.init_db()
        monkeypatch.setattr(v5_pages, "load_usage_history", lambda *args, **kwargs: ())
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._populate_report_periods()
        page._refresh_monthly(0)
        page._populate_month_dropdown_users(0)

        assert {label.text() for label in page.report_kpis.values()} == {"—"}
        assert "ไม่มี Posted Ledger" in page.report_period_note.text()
        assert page.report_period_note.isHidden()
        assert "ยังไม่มีข้อมูล" in page.report_overview_warning.text()
        assert not page.btn_export_monthly.isEnabled()
        assert not page.btn_export_users.isEnabled()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_loader_error_is_visible_and_disables_exports(tmp_path, monkeypatch):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-error.sqlite3")
        database.init_db()
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        def fail(*args, **kwargs):
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr(v5_pages, "load_usage_history", fail)
        page.refresh()

        assert not page.reports_error.isHidden()
        assert "ledger unavailable" in page.reports_error.text()
        assert {label.text() for label in page.report_kpis.values()} == {"—"}
        assert not page.btn_export_monthly.isEnabled()
        assert not page.btn_export_users.isEnabled()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_trend_uses_posted_ledger_projection_and_hides_value_labels_by_default(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-trend.sqlite3")
        database.init_db()
        record = MonthlyUsage(
            device_slot=0,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            total=30,
            a3_color=2,
            a3_bw=3,
            a4_color=10,
            a4_bw=15,
            scan=1,
            gross_cost=60,
            net_cost=58.8,
            day_count=1,
            incomplete_days=0,
            device_identity="serial:SER-A",
            device_name_snapshot="Printer Ledger",
            device_serial_snapshot="SER-A",
            print_color=8,
            print_bw=10,
            copy_color=4,
            copy_bw=8,
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda *args, **kwargs: (record,),
        )
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        data = page._prepare_graph_data()

        assert data["all_months"] == ["2026-07-31"]
        assert data["slot_monthly"][0]["2026-07-31"]["total"] == 30
        assert data["slot_monthly"][0]["2026-07-31"]["print_color"] == 8
        assert data["m_names"][0] == "Printer Ledger"
        assert not page.chk_show_values.isChecked()
        assert page._graph_view_btns["by_machine"].text() == "รายเครื่อง"
        assert page.btn_save_png.text() == "ส่งออก PNG"
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_trend_type_view_uses_time_chart_and_marks_provisional_cache(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-trend-provisional.sqlite3")
        database.init_db()
        record = MonthlyUsage(
            device_slot=0,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            total=30,
            a3_color=2,
            a3_bw=3,
            a4_color=10,
            a4_bw=15,
            scan=1,
            gross_cost=60,
            net_cost=58.8,
            day_count=1,
            incomplete_days=0,
            device_name_snapshot="Printer Ledger",
            print_color=8,
            print_bw=10,
            copy_color=4,
            copy_bw=8,
            provisional_total=7,
            provisional_print_color=3,
            provisional_print_bw=2,
            provisional_copy_color=1,
            provisional_copy_bw=1,
            provisional_days=1,
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda *args, **kwargs: (record,),
        )
        monkeypatch.setattr(
            v5_pages,
            "load_subject_history",
            lambda *args, **kwargs: (),
        )
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._set_graph_view("by_type")
        app.processEvents()
        data = page._graph_data_cache

        assert page.plot_widget.isVisible() == page.isVisible()
        assert page.pie_container.isHidden()
        assert data["slot_monthly"][0]["2026-07-31"]["provisional_total"] == 7
        assert (
            data["slot_monthly"][0]["2026-07-31"]["provisional_print_color"]
            == 3
        )
        assert any(
            "Print สี ระหว่างวัน" in label
            for label, *_rest in page._hover_bars
        )
        assert any(
            "Copy ขาวดำ ระหว่างวัน" in label
            for label, *_rest in page._hover_bars
        )
        assert "Daily Cache (~)" in page.trend_data_note.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_trend_current_year_filter_uses_period_end_dates(tmp_path, monkeypatch):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-trend-year.sqlite3")
        database.init_db()
        monkeypatch.setattr(v5_pages, "load_usage_history", lambda *args, **kwargs: ())
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())
        page._available_months_for_filter = [
            "2025-12-31",
            "2026-01-31",
            "2026-07-31",
        ]
        page._graph_date_from = "2025-12-31"
        page._graph_date_to = "2026-07-31"
        page._populate_date_filter_dropdowns()

        page._on_date_reset_all()

        assert page._graph_date_from == "2026-01-31"
        assert page._graph_date_to == "2026-07-31"
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_overview_uses_billable_pages_and_reveals_frozen_cost_details(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-overview-cost-details.sqlite3")
        database.init_db()
        records = (
            MonthlyUsage(
                device_slot=0,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                total=999,
                a3_color=10,
                a3_bw=5,
                a4_color=20,
                a4_bw=15,
                scan=12,
                gross_cost=100,
                net_cost=98,
                day_count=1,
                incomplete_days=0,
            ),
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda slots, granularity, cache: records,
        )
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._populate_report_periods()
        report_index = next(
            index
            for index in range(page.report_period_combo.count())
            if tuple(page.report_period_combo.itemData(index))
            == ("2026-01-01", "2026-01-31")
        )
        page.report_period_combo.setCurrentIndex(report_index)
        page._refresh_reports_overview()

        assert page.report_kpis["usage"].text() == "50"
        assert page.report_kpis["scan"].text() == "12"
        assert page.report_kpis["cost"].text() == "98.00"
        assert page.report_printers.item(0, 5).text() == "98.00"

        page.report_cost_detail_checkbox.setChecked(True)
        assert "ค่าใช้จ่ายก่อนหัก 100.00 บาท" in page.report_cost_detail_summary.text()
        assert "ส่วนลดกระดาษเสีย 2.00 บาท (2.00%)" in page.report_cost_detail_summary.text()
        assert "ค่าใช้จ่ายสุทธิ 98.00 บาท" in page.report_cost_detail_summary.text()
        assert page.report_printers.item(0, 5).text() == "100.00"
        assert page.report_printers.item(0, 6).text() == "2.00%"
        assert page.report_printers.item(0, 7).text() == "98.00"
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_overview_separates_confirmed_and_current_cache_estimate(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-overview-provisional.sqlite3")
        database.init_db()
        records = (
            MonthlyUsage(
                device_slot=0,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                total=50,
                a3_color=5,
                a3_bw=5,
                a4_color=20,
                a4_bw=20,
                scan=2,
                gross_cost=100,
                net_cost=98,
                day_count=1,
                incomplete_days=0,
                provisional_total=10,
                provisional_a3_color=2,
                provisional_a4_color=8,
                provisional_scan=1,
                provisional_gross_cost=22,
                provisional_net_cost=21.56,
                provisional_days=1,
            ),
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda slots, granularity, cache: records,
        )
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._populate_report_periods()
        page._refresh_reports_overview()

        assert page.report_kpis["usage"].text() == "~60"
        assert page.report_kpis["color"].text() == "~35"
        assert page.report_kpis["bw"].text() == "~25"
        assert page.report_kpis["scan"].text() == "~3"
        assert page.report_kpis["cost"].text() == "~119.56"
        assert page.report_provisional_summary.isHidden()
        page.report_advanced_button.setChecked(True)
        assert not page.report_provisional_summary.isHidden()
        assert "ยืนยันแล้วจาก Billing Ledger: 50 หน้า · 98.00 บาท" in page.report_provisional_summary.text()
        assert "วันนี้จาก Daily Cache: +10 หน้า · ~21.56 บาท" in page.report_provisional_summary.text()
        assert "ยังไม่ถูกบันทึกลง Billing Ledger" in page.report_provisional_summary.text()
        assert page.report_printers.item(0, 1).text() == "ยืนยันแล้ว + วันนี้"
        assert page.report_printers.item(0, 2).text() == "~35"
        assert page.report_printers.item(0, 5).text() == "~119.56"
        with database._open(commit=False) as conn:
            assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 0
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_show_held_days_without_claiming_current_waste_for_frozen_ledger(tmp_path, monkeypatch):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-held-copy.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "1")
        database.set_cfg("waste_paper_pct", "47")
        records = (
            MonthlyUsage(
                device_slot=0,
                period_start=date(2026, 6, 26),
                period_end=date(2026, 7, 25),
                total=100,
                a3_color=10,
                a3_bw=5,
                a4_color=60,
                a4_bw=25,
                scan=7,
                gross_cost=200,
                net_cost=196,
                day_count=1,
                incomplete_days=0,
                held_days=2,
            ),
            MonthlyUsage(
                device_slot=1,
                period_start=date(2026, 6, 26),
                period_end=date(2026, 7, 25),
                total=50,
                a3_color=5,
                a3_bw=5,
                a4_color=20,
                a4_bw=20,
                scan=2,
                gross_cost=100,
                net_cost=95,
                day_count=1,
                incomplete_days=1,
                held_days=0,
            ),
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda slots, granularity, cache: records,
        )
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())

        page._populate_report_periods()
        page._refresh_monthly(0)
        report_index = next(
            (
                index
                for index in range(page.report_period_combo.count())
                if tuple(page.report_period_combo.itemData(index))
                == ("2026-06-26", "2026-07-25")
            ),
            -1,
        )
        assert report_index >= 0
        page.report_period_combo.setCurrentIndex(report_index)
        page._refresh_reports_overview()

        assert "มีข้อมูลรอตรวจสอบ 3 device-day" in page.report_overview_warning.text()
        assert "Hold 2 device-day ไม่รวมในยอด" in page._report_overview_review_detail
        assert "ข้อมูลไม่สมบูรณ์ 1 device-day" in page._report_overview_review_detail
        assert "Pricelist/ส่วนลดตามแต่ละรายการ" in page.report_period_note.text()
        assert page.report_period_note.isHidden()
        assert "47" not in page.report_period_note.text()
        assert "ยึดค่าที่บันทึกใน Ledger ของแต่ละวัน" in page.lbl_billing_day.text()
        assert "47" not in page.lbl_billing_day.text()
        assert "Hold 2 device-day ไม่รวมในยอด" in page.monthly_summary.text()
        assert page.report_printer_title.text() == "Printer"
        assert page.report_user_title.text() == "User / Account"
        assert page.report_kpis["usage"].text() == "—"
        assert page.report_kpis["color"].text() == "—"
        assert page.report_kpis["bw"].text() == "—"
        assert page.report_kpis["scan"].text() == "—"
        assert page.report_kpis["cost"].text() == "—"
        assert page.report_kpis["devices"].text() == "2"
        assert page.report_printers.horizontalHeaderItem(0).text() == "เครื่อง"
        assert page.report_printers.horizontalHeaderItem(1).text() == "สถานะ"
        assert page.report_printers.columnWidth(0) >= 120
        assert page.report_printers.columnWidth(1) >= 80
        assert page.report_printers.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
        assert page.report_printers.item(0, 0).text() == "Printer 1"
        assert "Printer 1" in page.report_printers.item(0, 0).toolTip()
        assert page.report_printers.item(0, 1).text() == "รอตรวจสอบ 2 วัน"
        assert "ไม่รวมในยอด" in page.report_printers.item(0, 1).toolTip()
        dialogs: list[tuple[str, str]] = []
        monkeypatch.setattr(
            v5_pages.QMessageBox,
            "information",
            lambda _parent, title, text: dialogs.append((title, text)),
        )
        page.report_printers.cellClicked.emit(0, 1)
        assert dialogs
        assert "รอตรวจสอบ 2 วัน" in dialogs[0][1]
        assert "ตรวจสอบรอบบิล" in dialogs[0][1]
        assert page.report_printers.item(1, 1).text() == "ไม่สมบูรณ์ 1 วัน"
        assert "ตรวจสอบรอบบิล" in page.report_printers.item(1, 1).toolTip()

        assert not page.report_cost_detail_checkbox.isChecked()
        assert page.report_printers.columnCount() == 6
        page.report_cost_detail_checkbox.setChecked(True)
        assert not page.report_cost_detail_summary.isHidden()
        assert page.report_printers.columnCount() == 8
        assert page.report_printers.horizontalHeaderItem(5).text() == "ก่อนหัก"
        assert page.report_printers.horizontalHeaderItem(6).text() == "ส่วนลด"
        assert page.report_printers.horizontalHeaderItem(7).text() == "สุทธิ"
        assert page.report_cost_detail_summary.text().count("—") == 3
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_keep_frozen_device_identities_separate_after_slot_rollover(tmp_path, monkeypatch):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-identity-rollover.sqlite3")
        database.init_db()
        records = (
            MonthlyUsage(
                device_slot=0,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                total=10,
                a3_color=0,
                a3_bw=0,
                a4_color=10,
                a4_bw=0,
                scan=1,
                gross_cost=10,
                net_cost=10,
                day_count=1,
                incomplete_days=0,
                device_identity="serial:SER-A",
                device_name_snapshot="Printer A",
                device_serial_snapshot="SER-A",
            ),
            MonthlyUsage(
                device_slot=0,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                total=20,
                a3_color=0,
                a3_bw=0,
                a4_color=20,
                a4_bw=0,
                scan=2,
                gross_cost=20,
                net_cost=20,
                day_count=1,
                incomplete_days=0,
                device_identity="serial:SER-B",
                device_name_snapshot="Printer B",
                device_serial_snapshot="SER-B",
            ),
        )
        monkeypatch.setattr(
            v5_pages,
            "load_usage_history",
            lambda slots, granularity, cache: records,
        )
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_RolloverRepository(), cache=_Cache())

        page._populate_report_periods()
        page._refresh_monthly(0)

        assert page.report_kpis["usage"].text() == "30"
        assert page.report_kpis["devices"].text() == "1"
        assert page.report_printers.rowCount() == 2
        overview_rows = {
            page.report_printers.item(row, 0).text(): page.report_printers.item(row, 1).text()
            for row in range(page.report_printers.rowCount())
        }
        assert overview_rows == {
            "Printer A · SER-A": "เครื่องเดิม",
            "Printer B · SER-B": "Online",
        }
        assert "มีข้อมูลรอตรวจสอบ" in page.report_overview_warning.text()
        assert "เครื่องเดิม/ปัจจุบันร่วมกัน 1 slot" in page._report_overview_review_detail

        table = page.tbl_monthly
        assert table.columnCount() == 10
        assert table.groupedHeaderItem(0, 1).text() == "Printer A · SER-A"
        assert table.groupedHeaderItem(0, 4).text() == "Printer B · SER-B"
        assert "Serial: SER-A" in table.groupedHeaderItem(0, 1).toolTip()
        assert [table.item(0, column).text() for column in (1, 4, 7)] == [
            "10",
            "20",
            "30",
        ]
        assert "เครื่องเดิม/ปัจจุบันร่วมกัน 1 slot" in page.monthly_summary.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_keep_disabled_slot_history_but_current_tab_stays_enabled_only(tmp_path, monkeypatch):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "history-disabled-slot.sqlite3")
        database.init_db()
        records = (
            MonthlyUsage(
                device_slot=1,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                total=40,
                a3_color=0,
                a3_bw=0,
                a4_color=10,
                a4_bw=30,
                scan=0,
                gross_cost=12,
                net_cost=12,
                day_count=1,
                incomplete_days=0,
                device_identity="serial:SER-OLD",
                device_name_snapshot="Disabled Printer",
                device_serial_snapshot="SER-OLD",
            ),
        )
        requested_slots: list[tuple[int, ...]] = []

        def load_history(slots, granularity, cache):
            requested_slots.append(tuple(slots))
            return records

        monkeypatch.setattr(v5_pages, "report_slots", lambda: [0, 1])
        monkeypatch.setattr(v5_pages, "load_usage_history", load_history)
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_DisabledHistoryRepository(), cache=_Cache())

        page._populate_report_periods()
        page._refresh_monthly(0)
        page._refresh_current_all()

        assert requested_slots and all(slots == (0, 1) for slots in requested_slots)
        assert page.report_printers.item(0, 0).text() == "Disabled Printer · SER-OLD"
        assert page.report_printers.item(0, 1).text() == "เครื่องเดิม"
        assert page.report_kpis["usage"].text() == "40"
        assert page.report_kpis["devices"].text() == "0"
        assert page.tbl_monthly.groupedHeaderItem(0, 1).text() == "Disabled Printer · SER-OLD"
        assert page.tbl_monthly.item(0, 1).text() == "10"
        assert page.tbl_current_all.columnCount() == 2
        assert page.tbl_current_all.groupedHeaderItem(0, 1).text() == "Active Printer"
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_reports_builder_uses_ysoft_style_report_profile_and_advanced_controls(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "report-builder.sqlite3")
        database.init_db()
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(
            repository=_Repository(),
            cache=_Cache(),
            subject_cache=_Cache(),
        )

        assert [
            page.report_profile_combo.itemText(index)
            for index in range(page.report_profile_combo.count())
        ] == ["Standard", "Per device", "Usage & cost", "Per user", "Trend"]
        page.report_profile_combo.setCurrentIndex(3)
        assert page.tabs.currentWidget() is page.tab_users
        page.report_advanced_button.setChecked(True)
        assert not page.report_advanced_panel.isHidden()
        page.report_granularity_combo.setCurrentIndex(0)
        assert page.history_view_combo.currentData() == "daily"
        page.report_detail_checkbox.setChecked(True)
        assert page.report_cost_detail_checkbox.isChecked()
        assert page.chk_detail_monthly.isChecked()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_report_center_replaces_legacy_reports_with_cloud_overview_users_and_printers(
    tmp_path, monkeypatch
):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "report-center.sqlite3")
        database.init_db()
        current_day = date.today()
        records = (
            MonthlyUsage(
                device_slot=0,
                period_start=current_day,
                period_end=current_day,
                total=1_000,
                a3_color=100,
                a3_bw=50,
                a4_color=400,
                a4_bw=450,
                scan=20,
                gross_cost=12,
                net_cost=10,
                day_count=1,
                incomplete_days=0,
                provisional_total=200,
                provisional_a4_color=100,
                provisional_net_cost=2,
                provisional_days=1,
            ),
        )
        usage_loads = []

        def load_report_usage(slots, granularity, cache):
            usage_loads.append(granularity)
            return records

        monkeypatch.setattr(v5_pages, "load_usage_history", load_report_usage)
        monkeypatch.setattr(v5_pages, "load_subject_history", lambda *args, **kwargs: ())
        app = QApplication.instance() or QApplication([])
        page = PageHistoryV5(repository=_Repository(), cache=_Cache())
        assert usage_loads == []

        assert page.tabs.isHidden()
        assert [
            page.report_center_tabs.tabText(index)
            for index in range(page.report_center_tabs.count())
        ] == ["Overview", "Users", "Printers", "Usage", "Legacy"]
        report = page.report_center
        content_pages = (
            report.overview_page, report.users_page, report.printers_page,
            report.usage_page, report.legacy_raw_page,
        )
        for index, content in enumerate(content_pages):
            scrolls = report.tabs.widget(index).findChildren(QScrollArea)
            owners = [scroll for scroll in scrolls if scroll.widget() is content]
            assert len(owners) == 1
            scroll = owners[0]
            assert scroll.widgetResizable()
            assert not scroll.viewport().isAncestorOf(report.header)
            assert not scroll.viewport().isAncestorOf(report.tabs.tabBar())
            for start, end in report.period_edit_pairs:
                assert not scroll.viewport().isAncestorOf(start)
                assert not scroll.viewport().isAncestorOf(end)

        page._refresh_report_center()
        assert usage_loads == ["monthly", "daily"]
        cloud = page.report_center
        assert cloud.overview_kpis["total_usage"].lbl_val.text() == "1,200"
        assert cloud.overview_printers.item(0, 0).text() == "Printer 1"
        assert cloud.usage_monthly_table.rowCount() == 0
        # This fixture has only aggregate paper totals.  Print/Copy must stay
        # explicitly unavailable instead of being guessed from Color/B&W.
        cloud.tabs.setCurrentIndex(2)
        assert cloud.printer_metric_cards["color_print"]._full_value == "—"
        assert cloud.printer_metric_cards["color_copy"]._full_value == "—"
        assert cloud.printers_table.item(0, 0).text() == "Printer 1"
        assert cloud.printer_detail.item(0, 1).text() == "Printer 1"
        cloud.tabs.setCurrentIndex(3)
        assert cloud.usage_monthly_table.item(0, 0).text() == current_day.strftime("%m/%Y")
        total_metric_index = next(
            index
            for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
            if field == "total"
        )
        assert cloud.usage_monthly_table.item(
            0, 1 + total_metric_index
        ).text() == "1,200"
        cloud.tabs.setCurrentIndex(2)
        cloud._select_printer_row(0, 0)
        assert "ทุกเครื่องพร้อมกัน" in cloud.printer_compare_note.text()
        exported = []
        import services.report_export_job as export_job
        import services.report_excel_export as excel
        monkeypatch.setattr(export_job, 'load_usage_history', load_report_usage)
        monkeypatch.setattr(export_job, 'load_subject_history', lambda *args, **kwargs: ())
        monkeypatch.setattr(
            v5_pages.QFileDialog,
            "getSaveFileName",
            lambda *_args, **_kwargs: (str(tmp_path / "cloud-report.xlsx"), "Excel Workbook (*.xlsx)"),
        )
        monkeypatch.setattr(
            v5_pages.ReportExportPeriodDialog,
            "get_range",
            lambda *_args, **_kwargs: (current_day, current_day),
        )
        monkeypatch.setattr(
            excel,
            "export_cloud_reports_xlsx",
            lambda path, report, **kwargs: exported.append(report) or Path(path),
        )
        monkeypatch.setattr(v5_pages.QMessageBox, "information", lambda *_args, **_kwargs: None)
        cloud.export_button.click()
        # This legacy suite leaves QtCharts deferred deletes from earlier pages.
        # Drain just this stubbed job; live event-loop responsiveness is covered
        # with fresh report pages in test_report_export_job.
        page._export_controller.future.result(timeout=5)
        page._export_controller._collect()
        assert len(exported) == 1
        assert exported[0].monthly_records == records
        assert exported[0].period == (current_day.isoformat(), current_day.isoformat())
        assert exported[0].selected_daily_records == records
        assert exported[0].devices[0].name == "Printer 1"
        page.shutdown_report_loading()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)
