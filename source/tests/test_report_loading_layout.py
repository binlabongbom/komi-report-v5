"""Report loading may change the header status, never the table/graph geometry."""
from pathlib import Path

import pytest
from excel_export_fixture import report_for
from PyQt6.QtCore import QPoint
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from i18n import set_language
from ui.cloud_reports import CloudReportsWidget


@pytest.mark.parametrize('language', ['th', 'en'])
@pytest.mark.parametrize('width', [794, 1280])
def test_loading_and_retry_keep_all_report_viewports_in_place(language, width):
    app = QApplication.instance() or QApplication([])
    set_language(language)
    report = report_for(users=2, days=3, printers=3)
    widget = CloudReportsWidget(staged=True)
    widget.resize(width, 850)
    widget.show()

    def rect(control):
        point = control.mapTo(widget, QPoint())
        return (point.x(), point.y(), control.width(), control.height())

    def settled_rects(controls):
        previous, stable = None, 0
        for _ in range(100):
            QTest.qWait(20)
            current = [rect(control) for control in controls]
            stable = stable + 1 if current == previous and not widget._layout_timer.isActive() else 0
            if stable >= 8:
                return current
            previous = current
        pytest.fail('The initial chart/table layout did not settle')

    try:
        for index in range(5):
            widget.tabs.setCurrentIndex(index)
            widget.set_data(records=report.selected_records, daily_records=report.selected_daily_records,
                monthly_records=report.monthly_records, subjects=report.subjects, devices=report.devices,
                raw_counter_records=report.raw_counter_records, period=report.period,
                last_sync_at='2026-07-03T17:00:00+07:00', tab_index=index)
            for _ in range(100):
                QTest.qWait(20)
                if widget.loading_panel.isHidden():
                    break
            assert widget.loading_panel.isHidden(), (index, widget._loading, widget._tab_loading,
                widget._pending_render_tail, widget.header_status.currentIndex())
            controls = [widget.tabs, widget.tab_scrolls[index], widget.header_status,
                        widget.export_button, widget.refresh_button]
            controls += [getattr(widget, name) for name in (
                ('overview_trend', 'overview_printers'), ('user_overview_button', 'users_table'),
                ('printer_trend', 'printers_table'), ('usage_monthly_table', 'usage_printer_table'),
                ('legacy_machine_table', 'legacy_user_table'))[index]]
            for usage_view in range(2 if index == 3 else 1):
                if index == 3:
                    widget.usage_tabs.setCurrentIndex(usage_view)
                # Qt lays out hidden tab pages lazily. Check each Usage table
                # while displayed, rather than the inactive page's geometry.
                visible_controls = [control for control in controls if control.isVisible()]
                before = settled_rects(visible_controls)
                assert widget.width() == width
                assert widget.header_status.parentWidget() is widget.header

                widget.set_loading(True)
                QTest.qWait(30)
                assert widget.loading_panel.isVisible()
                assert widget.loading_indicator.isVisible()
                assert [rect(control) for control in visible_controls] == before

                widget._show_slow_loading()
                QTest.qWait(30)
                assert widget.retry_button.isVisible()
                assert [rect(control) for control in visible_controls] == before
                assert widget.loading_label.heightForWidth(widget.loading_label.width()) <= widget.loading_label.height()
                retry = QSignalSpy(widget.refresh_requested)
                widget.retry_button.click()
                assert len(retry) == 1
                if index == 3:
                    out = Path(__file__).resolve().parents[2] / 'outputs' / 'report-loading-header'
                    out.mkdir(parents=True, exist_ok=True)
                    widget.grab().save(str(out / f'slow-{language}-{width}-view{usage_view}.png'))

                widget.set_loading(False)
                QTest.qWait(30)
                assert widget.loading_panel.isHidden()
                assert widget.updated_label.isVisible()
                assert [rect(control) for control in visible_controls] == before

                widget.set_tab_loading(index, True)
                QTest.qWait(30)
                assert widget.loading_panel.isVisible()
                assert [rect(control) for control in visible_controls] == before
                widget.set_tab_loading(index, False)
                QTest.qWait(30)
                assert widget.loading_panel.isHidden()
                assert [rect(control) for control in visible_controls] == before
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
