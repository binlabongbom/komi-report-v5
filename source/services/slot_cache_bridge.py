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


def _setup_initial(epoch):
    doc = epoch['document']
    return doc['operation'] == 'initial' and doc['actor'] in {'setup_wizard', 'system:pending-setup'}


def _normalized_reading(event):
    from services.parser_mapping import apply_parser_mapping_overrides
    from services.shared_web_read import SharedWebRead
    return apply_parser_mapping_overrides(SharedWebRead._reading(event), event['payload']['serial'])


def approved_baseline(conn, slot, reading, stamp, *, normalized=False):
    head = SlotEpochStore._head(conn, slot)
    if not head:
        return None
    epoch = SlotEpochStore._epoch(conn, head)
    doc = epoch['document']
    if doc['operation'] == 'initial' and not _setup_initial(epoch):
        return None
    p = doc['baseline_event']['payload']
    schema = p['reading']['schema_version']
    if normalized and _setup_initial(epoch) and schema != reading.schema_version:
        schema = _normalized_reading(doc['baseline_event']).schema_version
    device = conn.execute('SELECT serial,host,enabled FROM devices WHERE slot=?', (slot,)).fetchone()
    issues = conn.execute('SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?', (head,)).fetchone()
    if (device != (p['serial'], reading.host, 1) or p['reading']['host'] != reading.host
            or reading.schema_version != schema or not issues or json.loads(issues[0])
            or stamp < _at(p['observed_at'])):
        return None
    return epoch


def _initial_day_event(conn, epoch, stamp):
    """Carry the last accepted prior-day reading, never reuse day-one opening.

    Setup's committed event remains the opening until there is an explicitly
    assigned prior-day observation. Unbound legacy observations are excluded.
    """
    start = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute('''SELECT w.event_id FROM web_observations w
        JOIN slot_meter_assignments a ON a.event_id=w.event_id
        WHERE a.epoch_id=? AND julianday(w.observed_at)<julianday(?)
        ORDER BY julianday(w.observed_at) DESC,w.sequence DESC LIMIT 1''',
        (epoch['id'], start.isoformat())).fetchone()
    return (SlotEpochStore()._event(conn, row[0]) if row
            else epoch['document']['baseline_event'])


def _fresh_initial_state(state, payload):
    """Only seed an untouched local cache, including an SNMP-only heartbeat."""
    if state.get('sample_count', 0) or any(state.get(key) for key in (
        'counter_review', 'resets', 'counter_resolutions', 'device_segments',
        'slot_replacements', 'cache_corruption', 'identity_conflict',
        'identity_baseline_mismatch', 'unsafe_reconciliation_seen', 'slot_epoch',
    )) or any(state.get('delta', {}).values()):
        return False
    identity = state.get('device_identity', {})
    return ((not identity.get('serial') or identity['serial'] == payload['serial'])
            and (not identity.get('host') or identity['host'] == payload['reading']['host']))


def _initial_audit(epoch, event):
    return {'epoch_id': epoch['id'], 'baseline_event': epoch['document']['baseline_event']['id'],
            'opening_event': event['id'], 'observed_at': event['payload']['observed_at']}


def _seed_initial_device(conn, epoch, slot, state, reading, stamp):
    original = epoch['document']['baseline_event']['payload']
    if not _fresh_initial_state(state, original) or conn.execute(
        'SELECT 1 FROM daily_meter_records WHERE device_slot=? LIMIT 1', (slot,)
    ).fetchone():
        return
    event = _initial_day_event(conn, epoch, stamp)
    baseline_reading = _normalized_reading(event)
    baseline = {c.canonical_field: c.count for c in baseline_reading.counters if c.subject_type is None}
    current = {c.canonical_field: c.count for c in reading.counters if c.subject_type is None}
    if (baseline_reading.schema_version != reading.schema_version or not baseline
            or set(baseline) != set(current) or any(c.confidence != 'verified'
                for c in baseline_reading.counters if c.subject_type is None)):
        return
    at = event['payload']['observed_at']
    state['opening'] = dict(baseline)
    state['latest'] = dict(baseline)
    state['delta'] = {key: 0 for key in baseline}
    state['first_success'] = state['last_success'] = at
    state['source'] = {'schema_version': baseline_reading.schema_version}
    state['slot_epoch'] = epoch['id']
    state['initial_setup_baseline'] = _initial_audit(epoch, event)


def bridge_device_state(slot, state, reading, stamp):
    with _open(commit=False) as conn:
        epoch = approved_baseline(conn, slot, reading, stamp, normalized=True)
        if not epoch or state.get('slot_epoch') == epoch['id']:
            return
        if _setup_initial(epoch):
            _seed_initial_device(conn, epoch, slot, state, reading, stamp)
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
    if epoch is None or _setup_initial(epoch):
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
    if _setup_initial(epoch) and previous_at:
        return None  # Existing Raw history owns its opening, even after restart.
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
        if _setup_initial(epoch):
            _seed_initial_subjects(conn, epoch, slot, state, stamp)
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


def _seed_initial_subjects(conn, epoch, slot, state, stamp):
    from services.shared_web_read import SharedWebRead
    from services.subject_history import extract_subject_totals
    original = epoch['document']['baseline_event']['payload']
    if (not _fresh_initial_state(state, original) or state.get('subjects')
            or conn.execute('SELECT 1 FROM daily_subject_records WHERE device_slot=? LIMIT 1',
                            (slot,)).fetchone()):
        return
    event = _initial_day_event(conn, epoch, stamp)
    p = event['payload']
    baseline_reading = SharedWebRead._reading(event)
    totals = extract_subject_totals(baseline_reading)
    if (not totals or any(c.warnings or c.subject_id.startswith('name:') for c in totals)
            or any(c.confidence != 'verified' for c in baseline_reading.counters if c.subject_type)):
        return
    for counter in totals:
        state['subjects'][counter.identity_key] = {
            'subject_type': counter.subject_type, 'subject_id': counter.subject_id,
            'subject_name': counter.subject_name, 'opening_total': counter.total_counter,
            'latest_total': counter.total_counter, 'delta_total': 0.0,
            'reset_count': 0, 'resets': [], 'missing_baseline': False, 'sample_count': 0,
            'first_success': p['observed_at'], 'last_success': p['observed_at'],
            'canonical_field': counter.canonical_field, 'source_path': counter.source_path,
            'source': baseline_reading.source, 'warnings': [],
            'initial_setup_baseline': _initial_audit(epoch, event),
        }
    state['slot_epoch'] = epoch['id']
    state['last_success'] = p['observed_at']
