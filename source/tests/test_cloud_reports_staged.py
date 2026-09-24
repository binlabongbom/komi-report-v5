import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from ui.cloud_reports import CloudReportsWidget


@pytest.fixture
def staged():
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget(staged=True)
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def deliver(widget, **kwargs):
    widget.set_data(records=(), daily_records=(), subjects=(), devices=(),
                    period=("2026-09-01", "2026-09-30"), last_sync_at=None, **kwargs)


def test_builds_only_overview_then_each_requested_tab_once(staged):
    assert staged.tabs.count() == 5
    assert staged.built_tabs == {0}
    assert not hasattr(staged, "users_table")
    assert not hasattr(staged, "usage_tabs")
    assert not staged.has_data
    assert all(card._full_value == "—" for card in staged.overview_kpis.values())
    wrappers = [staged.tabs.widget(index) for index in range(5)]
    for index in (4, 2, 1, 3):
        before = staged.tabs.currentIndex()
        assert staged.prewarm_tab(index) is wrappers[index]
        assert staged.ensure_tab(index) is wrappers[index]
        assert staged.tabs.currentIndex() == before
    assert len(staged.tab_scrolls) == 5
    assert staged.legacy_history_page is not None
    assert staged.legacy_raw_page is not None
    assert staged.built_tabs == set(range(5))


def test_lazy_controls_inherit_period_and_support_resize_before_data(staged):
    period = ("2026-09-04", "2026-09-18")
    staged.set_periods((period,), period)
    staged.tabs.setCurrentIndex(1)
    staged.resize(800, 600)
    staged._apply_responsive_layout()
    for start, end in staged.period_edit_pairs:
        assert start.date().toString("yyyy-MM-dd") == period[0]
        assert end.date().toString("yyyy-MM-dd") == period[1]
    assert staged.users_table.rowCount() == 0
    assert staged.include_waste_adjustment()
    staged.show_error("offline")
    assert not staged.has_data


def test_scoped_snapshots_never_render_other_tabs_data(staged, monkeypatch):
    counts = {"users": 0, "printers": 0}
    def users(): counts["users"] += 1
    def printers(): counts["printers"] += 1
    monkeypatch.setattr(staged, "_build_user_rows", users)
    monkeypatch.setattr(staged, "_build_printer_rows", printers)
    deliver(staged, tab_index=0)
    assert counts == {"users": 1, "printers": 1}
    staged.tabs.setCurrentIndex(1)
    assert not staged.has_data
    assert counts == {"users": 1, "printers": 1}
    assert staged.users_table.rowCount() == 0
    deliver(staged, tab_index=1)
    assert counts == {"users": 2, "printers": 1}
    assert staged.users_table.rowCount() == 0
    staged.tabs.setCurrentIndex(2)
    assert not staged.has_data
    assert staged.printers_table.rowCount() == 0
    staged.tabs.setCurrentIndex(0)
    assert staged.has_data
    assert counts == {"users": 2, "printers": 1}
    assert staged.overview_kpis["total_usage"]._full_value == "—"


def test_loading_slow_and_error_preserve_snapshot_and_offer_retry(staged):
    deliver(staged, tab_index=0)
    staged.overview_kpis["total_usage"].set_metric("123")
    staged.set_loading(True)
    assert staged.loading_indicator.maximum() == 0
    assert staged.loading_indicator.minimum() == 0
    assert staged._slow_loading_timer.interval() == 5000
    assert staged._slow_loading_timer.isActive()
    assert staged.overview_kpis["total_usage"]._full_value == "123"
    staged._show_slow_loading()
    assert "นานกว่าปกติ" in staged.loading_label.text()
    assert not staged.retry_button.isHidden()
    staged.show_error("connection failed")
    assert not staged.loading_panel.isHidden()
    assert staged.overview_kpis["total_usage"]._full_value == "123"
    assert "ข้อมูลเดิม" in staged.loading_label.text()
    assert not staged._slow_loading_timer.isActive()
    retry = QSignalSpy(staged.refresh_requested)
    staged.retry_button.click()
    assert len(retry) == 1


