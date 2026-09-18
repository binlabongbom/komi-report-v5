from contextlib import closing
from copy import deepcopy
from datetime import date
import json
import sqlite3

import pytest

from database import get_db_path
from services.peer_billing_amendments import PeerBillingAmendments
from test_billing_web_amendment import setup, confirm, event


def peer(path=None, authorize=lambda member, document: True):
    return PeerBillingAmendments(path=path, authorize=authorize, today=lambda: date(2026, 9, 25))


def fixture_ledger_edit(conn, sql):
    # Construct a different pre-existing test database, then restore its guards.
    triggers = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='billing_ledger'").fetchall()
    for name, _ in triggers:
        conn.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
    conn.execute(sql)
    for _, statement in triggers:
        conn.execute(statement)


def clone(tmp_path, name):
    target = tmp_path / (name + '.sqlite3')
    with closing(sqlite3.connect(get_db_path())) as src, closing(sqlite3.connect(target)) as dest:
        src.backup(dest)
    # Local database row IDs are deliberately different across computers.
    with closing(sqlite3.connect(target)) as conn, conn:
        conn.execute('UPDATE daily_meter_records SET id=id+100')
        fixture_ledger_edit(conn, 'UPDATE billing_ledger SET id=id+1000,source_daily_record_id=source_daily_record_id+100')
    return target


def counts(path):
    with closing(sqlite3.connect(path)) as conn:
        return [conn.execute('SELECT * FROM ' + table).fetchall() for table in
                ('daily_meter_records', 'billing_ledger', 'peer_billing_amendments', 'peer_billing_deliveries')]


def test_acknowledged_amendment_missing_after_restore_is_sent_again(tmp_path):
    from types import SimpleNamespace
    service, args, _ = setup()
    b_path = clone(tmp_path, 'B')
    backup = clone(tmp_path, 'B-before-amendment')
    confirm(service, args, service.preview(*args))
    a, b = peer(), peer(b_path)
    transport = SimpleNamespace(amendment=lambda d: b.receive('A', d),
                                amendment_contains=lambda d: b.contains('A', d))
    assert a.deliver_one('B', transport)
    assert a.pending('B') is None
    with closing(sqlite3.connect(backup)) as old, closing(sqlite3.connect(b_path)) as dest:
        old.backup(dest)
    audit = a.recheck('B', transport)
    assert not audit['more'] and a.pending('B') is not None
    assert a.deliver_one('B', transport)
    before = counts(b_path)
    a.recheck('B', transport)
    assert a.pending('B') is None and counts(b_path) == before


def test_three_databases_deliver_retry_and_forward_once(tmp_path):
    service, args, _ = setup()
    b, c = peer(clone(tmp_path, 'B')), peer(clone(tmp_path, 'C'))
    confirm(service, args, service.preview(*args))
    a = peer()
    document = a.pending('B')
    receipt = b.receive('A', document)
    before = counts(b.service.path)
    assert b.receive('A', document) == receipt
    assert counts(b.service.path) == before
    assert b.pending('A') is None  # No echo to the sender.
    assert b.pending('C') == document
    b.acknowledge('C', c.receive('B', document))
    a.acknowledge('B', receipt)
    assert a.pending('B') is None
    for p in (a, b, c):
        with p.service._connection() as conn:
            assert conn.execute('SELECT SUM(net_cents) FROM billing_ledger').fetchone()[0] == 30100
            assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    assert a.pending('C') == document  # Another member needs its own receipt.


def test_queue_is_atomic_with_ledger(tmp_path):
    service, args, _ = setup()
    before = counts(get_db_path())
    with service._connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON peer_billing_amendments BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):
        confirm(service, args, service.preview(*args))
    assert counts(get_db_path()) == before


def test_receive_rollback_on_revocation_and_receipt_failure(tmp_path):
    service, args, _ = setup()
    target = clone(tmp_path, 'B')
    confirm(service, args, service.preview(*args))
    document = peer().pending('B')
    calls = []
    def revoke(member, document):
        calls.append(member)
        return len(calls) == 1
    b = peer(target, revoke)
    before = counts(target)
    with pytest.raises(PermissionError):
        b.receive('A', document)
    assert counts(target) == before
    b = peer(target)
    with b.service._connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON peer_billing_deliveries BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):
        b.receive('A', document)
    assert counts(target) == before


def test_different_accounting_and_missing_evidence_do_not_overwrite(tmp_path):
    service, args, _ = setup()
    target = clone(tmp_path, 'B')
    confirm(service, args, service.preview(*args))
    document = peer().pending('B')
    b = peer(target)
    with b.service._connection(write=True) as conn:
        fixture_ledger_edit(conn, 'UPDATE billing_ledger SET net_cents=net_cents-1')
    before = counts(target)
    with pytest.raises(ValueError, match='differs'):
        b.receive('A', document)
    assert counts(target) == before
    with b.service._connection(write=True) as conn:
        fixture_ledger_edit(conn, 'UPDATE billing_ledger SET net_cents=net_cents+1')
        conn.execute('DELETE FROM slot_meter_assignments WHERE event_id=?', (document['payload']['events'][-1],))
    before = counts(target)
    with pytest.raises(ValueError):
        b.receive('A', document)
    assert counts(target) == before


def test_bad_document_and_unverified_member_are_rejected(tmp_path):
    service, args, _ = setup()
    b = peer(clone(tmp_path, 'B'))
    confirm(service, args, service.preview(*args))
    document = peer().pending('B')
    changed = deepcopy(document)
    changed['payload']['after'][0]['net_cents'] += 100
    before = counts(b.service.path)
    with pytest.raises(ValueError):
        b.receive('A', changed)
    with pytest.raises(PermissionError):
        peer(b.service.path, lambda *args: 'yes').receive('A', document)
    assert counts(b.service.path) == before


def test_lost_reply_restart_and_retry_delay(tmp_path):
    service, args, _ = setup()
    b = peer(clone(tmp_path, 'B'))
    confirm(service, args, service.preview(*args))
    a = peer()
    class Transport:
        drop = True
        def amendment(self, document):
            receipt = b.receive('A', document)
            if self.drop:
                raise TimeoutError('lost reply after commit')
            return receipt
    transport = Transport()
    with pytest.raises(TimeoutError):
        a.deliver_one('B', transport)
    before = counts(b.service.path)
    assert a.pending('B') is None  # Backoff, still pending after restart.
    transport.drop = False
    assert peer().deliver_one('B', transport, reconnect=True)
    assert counts(b.service.path) == before
    assert peer().pending('B', reconnect=True) is None
