"""Portable, atomic corrections against matching frozen accounting evidence.

Local row numbers never identify another computer's entries. A recipient must
already have the exact source and preceding decision; differences stay queued.
Manual amounts remain explicitly manual, including approvals of held records.
"""
from datetime import date
import hashlib
import json

from services.billing_ledger import (FORMULA_VERSION, MANUAL_ADJUSTMENT_VERSION,
    REVERSAL_VERSION, _load_correction_source, _manual_adjustment_attestation,
    _manual_waste_basis_points, _reversal_attestation)
from services.billing_periods import billing_month_range

FORMAT = 'komi.billing.correction-transfer.v1'
MAX_BYTES = 1024 * 1024
MAX_OPERATIONS = 2000


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def snapshot(conn, ledger_id):
    source = _load_correction_source(conn, ledger_id)
    formula = conn.execute('SELECT formula_version FROM billing_ledger WHERE id=?', (ledger_id,)).fetchone()[0]
    # Bind subsequent edits to a shared preceding decision when one exists.
    parent = conn.execute('''SELECT a.amendment_id FROM peer_billing_amendments a,
        json_each(a.results_json) r WHERE json_extract(r.value,'$.id')=?
        AND COALESCE(json_extract(r.value,'$.kind'),'ledger')='ledger'
        ORDER BY a.sequence DESC LIMIT 1''', (ledger_id,)).fetchone()
    cursor = conn.execute('''SELECT record_date,opening_json,closing_json,delta_json,category_json,source_json,
        first_success,last_success,sample_count,error_count,incomplete FROM daily_meter_records WHERE id=?''', (source[8],))
    daily = list(cursor.fetchone())
    for index in range(1, 6):
        daily[index] = json.loads(daily[index])
    if daily[5].get('allocation_only') is True and isinstance(daily[5].get('web_allocation'), dict):
        # These two fields identify a local preview/commit, not physical proof.
        daily[5]['web_allocation'].pop('revision', None)
        daily[5]['web_allocation'].pop('created_at', None)
    return {'kind': source[0], 'slot': source[1], 'serial': source[4], 'day': source[5],
        'period': list(source[6:8]), 'source_hash': hashlib.sha256(_json(daily).encode()).hexdigest(),
        'delta': json.loads(source[10]), 'categories': json.loads(source[11]),
        'prices': json.loads(source[12]), 'gross': source[13], 'discount': source[14],
        'net': source[15], 'billing_day': source[16], 'currency': source[17],
        'hold_reason': source[19], 'formula': formula, 'parent': parent[0] if parent else None}


def _operation(conn, target, result, action):
    before = snapshot(conn, target)
    row = _load_correction_source(conn, result)
    after = {'gross': row[13], 'net': row[15]}
    if action == 'reprice':
        audit = json.loads(row[18])['repricing']
        after.update(prices=json.loads(row[12]), discount=row[14], billing_day=row[16],
            period=list(row[6:8]), price_effective_date=audit['price_effective_date'],
            apply_current_discount=audit['apply_current_discount'],
            apply_current_period=audit['apply_current_period'])
    return {'action': action, 'before': before, 'after': after}


def enqueue_corrections(conn, changes, *, actor, reason, created_at):
    """Queue all changes from one reviewed action in its existing transaction."""
    if not conn.in_transaction:
        raise ValueError('Corrections and their delivery queue must commit together')
    payload = {'format': FORMAT, 'actor': actor.strip(), 'reason': reason.strip(), 'created_at': created_at,
               'operations': [_operation(conn, target, result, action) for target, result, action in changes]}
    document = {'id': hashlib.sha256(_json(payload).encode()).hexdigest(), 'payload': payload}
    validate(document)
    results = []
    for target, result, action in changes:
        ids = [result]
        if action in {'replace', 'reprice'}:
            ids.insert(0, conn.execute('SELECT replaces_ledger_id FROM billing_ledger WHERE id=?', (result,)).fetchone()[0])
        for key in ids:
            row = conn.execute('SELECT id,idempotency_key FROM billing_ledger WHERE id=?', (key,)).fetchone()
            results.append({'id': row[0], 'key': row[1]})
    conn.execute('''INSERT INTO peer_billing_amendments(amendment_id,document_json,results_json,created_at)
        VALUES(?,?,?,?)''', (document['id'], _json(document), _json(results), created_at))
    return document['id']


def _money(value, *, negative=False):
    if type(value) is not int or not (-(2**63 - 1) if negative else 0) <= value <= 2**63 - 1:
        raise ValueError('Invalid correction amount')
    return value


