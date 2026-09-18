"""Review a held or issued day's manual monetary correction."""
from decimal import Decimal
import json
import socket
import sqlite3

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QCheckBox, QPlainTextEdit, QDialogButtonBox)
from services.billing_manual_review import BillingManualReview
from ui.counter_review import plain
from i18n import tr


class BillingManualReviewDialog(QDialog):
    def __init__(self, ledger_id, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or BillingManualReview()
        self.ledger_id, self.result_id, self.preview = ledger_id, None, None
        self.setWindowTitle(tr('ตรวจและแก้ยอดย้อนหลัง', 'Review a historical amount'))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        try:
            self.preview = self.service.preview(ledger_id)
        except (ValueError, sqlite3.Error):
            layout.addWidget(plain(tr('เลือก Hold หรือรายการล่าสุดของวันที่ปิดแล้ว', 'Select a current hold or posting for a closed day.')))
        form = QFormLayout()
        if self.preview:
            p = self.preview
            for label, value in ((tr('เครื่องพิมพ์', 'Printer'), f"Slot {p['slot']+1} · {p['name']} · {p['serial']}"),
                                 (tr('วันที่ / รอบบิล', 'Day / period'), f"{p['day']} · {' – '.join(p['period'])}"),
                                 (tr('ยอดเดิม', 'Previous amount'), f"฿{p['gross']/100:,.2f} / ฿{p['net']/100:,.2f}"),
                                 (tr('เหตุผลที่พักยอด', 'Hold reason'), p['hold_reason'] or '—')):
                form.addRow(label, plain(value))
        self.gross, self.net = QDoubleSpinBox(), QDoubleSpinBox()
        for field in (self.gross, self.net):
            field.setDecimals(2)
            field.setRange(0, 1_000_000_000)
            field.setPrefix('฿ ')
        if self.preview:
            self.gross.setValue(self.preview['gross'] / 100)
            self.net.setValue(self.preview['net'] / 100)
        form.addRow(tr('ยอดใหม่ก่อนส่วนลด', 'New gross amount'), self.gross)
        form.addRow(tr('ยอดใหม่สุทธิ', 'New net amount'), self.net)
        layout.addLayout(form)
        if self.preview:
            proof = QPlainTextEdit(json.dumps({'delta': self.preview['delta'], 'evidence': self.preview['proof']}, ensure_ascii=False, indent=2))
            proof.setReadOnly(True)
            proof.setMaximumHeight(140)
            layout.addWidget(proof)
        layout.addWidget(plain(tr(
            'ยอดนี้เป็นจำนวนเงินที่ผู้ตรวจกรอก ไม่ได้ยืนยันว่ามิเตอร์เดิมถูกต้อง ต้นฉบับและคำเตือนมิเตอร์ยังคงอยู่ '
            'ฉบับแก้ไขจะเข้าคิวส่งให้สมาชิกที่ยืนยันสิทธิ์แล้ว หากบัญชีปลายทางไม่ตรงจะรอตรวจ',
            'These are reviewer-entered amounts, not verification of the original meter. Original evidence and meter warnings remain. '
            'The correction is queued for verified members; differing accounts require review.')))
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText(tr('เหตุผลและหลักฐานที่ใช้ตรวจยอด', 'Reason and evidence for the amount'))
        layout.addWidget(self.reason)
        self.reviewed = QCheckBox(tr('ตรวจยอดแล้ว และรับทราบว่ามีผลกับบัญชีร่วม', 'I reviewed these amounts and their effect on shared accounting'))
        layout.addWidget(self.reviewed)
        self.error = plain('')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText(tr('ยืนยันฉบับแก้ไข', 'Confirm correction'))
        self.confirm_button.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('ยกเลิก', 'Cancel'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.reason.textChanged.connect(self._validate)
        self.reviewed.toggled.connect(self._validate)
        self.gross.valueChanged.connect(self._validate)
        self.net.valueChanged.connect(self._validate)
        self._validate()

    def _validate(self, *_):
        self.confirm_button.setEnabled(bool(self.preview and self.reviewed.isChecked() and self.reason.text().strip()
                                           and self.net.value() <= self.gross.value()))

    def _confirm(self):
        if not self.confirm_button.isEnabled():
            return
        try:
            self.result_id = self.service.confirm(self.ledger_id, expected_revision=self.preview['revision'],
                actor=socket.gethostname(), reason=self.reason.text(),
                gross_cents=int(Decimal(str(self.gross.value())) * 100), net_cents=int(Decimal(str(self.net.value())) * 100))
        except (ValueError, sqlite3.Error, OSError):
            self.error.setText(tr('บันทึกไม่สำเร็จหรือข้อมูลเปลี่ยน กรุณาปิดแล้วตรวจใหม่', 'Could not save, or data changed. Close and review again.'))
            self.confirm_button.setEnabled(False)
            return
        self.accept()
