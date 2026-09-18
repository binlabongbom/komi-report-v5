"""Read-only history browsing and explicitly reviewed, append-only undo."""
import sqlite3
from datetime import datetime
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QVBoxLayout,
)

from i18n import tr
from services.shared_settings import SharedSettingsService
from ui.shared_settings_confirmation import _display, confirm_shared_settings, setting_labels


def _reason(value):
    known = {
        "setup_settings_saved": tr("บันทึกเครื่องพิมพ์และการตั้งค่า", "Printer and setup settings saved"),
        "slot_baseline_reviewed": tr("ยืนยันฐานมิเตอร์ของ Slot", "Slot meter baseline reviewed"),
        "billing_settings_saved": tr("เปลี่ยนรอบบิลหรือส่วนลด", "Billing or discount changed"),
        "schedule_settings_saved": tr("เปลี่ยนตารางอ่านข้อมูล", "Reading schedule changed"),
        "local_settings_baseline": tr("ค่าก่อนเริ่มบันทึกประวัติ", "Settings before audit history"),
        "local_settings_observed": tr("บันทึกค่าที่มีอยู่", "Existing settings recorded"),
        "reviewed_peer_choice": tr("ยืนยันเลือกค่าร่วมกัน", "Shared settings choice confirmed"),
    }
    if value.startswith("undo:"):
        return tr("ย้อนค่าจากประวัติ", "Settings restored from history")
    return known.get(value, value)