def validate(document):
    if not isinstance(document, dict) or set(document) != {'id', 'payload'}:
        raise ValueError('Invalid correction envelope')
    payload = document['payload']
    if (not isinstance(payload, dict) or set(payload) != {'format', 'actor', 'reason', 'created_at', 'operations'}
            or payload['format'] != FORMAT):
        raise ValueError('Invalid correction format')
    encoded = _json(document)
    if len(encoded.encode()) > MAX_BYTES or hashlib.sha256(_json(payload).encode()).hexdigest() != document['id']:
        raise ValueError('Altered or oversized correction')
    if (any(not isinstance(payload[k], str) or not payload[k].strip() or len(payload[k]) > 1000
            for k in ('actor', 'reason', 'created_at')) or not isinstance(payload['operations'], list)
            or not 1 <= len(payload['operations']) <= MAX_OPERATIONS):
        raise ValueError('Invalid correction review')
    seen = set()
    for operation in payload['operations']:
        if not isinstance(operation, dict) or set(operation) != {'action', 'before', 'after'}:
            raise ValueError('Invalid correction operation')
        before, after, action = operation['before'], operation['after'], operation['action']
        if action not in {'reverse', 'replace', 'approve_hold', 'reprice'} or not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError('Unsupported correction operation')
        if (type(before.get('slot')) is not int or before['slot'] not in range(3)
                or not isinstance(before.get('serial'), str) or len(before['serial']) > 256):
            raise ValueError('Invalid correction printer scope')
        day = date.fromisoformat(before['day'])
        identity = (before['slot'], before['serial'], day)
        if identity in seen:
            raise ValueError('Duplicate correction source')
        seen.add(identity)
        expected = {'gross', 'net'}
        if action == 'reprice':
            expected |= {'prices', 'discount', 'billing_day', 'period', 'price_effective_date',
                         'apply_current_discount', 'apply_current_period'}
        if set(after) != expected:
            raise ValueError('Invalid correction result')
        _money(after['gross'], negative=action == 'reverse')
        _money(after['net'], negative=action == 'reverse')
        if action == 'reverse':
            if (after['gross'], after['net']) != (-before['gross'], -before['net']):
                raise ValueError('A reversal must exactly compensate the source')
        elif after['net'] > after['gross']:
            raise ValueError('Invalid correction discount')
        if action == 'reprice':
            if (type(after['discount']) is not int or not 0 <= after['discount'] <= 10000
                    or type(after['billing_day']) is not int or not 1 <= after['billing_day'] <= 31
                    or any(type(after[k]) is not bool for k in ('apply_current_discount', 'apply_current_period'))
                    or not isinstance(after['prices'], dict)):
                raise ValueError('Invalid corrected policy')
            for value in after['prices'].values():
                _money(value)
            if date.fromisoformat(after['price_effective_date']) > day:
                raise ValueError('The corrected price is not effective on this day')
            if not after['apply_current_discount'] and after['discount'] != before['discount']:
                raise ValueError('Unreviewed discount change')
            if not after['apply_current_period'] and (after['billing_day'], after['period']) != (before['billing_day'], before['period']):
                raise ValueError('Unreviewed period change')
            if after['apply_current_period'] and after['period'] != [v.isoformat() for v in billing_month_range(day, after['billing_day'])]:
                raise ValueError('Invalid corrected period')
            if any(type(v) is not int or v < 0 for v in before['delta'].values()):
                raise ValueError('Invalid frozen counter evidence')
            gross = sum(value * after['prices'][before['categories'][key]] for key, value in before['delta'].items())
            net = (gross * (10000 - after['discount']) + 5000) // 10000
            if (gross, net) != (after['gross'], after['net']):
                raise ValueError('Corrected amounts do not match the frozen formula')
    return encoded


def _resolve(conn, before, action, reason):
    from services.billing_web_amendment import _validate_source_hash
    if not before['serial']:
        raise ValueError('A verified printer serial is required to share a correction')
    rows = conn.execute('''SELECT id FROM billing_ledger b WHERE device_slot=? AND device_serial_snapshot=?
        AND record_date=?''',
        (before['slot'], before['serial'], before['day'])).fetchall()
    matches = [row[0] for row in rows if snapshot(conn, row[0]) == before]
    if len(matches) != 1:
        raise ValueError('Local accounting differs; correction needs review')
    target = matches[0]
    source = _load_correction_source(conn, target)
    latest = conn.execute('SELECT id,entry_kind,replaces_ledger_id,hold_reason FROM billing_ledger WHERE source_daily_record_id=? ORDER BY id DESC LIMIT 1',
                          (source[8],)).fetchone()
    if latest[0] != target and not (action == 'replace' and latest[1:] == ('reversal', target, reason)):
        raise ValueError('Local accounting has already been superseded')
    _validate_source_hash(conn, source[8], source[9])
    return target, source


