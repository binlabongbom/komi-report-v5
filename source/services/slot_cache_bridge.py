"""Resume open local caches from an explicitly adopted, serial-bound epoch.

Epoch decisions are durable; caches replay the decision idempotently on their
next observation. Closed reports/archives are never changed by this bridge.
The mixed/reset day retains its hold and original segment for later review.
"""
from copy import deepcopy
from datetime import datetime
import json

from database import _open
from services.slot_epoch_store import SlotEpochStore


def _at(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def approved_baseline(conn, slot, reading, stamp):
    head = SlotEpochStore._head(conn, slot)
    if not head:
        return None
    epoch = SlotEpochStore._epoch(conn, head)
    doc = epoch['document']
    if doc['operation'] == 'initial':
        return None
    p = doc['baseline_event']['payload']
    device = conn.execute('SELECT serial,host,enabled FROM devices WHERE slot=?', (slot,)).fetchone()
    issues = conn.execute('SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?', (head,)).fetchone()
    if (device != (p['serial'], reading.host, 1) or p['reading']['host'] != reading.host
            or reading.schema_version != p['reading']['schema_version'] or not issues or json.loads(issues[0])
            or stamp < _at(p['observed_at'])):
        return None
    return epoch


def bridge_device_state(slot, state, reading, stamp):
    with _open(commit=False) as conn:
        epoch = approved_baseline(conn, slot, reading, stamp)
        if not epoch or state.get('slot_epoch') == epoch['id']:
            return
        if conn.execute('SELECT 1 FROM daily_meter_records WHERE device_slot=? AND record_date=?',
                        (slot, stamp.date().isoformat())).fetchone():
            return
        # Never reinterpret an old hold or overwrite a more recent observation.
        p = epoch['document']['baseline_event']['payload']
        if state.get('last_success') and state.get('sample_count', 0) and _at(state['last_success']) > _at(p['observed_at']):
            return
        previous = conn.execute('SELECT source_json FROM daily_meter_records WHERE device_slot=? AND record_date<? ORDER BY record_date DESC LIMIT 1',
                                (slot, stamp.date().isoformat())).fetchone()
        if previous and json.loads(previous[0]).get('slot_epoch') == epoch['id']:
            state['slot_epoch'] = epoch['id']
            return
    baseline = {c['canonical_field']: c['count'] for c in p['reading']['counters'] if c['subject_type'] is None}
    current = {c.canonical_field: c.count for c in reading.counters if c.subject_type is None}
    if not baseline or set(baseline) != set(current) or any(c.get('confidence') != 'verified' for c in p['reading']['counters'] if c['subject_type'] is None):
        return
    preserved = {key: deepcopy(state.get(key)) for key in ('device_identity', 'opening', 'latest', 'delta',
        'first_success', 'last_success', 'source', 'resets', 'counter_review', 'counter_resolutions')}
    state.setdefault('device_segments', []).append(preserved)
    audit = {'id': epoch['id'], 'epoch_id': epoch['id'], 'baseline_event': epoch['document']['baseline_event']['id'],
             'actor': epoch['document']['actor'], 'reason': epoch['document']['reason'],
             'observed_at': p['observed_at'], 'preserved_delta': deepcopy(state.get('delta', {}))}
    for key, issue in state.get('counter_review', {}).items():
        if key not in baseline:
            continue
        state.setdefault('counter_resolutions', []).append({**audit, 'key': key, 'review_at': issue['at'],
                                                           'baseline': baseline[key]})
    state['counter_review'] = {k: v for k, v in state.get('counter_review', {}).items() if k not in baseline}
    state['resets'] = []  # Original reset evidence remains in the saved segment.
    state.setdefault('slot_replacements', []).append(audit)
    state['opening'] = dict(baseline)
    state['latest'] = dict(baseline)
    state['last_success'] = p['observed_at']
    state['first_success'] = state.get('first_success') or p['observed_at']
    state['device_identity'] = {'name': p['printer_name'], 'serial': p['serial'], 'host': reading.host}
    state['source'] = {'schema_version': reading.schema_version}
    state['slot_epoch'] = epoch['id']
    state['unsafe_reconciliation_seen'] = True
    state.pop('replacement_candidate', None)


def bridge_raw_counter(conn, epoch, slot, day, counter):
    """Resume an existing open exact-counter row in the caller's transaction."""
    if epoch is None:
        return
    from services.raw_counter_history import _subject_identity
    p = epoch['document']['baseline_event']['payload']
    kind, subject_id, _ = _subject_identity(counter)
    match = [c for c in p['reading']['counters'] if c['canonical_field'] == counter.canonical_field
             and c['source_path'] == counter.source_path and (c['subject_type'] or '') == kind
             and (c['subject_id'] or '') == subject_id and c['confidence'] == 'verified']
    if len(match) != 1:
        return
    row = conn.execute('''SELECT id,last_success,delta_value,counter_resolutions_json FROM daily_raw_counter_records
        WHERE device_slot=? AND record_date=? AND device_serial_snapshot=? AND canonical_field=?
        AND source_path=? AND subject_type=? AND subject_id=?''',
        (slot, day, p['serial'], counter.canonical_field, counter.source_path, kind, subject_id)).fetchone()
    if row is None or not row[1] or _at(row[1]) > _at(p['observed_at']):
        return
    resolutions = json.loads(row[3])
    if any(r.get('epoch_id') == epoch['id'] for r in resolutions):
        return
    resolutions.append({'epoch_id': epoch['id'], 'baseline_event': epoch['document']['baseline_event']['id'],
        'baseline': match[0]['count'], 'observed_at': p['observed_at'], 'preserved_delta': row[2],
        'actor': epoch['document']['actor'], 'reason': epoch['document']['reason']})
    conn.execute('''UPDATE daily_raw_counter_records SET closing_value=?,last_success=?,
        counter_review_json='null',counter_resolutions_json=? WHERE id=?''',
        (match[0]['count'], p['observed_at'], json.dumps(resolutions, ensure_ascii=False, sort_keys=True), row[0]))


def raw_baseline_after_gap(epoch, counter, previous_at):
    if epoch is None:
        return None
    p = epoch['document']['baseline_event']['payload']
    if previous_at and _at(previous_at) > _at(p['observed_at']):
        return None
    matches = [c for c in p['reading']['counters'] if
        (c['canonical_field'], c['source_path'], c['subject_type'], c['subject_id'], c['confidence']) ==
        (counter.canonical_field, counter.source_path, counter.subject_type, counter.subject_id, 'verified')]
    if len(matches) != 1:
        return None
    return {'epoch_id': epoch['id'], 'baseline_event': epoch['document']['baseline_event']['id'],
        'baseline': matches[0]['count'], 'observed_at': p['observed_at'],
        'actor': epoch['document']['actor'], 'reason': epoch['document']['reason']}


def bridge_subject_state(slot, state, reading, stamp):
    from services.shared_web_read import SharedWebRead
    from services.subject_history import extract_subject_totals
    with _open(commit=False) as conn:
        epoch = approved_baseline(conn, slot, reading, stamp)
        if not epoch or state.get('slot_epoch') == epoch['id']:
            return
        if conn.execute('SELECT 1 FROM daily_subject_records WHERE device_slot=? AND record_date=?',
                        (slot, stamp.date().isoformat())).fetchone():
            return
        p = epoch['document']['baseline_event']['payload']
        if state.get('last_success') and _at(state['last_success']) > _at(p['observed_at']):
            return
        previous = conn.execute('SELECT source_json FROM daily_subject_records WHERE device_slot=? AND record_date<? ORDER BY record_date DESC LIMIT 1',
                                (slot, stamp.date().isoformat())).fetchone()
        if previous and json.loads(previous[0]).get('slot_epoch') == epoch['id']:
            state['slot_epoch'] = epoch['id']
            return
    totals = extract_subject_totals(SharedWebRead._reading(epoch['document']['baseline_event']))
    if (not totals or any(c.warnings or c.subject_id.startswith('name:') for c in totals)
            or any(c['confidence'] != 'verified' for c in p['reading']['counters'] if c['subject_type'])
            or not set(state['subjects']) <= {c.identity_key for c in totals}):
        return
    identity = {'name': p['printer_name'], 'serial': p['serial'], 'host': reading.host}
    for counter in totals:
        item = state['subjects'].get(counter.identity_key)
        old = deepcopy({k: v for k, v in item.items() if k != 'counter_resolutions'}) if item else None
        if item is None:
            item = {'subject_type': counter.subject_type, 'subject_id': counter.subject_id,
                'subject_name': counter.subject_name, 'delta_total': 0.0, 'reset_count': 0,
                'sample_count': 0, 'first_success': p['observed_at'], 'source': p['reading']['source'],
                'canonical_field': counter.canonical_field, 'source_path': counter.source_path,
                'missing_baseline': False, 'warnings': []}
            state['subjects'][counter.identity_key] = item
        item.setdefault('counter_resolutions', []).append({'epoch_id': epoch['id'],
            'baseline_event': epoch['document']['baseline_event']['id'], 'baseline': counter.total_counter,
            'observed_at': p['observed_at'], 'actor': epoch['document']['actor'], 'reason': epoch['document']['reason'],
            'previous_segment': old, 'previous_identity': deepcopy(state['device_identity'])})
        item['opening_total'] = item['latest_total'] = counter.total_counter
        item['last_success'] = p['observed_at']
        item['resets'] = []
        item.pop('counter_review', None)
        item['warnings'] = sorted(set(item.get('warnings', [])) | {'reviewed_slot_baseline'})
    state['device_identity'] = identity
    state['slot_epoch'] = epoch['id']
    state['last_success'] = p['observed_at']
