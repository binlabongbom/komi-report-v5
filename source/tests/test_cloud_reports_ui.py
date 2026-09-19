import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import date

import pytest
from PyQt6.QtCharts import QBarSeries
from PyQt6.QtCore import QDate, QLocale, QPoint, Qt, QTimer
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QDateEdit, QPushButton, QTableView, QToolButton

from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.raw_counter_history import RawCounterDailyRecord, UsageMeterBaseline
from services.subject_history import SubjectPeriodUsage
from ui.cloud_reports import USAGE_METRICS, CloudReportsWidget
from widgets import FrozenLeftTable


@pytest.mark.parametrize("field,target", [("start", QDate(2026, 8, 15)), ("end", QDate(2026, 10, 15))])
def test_calendar_month_menu_and_day_click_allow_dates_outside_report_history(field, target):
    qt_app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    history = (("2026-09-01", "2026-09-30"),)
    widget.set_periods(history, history[0])
    widget.resize(1000, 720)
    widget.show()
    qt_app.processEvents()
    QTest.qWait(20)
    start, end = widget.period_edit_pairs[0]
    editor = start if field == "start" else end
    calendar = editor.calendarWidget()
    calendar.setLocale(QLocale(QLocale.Language.English))
    changed = QSignalSpy(widget.period_changed)
    QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=editor.rect().center())
    qt_app.processEvents()
    assert calendar.isVisible()
    month_button = calendar.findChild(QToolButton, "qt_calendar_monthbutton")
    assert month_button is not None
    menu = month_button.menu()
    assert menu is not None
    interaction = {}

    def choose_month():
        # A native menu can enter a nested event loop. Record failures here;
        # assertions belong outside Qt callbacks to avoid aborting the process.
        try:
            actions = [action for action in menu.actions() if not action.isSeparator()]
            interaction["visible"] = menu.isVisible()
            interaction["action_count"] = len(actions)
            action = actions[target.month() - 1]
            interaction["enabled"] = action.isEnabled()
            if action.isEnabled():
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        except Exception as error:
            interaction["error"] = repr(error)
        finally:
            menu.close()

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(menu.close)
    watchdog.start(1000)
    QTimer.singleShot(0, choose_month)
    QTest.mouseClick(month_button, Qt.MouseButton.LeftButton, pos=month_button.rect().center())
    qt_app.processEvents()
    watchdog.stop()
    assert "error" not in interaction, interaction
    assert interaction.get("visible"), interaction
    assert interaction.get("action_count") == 12, interaction
    assert interaction.get("enabled"), "Month selection must not be disabled by the available history range"
    assert (calendar.yearShown(), calendar.monthShown()) == (target.year(), target.month())
    assert len(changed) == 0, "Changing the displayed month must not change the report period yet"
    view = calendar.findChild(QTableView, "qt_calendar_calendarview")
    assert view is not None
    model = view.model()
    day_cells = [
        model.index(row, column)
        for row in range(model.rowCount())
        for column in range(model.columnCount())
        if str(model.index(row, column).data()) == str(target.day())
    ]
    assert len(day_cells) == 1
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(day_cells[0]).center())
    qt_app.processEvents()
    assert editor.date() == target
    assert not calendar.isVisible()
    expected = ("2026-08-15", "2026-09-30") if field == "start" else ("2026-09-01", "2026-10-15")
    assert len(changed) == 1
    assert changed[0][0] == expected
    assert widget.current_period() == expected
    assert len(widget.period_edit_pairs) == 4
    for pair in widget.period_edit_pairs:
        for control in pair:
            assert control.minimumDate() <= QDate(2026, 8, 15)
            assert control.maximumDate() >= QDate(2026, 10, 15)
        assert pair[0].date().toString("yyyy-MM-dd") == expected[0]
        assert pair[1].date().toString("yyyy-MM-dd") == expected[1]
    widget.close()


