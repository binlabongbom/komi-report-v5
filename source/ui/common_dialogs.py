"""Reusable, non-Reports dialogs kept independent from the large page modules."""

from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit

from database import get_cfg, set_cfg
from services.device_config import DeviceConfigRepository
from services.usage import latest_counters
from widgets import btn
from i18n import tr


class AllCountersDialog(QDialog):
    def __init__(self, title: str, counters: dict[str, float], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        table = QTableWidget(len(counters), 2)
        self.table = table
        table.setHorizontalHeaderLabels(["Counter ที่อ่านได้", "Value"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        for row, (key, value) in enumerate(sorted(counters.items())):
            table.setItem(row, 0, QTableWidgetItem(key))
            table.item(row, 0).setToolTip(key)
            table.setItem(row, 1, QTableWidgetItem(f"{value:,.0f}"))
            table.item(row, 1).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        self.details_button = btn(tr("อ่าน Counter เต็ม", "Read full counter"), "outline")
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self.show_details)
        table.itemSelectionChanged.connect(self._selection_changed)
        table.cellDoubleClicked.connect(self.show_details)
        layout.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignRight)

    def _selection_changed(self):
        self.details_button.setEnabled(self.table.currentRow() >= 0)

    def show_details(self, *_):
        row = self.table.currentRow()
        if row < 0:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("รายละเอียด Counter", "Counter details"))
        dialog.resize(640, 280)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit("\n\n".join(self.table.item(row, column).text() for column in range(2)))
        text.setReadOnly(True)
        layout.addWidget(text)
        close = btn(tr("ปิด", "Close"), "outline")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()


class PinnedCountersDialog(QDialog):
    def __init__(self, repository: DeviceConfigRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("เลือก Counter ที่แสดงเพิ่มบน Overview")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        existing = set(json.loads(get_cfg("pinned_counters_json", "[]") or "[]"))
        self._existing = existing
        keys: set[str] = set()
        for device in repository.list(enabled_only=True):
            keys.update(latest_counters(device.slot))
        all_keys = keys | existing
        self.table = QTableWidget(len(all_keys), 1)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setHorizontalHeaderLabels(["Counter ที่อ่านได้"])
        for row, key in enumerate(sorted(all_keys)):
            item = QTableWidgetItem(key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(key if key in keys else tr("ยังอ่านไม่ได้ · เก็บค่าที่เคยเลือกไว้", "Not read yet. Your saved selection is preserved."))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in existing else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, item)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        note = QLabel(tr("รายการเดิมยังคงเลือกไว้ แม้ยังอ่านไม่ได้ · ยกเลิกเครื่องหมายเพื่อเอาออก",
                         "Saved counters remain selected even when unavailable. Uncheck to remove."))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.save_button = btn(tr("บันทึก Counter ที่เลือก", "Save selected counters"), "primary")
        self.save_button.setEnabled(bool(all_keys))
        if not all_keys:
            note.setText(tr("ยังไม่มี Counter ให้เลือก กรุณาอ่านข้อมูลเครื่องพิมพ์ก่อน", "No counters available. Read a printer first."))
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignRight)

    def _save(self) -> None:
        if not self.table.rowCount():
            return
        selected = [
            self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        if not selected and self._existing:
            result = QMessageBox.question(self, tr("ล้าง Counter ที่เลือก", "Clear saved counters"),
                tr("ต้องการเอา Counter ที่เคยเลือกออกทั้งหมดหรือไม่?", "Remove all previously selected counters?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if result != QMessageBox.StandardButton.Yes:
                return
        set_cfg("pinned_counters_json", json.dumps(selected, ensure_ascii=False))
        self.accept()
