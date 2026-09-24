from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from excel_export_fixture import report_for
from services.report_models import build_user_rows
from ui.cloud_reports import CloudReportsWidget


def priced_report():
    report = report_for(users=2, days=4, printers=3)
    costs = tuple(replace(cost, **{field: getattr(cost, field) * 2
        for field in ('a4_color', 'a4_bw', 'a3_color', 'a3_bw')})
        if cost.device_slot == 1 else cost for cost in report.category_costs)
    return replace(report, category_costs=costs)


def test_user_cost_uses_each_printers_daily_allocation_and_requires_complete_evidence():
    report = priced_report()
    rows = build_user_rows(report.subjects, report.raw_counter_records, category_costs=report.category_costs)
    assert [rows[0]['by_slot'][i]['cost'] for i in range(3)] == [64, 128, 64]
    assert all(value['cost_available'] for value in rows[0]['by_slot'].values())
    missing_day = tuple(cost for cost in report.category_costs if not (
        cost.device_slot == 1 and cost.record_date.isoformat() == report.period[0]))
    rows = build_user_rows(report.subjects, report.raw_counter_records, category_costs=missing_day)
    assert rows[0]['by_slot'][0]['cost_available']
    assert not rows[0]['by_slot'][1]['cost_available']
    incomplete = tuple(replace(subject, period_usage=subject.period_usage + 1) for subject in report.subjects)
    rows = build_user_rows(incomplete, report.raw_counter_records, category_costs=report.category_costs)
    assert not any(value['cost_available'] for value in rows[0]['by_slot'].values())
    unallocated = tuple(replace(cost, unallocated=10) for cost in report.category_costs)
    rows = build_user_rows(report.subjects, report.raw_counter_records, category_costs=unallocated)
    assert not any(value['cost_available'] for value in rows[0]['by_slot'].values())
    rows = build_user_rows(tuple(replace(subject, period_usage=0) for subject in report.subjects),
        tuple(replace(record, delta_value=0) for record in report.raw_counter_records))
    assert all(value['cost_available'] and value['cost'] == 0 for value in rows[0]['by_slot'].values())


def test_users_overview_and_printer_views_keep_selection_and_independent_detail():
    app = QApplication.instance() or QApplication([])
    report = priced_report()
    widget = CloudReportsWidget()
    widget.set_data(records=report.selected_records, daily_records=report.selected_daily_records,
        subjects=report.subjects, devices=report.devices, period=report.period, last_sync_at=None,
        raw_counter_records=report.raw_counter_records, category_costs=report.category_costs)
    widget.tabs.setCurrentIndex(1)
    table = widget.users_table
    assert table.columnCount() == 14
    assert table.item(0, 1).text() == '12'  # Print A3 color across all three slots
    assert table.item(0, 12).text() == '96'
    assert table.item(0, 13).text() == '256.00'
    assert widget.users_top_chart.height() == widget.users_printer_chart.height() == 150
    table._left.setCurrentCell(1, 0)
    selected = table.item(1, 0).data(Qt.ItemDataRole.UserRole)
    widget.user_printers_button.click()
    assert widget._selected_user == selected
    assert table.columnCount() == 16  # five summary columns per printer
    assert [table.item(0, col).text() for col in (5, 10, 15)] == ['64.00', '128.00', '64.00']
    table.toggle_buttons['slot:1'].click()
    assert table.printer_columns['slot:0'][1] == 5
    assert table.printer_columns['slot:1'][1] == 13
    assert table.printer_columns['slot:2'][1] == 5
    widget.user_overview_button.click()
    assert widget._selected_user == selected
    assert table._left.currentRow() == 1
    table.toggle_buttons['all'].click()
    assert table.columnCount() == 6
    assert table.item(0, 1).text() == '48'
    assert table.item(0, 5).text() == '256.00'
    widget.close()
    app.processEvents()


def test_users_aggregate_cost_does_not_show_partial_total():
    app = QApplication.instance() or QApplication([])
    report = priced_report()
    widget = CloudReportsWidget()
    widget.set_data(records=(), daily_records=(), subjects=report.subjects,
        devices=report.devices, period=report.period, last_sync_at=None,
        raw_counter_records=report.raw_counter_records,
        category_costs=tuple(cost for cost in report.category_costs if cost.device_slot != 1))
    widget.tabs.setCurrentIndex(1)
    assert widget.users_table.item(0, 13).text() == '—'
    assert widget.users_table.item(0, 13).toolTip()
    widget.close()
    app.processEvents()
