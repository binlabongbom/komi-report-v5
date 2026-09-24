"""Counter review UI, separate from the settings/report monolith."""
from ui.styles import text as text_styles
from ui.review_components import field_label

from datetime import datetime
import sqlite3
import socket

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QFormLayout, QLabel,
                            QComboBox, QLineEdit, QCheckBox, QDialogButtonBox, QPushButton)
from i18n import tr


def plain(text):
    label = QLabel(str(text))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class CounterReviewDialog(QDialog):
    def __init__(self, cache, slot, day, key, preview, parent=None, *, clock=None):
        super().__init__(parent)
        self.cache, self.slot, self.day, self.key, self.preview = cache, slot, day, key, preview
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.setWindowTitle(tr("ยืนยันค่าเริ่มต้นมิเตอร์", "Confirm meter baseline"))
        self.setMinimumWidth(480)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        identity = preview["device_identity"]
        for title, value in (
            (tr("เครื่องพิมพ์", "Printer"), identity.get("name", "")),
            ("Serial", identity["serial"]),
            (tr("มิเตอร์", "Counter"), preview.get("label", key)),
            (tr("ค่าก่อนลดลง", "Counter before drop"), preview["before"]),
            (tr("ค่าเริ่มต้นใหม่ที่อ่านได้", "Observed new baseline"), preview["baseline"]),
            (tr("อ่านเมื่อ", "Observed at"), preview["observed_at"]),
            (tr("ยอดที่นับได้เดิม", "Previously counted usage"), preview["preserved_delta"]),
        ):
            form.addRow(title, plain(value))
        layout.addLayout(form)
        layout.addWidget(plain(tr(
            "ระบบจะนับเฉพาะยอดที่เพิ่มจากค่าเริ่มต้นใหม่นี้ ยอดเดิมจะไม่ถูกบวกซ้ำ และรายงานวันที่มีปัญหายังคงรอตรวจสอบ",
            "Only increases beyond this baseline will be counted. Existing usage is preserved; the affected day's report stays under review.",
        )))
        layout.addWidget(plain(tr(
            "การยืนยันนี้มีผลกับข้อมูลบนคอมพิวเตอร์เครื่องนี้",
            "This confirmation applies to data on this computer.",
        )))
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText(tr("เหตุผลที่ยืนยันค่าเริ่มต้นใหม่", "Reason for the new baseline"))
        self.reason.setAccessibleName(self.reason.placeholderText())
        field_label(layout, self.reason)
        layout.addWidget(self.reason)
        self.verified = QCheckBox(tr("ตรวจสอบ Serial และค่ามิเตอร์จากเครื่องพิมพ์แล้ว", "I checked the printer serial and meter"))
        layout.addWidget(self.verified)
        self.error = plain("")
        self.error.setStyleSheet(text_styles.label('#B42318'))
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm.setText(tr("ยืนยันค่าเริ่มต้นใหม่", "Confirm new baseline"))
        self.confirm.setEnabled(False)
        self.confirm.setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("ยกเลิก", "Cancel"))
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._confirm)
        self.reason.textChanged.connect(self._validate)
        self.verified.toggled.connect(self._validate)
        layout.addWidget(self.buttons)

    def _validate(self):
        self.confirm.setEnabled(bool(self.reason.text().strip()) and self.verified.isChecked())

    def _confirm(self):
        if not self.confirm.isEnabled():
            return
        try:
            self.cache.confirm_counter_baseline(self.slot, self.day, self.key,
                expected_revision=self.preview["revision"], actor=socket.gethostname(),
                reason=self.reason.text(), at=self.clock())
        except (ValueError, OSError, sqlite3.Error):
            self.error.setText(tr(
                "ยืนยันไม่สำเร็จ ข้อมูลอาจเปลี่ยนหรือบันทึกไม่ได้ กรุณาปิดหน้าต่างนี้แล้วเปิดตรวจสอบใหม่",
                "Confirmation failed. Data may have changed or could not be saved. Close this dialog and review again.",
            ))
            self.confirm.setEnabled(False)
            return
        self.accept()


