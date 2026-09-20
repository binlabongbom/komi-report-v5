from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
import sqlite3
from threading import Event

import pytest

import database
from services.installation_identity import load_or_create_installation_identity
from services.peer_membership import PeerMembership
from services.peer_network import PeerNetworkNode
from services.peer_https import PeerHTTPSClient
from services.peer_settings_history import SettingsHistory
from services.registration_vault import SessionRegistrationSecretStore
from services.web_observations import WebObservationStore
from test_peer_https import certificates, context
from test_reader_jobs import fixture
from test_subject_history import _reading


@pytest.fixture
def network(tmp_path, certificates):
    fixture()
    database.set_cfg('company_name', 'Synthetic network')
    SettingsHistory().observe_current()
    paths = {'A': database.get_db_path(), 'B': tmp_path / 'B-node.db'}
    with closing(sqlite3.connect(paths['A'])) as source, closing(sqlite3.connect(paths['B'])) as target:
        source.backup(target)
        target.execute("DELETE FROM web_observation_state WHERE key='origin'")
        target.commit()
    access = {}
    for name in ('A', 'B'):
        vault = SessionRegistrationSecretStore()
        access[name] = PeerMembership(path=paths[name], vault=vault,
            identity=load_or_create_installation_identity(vault, name))
    access['A'].initialize_primary('Synthetic network')
    access['B'].accept_invitation(access['A'].invitation(), company='Synthetic network', primary_id='A')
    urls, nodes, ready = {}, {}, {'A', 'B'}
    def transport(local, remote):
        return PeerHTTPSClient(urls[remote], member=remote, context=context(certificates, local),
            authorize_certificate=access[local].authorize_certificate, timeout=2)
    try:
        for name in ('A', 'B'):
            node = nodes[name] = PeerNetworkNode(access=access[name],
                client_for=lambda remote, local=name: transport(local, remote),
                ready=lambda slot, local=name: local in ready)
            address = node.start(('127.0.0.1', 0), context=context(certificates, name, server=True))
            urls[name] = f'https://127.0.0.1:{address[1]}'
        for name in ('A', 'B'):
            packet = access[name].contact(certificate_pem=certificates[name]['certificate'].read_text(), url=urls[name])
            for peer in access.values():
                peer.accept_contact(packet)
        yield nodes, access, transport, ready
    finally:
        for node in nodes.values():
            node.stop(wait=True)


def collect(node, request, read):
    return node.shared_reads.collect(0, manual=True, request_id=request,
        read=read, printer_name='Synthetic printer')


def test_real_tls_manual_reader_and_joiner_receive_one_committed_web_result(network):
    nodes, access, transport, _ = network
    entered, release, joined = Event(), Event(), Event()
    calls = []
    def printer():
        calls.append('web')
        entered.set()
        assert release.wait(8)
        return _reading(301, collected_at=datetime(2026, 9, 18, 10, 10, tzinfo=UTC))
    original = nodes['A'].router.request
    def join(*args, **kwargs):
        result = original(*args, **kwargs)
        assert not result.job['can_read']
        joined.set()
        return result
    nodes['A'].router.request = join
    with ThreadPoolExecutor(max_workers=2) as pool:
        b = pool.submit(collect, nodes['B'], 'manual-1010', printer)
        try:
            assert entered.wait(8)
            a = pool.submit(collect, nodes['A'], 'simultaneous', lambda: pytest.fail('Joined peer read printer'))
            assert joined.wait(8)
        finally:
            release.set()
        first, second = b.result(timeout=8), a.result(timeout=8)
    assert calls == ['web']
    assert first.event == second.event
    assert first.local and not second.local
    assert nodes['A'].shared_reads.scheduled_owner(0)
    assert not nodes['B'].shared_reads.scheduled_owner(0)
    assert all(len(WebObservationStore(node.path).page()['events']) == 2 for node in nodes.values())


def test_real_tls_delivery_uses_membership_scope_and_survives_duplicate_run(network):
    nodes, access, _, _ = network
    scope = access['A'].current_scope(0)
    event = WebObservationStore(nodes['A'].path).record(0,
        _reading(123, collected_at=datetime(2026, 9, 18, 10, tzinfo=UTC)),
        serial=scope.serial, printer_name='Fixture', epoch_id=scope.epoch_id)
    session = nodes['A'].session('B')
    assert session.run().status == 'complete'
    assert event in WebObservationStore(nodes['B'].path).page()['events']
    assert session.run().sent == 0
    access['A'].remove('B')
    with pytest.raises(PermissionError):
        session.run()
    with pytest.raises(PermissionError):
        nodes['A'].session('B')


