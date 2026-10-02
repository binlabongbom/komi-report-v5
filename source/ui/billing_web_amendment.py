"""Explicit review before creating local immutable Web allocation corrections."""
from ui.review_components import field_label

from ui.resource_cleanup import close_executor_with
from concurrent.futures import ThreadPoolExecutor
import logging
import socket

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QLineEdit, QTableWidget,
                            QTableWidgetItem, QAbstractItemView, QDialogButtonBox)
from services.billing_web_amendment import BillingWebAmendmentService
from i18n import tr
from ui.counter_review import plain


class BillingWebAmendmentDialog(QDialog):
    def __init__(self, scope, parent=None, *, database_path=None, service=None):
        super().__init__(parent)
        self.scope = scope
        self.service = service or BillingWebAmendmentService(database_path=database_path)
        self.preview = self.future = self.operation = None
        self.result_ids = ()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-web-amendment")
        close_executor_with(self, self.pool)
        self.setWindowTitle("แก้การแบ่งยอดตามหลักฐาน Web")
        self.resize(1000, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(plain(f"Slot {scope[0] + 1} · {scope[2]:%d/%m/%Y} – {scope[3]:%d/%m/%Y}"))
        self.description = plain("ตรวจตัวนับเครื่องทั้งหมดและยอดรวมเดิม ใช้ราคาและส่วนลดที่บันทึกไว้ ไม่คิดเงินจากกราฟเฉลี่ย "
            "ยืนยันแล้วจะเก็บต้นฉบับและคิวส่งฉบับแก้ไข สมาชิกที่เชื่อมต่อและยืนยันสิทธิ์แล้วจึงรับได้ "
            "ดูรายการรอยืนยันรับได้ที่การตั้งค่าเครือข่าย")
        layout.addWidget(self.description)
        self.load_button = QPushButton("ตรวจการแบ่งยอด")
        self.load_button.clicked.connect(self.load)
        layout.addWidget(self.load_button)
        self.status = plain("เลือกตรวจรายการก่อนยืนยัน · ใช้เฉพาะวันที่ปิดแล้วและฐาน Slot ที่ยืนยันแล้ว")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["วันลงยอด", "รายการเดิม", "สุทธิเดิม", "สุทธิใหม่", "ช่วงหลักฐาน / หมายเหตุ"])
        from PyQt6.QtWidgets import QHeaderView
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText("เหตุผลที่แก้การแบ่งยอด")
        self.reason.textChanged.connect(self.validate)
        field_label(layout, self.reason)
        layout.addWidget(self.reason)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("ยืนยันฉบับแก้ไขบนคอมนี้")
        self.confirm_button.setEnabled(False)
        self.confirm_button.setAutoDefault(False)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText(tr('ยกเลิก', 'Cancel'))
        self.cancel_button.setDefault(True)
        self.buttons.accepted.connect(self.confirm)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.collect)
        self.finished.connect(lambda _: self.timer.stop())

    def validate(self):
        self.confirm_button.setEnabled(bool(self.preview and self.preview["changed"] and self.reason.text().strip() and self.future is None))

    def load(self):
        if self.future is not None:
            return
        self.preview = None
        self.table.setRowCount(0)
        self.operation = "preview"
        self.status.setText(tr('กำลังตรวจหลักฐานและบัญชีเดิม…', 'Checking evidence and original accounting entries…'))
        self.load_button.setEnabled(False)
        self.future = self.pool.submit(self.service.preview, *self.scope)
        self.validate()
        self.timer.start()

    def collect(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        operation, self.operation = self.operation, None
        self.load_button.setEnabled(True)
        self.reason.setEnabled(True)
        self.cancel_button.setEnabled(True)
        try:
            result = future.result()
        except Exception as error:
            logging.getLogger(__name__).exception("Web allocation review failed")
            self.preview = None
            self.status.setText(str(error) if isinstance(error, ValueError) else "บันทึกหรืออ่านข้อมูลไม่สำเร็จ ไม่มีการแก้เพียงบางรายการ กรุณาตรวจใหม่")
            self.validate()
            return
        if operation == "confirm":
            self.result_ids = result
            self.accept()
            return
        self.preview = result
        self.show_preview(result)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(4, 430)
        self.table.resizeRowsToContents()
        self.validate()

    def show_preview(self, result):
        self.status.setText(tr("เปลี่ยน {count} วัน · สุทธิของรายการที่เปลี่ยน ฿{before:,.2f} → ฿{after:,.2f}\nยอดหน้าไม่เพิ่มซ้ำ · ส่วนลดปัดเป็นสตางค์ต่อวันจึงอาจทำให้ยอดเงินต่างเล็กน้อย",
            "Changed days: {count} · Net amount of changed entries: ฿{before:,.2f} → ฿{after:,.2f}\nPages are not counted twice. Daily discount rounding may slightly change the amount.").format(
                count=len(result['changed']), before=result['old_net_cents']/100, after=result['net_cents']/100))
        self.table.setRowCount(len(result["changed"]))
        for index, item in enumerate(result["changed"]):
            notes = "\n".join(dict.fromkeys(i["remark"] or f"{i['from']} – {i['to']}" for i in item["intervals"]))
            values = (item["day"], item["ledger_id"] or "รายการจัดสรรใหม่ · ไม่ใช่การอ่าน", f"{item['old_net_cents']/100:,.2f}",
                      f"{item['net_cents']/100:,.2f}", notes or "ย้ายยอดไปตามหลักฐานของวันอื่นในช่วงเดียวกัน")
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

    def confirm(self):
        if not self.confirm_button.isEnabled():
            return
        self.operation = "confirm"
        for button in (self.confirm_button, self.cancel_button, self.load_button, self.reason):
            button.setEnabled(False)
        self.status.setText(tr('กำลังบันทึกฉบับแก้ไข…', 'Saving the correction…'))
        self.future = self.pool.submit(self.service.confirm, *self.scope, expected_revision=self.preview["revision"],
            actor=socket.gethostname(), reason=self.reason.text())
        self.timer.start()

    def reject(self):
        if self.operation != "confirm":
            super().reject()

    def closeEvent(self, event):
        if self.operation == "confirm":
            event.ignore()
        else:
            super().closeEvent(event)
