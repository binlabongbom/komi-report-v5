"""Compact usage tables with a frozen period and content-aware numeric widths."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QAbstractItemView

from widgets import FrozenLeftTable


class UsageTable(FrozenLeftTable):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._row_h = 30
        self._cloud_text_columns = frozenset((0,))
        self.setMinimumWidth(0)
        for table in (self._left, self._right):
            table.setAlternatingRowColors(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setStyleSheet(self._TBL_STYLE + 'QTableWidget::item { padding:2px 4px; }')
        for table in (self._right, self._group_right):
            table.horizontalHeader().setMinimumSectionSize(38)
        for table in (self._group_left, self._group_right):
            table.setWordWrap(True)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_fit_timer'):
            self._fit_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_timer.start(0)

    def setGroupedHeader(self, left_label, groups, sublabels):
        super().setGroupedHeader(left_label, groups, sublabels)
        line = QFontMetrics(self._group_right.font()).height()
        heights = (max(26, line + 8), max(30, line + 10))
        for table in (self._group_left, self._group_right):
            for row, height in enumerate(heights):
                table.setRowHeight(row, height)
            table.setFixedHeight(sum(heights) + 2)
        self._group_header.setFixedHeight(sum(heights) + 2)

    def fit_columns(self):
        if self.columnCount() < 2:
            return
        fm = QFontMetrics(self._right.font())
        left = max(108, fm.horizontalAdvance('Meter เริ่มต้น') + 12, fm.horizontalAdvance('30/09/2026') + 12)
        self.setColumnWidth(0, left)
        minimums = []
        for col in range(1, self.columnCount()):
            texts = [self.item(row, col).text() for row in range(self.rowCount())
                     if self.item(row, col) is not None]
            # Compact header labels and numeric values must
            # remain legible: unusually large amounts may still need scrolling.
            header = self.groupedHeaderItem(1, col)
            texts += header.text().splitlines() if header is not None else []
            group = self.groupedHeaderItem(0, col)
            if group is not None and self.groupedHeaderSpan(0, col)[1] == 1:
                texts += [group.text()]
            minimums.append(max(42, *(fm.horizontalAdvance(t) + 12 for t in texts)))
        available = max(0, self.width() - left - self._vsb.sizeHint().width() - 20)
        extra = max(0, available - sum(minimums))
        for col, width in enumerate(minimums, 1):
            self.setColumnWidth(col, width + extra // len(minimums))
        self._refresh_viewport_alignment()

    def fit_rows(self, *, compact=False):
        # Short monthly reports for three Slots fit together. Long daily
        # reports scroll vertically inside each table with the header fixed.
        rows = min(max(1, self.rowCount()), 6 if compact else 16)
        self.setMinimumHeight(0)
        self.setFixedHeight(self._group_header.height() + sum(self._left.rowHeight(i) for i in range(min(rows, self.rowCount()))) + 8)
        self._fit_timer.start(0)
