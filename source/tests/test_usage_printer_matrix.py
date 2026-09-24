"""Customer-facing comparison, independent expansion and shared period scrolling."""
from dataclasses import replace
from datetime import date

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from config import build_qss
from services.device_config import DeviceConfig
from test_cloud_reports_ui import _usage
from ui.cloud_reports import CloudReportsWidget


@pytest.fixture
def matrix():
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    records = tuple(replace(_usage(date(2026, month, 1)), device_slot=slot)
                    for month in (1, 2, 3) for slot in range(3)
                    if (month, slot) != (2, 1))
    devices = tuple(DeviceConfig(slot, f'Printer {slot + 1}', f'192.0.2.{slot + 10}')
                    for slot in range(3))
    widget.set_data(records=records, daily_records=records, usage_daily_records=records,
                    monthly_records=records, subjects=(), devices=devices,
                    period=('2026-01-01', '2026-03-31'), last_sync_at=None)
    widget.tabs.setCurrentIndex(3)
    widget.usage_tabs.setCurrentIndex(1)
    yield app, widget, records, devices
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_months_share_one_axis_and_missing_period_is_not_zero(matrix):
    _, widget, _, _ = matrix
    table = widget.usage_printer_table
    assert table.columnCount() == 13
    assert table.rowCount() == 3
    assert [table.item(row, 0).text() for row in range(3)] == ['03/2026', '02/2026', '01/2026']
    assert [table.item(0, col).text() for col in range(1, 5)] == ['78', '42', '12', '29.40']
    assert [table.item(1, col).text() for col in range(5, 9)] == ['—'] * 4
    assert table.item(1, 9).text() == '78'
    assert table.groupedHeaderSpan(0, 1) == (1, 4)
    assert table.groupedHeaderItem(0, 1).text() == 'Slot 1 · Printer 1'


def test_expand_independently_without_reloading_or_reaggregating(matrix, monkeypatch):
    _, widget, _, _ = matrix
    table = widget.usage_printer_table
    monkeypatch.setattr(widget, '_usage_records', lambda *_: pytest.fail('Expansion must reuse loaded data'))
    table.toggle_buttons['slot:1'].click()
    assert table.columnCount() == 21
    assert table.printer_columns == {'slot:0': (1, 4), 'slot:1': (5, 12), 'slot:2': (17, 4)}
    assert table.groupedHeaderSpan(1, 1) == (2, 1)
    assert table.groupedHeaderSpan(1, 5) == (1, 5)
    assert [table.item(0, col).text() for col in range(5, 10)] == ['8', '5', '40', '25', '0']
    assert table.item(0, 16).text() == '29.40'
    table.toggle_buttons['slot:2'].click()
    assert table.columnCount() == 29
    table.toggle_buttons['slot:1'].click()
    assert table.columnCount() == 21
    assert widget._expanded_usage_printers == {'slot:2'}
    assert table.toggle_buttons['slot:2'].text() == '−'
    assert table.toggle_buttons['slot:1'].text() == '+'


def test_expansion_survives_filter_and_refresh_and_empty_selection(matrix):
    _, widget, records, devices = matrix
    table = widget.usage_printer_table
    table.toggle_buttons['slot:1'].click()
    widget.usage_device_filters[1].setChecked(False)
    assert table.columnCount() == 9
    widget.usage_device_filters[1].setChecked(True)
    assert table.columnCount() == 21
    widget.set_data(records=records, daily_records=records, monthly_records=records,
                    subjects=(), devices=devices, period=('2026-01-01', '2026-03-31'), last_sync_at=None)
    assert table.toggle_buttons['slot:1'].isChecked()
    for checkbox in widget.usage_device_filters.values():
        checkbox.setChecked(False)
    assert table.columnCount() == 1
    assert table.rowCount() == 1
    assert not table.toggle_buttons
    widget.usage_device_filters[1].setChecked(True)
    assert table.columnCount() == 13
    assert table.rowCount() == 2


@pytest.mark.parametrize('granularity,label,rows,print_total', [
    ('D', 'วัน', 3, '78'), ('M', 'เดือน', 3, '78'), ('Y', 'ปี', 1, '234'),
])
def test_period_modes_and_waste_cost_remain_correct(matrix, granularity, label, rows, print_total):
    _, widget, _, _ = matrix
    widget.usage_granularity_buttons[granularity].click()
    table = widget.usage_printer_table
    assert table.rowCount() == rows
    assert table.groupedHeaderItem(0, 0).text() == label
    assert table.item(0, 1).text() == print_total
    widget.usage_waste_checkbox.setChecked(False)
    assert table.item(0, 4).text() == ('90.00' if granularity == 'Y' else '30.00')
    table.toggle_buttons['slot:0'].click()
    assert table.item(0, 12).text() == ('90.00' if granularity == 'Y' else '30.00')


def test_unknown_operation_and_price_remain_unavailable(matrix):
    _, widget, records, devices = matrix
    record = replace(records[0], print_available=False, print_a3_color=0, print_a3_bw=0,
                     print_a4_color=0, print_a4_bw=0, print_other=0,
                     provisional_cost_available=False, scan=0)
    widget.set_data(records=(record,), daily_records=(record,), monthly_records=(record,),
                    subjects=(), devices=devices, period=('2026-01-01', '2026-01-31'), last_sync_at=None)
    table = widget.usage_printer_table
    assert [table.item(0, col).text() for col in range(1, 5)] == ['—', '42', '0', '—']
    table.toggle_buttons['slot:0'].click()
    assert [table.item(0, col).text() for col in range(1, 6)] == ['—'] * 5
    assert table.item(0, 12).text() == '—'


def test_one_year_rows_and_headers_stay_aligned_when_scrolling(matrix):
    app, widget, _, devices = matrix
    records = tuple(replace(_usage(date(year, month, 1)), device_slot=slot)
                    for year in (2025,) for month in range(1, 13) for slot in range(3))
    widget.set_data(records=records, daily_records=records, monthly_records=records,
                    subjects=(), devices=devices, period=('2025-01-01', '2025-12-31'), last_sync_at=None)
    widget.setStyleSheet(build_qss())
    # A 900px report area leaves room for three readable summary groups.
    # Narrower areas may scroll rather than clipping names or numeric values.
    widget.resize(900, 640)
    widget.show()
    QTest.qWait(80)
    table = widget.usage_printer_table
    assert table.rowCount() == 12
    assert table._right.horizontalScrollBar().maximum() == 0, {
        'table': table.width(), 'viewport': table._right.viewport().width(),
        'widths': [table._right.columnWidth(c) for c in range(12)],
        'font': table._right.font().toString(),
    }
    # Keyboard activation must work as well as mouse clicks.
    table.toggle_buttons['slot:1'].setFocus()
    QTest.keyClick(table.toggle_buttons['slot:1'], Qt.Key.Key_Space)
    QTest.qWait(40)
    assert table.toggle_buttons['slot:1'].isChecked()
    assert table._right.horizontalScrollBar().maximum() > 0
    table._right.horizontalScrollBar().setValue(table._right.horizontalScrollBar().maximum())
    table._vsb.setValue(table._vsb.maximum())
    app.processEvents()
    assert table._group_right.horizontalScrollBar().value() == table._right.horizontalScrollBar().value()
    assert table._left.rowAt(1) == table._right.rowAt(1)
    row = table._right.rowAt(1)
    assert table._left.rowViewportPosition(row) == table._right.rowViewportPosition(row)
    assert table._group_header.isVisible()
