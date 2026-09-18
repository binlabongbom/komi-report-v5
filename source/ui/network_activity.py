"""Event-driven network activity view, using actual runtime and durable receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView

from database import get_db_path
from services.network_activity import load_network_activity
from widgets import btn


def _date(value):
    if not value:
        return "ยังไม่มี"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError):
        return "ตรวจสอบเวลา"


class NetworkActivityPanel(QWidget):
    _completed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.polling = None
        self._future = None
        self._again = False
        self._page = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-network-status")
        self.destroyed.connect(lambda _=None, pool=self._pool: pool.shutdown(wait=False, cancel_futures=True))
        self._completed.connect(self._render, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        title = QHBoxLayout()
        heading = QLabel("สถานะการทำงานร่วมกัน")
        heading.setStyleSheet("font-weight:700;color:#123262;")
        title.addWidget(heading, 1)
        self.refresh_button = btn("ตรวจสถานะอีกครั้ง", "outline")
        self.refresh_button.clicked.connect(self.refresh)
        title.addWidget(self.refresh_button)
        layout.addLayout(title)
        self.summary = QLabel("ยังไม่มีสถานะการเชื่อมต่อสมาชิก")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.local_read = QLabel("การอ่านบนคอมนี้: ยังไม่มีสถานะ")
        self.local_read.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.local_read)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["คอมพิวเตอร์", "รับประวัติ", "รับครบล่าสุด", "Web รอยืนยันรับ", "การตั้งค่า"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget{background:white;alternate-background-color:#F8FAFC;"
            "border:1px solid #D7E0E8;border-radius:6px;color:#24364B;}"
            "QHeaderView::section{background:#EDF2F7;color:#42526B;font-weight:600;"
            "border:none;border-bottom:1px solid #D7E0E8;padding:10px 8px;}"
            "QTableWidget::item{padding:8px;border-bottom:1px solid #EDF2F7;}"
            "QTableWidget::item:selected{background:#E0EDFA;color:#123262;}")
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(125)
        self.table.setMaximumHeight(265)
        self.table.hide()
        layout.addWidget(self.table)
        pager = QHBoxLayout()
        self.previous_button = btn("ก่อนหน้า", "outline")
        self.next_button = btn("ถัดไป", "outline")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        self.next_button.clicked.connect(lambda: self._change_page(1))
        self.previous_button.hide()
        self.next_button.hide()
        pager.addStretch(1)
        pager.addWidget(self.previous_button)
        pager.addWidget(self.next_button)
        layout.addLayout(pager)
        self.notice = QLabel("รอยืนยันรับ = ยังไม่มีหลักฐานว่าคอมปลายทางบันทึกแล้ว · สถานะรับประวัติไม่ใช่สถานะการตั้งค่าหรือผู้อ่านร่วม")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("color:#64748B;")
        layout.addWidget(self.notice)

    def bind_runtime(self, polling):
        if self.polling is polling:
            return
        if self.polling is not None:
            for signal in (self.polling.peer_history.changed, self.polling.activity_changed, self.polling.device_updated):
                signal.disconnect(self.schedule_refresh)
        self.polling = polling
        for signal in (polling.peer_history.changed, polling.activity_changed, polling.device_updated):
            signal.connect(self.schedule_refresh)
        self.schedule_refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_refresh()

    def _change_page(self, step):
        self._page = max(0, self._page + step)
        self.refresh()

    def schedule_refresh(self, *_args):
        if self.isVisible():
            self._timer.start(100)

    def refresh(self):
        if not self.isVisible():
            return
        if self._future is not None:
            self._again = True
            return
        rows = self.polling.peer_history.snapshot() if self.polling is not None else []
        # Pagination is a display bound, never a limit on licensed computers.
        total = len(rows)
        self._page = min(self._page, max(0, (total - 1) // 100))
        start = self._page * 100
        rows = rows[start:start + 100]
        for button in (self.previous_button, self.next_button):
            button.setVisible(total > 100)
        self.previous_button.setEnabled(self._page > 0)
        self.next_button.setEnabled(start + 100 < total)
        path = str(get_db_path())
        self._request = (path, rows, total)
        self._future = self._pool.submit(load_network_activity, path, [row["member"] for row in rows])
        self._future.add_done_callback(self._notify)

    def _notify(self, future):
        try:
            self._completed.emit(future)
        except RuntimeError:
            pass

    def _render(self, future):
        if future is not self._future:
            return
        self._future = None
        path, rows, total = self._request
        if path != str(get_db_path()):
            self._again = True
        else:
            try:
                data = future.result()
            except Exception:
                self.summary.setText("อ่านสถานะไม่สำเร็จ ข้อมูลเดิมยังแสดงอยู่ · กดตรวจสถานะอีกครั้ง")
            else:
                active = self.polling.active_slots() if self.polling is not None else ()
                self.local_read.setText("การอ่านบนคอมนี้: " + (", ".join(f"Slot {slot + 1}" for slot in active) if active else "ไม่มีงานอ่านอยู่"))
                message = (f"สมาชิกในรายการ {total} คอม" if total else
                           "ยังไม่มีการเชื่อมต่อสมาชิกที่ยืนยันแล้ว · ไม่ได้หมายความว่าไม่มีคอมอื่นในเครือข่าย")
                if total > 100:
                    message += f" · หน้าที่ {self._page + 1}"
                message += f"\nการตั้งค่ารอตรวจ {data['settings_reviews']} รายการ"
                if data["slot_reviews"]:
                    message += " · ฐานมิเตอร์รอตรวจ: " + ", ".join(f"Slot {slot}" for slot in data["slot_reviews"])
                self.summary.setText(message)
                self.table.setRowCount(len(rows))
                self.table.setFixedHeight(min(265, self.table.horizontalHeader().sizeHint().height()
                    + 42 * len(rows) + 2 * self.table.frameWidth() + 4))
                self.table.setVisible(bool(rows))
                states = {"waiting": "รอเริ่ม", "receiving": "กำลังรับ", "complete": "รับครบตามรอบ", "pending": "รอเชื่อมต่อ/ตรวจสอบ", "cancelled": "หยุดแล้ว"}
                errors = {"unauthorized": "สิทธิ์สมาชิกเปลี่ยน", "timeout": "เชื่อมต่อหมดเวลา", "invalid_data": "ข้อมูลต้องตรวจสอบ", "transport": "รับข้อมูลไม่สำเร็จ"}
                for index, row in enumerate(rows):
                    member = row["member"]
                    queue = data["queues"][member]
                    values = [member, states.get(row["status"], "รอตรวจสอบ"), _date(row["last_success"]),
                              str(queue["web_pending"]), "รอยืนยันรับ" if queue["settings_pending"] else "ไม่มีค่ารอส่ง"]
                    for column, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setToolTip(errors.get(row["error"], "") if column == 1 else value)
                        self.table.setItem(index, column, item)
        if self._again:
            self._again = False
            self.schedule_refresh()
