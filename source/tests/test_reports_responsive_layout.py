"""Behavioral layout checks using synthetic reports and the isolated test DB."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import date
from itertools import combinations

import pytest
from PyQt6.QtCore import QDate, QPoint, QRect
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from i18n import ENGLISH, THAI, apply_language, get_language, set_language
from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.subject_history import SubjectPeriodUsage
from ui.cloud_reports import CloudReportsWidget

_qt_app_keepalive = None


def _settle() -> None:
    QApplication.processEvents()
    QTest.qWait(30)
    QApplication.processEvents()


def _rect_in(child: QWidget, ancestor: QWidget) -> QRect:
    return QRect(child.mapTo(ancestor, QPoint()), child.size())


def _full_text(label: QLabel) -> str:
    return label.toolTip() or label.text()


def _content_scroll(widget: CloudReportsWidget, content: QWidget) -> QScrollArea:
    matches = [
        scroll
        for scroll in widget.tabs.currentWidget().findChildren(QScrollArea)
        if scroll.widget() is content or scroll.widget().isAncestorOf(content)
    ]
    assert len(matches) == 1, "Active report content must have one owning scroll area"
    return matches[0]


@pytest.fixture
def report_widget():
    global _qt_app_keepalive
    app = QApplication.instance() or QApplication([])
    # Retain QApplication before the first fixture teardown on native Windows.
    _qt_app_keepalive = app
    day = date(2026, 8, 6)
    period = (day.isoformat(), day.isoformat())
    usage = MonthlyUsage(
        device_slot=0,
        period_start=day,
        period_end=day,
        total=120,
        a3_color=10,
        a3_bw=5,
        a4_color=50,
        a4_bw=55,
        scan=12,
        gross_cost=30,
        net_cost=29.4,
        day_count=1,
        incomplete_days=0,
        device_identity="serial:TEST-A",
        device_name_snapshot="Sales Printer",
        device_serial_snapshot="TEST-A",
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
    subject = SubjectPeriodUsage(
        device_slot=0,
        period_start=day,
        period_end=day,
        subject_type="user",
        subject_id="u-1",
        subject_name="Alice Example",
        latest_total=500,
        period_usage=75,
        reset_count=0,
        missing_baseline_days=0,
        incomplete_days=0,
        sample_count=2,
        latest_at="2026-08-06T09:00:00+07:00",
        warnings=(),
        device_identity="serial:TEST-A",
        device_name_snapshot="Sales Printer",
        device_serial_snapshot="TEST-A",
    )
    widget = CloudReportsWidget()
    widget.set_periods((period, ("2026-08-05", "2026-08-05")), period)
    widget.set_data(
        records=(usage,),
        daily_records=(usage,),
        monthly_records=(usage,),
        subjects=(subject, replace(subject, subject_id="u-2", subject_name="Bob Example", period_usage=25)),
        devices=(DeviceConfig(0, "Sales Printer", "192.0.2.10", serial="TEST-A"),),
        period=period,
        last_sync_at="2026-08-06T09:00:00+07:00",
    )
    widget.resize(800, 620)
    widget.show()
    _settle()
    yield widget
    widget.close()
    app.processEvents()


def test_visiting_tall_tabs_does_not_inflate_overview(report_widget):
    widget = report_widget
    scroll = _content_scroll(widget, widget.overview_page)
    before = (
        widget.size(),
        scroll.viewport().size(),
        widget.overview_page.height(),
        scroll.verticalScrollBar().maximum(),
    )
    for index in (4, 3, 2, 1, 0, 4, 0):
        widget.tabs.setCurrentIndex(index)
        _settle()
    after = (
        widget.size(),
        scroll.viewport().size(),
        widget.overview_page.height(),
        scroll.verticalScrollBar().maximum(),
    )
    assert after == before
    assert widget.height() <= 620, "Other tab minimum sizes must not force the report window taller"
    assert widget.rect().contains(_rect_in(scroll, widget))


@pytest.mark.parametrize("tab_index,content_name", [(0, "overview_page"), (1, "users_page"), (2, "printers_page")])
def test_header_and_period_stay_visible_while_report_content_scrolls(report_widget, tab_index, content_name):
    widget = report_widget
    widget.tabs.setCurrentIndex(tab_index)
    _settle()
    content = getattr(widget, content_name)
    scroll = _content_scroll(widget, content)
    editors = [editor for pair in widget.period_edit_pairs for editor in pair if editor.isVisible()]
    assert len(editors) == 2
    anchors = [widget.export_button, widget.refresh_button, widget.tabs.tabBar(), *editors]
    before = [_rect_in(anchor, widget) for anchor in anchors]
    content_top = content.mapTo(scroll.viewport(), QPoint()).y()
    scrollbar = scroll.verticalScrollBar()
    assert scrollbar.maximum() > 0, "Fixture must exercise real content scrolling"
    scrollbar.setValue(scrollbar.maximum())
    _settle()
    assert content.mapTo(scroll.viewport(), QPoint()).y() < content_top
    assert [_rect_in(anchor, widget) for anchor in anchors] == before
    for anchor, rect in zip(anchors, before, strict=True):
        assert widget.rect().contains(rect), anchor.objectName()
        assert not scroll.viewport().isAncestorOf(anchor)


@pytest.mark.parametrize("width", [800, 660])
def test_narrow_overview_keeps_kpi_text_and_panels_inside_content(report_widget, width):
    widget = report_widget
    widget.resize(width, 620)
    _settle()
    scroll = _content_scroll(widget, widget.overview_page)
    width_constraints = [
        (child.objectName() or type(child).__name__, child.minimumSizeHint().width())
        for child in widget.findChildren(QWidget)
        if child.isVisible() and child.minimumSizeHint().width() > width - 40
    ]
    tab_constraints = [
        (
            widget.tabs.tabText(index),
            widget.tabs.widget(index).minimumSizeHint().width(),
            [
                child.minimumSizeHint().width()
                for child in widget.tabs.widget(index).findChildren(QWidget)
                if child.objectName() == "cloud_report_toolbar"
            ],
        )
        for index in range(widget.tabs.count())
    ]
    assert widget.width() <= width, (
        f"Requested width {width}, actual {widget.width()}; "
        f"visible minimum-size hints: {width_constraints}; wrappers/toolbars: {tab_constraints}"
    )
    assert scroll.horizontalScrollBar().maximum() == 0
    assert widget.overview_page.width() <= scroll.viewport().width()
    cards = list(widget.overview_kpis.values())
    assert len(cards) == 6
    assert len({_rect_in(card, widget.overview_page).y() for card in cards}) == 1, (
        "All six KPI cards must share one row at compact report widths"
    )
    for card in cards:
        assert widget.overview_page.rect().contains(_rect_in(card, widget.overview_page))
        labels = [card.lbl_title, card.lbl_detail, card.lbl_val]
        rects = [_rect_in(label, card) for label in labels]
        for label, rect in zip(labels, rects, strict=True):
            assert card.rect().contains(rect), label.text()
        for left, right in combinations(rects, 2):
            assert not left.intersects(right), "KPI labels and values must not overlap"
        title_rect, detail_rect, value_rect = rects
        assert title_rect.bottom() < detail_rect.top()
        assert title_rect.left() == detail_rect.left()
        left_column = title_rect.united(detail_rect)
        assert value_rect.left() > left_column.right(), "Value must occupy the right column"
        assert abs(value_rect.center().y() - left_column.center().y()) <= 1, (
            "Value must be vertically centered beside the two left-hand rows"
        )
        assert not card.lbl_title.wordWrap()
        assert not card.lbl_detail.wordWrap()
        for label in (card.lbl_title, card.lbl_val):
            assert label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width(), label.text()
    for left, right in combinations(cards, 2):
        assert not _rect_in(left, widget.overview_page).intersects(_rect_in(right, widget.overview_page))
    for chart in (widget.overview_trend, widget.overview_mix):
        panel = chart.parentWidget()
        for label in panel.findChildren(QLabel):
            if label.objectName() not in {"cloud_panel_title", "cloud_panel_subtitle"}:
                continue
            assert panel.rect().contains(_rect_in(label, panel))
            text_width = label.fontMetrics().horizontalAdvance(label.text())
            if text_width <= chart.width():
                assert label.contentsRect().width() >= text_width, (
                    "Panel text must use available chart width before wrapping"
                )


@pytest.mark.parametrize("width", [800, 660])
def test_compact_typography_and_tabs_preserve_readable_kpi_values(report_widget, width):
    widget = report_widget
    widget.resize(1440, 900)
    _settle()
    card = widget.overview_kpis["total_usage"]
    wide_title_size = card.lbl_title.fontInfo().pixelSize()
    wide_value_size = card.lbl_val.fontInfo().pixelSize()
    widget.resize(width, 620)
    _settle()
    assert 11 <= card.lbl_title.fontInfo().pixelSize() < wide_title_size
    assert 16 <= card.lbl_val.fontInfo().pixelSize() < wide_value_size
    assert widget.tabs.tabBar().height() <= 34
    for index in range(widget.tabs.count()):
        assert widget.tabs.tabBar().rect().contains(widget.tabs.tabBar().tabRect(index)), (
            "Every report tab must remain visible at the compact width"
        )
    assert card.lbl_val.text() == "120"
    full_value = "9,876,543,210,123,456"
    card.set_metric(full_value, "ยอดรวมสำหรับทดสอบการแสดงผล")
    _settle()
    assert full_value in (card.lbl_val.text(), card.lbl_val.toolTip()), (
        "An elided value must retain the complete value in its tooltip"
    )
    assert card.lbl_val.fontInfo().pixelSize() >= 16
    assert card.lbl_val.fontMetrics().horizontalAdvance(card.lbl_val.text()) <= card.lbl_val.contentsRect().width()
    widget.resize(1440, 900)
    _settle()
    assert full_value in (card.lbl_val.text(), card.lbl_val.toolTip())
    cost = widget.overview_kpis["total_cost"]
    ordinary_amount = "฿1,014.30"
    cost.set_metric(ordinary_amount, "ยอดสุทธิ")
    widget.resize(1440, 620)
    _settle()
    assert cost.lbl_val.text() == ordinary_amount, "Ordinary currency totals must fit before elision"
    assert cost.lbl_val.fontInfo().pixelSize() >= 16
    widget.resize(660, 620)
    _settle()
    assert cost.lbl_val.toolTip() == ordinary_amount
    assert cost.lbl_val.accessibleName() == ordinary_amount
    assert cost.lbl_val.fontInfo().pixelSize() >= 16
    assert widget.overview_page.rect().contains(_rect_in(cost, widget.overview_page))
    cost_rects = [_rect_in(label, cost) for label in (cost.lbl_title, cost.lbl_detail, cost.lbl_val)]
    for rect in cost_rects:
        assert cost.rect().contains(rect)
    for left, right in combinations(cost_rects, 2):
        assert not left.intersects(right)
    assert cost.lbl_val.fontMetrics().horizontalAdvance(cost.lbl_val.text()) <= cost.lbl_val.contentsRect().width()


@pytest.mark.parametrize("language", [THAI, ENGLISH])
def test_translated_kpi_glyphs_fit_vertically_and_full_values_survive_resize(report_widget, language):
    widget = report_widget
    previous_language = get_language()
    full_value = "9,876,543,210,123,456"
    value_card = widget.overview_kpis["total_usage"]
    try:
        set_language(language)
        apply_language(widget)
        expected_title = "ยอดใช้งานรวม" if language == THAI else "Total usage"
        value_card.set_metric(full_value, "ช่วงรายงานที่เลือก")
        for width, height in ((1440, 900), (800, 620), (1440, 900)):
            widget.resize(width, height)
            apply_language(widget)
            _settle()
            for card in widget.overview_kpis.values():
                value = card.lbl_val
                assert value.fontMetrics().height() <= value.contentsRect().height(), (
                    f"{language}: {value.text()} glyph height {value.fontMetrics().height()} "
                    f"exceeds label height {value.contentsRect().height()} at width {width}"
                )
                for label in (card.lbl_title, card.lbl_detail):
                    assert not label.wordWrap(), "Each left-hand label must remain a single line"
                    assert label.fontMetrics().height() <= label.contentsRect().height(), label.text()
                title = card.lbl_title
                assert title.fontMetrics().horizontalAdvance(title.text()) <= title.contentsRect().width(), title.text()
            assert _full_text(value_card.lbl_title) == expected_title
            assert value_card.lbl_title.accessibleName() == expected_title
            assert value_card.lbl_val.toolTip() == full_value
            assert value_card.lbl_val.accessibleName() == full_value
            assert value_card.lbl_val.fontMetrics().horizontalAdvance(value_card.lbl_val.text()) <= value_card.lbl_val.contentsRect().width()
            if language == ENGLISH:
                assert not any("\u0e00" <= char <= "\u0e7f" for char in value_card.lbl_detail.text()), (
                    "Resize-time elision must not overwrite translated detail with Thai source text"
                )
        other_language = ENGLISH if language == THAI else THAI
        set_language(other_language)
        apply_language(widget)
        widget.resize(660, 620)
        _settle()
        switched_title = "Total usage" if other_language == ENGLISH else "ยอดใช้งานรวม"
        assert _full_text(value_card.lbl_title) == switched_title
        assert value_card.lbl_title.accessibleName() == switched_title
        assert value_card.lbl_val.toolTip() == full_value
        assert value_card.lbl_val.accessibleName() == full_value
        assert value_card.lbl_title.fontMetrics().horizontalAdvance(value_card.lbl_title.text()) <= value_card.lbl_title.contentsRect().width()
    finally:
        set_language(previous_language)


def test_resize_and_tab_navigation_preserve_report_values_selection_and_period(report_widget):
    widget = report_widget
    values = {key: _full_text(card.lbl_val) for key, card in widget.overview_kpis.items()}
    assert values["total_usage"] == "120"
    assert values["total_cost"] == "฿29.40"
    widget.tabs.setCurrentIndex(1)
    _settle()
    widget.users_table.setCurrentCell(0, 0)
    _settle()
    selection = widget.user_filter_badge.text()
    assert "Alice Example" in selection
    emitted = []
    widget.period_changed.connect(emitted.append)
    widget.period_start_edit.setDate(QDate(2026, 8, 5))
    _settle()
    assert emitted[-1] == ("2026-08-05", "2026-08-06")
    for width, index in ((660, 4), (800, 0), (660, 2), (800, 1)):
        widget.resize(width, 620)
        widget.tabs.setCurrentIndex(index)
        _settle()
    assert widget.user_filter_badge.text() == selection
    assert widget.current_period() == ("2026-08-05", "2026-08-06")
    for start, end in widget.period_edit_pairs:
        assert start.date() == QDate(2026, 8, 5)
        assert end.date() == QDate(2026, 8, 6)
    assert {key: _full_text(card.lbl_val) for key, card in widget.overview_kpis.items()} == values
    widget.tabs.setCurrentIndex(0)
    _settle()
    assert widget.overview_users.item(0, 0).text() == "Alice Example"
    assert widget.overview_users.item(0, 2).text() == "75"
