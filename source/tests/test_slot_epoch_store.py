from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, UTC
import hashlib
import json
import sqlite3
import uuid

import pytest

import database
from database import _open
from services.slot_epoch_store import SlotEpochStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.web_observations import WebObservationStore, _json
from services.web_observation_archive import WebObservationArchive
from test_subject_history import _reading
from test_slot_meter_continuity import total


def read(serial, value, day, *, bw=None):
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial=serial)])
    at = datetime(2026, 9, day, 10, tzinfo=UTC)
    reading = _reading(value, collected_at=at)
    if bw is not None:
        reading = replace(reading, counters=(reading.counters[0], replace(reading.counters[1], count=bw)))
    return WebObservationStore().record(0, reading, at=at, serial=serial, printer_name="Fixture")


def confirm(store, event, operation):
    preview = store.preview(0, event["id"], operation=operation, actor="PC-A", reason="Reviewed fixture physical meter")
    return store.confirm(preview)


def fixture():
    store = SlotEpochStore()
    old = read("OLD", 2000, 16)
    head = confirm(store, old, "initial")
    return store, old, head


def imported_old(old, value, day):
    event = deepcopy(old)
    event["payload"]["read_id"] = uuid.uuid4().hex
    event["payload"]["observed_at"] = datetime(2026, 9, day, 11, tzinfo=UTC).isoformat()
    event["payload"]["reading"]["counters"][0]["count"] = value
    event["id"] = hashlib.sha256(_json(event["payload"]).encode()).hexdigest()
    WebObservationStore().receive([event], expected_slot=0, expected_serial=event["payload"]["serial"])
    return event


def test_replacement_survives_restart_days_and_archival_without_meter_jump(tmp_path):
    store, _, _ = fixture()
    baseline = read("USED", 50000, 18)
    preview = store.preview(0, baseline["id"], operation="replacement", actor="PC-A", reason="Old printer unavailable")
    head = store.confirm(preview)
    assert store.confirm(preview) == head
    assert total(store.current(0)).slot_total == 2000
    next_read = read("USED", 50100, 19)
    assert store.assign(next_read["id"], head)
    assert not store.assign(next_read["id"], head)
    assert total(SlotEpochStore().current(0)).slot_total == 2100
    archive = WebObservationArchive()
    while archive.archive_batch(today=date(2028, 1, 1)):
        pass
    assert total(SlotEpochStore().current(0)).physical_maximum == 50100
    from tools.db_recovery import backup_database
    backup = tmp_path / "portable" / "recovered.sqlite3"
    backup_database(database.get_db_path(), backup)
    assert SlotEpochStore(backup).head(0)["id"] == head
    assert total(SlotEpochStore(backup).current(0)).slot_total == 2100
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_epochs").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_epoch_outbox").fetchone()[0] == 2


@pytest.mark.parametrize("change", ["parent_evidence", "candidate", "device"])
def test_stale_preview_never_changes_head_or_outbox(change):
    store, old, old_head = fixture()
    candidate = read("USED", 50000, 18)
    preview = store.preview(0, candidate["id"], operation="replacement", actor="A", reason="review")
    if change == "parent_evidence":
        new = imported_old(old, 2020, 17)
        store.assign(new["id"], old_head)
    elif change == "candidate":
        read("USED", 50001, 19)
    else:
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Changed", "192.0.2.11", serial="USED")])
    with pytest.raises(ValueError):
        store.confirm(preview)
    assert store.head(0)["id"] == old_head
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_epochs").fetchone()[0] == 1


