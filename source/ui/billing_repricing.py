"""A concrete before/after review of a dated price correction."""
import socket
import sqlite3

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox
from services.billing_repricing import BillingRepricingService
from ui.counter_review import plain
from i18n import tr


class BillingRepricingDialog(QDialog):
    def __init__(self, ledger_id, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or BillingRepricingService()
        self.ledger_id = ledger_id
        self.setWindowTitle(tr("คำนวณใหม่จากประวัติราคา", "Recalculate from dated prices"))
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.preview = None
        self.result_id = None
        try:
            self.preview = self.service.preview(ledger_id)
        except (ValueError, sqlite3.Error):
            layout.addWidget(plain(tr("รายการนี้ยังคำนวณใหม่ไม่ได้ อาจมีรายการแก้ไขแล้ว หรือหลักฐานมิเตอร์/ราคาไม่พร้อม",
                "This entry cannot be repriced. It may be superseded, or verified meter evidence/dated prices are unavailable.")))
        if self.preview:
            p = self.preview
            form = QFormLayout()
            for label, value in (
                (tr("เครื่องพิมพ์", "Printer"), p["device_name"]), ("Serial", p["serial"]),
                (tr("วันที่ใช้งาน", "Usage date"), p["record_date"]),
                (tr("ราคามีผลตั้งแต่", "Price effective from"), p["price_effective_date"]),
                (tr("ก่อนหักส่วนลด", "Gross amount"), f"฿{p['old_gross_cents']/100:,.2f} → ฿{p['gross_cents']/100:,.2f}"),
                (tr("ยอดสุทธิ", "Net amount"), f"฿{p['old_net_cents']/100:,.2f} → ฿{p['net_cents']/100:,.2f}"),
            ):
                form.addRow(label, plain(value))
            layout.addLayout(form)
            layout.addWidget(plain(tr(
                "ใช้มิเตอร์ หมวดราคา ส่วนลด และรอบบิลจากรายการเดิม สร้างรายการแก้ไขพร้อมประวัติในคอมนี้ เอกสารเดิมไม่ถูกเขียนทับ",
                "Uses the original usage, categories, discount and billing period. Appends a local correction with audit; original documents remain unchanged.")))
            if not p["changed"]:
                layout.addWidget(plain(tr("ราคาและยอดไม่เปลี่ยน", "Prices and amounts are unchanged")))
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText(tr("เหตุผลที่คำนวณใหม่", "Reason for recalculation"))
        layout.addWidget(self.reason)
        self.error = plain("")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText(tr("ยืนยันรายการแก้ไข", "Confirm correction"))
        self.confirm_button.setEnabled(False)
        self.confirm_button.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("ยกเลิก", "Cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        self.reason.textChanged.connect(lambda: self.confirm_button.setEnabled(
            bool(self.preview and self.preview["changed"] and self.reason.text().strip())))
        layout.addWidget(buttons)

    def _confirm(self):
        if not self.confirm_button.isEnabled():
            return
        try:
            self.result_id = self.service.confirm(self.ledger_id, expected_revision=self.preview["revision"],
                actor=socket.gethostname(), reason=self.reason.text())
        except (ValueError, sqlite3.Error, OSError):
            self.error.setText(tr("บันทึกไม่สำเร็จหรือข้อมูลเปลี่ยน กรุณาปิดแล้วตรวจสอบใหม่",
                                 "Could not save, or data changed. Close and review again."))
            self.confirm_button.setEnabled(False)
            return
        self.accept()
