"""Legacy import UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from services.device_config import DeviceConfigRepository
from services.legacy_history_import import (
    LegacyHistoryImportError,
    LegacyHistoryImportResult,
    LegacyHistoryPreview,
    import_legacy_history,
    preview_legacy_history,
)
from ui.styles import reports as reports_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_GREEN, C_RED, C_TEXT2, F_2XL
from widgets import btn, fnt


class LegacyHistoryImportDialog(QDialog):
    """Preview and import only V4.6 aggregate usage history."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.preview: LegacyHistoryPreview | None = None
        self.import_result: LegacyHistoryImportResult | None = None
        self.setWindowTitle(tr("นำเข้าประวัติการใช้งาน V4.6", "Import V4.6 usage history"))
        self.resize(860, 620)
        self.setMinimumSize(720, 520)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel(tr("นำเข้าประวัติการใช้งาน V4.6", "Import V4.6 usage history"))
        title.setFont(fnt(F_2XL, True))
        root.addWidget(title)
        intro = QLabel(
            tr(
                "เลือกสำเนา Database จาก KOMI Report V4.6 ระบบจะตรวจสอบและแสดง Preview ก่อนนำเข้า",
                "Choose a copy of a KOMI Report V4.6 database. It will be checked and previewed before import.",
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(text_styles.label(C_TEXT2))
        root.addWidget(intro)

        boundary = QLabel(
            tr(
                "ประวัติต่อด้วย Slot เดิม · Serial ใช้เป็นหลักฐานการเปลี่ยนเครื่อง ไม่ใช้แบ่งประวัติ "
                "· ไม่แตะ IP, Username/Password, ราคา, Settings หรือ Billing Ledger",
                "History continues by logical Slot · Serial marks printer replacement and never splits the Slot "
                "· IP, credentials, prices, settings and Billing Ledger are not imported",
            )
        )
        boundary.setWordWrap(True)
        boundary.setStyleSheet(
            reports_styles.LEGACY_HISTORY_IMPORT_DIALOG_BOUNDARY
        )
        root.addWidget(boundary)

        source_row = QHBoxLayout()
        self.source_path = QLineEdit()
        self.source_path.setReadOnly(True)
        self.source_path.setPlaceholderText(
            tr("ยังไม่ได้เลือก Database V4.6", "No V4.6 database selected")
        )
        self.source_path.setMinimumHeight(42)
        source_row.addWidget(self.source_path, 1)
        self.choose_button = btn(tr("เลือก Database…", "Choose database…"), "outline")
        self.choose_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.choose_button)
        root.addLayout(source_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        self.preview_summary = QLabel(
            tr(
                "เลือก Database เพื่อดูจำนวนรายการ ช่วงวันที่ และข้อมูลซ้ำ",
                "Choose a database to preview rows, date range and duplicates.",
            )
        )
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setMinimumHeight(92)
        self.preview_summary.setStyleSheet(
            reports_styles.LEGACY_HISTORY_IMPORT_DIALOG_PREVIEW_SUMMARY
        )
        content_layout.addWidget(self.preview_summary)

        self.device_table = QTableWidget(0, 5)
        self.device_table.setObjectName("legacy_history_device_table")
        self.device_table.setHorizontalHeaderLabels(
            (
                "Slot",
                tr("จุดติดตั้งใน V5", "V5 installation point"),
                tr("ชื่อเครื่องเดิม", "Previous printer name"),
                "Serial Number",
                tr("จำนวนรายการ", "Rows"),
            )
        )
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.verticalHeader().setDefaultSectionSize(38)
        self.device_table.setMinimumHeight(150)
        device_header = self.device_table.horizontalHeader()
        device_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        device_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        device_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        device_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        device_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        content_layout.addWidget(self.device_table)

        self.preview_note = QLabel(
            tr(
                "ไฟล์ต้นฉบับจะเปิดแบบ Read-only และ V5 จะสร้าง Backup ก่อนเขียนข้อมูล",
                "The source stays read-only and V5 creates a backup before writing.",
            )
        )
        self.preview_note.setWordWrap(True)
        self.preview_note.setStyleSheet(text_styles.label(C_TEXT2))
        content_layout.addWidget(self.preview_note)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel(tr("พร้อมเลือกไฟล์", "Ready to choose a file"))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(text_styles.label(C_TEXT2))
        footer.addWidget(self.status_label, 1)
        self.close_button = btn(tr("ยกเลิก", "Cancel"), "outline")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        self.import_button = btn(tr("นำเข้าประวัติ", "Import history"), "primary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._run_import)
        footer.addWidget(self.import_button)
        root.addLayout(footer)

    def _set_status(self, text: str, *, state: str = "normal") -> None:
        colours = {
            "normal": C_TEXT2,
            "working": "#1769AA",
            "success": C_GREEN,
            "error": C_RED,
        }
        self.status_label.setText(text)
        self.status_label.setStyleSheet(text_styles.label(colours[state], font_weight='700'))

    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("เลือกสำเนา Database V4.6", "Choose a copy of the V4.6 database"),
            "",
            "SQLite Database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if path:
            self.load_source(path)

    def load_source(self, path: str) -> LegacyHistoryPreview | None:
        """Load a preview; public for focused UI checks."""

        self.preview = None
        self.import_result = None
        self.source_path.setText(path)
        self.import_button.setEnabled(False)
        self._set_status(tr("กำลังตรวจสอบ Database…", "Checking database…"), state="working")
        QApplication.processEvents()
        try:
            preview = preview_legacy_history(path)
        except LegacyHistoryImportError as err:
            self.device_table.setRowCount(0)
            self.preview_summary.setText(str(err))
            self._set_status(tr("ตรวจสอบไม่ผ่าน", "Validation failed"), state="error")
            return None
        self.preview = preview
        self._render_preview(preview)
        self.import_button.setEnabled(preview.new_rows > 0)
        if preview.new_rows:
            self.import_button.setText(
                tr(
                    f"สำรองและนำเข้า {preview.new_rows:,} รายการ",
                    f"Back up and import {preview.new_rows:,} rows",
                )
            )
            self._set_status(tr("ตรวจสอบผ่าน พร้อมนำเข้า", "Validated and ready"), state="success")
        else:
            self.import_button.setText(tr("ไม่มีข้อมูลใหม่", "No new history"))
            self._set_status(
                tr("ข้อมูลทั้งหมดเคยนำเข้าแล้ว", "All history has already been imported"),
                state="normal",
            )
        return preview

    def _render_preview(self, preview: LegacyHistoryPreview) -> None:
        date_range = (
            f"{preview.date_min} – {preview.date_max}"
            if preview.date_min and preview.date_max
            else tr("ไม่พบวันที่ที่อ่านได้", "No readable dates")
        )
        self.preview_summary.setText(
            tr(
                f"ช่วงข้อมูล: {date_range}\n"
                f"พบทั้งหมด {preview.total_rows:,} · นำเข้าใหม่ {preview.new_rows:,} · "
                f"ข้อมูลซ้ำ {preview.duplicate_rows:,} · อ่านไม่ได้ {preview.rejected_rows:,}",
                f"Date range: {date_range}\n"
                f"Total {preview.total_rows:,} · New {preview.new_rows:,} · "
                f"Duplicates {preview.duplicate_rows:,} · Rejected {preview.rejected_rows:,}",
            )
        )
        configured = {device.slot: device.name for device in DeviceConfigRepository().list()}
        self.device_table.setRowCount(len(preview.devices))
        for row, device in enumerate(preview.devices):
            values = (
                f"Slot {device.slot + 1}",
                configured.get(device.slot, tr("กำหนดใน Setup Wizard", "Set in Setup Wizard")),
                device.machine_name or "—",
                device.serial or "—",
                f"{device.reading_count:,}",
            )
            for column, value in enumerate(values):
                self.device_table.setItem(row, column, QTableWidgetItem(value))

    def _run_import(self) -> None:
        if self.preview is None:
            return
        self.choose_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self._set_status(tr("กำลังสำรองและนำเข้า…", "Backing up and importing…"), state="working")
        QApplication.processEvents()
        try:
            result = import_legacy_history(self.preview)
        except LegacyHistoryImportError as err:
            self.choose_button.setEnabled(True)
            self.import_button.setEnabled(True)
            self._set_status(str(err), state="error")
            return
        self.import_result = result
        self.import_button.setText(tr("นำเข้าสำเร็จ", "Import complete"))
        self.close_button.setText(tr("ปิด", "Close"))
        self.preview_note.setText(
            tr(
                f"Backup: {result.backup_path.name}",
                f"Backup: {result.backup_path.name}",
            )
        )
        self._set_status(
            tr(
                f"นำเข้าประวัติสำเร็จ {result.imported_rows:,} รายการ",
                f"Imported {result.imported_rows:,} history rows",
            ),
            state="success",
        )
