from copy import deepcopy
import sqlite3
import pytest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

import database
from services.network_activity import load_network_activity
from services.peer_settings_history import SettingsHistory, _revision
from services.peer_settings_outbox import PeerSettingsOutbox
from services.web_observations import WebObservationStore
from ui.network_activity import NetworkActivityPanel
from test_shared_settings import configured
from test_web_observations import store, record
from test_peer_history_runtime import until


def test_status_uses_per_member_durable_receipts_without_changing_them():
    service = configured()
    old = service.commit(service.preview({"billing_day": 15}, reason="fixture"))
    newest = service.commit(service.preview({"billing_day": 20}, reason="fixture"))
    PeerSettingsOutbox().acknowledge("A", old)
    observation = record(store(), 1)
    WebObservationStore().acknowledge("A", [observation["id"]])
    before = load_network_activity(database.get_db_path(), ["A", "B"])
    assert before["queues"] == {"A": {"web_pending": 0, "settings_pending": True, "amendments_pending": 0},
                                "B": {"web_pending": 1, "settings_pending": True, "amendments_pending": 0}}
    assert load_network_activity(database.get_db_path(), ["A", "B"]) == before
    PeerSettingsOutbox().acknowledge("A", newest)
    assert load_network_activity(database.get_db_path(), ["A"])["queues"]["A"]["settings_pending"] is False


def test_only_unresolved_incoming_history_counts_as_review():
    service = configured()
    local = service.commit(service.preview({"billing_day": 15}, reason="fixture"))
    packet = SettingsHistory().export()
    doc = deepcopy(packet["revisions"][local])
    doc["parents"] = [local]
    doc["payload"]["settings"]["billing_day"] = 20
    incoming = _revision(doc)
    packet["head"] = incoming
    packet["revisions"][incoming] = doc
    SettingsHistory().receive(packet)
    assert load_network_activity(database.get_db_path(), [])["settings_reviews"] == 1
    preview = service.preview_choice(incoming, chosen_head=incoming, reason="fixture choice")
    service.commit(preview)
    assert load_network_activity(database.get_db_path(), [])["settings_reviews"] == 0


def test_missing_database_does_not_create_an_empty_file(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        load_network_activity(path, [])
    assert not path.exists()


class Runtime(QObject):
    changed = pyqtSignal()
    activity_changed = pyqtSignal()
    device_updated = pyqtSignal(int)

    def __init__(self, rows):
        super().__init__()
        self.rows = rows
        self.peer_history = self

    def snapshot(self):
        return deepcopy(self.rows)

    def active_slots(self):
        return (0,)


def row(member="A", status="pending"):
    return {"member": member, "status": status, "error": "timeout", "after": 0, "through": 0,
            "last_success": ""}


def test_panel_uses_actual_state_keeps_failed_transfer_and_empty_state_honest():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime([row("<b>A</b>")])
    panel = NetworkActivityPanel()
    panel.bind_runtime(runtime)
    panel.show()
    try:
        until(lambda: panel.table.rowCount() == 1)
        assert panel.table.item(0, 0).text() == "<b>A</b>"
        assert "รอเชื่อมต่อ" in panel.table.item(0, 1).text()
        assert panel.table.item(0, 2).text() == "ยังไม่มี"
        assert "Slot 1" in panel.local_read.text()
        assert "ยังไม่ได้เชื่อมต่อ" in panel.shared_read.text()
        class Shared:
            def snapshot(self):
                return [{"slot": 0, "authority": "A", "reader": "B", "phase": "complete", "observed_at": "2026-09-18T10:10:00+07:00"}]
        runtime.shared_reads = Shared()
        runtime.rows = []
        runtime.changed.emit()
        until(lambda: panel.table.rowCount() == 0)
        assert "ไม่ได้หมายความว่าไม่มีคอมอื่น" in panel.summary.text()
        assert "ผู้ประสาน A · ผู้อ่าน B · บันทึกผลแล้ว" in panel.shared_read.text()
    finally:
        panel.close()
        panel._pool.shutdown(wait=True)


def test_status_error_preserves_last_data_and_no_hidden_periodic_queries(monkeypatch):
    import ui.network_activity as module
    app = QApplication.instance() or QApplication([])
    runtime = Runtime([row()])
    panel = NetworkActivityPanel()
    panel.bind_runtime(runtime)
    panel.show()
    try:
        until(lambda: panel.table.rowCount() == 1)
        def unavailable(*args):
            raise OSError("fixture DB unavailable")
        monkeypatch.setattr(module, "load_network_activity", unavailable)
        panel.refresh()
        until(lambda: "อ่านสถานะไม่สำเร็จ" in panel.summary.text())
        assert panel.table.rowCount() == 1
        assert panel.table.item(0, 2).text() == "ยังไม่มี"
        panel.hide()
        runtime.changed.emit()
        QTest.qWait(150)
        assert panel._future is None
        assert not panel._timer.isActive()
    finally:
        panel.close()
        panel._pool.shutdown(wait=True)


def test_display_pagination_does_not_limit_members():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime([row(f"PC-{index:03}") for index in range(105)])
    panel = NetworkActivityPanel()
    panel.bind_runtime(runtime)
    panel.show()
    try:
        until(lambda: panel.table.rowCount() == 100)
        assert panel.next_button.isEnabled()
        panel.next_button.click()
        until(lambda: panel.table.rowCount() == 5)
        assert panel.table.item(0, 0).text() == "PC-100"
        assert not panel.next_button.isEnabled()
        assert "105" in panel.summary.text()
        panel.previous_button.click()
        until(lambda: panel.table.rowCount() == 100)
    finally:
        panel.close()
        panel._pool.shutdown(wait=True)