def test_custom_calendar_range_survives_history_refresh_and_empty_report_data():
    qt_app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    history = (("2026-09-01", "2026-09-30"),)
    widget.set_periods(history, history[0])
    start, end = widget.period_edit_pairs[0]
    start.setDate(QDate(2026, 8, 15))
    end.setDate(QDate(2026, 10, 15))
    expected = ("2026-08-15", "2026-10-15")
    assert widget.current_period() == expected
    changes = QSignalSpy(widget.period_changed)
    for refreshed_history in (history, (), (("2026-09-07", "2026-09-07"),)):
        widget.set_periods(refreshed_history, widget.current_period())
        widget.set_data(
            records=(), daily_records=(), monthly_records=(), subjects=(), devices=(),
            period=widget.current_period(), last_sync_at=None,
        )
        for index in (1, 2, 4, 0):
            widget.tabs.setCurrentIndex(index)
        qt_app.processEvents()
        assert widget.current_period() == expected
        for first, last in widget.period_edit_pairs:
            assert first.date() == QDate(2026, 8, 15)
            assert last.date() == QDate(2026, 10, 15)
    assert len(changes) == 0, "History refresh must not emit a replacement selection"
    widget.close()


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


def _raw(
    day: date,
    *,
    slot: int,
    field: str,
    label: str,
    delta: float,
    subject: bool = False,
) -> RawCounterDailyRecord:
    return RawCounterDailyRecord(
        device_slot=slot,
        record_date=day,
        canonical_field=field,
        label=label,
        source_path="/wcd/system_counter.xml",
        subject_type="user" if subject else "",
        subject_id="u-1" if subject else "",
        subject_name="alice" if subject else "",
        opening_value=100,
        closing_value=100 + delta,
        delta_value=delta,
        reset_count=0,
        sample_count=2,
        first_success="2026-08-06T08:00:00+07:00",
        last_success="2026-08-06T09:00:00+07:00",
        source_name="legacy_xml",
        device_name_snapshot=f"MFP {slot + 1}",
        device_serial_snapshot=f"SER-{slot + 1}",
        incomplete=False,
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
        raw_counter_records=(
            _raw(day, slot=0, field="paper.a5", label="A5", delta=7),
            _raw(day, slot=1, field="fax.total", label="FAX", delta=2),
            _raw(day, slot=0, field="paper.a5", label="A5", delta=5, subject=True),
        ),
    )

    assert [widget.tabs.tabText(index) for index in range(widget.tabs.count())] == [
        "Overview",
        "Users",
        "Printers",
        "Usage",
        "Legacy",
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
    widget.tabs.setCurrentIndex(3)
    assert [widget.usage_tabs.tabText(index) for index in range(widget.usage_tabs.count())] == [
        "ทุกเครื่อง",
        "ตามเครื่อง",
    ]
    assert len(widget.period_edit_pairs) == 4
    assert widget.usage_page.findChildren(QDateEdit) == []
    assert widget.usage_monthly_table.rowCount() == 2
    assert widget.usage_monthly_table.item(0, 0).text() == "08/2026"
    assert isinstance(widget.usage_monthly_table, FrozenLeftTable)
    assert widget.usage_monthly_table.groupedHeaderItem(0, 1).text() == "Print"
    assert widget.usage_monthly_table.groupedHeaderSpan(0, 1) == (1, 5)
    assert widget.usage_monthly_table.groupedHeaderItem(0, 6).text() == "Copy"
    assert widget.usage_monthly_table.groupedHeaderSpan(0, 6) == (1, 5)
    assert widget.usage_monthly_table.groupedHeaderItem(1, 1).text() == "A3 Color"
    assert widget.usage_waste_checkbox.isChecked()
    assert widget.usage_waste_checkbox.text() == "คิดรวม % กระดาษเสีย"
    total_metric_index = next(
        index for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
        if field == "total"
    )
    cost_metric_index = next(
        index for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
        if field == "cost"
    )
    assert widget.usage_monthly_table.horizontalHeaderItem(
        1 + total_metric_index
    ).text() == "รวม"
    assert widget.usage_monthly_table.item(0, 1 + total_metric_index).text() == "200"
    assert widget.usage_monthly_table.item(0, 1 + cost_metric_index).text() == "58.80"
    widget.usage_waste_checkbox.setChecked(False)
    assert widget.usage_monthly_table.item(0, 1 + cost_metric_index).text() == "60.00"
    assert widget.overview_kpis["total_cost"].lbl_val.text() == "฿30.00"
    assert not widget.include_waste_adjustment()
    widget.usage_waste_checkbox.setChecked(True)
    assert widget.overview_kpis["total_cost"].lbl_val.text() == "฿29.40"
    # The device view is a matrix: one row per period, device names are
    # three-level device/operation/detail headers instead of truncated labels.
    assert widget.usage_by_printer_table.rowCount() == 2
    metric_count = len(USAGE_METRICS)
    assert widget.usage_by_printer_table.columnCount() == 1 + 2 * metric_count
    assert widget.usage_by_printer_table.item(0, 0).text() == "08/2026"
    assert widget.usage_by_printer_table.item(
        0, 1 + total_metric_index
    ).text() == "120"
    assert widget.usage_by_printer_table.item(
        0, 1 + metric_count + total_metric_index
    ).text() == "80"
    matrix = widget.usage_by_printer_table
    assert isinstance(matrix, FrozenLeftTable)
    assert matrix.groupedHeaderItem(0, 0).text() == "เดือน"
    assert matrix.groupedHeaderItem(0, 1).text() == "Slot 1 · Sales Printer"
    assert matrix.groupedHeaderItem(0, 1 + metric_count).text() == (
        "Slot 2 · Archive Printer"
    )
    assert matrix.groupedHeaderSpan(0, 0) == (3, 1)
    assert matrix.groupedHeaderItem(1, 1).text() == "Print"
    assert matrix.groupedHeaderItem(2, 1).text() == "A3 Color"
    matrix._right.horizontalScrollBar().setValue(matrix._right.horizontalScrollBar().maximum())
    assert matrix.item(0, 0).text() == "08/2026"
    assert matrix._left.x() == 0
    widget.tabs.setCurrentIndex(4)
    assert widget.legacy_machine_table.horizontalHeaderItem(0).text() == "กลุ่มงาน"
    assert widget.legacy_machine_table.horizontalHeaderItem(1).text() == (
        "ประเภท Counter (ชื่อจากเครื่อง)"
    )
    assert widget.legacy_machine_table.item(0, 1).text() == "A5"
    assert widget.legacy_machine_table.item(0, 2).text() == "7"
    assert widget.legacy_machine_table.item(0, 3).text() == "—"
    assert widget.legacy_machine_table.item(1, 2).text() == "—"
    assert widget.legacy_machine_table.item(1, 3).text() == "2"
    assert widget.legacy_machine_table.item(0, 0).text() == "—"
    assert widget.legacy_user_table.item(0, 0).text() == "alice (user)"
    assert widget.legacy_user_table.item(0, 1).text() == "5"
    assert widget.legacy_daily_table.item(0, 0).text() == "06/08/2026"

    widget.tabs.setCurrentIndex(1)
    widget._select_user_row(0, 0)
    assert widget.user_filter_badge.text() == "กำลังกรอง: alice"
    widget.tabs.setCurrentIndex(2)
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

    widget.tabs.setCurrentIndex(3)
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
    start_edit, _end_edit = widget.period_edit_pairs[0]
    assert start_edit.calendarPopup()
    assert start_edit.lineEdit().isReadOnly()
    assert not start_edit.calendarWidget().isVisible()
    QTest.mouseClick(
        start_edit,
        Qt.MouseButton.LeftButton,
        pos=QPoint(start_edit.width() // 2, start_edit.height() // 2),
    )
    app.processEvents()
    assert start_edit.calendarWidget().isVisible()
    QTest.keyClick(start_edit, Qt.Key.Key_Escape)
    calendar_buttons = [
        button
        for button in widget.findChildren(QPushButton, "cloud_calendar_button")
        if button.text() == "📅"
    ]
    assert len(calendar_buttons) == 8
    for button in calendar_buttons[:2]:
        assert button.width() == button.height() == 24
        assert button.height() <= start_edit.height()
    calendar_buttons[0].click()
    app.processEvents()
    assert start_edit.calendarWidget().isVisible()
    QTest.keyClick(start_edit, Qt.Key.Key_Escape)

    export_requests = QSignalSpy(widget.export_requested)
    date_exports = widget.findChildren(QPushButton, "cloud_period_export")
    assert date_exports == []
    selected_period = (start_edit.date(), _end_edit.date())
    for index in range(widget.tabs.count()):
        widget.tabs.setCurrentIndex(index)
        widget.export_button.click()
        assert len(export_requests) == index + 1
        assert (start_edit.date(), _end_edit.date()) == selected_period

    widget.close()
    app.processEvents()


def test_usage_starts_with_reference_meter_without_counting_it_as_usage_or_cost():
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
    widget.set_data(
        records=(first, second),
        daily_records=(first, second),
        usage_daily_records=(first, second),
        monthly_records=(first, second),
        subjects=(),
        devices=(
            DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="SER-A"),
            DeviceConfig(1, "Archive Printer", "192.0.2.11", serial="SER-B"),
        ),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
        usage_meter_baselines=(
            UsageMeterBaseline(0, date(2026, 7, 1), 10_000, "Sales Printer", "SER-A"),
            UsageMeterBaseline(1, date(2026, 7, 1), 20_000, "Archive Printer", "SER-B"),
        ),
    )
    widget.tabs.setCurrentIndex(3)

    total_index = next(
        index for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
        if field == "total"
    )
    cost_index = next(
        index for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
        if field == "cost"
    )
    assert widget.usage_monthly_table.item(0, 0).text() == "Meter เริ่มต้น"
    assert widget.usage_monthly_table.item(0, 1 + total_index).text() == "30,000"
    assert widget.usage_monthly_table.item(0, 1 + cost_index).text() == "—"
    assert widget.usage_monthly_table.item(0, 1).text() == "—"
    assert widget.usage_monthly_table.item(1, 1 + total_index).text() == "200"
    assert widget.usage_monthly_table.item(1, 1 + cost_index).text() == "58.80"

    metric_count = len(USAGE_METRICS)
    matrix = widget.usage_by_printer_table
    assert matrix.item(0, 0).text() == "Meter เริ่มต้น"
    assert matrix.item(0, 1 + total_index).text() == "10,000"
    assert matrix.item(0, 1 + metric_count + total_index).text() == "20,000"
    assert matrix.item(0, 1 + cost_index).text() == "—"

    # The baseline is display-only. Existing summaries and chart series still
    # contain only actual usage periods.
    assert widget.overview_kpis["total_usage"].lbl_val.text() == "200"
    assert widget.overview_kpis["total_cost"].lbl_val.text() == "฿58.80"
    assert all(points.count() == 1 for series in widget.usage_timeline_chart.chart().series()
               for points in (series.barSets() if isinstance(series, QBarSeries) else [series]))

    widget.usage_granularity_buttons["D"].click()
    assert widget.usage_monthly_table.item(0, 0).text() == "Meter เริ่มต้น"
    assert widget.usage_monthly_table.item(1, 0).text() == "06/08/2026"
    widget.usage_granularity_buttons["Y"].click()
    assert widget.usage_monthly_table.item(0, 0).text() == "Meter เริ่มต้น"
    assert widget.usage_monthly_table.item(1, 0).text() == "2026"
    widget.close()
    app.processEvents()


def test_users_matrix_uses_real_names_and_slot_operation_detail_headers():
    app = QApplication.instance() or QApplication([])
    day = date(2026, 8, 6)
    test_user = replace(_subject(day), subject_id="1", subject_name="TEST1")
    raw_print = replace(
        _raw(
            day,
            slot=0,
            field="counter.print.a3_color",
            label="Print A3 Color",
            delta=9,
            subject=True,
        ),
        subject_id="1",
        subject_name="TEST1",
    )
    widget = CloudReportsWidget()
    widget.set_data(
        records=(_usage(day),),
        daily_records=(_usage(day),),
        subjects=(test_user,),
        devices=(DeviceConfig(0, "KM bizhub C450i", "192.0.2.10", serial="SER-A"),),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
        raw_counter_records=(raw_print,),
    )
    widget.tabs.setCurrentIndex(1)

    table = widget.users_table
    assert table.item(0, 0).text() == "TEST1"
    assert table.groupedHeaderSpan(0, 0) == (3, 1)
    assert table.groupedHeaderItem(0, 1).text() == "Slot 1 · KM bizhub C450i"
    assert table.groupedHeaderItem(1, 1).text() == "Print"
    assert table.groupedHeaderItem(2, 1).text() == "A3 Color"
    assert table.item(0, 1).text() == "9"
    assert table.item(0, 13).text() == "—"  # per-user cost is not inferred
    assert table._right.textElideMode() == Qt.TextElideMode.ElideNone
    widget.close()
    app.processEvents()


def test_usage_all_devices_checkboxes_filter_aggregate_but_keep_per_device_matrix():
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
    widget.set_data(
        records=(first, second),
        daily_records=(first, second),
        usage_daily_records=(first, second),
        monthly_records=(first, second),
        subjects=(),
        devices=(
            DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="SER-A"),
            DeviceConfig(1, "Archive Printer", "192.0.2.11", serial="SER-B"),
        ),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
    )
    widget.tabs.setCurrentIndex(3)
    total_index = next(
        index for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
        if field == "total"
    )
    cost_index = next(
        index for index, (field, _label, _availability) in enumerate(USAGE_METRICS)
        if field == "cost"
    )
    metric_count = len(USAGE_METRICS)
    assert all(box.isChecked() for box in widget.usage_device_filters.values())
    assert widget.usage_monthly_table.item(0, 1 + total_index).text() == "200"

    widget.usage_device_filters[1].setChecked(False)

    assert widget.usage_monthly_table.item(0, 1 + total_index).text() == "120"
    assert widget.usage_monthly_table.item(0, 1 + cost_index).text() == "29.40"
    assert widget.usage_by_printer_table.item(
        0, 1 + metric_count + total_index
    ).text() == "80"
    assert all(points.count() == 1 for series in widget.usage_timeline_chart.chart().series()
               for points in (series.barSets() if isinstance(series, QBarSeries) else [series]))
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
    widget.tabs.setCurrentIndex(2)

    def chart_labels(chart):
        return [bar_set.label() for bar_set in chart.series()[0].barSets()]

    expected_mix = ["Sales Printer", "Archive Printer"]
    expected_trend = [
        "Sales Printer · Print",
        "Sales Printer · Copy",
        "Archive Printer · Print",
        "Archive Printer · Copy",
    ]
    assert chart_labels(widget.printer_mix.chart()) == expected_mix
    assert chart_labels(widget.printer_trend.chart()) == expected_trend
    widget._select_printer_row(1, 0)
    assert widget.printer_detail.item(0, 1).text() == "Archive Printer"
    assert chart_labels(widget.printer_mix.chart()) == expected_mix
    assert chart_labels(widget.printer_trend.chart()) == expected_trend
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

    widget.tabs.setCurrentIndex(1)
    widget.users_table.setCurrentCell(0, 0)
    app.processEvents()
    assert widget.user_filter_badge.text() == "กำลังกรอง: alice"

    widget.tabs.setCurrentIndex(2)
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
    widget.tabs.setCurrentIndex(1)
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
    day = date(2026, 8, 6)
    widget.set_data(
        records=(_usage(day),),
        daily_records=(_usage(day),),
        subjects=(_subject(day),),
        devices=(DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="SER-A"),),
        period=(day.isoformat(), day.isoformat()),
        last_sync_at=None,
    )
    widget.tabs.setCurrentIndex(1)

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

    widget._fill_table(table, [("  TEST1  ", *("100" for _ in range(table.columnCount() - 1)))])
    assert table.item(0, 0).text() == "TEST1"
    assert table.item(0, 0).textAlignment() == left
    assert table.item(0, 2).textAlignment() == right

    widget.close()
    app.processEvents()