def test_shutdown_fences_inflight_request_and_tracks_drain(network):
    nodes, access, transport, _ = network
    entered, release = Event(), Event()
    original = nodes['A'].data.history.manifest
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)
    nodes['A'].data.history.manifest = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(transport('B', 'A').manifest)
        try:
            assert entered.wait(5)
            assert nodes['A'].stop() == 1
            assert nodes['A'].resolve_certificate('anything') is None
            with pytest.raises(PermissionError):
                nodes['A'].session('B')
        finally:
            release.set()
        with pytest.raises(PermissionError):
            request.result(timeout=5)
    assert nodes['A'].stop(wait=True) == 0


def test_ineligible_owner_yields_to_eligible_peer(network):
    nodes, _, _, ready = network
    ready.remove('A')
    assert nodes['B'].shared_reads.scheduled_owner(0)
    ready.add('A')
    assert not nodes['A'].shared_reads.scheduled_owner(0)


def test_trickled_headers_cannot_hold_runtime_shutdown(network):
    import socket
    from threading import Thread
    from time import monotonic
    nodes, _, transport, _ = network
    node = nodes['A']
    node._server.peer_timeout = .5
    client = transport('B', 'A')
    stop = Event()
    with socket.create_connection((client.host, client.port), timeout=2) as raw:
        with client.context.wrap_socket(raw, server_hostname=client.host) as tls:
            tls.sendall(b'POST /komi-peer/v1/rpc HTTP/1.0\r\nX-Slow: ')
            def trickle():
                while not stop.wait(.1):
                    try:
                        tls.sendall(b'x')
                    except OSError:
                        break
            writer = Thread(target=trickle, daemon=True)
            writer.start()
            try:
                started = monotonic()
                assert node.stop(wait=True) == 0
                assert monotonic() - started < 2
            finally:
                stop.set()
                writer.join(2)


def test_real_tls_receive_applies_settings_and_refreshes_live_view_on_qt_owner(network):
    from services.background_polling import BackgroundPollingCoordinator
    from services.shared_settings import SharedSettingsService
    from services.runtime_snapshots import runtime_snapshots
    from test_peer_history_runtime import until
    nodes, access, _, _ = network
    database.set_db_path(nodes['B'].path)
    polling = BackgroundPollingCoordinator()
    polling.pause('synthetic-registration-gate')
    try:
        b = nodes['B']
        polling.bind_peer_network(b, address=('127.0.0.1', 0), context=b._server.tls_context, members=('A', 'B'))
        database.set_db_path(nodes['A'].path)
        editor = SharedSettingsService()
        revision = editor.commit(editor.preview({'waste_paper_pct': 7}, reason='Synthetic shared edit'))
        scope = access['A'].current_scope(0)
        observed = datetime(2026, 9, 19, 10, 10, tzinfo=UTC)
        event = WebObservationStore(nodes['A'].path).record(0, _reading(999, collected_at=observed),
            at=observed, serial=scope.serial, printer_name='Synthetic printer', epoch_id=scope.epoch_id)
        database.set_db_path(nodes['B'].path)
        assert nodes['A'].session('B').run().status == 'complete'
        # No test-triggered settings application or snapshot refresh: receipt
        # signals from the HTTPS worker must reach the existing Qt owner.
        until(lambda: database.get_cfg('waste_paper_pct') == '7.0')
        until(lambda: runtime_snapshots.get(0) is not None and runtime_snapshots.get(0).event_id == event['id'])
        assert access['B'].current_scope(0).settings_revision == revision
        assert polling.is_paused
        assert runtime_snapshots.get(0).collected_at == observed.isoformat()
    finally:
        polling.stop(wait=True)


def test_startup_and_reconnect_wake_remote_delivery_without_endless_echo(network):
    nodes, _, _, _ = network
    sessions = {'A': nodes['A'].session('B'), 'B': nodes['B'].session('A')}
    wakes = []
    for name, node in nodes.items():
        def received(member, local=name):
            wakes.append((local, member))
            sessions[local].reconnected(announce=False)
        node.on_wake = received
    for _ in range(3):
        sessions['A'].run()
        sessions['B'].run()
    assert len(wakes) == 2
    sessions['B'].reconnected()
    sessions['B'].run()
    sessions['A'].run()
    sessions['B'].run()
    assert len(wakes) == 3 and wakes[-1] == ('A', 'B')
