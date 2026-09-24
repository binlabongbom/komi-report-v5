"""Keep navigation work bounded without dropping data or historical price rules."""
from contextlib import contextmanager
from datetime import date, timedelta
from threading import Event
import sqlite3

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository
from ui.cloud_reports import CloudReportsWidget
from ui.flow_layout import FlowLabel


def test_report_read_reuses_connection_but_closes_it_at_end(monkeypatch):
    opened = []
    original = database.read_only_connection
    def connect(path):
        connection = original(path)
        opened.append(connection)
        return connection
    monkeypatch.setattr(database, 'read_only_connection', connect)
    database.set_cfg('billing_day', '7')
    with database.report_read_database(database.get_db_path()):
        for _ in range(30):
            with database._open(commit=False) as connection:
                assert connection.execute("SELECT value FROM settings WHERE key='billing_day'").fetchone()[0] == '7'
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            database.set_cfg('billing_day', '9')
        assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        opened[0].execute('SELECT 1')
    database.set_cfg('billing_day', '10')
    with database.report_read_database(database.get_db_path()):
        assert database.get_cfg('billing_day') == '10'
    assert len(opened) == 2


def test_cancelled_report_releases_its_connection_and_context():
    cancelled = Event()
    path = database.get_db_path()
    with pytest.raises(sqlite3.OperationalError, match='interrupted'):
        with database.report_read_database(path, cancelled=cancelled):
            with database._open(commit=False) as connection:
                cancelled.set()
                connection.execute('''WITH RECURSIVE n(x) AS
                    (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT SUM(x) FROM n''').fetchone()
    assert database.get_db_path() == path
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
    database.set_cfg('billing_day', '11')
    assert database.get_cfg('billing_day') == '11'


def test_read_scopes_keep_separate_transactions_and_row_factories():
    with database.report_read_database(database.get_db_path()):
        with database._open(commit=False) as first:
            first.execute('BEGIN')
            first.row_factory = sqlite3.Row
            with database._open(commit=False) as nested:
                assert nested is not first
                nested.execute('BEGIN')
                assert nested.execute('SELECT 1').fetchone() == (1,)
            assert first.in_transaction
        with database._open(commit=False) as second:
            assert second is first
            second.execute('BEGIN')
            assert second.execute('SELECT 2').fetchone() == (2,)


def test_price_batch_keeps_effective_dates_and_reads_once(monkeypatch):
    import services.pricing as pricing
    DeviceConfigRepository().replace_all([DeviceConfig(i, f'Fixture {i}', f'192.0.2.{i+10}') for i in range(3)])
    repository = PricingRepository()
    repository.set_prices(0, date(2021, 1, 1), PriceList(a4_color=2, a3_color=4))
    repository.set_prices(0, date(2024, 7, 1), PriceList(a4_color=3, a3_color=5))
    repository.set_prices(1, date(2023, 1, 1), PriceList(a4_bw=.5))
    requests = [(slot, date(2021, 1, 1) + timedelta(days=i)) for slot in range(3) for i in range(1826)]
    boundaries = [(0, date(2020, 12, 31)), (0, date(2024, 6, 30)), (0, date(2024, 7, 1)),
                  (1, date(2022, 12, 31)), (1, date(2023, 1, 1)), (2, date(2025, 1, 1))]
    expected = {key: repository.get_prices(*key) for key in boundaries}
    opened = []
    original = pricing._open
    @contextmanager
    def counted(*args, **kwargs):
        opened.append(True)
        with original(*args, **kwargs) as connection:
            yield connection
    monkeypatch.setattr(pricing, '_open', counted)
    result = repository.get_prices_for_days(requests + boundaries)
    assert len(opened) == 1
    assert all(result[key] == prices for key, prices in expected.items())
    assert len(result) == len(set(requests + boundaries))
    assert repository.get_prices_for_days([]) == {}
    assert len(opened) == 1


def test_new_report_tabs_inherit_styles_without_restyling_existing_pages(monkeypatch):
    widget = CloudReportsWidget(staged=True)
    widget.resize(1280, 850)
    widget.show()
    QTest.qWait(80)
    original = widget.styleSheet()
    reapplied = []
    monkeypatch.setattr(widget, 'setStyleSheet', reapplied.append)
    for index in (1, 2, 3, 4):
        widget.tabs.setCurrentIndex(index)
        QTest.qWait(30)
        widget._apply_responsive_layout()
    assert widget.styleSheet() == original
    assert not reapplied
    widget.close()


def test_legend_measurement_cache_tracks_text_and_font():
    app = QApplication.instance() or QApplication([])
    label = FlowLabel('Slot 1')
    small = label.sizeHint()
    assert label.sizeHint() == small
    label.setText('Slot 1 · KM bizhub C450i Test')
    longer = label.sizeHint()
    assert longer.width() > small.width()
    font = label.font()
    font.setPointSize(font.pointSize() + 6)
    label.setFont(font)
    assert label.sizeHint().height() > longer.height()
    label.close()


def test_compact_tabs_resize_buttons_without_restyling_page_tree(monkeypatch):
    from PyQt6.QtWidgets import QWidget
    from ui.page_tabs import PageTabs
    tabs = PageTabs()
    tabs.addTab(QWidget(), 'Reports')
    tabs.resize(900, 650)
    tabs.show()
    QTest.qWait(30)
    initial = tabs.tabBar().tabRect(0).height()
    root_style = tabs.styleSheet()
    monkeypatch.setattr(tabs, 'setStyleSheet', lambda *_: pytest.fail('Do not repolish hidden pages'))
    tabs.set_compact(True)
    QTest.qWait(30)
    assert tabs.tabBar().tabRect(0).height() < initial
    assert tabs.styleSheet() == root_style
    tabs.set_compact(False)
    QTest.qWait(30)
    assert tabs.tabBar().tabRect(0).height() == initial
    tabs.close()


def test_total_only_users_keep_unknown_cost_without_daily_recalculation(monkeypatch):
    from dataclasses import replace
    from excel_export_fixture import report_for
    from services.report_models import build_user_rows
    import services.report_user_costs as costs
    report = report_for(users=1, days=30, printers=1)
    raw = tuple(replace(row, canonical_field='counter.user.total.total', label='User Total')
                for row in report.raw_counter_records if row.is_subject)
    monkeypatch.setattr(costs, 'subject_costs', lambda *_a, **_k: pytest.fail('Unclassified totals have no category cost to calculate'))
    rows = build_user_rows(report.subjects, raw, category_costs=report.category_costs)
    assert rows and rows[0]['usage'] > 0
    assert not rows[0]['by_slot'][0]['cost_available']
