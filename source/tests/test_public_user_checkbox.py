"""Users can opt into one shared public identity without losing table state."""

import pytest
from excel_export_fixture import report_for
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from i18n import set_language
from services.report_models import build_user_rows, freeze
from ui.cloud_reports import CloudReportsWidget


@pytest.fixture
def public_report_widget():
    """One public identity over two printers and two named users on the third.

    Classification of real device evidence is covered by the service tests;
    these fixtures exercise presentation of an already classified snapshot.
    """
    app = QApplication.instance() or QApplication([])
    report = report_for(users=2, days=2, printers=3)
    all_rows = build_user_rows(
        report.subjects, report.raw_counter_records, category_costs=report.category_costs
    )
    named_rows = tuple(
        dict(row, by_slot={2: row['by_slot'][2]}, usage=row['by_slot'][2]['total'])
        for row in all_rows
    )
    public_slots = {}
    for slot in (0, 1):
        slot_row = dict(all_rows[0]['by_slot'][slot])
        for field, value in tuple(slot_row.items()):
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                slot_row[field] = sum(row['by_slot'][slot][field] for row in all_rows)
        public_slots[slot] = slot_row
    public_rows = freeze((dict(
        all_rows[0], key='public:all', type='public', name='Public User',
        by_slot=public_slots, usage=sum(slot['total'] for slot in public_slots.values()),
    ),))
    models = {'users': named_rows, 'public_users': public_rows}
    payload = dict(
        records=report.selected_records, daily_records=report.selected_daily_records,
        subjects=(), devices=report.devices, period=report.period, last_sync_at=None,
        raw_counter_records=(), category_costs=report.category_costs, prepared_models=models,
    )
    widget = CloudReportsWidget()
    widget.resize(1400, 900)
    widget.set_data(**payload)
    widget.tabs.setCurrentIndex(1)
    widget.show()
    QTest.qWait(50)
    yield widget, payload
    widget.close()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('language', ['th', 'en'])
@pytest.mark.parametrize('width', [760, 1500])
def test_public_checkbox_precedes_view_buttons_in_one_header_row(public_report_widget, language, width):
    widget, payload = public_report_widget
    set_language(language)
    widget.set_data(**payload)
    widget.resize(width, 900)
    QTest.qWait(50)
    checkbox = widget.public_user_checkbox
    overview = widget.user_overview_button
    printers = widget.user_printers_button
    assert checkbox.text() == 'Public User'
    assert not checkbox.isChecked()
    assert checkbox.isVisible()
    positions = [control.mapTo(widget.users_page, QPoint()) for control in (checkbox, overview, printers)]
    assert positions[0].x() + checkbox.width() <= positions[1].x()
    assert positions[1].x() + overview.width() <= positions[2].x()
    centers = [point.y() + control.height() / 2
               for point, control in zip(positions, (checkbox, overview, printers), strict=True)]
    assert max(centers) - min(centers) <= 2
    assert positions[-1].x() + printers.width() <= widget.users_page.width()
    checkbox.click()
    assert widget.users_table.rowCount() == 3
    assert widget.users_table.item(2, 0).text() == 'Public User'


def test_toggle_uses_prepared_rows_and_preserves_named_selection(public_report_widget, monkeypatch):
    widget, _payload = public_report_widget
    table = widget.users_table
    original_rows = widget._user_rows
    original_cells = tuple(table.item(0, column).text() for column in range(table.columnCount()))
    table._left.setCurrentCell(1, 0)
    selected = table.item(1, 0).data(Qt.ItemDataRole.UserRole)

    def unexpected_rebuild(*_args, **_kwargs):
        pytest.fail('The display toggle must not rebuild report models')

    monkeypatch.setattr(widget, '_build_user_rows', unexpected_rebuild)
    monkeypatch.setattr('ui.cloud_reports.build_user_rows', unexpected_rebuild)
    widget.public_user_checkbox.click()
    assert table.rowCount() == 3
    assert widget._user_rows is original_rows
    assert tuple(table.item(0, column).text() for column in range(table.columnCount())) == original_cells
    assert widget._selected_user == selected
    assert table._left.currentRow() == 1
    assert table.item(2, 12).text() == '64'
    assert table.item(2, 13).text() == '128.00'
    widget.public_user_checkbox.click()
    assert table.rowCount() == 2
    assert widget._selected_user == selected
    assert table._left.currentRow() == 1


def test_one_public_row_keeps_separate_printer_columns_and_hides_cleanly(public_report_widget):
    widget, _payload = public_report_widget
    table = widget.users_table
    widget.public_user_checkbox.click()
    table._left.setCurrentCell(2, 0)
    selected = table.item(2, 0).data(Qt.ItemDataRole.UserRole)
    widget.user_printers_button.click()
    assert table.rowCount() == 3
    assert table.item(2, 0).text() == 'Public User'
    assert set(table.printer_columns) == {'slot:0', 'slot:1', 'slot:2'}
    assert widget._selected_user == selected
    assert table._left.currentRow() == 2
    for slot in range(3):
        start, count = table.printer_columns[f'slot:{slot}']
        assert table.item(2, start + count - 2).text() == ('32' if slot in (0, 1) else '0')
        assert table.item(2, start + count - 1).text() == ('64.00' if slot in (0, 1) else '—')
    # Expanding one printer does not change the other's detail state.
    table.toggle_buttons['slot:0'].click()
    assert table.printer_columns['slot:0'][1] == 13
    assert table.printer_columns['slot:1'][1] == 5
    widget.user_overview_button.click()
    assert table.rowCount() == 3
    assert table.item(2, 0).text() == 'Public User'
    assert table.item(2, 12).text() == '64'
    assert widget._selected_user == selected
    widget.public_user_checkbox.click()
    assert table.rowCount() == 2
    assert widget._selected_user is None
    assert table._left.currentRow() == -1