@pytest.mark.parametrize("mode", ["classified", "total_only", "missing", "partial_users"])
def test_users_cards_separate_color_without_inventing_missing_counters(mode):
    app = QApplication.instance() or QApplication([])
    day = date(2026, 9, 8)
    widget = CloudReportsWidget()
    subjects = (replace(_subject(day), period_usage=3),)
    if mode == "partial_users":
        subjects += (replace(_subject(day), subject_id="u-2", subject_name="bob", period_usage=1),)
    counters = []
    if mode in ("classified", "partial_users"):
        for operation in ("print", "copy"):
            for family in ("full_color", "bw"):
                field = f"counter.{operation}.{family}_total"
                counters.append(_raw(day, slot=0, field=field, label=field,
                                     delta=3 if operation == "print" and family == "full_color" else 0,
                                     subject=True))
    elif mode == "total_only":
        counters.append(_raw(day, slot=0, field="counter.print.total", label="Print total",
                             delta=3, subject=True))
    widget.set_data(records=(), daily_records=(), subjects=subjects, devices=(),
                    raw_counter_records=counters, period=("2026-09-01", "2026-09-30"),
                    last_sync_at=None)
    widget.tabs.setCurrentIndex(1)
    app.processEvents()
    expected = ("3", "0", "0", "0") if mode == "classified" else ("—",) * 4
    for key, value in zip(("color_print", "bw_print", "color_copy", "bw_copy"), expected):
        card = widget.user_metric_cards[key]
        assert card._full_value == value
        assert card.layout().getItemPosition(card.layout().indexOf(card.lbl_val))[0] == 1
    assert widget.user_metric_cards["usage"]._full_value == ("4" if mode == "partial_users" else "3")
    assert widget.user_metric_cards["count"]._full_value == ("2" if mode == "partial_users" else "1")
    widget.show_error("test error")
    assert all(card._full_value == "—" for card in widget.user_metric_cards.values())
    widget.close()


