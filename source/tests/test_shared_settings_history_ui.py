from PyQt6.QtCore import Qt
from copy import deepcopy
import pytest

import database
from services.peer_settings_history import SettingsHistory
from test_shared_settings import configured, state
from ui import shared_settings_history as ui


def select_revision(dialog, revision):
    for index in range(dialog.records.count()):
        item = dialog.records.item(index)
        if item.data(Qt.ItemDataRole.UserRole)["revision"] == revision:
            dialog.records.setCurrentItem(item)
            return
    raise AssertionError("Revision not displayed")


def test_history_browse_and_cancel_undo_never_write(monkeypatch):
    service = configured()
    revision = service.commit(service.preview({"billing_day": 15}, reason="billing_settings_saved"))
    before = state()
    dialog = ui.SharedSettingsHistoryDialog()
    select_revision(dialog, revision)
    assert dialog.undo.isEnabled()
    assert revision in dialog.details.toPlainText()
    monkeypatch.setattr(ui, "confirm_shared_settings", lambda *_: False)
    dialog._undo()
    assert state() == before


def test_history_undo_appends_without_overwriting_unrelated_edit(monkeypatch):
    service = configured()
    revision = service.commit(service.preview({"billing_day": 15}, reason="billing_settings_saved"))
    service.commit(service.preview({"sync_schedule_windows": "[]"}, reason="schedule_settings_saved"))
    dialog = ui.SharedSettingsHistoryDialog()
    select_revision(dialog, revision)
    monkeypatch.setattr(ui, "confirm_shared_settings", lambda *_: True)
    dialog._undo()
    assert database.get_cfg("billing_day") == "31"
    assert database.get_cfg("sync_schedule_windows") == "[]"
    assert SettingsHistory().export()["head"] != revision
    assert "รายการใหม่" in dialog.status.text()


def test_history_stale_undo_leaves_newer_value(monkeypatch):
    service = configured()
    revision = service.commit(service.preview({"billing_day": 15}, reason="billing_settings_saved"))
    dialog = ui.SharedSettingsHistoryDialog()
    select_revision(dialog, revision)
    def review(*_args):
        service.commit(service.preview({"billing_day": 20}, reason="other save"))
        return True
    monkeypatch.setattr(ui, "confirm_shared_settings", review)
    dialog._undo()
    assert database.get_cfg("billing_day") == "20"
    assert "เปลี่ยน" in dialog.status.text()


def test_history_pages_are_read_only_and_do_not_skip_or_repeat():
    service = configured()
    for day in range(1, 9):
        service.commit(service.preview({"billing_day": day}, reason="save"))
    before = state()
    seen, cursor = [], None
    while page := service.history_page(before_rowid=cursor, limit=3):
        seen.extend(row["revision"] for row in page)
        cursor = page[-1]["rowid"]
    assert len(seen) == len(set(seen)) == len(before["history"])
    assert state() == before


@pytest.mark.parametrize("choice", ["incoming", "local", "cancel"])
def test_conflict_dialog_reviews_choice_and_keeps_both_parents(monkeypatch, choice):
    from services.peer_settings_history import _revision
    service = configured()
    root = SettingsHistory().observe_current()
    packet = SettingsHistory().export()
    doc = deepcopy(packet["revisions"][root])
    doc.update(parents=[root], actor="other-computer", reason="billing_settings_saved")
    doc["payload"]["settings"]["billing_day"] = 20
    remote = _revision(doc)
    packet["revisions"][remote] = doc
    packet["head"] = remote
    local = service.commit(service.preview({"billing_day": 15}, reason="billing_settings_saved"))
    assert SettingsHistory().receive(packet)["status"] == "conflict"
    dialog = ui.SharedSettingsHistoryDialog()
    select_revision(dialog, remote)
    assert dialog.accept_peer.isEnabled()
    assert dialog.keep_local.isEnabled()
    assert not dialog.undo.isEnabled()
    before = state()
    monkeypatch.setattr(ui, "confirm_shared_settings", lambda *_: choice != "cancel")
    dialog._choose_peer(choice != "local")
    if choice == "cancel":
        assert state() == before
    else:
        assert database.get_cfg("billing_day") == ("20" if choice == "incoming" else "15")
        packet = SettingsHistory().export()
        assert set(packet["revisions"][packet["head"]]["parents"]) == {remote, local}
        assert not any(row["incoming"] for row in service.history_page())
