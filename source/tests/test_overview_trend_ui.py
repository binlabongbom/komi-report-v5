"""The landing-page chart follows the selected summary, including gaps and zeroes."""
from copy import deepcopy
from datetime import date, timedelta

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from test_overview_v5_ui import _summary

from i18n import set_language
from ui.pages import overview


def wait_for_summary(page):
    for _ in range(400):
        if not page.summary_reader.busy:
            break
        QTest.qWait(5)
    assert not page.summary_reader.busy


def trend_summary(key):
    summary = _summary()
    if key == 'day':
        keys = [(date(2026, 9, 12) + timedelta(days=offset)).isoformat() for offset in range(14)]
        buckets = {day: {'machines': [None, None], 'provisional_machines': [None, None]} for day in keys}
        for day, values, pending in [('2026-09-22', [10, None], [0, None]),
                                     ('2026-09-23', [2, None], [1, None]),
                                     ('2026-09-25', [4, 0], [2, 0])]:
            buckets[day] = {'machines': values, 'provisional_machines': pending}
        summary['metrics'].update(display_total=6, total=4, provisional_total=2)
    else:
        buckets = {'2026-08': {'machines': [100, 20], 'provisional_machines': [0, 0]},
                   '2026-09': {'machines': [200, 30], 'provisional_machines': [6, 0]}}
        summary['metrics'].update(display_total=236, total=230, provisional_total=6)
    summary['trend'] = {'granularity': 'day' if key == 'day' else 'month', 'buckets': buckets,
                        'slots': [0, 2], 'machine_names': ['Frozen Slot 1', 'Frozen Slot 3'], 'available': True}
    return summary


@pytest.mark.parametrize('language', ['th', 'en'])
def test_today_is_default_and_dropdown_changes_chart_axis_values_and_summary(monkeypatch, language):
    app = QApplication.instance() or QApplication([])
    set_language(language)
    requests = []
    def loader(key):
        requests.append(key)
        return trend_summary(key)
    monkeypatch.setattr(overview, 'build_overview_summary', loader)
    page = overview.PageOverviewV2(lambda: [])
    page.show()
    try:
        assert page.period_combo.currentData() == 'day'
        page.refresh()
        wait_for_summary(page)
        assert requests == ['day']
        assert page.period_combo.currentText() == ('วันนี้' if language == 'th' else 'Today')
        chart = page.view_bar.chart()
        assert chart.axes(Qt.Orientation.Horizontal)[0].categories() == [f'{day:02}/09' for day in range(12, 26)]
        assert page.card_total_usage.lbl_val.text() == '6'
        assert [[(point.x(), point.y()) for point in series.points()] for series in chart.series()] == [
            [(10, 10), (11, 3)], [(13, 6)], [(13, 0)]]
        assert [series.name() for series in chart.series()] == ['Frozen Slot 1', 'Frozen Slot 1', 'Frozen Slot 3']
        assert len([marker for marker in chart.legend().markers() if marker.isVisible()]) == 2
        page.period_combo.setCurrentIndex(page.period_combo.findData('month'))
        wait_for_summary(page)
        assert page.card_total_usage.lbl_val.text() == '236'
        chart = page.view_bar.chart()
        assert chart.axes(Qt.Orientation.Horizontal)[0].categories() == ['Aug 26', 'Sep 26']
        assert [[point.y() for point in series.points()] for series in chart.series()] == [[100, 206], [20, 30]]
        page.period_combo.setCurrentIndex(page.period_combo.findData('day'))
        wait_for_summary(page)
        assert len(page.view_bar.chart().axes(Qt.Orientation.Horizontal)[0].categories()) == 14
        assert page.card_total_usage.lbl_val.text() == '6'
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_empty_daily_trend_clears_old_month_chart_and_legacy_daily_metrics_are_unavailable(monkeypatch):
    app = QApplication.instance() or QApplication([])
    set_language('en')
    empty = deepcopy(trend_summary('day'))
    empty['trend']['available'] = False
    empty['trend']['buckets'] = {}
    empty['metrics_available'] = False
    empty['metrics'] = {}
    monkeypatch.setattr(overview, 'build_overview_summary', lambda key: empty if key == 'day' else trend_summary(key))
    page = overview.PageOverviewV2(lambda: [])
    page.show()
    try:
        page.period_combo.setCurrentIndex(page.period_combo.findData('month'))
        wait_for_summary(page)
        assert page.view_bar.chart().series()
        page.period_combo.setCurrentIndex(page.period_combo.findData('day'))
        wait_for_summary(page)
        assert not page.view_bar.chart().series()
        assert not page.view_bar.chart().axes()
        assert page.view_bar.chart().title() == 'No data in this period'
        assert page.card_total_usage.lbl_val.text() == '—'
        assert page.card_total_cost.lbl_val.text() == '—'
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
