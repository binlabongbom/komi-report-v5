"""Compact usage tables with a frozen period and content-aware numeric widths."""
from ui.styles import tables as tables_styles
from ui.styles import reports as reports_styles
from ui.styles import text as text_styles
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QAbstractItemView, QWidget, QHBoxLayout, QLabel, QToolButton

from i18n import tr

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
            table.setStyleSheet(self._TBL_STYLE + tables_styles.COMPACT_CELL)
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


class PrinterUsageTable(UsageTable):
    """One period axis with independently expandable printer column groups."""

    printer_toggled = pyqtSignal(str)

    def __init__(self, parent=None, *, fit_content_height=True):
        super().__init__(parent)
        self._fit_content_height = fit_content_height
        self.toggle_buttons = {}
        self.printer_columns = {}
        self._printer_groups = ()
        for table in (self._left, self._right, self._group_left, self._group_right):
            table.setStyleSheet(table.styleSheet() + tables_styles.MATRIX_CELL)
        for table in (self._right, self._group_right):
            table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._right.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self._right.viewport() and event.type() == QEvent.Type.Resize:
            # The shared vertical scrollbar can reduce the body width after
            # the outer table has already received its resize event.
            self._fit_timer.start(0)
        return super().eventFilter(watched, event)

    def set_printers(self, period_label, groups, detail_labels, *, final_label=None, include_total=False):
        # groups: (stable identity, configured Slot label, expanded).
        detail_labels = tuple(label.replace(' ', '\n', 1) if label.startswith(('A3 ', 'A4 '))
                              else label for label in detail_labels)
        self._printer_groups = tuple(groups)
        self._group_right.clearContents()
        self.toggle_buttons = {}
        self.printer_columns = {}
        outer, middle, labels, separators = [], [], [], []
        column = 1
        has_detail = any(expanded for _, _, expanded in groups)
        cost_label = final_label or tr('ค่าใช้จ่าย', 'Cost')
        for identity, name, expanded in groups:
            count = (12 if expanded else 4) + int(include_total)
            self.printer_columns[identity] = (column, count)
            outer.append((name, count))
            if expanded:
                middle.extend((('Print', 5), ('Copy', 5), ('Scan', 1)))
                if include_total:
                    middle.append((tr('รวม', 'Total'), 1))
                middle.append((cost_label, 1))
                labels.extend(detail_labels)
            else:
                compact = ('Print', 'Copy', 'Scan') + ((tr('รวม', 'Total'),) if include_total else ()) + (cost_label,)
                middle.extend((label, 1) for label in compact)
                labels.extend(compact)
            column += count
            separators.append(column - 1)
        self.setColumnCount(column)
        self.setHorizontalHeaderLabels((period_label, *labels))
        for index in range(column):
            header = self.horizontalHeaderItem(index)
            if header is not None:
                alignment = Qt.AlignmentFlag.AlignLeft if index == 0 else Qt.AlignmentFlag.AlignRight
                header.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        if has_detail:
            self.setThreeLevelGroupedHeader(period_label, outer, middle, labels)
            for identity, _, expanded in groups:
                if not expanded:
                    start, count = self.printer_columns[identity]
                    for col in range(start - 1, start - 1 + count):
                        self._group_right.setSpan(1, col, 2, 1)
        else:
            self.setGroupedHeader(period_label, outer, labels)
        self._column_labels = labels
        self.setGroupSeparators(separators[:-1], color='#AABBCF', width=2)
        for identity, name, expanded in groups:
            start, _ = self.printer_columns[identity]
            host = QWidget()
            host.setStyleSheet(reports_styles.PRINTER_USAGE_TABLE_HOST)
            layout = QHBoxLayout(host)
            layout.setContentsMargins(6, 3, 6, 3)
            layout.setSpacing(5)
            label = QLabel(name)
            label.setMinimumWidth(0)
            label.setWordWrap(True)
            label.setToolTip(name)
            label.setStyleSheet(text_styles.label('#123262', font_weight='600', border='none'))
            button = QToolButton()
            button.setText('−' if expanded else '+')
            button.setCheckable(True)
            button.setChecked(expanded)
            button.setFixedSize(26, 26)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            action = tr('ยุบรายละเอียด', 'Collapse details') if expanded else tr('ขยายรายละเอียด', 'Expand details')
            button.setAccessibleName(f'{action} {name}')
            button.setToolTip(f'{action} {name}')
            button.setStyleSheet(reports_styles.PRINTER_USAGE_TABLE_BUTTON)
            button.clicked.connect(lambda _checked, key=identity: self.printer_toggled.emit(key))
            layout.addWidget(label, 1)
            layout.addWidget(button)
            self._group_right.setCellWidget(0, start - 1, host)
            self.toggle_buttons[identity] = button
        self._fit_timer.start(0)

    def fit_columns(self):
        if self.columnCount() < 2:
            if self._fit_content_height:
                self.setFixedHeight(self._group_header.height() + 60)
            return
        fm = QFontMetrics(self._right.font())
        header_fm = QFontMetrics(self._group_right.font())
        period_texts = [self.item(row, 0).text() for row in range(self.rowCount())
                        if self.item(row, 0) is not None]
        left = max(getattr(self, '_frozen_min_width', 80),
                   *(fm.horizontalAdvance(text) + 12 for text in period_texts))
        self.setColumnWidth(0, min(left, getattr(self, '_frozen_max_width', left)))
        minimums = []
        for col, label in enumerate(self._column_labels, 1):
            texts = label.splitlines() + [self.item(row, col).text() for row in range(self.rowCount())
                                         if self.item(row, col) is not None]
            middle = self.groupedHeaderItem(1, col)
            if middle is not None and self.groupedHeaderSpan(1, col)[1] == 1:
                texts += middle.text().splitlines()
            minimums.append(max(38, *(max(fm.horizontalAdvance(text), header_fm.horizontalAdvance(text)) + 6
                                     for text in texts)))
        available = max(0, self._right.viewport().width() - 2)
        extra = max(0, available - sum(minimums))
        for col, width in enumerate(minimums, 1):
            self.setColumnWidth(col, width + extra // len(minimums))
        header_height = 42
        for identity, name, _ in self._printer_groups:
            start, count = self.printer_columns[identity]
            # Include the cell delegate's insets as well as the button and
            # layout margins; the embedded widget is smaller than the span.
            width = sum(self._right.columnWidth(col - 1) for col in range(start, start + count)) - 64
            host = self._group_right.cellWidget(0, start - 1)
            label = host.findChild(QLabel)
            label.ensurePolished()
            header_height = max(header_height, label.heightForWidth(max(1, width)) + 20)
        detail_lines = max((len(label.splitlines()) for label in self._column_labels), default=1)
        heights = [header_height] + [32] * (self._group_right.rowCount() - 1)
        heights[-1] = max(32, header_fm.height() * detail_lines + 8)
        for table in (self._group_left, self._group_right):
            for row, height in enumerate(heights):
                table.setRowHeight(row, height)
            table.setFixedHeight(sum(heights) + 2)
        self._group_header.setFixedHeight(sum(heights) + 2)
        if self._fit_content_height:
            rows = min(self.rowCount(), 16)
            self.setFixedHeight(sum(heights) + sum(self.rowHeight(i) for i in range(rows))
                                + self._right.horizontalScrollBar().sizeHint().height() + 8)
        self._refresh_viewport_alignment()
