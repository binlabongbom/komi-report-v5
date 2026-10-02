"""Qt-owner-thread application of already authenticated incoming settings."""
from PyQt6.QtCore import QObject, Qt, pyqtSignal

from database import get_db_path
from services.peer_change_events import subscribe
from services.peer_settings_inbox import PeerSettingsInbox


class PeerSettingsRuntime(QObject):
    applied = pyqtSignal()
    review_needed = pyqtSignal(object)
    failed = pyqtSignal(str)
    _wake = pyqtSignal()

    def __init__(self, polling, *, authorize, authorize_epoch):
        super().__init__(polling)
        self.polling = polling
        self.inbox = PeerSettingsInbox(authorize=authorize, authorize_epoch=authorize_epoch)
        self.path = get_db_path()
        self._known_devices = self._devices()
        self._busy = self._stopped = False
        self._notified = set()
        self._wake.connect(self.process, Qt.ConnectionType.QueuedConnection)
        self._unsubscribe = subscribe(self.path, self.notify)
        polling.activity_changed.connect(self.process, Qt.ConnectionType.QueuedConnection)

    def notify(self):
        self._wake.emit()

    def _devices(self):
        from database import _open
        with _open(commit=False) as conn:
            epochs = dict(conn.execute('SELECT device_slot,epoch_id FROM slot_meter_heads'))
        return {d.slot: (d.host, d.serial, d.enabled, epochs.get(d.slot)) for d in self.polling.repository.list()}

    def _refresh(self, before):
        from services.runtime_snapshots import runtime_snapshots
        after = self._devices()
        self._known_devices = after
        for slot in before.keys() | after.keys():
            if before.get(slot) != after.get(slot):
                self.polling.states.pop(slot, None)
                self.polling.last_poll.pop(slot, None)
                runtime_snapshots.clear(slot)
        self.polling.reload_policy()
        self.applied.emit()

    def apply_review(self, preview):
        if (self._stopped or self._busy or self.path != get_db_path()
                or self.polling.active_slots() or getattr(self.polling, '_stopped', False)):
            raise ValueError('Wait for meter collection to finish before applying this review')
        before = self._devices()
        result = self.inbox.application.commit(preview)
        self._refresh(before)
        return result

    def process(self):
        if (self._busy or self._stopped or self.path != get_db_path()
                or self.polling.active_slots() or getattr(self.polling, '_stopped', False)):
            return
        self._busy = True
        try:
            changed = False
            before = self._known_devices
            for row in self.inbox.pending():
                try:
                    result = self.inbox.apply_descendant(row['member'], row['head'])
                    changed |= result['applied']
                    if not result['applied'] and row['head'] not in self._notified:
                        # A review object still requires current authorization.
                        self.inbox.prepare(row['member'], row['head'], resolve_conflict=True)
                        self._notified.add(row['head'])
                        self.review_needed.emit(row)
                except (ValueError, PermissionError):
                    if row['head'] not in self._notified:
                        self._notified.add(row['head'])
                        self.failed.emit('การตั้งค่าที่รับมาต้องตรวจสิทธิ์ ฐาน Slot หรือข้อขัดแย้งก่อนใช้')
            if changed or before != self._devices():
                self._refresh(before)
        except Exception:
            self.failed.emit('ยังใช้การตั้งค่าที่รับมาไม่สำเร็จ รายการยังอยู่ในประวัติรอตรวจ')
        finally:
            self._busy = False

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._unsubscribe()
        self.polling.activity_changed.disconnect(self.process)
