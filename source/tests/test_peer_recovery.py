"""Recovery diagnostics use synthetic databases/vaults; no customer secrets."""
import sqlite3

import pytest

import database
from services.installation_identity import installation_private_key_reference, load_or_create_installation_identity
from services.peer_transport_factory import PeerRecoveryRequired, local_membership
from services.registration_vault import SessionRegistrationSecretStore
from test_peer_https import certificates
from test_peer_membership import joined


@pytest.fixture
def enrolled(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    for access in (a, b):
        with sqlite3.connect(access.path) as conn:
            conn.execute("INSERT INTO settings VALUES('installation_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (access.member_id,))
    return a


def test_missing_key_does_not_silently_replace_identity_and_original_can_be_restored(enrolled):
    access = enrolled
    reference = installation_private_key_reference(access.member_id)
    original = access.vault.load(reference)
    access.vault.delete(reference)
    with pytest.raises(PeerRecoveryRequired, match='identity_missing'):
        local_membership(path=access.path, vault=access.vault)
    assert access.vault.load(reference) is None
    access.vault.save(reference, original)
    loaded = local_membership(path=access.path, vault=access.vault)
    assert loaded.identity.public_key_base64url == access.identity.public_key_base64url
    assert loaded.authorize_session('B')


def test_changed_identity_is_rejected_without_overwriting_vault_or_contacts(enrolled):
    access = enrolled
    reference = installation_private_key_reference(access.member_id)
    access.vault.delete(reference)
    other = load_or_create_installation_identity(access.vault, access.member_id)
    before = access.contacts()
    with pytest.raises(PeerRecoveryRequired, match='identity_changed'):
        local_membership(path=access.path, vault=access.vault)
    assert load_or_create_installation_identity(access.vault, access.member_id) == other
    assert access.contacts() == before


def test_missing_group_key_is_not_recreated_from_database(enrolled):
    access = enrolled
    reference = access._reference(access.group()['group_id'])
    access.vault.delete(reference)
    with pytest.raises(PeerRecoveryRequired, match='group_secret_missing'):
        local_membership(path=access.path, vault=access.vault)
    assert access.vault.load(reference) is None


def test_restored_database_under_another_installation_never_creates_keys(enrolled):
    access = enrolled
    with sqlite3.connect(access.path) as conn:
        conn.execute("UPDATE settings SET value='new-installation' WHERE key='installation_id'")
    vault = SessionRegistrationSecretStore()
    with pytest.raises(PeerRecoveryRequired, match='installation_mismatch'):
        local_membership(path=access.path, vault=vault)
    assert not vault._values


def test_vault_read_failure_is_classified_without_leaking_exception(enrolled):
    from komi_snmp_profiler.credential_store import CredentialStoreError
    class OfflineVault:
        def load(self, reference):
            raise CredentialStoreError('synthetic-private-details')
    with pytest.raises(PeerRecoveryRequired) as caught:
        local_membership(path=enrolled.path, vault=OfflineVault())
    assert str(caught.value) == 'vault_unavailable'


def test_restored_local_removal_cannot_reactivate_itself_on_restart(enrolled):
    # Simulate a restored local tombstone, not a supported peer remove action.
    with sqlite3.connect(enrolled.path) as conn:
        conn.execute('UPDATE lan_peer_members SET revoked=1 WHERE member_id=?', (enrolled.member_id,))
    with pytest.raises(PeerRecoveryRequired, match='member_removed'):
        local_membership(path=enrolled.path, vault=enrolled.vault)


def test_loader_never_creates_missing_database(tmp_path):
    path = tmp_path/'absent.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        local_membership(path=path, vault=SessionRegistrationSecretStore())
    assert not path.exists()


def test_runtime_can_retry_after_original_key_is_restored_without_restart(tmp_path, monkeypatch):
    import socket
    from services.background_polling import BackgroundPollingCoordinator
    from services.peer_membership import PeerMembership
    from services.peer_network_runtime import PeerNetworkRuntime
    from services.peer_settings_history import SettingsHistory
    from test_reader_jobs import fixture
    from test_peer_network_runtime import until
    fixture()
    database.set_cfg('company_name', 'Synthetic company')
    database.set_cfg('installation_id', 'A')
    SettingsHistory().observe_current()
    vault = SessionRegistrationSecretStore()
    access = PeerMembership(path=database.get_db_path(), vault=vault,
        identity=load_or_create_installation_identity(vault, 'A'))
    access.initialize_primary('Synthetic company')
    reference = installation_private_key_reference('A')
    original = vault.load(reference)
    vault.delete(reference)
    monkeypatch.setattr('services.secondary_setup._active_ipv4_subnets', lambda: [])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    polling = BackgroundPollingCoordinator()
    runtime = polling.peer_network_runtime = PeerNetworkRuntime(polling,
        runtime_root=tmp_path, membership_loader=lambda **kw: local_membership(vault=vault, **kw),
        host='127.0.0.1', port=port, bind_host='127.0.0.1', enabled=True)
    try:
        polling.pause('synthetic-registration-gate')
        polling.start()
        until(lambda: runtime.state == 'unavailable')
        assert runtime.error == 'identity_missing'
        assert polling.peer_network is None and vault.load(reference) is None
        vault.save(reference, original)
        polling.network_recovered()
        until(lambda: runtime.state == 'connected')
        assert runtime.error == ''
        assert polling.peer_network.client_for('A').manifest()['through'] == 1
    finally:
        polling.stop(wait=True)


def test_signed_renewal_restores_real_tls_without_trusting_replayed_old_leaf(tmp_path, certificates):
    import ipaddress
    from services.peer_contact_discovery import refresh_known_contacts
    from services.peer_network import PeerNetworkNode
    from services.peer_transport_factory import PeerTransportFactory
    a, b = joined(tmp_path, certificates)
    access = {'A': a, 'B': b}
    factories = {name: PeerTransportFactory(peer, runtime_root=tmp_path/'tls',
                    hostname='synthetic-old', lan_ips=['127.0.0.1'])
                 for name, peer in access.items()}
    nodes = {}
    try:
        for name, peer in access.items():
            factory = factories[name]
            node = nodes[name] = PeerNetworkNode(access=peer, client_for=factory.client,
                                                ready=lambda slot: False)
            host, port = node.start(('127.0.0.1', 0), context=factory.context(server=True))
            packet = factory.own_contact(host=host, port=port)
            for recipient in access.values():
                recipient.accept_contact(packet)
        for name, node in nodes.items():
            node._server.tls_context = factories[name].context(server=True)
        assert factories['A'].client('B').manifest()['through'] == 0
        old = next(p for p in a.contacts() if p['document']['member_id'] == 'B')
        old_client = factories['B'].client('A')
        renewed = factories['B'] = PeerTransportFactory(b, runtime_root=tmp_path/'tls',
            hostname='synthetic-renewed', lan_ips=['127.0.0.1'])
        host, port = nodes['B']._server.server_address
        current = renewed.own_contact(host=host, port=port)
        b.accept_contact(current)
        nodes['B']._server.tls_context = renewed.context(server=True)
        assert current['document']['certificate'] != old['document']['certificate']
        assert current['document']['public_key'] == old['document']['public_key']
        with pytest.raises(OSError):
            factories['A'].client('B').manifest()
        interfaces = [(ipaddress.IPv4Address('127.0.0.2'), ipaddress.IPv4Network('127.0.0.0/8'))]
        assert refresh_known_contacts(a, interfaces, discover=lambda _: [('127.0.0.1', 3000)],
            fetch=lambda *_: current) == 1
        # Keep the original SSL context (which contains the retired leaf). The
        # exact live fingerprint authorizer must still reject that old leaf.
        factories['A'].refresh_server_trust(nodes['A']._server.tls_context)
        assert factories['A'].client('B').manifest()['through'] == 0
        assert renewed.client('A').manifest()['through'] == 0
        with pytest.raises((OSError, PermissionError)):
            old_client.manifest()
        assert refresh_known_contacts(a, interfaces, discover=lambda _: [('127.0.0.1', 3000)],
            fetch=lambda *_: old) == 0
        assert factories['A'].client('B').manifest()['through'] == 0
    finally:
        for node in nodes.values():
            node.stop(wait=True)
