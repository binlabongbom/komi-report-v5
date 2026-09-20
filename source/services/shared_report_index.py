"""Compact, rebuildable daily index of reviewed Web observations.

The journal remains the source of actual reads. This index keeps real first,
maximum and last points per counter/day, not a second copy of every user reading.
It is updated in the observation transaction and never changes issued reports.
"""
from contextlib import closing
from datetime import datetime
import json
import sqlite3

from services.slot_meter_continuity import counter_key, counter_values, _fraction, _number, _encoded_number


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def epoch_calendar(conn, epoch):
    """Use the root's recorded UTC offset on every PC, never its local timezone.

    This is the fixed-offset calendar recorded by the current epoch format.
    A future calendar-policy change must be reviewed separately from PC settings.
    """
    root, seen = epoch, set()
    while root['document']['parent'] is not None:
        parent = root['document']['parent']
        if parent in seen:
            raise ValueError('Cyclic meter epoch')
        seen.add(parent)
        row = conn.execute('SELECT document_json FROM slot_meter_epochs WHERE id=?', (parent,)).fetchone()
        if row is None:
            raise ValueError('Missing reviewed parent epoch')
        root = json.loads(row[0])
    return datetime.fromisoformat(root['document']['baseline_event']['payload']['observed_at']).tzinfo


def _point_order(point):
    return point['at'], _number(point['value']), point['id']


def _neighbor_issues(conn, epoch_id, event, incoming, archive_reader=None):
    """Retain a decrease hidden between daily extrema, even on reordered import.

    Only the two adjacent original results are decoded. Missing/archived neighbor
    detail cannot serve as an implicit financial safety attestation.
    """
    issues = {}
    p = event['payload']
    for operator, order in (('<', 'DESC'), ('>', 'ASC')):
        row = conn.execute(f'''SELECT w.document_json,w.observed_at,w.event_id,w.archive_id FROM web_observations w
            JOIN slot_meter_assignments a ON a.event_id=w.event_id
            WHERE a.epoch_id=? AND (julianday(w.observed_at),w.event_id) {operator} (julianday(?),?)
            ORDER BY julianday(w.observed_at) {order},w.event_id {order} LIMIT 1''',
            (epoch_id, p['observed_at'], event['id'])).fetchone()
        if row is None:
            continue
        raw = row[0]
        if not raw and archive_reader is not None:
            raw = archive_reader(row[2], row[0], row[3])
        if not raw:
            # A missing archived payload is not a counter-missing observation.
            # Report loading marks incomplete indexing from the durable journal.
            continue
        values = counter_values(json.loads(raw))
        same_time = datetime.fromisoformat(row[1]) == datetime.fromisoformat(p['observed_at'])
        for key, counter in incoming.items():
            value = _fraction(counter['count'])
            flags = issues.setdefault(key, set())
            if key not in values:
                flags.add('selected_counter_missing_on_observed_days')
            elif same_time and values[key] != value:
                flags.add('same_time_counter_conflict')
            elif (operator == '<' and values[key] > value) or (operator == '>' and values[key] < value):
                flags.add('lower_counter_or_clock_conflict')
    return issues


def index_event(conn, epoch, event, *, archive_reader=None):
    """Called with an existing, validated epoch assignment in a write transaction."""
    if not conn.in_transaction:
        raise ValueError('Indexing requires the observation transaction')
    epoch_id, event_id = epoch['id'], event['id']
    if conn.execute('SELECT 1 FROM shared_report_events WHERE epoch_id=? AND event_id=?',
                    (epoch_id, event_id)).fetchone():
        return False
    p = event['payload']
    zone = epoch_calendar(conn, epoch)
    stamp = datetime.fromisoformat(p['observed_at']).astimezone(zone)
    day, at = stamp.date().isoformat(), stamp.isoformat(timespec='microseconds')
    baseline = epoch['document']['baseline_event']['payload']
    before_baseline = stamp < datetime.fromisoformat(baseline['observed_at'])
    unique = {}
    for counter in p['reading']['counters']:
        if counter['canonical_field'].startswith('counter.'):
            key = counter_key(counter)
            # validate_event/counter_values already reject conflicting duplicates.
            # Choose display metadata deterministically when a source repeats a key.
            if key not in unique or _json(counter) > _json(unique[key]):
                unique[key] = counter
    from services.reconciliation import reconcile_web_counters
    device_values = {c['canonical_field']: c['count'] for c in unique.values() if c['subject_type'] is None}
    billing_safe = reconcile_web_counters(device_values).billing_safe
    neighbor_flags = _neighbor_issues(conn, epoch_id, event, unique, archive_reader)
    for table, period in (('shared_report_days', day), ('shared_report_months', day[:7])):
        row = conn.execute(f'SELECT document_json FROM {table} WHERE epoch_id=? AND record_date=?',
                           (epoch_id, period)).fetchone()
        data = json.loads(row[0]) if row else {'count': 0, 'counters': {}, 'schemas': [], 'issues': [], 'days': []}
        data['count'] += 1
        data['days'] = sorted(set(data['days']) | {day})
        data['schemas'] = sorted(set(data['schemas']) | {p['reading']['schema_version']})
        if before_baseline:
            data['issues'] = sorted(set(data['issues']) | {'evidence_before_reviewed_baseline'})
        data['billing_safe'] = data.get('billing_safe', True) and billing_safe
        _merge_counters(data, p, event_id, at, unique, neighbor_flags)
        device_data = dict(data, counters={k: v for k, v in data['counters'].items() if json.loads(k)[1] is None})
        conn.execute(f'''INSERT INTO {table} VALUES(?,?,?,?)
            ON CONFLICT(epoch_id,record_date) DO UPDATE SET document_json=excluded.document_json,device_json=excluded.device_json''',
            (epoch_id, period, _json(data), _json(device_data)))
    conn.execute('INSERT INTO shared_report_events VALUES(?,?)', (epoch_id, event_id))
    return True


