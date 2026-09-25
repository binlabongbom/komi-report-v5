"""Configured printers remain visible without inventing usage for missing periods."""
from dataclasses import replace

import pytest
from excel_export_fixture import report_for
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from i18n import set_language
from services.report_models import build_printer_rows
from ui.cloud_reports import CloudReportsWidget


def show_report(records, devices, period, *, prepared=False):
    widget = CloudReportsWidget()
    models = {'printers': build_printer_rows(records, devices)} if prepared else {}
    widget.set_data(records=records, daily_records=records, subjects=(), devices=devices,
                    period=period, last_sync_at=None, prepared_models=models)
    widget.tabs.setCurrentIndex(2)
    return widget


@pytest.mark.parametrize('prepared', [False, True])
@pytest.mark.parametrize('language', ['th', 'en'])
def test_printer_with_no_period_entries_stays_visible_without_changing_totals(prepared, language):
    app = QApplication.instance() or QApplication([])
    set_language(language)
    report = report_for(users=2, days=1, printers=3)
    records = report.selected_records[:2]
    devices = tuple(replace(device, connection_status='online') for device in report.devices)
    widget = show_report(records, devices, report.period, prepared=prepared)
    try:
        table = widget.printers_table
        assert table.rowCount() == 3
        assert table.item(2, 0).text() == 'Slot 3 · Fixture 3'
        assert table.item(2, 0).data(Qt.ItemDataRole.UserRole) == 'serial:SYNTH-2'
        assert table.item(2, 1).text() == ('ไม่มีรายการในช่วงนี้' if language == 'th' else 'No entries in this period')
        assert [table.item(2, column).text() for column in range(2, 9)] == ['—'] * 7
        assert 'online' in table.item(2, 1).toolTip()
        assert len(widget._printer_rows) == 2
        assert sum(row['total'] for row in widget._printer_rows) == 32
        assert len(widget.printer_trend.chart().series()[0].barSets()) == 4
    finally:
        widget.close()
        app.processEvents()


def test_missing_period_and_observed_zero_remain_different_and_disabled_roster_is_hidden():
    app = QApplication.instance() or QApplication([])
    set_language('en')
    report = report_for(users=0, days=1, printers=3)
    devices = tuple(replace(device, enabled=index != 1, connection_status='online')
                    for index, device in enumerate(report.devices))
    widget = show_report((), devices, report.period)
    try:
        table = widget.printers_table
        assert table.rowCount() == 2
        assert [table.item(row, 0).text() for row in range(2)] == ['Slot 1 · Fixture 1', 'Slot 3 · Fixture 3']
        assert table.item(1, 7).text() == '—'
        widget.set_data(records=(report.selected_records[2],), daily_records=(), subjects=(), devices=devices,
                        period=report.period, last_sync_at=None)
        assert table.rowCount() == 2
        assert table.item(0, 0).text() == 'Slot 3 · Fixture 3'
        assert table.item(0, 1).text() == 'Online'
        assert table.item(0, 7).text() == '0'
        assert table.item(0, 8).text() == '0.00'
    finally:
        widget.close()
        app.processEvents()


def test_replaced_printer_history_keeps_its_name_and_current_printer_has_separate_missing_row():
    app = QApplication.instance() or QApplication([])
    report = report_for(users=2, days=1, printers=1)
    current = replace(report.devices[0], name='Replacement', serial='NEW-SERIAL')
    widget = show_report(report.selected_records, (current,), report.period)
    try:
        table = widget.printers_table
        assert table.rowCount() == 2
        assert table.item(0, 0).text() == 'Slot 1 · Fixture 1'
        assert table.item(0, 7).text() == '16'
        assert table.item(1, 0).text() == 'Slot 1 · Replacement'
        assert table.item(1, 7).text() == '—'
        # Legacy slot-only identities already represent the current slot.
        legacy = replace(report.selected_records[0], device_identity='slot:0')
        widget.set_data(records=(legacy,), daily_records=(), subjects=(), devices=(current,),
                        period=report.period, last_sync_at=None)
        assert table.rowCount() == 1
    finally:
        widget.close()
        app.processEvents()