def _date(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return value


class SharedSettingsHistoryDialog(QDialog):
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = SharedSettingsService()
        self.setWindowTitle(tr("ประวัติการตั้งค่าร่วม", "Shared settings history"))
        self.resize(940, 640)
        layout = QVBoxLayout(self)
        notice = QLabel(tr(
            "เลือกการเปลี่ยนแปลงเพื่อดูรายละเอียด การย้อนค่าจะสร้างประวัติใหม่\n"
            "ย้อนจากหน้านี้ได้ทั้งวันตัดรอบบิล ส่วนลด ตาราง/เวลาทำงาน รูปแบบราคา และราคาตามวันบังคับใช้",
            "Select a change to inspect it. Undo creates a new history entry.\n"
            "This screen supports undo for billing day, discount, schedules, working hours, pricing mode and dated prices.",
        ))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.records = QListWidget()
        self.records.currentItemChanged.connect(self._selected)
        layout.addWidget(self.records, 1)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.more = QPushButton(tr("โหลดประวัติเพิ่ม", "Load more history"))
        self.more.clicked.connect(self._load_more)
        actions.addWidget(self.more)
        actions.addStretch()
        self.undo = QPushButton(tr("ตรวจและย้อนค่า", "Review undo"))
        self.undo.setEnabled(False)
        self.undo.clicked.connect(self._undo)
        actions.addWidget(self.undo)
        self.accept_peer = QPushButton(tr("ใช้ค่าจากรายการนี้", "Use these incoming values"))
        self.keep_local = QPushButton(tr("คงค่าปัจจุบัน", "Keep current values"))
        self.accept_peer.setEnabled(False)
        self.keep_local.setEnabled(False)
        self.accept_peer.clicked.connect(lambda: self._choose_peer(True))
        self.keep_local.clicked.connect(lambda: self._choose_peer(False))
        actions.addWidget(self.keep_local)
        actions.addWidget(self.accept_peer)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("ปิด", "Close"))
        layout.addWidget(buttons)
        self.cursor = None
        self._load_more()

    def _load_more(self):
        try:
            rows = self.service.history_page(before_rowid=self.cursor)
            for row in rows:
                doc = row["document"]
                prefix = tr("ปัจจุบัน · ", "Current · ") if row["current"] else ""
                if row["incoming"]:
                    prefix = tr("รอตรวจจากเครื่องอื่น · ", "Incoming review · ")
                item = QListWidgetItem(prefix + _date(doc["created_at"]) + " · " + _reason(doc["reason"]))
                item.setToolTip(row["revision"])
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.records.addItem(item)
            if rows:
                self.cursor = rows[-1]["rowid"]
            self.more.setEnabled(len(rows) == 50)
            if not self.records.count():
                self.status.setText(tr("ยังไม่มีประวัติการเปลี่ยนแปลง", "No settings changes recorded yet"))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))

    def _selected(self, item, _previous=None):
        self.undo.setEnabled(False)
        self.accept_peer.setEnabled(False)
        self.keep_local.setEnabled(False)
        if item is None:
            self.details.clear()
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        doc = row["document"]
        lines = [tr("รหัสคอมพิวเตอร์: ", "Computer ID: ") + doc["actor"],
                 tr("รายการ: ", "Revision: ") + row["revision"]]
        payload = doc["payload"]
        previous = row["previous"]
        labels = setting_labels()
        for key in ("organization", "devices", "price_history", "slot_epochs"):
            if key in payload:
                old = previous.get(key) if previous else None
                if old != payload[key]:
                    lines.append(labels[key] + "\n" + tr("เดิม: ", "Previous: ") + _display(key, old)
                                 + "\n" + tr("ใหม่: ", "New: ") + _display(key, payload[key]))
        for key, value in payload["settings"].items():
            old = previous["settings"].get(key) if previous else None
            if old != value:
                lines.append(labels[key] + "\n" + tr("เดิม: ", "Previous: ") + _display(key, old)
                             + "\n" + tr("ใหม่: ", "New: ") + _display(key, value))
        self.details.setPlainText("\n\n".join(lines))
        self.undo.setEnabled(bool(row["undo_fields"]) and not row["incoming"])
        self.accept_peer.setEnabled(row["incoming"])
        self.keep_local.setEnabled(row["incoming"])

    def _choose_peer(self, incoming):
        item = self.records.currentItem()
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        try:
            # A fresh head is read here; the following preview/commit still
            # rejects concurrent writes while the confirmation is open.
            from database import _open
            from services.peer_settings_history import SettingsHistory
            with _open(commit=False) as conn:
                local = SettingsHistory._state(conn, "head")
                member = SettingsHistory._state(conn, 'sender:' + row['revision'])
            polling = getattr(self.window(), 'polling', None)
            owner = self.parent()
            while polling is None and owner is not None:
                polling = getattr(owner, 'polling', None)
                owner = owner.parent()
            runtime = getattr(polling, 'peer_settings', None)
            if incoming and member and runtime is not None:
                if polling.active_slots():
                    self.status.setText(tr('รอการอ่านที่กำลังทำอยู่เสร็จก่อนเปลี่ยนชุดตั้งค่า',
                                           'Wait for the active reading before changing configuration'))
                    return
                preview = runtime.inbox.prepare(member, row['revision'], resolve_conflict=True)
                if not confirm_shared_settings(self, preview):
                    return
                # The modal review may have allowed a scheduled read to start.
                if polling.active_slots():
                    self.status.setText(tr('มีงานอ่านเริ่มระหว่างตรวจ กรุณายืนยันอีกครั้งเมื่ออ่านเสร็จ',
                                           'A reading started during review; confirm after it finishes'))
                    return
                runtime.apply_review(preview)
                self.settings_changed.emit()
                self.records.clear()
                self.cursor = None
                self._load_more()
                self.status.setText(tr('ใช้ชุดการตั้งค่าและ Slot ที่ตรวจแล้ว', 'Reviewed configuration and slots applied'))
                return
            preview = self.service.preview_choice(row["revision"],
                chosen_head=row["revision"] if incoming else local, reason="reviewed_peer_choice")
            if not confirm_shared_settings(self, preview):
                return
            self.service.commit(preview)
            self.settings_changed.emit()
            self.records.clear()
            self.cursor = None
            self._load_more()
            self.status.setText(tr("บันทึกการเลือกแล้ว", "Choice recorded"))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))

    def _undo(self):
        item = self.records.currentItem()
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        try:
            preview = self.service.preview_undo(row["revision"], keys=row["undo_fields"],
                                                reason="reviewed_history_undo")
            if not preview.changes or not confirm_shared_settings(self, preview):
                return
            self.service.commit(preview)
            self.settings_changed.emit()
            self.records.clear()
            self.cursor = None
            self._load_more()
            self.status.setText(tr("ย้อนค่าแล้วและบันทึกเป็นรายการใหม่", "Restored settings as a new history entry"))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))


def show_shared_settings_history(parent):
    dialog = SharedSettingsHistoryDialog(parent)
    refresh = getattr(parent, "refresh_from_config", None)
    if callable(refresh):
        dialog.settings_changed.connect(refresh)
    changed = getattr(parent, "changed", None)
    if changed is not None:
        dialog.settings_changed.connect(changed.emit)
    dialog.exec()
