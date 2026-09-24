"""Searchable reference, not an event log: every registered application code."""
from math import ceil
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate)

from i18n import tr
from services.error_reference import error_references


class _WrappedCellDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        self.initStyleOption(option, index)
        width = self.parent().columnWidth(index.column())
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        document.setPlainText(option.text)
        document.setTextWidth(max(1, width - 22))
        return QSize(width, ceil(document.size().height()) + 20)


class ErrorListPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = error_references()
        body = QVBoxLayout(self)
        body.setContentsMargins(16, 16, 16, 16)
        heading = QHBoxLayout()
        title = QLabel('Error list')
        title.setProperty('i18n_data', True)
        title.setStyleSheet('font-size:18px;font-weight:700;color:#123262;')
        heading.addWidget(title)
        heading.addStretch()
        self.copy_button = QPushButton(tr('คัดลอกรายละเอียด', 'Copy details'))
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy)
        heading.addWidget(self.copy_button)
        body.addLayout(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('ค้นหา Error code, ปัญหา หรือวิธีแก้ไข', 'Search error code, problem or solution'))
        self.search.setClearButtonEnabled(True)
        body.addWidget(self.search)
        self.count_label = QLabel()
        self.count_label.setProperty('i18n_data', True)
        body.addWidget(self.count_label)
        self.table = QTableWidget(0, 4)
        self.table.setProperty('i18n_data', True)
        self.table.setHorizontalHeaderLabels(['Error code', tr('ปัญหาที่เจอ', 'Problem'),
            tr('แนวทางตรวจสอบ', 'Evidence to check'), tr('แนวทางแก้ไขเบื้องต้น', 'Initial solution')])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.setItemDelegate(_WrappedCellDelegate(self.table))
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 158)
        self.table.setStyleSheet('QTableWidget{background:white;border:1px solid #D7E0E8;}'
            'QHeaderView::section{background:#EDF2F7;color:#123262;padding:6px;border:1px solid #D7E0E8;}'
            'QTableWidget::item{padding:6px;}')
        body.addWidget(self.table, 1)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.table.resizeRowsToContents)
        header.sectionResized.connect(lambda *_: self._resize_timer.start(80))
        self.table.itemSelectionChanged.connect(lambda: self.copy_button.setEnabled(bool(self.table.selectedItems())))
        self.search.textChanged.connect(self._filter)
        self._filter()

    def _filter(self, text=''):
        terms = text.casefold().split()
        rows = [entry for entry in self.entries if all(term in '\n'.join(
            (entry.code, entry.problem, entry.check, entry.action)).casefold() for term in terms)]
        self.table.clearSelection()
        self.table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            for col, value in enumerate((entry.code, entry.problem, entry.check, entry.action)):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.table.setItem(row, col, item)
        self.count_label.setText(tr(f'แสดง {len(rows)} / {len(self.entries)} รหัส',
                                   f'{len(rows)} / {len(self.entries)} codes'))
        self.copy_button.setEnabled(False)
        self._resize_timer.start(0)

    def _copy(self):
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return
        QApplication.clipboard().setText('\n\n'.join(
            f'{self.table.horizontalHeaderItem(col).text()}: {self.table.item(row, col).text()}'
            for col in range(4)))
