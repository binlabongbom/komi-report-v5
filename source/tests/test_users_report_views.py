from dataclasses import replace

import pytest
from excel_export_fixture import report_for
from PyQt6.QtCharts import QChartView
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

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


@pytest.mark.parametrize('prepared', [False, True])
def test_users_overview_and_printer_views_keep_selection_and_independent_detail(prepared):
    app = QApplication.instance() or QApplication([])
    report = priced_report()
    widget = CloudReportsWidget()
    models = {'users': build_user_rows(report.subjects, report.raw_counter_records,
                                     category_costs=report.category_costs)} if prepared else {}
    widget.set_data(records=report.selected_records, daily_records=report.selected_daily_records,
        subjects=report.subjects, devices=report.devices, period=report.period, last_sync_at=None,
        raw_counter_records=() if prepared else report.raw_counter_records,
        category_costs=report.category_costs, prepared_models=models)
    widget.tabs.setCurrentIndex(1)
    table = widget.users_table
    assert table.columnCount() == 14
    assert table.item(0, 1).text() == '12'  # Print A3 color across all three slots
    assert table.item(0, 12).text() == '96'
    assert table.item(0, 13).text() == '256.00'
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


@pytest.mark.parametrize('language', ['th', 'en'])
@pytest.mark.parametrize('incomplete', [False, True])
def test_users_table_retains_zero_and_incomplete_readings(language, incomplete):
    from i18n import set_language
    set_language(language)
    app = QApplication.instance() or QApplication([])
    report = priced_report()
    subjects = tuple(replace(subject, period_usage=2 if incomplete else 0) for subject in report.subjects)
    counters = tuple(replace(record, delta_value=0) for record in report.raw_counter_records)
    widget = CloudReportsWidget()
    widget.set_data(records=(), daily_records=(), subjects=subjects, devices=report.devices,
        period=report.period, last_sync_at=None, raw_counter_records=counters)
    widget.tabs.setCurrentIndex(1)
    app.processEvents()
    try:
        table = widget.users_table
        assert table.rowCount() == 2
        assert table.item(0, 12).text() == ('6' if incomplete else '0')
        assert table.item(0, 13).text() == ('—' if incomplete else '0.00')
        assert widget.user_recovery_button.isHidden()
        # A following real reading must update the table without recreating its widget.
        widget.set_data(records=(), daily_records=(), subjects=report.subjects, devices=report.devices,
            period=report.period, last_sync_at=None, raw_counter_records=report.raw_counter_records)
        assert widget.users_table is table
        assert table.item(0, 12).text() == '96'
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('language', ['th', 'en'])
@pytest.mark.parametrize('width', [1600, 1000, 760])
def test_users_table_fills_available_area_and_scrolls_inside_sticky_headers(language, width):
    from qt_render_environment import configure_offscreen_fonts

    from i18n import set_language
    set_language(language)
    app = QApplication.instance() or QApplication([])
    configure_offscreen_fonts(app)
    report = report_for(users=40, days=1, printers=3)
    widget = CloudReportsWidget()
    widget.resize(width, 650)
    widget.set_data(records=(), daily_records=(), subjects=report.subjects, devices=report.devices,
        period=report.period, last_sync_at=None, raw_counter_records=report.raw_counter_records)
    widget.tabs.setCurrentIndex(1)
    widget.show()
    QTest.qWait(100)
    try:
        table = widget.users_table
        scroll = widget.tab_scrolls[1]
        assert not widget.users_page.findChildren(QChartView)
        small_height = table.height()
        widget.resize(width, 1050)
        QTest.qWait(100)
        assert table.height() >= small_height + 390
        assert table.height() > 620  # The former maximum must not leave unused space.
        assert scroll.verticalScrollBar().maximum() == 0
        assert table.mapTo(widget.users_page, QPoint()).y() < 100
        bottom_gap = widget.users_page.height() - table.mapTo(widget.users_page, QPoint(0, table.height())).y()
        assert 0 <= bottom_gap <= 20
        assert table.width() >= widget.users_page.width() - 40
        assert table._vsb.maximum() > 0
        header_top = table._group_header.mapTo(table, QPoint()).y()
        table._vsb.setValue(table._vsb.maximum())
        app.processEvents()
        assert table._group_header.mapTo(table, QPoint()).y() == header_top
        assert table._right.rowAt(table._right.viewport().height() - 10) == table.rowCount() - 1
        # Per-printer mode also keeps the same full-height table and all 40 users.
        widget.user_printers_button.click()
        QTest.qWait(50)
        assert table.rowCount() == 40
        assert table.height() >= small_height + 390
        assert scroll.verticalScrollBar().maximum() == 0
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
