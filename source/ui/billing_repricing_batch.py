"""Review every changed posting before an atomic date-range price correction."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import logging
import socket

from PyQt6.QtCore import QDate, QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QDateEdit, QComboBox,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QAbstractItemView, QDialogButtonBox)

from services.billing_repricing_batch import BatchRepricingService
from ui.counter_review import plain


class BatchRepricingDialog(QDialog):
    def __init__(self, parent=None, *, service=None, today=None):
        super().__init__(parent)
        self.service = service or BatchRepricingService()
        self.preview = None
        self.result_ids = ()
        self.future = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-reprice-preview")
        pool = self.pool
        self.destroyed.connect(lambda: pool.shutdown(wait=False, cancel_futures=True))
        self.setWindowTitle("คำนวณราคาใหม่ตามช่วงวันที่")
        self.resize(940, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(plain("ใช้ราคาตามวันบังคับใช้ คงมิเตอร์ ส่วนลด และรอบบิลเดิม สร้างรายการแก้ไขพร้อมประวัติบนคอมนี้ โดยเก็บรายการเดิมไว้"))
        controls = QHBoxLayout()
        now = today or date.today()
        self.start = QDateEdit(QDate(now.replace(day=1)))
        self.end = QDateEdit(QDate(now))
        for picker in (self.start, self.end):
            picker.setCalendarPopup(True)
            picker.setDisplayFormat("dd/MM/yyyy")
            controls.addWidget(picker)
        self.slots = QComboBox()
        self.slots.addItem("ทุก Slot", [0, 1, 2])
        for slot in range(3):
            self.slots.addItem(f"Slot {slot + 1}", [slot])
        controls.addWidget(self.slots)
        self.load_button = QPushButton("ตรวจรายการที่เปลี่ยน")
        self.load_button.clicked.connect(self.load)
        controls.addWidget(self.load_button)
        layout.addLayout(controls)
        self.status = plain("เลือกช่วงวันที่ใช้งาน แล้วตรวจยอดก่อนยืนยัน")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["รายการ", "วันที่ใช้งาน", "เครื่อง / Serial", "สุทธิเดิม", "สุทธิใหม่", "ผลตรวจ"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText("เหตุผลที่คำนวณใหม่")
        layout.addWidget(self.reason)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("ยืนยันรายการที่เปลี่ยนทั้งหมด")
        self.confirm_button.setEnabled(False)
        self.confirm_button.setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.buttons.accepted.connect(self.confirm)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.reason.textChanged.connect(self.validate)
        self.start.dateChanged.connect(self.invalidate)
        self.end.dateChanged.connect(self.invalidate)
        self.slots.currentIndexChanged.connect(self.invalidate)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.collect)
        self.finished.connect(lambda _: self.timer.stop())

    def invalidate(self, *_):
        self.preview = None
        self.table.setRowCount(0)
        self.status.setText("ช่วงวันที่เปลี่ยน กรุณาตรวจรายการใหม่")
        self.validate()

    def validate(self, *_):
        self.confirm_button.setEnabled(bool(self.preview and self.preview["changed"] and self.reason.text().strip() and self.future is None))

    def load(self):
        if self.future is not None:
            return
        self.invalidate()
        self.scope = self.start.date().toPyDate(), self.end.date().toPyDate(), self.slots.currentData()
        for widget in (self.start, self.end, self.slots, self.load_button):
            widget.setEnabled(False)
        self.status.setText("กำลังตรวจรายการและประวัติราคา…")
        self.future = self.pool.submit(self.service.preview, *self.scope)
        self.timer.start()

    def collect(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        for widget in (self.start, self.end, self.slots, self.load_button):
            widget.setEnabled(True)
        try:
            self.preview = future.result()
        except Exception as error:
            logging.getLogger(__name__).exception("Batch repricing preview failed")
            self.status.setText(str(error) if isinstance(error, ValueError) else "อ่านข้อมูลไม่สำเร็จ กรุณาลองใหม่")
            return
        p = self.preview
        self.status.setText(f"เปลี่ยน {len(p['changed']):,} รายการ · ไม่เปลี่ยน {p['unchanged']:,} · ข้ามรายการรอตรวจ {len(p['skipped']):,}\n"
            f"ยอดสุทธิของรายการที่เปลี่ยน: ฿{p['old_net_cents']/100:,.2f} → ฿{p['net_cents']/100:,.2f}")
        self.table.setRowCount(len(p["changed"]) + len(p["skipped"]))
        for index, row in enumerate(p["changed"]):
            values = (row["ledger_id"], row["record_date"], f"{row['device_name']} / {row['serial']}",
                f"{row['old_net_cents']/100:,.2f}", f"{row['net_cents']/100:,.2f}", f"ใช้ราคาตั้งแต่ {row['price_effective_date']}")
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        for index, ledger_id in enumerate(p["skipped"], start=len(p["changed"])):
            self.table.setItem(index, 0, QTableWidgetItem(str(ledger_id)))
            self.table.setItem(index, 5, QTableWidgetItem("ข้าม: รอตรวจ / ปรับด้วยมือ / ราคาไม่ครบ"))
        self.table.resizeColumnsToContents()
        self.validate()

    def confirm(self):
        if not self.confirm_button.isEnabled():
            return
        self.confirm_button.setEnabled(False)
        try:
            self.result_ids = self.service.confirm(*self.scope, expected_revision=self.preview["revision"],
                actor=socket.gethostname(), reason=self.reason.text())
        except Exception:
            logging.getLogger(__name__).exception("Batch repricing failed")
            self.preview = None
            self.status.setText("บันทึกไม่สำเร็จหรือข้อมูลเปลี่ยน ไม่มีการแก้เพียงบางรายการ กรุณาตรวจรายการใหม่")
            return
        self.accept()
