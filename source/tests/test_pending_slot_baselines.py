"""Regression: a newly added shared slot read once before its baseline existed."""
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import json
import sqlite3

import pytest
from PyQt6.QtWidgets import QLabel

import app
import database
from services.device_config import DeviceConfigRepository
from services.pending_slot_baselines import recover_pending_slot_baselines
from services.peer_membership import SlotBaselineRequired
from services.raw_counter_history import RawCounterHistoryStore
from services.slot_epoch_store import SlotEpochStore
from services.support_diagnostics import diagnose
from services.web_observations import WebObservationStore
from test_setup_meter_baselines import device, reading, setup_service, preview, plan_for, total
from test_upgrade_baseline_routing import membership, coordinator


def interrupted_setup():
    devices = [device(slot) for slot in range(3)]
    service = setup_service()
    service.commit(preview(service, devices[:2], plan=plan_for(devices[:2])))
    access = membership()
    service.commit(preview(service, devices))
    first = reading(devices[2])
    WebObservationStore().record(2, first, serial=devices[2].serial, printer_name=devices[2].name)
    RawCounterHistoryStore().update_reading(2, first)
    DeviceConfigRepository().update_runtime(2, status='online', checked_at=first.collected_at,
        success_at=first.collected_at, total=2475)
    return devices, access, first


def preserved():
    with database._open(commit=False) as conn:
        return {table: conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                for table in ('daily_raw_counter_records', 'web_observations', 'price_history',
                              'billing_ledger', 'daily_meter_records', 'daily_subject_records')}


def test_repair_preserves_original_evidence_and_counts_only_next_increment():
    devices, access, first = interrupted_setup()
    with pytest.raises(SlotBaselineRequired):
        access.current_scope(2)
    before = preserved()
    old_heads = [SlotEpochStore().head(slot) for slot in (0, 1)]
    assert recover_pending_slot_baselines(database.get_db_path()) == (2,)
    assert preserved() == before
    assert [SlotEpochStore().head(slot) for slot in (0, 1)] == old_heads
    assert access.current_scope(2)
    assert total(SlotEpochStore().current(2)).epoch_usage == 0
    assert total(SlotEpochStore().current(2)).slot_total == 2475
    assert recover_pending_slot_baselines(database.get_db_path()) == ()
    next_read = reading(devices[2], 2480, at=datetime.fromisoformat(first.collected_at)+timedelta(seconds=1))
    WebObservationStore().record(2, next_read, serial=devices[2].serial,
        printer_name=devices[2].name, epoch_id=SlotEpochStore().head(2)['id'])
    RawCounterHistoryStore().update_reading(2, next_read)
    assert total(SlotEpochStore().current(2)).epoch_usage == 5
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT SUM(delta_value) FROM daily_raw_counter_records WHERE device_slot=2 AND canonical_field='counter.total.total'").fetchone()[0] == 5


@pytest.mark.parametrize('reason', ['usage', 'second_read', 'foreign_origin', 'secondary', 'standalone'])
def test_ambiguous_or_non_primary_history_is_never_rebased(reason):
    devices, _, first = interrupted_setup()
    with database._open() as conn:
        if reason == 'usage':
            conn.execute('UPDATE daily_raw_counter_records SET delta_value=1 WHERE device_slot=2')
        elif reason == 'foreign_origin':
            conn.execute("UPDATE web_observation_state SET value='different-origin' WHERE key='origin'")
        elif reason == 'secondary':
            group = json.loads(conn.execute('SELECT document FROM lan_peer_group').fetchone()[0])
            group['primary_id'] = 'different-primary'
            conn.execute('UPDATE lan_peer_group SET document=?', (json.dumps(group),))
        elif reason == 'standalone':
            conn.execute('DELETE FROM lan_peer_group')
    if reason == 'second_read':
        WebObservationStore().record(2, reading(devices[2], at=datetime.fromisoformat(first.collected_at)+timedelta(seconds=1)),
            serial=devices[2].serial, printer_name=devices[2].name)
    before = preserved()
    assert recover_pending_slot_baselines(database.get_db_path()) == ()
    assert SlotEpochStore().head(2) is None
    assert preserved() == before


def test_preparation_failure_is_saved_and_visible_during_and_after_read(tmp_path):
    _, _, _ = interrupted_setup()
    repo = DeviceConfigRepository()
    old_success = repo.get(2).last_success_at
    polling = coordinator(tmp_path, repo)
    future = Future()
    future.set_exception(SlotBaselineRequired('Shared Slot requires reviewed setup and meter baseline'))
    try:
        polling._finished(2, future, repo.get(2))
        failed = repo.get(2)
        assert failed.last_success_at == old_success
        assert failed.connection_status == 'checking'
        assert diagnose(failed.last_error).error_code == 'KOMI-LAN-005'
        label = QLabel()
        messages = []
        fake = SimpleNamespace(polling=SimpleNamespace(repository=repo, active_slots=lambda: {0, 1}),
            pg_overview=SimpleNamespace(read_feedback=label),
            statusBar=lambda: SimpleNamespace(showMessage=messages.append),
            _manual_read_feedback=({0, 1, 2}, datetime.now(UTC)+timedelta(seconds=1)))
        app.MainWindow._refresh_manual_read_feedback(fake)
        assert 'Slot 3 [KOMI-LAN-005]' in label.text()
        fake.polling.active_slots = lambda: set()
        app.MainWindow._refresh_manual_read_feedback(fake)
        assert 'Slot 3 [KOMI-LAN-005]' in label.text()
        assert 'ไม่มีข้อมูลใหม่' not in label.text()
    finally:
        polling.stop(wait=True)


def test_existing_shared_customer_without_proven_new_slot_is_untouched():
    devices = [device(slot) for slot in range(3)]
    service = setup_service()
    # All three slots predate enrollment, as on an upgraded installation.
    service.commit(preview(service, devices))
    membership()
    first = reading(devices[2])
    WebObservationStore().record(2, first, serial=devices[2].serial, printer_name=devices[2].name)
    RawCounterHistoryStore().update_reading(2, first)
    before = preserved()
    assert recover_pending_slot_baselines(database.get_db_path()) == ()
    assert preserved() == before
    assert SlotEpochStore().head(2) is None


def test_failed_revision_rolls_back_entire_repair():
    interrupted_setup()
    before = preserved()
    with database._open() as conn:
        conn.execute("CREATE TRIGGER reject_repair BEFORE INSERT ON peer_settings_revisions BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic write failure'):
        recover_pending_slot_baselines(database.get_db_path())
    assert SlotEpochStore().head(2) is None
    assert preserved() == before
