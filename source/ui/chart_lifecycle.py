"""Release the chart that QChartView stops owning when it is replaced."""
from PyQt6 import sip


def replace_chart(view, chart):
    previous = view.chart()
    if previous is chart:
        return
    view.setChart(chart)
    if previous is not None and not sip.isdeleted(previous):
        previous.deleteLater()
