from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.initial_slot_baselines import ensure_initial_slot_baselines, InitialBaselineRequired
from services.web_observations import WebObservationStore
from services.slot_epoch_store import SlotEpochStore
from komi_snmp_profiler.models import MeterReading, WebCounterValue, Confidence, WebAuthState


def configure(slots=2):
    database.set_cfg('company_name', 'Initial baseline test')
    database.set_cfg('installation_id', 'INITIAL-SOURCE')
    DeviceConfigRepository().replace_all([DeviceConfig(s, f'Printer {s}', f'192.0.2.{10+s}', serial=f'SER-{s}') for s in range(slots)])


def record(slot, total=100, *, hour=10, confidence=Confidence.VERIFIED):
    stamp = datetime(2026, 9, 22, hour, tzinfo=UTC)
    reading = MeterReading(host=f'192.0.2.{10+slot}', collected_at=stamp.isoformat(),
        counters=tuple(WebCounterValue(field, field, value, 'Device', field, confidence)
            for field, value in (('counter.total.total', total), ('counter.print.total', total),
                ('counter.copy.total', 0), ('counter.print.full_color_total', 0), ('counter.print.bw_total', total))),
        source='fixture', auth_state=WebAuthState.ADMIN)
    return WebObservationStore().record(slot, reading, serial=f'SER-{slot}', printer_name=f'Printer {slot}', at=stamp)


def test_two_fresh_slots_initialize_once_without_accounting_changes():
    configure()
    record(0); record(1)
    path = database.get_db_path()
    assert ensure_initial_slot_baselines(path) == (0, 1)
    heads = [SlotEpochStore().head(s) for s in range(2)]
    assert ensure_initial_slot_baselines(path) == ()
    assert heads == [SlotEpochStore().head(s) for s in range(2)]
    with database._open(commit=False) as conn:
        assert conn.execute('SELECT count(*) FROM billing_ledger').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM daily_meter_records').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM slot_meter_epochs').fetchone()[0] == 2


def test_missing_second_slot_rolls_back_all_initial_baselines():
    configure()
    record(0)
    with pytest.raises(InitialBaselineRequired, match='Slot 2'):
        ensure_initial_slot_baselines(database.get_db_path())
    assert SlotEpochStore().head(0) is None
    record(1)
    assert ensure_initial_slot_baselines(database.get_db_path()) == (0, 1)


@pytest.mark.parametrize('case', ['decrease', 'same_time_conflict', 'unverified', 'serial_change'])
def test_unsafe_initial_evidence_never_creates_a_baseline(case):
    configure(1)
    record(0)
    if case == 'decrease':
        record(0, 90, hour=11)
    elif case == 'same_time_conflict':
        record(0, 110)
    elif case == 'unverified':
        record(0, 110, hour=11, confidence=Confidence.INFERRED)
    else:
        with database._open() as conn:
            conn.execute("UPDATE devices SET serial='REPLACEMENT' WHERE slot=0")
    with pytest.raises(InitialBaselineRequired):
        ensure_initial_slot_baselines(database.get_db_path())
    assert SlotEpochStore().head(0) is None


def test_concurrent_initialization_is_idempotent_and_existing_reset_is_not_auto_approved():
    configure(1)
    record(0)
    path = database.get_db_path()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ensure_initial_slot_baselines, [path, path]))
    assert sorted(map(len, results)) == [0, 1]
    head = SlotEpochStore().head(0)
    record(0, 10, hour=11)
    assert ensure_initial_slot_baselines(path) == ()
    assert SlotEpochStore().head(0) == head


def test_new_member_receives_initial_baselines_without_source_review(tmp_path, monkeypatch):
    from services import peer_enrollment as enrollment
    from services.peer_sync_authorization import ensure_pairing_default, new_claim_token, claim_pairing_window
    from services.peer_transport_factory import local_membership
    from services.registration_vault import SessionRegistrationSecretStore
    configure()
    record(0); record(1)
    source_path = database.get_db_path()
    access = local_membership(vault=SessionRegistrationSecretStore())
    monkeypatch.setenv('KOMI_PEER_SYNC_STATE_FILE', str(tmp_path / 'pairing.json'))
    ensure_pairing_default('INITIAL-SOURCE', continuous=True)
    token = new_claim_token()
    claim_pairing_window(token, '127.0.0.2')
    original = enrollment.prepare_enrollment_source
    monkeypatch.setattr(enrollment, 'prepare_enrollment_source', lambda peer: original(peer, runtime_root=tmp_path/'source', host='127.0.0.1'))
    database.set_db_path(tmp_path/'receiver.db')
    database.init_db()
    preview = enrollment.prepare_enrollment(lambda op, data: enrollment.EnrollmentSource(access).call(token, '127.0.0.2', op, data),
        vault=SessionRegistrationSecretStore(), runtime_root=tmp_path/'target', host='127.0.0.2')
    try:
        preview.commit()
        for slot in (0, 1):
            assert SlotEpochStore().head(slot) == SlotEpochStore(source_path).head(slot)
        assert access.authorize_session(preview.identity.installation_id)
    finally:
        preview.close()


def test_api_explains_missing_web_evidence_without_asking_for_source_approval(monkeypatch):
    from fastapi.testclient import TestClient
    import web_api
    from services import peer_enrollment, peer_transport_factory
    monkeypatch.setattr(peer_transport_factory, 'local_membership', lambda: object())
    def missing(*args, **kwargs):
        raise InitialBaselineRequired('เครื่องต้นทาง Slot 2: ยังไม่มีผลอ่าน Web')
    monkeypatch.setattr(peer_enrollment.EnrollmentSource, 'call', missing)
    response = TestClient(web_api.app).post('/api/v3/peer/enrollment', json={'operation':'begin','data':{}})
    assert response.status_code == 409
    assert response.json()['detail'] == 'เครื่องต้นทาง Slot 2: ยังไม่มีผลอ่าน Web'
