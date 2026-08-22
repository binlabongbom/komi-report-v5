import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QApplication, QDateEdit

from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.subject_history import SubjectPeriodUsage
from ui.cloud_reports import CloudReportsWidget
from widgets import FrozenLeftTable


def _usage(day: date, total: float = 120) -> MonthlyUsage:
    return MonthlyUsage(
        device_slot=0,
        period_start=day,
        period_end=day,
        total=total,
        a3_color=10,
        a3_bw=5,
        a4_color=50,
        a4_bw=55,
        scan=12,
        gross_cost=30,
        net_cost=29.4,
        day_count=1,
        incomplete_days=0,
        device_identity="serial:SER-A",
        device_name_snapshot="Sales Printer",
        device_serial_snapshot="SER-A",
        print_color=48,
        print_bw=30,
        copy_color=12,
        copy_bw=30,
        print_a3_color=8,
        print_a4_color=40,
        print_a3_bw=5,
        print_a4_bw=25,
        copy_a3_color=2,
        copy_a4_color=10,
        copy_a3_bw=0,
        copy_a4_bw=30,
        print_available=True,
        copy_available=True,
    )


def _subject(day: date) -> SubjectPeriodUsage:
    return SubjectPeriodUsage(
        device_slot=0,
        period_start=day,
        period_end=day,
        subject_type="user",
        subject_id="u-1",
        subject_name="alice",
        latest_total=500,
        period_usage=75,
        reset_count=0,
        missing_baseline_days=0,
        incomplete_days=0,
        sample_count=2,
        latest_at="2026-08-06T09:00:00+07:00",
        warnings=(),
        device_identity="serial:SER-A",
        device_name_snapshot="Sales Printer",
        device_serial_snapshot="SER-A",
    )


