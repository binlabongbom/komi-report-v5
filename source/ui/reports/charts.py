"""Qt chart rendering shared by Reports; all widgets stay on the GUI thread."""
from __future__ import annotations

from PyQt6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QCategoryAxis, QChart, QStackedBarSeries, QValueAxis
from PyQt6.QtCore import QMargins, Qt, QThread
from PyQt6.QtGui import QColor, QCursor, QFont
from PyQt6.QtWidgets import QApplication, QToolTip

from i18n import tr
from services.report_chart_models import ChartModel
from ui.styles.reports import BLUE, DEVICE_COLORS, GREEN, ORANGE


def bar_chart(categories, series_data, *, stacked=False, show_legend=None) -> QChart:
    """Shared series/axis/hover setup; preserve grouped and stacked chart scales."""
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('Report charts must be rendered on the GUI thread')
    chart = QChart()
    chart.setBackgroundVisible(False)
    chart.setMargins(QMargins(2, 2, 2, 2))
    if not categories or (stacked and not series_data):
        chart.setTitle(tr('ยังไม่มีข้อมูลสำหรับสร้างกราฟ', 'No chart data') if stacked else 'ยังไม่มีข้อมูลสำหรับสร้างกราฟ')
        chart.legend().hide()
        return chart
    series = QStackedBarSeries() if stacked else QBarSeries()
    if stacked:
        series.setBarWidth(0.68)
    maxima = [0.0] * len(categories)
    fractional = False
    for name, values, color in series_data:
        values = tuple(float(value) for value in values)
        bar = QBarSet(name)
        bar.append(list(values))
        bar.setColor(QColor(color))
        for index, value in enumerate(values):
            maxima[index] = maxima[index] + value if stacked else max(maxima[index], value)
            fractional |= not value.is_integer()
        def hover(entered, index, *, values=values, name=name):
            if entered:
                value = values[index]
                formatted = f'{value:,.0f}' if stacked or value.is_integer() else f'{value:,.2f}'
                QToolTip.showText(QCursor.pos(), f'{categories[index]}\n{name}: {formatted}')
            else:
                QToolTip.hideText()
        bar.hovered.connect(hover)
        series.append(bar)
    chart.addSeries(series)
    axis_x = QBarCategoryAxis()
    axis_x.append(list(categories))
    axis_x.setLabelsAngle(-45 if len(categories) > 7 else 0)
    axis_y = QValueAxis()
    if stacked:
        axis_y.setTitleText(tr('หน้า', 'Pages'))
    axis_y.setRange(0, max(1.0, max(maxima) * (1.15 if stacked else 1.18)))
    axis_y.setTickCount(4)
    axis_y.setLabelFormat('%.2f' if fractional else '%.0f')
    axis_y.applyNiceNumbers()
    axis_font = QFont()
    axis_font.setPointSize(9)
    axis_x.setLabelsFont(axis_font)
    if not stacked:
        axis_y.setLabelsFont(axis_font)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_x)
    series.attachAxis(axis_y)
    chart.legend().setVisible(len(series_data) > 1 if show_legend is None else show_legend)
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    return chart


def render_chart(model: ChartModel) -> QChart:
    colors = {'print': BLUE, 'copy': ORANGE, 'scan': GREEN}
    series = []
    for item in model.series:
        color = DEVICE_COLORS[item.palette_index % len(DEVICE_COLORS)] if item.role == 'device' else colors[item.role]
        if item.light:
            color = QColor(color).lighter(155).name()
        series.append((item.label, item.values, color))
    chart = bar_chart(model.categories, tuple(series), stacked=True, show_legend=False)
    if model.day_labels:
        old_axis = chart.axes(Qt.Orientation.Horizontal)[0]
        chart.removeAxis(old_axis)
        old_axis.deleteLater()
        axis = QCategoryAxis()
        axis.setStartValue(-0.5)
        for index, label in enumerate(model.day_labels):
            axis.append(label, index * 2 + 1.5)
        axis.setRange(-0.5, len(model.day_labels) * 2 - 0.5)
        axis.setLabelsAngle(-45 if len(model.day_labels) > 7 else 0)
        chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
        chart.series()[0].attachAxis(axis)
    if model.estimated:
        chart.setTitle(tr('วันที่ไม่มีข้อมูล Web แสดงค่าเฉลี่ยประมาณการ', 'Days without Web readings show estimated averages'))
    return chart


def paper_legend_entries(*, scan=False):
    entries = [f'<span style="color:{color}">■</span><span style="color:{QColor(color).lighter(155).name()}">■</span> '
               f'A4 | A3 {name}' for name, color in (('Print', BLUE), ('Copy', ORANGE))]
    if scan:
        entries.append(f'<span style="color:{GREEN}">■</span> Scan')
    return entries
