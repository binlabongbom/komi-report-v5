"""Event-driven network activity view, using actual runtime and durable receipts."""
from ui.styles import tables as tables_styles
from ui.styles import text as text_styles
from ui.resource_cleanup import close_executor_with
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView

from i18n import tr, apply_language
from database import get_db_path
from services.network_activity import load_network_activity
from widgets import btn


def _date(value):
    if not value:
        return tr("ยังไม่มี", "Not yet")
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError):
        return tr("ตรวจสอบเวลา", "Check timestamp")


class NetworkActivityPanel(QWidget):
    _completed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.polling = None
        self._future = None
        self._again = False
        self._page = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-network-status")
        close_executor_with(self, self._pool)
        self._completed.connect(self._render, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        title = QHBoxLayout()
        heading = QLabel("สถานะการทำงานร่วมกัน")
        heading.setStyleSheet(text_styles.label('#123262', font_weight='700'))
        title.addWidget(heading, 1)
        self.refresh_button = btn("ตรวจสถานะอีกครั้ง", "outline")
        self.refresh_button.clicked.connect(self.refresh)
        title.addWidget(self.refresh_button)
        layout.addLayout(title)
        self.reconnect_button = btn(tr('ค้นหาและเชื่อมต่อสมาชิกเดิมอีกครั้ง', 'Find and reconnect existing members'), 'outline')
        self.reconnect_button.clicked.connect(self._reconnect)
        self.reconnect_button.setEnabled(False)
        layout.addWidget(self.reconnect_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.reinstall_button = btn(tr('เริ่มสมาชิกใหม่โดยเก็บฐานเดิม', 'Start a new member and keep the old database'), 'outline')
        self.reinstall_button.clicked.connect(self._reinstall)
        self.reinstall_button.hide()
        layout.addWidget(self.reinstall_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.summary = QLabel("ยังไม่มีสถานะการเชื่อมต่อสมาชิก")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.local_read = QLabel("การอ่านบนคอมนี้: ยังไม่มีสถานะ")
        self.local_read.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.local_read)
        self.shared_read = QLabel("ผู้อ่านร่วม: ยังไม่ได้เชื่อมต่อบริการสมาชิก")
        self.shared_read.setTextFormat(Qt.TextFormat.PlainText)
        self.shared_read.setWordWrap(True)
        layout.addWidget(self.shared_read)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["คอมพิวเตอร์", "รับ/ส่งข้อมูล", "เสร็จครบล่าสุด", "Web รอยืนยันรับ", "การตั้งค่า", "ฉบับแก้ไขรอรับ"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(tables_styles.NETWORK_ACTIVITY)
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
        self.notice.setStyleSheet(text_styles.label('#64748B'))
        layout.addWidget(self.notice)

    def bind_runtime(self, polling):
        if self.polling is polling:
            return
        if self.polling is not None:
            for signal in self._runtime_signals(self.polling):
                signal.disconnect(self.schedule_refresh)
        self.polling = polling
        for signal in self._runtime_signals(polling):
            signal.connect(self.schedule_refresh)
        self.schedule_refresh()

    @staticmethod
    def _runtime_signals(polling):
        signals = [polling.peer_history.changed, polling.activity_changed, polling.device_updated]
        network = getattr(polling, 'peer_network_runtime', None)
        if network is not None:
            signals.append(network.changed)
        return signals

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_refresh()

    def _change_page(self, step):
        self._page = max(0, self._page + step)
        self.refresh()

    def schedule_refresh(self, *_args):
        if self.isVisible():
            self._timer.start(100)

    def _reconnect(self):
        runtime = getattr(self.polling, 'peer_network_runtime', None)
        if runtime is None or getattr(runtime, '_future', None) is not None:
            return
        self.reconnect_button.setEnabled(False)
        # This explicitly requests discovery/retry; merely displaying status
        # does not probe peers or periodically transfer settings.
        self.polling.network_recovered()
        self.schedule_refresh()

    def _reinstall(self):
        from ui.peer_reinstallation import PeerReinstallationDialog
        dialog = PeerReinstallationDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

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
                self.summary.setText(tr("อ่านสถานะไม่สำเร็จ ข้อมูลเดิมยังแสดงอยู่ · กดตรวจสถานะอีกครั้ง", "Unable to load status. Previous data is still displayed. Check status again."))
            else:
                computers = data.get('computers', {})
                active = self.polling.active_slots() if self.polling is not None else ()
                self.local_read.setText(tr("การอ่านบนคอมนี้: {slots}", "Reading on this computer: {slots}").format(slots=", ".join(f"Slot {slot + 1}" for slot in active) if active else tr("ไม่มีงานอ่านอยู่", "No active reads")))
                shared = getattr(self.polling, "shared_reads", None)
                if shared is None:
                    self.shared_read.setText(tr('ผู้อ่านร่วม: ยังไม่ได้เชื่อมต่อบริการสมาชิก', 'Shared reader: membership service is not connected'))
                else:
                    jobs = shared.snapshot()
                    phases = {"reading": tr("กำลังอ่าน", "Reading"), "complete": tr("บันทึกผลแล้ว", "Saved"),
                              "failed": tr("อ่านไม่สำเร็จ", "Read failed"), "expired": tr("งานหมดเวลา", "Expired"),
                              "probe_complete": tr("จบ SNMP · ไม่มีผล Web ใหม่", "SNMP finished; no new Web reading")}
                    self.shared_read.setText(tr("ผู้อ่านร่วม · สถานะที่รับล่าสุด ไม่ใช่การตรวจออนไลน์:\n", "Shared reader: last received status, not an online check:\n") + (
                        "\n".join(tr("Slot {slot} · ผู้ประสาน {authority} · ผู้อ่าน {reader} · {phase} · {at}",
                                      "Slot {slot} · Coordinator {authority} · Reader {reader} · {phase} · {at}").format(
                            slot=job['slot']+1, authority=computers.get(job['authority'], job['authority']),
                            reader=computers.get(job['reader'], job['reader']),
                            phase=phases.get(job['phase'], tr("รอตรวจ", "Needs review")), at=_date(job['observed_at'])) for job in jobs)
                        or tr("ยังไม่มีคำขออ่านร่วม", "No shared read requests")))
                    self.shared_read.setProperty("i18n_data", True)  # Names inside the rendered status are data.
                    if any(job.get('coordination_partial') for job in jobs):
                        self.shared_read.setText(self.shared_read.text() + tr(
                            "\nติดต่อสมาชิกไม่ครบในเวลาที่กำหนด · อาจมีการอ่านซ้อนในเครือข่ายที่ขาดกัน",
                            "\nSome members could not be checked in time. Disconnected network segments may read independently."))
                message = (tr("สมาชิกในรายการ {total} คอม", "{total} listed computers").format(total=total) if total else
                           tr("ยังไม่มีสมาชิกที่ยืนยันการเชื่อมต่อ · ไม่ได้หมายความว่าไม่มีคอมอื่นในเครือข่าย", "No verified member connections yet. This does not mean there are no other computers on the network."))
                runtime = getattr(self.polling, 'peer_network_runtime', None)
                busy = runtime is not None and getattr(runtime, '_future', None) is not None
                enrolled = runtime is not None and runtime.state != 'not_enrolled'
                self.reinstall_button.setVisible(runtime is not None and runtime.state == 'unavailable'
                    and runtime.error in {'identity_missing','identity_changed','installation_mismatch','member_removed','group_secret_missing'})
                self.reconnect_button.setEnabled(enrolled and not busy)
                if busy:
                    message += tr('\nกำลังตรวจการเชื่อมต่อสมาชิกเดิม…', '\nChecking existing member connections…')
                if runtime is not None and runtime.state == 'unavailable':
                    reasons = {
                        'identity_missing': tr('ไม่พบกุญแจสมาชิกเดิมหรือกุญแจเสียหาย · ต้องกู้กุญแจเดิมหรือเชื่อมสมาชิกใหม่โดยยืนยันสิทธิ์ก่อน', 'The original member key is missing or damaged. Restore it or complete an approved enrollment recovery.'),
                        'enrollment_pending': tr('เข้ากลุ่มยังไม่ครบ · ตรวจว่าต้นทางออนไลน์ แล้วกดค้นหาและเชื่อมต่ออีกครั้ง', 'Enrollment is incomplete. Check that the source is online, then find and reconnect again.'),
                        'identity_changed': tr('กุญแจไม่ตรงกับสมาชิกเดิม · หยุดการเชื่อมต่อไว้เพื่อรอยืนยันการกู้สมาชิก', 'The key does not match the original member. Connections are stopped pending approved recovery.'),
                        'installation_mismatch': tr('ฐานข้อมูลนี้เป็นของการติดตั้งอื่น · ต้องยืนยันการกู้สมาชิกก่อนเชื่อมต่อ', 'This database belongs to another installation. Approved recovery is required before connecting.'),
                        'group_secret_missing': tr('ไม่พบกุญแจกลุ่มเดิมในระบบหรือกุญแจเสียหาย · การคืนเฉพาะฐานข้อมูลยังเชื่อมสมาชิกไม่ได้', 'The original group key is missing or damaged in the OS vault. Restoring only the database does not restore member access.'),
                        'vault_unavailable': tr('เปิดที่เก็บกุญแจของระบบไม่ได้ · ตรวจบัญชีผู้ใช้ระบบแล้วลองเชื่อมต่ออีกครั้ง', 'The OS key vault is unavailable. Check the OS user account and retry the connection.'),
                        'member_removed': tr('เครื่องนี้ถูกถอดจากสมาชิกแล้ว · ต้องยืนยันสิทธิ์ก่อนเข้าร่วมอีกครั้ง', 'This computer has been removed. Approval is required before it can rejoin.'),
                    }
                    message += '\n' + reasons.get(runtime.error, tr('เริ่มบริการสมาชิกไม่สำเร็จ · ตรวจสิทธิ์ การตั้งค่าเครือข่าย หรือพอร์ตที่ใช้งาน', 'Unable to start member connections. Check enrollment, network settings or the listener port.'))
                if total > 100:
                    message += tr(" · หน้าที่ {page}", " · Page {page}").format(page=self._page + 1)
                message += tr("\nการตั้งค่ารอตรวจ {count} รายการ", "\nSettings awaiting review: {count}").format(count=data['settings_reviews'])
                if data["slot_reviews"]:
                    message += tr(" · ฐานมิเตอร์รอตรวจ: ", " · Baselines awaiting review: ") + ", ".join(f"Slot {slot}" for slot in data["slot_reviews"])
                self.summary.setText(message)
                self.table.setRowCount(len(rows))
                self.table.setFixedHeight(min(265, self.table.horizontalHeader().sizeHint().height()
                    + 42 * len(rows) + 2 * self.table.frameWidth() + 4))
                self.table.setVisible(bool(rows))
                states = {"waiting": tr("รอเริ่ม", "Waiting"), "receiving": tr("กำลังรับ", "Receiving"),
                          "complete": tr("รับครบตามรอบ", "Round complete"), "pending": tr("รอเชื่อมต่อ/ตรวจสอบ", "Awaiting connection/review"), "cancelled": tr("หยุดแล้ว", "Stopped")}
                errors = {"unauthorized": tr("สิทธิ์สมาชิกเปลี่ยน", "Membership changed"), "timeout": tr("เชื่อมต่อหมดเวลา", "Connection timed out"),
                          "invalid_data": tr("ข้อมูลต้องตรวจสอบ", "Data needs review"), "transport": tr("รับข้อมูลไม่สำเร็จ", "Unable to receive data")}
                for index, row in enumerate(rows):
                    member = row["member"]
                    queue = data["queues"][member]
                    values = [computers.get(member, member), states.get(row["status"], tr("รอตรวจสอบ", "Needs review")), _date(row["last_success"]),
                              str(queue["web_pending"]), tr("รอยืนยันรับ", "Awaiting receipt") if queue["settings_pending"] else tr("ไม่มีค่ารอส่ง", "No pending settings"),
                              str(queue['amendments_pending'])]
                    for column, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setToolTip(f'{value}\n{member}' if column == 0 else errors.get(row["error"], "") if column == 1 else value)
                        self.table.setItem(index, column, item)
        apply_language(self)
        if self._again:
            self._again = False
            self.schedule_refresh()
