from excel_export_fixture import report_for
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication
from qt_render_environment import configure_offscreen_fonts

from ui.cloud_reports import CloudReportsWidget


def test_printer_chart_panels_do_not_absorb_spare_height_or_push_table_down():
    app = QApplication.instance() or QApplication([])
    configure_offscreen_fonts(app)
    report = report_for(users=2, days=4, printers=3)
    widget = CloudReportsWidget()
    widget.set_data(
        records=report.selected_records,
        daily_records=report.selected_daily_records,
        subjects=report.subjects,
        devices=report.devices,
        period=report.period,
        last_sync_at=None,
        raw_counter_records=report.raw_counter_records,
        category_costs=report.category_costs,
    )
    widget.tabs.setCurrentIndex(2)
    widget.show()
    try:
        table_panel = widget.printers_table.parentWidget()
        chart_panels = (
            widget.printer_trend.parentWidget(),
            widget.printer_mix.parentWidget(),
        )
        legends = (widget.printer_trend_legend, widget.printer_mix_legend)
        wide_positions = []
        # A taller viewport must not create an empty block inside the charts;
        # narrowing and restoring the window must not retain wrapped heights.
        for width, height in ((1660, 850), (1660, 1100), (960, 750), (1660, 1100)):
            widget.resize(width, height)
            for _ in range(15):
                app.processEvents()
            assert chart_panels[0].height() == chart_panels[1].height()
            for panel, legend in zip(chart_panels, legends, strict=True):
                assert legend.isVisible()
                assert legend.geometry().bottom() < panel.height()
            lowest_legend = max(
                legend.mapTo(widget.printers_page, QPoint(0, legend.height())).y()
                for legend in legends
            )
            table_top = table_panel.mapTo(widget.printers_page, QPoint()).y()
            assert 0 <= table_top - lowest_legend <= 40
            if width == 1660:
                wide_positions.append(table_top)
        assert max(wide_positions) - min(wide_positions) <= 2
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