def test_printer_cards_match_overview_and_preserve_scan_summary():
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    day = date(2026, 8, 6)
    period = (day.isoformat(), day.isoformat())
    widget.set_periods((period,), period)
    widget.set_data(records=(_usage(day),), daily_records=(), subjects=(), devices=(),
                    period=period, last_sync_at=None)
    widget.tabs.setCurrentIndex(2)
    widget.resize(1440, 800)
    widget.show()
    app.processEvents()
    for key in ("color_print", "bw_print", "color_copy", "bw_copy"):
        assert widget.printer_metric_cards[key]._full_value == widget.overview_kpis[key]._full_value
        assert widget.printer_metric_cards[key]._full_detail == widget.overview_kpis[key]._full_detail
    assert "เครื่องที่มีการใช้งาน 1 เครื่อง" in widget.printer_activity_summary.text()
    assert "Scan" in widget.printer_activity_summary.text()
    for width in (1440, 1024):
        widget.resize(width, 760)
        app.processEvents()
        cards = list(widget.printer_metric_cards.values())
        assert len({card.y() for card in cards}) in (1, 2, 3)
        assert len({card.height() for card in cards}) == 1
    widget.show_error("unavailable")
    assert all(card._full_value == "—" for card in widget.printer_metric_cards.values())
    assert "Scan —" in widget.printer_activity_summary.text()
    widget.close()
