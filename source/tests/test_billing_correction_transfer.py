from contextlib import closing
from copy import deepcopy
from datetime import date
import hashlib
import json
import sqlite3

import pytest

from database import _open, get_db_path, set_cfg
from services.billing_ledger import approve_held_entry, post_daily_record, replace_entry, reverse_entry
from services.billing_repricing import BillingRepricingService
from services.billing_repricing_batch import BatchRepricingService
from services.billing_correction_transfer import _json
from services.pricing import PricingRepository, PriceList
from test_billing_ledger import _daily
from test_billing_repricing import posting
from test_peer_billing_amendments import peer, clone, counts, fixture_ledger_edit


def corrected(service, target):
    return service.confirm(target, expected_revision=service.preview(target)['revision'],
                           actor='A', reason='Reviewed dated price')


def test_reprice_three_databases_different_ids_retry_forward_and_chain(tmp_path):
    target = posting()
    b, c = peer(clone(tmp_path, 'B')), peer(clone(tmp_path, 'C'))
    a, service = peer(), BillingRepricingService()
    first = corrected(service, target)
    document = a.pending('B')
    receipt = b.receive('A', document)
    before = counts(b.service.path)
    assert b.receive('A', document) == receipt and counts(b.service.path) == before
    assert b.pending('A') is None
    forwarded = b.pending('C')
    assert forwarded == document
    c.receive('B', forwarded)
    a.acknowledge('B', receipt)
    assert a.pending('B') is None
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=3))
    corrected(service, first)
    second = a.pending('B')
    assert second['payload']['operations'][0]['before']['parent'] == document['id']
    # Frozen reviewed policy is used even if B has since received another setting.
    b.receive('A', second)
    for database, expected in ((get_db_path(), 900), (b.service.path, 900), (c.service.path, 600)):
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute('SELECT SUM(gross_cents) FROM billing_ledger').fetchone()[0] == expected
            assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('action', ['reverse', 'replace', 'approve_hold'])
def test_manual_decisions_keep_original_evidence_and_manual_status(tmp_path, action):
    target = posting()
    if action == 'approve_hold':
        with _open() as conn:
            record = _daily(conn, {}, record_date='2026-07-17')
        target = post_daily_record(record)
    b = peer(clone(tmp_path, 'B'))
    if action == 'reverse':
        reverse_entry(target, reason='Reviewed original evidence')
    else:
        function = replace_entry if action == 'replace' else approve_held_entry
        function(target, gross_cents=200, net_cents=190, reason='Reviewed original evidence')
    document = peer().pending('B')
    b.receive('A', document)
    with b.service._connection() as conn:
        row = conn.execute('SELECT entry_kind,attestation_json FROM billing_ledger ORDER BY id DESC LIMIT 1').fetchone()
        proof = json.loads(row[1])
        assert proof['billing_safe'] is False
        if action != 'reverse':
            assert proof['manual_adjustment']['amount_origin'] == 'operator_entered'
        assert conn.execute('SELECT COUNT(*) FROM daily_meter_records').fetchone()[0] == (2 if action == 'approve_hold' else 1)
    encoded = _json(document)
    assert 'target_ledger_id' not in encoded and 'source_daily_record_id' not in encoded


def test_batch_period_discount_correction_commits_all_or_none(tmp_path):
    posting()
    with _open() as conn:
        record = _daily(conn, {'reconciliation': {'billing_safe': True}}, record_date='2026-07-17')
    post_daily_record(record)
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=4))
    set_cfg('waste_paper_pct', '10')
    set_cfg('billing_day', '20')
    b = peer(clone(tmp_path, 'B'))
    service = BatchRepricingService()
    args = (date(2026, 7, 16), date(2026, 7, 17), [0])
    options = dict(apply_current_discount=True, apply_current_period=True)
    preview = service.preview(*args, **options)
    service.confirm(*args, **options, expected_revision=preview['revision'], actor='A', reason='Reviewed whole range')
    document = peer().pending('B')
    assert len(document['payload']['operations']) == 2
    before = counts(b.service.path)
    with b.service._connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_second BEFORE INSERT ON billing_ledger WHEN NEW.record_date='2026-07-17' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):
        b.receive('A', document)
    assert counts(b.service.path) == before
    with b.service._connection(write=True) as conn:
        conn.execute('DROP TRIGGER fail_second')
    b.receive('A', document)
    with b.service._connection() as conn:
        assert conn.execute('SELECT SUM(net_cents) FROM billing_ledger').fetchone()[0] == 2160
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger WHERE entry_kind='replacement' AND billing_day=20 AND waste_basis_points=1000").fetchone()[0] == 2


