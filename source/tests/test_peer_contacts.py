from contextlib import closing
from copy import deepcopy
import sqlite3

import pytest

from services.peer_contacts import PeerContactExchange, PeerContactPull
from services.peer_transport_factory import PeerTransportFactory
from test_peer_membership import joined, member
from test_peer_https import certificates
from test_peer_network import network


def add_peer(tmp_path, source, name):
    # Synthetic third installation: no copying of enrollment or OS secrets.
    peer = member(tmp_path, name)
    with closing(sqlite3.connect(peer.path)) as conn, conn:
        conn.execute('DELETE FROM lan_peer_group')
        conn.execute('DELETE FROM lan_peer_members')
    peer.accept_invitation(source.invitation(), company=source.group()['company'], primary_id=source.group()['primary_id'])
    factory = PeerTransportFactory(peer, runtime_root=tmp_path / name, lan_ips=['127.0.0.1'])
    packet = factory.own_contact(host='127.0.0.1', port=37853)
    peer.accept_contact(packet)
    source.accept_contact(packet)
    return peer, packet


def exchange(peer):
    return PeerContactExchange(access=peer, authorize=peer.authorize_session)


def test_roster_paging_and_retry_keep_newer_contacts_and_local_removals(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    c, packet = add_peer(tmp_path, a, 'C')
    source, target = exchange(a), exchange(b)
    cursor = ''
    while True:
        page = source.page('B', after=cursor, limit=1)
        result = target.receive('A', page, after=cursor)
        cursor = result['after']
        if not result['more']:
            break
    assert b.members(0) == ('A', 'B', 'C')
    new = c.contact(certificate_pem=packet['document']['certificate'], url='https://127.0.0.1:37854')
    c.accept_contact(new)
    b.accept_contact(new)
    target.receive('A', source.page('B'))  # A still has the old C contact.
    assert next(p for p in b.contacts() if p['document']['member_id'] == 'C') == new
    b.remove('C')
    target.receive('A', source.page('B'))
    assert b.members(0) == ('A', 'B')
    assert target.page('A', after='C') == {'contacts': [], 'after': 'C', 'more': False}


def test_invalid_contact_page_cannot_partially_enroll_or_revive_unknown_sender(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    add_peer(tmp_path, a, 'C')
    add_peer(tmp_path, a, 'D')
    source, target = exchange(a), exchange(b)
    page = source.page('B')
    invalid = deepcopy(page)
    invalid['contacts'][-1]['proof'] = '0' * 64
    with pytest.raises(PermissionError):
        target.receive('A', invalid)
    assert b.members(0) == ('A', 'B')
    with pytest.raises(PermissionError):
        target.receive('C', page)
    with pytest.raises(ValueError, match='order'):
        target.receive('A', {**page, 'after': ''})
    assert b.members(0) == ('A', 'B')


def test_pull_is_bounded_and_cancellation_keeps_cursor(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    add_peer(tmp_path, a, 'C')
    source, target = exchange(a), exchange(b)
    class Transport:
        def contacts(self, *, after):
            return source.page('B', after=after, limit=1)
    pull = PeerContactPull(exchange=target, member='A', transport=Transport())
    assert pull.run(cancelled=lambda: False, max_pages=1)
    from concurrent.futures import CancelledError
    with pytest.raises(CancelledError):
        pull.run(cancelled=lambda: True)
    assert pull.after == 'A'
    assert not pull.run(cancelled=lambda: False)
    assert pull.complete


def test_real_tls_session_imports_third_member_before_reading_its_history(network, tmp_path):
    from datetime import UTC, datetime
    from services.web_observations import WebObservationStore
    from test_subject_history import _reading
    nodes, access, transport, _ = network
    c, packet = add_peer(tmp_path, access['A'], 'C')
    scope = access['A'].current_scope(0)
    event = WebObservationStore(c.path).record(0,
        _reading(303, collected_at=datetime(2026, 9, 18, 10, 15, tzinfo=UTC)),
        serial=scope.serial, printer_name='Synthetic printer', epoch_id=scope.epoch_id)
    assert nodes['A'].data.web.receive('C', [event])['committed']
    assert not access['B'].authorize_session('C')
    result = nodes['B'].session('A').run()
    assert result.status == 'complete'
    assert access['B'].authorize_session('C')
    assert event in WebObservationStore(nodes['B'].path).page()['events']
