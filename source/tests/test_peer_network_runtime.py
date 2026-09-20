import socket
from time import monotonic

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import database
from services.background_polling import BackgroundPollingCoordinator
from services.installation_identity import load_or_create_installation_identity
from services.peer_membership import PeerMembership
from services.peer_network_runtime import PeerNetworkRuntime
from services.peer_settings_history import SettingsHistory
from services.registration_vault import SessionRegistrationSecretStore
from test_reader_jobs import fixture


def until(predicate):
    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + 10
    while not predicate() and monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()
    return app


def test_no_enrollment_never_loads_vault_or_creates_listener(tmp_path):
    polling = BackgroundPollingCoordinator()
    def forbidden(**kwargs):
        raise AssertionError('An unenrolled PC must not access membership credentials')
    polling.peer_network_runtime = PeerNetworkRuntime(polling, enabled=True,
        runtime_root=tmp_path, membership_loader=forbidden, host='127.0.0.1', bind_host='127.0.0.1')
    try:
        polling.pause('synthetic-registration-gate')
        polling.start()
        until(lambda: polling.peer_network_runtime._future is None)
        assert polling.peer_network_runtime.state == 'not_enrolled'
        assert polling.peer_network is None and polling.shared_reads is None
    finally:
        polling.stop(wait=True)


def test_enrolled_runtime_starts_from_records_and_survives_owner_restart(tmp_path, monkeypatch):
    fixture()
    database.set_cfg('company_name', 'Synthetic company')
    database.set_cfg('installation_id', 'A')
    SettingsHistory().observe_current()
    vault = SessionRegistrationSecretStore()
    access = PeerMembership(path=database.get_db_path(), vault=vault,
        identity=load_or_create_installation_identity(vault, 'A'))
    access.initialize_primary('Synthetic company')
    monkeypatch.setattr('services.secondary_setup._active_ipv4_subnets', lambda: [])
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    boot_ids = []
    for _ in range(2):
        polling = BackgroundPollingCoordinator()
        polling.peer_network_runtime = PeerNetworkRuntime(polling, runtime_root=tmp_path,
            membership_loader=lambda **kwargs: access, host='127.0.0.1', port=port,
            bind_host='127.0.0.1', enabled=True)
        try:
            polling.pause('synthetic-registration-gate')
            polling.start()
            until(lambda: polling.peer_network is not None)
            node = polling.peer_network
            assert polling.peer_network_runtime.state == 'connected'
            assert polling.shared_reads is node.shared_reads
            assert polling.peer_settings is not None
            assert node._server.server_address == ('127.0.0.1', port)
            assert not node.election.presence('A', access.current_scope(0)).ready
            boot_ids.append(node.election.boot_id)
            assert node.client_for('A').manifest()['through'] == 1
        finally:
            polling.stop(wait=True)
        assert node._server.active_requests == 0
        assert not node._thread.is_alive()
    assert boot_ids[0] != boot_ids[1]