def test_conflict_revocation_corrupt_source_and_invalid_formula_leave_no_receipt(tmp_path):
    target = posting()
    b = peer(clone(tmp_path, 'B'))
    corrected(BillingRepricingService(), target)
    document = peer().pending('B')
    before = counts(b.service.path)
    calls = []
    def revoked(*args):
        calls.append(1)
        return len(calls) == 1
    with pytest.raises(PermissionError):
        peer(b.service.path, revoked).receive('A', document)
    assert counts(b.service.path) == before
    altered = deepcopy(document)
    altered['payload']['operations'][0]['after']['gross'] += 1
    altered['id'] = hashlib.sha256(_json(altered['payload']).encode()).hexdigest()
    with pytest.raises(ValueError, match='formula'):
        b.receive('A', altered)
    assert counts(b.service.path) == before
    with b.service._connection(write=True) as conn:
        conn.execute("UPDATE daily_meter_records SET sample_count=99")
    changed = counts(b.service.path)
    with pytest.raises(ValueError):
        b.receive('A', document)
    assert counts(b.service.path) == changed


def test_queue_failure_rolls_back_local_price_and_manual_corrections():
    target = posting()
    before = counts(get_db_path())
    with _open() as conn:
        conn.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON peer_billing_amendments BEGIN SELECT RAISE(ABORT,'fixture'); END")
    for action in (lambda: corrected(BillingRepricingService(), target),
                   lambda: replace_entry(target, gross_cents=200, net_cents=190, reason='reviewed')):
        with pytest.raises(sqlite3.DatabaseError):
            action()
        assert counts(get_db_path()) == before


def test_standalone_reversal_then_replacement_does_not_reverse_twice(tmp_path):
    target = posting()
    b = peer(clone(tmp_path, 'B'))
    a = peer()
    reverse_entry(target, reason='Reviewed')
    a.acknowledge('B', b.receive('A', a.pending('B')))
    replace_entry(target, gross_cents=200, net_cents=190, reason='Reviewed')
    b.receive('A', a.pending('B'))
    with b.service._connection() as conn:
        assert conn.execute('SELECT SUM(net_cents) FROM billing_ledger').fetchone()[0] == 190
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger WHERE entry_kind='reversal'").fetchone()[0] == 1


def test_superseded_posting_cannot_get_a_second_manual_replacement():
    target = posting()
    corrected(BillingRepricingService(), target)
    before = counts(get_db_path())
    with pytest.raises(ValueError, match='superseded'):
        replace_entry(target, gross_cents=500, net_cents=500, reason='Reviewed dated price')
    assert counts(get_db_path()) == before


def test_reprice_after_web_allocation_uses_portable_source_evidence(tmp_path):
    from test_billing_web_amendment import setup, confirm
    service, args, _ = setup()
    b = peer(clone(tmp_path, 'B'))
    results = confirm(service, args, service.preview(*args))
    a = peer()
    a.acknowledge('B', b.receive('A', a.pending('B')))
    PricingRepository().set_prices(0, date(2026, 9, 1), PriceList(a4_color=2))
    reprice = BillingRepricingService()
    corrected(reprice, results[0])
    b.receive('A', a.pending('B'))
    with b.service._connection() as conn:
        assert conn.execute('SELECT SUM(net_cents) FROM billing_ledger').fetchone()[0] == 60200


def test_detail_revision_ids_do_not_become_financial_parents(tmp_path):
    from test_report_detail_amendment import setup, confirm
    service, args, _ = setup()
    target = posting()
    b = peer(clone(tmp_path, 'B'))
    confirm(service, args)
    a = peer()
    a.acknowledge('B', b.receive('A', a.pending('B')))
    # Detail revisions and ledger entries have independent integer sequences.
    # A matching local number is not an earlier accounting decision.
    corrected(BillingRepricingService(), target)
    document = a.pending('B')
    assert document['payload']['operations'][0]['before']['parent'] is None
    b.receive('A', document)
    with b.service._connection() as conn:
        assert conn.execute('SELECT SUM(gross_cents) FROM billing_ledger').fetchone()[0] == 600
