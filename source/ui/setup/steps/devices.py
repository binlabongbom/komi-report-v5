"""Printer selection controls and scan progress presentation."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ui.setup.controls import SetupDeviceStatusDelegate
from ui.styles import setup as setup_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_TEXT2
from widgets import btn


class DevicesStep(QWidget):
    """Device selection view; discovery and verification remain asynchronous in the wizard."""

    scan_requested = pyqtSignal()
    cancel_scan_requested = pyqtSignal()
    advanced_scan_requested = pyqtSignal()
    manual_setup_requested = pyqtSignal()
    device_action_requested = pyqtSignal(int, int)
    verify_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        page = self
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        intro = QLabel("ระบบจะค้นหาเฉพาะเครือข่าย LAN ที่เครื่องนี้เชื่อมต่อ · เลือกเครื่องพิมพ์ได้สูงสุด 3 เครื่อง")
        intro.setWordWrap(True)
        intro.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(intro)

        actions = QHBoxLayout()
        self.scan_button = btn("ค้นหาเครื่องพิมพ์อัตโนมัติ", "primary")
        self.scan_button.setAccessibleDescription("สแกน Konica Minolta ในเครือข่าย LAN ที่เชื่อมต่ออยู่")
        self.scan_button.clicked.connect(self.scan_requested)
        actions.addWidget(self.scan_button)
        self.cancel_scan_button = btn("ยกเลิกการค้นหา", "outline")
        self.cancel_scan_button.clicked.connect(self.cancel_scan_requested)
        self.cancel_scan_button.setVisible(False)
        actions.addWidget(self.cancel_scan_button)
        self.fallback_toggle = btn("ค้นหาไม่พบ? ใช้วิธีอื่น", "outline")
        self.fallback_toggle.setCheckable(True)
        self.fallback_toggle.toggled.connect(self._toggle_fallback_actions)
        actions.addWidget(self.fallback_toggle)
        actions.addStretch()
        self.selection_badge = QLabel("เลือกแล้ว 0/3")
        self.selection_badge.setStyleSheet(setup_styles.SETUP_WIZARD_SELECTION_BADGE)
        self.selection_badge.setAccessibleName("จำนวนเครื่องพิมพ์ที่เลือก")
        actions.addWidget(self.selection_badge)
        layout.addLayout(actions)

        self.fallback_actions = QWidget()
        fallback_layout = QHBoxLayout(self.fallback_actions)
        fallback_layout.setContentsMargins(0, 0, 0, 0)
        fallback_layout.setSpacing(10)
        self.advanced_scan_button = btn("กำหนดช่วง IP", "outline")
        self.advanced_scan_button.clicked.connect(self.advanced_scan_requested)
        fallback_layout.addWidget(self.advanced_scan_button)
        self.manual_setup_button = btn("เพิ่ม IP ด้วยตนเอง", "outline")
        self.manual_setup_button.clicked.connect(self.manual_setup_requested)
        fallback_layout.addWidget(self.manual_setup_button)
        fallback_hint = QLabel("ใช้เมื่อเครื่องพิมพ์อยู่นอกช่วงเครือข่ายที่ค้นหาอัตโนมัติ")
        fallback_hint.setStyleSheet(text_styles.label(C_TEXT2))
        fallback_layout.addWidget(fallback_hint)
        fallback_layout.addStretch()
        self.fallback_actions.setVisible(False)
        layout.addWidget(self.fallback_actions)

        self.scan_status = QLabel("พร้อมค้นหา · ระบบยังไม่ได้สแกนเครือข่าย")
        self.scan_status.setStyleSheet(text_styles.label("#245268", background="#EEF6F9", padding="8px 10px"))
        self.scan_status.setAccessibleName("สถานะการค้นหาเครื่องพิมพ์")
        layout.addWidget(self.scan_status)

        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setRange(0, 1)
        self.scan_progress_bar.setValue(0)
        self.scan_progress_bar.setTextVisible(True)
        self.scan_progress_bar.setFormat("สแกน 0 / 0 IP (0%)")
        self.scan_progress_bar.setAccessibleName("ความคืบหน้าการค้นหาเครื่องพิมพ์")
        self.scan_progress_bar.setStyleSheet(setup_styles.SETUP_WIZARD_SCAN_PROGRESS_BAR)
        self.scan_progress_bar.setVisible(False)
        layout.addWidget(self.scan_progress_bar)

        self.device_table = QTableWidget(0, 6)
        self.device_table.setHorizontalHeaderLabels(
            ("เลือก", "ชื่อรุ่น", "IP address", "Serial Number", "สถานะ", "สิทธิ์เข้าถึง")
        )
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setAlternatingRowColors(False)
        self.device_table.setObjectName("setup_device_table")
        self.device_table.setWordWrap(False)
        table_palette = QPalette(self.palette())
        table_palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        table_palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F7FAFD"))
        table_palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
        table_palette.setColor(QPalette.ColorRole.Highlight, QColor("#DCEEFF"))
        table_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#172033"))
        self.device_table.setPalette(table_palette)
        self.device_table.viewport().setAutoFillBackground(True)
        self.device_table.setStyleSheet(setup_styles.DEVICE_TABLE)
        self.device_table.setItemDelegate(SetupDeviceStatusDelegate(self.device_table))
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.verticalHeader().setDefaultSectionSize(46)
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.setAccessibleName("รายการเครื่องพิมพ์ที่ค้นพบ")
        self.device_table.cellClicked.connect(self.device_action_requested)
        layout.addWidget(self.device_table, 1)
        actions = QHBoxLayout()
        hint = QLabel("เลือกเครื่อง → ตรวจสอบ → สถานะพร้อมใช้งาน จึงกดถัดไปได้")
        hint.setWordWrap(True)
        hint.setStyleSheet(text_styles.label(C_TEXT2))
        actions.addWidget(hint)
        actions.addStretch()
        self.test_button = btn("ตรวจสอบเครื่องที่เลือก", "outline")
        self.test_button.setAccessibleDescription("ตรวจสอบ SNMP และ Web ของเครื่องพิมพ์ที่เลือก")
        self.test_button.clicked.connect(self.verify_requested)
        layout.addLayout(actions)

    def _toggle_fallback_actions(self, visible: bool) -> None:
        self.fallback_actions.setVisible(visible)
        self.fallback_toggle.setText("ซ่อนวิธีอื่น" if visible else "ค้นหาไม่พบ? ใช้วิธีอื่น")

    def set_scan_progress(self, completed: int, total: int) -> None:
        safe_total = max(1, int(total))
        safe_completed = min(max(0, int(completed)), safe_total)
        percent = round((safe_completed / safe_total) * 100)
        self.scan_progress_bar.setRange(0, safe_total)
        self.scan_progress_bar.setValue(safe_completed)
        self.scan_progress_bar.setFormat(f"สแกน {safe_completed:,} / {int(total):,} IP ({percent}%)")
        self.scan_progress_bar.setVisible(True)