def test_cloud_reports_share_period_and_cross_filter_users_and_printers():
    app = QApplication.instance() or QApplication([])
    day = date(2026, 8, 6)
    widget = CloudReportsWidget()
    periods = (("2026-08-06", "2026-08-06"), ("2026-08-05", "2026-08-05"))
    other_printer = replace(
        _usage(day, 80),
        device_slot=1,
        device_identity="serial:SER-B",
        device_name_snapshot="Archive Printer",
        device_serial_snapshot="SER-B",
    )
    prior_month = _usage(date(2026, 7, 1), 300)
    widget.set_periods(periods, periods[0])
    widget.set_data(
        records=(_usage(day),),
        daily_records=(_usage(day),),
        monthly_records=(_usage(day), other_printer, prior_month),
        subjects=(_subject(day),),
        devices=(
            DeviceConfig(
                0,
                "Sales Printer",
                "192.0.2.10",
                serial="SER-A",
                connection_status="online",
                last_total=10_000,
            ),
        ),
        period=periods[0],
        last_sync_at="2026-08-06T09:00:00+07:00",
    )

    assert [widget.tabs.tabText(index) for index in range(widget.tabs.count())] == [
        "Overview",
        "Users",
        "Printers",
        "Usage",
    ]
    assert widget.current_period() == periods[0]
    assert widget.export_button.text() == "ส่งออก Excel"
    exported = []
    widget.export_requested.connect(lambda: exported.append(True))
    widget.export_button.click()
    assert exported == [True]
    assert widget.overview_kpis["color_print"].lbl_val.text() == "48"
    assert widget.overview_kpis["color_print"].lbl_detail.textFormat() == Qt.TextFormat.RichText
    assert "A3" in widget.overview_kpis["color_print"].lbl_detail.text()
    assert widget.overview_kpis["bw_print"].lbl_val.text() == "30"
    assert widget.overview_kpis["color_copy"].lbl_val.text() == "12"
    assert widget.overview_kpis["bw_copy"].lbl_val.text() == "30"
    assert widget.overview_kpis["total_usage"].lbl_val.text() == "120"
    assert widget.overview_kpis["total_usage"].lbl_detail.text() == "ช่วงรายงานที่เลือก"
    assert widget.overview_kpis["total_cost"].lbl_val.text() == "฿29.40"
    assert [widget.usage_tabs.tabText(index) for index in range(widget.usage_tabs.count())] == [
        "ทุกเครื่อง",
        "ตามเครื่อง",
    ]
    assert len(widget.period_edit_pairs) == 3
    assert widget.usage_page.findChildren(QDateEdit) == []
    assert widget.usage_monthly_table.rowCount() == 2
    assert widget.usage_monthly_table.item(0, 0).text() == "08/2026"
    assert widget.usage_monthly_table.item(0, 6).text() == "200"
    # The device view is a matrix: one row per period, device names are
    # two-level header groups instead of being repeated in the table body.
    assert widget.usage_by_printer_table.rowCount() == 2
    assert widget.usage_by_printer_table.columnCount() == 15
    assert widget.usage_by_printer_table.item(0, 0).text() == "08/2026"
    assert widget.usage_by_printer_table.item(0, 6).text() == "120"
    assert widget.usage_by_printer_table.item(0, 13).text() == "80"
    matrix = widget.usage_by_printer_table
    assert isinstance(matrix, FrozenLeftTable)
    assert matrix.groupedHeaderItem(0, 0).text() == "เดือน"
    assert matrix.groupedHeaderItem(0, 1).text() == "Slot 1 · Sales Printer"
    assert matrix.groupedHeaderItem(0, 8).text() == "Slot 2 · Archive Printer"
    assert matrix.groupedHeaderSpan(0, 0) == (2, 1)
    matrix._right.horizontalScrollBar().setValue(matrix._right.horizontalScrollBar().maximum())
    assert matrix.item(0, 0).text() == "08/2026"
    assert matrix._left.x() == 0

    widget._select_user_row(0, 0)
    assert widget.user_filter_badge.text() == "กำลังกรอง: alice"
    widget._select_printer_row(0, 0)
    assert "ทุกเครื่องพร้อมกัน" in widget.printer_compare_note.text()
    assert widget.printer_detail.item(3, 1).text() == "10,000"

    emitted = []
    widget.period_changed.connect(emitted.append)
    start_edit, end_edit = widget.period_edit_pairs[1]
    start_edit.setDate(QDate(2026, 8, 5))
    end_edit.setDate(QDate(2026, 8, 5))
    assert emitted[-1] == periods[1]
    assert all(
        start.date() == QDate(2026, 8, 5) and end.date() == QDate(2026, 8, 5)
        for start, end in widget.period_edit_pairs
    )

    widget.usage_granularity_buttons["D"].click()
    assert widget.usage_monthly_table.horizontalHeaderItem(0).text() == "วัน"
    assert widget.usage_monthly_table.item(0, 0).text() == "06/08/2026"
    assert widget.usage_by_printer_table.rowCount() == 1
    assert widget.usage_by_printer_table.groupedHeaderItem(0, 0).text() == "วัน"
    widget.usage_granularity_buttons["Y"].click()
    assert widget.usage_monthly_table.horizontalHeaderItem(0).text() == "ปี"
    assert widget.usage_monthly_table.item(0, 0).text() == "2026"
    widget.close()
    app.processEvents()


def test_cloud_reports_header_and_date_range_fit_desktop_minimum():
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    widget.resize(794, 900)
    widget.show()
    app.processEvents()

    assert widget.minimumSizeHint().width() <= 794
    assert widget.refresh_button.width() + 4 >= widget.refresh_button.sizeHint().width()
    assert widget.export_button.width() + 4 >= widget.export_button.sizeHint().width()
    assert all(start.width() >= 142 and end.width() >= 142 for start, end in widget.period_edit_pairs)

    widget.close()
    app.processEvents()


