"""Review new shared-history postings without changing already issued accounts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import socket
from PyQt6.QtCore import QDate, QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialogButtonBox, QAbstractItemView, QHeaderView)
from ui.numeric_inputs import NumericDateEdit
from ui.counter_review import plain
from i18n import tr
from widgets import btn
from services.device_config import DeviceConfigRepository
from services.shared_billing import SharedBillingService


REASONS = {
    'day_not_closed': ('ยังไม่สิ้นวัน', 'Day is not closed'),
    'existing_account_or_legacy_source': ('มีบัญชีหรือข้อมูลเดิม ให้ตรวจฉบับแก้ไข', 'Existing account/history: review an amendment'),
    'missing_price': ('ยังไม่มีราคาที่ใช้ได้', 'Dated prices are unavailable'),
    'unverified_web_totals': ('ผลรวม Web ยังไม่ผ่านการตรวจ', 'Web totals are unverified'),
    'usage_totals_not_reconciled': ('ยอดใช้งานไม่ผ่านการตรวจผลรวม', 'Usage totals do not reconcile'),
    'multiple_slot_epochs': ('มีฐานมิเตอร์หลายชุดในวันเดียว', 'Multiple Slot baselines in one day'),
    'non_integer_or_negative_usage': ('ยอดใช้งานต้องตรวจสอบ', 'Usage requires review'),
}


class SharedBillingDialog(QDialog):
    def __init__(self, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or SharedBillingService()
        self.review = self.future = self.operation = None
        self.result_ids = None
        self.setWindowTitle(tr('ตรวจยอดจากประวัติร่วมก่อนลงบัญชี', 'Review shared history before posting'))
        self.resize(850, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(plain(tr('ลงเฉพาะยอดใหม่ที่มีหลักฐานครบ รายการเดิมไม่ถูกเขียนทับ วันที่มีปัญหาจะคงรอตรวจ',
            'Post only new usage with complete evidence. Existing entries stay unchanged; blocked dates remain for review.')))
        row = QHBoxLayout()
        self.slot = QComboBox()
        for device in DeviceConfigRepository().list(enabled_only=True):
            self.slot.addItem(f'{device.name} · {device.serial}', device.slot)
        self.start = NumericDateEdit(QDate.currentDate().addDays(-30))
        self.end = NumericDateEdit(QDate.currentDate().addDays(-1))
        for control in (self.start,self.end):
            control.setCalendarPopup(True)
            control.setDisplayFormat('dd/MM/yyyy')
        self.preview_button = btn(tr('ตรวจยอด', 'Review'), 'outline')
        self.preview_button.clicked.connect(self.prepare)
        for control in (self.slot,self.start,self.end,self.preview_button):
            row.addWidget(control)
        layout.addLayout(row)
        self.table = QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels([tr('วันที่','Date'), tr('จำนวนหน้า','Pages'), tr('สุทธิ','Net'), tr('สถานะ','Status')])
        self.table.horizontalHeader().setStretchLastSection(True)
        for column in range(3):
            self.table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.reason = QLineEdit()
        self.reason.setMaxLength(300)
        self.reason.setPlaceholderText(tr('เหตุผลยืนยันยอด', 'Reason for confirming usage'))
        layout.addWidget(self.reason)
        self.status = plain('')
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText(tr('ยืนยันลงบัญชีรายการที่พร้อม', 'Post ready entries'))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('ยกเลิก','Cancel'))
        self.confirm_button.setEnabled(False)
        self.buttons.accepted.connect(self.confirm)
        self.buttons.rejected.connect(self.reject)
        self.reason.textChanged.connect(self.update_confirm)
        self.slot.currentIndexChanged.connect(self.invalidate)
        self.start.dateChanged.connect(self.invalidate)
        self.end.dateChanged.connect(self.invalidate)
        layout.addWidget(self.buttons)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='komi-shared-billing')
        self.destroyed.connect(lambda _=None,pool=self.pool:pool.shutdown(wait=False,cancel_futures=True))
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.collect)

    def invalidate(self, *_):
        self.review = None
        self.update_confirm()

    def update_confirm(self, *_):
        self.confirm_button.setEnabled(bool(self.review and self.review['ready'] and self.reason.text().strip() and self.future is None))

    def launch(self, operation, function, *args, **kwargs):
        if self.future is not None:
            return
        self.operation = operation
        for control in (self.slot,self.start,self.end,self.preview_button,self.reason):
            control.setEnabled(False)
        self.future = self.pool.submit(function,*args,**kwargs)
        self.update_confirm()
        self.status.setText(tr('กำลังตรวจข้อมูล…','Checking data…'))
        self.timer.start()

    def prepare(self):
        self.review = None
        self.launch('preview', self.service.preview, self.slot.currentData(), self.start.date().toPyDate(), self.end.date().toPyDate())

    def confirm(self):
        if self.confirm_button.isEnabled():
            self.launch('confirm', self.service.confirm, self.review, actor=socket.gethostname(), reason=self.reason.text())

    def collect(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future,self.future = self.future,None
        for control in (self.slot,self.start,self.end,self.preview_button,self.reason):
            control.setEnabled(True)
        try:
            result = future.result()
        except Exception as error:
            self.review = None
            self.status.setText(str(error))
            self.update_confirm()
            return
        if self.operation == 'confirm':
            self.result_ids = result
            self.accept()
            return
        self.review = result
        entries = [(r['day'], r['delta'].get('counter.total.total','—'), f"{r['net_cents']/100:,.2f}", tr('พร้อมลงบัญชี','Ready to post')) for r in result['ready']]
        entries += [(r['day'],'—','—', '; '.join(tr(*REASONS[k]) if k in REASONS else tr('หลักฐานต้องตรวจสอบ','Evidence requires review') for k in r['reasons'])) for r in result['blocked']]
        self.table.setRowCount(len(entries))
        for i,entry in enumerate(sorted(entries)):
            for j,value in enumerate(entry):
                self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.status.setText(tr(f"พร้อม {len(result['ready'])} วัน · รอตรวจ {len(result['blocked'])} วัน", f"Ready: {len(result['ready'])} day(s) · Review: {len(result['blocked'])} day(s)"))
        self.update_confirm()

    def reject(self):
        if self.future is not None:
            return  # In-flight posting must finish before the dialog disappears.
        super().reject()