def test_public_toggle_preserves_full_table_area_and_survives_refresh(public_report_widget):
    widget, payload = public_report_widget
    table = widget.users_table

    def assert_table_fills_page():
        bottom = table.mapTo(widget.users_page, QPoint(0, table.height())).y()
        assert 0 <= widget.users_page.height() - bottom <= 20
        assert widget.tab_scrolls[1].verticalScrollBar().maximum() == 0
        assert table.mapTo(widget.users_page, QPoint()).y() < 120

    assert_table_fills_page()
    widget.public_user_checkbox.click()
    QTest.qWait(100)
    assert_table_fills_page()
    table._left.setCurrentCell(2, 0)
    selected = widget._selected_user
    widget.user_printers_button.click()
    widget.tabs.setCurrentIndex(0)
    widget.tabs.setCurrentIndex(1)
    widget.set_data(**payload)
    QTest.qWait(50)
    assert widget.public_user_checkbox.isChecked()
    assert widget.user_printers_button.isChecked()
    assert table.rowCount() == 3
    assert widget._selected_user == selected
    assert table._left.currentRow() == 2
    assert_table_fills_page()
    initial_height = table.height()
    widget.resize(1400, 1100)
    QTest.qWait(50)
    assert table.height() >= initial_height + 180
    assert_table_fills_page()


def test_missing_public_model_uses_daily_fallback_without_duplicate_named_users(public_report_widget):
    widget, payload = public_report_widget
    without_public = dict(payload, prepared_models={'users': payload['prepared_models']['users']})
    widget.set_data(**without_public)
    widget.public_user_checkbox.click()
    assert widget.public_user_checkbox.isChecked()
    assert widget.users_table.rowCount() == 3
    assert widget.users_table.item(2, 0).text() == 'Public User'
    assert widget.users_table.item(2, 12).text() == '64'
    # Prepared real users already identify slot 3 even when raw subjects are omitted.
    assert set(widget._public_user_rows[0]['by_slot']) == {0, 1}


def test_explicit_empty_public_model_is_respected_without_daily_fallback(public_report_widget):
    widget, payload = public_report_widget
    no_public = dict(payload, prepared_models={
        'users': payload['prepared_models']['users'], 'public_users': (),
    })
    widget.set_data(**no_public)
    widget.public_user_checkbox.click()
    assert widget.public_user_checkbox.isChecked()
    assert widget.users_table.rowCount() == 2
    assert all(widget.users_table.item(row, 0).text() != 'Public User'
               for row in range(widget.users_table.rowCount()))


def test_public_cost_follows_report_waste_basis_in_both_views_without_mutating_snapshot(public_report_widget):
    widget, payload = public_report_widget
    public_rows = freeze(tuple(dict(row, by_slot={
        slot: dict(values, gross_cost=80.0 + slot * 16, net_cost=64.0, cost=64.0)
        for slot, values in row['by_slot'].items()
    }) for row in payload['prepared_models']['public_users']))
    widget.set_data(**dict(payload, prepared_models={
        **payload['prepared_models'], 'public_users': public_rows,
    }))
    widget.public_user_checkbox.click()
    table = widget.users_table
    assert table.rowCount() == 3
    assert table.item(2, 13).text() == '128.00'
    table._left.setCurrentCell(2, 0)
    selected = widget._selected_user

    # The setting lives on Usage but applies when returning to Users as well.
    widget.tabs.setCurrentIndex(3)
    widget.usage_waste_checkbox.setChecked(False)
    widget.tabs.setCurrentIndex(1)
    assert table.item(2, 13).text() == '176.00'
    widget.user_printers_button.click()
    for slot, expected in ((0, '80.00'), (1, '96.00')):
        start, count = table.printer_columns[f'slot:{slot}']
        assert table.item(2, start + count - 1).text() == expected

    widget.tabs.setCurrentIndex(3)
    widget.usage_waste_checkbox.setChecked(True)
    widget.tabs.setCurrentIndex(1)
    assert widget.user_printers_button.isChecked()
    for slot in (0, 1):
        start, count = table.printer_columns[f'slot:{slot}']
        assert table.item(2, start + count - 1).text() == '64.00'
    widget.user_overview_button.click()
    assert table.item(2, 13).text() == '128.00'
    assert widget._selected_user == selected
    # Displaying gross costs must not rewrite cached model amounts for later use.
    assert widget._public_user_rows is public_rows
    for row in public_rows:
        for slot, values in row['by_slot'].items():
            assert (values['cost'], values['net_cost'], values['gross_cost']) == (64.0, 64.0, 80.0 + slot * 16)
