from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtTest import QTest

import database
from services.device_config import DeviceConfigRepository
from services.peer_settings_history import SettingsHistory
from services.peer_settings_transfer import PeerSettingsTransfer
from services.peer_settings_runtime import PeerSettingsRuntime
from services.shared_settings import SharedSettingsService
from services.runtime_snapshots import runtime_snapshots
from test_peer_setup_application import received, application, allowed, epoch_allowed
from test_peer_history_session import peers
from test_peer_history_runtime import until
from test_shared_settings_history_ui import select_revision
from test_subject_history import _reading


class Polling(QObject):
    activity_changed = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.repository = DeviceConfigRepository()
        self.states, self.last_poll = {}, {}
        self.active = ()
        self.reloaded = 0
        self._stopped = False
        self.is_paused = True  # Applying settings must not resume a license pause.
    def active_slots(self):
        return self.active
    def reload_policy(self):
        self.reloaded += 1


def transfer(paths):
    receiver = PeerSettingsTransfer(authorize=allowed, path=paths['B'])
    return receiver.receive('A', SettingsHistory(paths['A']).export_page())


def change_source(paths, value=5):
    database.set_db_path(paths['A'])
    service = SharedSettingsService()
    head = service.commit(service.preview({'waste_paper_pct': value}, reason='fixture'))
    database.set_db_path(paths['B'])
    transfer(paths)
    return head


def runtime():
    app = QApplication.instance() or QApplication([])
    polling = Polling()
    result = PeerSettingsRuntime(polling, authorize=allowed, authorize_epoch=epoch_allowed)
    polling.peer_settings = result
    return app, polling, result


def test_verified_descendant_waits_for_idle_and_refreshes_without_resuming_registration(peers):
    paths, _ = peers
    head, _ = received(peers)
    application().commit(application().preview('A', head, reason='initial'))
    _, polling, instance = runtime()
    polling.active = (0,)
    applied = []
    instance.applied.connect(lambda: applied.append(True))
    try:
        changed = change_source(paths)
        instance.process()
        assert database.get_cfg('waste_paper_pct') != '5.0'
        assert instance.inbox.pending()[0]['head'] == changed
        polling.active = ()
        polling.activity_changed.emit()
        until(lambda: applied)
        assert database.get_cfg('waste_paper_pct') == '5.0'
        assert polling.reloaded == 1 and polling.is_paused
        assert instance.inbox.pending() == []
        QTest.qWait(30)
        assert len(applied) == 1
    finally:
        instance.stop()


def test_initial_receive_requires_review_and_conflict_never_overwrites(peers):
    paths, _ = peers
    head, _ = received(peers)
    transfer(paths)
    _, polling, instance = runtime()
    reviews = []
    instance.review_needed.connect(reviews.append)
    try:
        instance.process()
        assert reviews[0]['status'] == 'initial_review'
        with database._open(commit=False) as conn:
            assert SettingsHistory._state(conn, 'head') is None
        instance.apply_review(instance.inbox.prepare('A', head))
        local = SharedSettingsService()
        local.commit(local.preview({'waste_paper_pct': 7}, reason='local choice'))
        changed = change_source(paths, 5)
        instance.process()
        assert reviews[-1]['status'] == 'conflict' and reviews[-1]['head'] == changed
        assert database.get_cfg('waste_paper_pct') == '7.0'
    finally:
        instance.stop()


def test_revoked_member_cannot_auto_apply_and_restart_recovers_pending_settings(peers):
    paths, _ = peers
    head, _ = received(peers)
    application().commit(application().preview('A', head, reason='initial'))
    changed = change_source(paths)
    _, polling, instance = runtime()
    try:
        instance.inbox.application.authorize = lambda *a: False
        instance.process()
        assert database.get_cfg('waste_paper_pct') != '5.0'
        assert instance.inbox.pending()[0]['head'] == changed
    finally:
        instance.stop()
    instance = PeerSettingsRuntime(polling, authorize=allowed, authorize_epoch=epoch_allowed)
    try:
        instance.process()
        assert database.get_cfg('waste_paper_pct') == '5.0'
    finally:
        instance.stop()


def test_history_dialog_applies_reviewed_full_slot_configuration(peers, monkeypatch):
    from ui import shared_settings_history as ui
    paths, _ = peers
    head, _ = received(peers)
    transfer(paths)
    _, polling, instance = runtime()
    parent = QWidget()
    parent.polling = polling
    dialog = ui.SharedSettingsHistoryDialog(parent)
    try:
        select_revision(dialog, head)
        monkeypatch.setattr(ui, 'confirm_shared_settings', lambda *_: False)
        dialog._choose_peer(True)
        assert instance.inbox.pending()
        monkeypatch.setattr(ui, 'confirm_shared_settings', lambda *_: True)
        dialog._choose_peer(True)
        assert not instance.inbox.pending()
        assert 'Slot' in dialog.status.text()
        assert DeviceConfigRepository().get(0).serial == 'USED'
    finally:
        dialog.close()
        parent.close()
        instance.stop()
