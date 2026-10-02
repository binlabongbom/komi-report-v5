"""Historical provenance travels without conferring active membership."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import sqlite3

import pytest

from services.peer_contacts import PeerContactPull
from services.peer_membership import _json
from services.web_observations import WebObservationStore
from test_peer_contacts import add_peer, exchange
from test_peer_https import certificates
from test_peer_membership import joined
from test_peer_network import network
from test_subject_history import _reading


def page(packet):
    return {'contacts': [packet], 'after': packet['document']['member_id'], 'more': False}


def signed(peer, document):
    value = {'document': document, 'signature': peer.identity.sign(_json(document).encode())}
    return {**value, 'proof': hmac.new(peer._secret(peer.group()), _json(value).encode(), hashlib.sha256).hexdigest()}


def expired(peer, packet):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    old = x509.load_pem_x509_certificate(packet['document']['certificate'].encode())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    builder = (x509.CertificateBuilder().subject_name(old.subject).issuer_name(old.issuer)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=3)).not_valid_after(now - timedelta(days=1)))
    for extension in old.extensions:
        builder = builder.add_extension(extension.value, extension.critical)
    cert = builder.sign(key, hashes.SHA256())
    return signed(peer, dict(packet['document'], generation=packet['document']['generation'] + 1,
                            certificate=cert.public_bytes(serialization.Encoding.PEM).decode()))


def test_expired_provenance_is_accepted_only_for_history_not_session_access(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    c, packet = add_peer(tmp_path, a, 'C')
    packet = expired(c, packet)
    with pytest.raises(ValueError, match='expired'):
        b.accept_contact(packet)
    target = exchange(b)
    target.receive('A', page(packet), historical=True)
    assert b.members(0) == ('A', 'B')
    assert not b.authorize_session('C')
    assert not any(p['document']['member_id'] == 'C' for p in b.contacts())
    with sqlite3.connect(b.path) as conn:
        assert conn.execute('SELECT origin FROM lan_evidence_origins WHERE member_id=?', ('C',)).fetchone() == (packet['document']['origin'],)
    # The same expired contact in a relayed active roster cannot grant access
    # or prevent the rest of the roster/catch-up from progressing.
    assert target.receive('A', page(packet)) == {'after': 'C', 'more': False}
    assert not b.authorize_session('C')


def test_historical_transfer_neither_revokes_active_member_nor_revives_local_removal(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    c, packet = add_peer(tmp_path, a, 'C')
    b.accept_contact(packet)
    a.remove('C')
    target = exchange(b)
    target.receive('A', exchange(a).page('B', historical=True), historical=True)
    assert b.authorize_session('C')  # A's local removal is not a global decree.
    b.remove('C')
    target.receive('A', page(packet), historical=True)
    target.receive('A', page(packet))
    assert not b.authorize_session('C')


def test_historical_page_rolls_back_if_any_signature_or_origin_binding_conflicts(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    c, cp = add_peer(tmp_path, a, 'C')
    d, dp = add_peer(tmp_path, a, 'D')
    target = exchange(b)
    bad = deepcopy(dp)
    bad['signature'] = '0' * 86
    with pytest.raises((PermissionError, ValueError)):
        target.receive('A', {'contacts': [cp, bad], 'after': 'D', 'more': False}, historical=True)
    with sqlite3.connect(b.path) as conn:
        assert not conn.execute("SELECT 1 FROM lan_evidence_origins WHERE member_id IN ('C','D')").fetchone()
    # Both signatures are valid, but D falsely claims C's retained origin. The
    # conflict after inserting C must still roll back the entire page.
    collision = signed(d, dict(dp['document'], origin=cp['document']['origin']))
    with pytest.raises(PermissionError, match='historical'):
        target.receive('A', {'contacts': [cp, collision], 'after': 'D', 'more': False}, historical=True)
    with sqlite3.connect(b.path) as conn:
        assert not conn.execute("SELECT 1 FROM lan_evidence_origins WHERE member_id IN ('C','D')").fetchone()
    with pytest.raises(PermissionError):
        target.receive('C', page(cp), historical=True)


def test_history_does_not_allow_replayed_older_contact_to_enroll_a_peer(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    c, old = add_peer(tmp_path, a, 'C')
    new = c.contact(certificate_pem=old['document']['certificate'], url='https://127.0.0.1:37854')
    exchange(b).receive('A', page(new), historical=True)
    with pytest.raises(PermissionError, match='Stale'):
        b.accept_contact(old)
    exchange(b).receive('A', page(old))
    assert not b.authorize_session('C')
    # A separately approved current roster can enroll the current identity.
    exchange(b).receive('A', page(new))
    assert b.authorize_session('C')


def test_origin_paging_is_bounded_cancellable_and_can_relay_without_original_member(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    c, packet = add_peer(tmp_path, a, 'C')
    a.remove('C')
    target, source = exchange(b), exchange(a)
    calls = []
    class Transport:
        def contacts(self, *, after):
            calls.append('contacts')
            return source.page('B', after=after)
        def origins(self, *, after):
            calls.append('origins')
            return source.page('B', after=after, limit=1, historical=True)
    pull = PeerContactPull(exchange=target, member='A', transport=Transport())
    assert pull.run(cancelled=lambda: False, max_pages=1)
    assert calls == ['contacts'] and pull.contacts_complete
    assert pull.run(cancelled=lambda: False, max_pages=1)
    assert pull.origins_after == 'A'
    from concurrent.futures import CancelledError
    with pytest.raises(CancelledError):
        pull.run(cancelled=lambda: True)
    assert pull.origins_after == 'A'
    assert not pull.run(cancelled=lambda: False)
    assert any(p['document']['member_id'] == 'C' for p in target.page('A', historical=True)['contacts'])
    assert b.members(0) == ('A', 'B')
    pull.reset()
    assert pull.after == pull.origins_after == '' and not pull.contacts_complete


def test_real_tls_recovers_removed_members_web_history_without_reenrollment(network, tmp_path):
    nodes, access, transport, _ = network
    c, packet = add_peer(tmp_path, access['A'], 'C')
    scope = access['A'].current_scope(0)
    event = WebObservationStore(c.path).record(0,
        _reading(303, collected_at=datetime(2026, 9, 18, 10, 15, tzinfo=UTC)),
        serial=scope.serial, printer_name='Synthetic printer', epoch_id=scope.epoch_id)
    nodes['A'].data.web.receive('C', [event])
    access['A'].remove('C')
    assert not access['B'].authorize_event('A', event)
    session = nodes['B'].session('A')
    assert session.run().status == 'complete'
    assert event in WebObservationStore(nodes['B'].path).page()['events']
    assert access['B'].authorize_event('A', event)
    assert not access['B'].authorize_session('C')
    assert not access['B'].resolve_certificate(access['A']._validate_contact(packet['document']))
    assert session.run().status == 'complete'
    with sqlite3.connect(nodes['B'].path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM web_observations WHERE event_id=?', (event['id'],)).fetchone() == (1,)
    assert any(p['document']['member_id'] == 'C' for p in transport('A', 'B').origins()['contacts'])


def test_runtime_detects_new_provenance_even_without_an_active_roster_change(tmp_path, certificates, monkeypatch):
    from services.background_polling import BackgroundPollingCoordinator
    from services.peer_network_runtime import PeerNetworkRuntime
    a, b = joined(tmp_path, certificates)
    monkeypatch.setattr('services.secondary_setup._active_ipv4_subnets', lambda: [])
    polling = BackgroundPollingCoordinator()
    runtime = PeerNetworkRuntime(polling, runtime_root=tmp_path/'runtime',
        membership_loader=lambda **kw: a, host='127.0.0.1', enabled=True)
    runtime.path = a.path
    try:
        before = runtime._prepare(None)
        assert runtime._prepare(before['digest']) == {'unchanged': True}
        c, packet = add_peer(tmp_path, b, 'C')
        exchange(a).receive('B', page(packet), historical=True)
        after = runtime._prepare(before['digest'])
        assert before['digest'] != after['digest']
        assert before['members'] == after['members'] == ['A', 'B']
        assert runtime._prepare(after['digest']) == {'unchanged': True}
    finally:
        polling.stop(wait=True)