class CounterReviewPanel(QWidget):
    def __init__(self, repository, cache, parent=None, *, clock=None, subject_cache=None, raw_cache=None):
        super().__init__(parent)
        self.repository, self.cache = repository, cache
        if subject_cache is None:
            from services.subject_history import SubjectDailyCacheStore
            subject_cache = SubjectDailyCacheStore()
        self.subject_cache = subject_cache
        if raw_cache is None:
            from services.raw_counter_review import RawCounterReviewStore
            raw_cache = RawCounterReviewStore()
        self.raw_cache = raw_cache
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._dialog = None
        layout = QVBoxLayout(self)
        layout.addWidget(plain(tr("ตรวจสอบมิเตอร์ที่ลดลงก่อนเริ่มนับต่อ", "Review falling counters before resuming usage")))
        self.items = QComboBox()
        self.items.setAccessibleName(tr("รายการมิเตอร์รอตรวจสอบ", "Counters awaiting review"))
        layout.addWidget(self.items)
        self.open_button = QPushButton(tr("ตรวจสอบและยืนยัน", "Review and confirm"))
        self.open_button.clicked.connect(self.open_review)
        layout.addWidget(self.open_button)
        refresh = QPushButton(tr("รีเฟรช", "Refresh"))
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        self.evidence_button = QPushButton(tr("ประวัติ Web และช่วงขาดการอ่าน", "Web history and missing intervals"))
        self.evidence_button.clicked.connect(self.open_evidence)
        layout.addWidget(self.evidence_button)
        self._evidence_dialog = None
        self.slot_baseline_button = QPushButton(tr("ตรวจฐานมิเตอร์ของ Slot", "Review slot meter baseline"))
        self.slot_baseline_button.clicked.connect(self.open_slot_baseline)
        layout.addWidget(self.slot_baseline_button)
        self._slot_baseline_dialog = None
        self.message = plain("")
        layout.addWidget(self.message)
        layout.addStretch()
        self.refresh()

    def open_slot_baseline(self):
        if self._slot_baseline_dialog is not None:
            self._slot_baseline_dialog.raise_()
            return
        from ui.slot_baseline_review import SlotBaselineDialog
        dialog = SlotBaselineDialog(self.repository.list(enabled_only=True), self)
        self._slot_baseline_dialog = dialog
        def finished(_result):
            self._slot_baseline_dialog = None
            self.refresh()
            dialog.deleteLater()
        dialog.finished.connect(finished)
        dialog.open()

    def open_evidence(self):
        if self._evidence_dialog is not None:
            self._evidence_dialog.raise_()
            return
        from ui.web_evidence_report import WebEvidenceDialog
        dialog = WebEvidenceDialog(self.repository.list(enabled_only=False), self)
        self._evidence_dialog = dialog
        def finished(_result):
            self._evidence_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(finished)
        dialog.open()

    def refresh(self):
        selected = self.items.currentData()
        self.items.clear()
        day = self.clock().date()
        for device in self.repository.list(enabled_only=True):
            state = self.cache.load(device.slot, day) or {}
            labels = state.get("source", {}).get("counter_sources", {})
            for key in state.get("counter_review", {}):
                label = labels.get(key, {}).get("label", key)
                self.items.addItem(f"{device.name} · {label}", (device.slot, day, key))
            subject_state = self.subject_cache.load(device.slot, day) or {}
            for key, item in subject_state.get("subjects", {}).items():
                if item.get("counter_review"):
                    label = f"{item['subject_type']} · {item['subject_name']} ({item['subject_id']})"
                    self.items.addItem(f"{device.name} · {label}", (device.slot, day, key, "subject"))
            raw_state = self.raw_cache.load(device.slot, day)
            for key in raw_state["counter_review"]:
                label = raw_state["source"]["counter_sources"][key]["label"]
                self.items.addItem(f"{device.name} · {label}", (device.slot, day, key, "raw"))
        index = self.items.findData(selected)
        if index >= 0:
            self.items.setCurrentIndex(index)
        self.open_button.setEnabled(self.items.count() > 0)
        self.message.setText("" if self.items.count() else tr("ไม่มีรายการรอตรวจสอบในข้อมูลวันนี้", "No pending reviews in today's data"))

    def open_review(self):
        if self._dialog is not None:
            self._dialog.raise_()
            return
        selected = self.items.currentData()
        if not selected:
            return
        slot, day, key = selected[:3]
        cache = self.cache
        if len(selected) == 4:
            cache = self.raw_cache if selected[3] == "raw" else self.subject_cache
        try:
            preview = cache.preview_counter_baseline(slot, day, key)
        except (ValueError, OSError, sqlite3.Error):
            self.message.setText(tr("ยังยืนยันไม่ได้ กรุณาอ่าน Serial และมิเตอร์ล่าสุดแล้วตรวจสอบใหม่", "Read the current serial and meter before reviewing again"))
            return
        dialog = CounterReviewDialog(cache, slot, day, key, preview, self, clock=self.clock)
        self._dialog = dialog
        def finished(_result):
            self._dialog = None
            dialog.deleteLater()
            self.refresh()
        dialog.finished.connect(finished)
        dialog.open()