def test_usage_can_load_without_constructing_user_or_printer_widgets(staged):
    staged.tabs.setCurrentIndex(3)
    deliver(staged, tab_index=3)
    assert staged.built_tabs == {0, 3}
    staged.usage_waste_checkbox.setChecked(False)
    assert not staged.include_waste_adjustment()
    assert not hasattr(staged, "users_table")
    assert not hasattr(staged, "printers_table")
    staged._apply_responsive_layout()


def test_per_tab_loading_tracks_visible_tab_and_guard_invalid_index(staged):
    staged.set_tab_loading(4, True)
    assert staged.loading_panel.isHidden()
    staged.tabs.setCurrentIndex(4)
    assert not staged.loading_panel.isHidden()
    deliver(staged, tab_index=4)
    assert staged.loading_panel.isHidden()
    with pytest.raises(ValueError):
        staged.ensure_tab(5)


@pytest.mark.parametrize("index,prefix,card_key", [(0, "overview", "total_usage"), (1, "users", None), (2, "printers", None)])
def test_tables_and_charts_yield_after_immediate_content(staged, monkeypatch, index, prefix, card_key):
    from PyQt6.QtTest import QTest

    staged.tabs.setCurrentIndex(index)
    events = []
    table_method = f"_render_{prefix}_{'table' if index == 1 else 'tables'}"
    chart_method = f"_render_{prefix}_charts"
    monkeypatch.setattr(staged, table_method, lambda: events.append("tables"))
    monkeypatch.setattr(staged, chart_method, lambda: events.append("charts"))
    deliver(staged, tab_index=index)
    if card_key is not None:
        assert staged.overview_kpis[card_key]._full_value == "—"
    else:
        table = staged.users_table if index == 1 else staged.printers_table
        assert table.rowCount() == 0
    assert events == [], "tables and charts must yield after immediate content"
    staged._render_tail_timer.stop()
    staged._run_render_tail()
    assert events == ["tables"], "charts must yield again after tables"
    for _ in range(50):
        if len(events) == 2:
            break
        QTest.qWait(10)
    assert events == ["tables", "charts"]


@pytest.mark.parametrize("invalidate", ["tab", "reload", "error", "close"])
def test_queued_tail_is_discarded_after_invalidation(staged, monkeypatch, invalidate):
    from PyQt6.QtTest import QTest

    events = []
    monkeypatch.setattr(staged, "_render_overview_tables", lambda: events.append("tables"))
    monkeypatch.setattr(staged, "_render_overview_charts", lambda: events.append("charts"))
    deliver(staged, tab_index=0)
    if invalidate == "tab":
        staged.tabs.setCurrentIndex(1)
    elif invalidate == "reload":
        staged.set_loading(True)
    elif invalidate == "error":
        staged.show_error("offline")
    else:
        staged.close()
    QTest.qWait(15)
    assert events == []


def test_new_snapshot_replaces_pending_tables_and_charts(staged, monkeypatch):
    from PyQt6.QtTest import QTest

    events = []
    monkeypatch.setattr(staged, "_render_overview_tables", lambda: events.append(("tables", staged._data_revision)))
    monkeypatch.setattr(staged, "_render_overview_charts", lambda: events.append(("charts", staged._data_revision)))
    deliver(staged, tab_index=0)
    old_revision = staged._data_revision
    deliver(staged, tab_index=0)
    for _ in range(50):
        if len(events) == 2:
            break
        QTest.qWait(10)
    assert events == [("tables", old_revision + 1), ("charts", old_revision + 1)]


def test_users_chart_labels_do_not_depend_on_printers_tab_rows(staged, monkeypatch):
    from types import SimpleNamespace
    from PyQt6.QtCharts import QChart

    staged.ensure_tab(1)
    staged._records = (SimpleNamespace(device_identity="serial:KM123", device_slot=0,
                                      device_name_snapshot="Finance printer"),)
    staged._user_rows = [{"key": "user:a", "name": "Alice", "usage": 3,
                          "printers": {"serial:KM123": 3}}]
    staged._printer_rows = []
    labels = []
    def chart(names, _values, _color):
        labels.append(names)
        return QChart()
    monkeypatch.setattr(staged, "_horizontal_like_chart", chart)
    staged._render_users_charts()
    assert labels == [["Alice"], ["Finance printer"]]
