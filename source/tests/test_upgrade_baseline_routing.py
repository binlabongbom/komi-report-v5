"""An installed legacy database must not become a new shared enrollment."""
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

import app
import database
from services.background_polling import BackgroundPollingCoordinator
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.installation_identity import load_or_create_installation_identity
from services.peer_membership import PeerMembership
from services.peer_network_runtime import PeerNetworkRuntime
from services.peer_settings_history import SettingsHistory
from services.registration_vault import SessionRegistrationSecretStore
from services.shared_web_read import SharedWebRead
from services.slot_epoch_store import SlotEpochStore
from services.subject_history import SubjectDailyCacheStore
from test_background_polling import FakeProbe, FakeReader
from test_reader_jobs import fixture as reviewed_slot


def configured_legacy_slot():
    database.set_cfg("company_name", "Existing customer")
    repository = DeviceConfigRepository()
    device = DeviceConfig(0, "Existing printer", "192.0.2.10", serial="SERIAL-1", last_total=100)
    repository.replace_all([device])
    assert SlotEpochStore().head(0) is None
    return repository, device


def coordinator(tmp_path, repository, **kwargs):
    QApplication.instance() or QApplication([])
    return BackgroundPollingCoordinator(
        repository, cache=DailyCacheStore(tmp_path / "meter-cache"),
        subject_cache=SubjectDailyCacheStore(tmp_path / "subject-cache"), **kwargs,
    )


def membership():
    database.set_cfg("company_name", "Existing customer")
    vault = SessionRegistrationSecretStore()
    access = PeerMembership(
        path=database.get_db_path(), vault=vault,
        identity=load_or_create_installation_identity(vault, "upgrade-routing-test"),
    )
    access.initialize_primary("Existing customer")
    SettingsHistory().observe_current()
    return access


def test_configured_legacy_slot_opens_and_reads_without_new_shared_baseline(tmp_path, monkeypatch):
    repository, device = configured_legacy_slot()
    assert app._v5_setup_is_complete(repository)
    now = datetime.fromisoformat("2026-09-25T10:00:00+07:00")

    class Reader(FakeReader):
        calls = 0

        def read(self, host):
            self.calls += 1
            return replace(super().read(host), collected_at=now.isoformat())

    reader = Reader()
    polling = coordinator(tmp_path, repository, probe=FakeProbe(), reader=reader, clock=lambda: now)
    # Discovery is enabled in production. An empty membership table alone,
    # rather than the test suite's discovery-disable flag, must stop enrollment.
    monkeypatch.delenv("KOMI_DISCOVERY_DISABLED", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("A legacy standalone installation must not open membership credentials or a listener")

    runtime = PeerNetworkRuntime(polling, runtime_root=tmp_path, membership_loader=forbidden)
    monkeypatch.setattr(polling, "bind_peer_network", forbidden)
    try:
        assert runtime.enabled
        assert runtime._prepare(None, discover=True) is None
        assert polling.peer_network is None and polling.shared_reads is None
        before = replace(FakeReader().read(device.host), collected_at=now.isoformat())
        before = replace(before, counters=tuple(
            replace(counter, count=100) if counter.canonical_field == "counter.total.total" else counter
            for counter in before.counters
        ))
        polling.cache.update_reading(0, before, at=now - timedelta(seconds=1))
        assert polling._poll_device(device, force_web=True)
        assert reader.calls == 1
        state = polling.cache.load(0, now.date())
        assert state["opening"]["counter.total.total"] == 100
        assert state["latest"]["counter.total.total"] == 101
        assert state["delta"]["counter.total.total"] == 1
        assert SlotEpochStore().head(0) is None
        assert app._v5_setup_is_complete(repository)
        with database._open(commit=False) as conn:
            assert conn.execute("SELECT COUNT(*) FROM lan_peer_group").fetchone()[0] == 0
    finally:
        runtime.stop(wait=True)
        polling.stop(wait=True)


def test_enrolled_slot_without_reviewed_baseline_never_falls_back_to_local_read(tmp_path):
    repository, device = configured_legacy_slot()
    access = membership()

    class ForbiddenReader:
        def read(self, host):
            pytest.fail("Missing shared baseline must not bypass membership and perform a local read")

    polling = coordinator(tmp_path, repository, probe=ForbiddenReader(), reader=ForbiddenReader())
    polling.shared_reads = SharedWebRead(
        router=None, current_scope=access.current_scope, observations=polling.observations,
        publish=lambda *args: None, fetch=lambda *args: None,
    )
    try:
        with pytest.raises(PermissionError, match="reviewed setup and meter baseline"):
            polling._poll_device(device, force_web=True)
        assert SlotEpochStore().head(0) is None
        assert polling.observations.page()["events"] == []
    finally:
        polling.stop(wait=True)


def test_enrolled_read_refuses_changed_serial_without_replacing_original_epoch(tmp_path):
    reviewed_slot()
    access = membership()
    original_epoch = SlotEpochStore().head(0)
    repository = DeviceConfigRepository()
    device = repository.get(0)

    class GrantedSharedRead:
        # A verified grant precedes SNMP; the probe below reveals a different
        # physical printer, which must invalidate that grant before Web reads.
        current_scope = access.current_scope

        def prepare(self, *args, **kwargs):
            return SimpleNamespace(job={"can_read": True})

        def collect(self, *args, **kwargs):
            pytest.fail("A replaced printer must not use the previous printer's shared epoch")

    class ForbiddenReader:
        def read(self, host):
            pytest.fail("Identity mismatch must be detected before reading Web")

    polling = coordinator(tmp_path, repository, probe=FakeProbe(), reader=ForbiddenReader(),
                          shared_reads=GrantedSharedRead())
    try:
        assert not polling._poll_device(device, force_web=True)
        assert SlotEpochStore().head(0) == original_epoch
        assert "Printer identity or baseline differs" in repository.get(0).last_error
        assert len(polling.observations.page()["events"]) == 1
    finally:
        polling.stop(wait=True)
