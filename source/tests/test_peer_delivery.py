import sqlite3

import pytest

import database
from services.peer_delivery import PeerSyncSession, PeerWebDelivery
from services.peer_settings_transfer import PeerSettingsTransfer
from services.peer_https import PeerDataEndpoint
from services.slot_epoch_exchange import SlotEpochExchange
from services.web_catchup import WebCatchup
from services.web_observations import WebObservationStore
from test_peer_https import certificates, server, client
from test_peer_settings_transfer import journal
from test_peer_settings_pages import seed, count
from test_peer_billing_amendments import clone, peer
from test_billing_web_amendment import setup, confirm


def session(path, transport):
    return PeerSyncSession(member='B', transport=transport, path=path,
        authorize_session=lambda *a: True, authorize_event=lambda *a: True,
        authorize_epoch=lambda *a: True, authorize_settings=lambda *a: True,
        authorize_amendment=lambda *a: True)


def endpoint(path):
    return PeerDataEndpoint(history=WebCatchup(authorize=lambda *a: True, path=path),
        epochs=SlotEpochExchange(authorize=lambda *a: True, path=path), amendments=peer(path),
        settings=PeerSettingsTransfer(authorize=lambda *a: True, path=path),
        web=PeerWebDelivery(authorize=lambda *a: True, path=path))


def test_runtime_session_delivers_all_queues_over_tls_without_duplicate_accounting(certificates, tmp_path):
    service, args, _ = setup()
    a = database.get_db_path()
    b = clone(tmp_path, 'B-accounting')
    # Simulate loss of the receiver's observation/epoch cache, keeping the
    # already issued daily accounting whose allocation will be amended.
    with sqlite3.connect(b) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        for table in ('slot_meter_maxima', 'slot_meter_assignments', 'slot_meter_epoch_state',
                      'slot_meter_heads', 'slot_meter_epoch_outbox', 'slot_meter_epochs',
                      'web_observation_outbox', 'web_observations'):
            conn.execute('DELETE FROM ' + table)
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    confirm(service, args, service.preview(*args))
    history = journal(a)
    seed(history, 7)
    with server(certificates, endpoint(b)) as url:
        sync = session(a, client(certificates, url))
        result = sync.run()
        assert result.status == 'complete', result
        assert count(journal(b)) == 7
        assert WebObservationStore(a).pending('B') == []
        assert peer(a).pending('B') is None
        with sqlite3.connect(b) as conn:
            before = conn.execute('SELECT COUNT(*),SUM(net_cents) FROM billing_ledger').fetchone()
        assert sync.run().sent == 0
        with sqlite3.connect(b) as conn:
            assert conn.execute('SELECT COUNT(*),SUM(net_cents) FROM billing_ledger').fetchone() == before
            assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_invalid_web_receipt_keeps_queue_but_other_work_can_finish(certificates, tmp_path):
    service, args, _ = setup()
    b = clone(tmp_path, 'B')
    confirm(service, args, service.preview(*args))
    receiver = endpoint(b)
    def bad_receipt(member, operation, data):
        result = receiver(member, operation, data)
        return {'event_ids': [], 'committed': True} if operation == 'web.receive' else result
    with server(certificates, bad_receipt) as url:
        result = session(database.get_db_path(), client(certificates, url)).run()
    assert result.status == 'pending' and not result.more_work
    assert result.errors == (('web', 'invalid_data'),)
    assert WebObservationStore().pending('B')
    assert peer().pending('B') is None


def test_revocation_rolls_back_whole_web_delivery(tmp_path):
    from test_web_observations import record, store
    event = record(store(), 1)
    target = tmp_path/'target.db'
    journal(target)
    checks = []
    def allow(*a):
        checks.append(a)
        return len(checks) < 3
    receiver = PeerWebDelivery(authorize=allow, path=target)
    with pytest.raises(PermissionError):
        receiver.receive('A', [event])
    assert WebObservationStore(target).page()['events'] == []


def test_local_wakeup_occurs_after_commit_and_never_after_rollback():
    from services.peer_change_events import subscribe
    from test_shared_settings import configured
    calls = []
    class Observer:
        def wake(self):
            with sqlite3.connect(database.get_db_path()) as conn:
                calls.append(conn.execute("SELECT value FROM settings WHERE key='billing_day'").fetchone()[0])
    observer = Observer()
    unsubscribe = subscribe(database.get_db_path(), observer.wake)
    try:
        service = configured()
        preview = service.preview({'billing_day': 15}, reason='fixture')
        service.commit(preview)
        assert calls[-1] == '15'
        before = list(calls)
        with pytest.raises(ValueError):
            service.commit(preview)
        assert calls == before
    finally:
        unsubscribe()


def test_agent_runtime_wakes_delivery_on_local_change_and_stops_cleanly(certificates, tmp_path):
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    from services.peer_history_runtime import PeerHistoryRuntime
    from services.peer_change_events import committed
    from test_peer_history_runtime import until
    app = QApplication.instance() or QApplication([])
    a, b = database.get_db_path(), tmp_path/'B.db'
    journal(b)
    runtime = PeerHistoryRuntime()
    with server(certificates, endpoint(b)) as url:
        sync = session(a, client(certificates, url))
        try:
            runtime.attach(sync)
            runtime.start()
            until(lambda: not runtime.busy)
            seed(journal(a), 2)
            committed(a)
            until(lambda: count(journal(b)) == 2 and not runtime.busy)
            assert runtime.snapshot()[0]['status'] == 'complete'
            runtime.stop(wait=True)
            seed(journal(a), 1)
            committed(a)
            QTest.qWait(30)
            assert count(journal(b)) == 2
        finally:
            runtime.stop(wait=True)