def _merge_counters(data, p, event_id, at, unique, neighbor_flags):
    for key, counter in unique.items():
        point = {'at': at, 'value': _encoded_number(_fraction(counter['count'])), 'id': event_id}
        metadata = {k: counter[k] for k in ('label', 'source_path', 'subject_name')}
        metadata.update(printer_name=p['printer_name'], host=p['reading']['host'])
        item = data['counters'].get(key)
        if item is None:
            item = {'first': point, 'last': point, 'high': point, 'count': 0,
                    'metadata': metadata, 'issues': []}
            data['counters'][key] = item
        flags = set(item['issues']) | neighbor_flags.get(key, set())
        if counter['confidence'] != 'verified':
            flags.add('unverified_counter')
        for selected in ('first', 'last', 'high'):
            old = item[selected]
            if old['at'] == at and old['value'] != point['value']:
                flags.add('same_time_counter_conflict')
        old_high = item['high']
        if ((_number(point['value']) < _number(old_high['value']) and at >= old_high['at'])
                or (_number(point['value']) > _number(old_high['value']) and at <= old_high['at'])):
            flags.add('lower_counter_or_clock_conflict')
        # At the same instant the highest counter is the display point. Conflicts
        # remain marked, rather than selecting an arbitrary arrival's value.
        if at < item['first']['at'] or (at == item['first']['at'] and _point_order(point) > _point_order(item['first'])):
            item['first'] = point
        if _point_order(point) >= _point_order(item['last']):
            item['last'], item['metadata'] = point, metadata
        if (_number(point['value']), at, event_id) > (_number(old_high['value']), old_high['at'], old_high['id']):
            item['high'] = point
        item['count'] += 1
        item['issues'] = sorted(flags)


def backfill_batch(path, *, limit=32, include_archives=False):
    """Upgrade retained evidence off the UI thread; old archive files are opt-in."""
    if type(limit) is not int or not 1 <= limit <= 128:
        raise ValueError('Invalid report index batch')
    from services.web_observations import WebObservationStore, validate_event
    from services.slot_epoch_store import SlotEpochStore
    with closing(sqlite3.connect(path, timeout=30)) as conn, conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        archive_filter = '' if include_archives else 'AND w.archive_id IS NULL'
        rows = conn.execute(f'''SELECT a.epoch_id,w.event_id,w.document_json,w.archive_id
            FROM slot_meter_assignments a JOIN web_observations w ON w.event_id=a.event_id
            LEFT JOIN shared_report_events s ON s.epoch_id=a.epoch_id AND s.event_id=a.event_id
            WHERE s.event_id IS NULL {archive_filter} ORDER BY w.sequence,a.epoch_id LIMIT ?''', (limit,)).fetchall()
        store = WebObservationStore(path)
        for epoch_id, event_id, raw, archive_id in rows:
            event = json.loads(store._document(event_id, raw, archive_id))
            validate_event(event)
            if event['id'] != event_id:
                raise ValueError('Journal index identity mismatch')
            index_event(conn, SlotEpochStore._epoch(conn, epoch_id), event,
                        archive_reader=store._document if include_archives else None)
        return len(rows)


def index_archived_reports(path, cancelled):
    """Explicit user action; stop only between atomic batches and retain progress."""
    indexed = 0
    while not cancelled.is_set():
        count = backfill_batch(path, include_archives=True)
        indexed += count
        if not count:
            break
    return {'indexed': indexed, 'cancelled': cancelled.is_set()}