def test_failed_outbox_insert_rolls_back_epoch_maxima_and_head():
    store, _, old_head = fixture()
    candidate = read("USED", 50000, 18)
    preview = store.preview(0, candidate["id"], operation="replacement", actor="A", reason="review")
    with _open() as conn:
        conn.execute("CREATE TRIGGER fail_epoch BEFORE INSERT ON slot_meter_epoch_outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.Error):
        store.confirm(preview)
    assert store.head(0)["id"] == old_head
    with _open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_epoch_state").fetchone()[0] == 1
        conn.execute("DROP TRIGGER fail_epoch")
    assert store.confirm(preview) == preview["epoch"]["id"]


def test_partial_reset_preserves_unreset_counter_increase_in_boundary_reading():
    store, _, old_head = fixture()
    at = datetime(2026, 9, 18, 10, tzinfo=UTC)
    reading = _reading(50, collected_at=at)
    reading = replace(reading, counters=(reading.counters[0], replace(reading.counters[1], count=3000)))
    boundary = WebObservationStore().record(0, reading, serial="OLD", printer_name="Fixture", epoch_id=old_head)
    reset = confirm(store, boundary, "reset")
    current = store.current(0)
    assert total(current).slot_total == 2000
    assert next(item for item in current.counters if "bw_total" in item.key).slot_total == 3000
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_assignments WHERE event_id=?", (boundary["id"],)).fetchone()[0] == 2
    next_read = read("OLD", 80, 19, bw=3010)
    store.assign(next_read["id"], reset)
    assert total(store.current(0)).slot_total == 2030
    assert next(item for item in store.current(0).counters if "bw_total" in item.key).slot_total == 3010
    assert not store.assign(boundary["id"], old_head)  # already bound atomically at confirmation


def test_late_closed_parent_evidence_flags_all_descendants_without_rewriting_totals():
    store, old, old_head = fixture()
    second = confirm(store, read("USED", 50000, 18), "replacement")
    store.assign(read("USED", 50100, 19)["id"], second)
    third = confirm(store, read("THIRD", 9000, 20), "replacement")
    store.assign(read("THIRD", 9050, 21)["id"], third)
    late = imported_old(old, 2010, 17)
    store.assign(late["id"], old_head)
    result = store.current(0)
    assert total(result).slot_total == 2150
    assert "late_parent_evidence" in result.issues


def test_maximum_proof_reads_only_selected_events_not_entire_journal(monkeypatch):
    store, _, head = fixture()
    for value in range(2001, 2021):
        item = read("OLD", value, 17)
        store.assign(item["id"], head)
    seen = []
    original = store._event
    def tracked(conn, event_id):
        seen.append(event_id)
        return original(conn, event_id)
    monkeypatch.setattr(store, "_event", tracked)
    assert total(store.current(0)).slot_total == 2020
    assert len(seen) <= 2  # one maximum per counter, baseline embedded in definition


def test_foreign_epoch_rebinding_is_rejected_and_reset_clears_all_references():
    store, old, _ = fixture()
    reset = confirm(store, read("OLD", 50, 18), "reset")
    with pytest.raises(ValueError, match="another epoch"):
        store.assign(old["id"], reset)
    database.reset_usage_data()
    assert store.head(0) is None and store.current(0) is None
    with _open(commit=False) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_epoch_bound_web_record_and_maximum_commit_together():
    store, _, head = fixture()
    at = datetime(2026, 9, 17, 10, tzinfo=UTC)
    events = WebObservationStore()
    bound = events.record(0, _reading(2010, collected_at=at), serial="OLD", printer_name="Fixture", epoch_id=head)
    assert bound["payload"]["format"] == "komi.web.observation.v2"
    assert bound["payload"]["meter_epoch_id"] == head
    assert total(store.current(0)).slot_total == 2010
    before = events.page()
    with _open() as conn:
        conn.execute("CREATE TRIGGER fail_maximum BEFORE UPDATE ON slot_meter_maxima BEGIN SELECT RAISE(ABORT,'maximum failure'); END")
    with pytest.raises(sqlite3.Error):
        events.record(0, _reading(2020, collected_at=at), serial="OLD", printer_name="Fixture", epoch_id=head)
    assert events.page() == before
    assert total(store.current(0)).slot_total == 2010
    with pytest.raises(ValueError, match="authorized meter epoch"):
        events.receive([bound], expected_slot=0, expected_serial="OLD")
    assert events.receive([bound], expected_slot=0, expected_serial="OLD", expected_epoch=head) == (bound["id"],)


def test_epoch_change_during_web_read_cannot_bind_result_to_new_baseline():
    store, _, old_head = fixture()
    boundary = read("OLD", 50, 18)
    new_head = confirm(store, boundary, "reset")
    at = datetime(2026, 9, 19, 10, tzinfo=UTC)
    before = WebObservationStore().page()
    with pytest.raises(ValueError, match="changed during"):
        WebObservationStore().record(0, _reading(80, collected_at=at), serial="OLD", printer_name="Fixture", epoch_id=old_head)
    assert WebObservationStore().page() == before
    event = WebObservationStore().record(0, _reading(80, collected_at=at), serial="OLD", printer_name="Fixture", epoch_id=new_head)
    assert total(store.current(0)).slot_total == 2030
    assert event["payload"]["meter_epoch_id"] == new_head


def test_existing_other_printer_history_cannot_be_initialized_as_new_absolute_meter():
    read("OLD", 2000, 16)
    candidate = read("USED", 50000, 18)
    store = SlotEpochStore()
    with pytest.raises(ValueError, match="migration review"):
        confirm(store, candidate, "initial")
    assert store.head(0) is None
