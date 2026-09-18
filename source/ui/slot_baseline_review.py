"""Review actual Web baselines before creating a shared slot decision."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime
import json
import logging
import socket

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QCheckBox, QTableWidget, QTableWidgetItem, QAbstractItemView, QDialogButtonBox)

from services.shared_slot_review import SharedSlotReviewService
from services.slot_meter_continuity import counter_values, _number
from ui.counter_review import plain


def amount(value):
    return f"{value.numerator:,}" if value.denominator == 1 else f"{Decimal(value.numerator) / Decimal(value.denominator):,.2f}"


class SlotBaselineDialog(QDialog):
    def __init__(self, devices, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or SharedSlotReviewService()
        self.preview = self.future = self.operation = None
        self.revision = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-slot-review")
        pool = self.pool
        self.destroyed.connect(lambda: pool.shutdown(wait=False, cancel_futures=True))
        self.setWindowTitle("ตรวจและยืนยันฐานมิเตอร์ของ Slot")
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(plain("ฐานนี้ใช้รักษายอดสะสมของ Slot เมื่อเปลี่ยนเครื่องหรือรีเซ็ตมิเตอร์ ตรวจ Serial และค่าที่อ่านได้ก่อนยืนยัน"))
        row = QHBoxLayout()
        self.slots = QComboBox()
        for device in devices:
            if device.enabled:
                self.slots.addItem(f"Slot {device.slot + 1} · {device.name} · {device.serial or 'ยังไม่มี Serial'}", device.slot)
        row.addWidget(self.slots, 1)
        self.load_button = QPushButton("ตรวจค่า Web ล่าสุด")
        row.addWidget(self.load_button)
        layout.addLayout(row)
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText("เหตุผล เช่น เปลี่ยนเครื่องแทนเครื่องเดิม หรือรีเซ็ตมิเตอร์ที่ตรวจสอบแล้ว")
        layout.addWidget(self.reason)
        self.status = plain("ระบุเหตุผลแล้วตรวจค่าที่บันทึกจากเครื่องพิมพ์")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["มิเตอร์ / ผู้ใช้", "ค่าจากเครื่องที่ใช้เป็นฐานใหม่", "ยอดสะสม Slot ที่ยกมา"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.verified = QCheckBox("ตรวจสอบเครื่องใน Slot, Serial และฐานมิเตอร์ตามรายการแล้ว")
        layout.addWidget(self.verified)
        layout.addWidget(plain("การยืนยันเป็นการเปลี่ยนฐานของ Slot ร่วมกันทั้งระบบ และจะบันทึกประวัติกับรายการรอส่งให้สมาชิกพร้อมกัน การบันทึกบนคอมนี้ยังไม่ยืนยันว่าคอมอื่นได้รับแล้ว"))
        layout.addWidget(plain("รายงานเรียกเก็บเดิมและรายการมิเตอร์ที่ยังรอตรวจสอบจะไม่ถูกอนุมัติจากการยืนยันฐานนี้"))
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("ยืนยันฐานและบันทึกประวัติ")
        self.confirm_button.setEnabled(False)
        self.confirm_button.setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.collect)
        self.finished.connect(lambda _: self.timer.stop())
        self.slots.currentIndexChanged.connect(self.invalidate)
        self.reason.textChanged.connect(self.invalidate)
        self.verified.toggled.connect(self.validate)
        self.load_button.clicked.connect(self.load)
        self.buttons.accepted.connect(self.confirm)
        self.buttons.rejected.connect(self.reject)

    def validate(self, *_):
        self.confirm_button.setEnabled(bool(self.preview and self.verified.isChecked() and self.future is None))

    def invalidate(self, *_):
        self.preview = None
        self.verified.setChecked(False)
        self.table.setRowCount(0)
        self.status.setText("กรุณาตรวจค่าล่าสุดก่อนยืนยัน")
        self.validate()

    def busy(self, value):
        for widget in (self.slots, self.reason, self.load_button, self.verified):
            widget.setEnabled(not value)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(self.operation != "confirm")
        self.validate()

    def load(self):
        if self.future is not None:
            return
        self.invalidate()
        if self.slots.currentData() is None or not self.reason.text().strip():
            self.status.setText("เลือก Slot และระบุเหตุผลก่อนตรวจค่า")
            return
        self.operation = "preview"
        self.future = self.pool.submit(self.service.preview, self.slots.currentData(),
            actor=socket.gethostname(), reason=self.reason.text().strip())
        self.busy(True)
        self.status.setText("กำลังตรวจ Serial ค่า Web และฐานเดิม…")
        self.timer.start()

    def collect(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        operation, self.operation = self.operation, None
        self.busy(False)
        try:
            result = future.result()
        except Exception as error:
            logging.getLogger(__name__).exception("Slot baseline review failed")
            self.preview = None
            self.table.setRowCount(0)
            self.status.setText("ยังยืนยันไม่ได้ กรุณาตรวจเครื่องและข้อมูลล่าสุด แล้วตรวจรายการอีกครั้ง\n" +
                (str(error) if isinstance(error, ValueError) else "อ่านหรือบันทึกข้อมูลไม่สำเร็จ"))
            self.validate()
            return
        if operation == "confirm":
            self.revision = result
            self.accept()
            return
        self.preview = result
        review = result["review"]
        doc = review["epoch"]["document"]
        baseline = doc["baseline_event"]["payload"]
        label = {"initial": "กำหนดฐาน Slot ครั้งแรก", "replacement": "เปลี่ยนเครื่องใน Slot เดิม", "reset": "ยืนยันหลังรีเซ็ตมิเตอร์"}[doc["operation"]]
        observed = datetime.fromisoformat(baseline["observed_at"]).astimezone().strftime("%d/%m/%Y %H:%M:%S")
        self.status.setText(f"{label}\nSerial: {result['previous_serial'] or 'ยังไม่มีฐานเดิม'} → {baseline['serial']} · อ่านเมื่อ {observed}")
        values = counter_values(doc["baseline_event"])
        self.table.setRowCount(len(doc["carried"]))
        for index, (key, carried) in enumerate(sorted(doc["carried"].items())):
            field, kind, subject = json.loads(key)
            text = result["counter_labels"].get(key, field + (f" · {kind} {subject}" if kind else ""))
            for column, value in enumerate((text, amount(values[key]) if key in values else "ไม่มีค่าใหม่ — เก็บยอดเดิม", amount(_number(carried)))):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.validate()

    def confirm(self):
        if not self.confirm_button.isEnabled():
            return
        self.operation = "confirm"
        self.future = self.pool.submit(self.service.confirm, self.preview)
        self.busy(True)
        self.status.setText("กำลังบันทึกฐาน Slot และประวัติร่วม…")
        self.timer.start()

    def reject(self):
        if self.operation != "confirm":
            super().reject()

    def closeEvent(self, event):
        if self.operation == "confirm":
            event.ignore()
        else:
            super().closeEvent(event)