def test_printer_charts_compare_all_devices_and_selection_only_changes_detail():
    app = QApplication.instance() or QApplication([])
    day = date(2026, 8, 6)
    first = _usage(day)
    second = replace(
        _usage(day, 80),
        device_slot=1,
        device_identity="serial:SER-B",
        device_name_snapshot="Archive Printer",
        device_serial_snapshot="SER-B",
    )
    widget = CloudReportsWidget()
    widget.set_periods(((day.isoformat(), day.isoformat()),), (day.isoformat(), day.isoformat()))
    widget.set_data(
        records=(first, second),
        daily_records=(first, second),
        subjects=(),
        devices=(
            DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="SER-A", last_total=10_000),
            DeviceConfig(1, "Archive Printer", "192.0.2.11", serial="SER-B", last_total=20_000),
        ),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
    )

    def chart_labels(chart):
        return [bar_set.label() for bar_set in chart.series()[0].barSets()]

    expected = ["Sales Printer", "Archive Printer"]
    assert chart_labels(widget.printer_mix.chart()) == expected
    assert chart_labels(widget.printer_trend.chart()) == expected
    widget._select_printer_row(1, 0)
    assert widget.printer_detail.item(0, 1).text() == "Archive Printer"
    assert chart_labels(widget.printer_mix.chart()) == expected
    assert chart_labels(widget.printer_trend.chart()) == expected
    widget.close()
    app.processEvents()


def test_keyboard_selection_updates_user_filter_and_printer_detail_immediately():
    app = QApplication.instance() or QApplication([])
    day = date(2026, 8, 6)
    second = replace(
        _usage(day, 80),
        device_slot=1,
        device_identity="serial:SER-B",
        device_name_snapshot="Archive Printer",
        device_serial_snapshot="SER-B",
    )
    widget = CloudReportsWidget()
    widget.set_periods(((day.isoformat(), day.isoformat()),), (day.isoformat(), day.isoformat()))
    widget.set_data(
        records=(_usage(day), second),
        daily_records=(_usage(day), second),
        subjects=(_subject(day),),
        devices=(
            DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="SER-A", last_total=10_000),
            DeviceConfig(1, "Archive Printer", "192.0.2.11", serial="SER-B", last_total=20_000),
        ),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
    )

    widget.users_table.setCurrentCell(0, 0)
    app.processEvents()
    assert widget.user_filter_badge.text() == "กำลังกรอง: alice"

    widget.printers_table.setCurrentCell(1, 0)
    app.processEvents()
    assert widget.printer_detail.item(0, 1).text() == "Archive Printer"
    widget.close()
    app.processEvents()


def test_empty_users_offer_a_reading_status_recovery_action():
    app = QApplication.instance() or QApplication([])
    day = date(2026, 8, 6)
    widget = CloudReportsWidget()
    widget.set_periods(((day.isoformat(), day.isoformat()),), (day.isoformat(), day.isoformat()))
    widget.set_data(
        records=(_usage(day),),
        daily_records=(_usage(day),),
        subjects=(),
        devices=(DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="SER-A"),),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
    )
    requests = []
    widget.reading_status_requested.connect(lambda: requests.append(True))

    assert not widget.user_recovery_button.isHidden()
    widget.user_recovery_button.click()
    assert requests == [True]
    widget.close()
    app.processEvents()


def test_cloud_reports_use_transparent_label_surfaces_and_consistent_table_alignment():
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()

    left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    table = widget.users_table
    assert "QWidget#cloud_reports QLabel{background:transparent;border:none;}" in widget.styleSheet()
    assert widget.overview_kpi_panel.objectName() == "cloud_overview_kpi_panel"
    assert widget.overview_kpis["color_print"].objectName() == "cloud_overview_metric_card"
    assert "background:transparent" in widget.overview_kpis["color_print"].lbl_val.styleSheet()
    assert not table.alternatingRowColors()
    assert table.verticalHeader().defaultSectionSize() == 34
    assert table.horizontalHeaderItem(0).textAlignment() == left
    assert table.horizontalHeaderItem(2).textAlignment() == right

    widget._fill_table(table, [("  Alpha Printer  ", "online", "100", "200", "1", "301", "75.00")])
    assert table.item(0, 0).text() == "Alpha Printer"
    assert table.item(0, 0).textAlignment() == left
    assert table.item(0, 2).textAlignment() == right

    widget.close()
    app.processEvents()
