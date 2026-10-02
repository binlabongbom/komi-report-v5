from copy import deepcopy
from datetime import date
import json
import sqlite3

import pytest

from database import _open, set_cfg
from services.device_config import DeviceConfigRepository
from services.peer_settings_history import SettingsHistory
from services.shared_settings import SharedSettingsService
from services.shared_settings_document import validate
from services.shared_slot_review import SharedSlotReviewService
from services.setup_settings import SetupSettingsService
from services.slot_epoch_store import SlotEpochStore
from test_slot_epoch_store import read
from test_slot_meter_continuity import total


def initial():
    set_cfg("company_name", "Synthetic company")
    set_cfg("client_first_started_at", "2026-09-01")
    read("OLD", 2000, 16)
    service = SharedSlotReviewService()
    preview = service.preview(0, actor="PC-A", reason="Confirmed initial printer")
    revision = service.confirm(preview)
    return service, preview, revision


def test_slot_review_atomically_links_epoch_to_settings_and_survives_other_edits():
    service, preview, revision = initial()
    assert service.confirm(preview) == revision
    packet = SettingsHistory().export()
    payload = packet["revisions"][revision]["payload"]
    assert payload["format_version"] == 3
    assert payload["slot_epochs"] == [{"slot": 0, "epoch_id": preview["review"]["epoch"]["id"]}]
    validate(payload)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM peer_settings_events WHERE revision=?", (revision,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_epoch_outbox").fetchone()[0] == 1
    changes = SharedSettingsService()
    changes.commit(changes.preview({"waste_paper_pct": 10}, reason="test"))
    setup = SetupSettingsService(DeviceConfigRepository())
    setup.commit(setup.preview(DeviceConfigRepository().list(), {"billing_day": "10"}, []))
    latest = SettingsHistory().observe_current()
    assert SettingsHistory().export()["revisions"][latest]["payload"]["slot_epochs"] == payload["slot_epochs"]
    assert service.confirm(preview) == revision  # Does not undo the newer settings.


@pytest.mark.parametrize("failure", ["journal", "outbox", "receipt"])
def test_failure_rolls_back_epoch_settings_head_and_all_delivery_records(failure):
    service, _, revision = initial()
    read("USED", 50000, 18)
    preview = service.preview(0, actor="PC-A", reason="Replace old printer")
    tables = ("slot_meter_epochs", "slot_meter_heads", "slot_meter_epoch_state", "slot_meter_assignments",
              "slot_meter_maxima", "slot_meter_epoch_outbox", "peer_settings_revisions", "peer_settings_state",
              "peer_settings_events", "config_log")
    def state():
        with _open(commit=False) as conn:
            return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables}
    before = state()
    table = {"journal": "peer_settings_revisions", "outbox": "peer_settings_events", "receipt": "config_log"}[failure]
    with _open() as conn:
        conn.execute(f"CREATE TRIGGER fail_slot BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.Error):
        service.confirm(preview)
    assert state() == before


def test_settings_change_or_new_read_invalidates_review_and_replacement_does_not_jump():
    service, _, _ = initial()
    read("USED", 50000, 18)
    preview = service.preview(0, actor="PC-A", reason="Replacement")
    set_cfg("billing_day", "15")
    with pytest.raises(ValueError, match="Settings changed"):
        service.confirm(preview)
    preview = service.preview(0, actor="PC-A", reason="Replacement")
    service.confirm(preview)
    store = SlotEpochStore()
    assert total(store.current(0)).slot_total == 2000
    event = read("USED", 50100, 19)
    store.assign(event["id"], store.head(0)["id"])
    assert total(store.current(0)).slot_total == 2100


@pytest.mark.parametrize("refs", [[{"slot": 3, "epoch_id": "a" * 64}],
    [{"slot": 0, "epoch_id": "a" * 64}] * 2, [{"slot": 0, "epoch_id": "x" * 64}], []])
def test_invalid_shared_epoch_references_are_rejected(refs):
    _, _, revision = initial()
    payload = deepcopy(SettingsHistory().export()["revisions"][revision]["payload"])
    payload["slot_epochs"] = refs
    with pytest.raises(ValueError):
        validate(payload)


def test_history_ui_shows_slot_reference_and_dialog_checks_reason_cancel_and_stale():
    from ui.shared_settings_history import SharedSettingsHistoryDialog
    from ui.slot_baseline_review import SlotBaselineDialog
    service, _, _ = initial()
    history = SharedSettingsHistoryDialog()
    history.records.setCurrentRow(0)
    assert "Slot 1" in history.details.toPlainText()
    history.reject()
    read("USED", 50000, 18)
    dialog = SlotBaselineDialog(DeviceConfigRepository().list())
    dialog.load()
    assert dialog.future is None
    dialog.reason.setText("Replace old printer")
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert "OLD → USED" in dialog.status.text()
    assert not dialog.confirm_button.isEnabled()
    dialog.verified.setChecked(True)
    assert dialog.confirm_button.isEnabled()
    # New reading after the preview must prevent confirming the old physical baseline.
    read("USED", 50010, 19)
    dialog.confirm()
    with pytest.raises(ValueError):
        dialog.future.result(timeout=10)
    dialog.collect()
    assert dialog.preview is None and dialog.revision is None
    assert SlotEpochStore().head(0)["document"]["baseline_event"]["payload"]["serial"] == "OLD"
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    dialog.verified.setChecked(True)
    dialog.confirm()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert dialog.revision is not None
    assert total(SlotEpochStore().current(0)).slot_total == 2000
    dialog.pool.shutdown(wait=True)


def test_slot_dialog_cancel_preserves_database():
    from ui.slot_baseline_review import SlotBaselineDialog
    initial()
    read("USED", 50000, 18)
    old = SlotEpochStore().head(0)
    dialog = SlotBaselineDialog(DeviceConfigRepository().list())
    dialog.reason.setText("Replacement")
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    dialog.reject()
    dialog.pool.shutdown(wait=True)
    assert SlotEpochStore().head(0) == old
