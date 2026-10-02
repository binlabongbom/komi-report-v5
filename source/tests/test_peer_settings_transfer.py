import sqlite3
from types import SimpleNamespace

import pytest

from services.peer_settings_transfer import PeerSettingsTransfer
from services.peer_https import PeerDataEndpoint
from test_peer_https import certificates, server, client
import database
from services.peer_settings_history import SettingsHistory
from test_peer_settings_pages import seed, count


def journal(path):
    previous = database.get_db_path()
    try:
        database.set_db_path(path)
        database.init_db()
    finally:
        database.set_db_path(previous)
    return SettingsHistory(path)


def test_paged_settings_over_tls_resume_without_applying_partial_values(certificates, tmp_path):
    a, b = journal(tmp_path/'A.db'), journal(tmp_path/'B.db')
    head = seed(a, 7)
    sender = PeerSettingsTransfer(path=a.path, authorize=lambda *a: True)
    receiver = PeerSettingsTransfer(path=b.path, authorize=lambda *a: True)
    endpoint = PeerDataEndpoint(history=None, epochs=None, amendments=None, settings=receiver)
    with server(certificates, endpoint) as url:
        transport = client(certificates, url)
        assert sender.send('B', transport, max_pages=1, page_size=2)['committed'] is False
        assert count(b) == 2 and sender.outbox.next_delivery('B') is not None
        sender = PeerSettingsTransfer(path=a.path, authorize=lambda *a: True)
        assert sender.send('B', transport, max_pages=1, page_size=2)['committed'] is False
        assert count(b) == 4  # Continues at the durable cursor rather than page zero.
        receipt = sender.send('B', transport, page_size=2)
        assert receipt == {'head': head, 'next_offset': None, 'committed': True, 'status': 'initial_review'}
        assert count(b) == 7 and sender.outbox.next_delivery('B') is None
    with sqlite3.connect(b.path) as conn:
        assert b._state(conn, 'head') is None  # Receiving history is not approval to overwrite app settings.


def test_revocation_rolls_back_imported_page(tmp_path):
    a, b = journal(tmp_path/'A.db'), journal(tmp_path/'B.db')
    seed(a, 1)
    calls = []
    def allowed(*args):
        calls.append(args)
        return len(calls) == 1
    receiver = PeerSettingsTransfer(path=b.path, authorize=allowed)
    with pytest.raises(PermissionError):
        receiver.receive('A', a.export_page())
    assert count(b) == 0


def test_wrong_receipt_never_acknowledges_settings(tmp_path):
    a = journal(tmp_path/'A.db')
    seed(a, 2)
    sender = PeerSettingsTransfer(path=a.path, authorize=lambda *a: True)
    transport = SimpleNamespace(settings_page=lambda p: {'head': 'wrong', 'next_offset': None, 'committed': True, 'status': 'in_sync'})
    with pytest.raises(ValueError):
        sender.send('B', transport)
    assert sender.outbox.next_delivery('B', reconnect=True) is not None


@pytest.mark.parametrize('completed', [False, True])
def test_restored_receiver_replays_missing_history(certificates, tmp_path, completed):
    a, b = journal(tmp_path/'A.db'), journal(tmp_path/'B.db')
    head = seed(a, 7)
    sender = PeerSettingsTransfer(path=a.path, authorize=lambda *a: True)
    receiver = PeerSettingsTransfer(path=b.path, authorize=lambda *a: True)
    endpoint = PeerDataEndpoint(history=None, epochs=None, amendments=None, settings=receiver)
    with server(certificates, endpoint) as url:
        transport = client(certificates, url)
        sender.send('B', transport, max_pages=10 if completed else 1, page_size=2)
        with sqlite3.connect(b.path) as conn:
            conn.execute('DELETE FROM peer_settings_state')
            conn.execute('DELETE FROM peer_settings_revisions')
        # A saved sender cursor/ACK must not conceal receiver data loss.
        receipt = sender.send('B', transport, reconnect=True, page_size=2)
        assert receipt['committed'] and receipt['head'] == head
        assert count(b) == 7


def test_inconsistent_final_status_cannot_acknowledge(tmp_path):
    a = journal(tmp_path/'A.db')
    head = seed(a, 1)
    sender = PeerSettingsTransfer(path=a.path, authorize=lambda *a: True)
    transport = SimpleNamespace(settings_page=lambda p: {
        'head': head, 'next_offset': None, 'committed': True, 'status': 'incomplete'})
    with pytest.raises(ValueError):
        sender.send('B', transport)
    assert sender.outbox.next_delivery('B', reconnect=True)
