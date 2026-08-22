"""Reusable, non-Reports dialogs kept independent from the large page modules."""

from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout

from database import get_cfg, set_cfg
from services.device_config import DeviceConfigRepository
from services.usage import latest_counters
from widgets import btn


class AllCountersDialog(QDialog):
    def __init__(self, title: str, counters: dict[str, float], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        table = QTableWidget(len(counters), 2)
        table.setHorizontalHeaderLabels(["Counter ที่อ่านได้", "Value"])
        for row, (key, value) in enumerate(sorted(counters.items())):
            table.setItem(row, 0, QTableWidgetItem(key))
            table.setItem(row, 1, QTableWidgetItem(f"{value:,.0f}"))
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)


class PinnedCountersDialog(QDialog):
    def __init__(self, repository: DeviceConfigRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("เลือก Counter ที่แสดงเพิ่มบน Overview")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        existing = set(json.loads(get_cfg("pinned_counters_json", "[]") or "[]"))
        keys: set[str] = set()
        for device in repository.list(enabled_only=True):
            keys.update(latest_counters(device.slot))
        self.table = QTableWidget(len(keys), 1)
        self.table.setHorizontalHeaderLabels(["Counter ที่อ่านได้"])
        for row, key in enumerate(sorted(keys)):
            item = QTableWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in existing else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, item)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        save = btn("บันทึก Counter ที่เลือก", "primary")
        save.clicked.connect(self._save)
        layout.addWidget(save, 0, Qt.AlignmentFlag.AlignRight)

    def _save(self) -> None:
        selected = [
            self.table.item(row, 0).text()
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        set_cfg("pinned_counters_json", json.dumps(selected, ensure_ascii=False))
        self.accept()
