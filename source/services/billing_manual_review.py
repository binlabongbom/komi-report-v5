"""Stale-safe review of closed-day manual amounts, preserving unsafe evidence."""
from datetime import date
import json

from database import _open
from services.billing_ledger import (_load_correction_source, _source_hash,
    _approve_held_entry, _replace_entry, _reverse_entry)
from services.peer_change_events import notify_local_change


def _preview(conn, ledger_id):
    source = _load_correction_source(conn, ledger_id)
    latest = conn.execute('SELECT MAX(id) FROM billing_ledger WHERE source_daily_record_id=?', (source[8],)).fetchone()[0]
    if latest != ledger_id or source[0] not in {'hold', 'posting', 'replacement'}:
        raise ValueError('Select the current hold or posting')
    if date.fromisoformat(source[5]) >= date.today():
        raise ValueError('Only a closed usage day can be corrected')
    evidence = conn.execute('SELECT * FROM daily_meter_records WHERE id=?', (source[8],)).fetchone()
    if evidence is None:
        raise ValueError('Original daily evidence is unavailable')
    return {'revision': _source_hash({'source': source, 'evidence': evidence, 'ledger': ledger_id}),
        'ledger_id': ledger_id, 'kind': source[0], 'slot': source[1], 'name': source[3], 'serial': source[4],
        'day': source[5], 'period': list(source[6:8]), 'gross': source[13], 'net': source[15],
        'hold_reason': source[19], 'delta': json.loads(source[10]), 'proof': json.loads(source[18])}


class BillingManualReview:
    def preview(self, ledger_id):
        with _open(commit=False) as conn:
            conn.execute('BEGIN')
            return _preview(conn, ledger_id)

    @notify_local_change
    def confirm(self, ledger_id, *, expected_revision, actor, reason, gross_cents, net_cents, reverse=False):
        if (not isinstance(actor, str) or not actor.strip() or len(actor) > 1000 or
                not isinstance(reason, str) or not reason.strip() or len(reason) > 1000 or type(reverse) is not bool):
            raise ValueError('A reviewer and reason are required')
        request = {'ledger_id': ledger_id, 'actor': actor.strip(), 'reason': reason.strip(),
                   'gross': gross_cents, 'net': net_cents, 'reverse': reverse}
        with _open() as conn:
            conn.execute('BEGIN IMMEDIATE')
            saved = conn.execute("SELECT new_value FROM config_log WHERE config_key='billing_manual_review' AND old_value=? ORDER BY id DESC LIMIT 1",
                                 (expected_revision,)).fetchone()
            if saved:
                value = json.loads(saved[0])
                if value['request'] != request or not conn.execute('SELECT 1 FROM billing_ledger WHERE id=? AND idempotency_key=?',
                                                                  (value['id'], value['key'])).fetchone():
                    raise ValueError('Manual correction retry differs or its history is unavailable')
                return value['id']
            preview = _preview(conn, ledger_id)
            if preview['revision'] != expected_revision:
                raise ValueError('Accounting or evidence changed after preview')
            if reverse:
                if preview['kind'] == 'hold' or (gross_cents, net_cents) != (0, 0):
                    raise ValueError('Only an existing posting can be reversed to zero')
                result = _reverse_entry(conn, ledger_id, actor=actor, reason=reason)
            else:
                function = _approve_held_entry if preview['kind'] == 'hold' else _replace_entry
                result = function(conn, ledger_id, actor=actor, reason=reason, gross_cents=gross_cents, net_cents=net_cents)
            key, stamp = conn.execute('SELECT idempotency_key,created_at FROM billing_ledger WHERE id=?', (result,)).fetchone()
            conn.execute('INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)',
                ('billing_manual_review', expected_revision, json.dumps({'request': request, 'id': result, 'key': key}, sort_keys=True), stamp))
            return result
