from datetime import UTC, datetime

from PyQt6.QtCore import QCoreApplication

from database import _open
from services.background_polling import BackgroundPollingCoordinator
from services.device_config import DeviceConfigRepository
from services.polling import DevicePollState
from services.runtime_snapshots import runtime_snapshots
from test_shared_slot_review import initial
from test_slot_epoch_store import read
from test_subject_history import _reading


def test_same_serial_baseline_resets_only_transient_meter_state(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    service, _, _ = initial()
    coordinator = BackgroundPollingCoordinator()
    repository = DeviceConfigRepository()
    device = repository.get(0)
    try:
        coordinator._align_poll_scope(device)
        coordinator.states[0] = DevicePollState(last_snmp_total=2000)
        coordinator.last_poll[0] = datetime.now(UTC)
        runtime_snapshots.update(0, _reading(2000, collected_at=datetime.now(UTC)))
        read('OLD', 30, 18)
        with _open() as conn:
            conn.execute("UPDATE devices SET last_total=2000,last_success_at='old-time',credential_ref='keep-credential' WHERE slot=0")
        preview = service.preview(0, actor='PC-A', reason='Reviewed physical reset')
        assert preview['review']['operation'] == 'reset'
        service.confirm(preview)
        after = repository.get(0)
        assert after.serial == device.serial
        assert after.last_total is None and after.last_success_at is None
        assert after.credential_ref == 'keep-credential'
        coordinator._align_poll_scope(after)
        assert coordinator.states[0].last_snmp_total is None
        assert 0 not in coordinator.last_poll
        assert runtime_snapshots.get(0) is None
        with _open(commit=False) as conn:
            assert conn.execute('SELECT COUNT(*) FROM web_observations').fetchone()[0] == 2
        # An idempotent retry cannot discard a newly read total after review.
        repository.update_runtime(0, status='ok', checked_at='new', total=31, success_at='new')
        service.confirm(preview)
        assert repository.get(0).last_total == 31
    finally:
        coordinator.stop(wait=True)


def test_local_review_refreshes_verified_runtime_even_without_new_incoming_settings():
    from test_peer_settings_runtime import runtime
    service, _, _ = initial()
    app, polling, instance = runtime()
    try:
        polling.states[0] = DevicePollState(last_snmp_total=2000)
        polling.last_poll[0] = datetime.now(UTC)
        runtime_snapshots.update(0, _reading(2000, collected_at=datetime.now(UTC)))
        read('OLD', 30, 18)
        service.confirm(service.preview(0, actor='PC-A', reason='Reviewed local reset'))
        instance.process()
        assert 0 not in polling.states and 0 not in polling.last_poll
        assert runtime_snapshots.get(0) is None
        assert polling.reloaded == 1 and polling.is_paused
    finally:
        instance.stop()