def apply(conn, document):
    """Called by the authenticated receiver inside its receipt transaction."""
    from services.billing_period_amendment import prepare_archives, rebuild_archives
    from services.billing_repricing import REPRICE_VERSION
    from services.billing_web_amendment import WEB_AMENDMENT_VERSION
    validate(document)
    payload = document['payload']
    resolved, periods = [], []
    for operation in payload['operations']:
        target, source = _resolve(conn, operation['before'], operation['action'], payload['reason'])
        action, after = operation['action'], operation['after']
        if source[0] != ('hold' if action == 'approve_hold' else 'posting') and not (action != 'approve_hold' and source[0] == 'replacement'):
            raise ValueError('Correction source kind differs')
        if action == 'reprice':
            proof = json.loads(source[18])
            if (proof.get('billing_safe') is not True or operation['before']['formula'] not in
                    {FORMULA_VERSION, REPRICE_VERSION, WEB_AMENDMENT_VERSION}):
                raise ValueError('Only verified automatic evidence can be repriced')
            periods.append({'device_slot': source[1], 'record_date': source[5],
                'old_period_start': source[6], 'old_period_end': source[7],
                'period_start': after['period'][0], 'period_end': after['period'][1]})
        resolved.append((target, source, operation))
    archives, _revision = prepare_archives(conn, periods)
    results = []
    reason, now = payload['reason'], payload['created_at']
    def insert(source, *, kind, parent, gross, net, discount, formula, attestation, prices=None, period=None, billing_day=None):
        key = f"peer-correction:{document['id']}:{len(results)}"
        cursor = conn.execute('''INSERT INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,
            device_serial_snapshot,record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,
            replaces_ledger_id,delta_json,category_json,price_cents_json,gross_cents,waste_basis_points,net_cents,
            billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (kind, *source[1:6], *(period or source[6:8]), *source[8:10], key, parent, *source[10:12],
             source[12] if prices is None else _json(prices), gross, discount, net,
             source[16] if billing_day is None else billing_day, source[17], formula, reason, _json(attestation), now))
        result = int(cursor.lastrowid)
        results.append({'id': result, 'key': key})
        return result
    for target, source, operation in resolved:
        action, after = operation['action'], operation['after']
        parent = target
        if action != 'approve_hold':
            existing = conn.execute("SELECT id,idempotency_key FROM billing_ledger WHERE entry_kind='reversal' AND replaces_ledger_id=?", (target,)).fetchone()
            if existing:
                parent = existing[0]
                results.append({'id': parent, 'key': existing[1]})
            else:
                parent = insert(source, kind='reversal', parent=target, gross=-source[13], net=-source[15],
                    discount=source[14], formula=REVERSAL_VERSION,
                    attestation=_reversal_attestation(source[18], target_ledger_id=target, gross_cents=source[13],
                        net_cents=source[15], reason=reason, created_at=now))
        if action == 'reverse':
            continue
        if action in {'replace', 'approve_hold'}:
            discount = _manual_waste_basis_points(after['gross'], after['net'])
            proof = _manual_adjustment_attestation(source[18], action='replace_entry' if action == 'replace' else action,
                target_ledger_id=target, gross_cents=after['gross'], net_cents=after['net'], waste_basis_points=discount,
                reason=reason, created_at=now, original_hold_reason=source[19] if action == 'approve_hold' else None)
            proof['manual_adjustment']['actor'] = payload['actor']
            insert(source, kind='replacement', parent=parent, gross=after['gross'], net=after['net'],
                   discount=discount, formula=MANUAL_ADJUSTMENT_VERSION, attestation=proof)
        else:
            audit = {'actor': payload['actor'], 'reason': reason, 'target_ledger_id': target,
                'preview_revision': document['id'], 'created_at': now, 'source_delta_used_for_amounts': True,
                'preserved_discount_and_period': not (after['apply_current_discount'] or after['apply_current_period']),
                'preserved_period': not after['apply_current_period'], 'old_billing_day': source[16],
                'old_period': list(source[6:8]), 'old_discount_basis_points': source[14],
                'discount_basis_points': after['discount'], **{k: after[k] for k in
                    ('price_effective_date', 'apply_current_discount', 'apply_current_period', 'billing_day', 'period')}}
            insert(source, kind='replacement', parent=parent, gross=after['gross'], net=after['net'],
                discount=after['discount'], formula=REPRICE_VERSION, prices=after['prices'], period=after['period'],
                billing_day=after['billing_day'], attestation={'billing_safe': True, 'calculation_mode': 'dated_price_recalculation',
                    'original_attestation': json.loads(source[18]), 'repricing': audit})
    rebuild_archives(conn, archives)
    from services.report_detail_amendment import refresh_period_summaries
    refresh_period_summaries(conn, periods)
    conn.execute('''INSERT INTO peer_billing_amendments(amendment_id,document_json,results_json,created_at)
        VALUES(?,?,?,?)''', (document['id'], _json(document), _json(results), now))
    return results
