"""Reviewed Web-derived detail revisions over immutable live/archive originals.

Only the selected cumulative counter and reviewed epoch are changed. Monthly
subject summaries exclude superseded cold rows and read revisions from the hot
database; opening a normal report never decodes old files for this workflow.
"""
from datetime import date, datetime, time, tzinfo
import hashlib
import json

from services.billing_web_amendment import BillingWebAmendmentService, _evidence
from services.billing_periods import billing_month_range
from services.peer_change_events import notify_local_change
from services.report_detail_archive import ReportDetailArchive, TABLES, _billing_day
from services.web_usage_projection import CounterIdentity, project_counter

FORMAT = 'komi.report.detail-amendment.v1'
MAX_BYTES = 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _key(kind, row):
    if kind == 'subject':
        from services.subject_history import _source_identity
        serial = _source_identity(row['source_json'], row['device_slot'])[2]
        counter = [f"counter.{row['subject_type']}.total.total", row['subject_type'], row['subject_id']]
    else:
        serial = row['device_serial_snapshot']
        counter = [row['canonical_field'], row['subject_type'] or None, row['subject_id'] or None]
    return row['device_slot'], serial, _json(counter), row['record_date']


def current_revisions(conn, kind, slots=None, *, start=None, end=None, include_rows=True, identity=None):
    filters, values = ['r.kind=?'], [kind]
    if slots:
        filters.append('r.device_slot IN (' + ','.join('?' for _ in slots) + ')')
        values.extend(slots)
    if start:
        filters.append('r.record_date>=?')
        values.append(start.isoformat())
    if end:
        filters.append('r.record_date<=?')
        values.append(end.isoformat())
    if identity:
        filters.extend(['r.serial=?', 'r.counter_key=?'])
        values.extend(identity)
    detail = 'r.row_json' if include_rows else 'NULL'
    rows = conn.execute(f'''SELECT r.device_slot,r.serial,r.counter_key,r.record_date,{detail},r.period_start,r.period_end
        FROM report_detail_revisions r WHERE ''' + ' AND '.join(filters) + ''' AND NOT EXISTS(
        SELECT 1 FROM report_detail_revisions n WHERE n.kind=r.kind AND n.device_slot=r.device_slot
        AND n.serial=r.serial AND n.counter_key=r.counter_key AND n.record_date=r.record_date AND n.id>r.id)''', values)
    return {tuple(row[:4]): {'row': json.loads(row[4]) if include_rows else None, 'period': list(row[5:])} for row in rows}


def without_superseded(conn, kind, documents):
    """Used only while explicitly constructing/rebuilding cold summaries."""
    if not documents:
        return []
    slots = sorted({item['row']['device_slot'] for item in documents})
    days = [date.fromisoformat(item['row']['record_date']) for item in documents]
    revisions = current_revisions(conn, kind, slots, start=min(days), end=max(days), include_rows=False)
    return [item for item in documents if _key(kind, item['row']) not in revisions]


def effective_documents(conn, kind, documents, slots=None, *, start=None, end=None, include_revisions=True):
    revisions = current_revisions(conn, kind, slots, start=start, end=end, include_rows=include_revisions)
    if not revisions:
        return documents
    return [item for item in documents if _key(kind, item['row']) not in revisions] + (list(revisions.values()) if include_revisions else [])




def iter_effective_rows(conn, kind, rows, columns, archived=(), slots=None, *,
                        start=None, end=None, include_revisions=True):
    """Read hot tuples directly while retaining archive/revision precedence.

    Most daily rows have no amendment. Converting every tuple to a dictionary
    and back costs substantially more than looking up the few revised days.
    """
    revisions = current_revisions(conn, kind, slots, start=start, end=end,
                                  include_rows=include_revisions)
    affected = {(key[0], key[3]) for key in revisions}
    slot_index, day_index = columns.index('device_slot'), columns.index('record_date')
    for row in rows:
        if ((row[slot_index], row[day_index]) in affected
                and _key(kind, dict(zip(columns, row))) in revisions):
            continue
        yield row, None
    for item in archived:
        if revisions and _key(kind, item['row']) in revisions:
            continue
        yield tuple(item['row'][key] for key in columns), item['period']
    if include_revisions:
        for item in revisions.values():
            yield tuple(item['row'][key] for key in columns), item['period']


def refresh_subject_summaries(conn, identities):
    from services.subject_history import SUBJECT_COLUMNS, subject_record_from_row, aggregate_subject_days
    for slot, serial, counter_key in identities:
        field, kind, subject_id = json.loads(counter_key)
        if kind not in {'user', 'track', 'account'} or field != f'counter.{kind}.total.total':
            continue
        revisions = current_revisions(conn, 'subject', [slot], identity=(serial, counter_key))
        if not revisions:
            continue
        periods = {row[0]: tuple(date.fromisoformat(v) for v in row[1:]) for row in conn.execute(
            'SELECT record_date,period_start,period_end FROM billing_ledger WHERE device_slot=? ORDER BY id', (slot,))}
        daily = []
        for item in revisions.values():
            row = item['row']
            record = subject_record_from_row([row[key] for key in SUBJECT_COLUMNS])
            period = periods.get(row['record_date']) or tuple(date.fromisoformat(v) for v in item['period'])
            daily.append((record, period))
        buckets = aggregate_subject_days(daily, _billing_day(conn))
        conn.execute('DELETE FROM report_revision_subject_periods WHERE device_slot=? AND device_identity=? AND subject_type=? AND subject_id=?',
                     (slot, 'serial:' + serial, kind, subject_id))
        for (start, end, slot, identity, kind, subject_id), bucket in buckets.items():
            bucket = {**bucket, 'warnings': sorted(bucket['warnings']), 'latest_date': bucket['latest_date'].isoformat()}
            conn.execute('INSERT INTO report_revision_subject_periods VALUES(?,?,?,?,?,?,?)',
                (slot, start.isoformat(), end.isoformat(), identity, kind, subject_id, _json(bucket)))


def refresh_period_summaries(conn, changed):
    identities = set()
    for item in changed:
        identities.update(conn.execute("SELECT DISTINCT device_slot,serial,counter_key FROM report_detail_revisions WHERE kind='subject' AND device_slot=? AND record_date=?",
                                       (item['device_slot'], item['record_date'])))
    refresh_subject_summaries(conn, identities)


def _records(conn, path, kind, slot, start, end):
    cursor = conn.execute(f'SELECT * FROM {TABLES[kind]} WHERE device_slot=? AND record_date BETWEEN ? AND ? LIMIT 100001',
                          (slot, start.isoformat(), end.isoformat()))
    columns = [c[0] for c in cursor.description]
    periods = {(r[0], r[1]): list(r[2:]) for r in conn.execute('SELECT device_slot,record_date,period_start,period_end FROM billing_ledger ORDER BY id')}
    records = []
    for row in cursor:
        row = dict(zip(columns, row))
        period = periods.get((slot, row['record_date'])) or [v.isoformat() for v in billing_month_range(date.fromisoformat(row['record_date']), _billing_day(conn))]
        records.append({'row': row, 'period': period})
    if len(records) > 100000:
        raise ValueError('รายละเอียดมากเกินไป กรุณาเลือกช่วงสั้นลง')
    size = sum(len(_json(item).encode()) for item in records)
    archive_count = conn.execute('SELECT COUNT(*) FROM report_detail_archives WHERE kind=? AND first_day<=? AND last_day>=?',
                                  (kind, end.isoformat(), start.isoformat())).fetchone()[0]
    if archive_count > 32:
        raise ValueError('Archive มากเกินไป กรุณาเลือกช่วงสั้นลง')
    for item in ReportDetailArchive(path).details(conn, kind, [slot], start=start, end=end):
        size += len(_json(item).encode())
        if size > 64 * 1024 * 1024 or len(records) >= 100000:
            raise ValueError('รายละเอียดมากเกินไป กรุณาเลือกช่วงสั้นลง')
        records.append(item)
    return effective_documents(conn, kind, records, [slot], start=start, end=end)


def _portable(item):
    row = {k: v for k, v in item['row'].items() if k not in {'id', 'created_at', 'updated_at'}}
    # Compare meaning, not whitespace of serialized source metadata.
    for key in row:
        if key.endswith('_json'):
            row[key] = json.loads(row[key])
    return {'row': row, 'period': list(item['period'])}


def preview(conn, path, slot, epoch_id, start, end, zone, counter, today):
    if (type(start) is not date or type(end) is not date or not 0 <= (end-start).days <= 92
            or end >= today or not isinstance(zone, tzinfo) or not isinstance(counter, CounterIdentity)):
        raise ValueError('เลือกตัวนับและวันที่ปิดแล้วไม่เกิน 93 วัน')
    epoch, events = _evidence(conn, path, slot, epoch_id, start, end, zone)
    serial = epoch['document']['baseline_event']['payload']['serial']
    identity = [counter.field, counter.subject_type, counter.subject_id]
    matches = [[c for c in e['payload']['reading']['counters'] if
        [c['canonical_field'], c['subject_type'], c['subject_id']] == identity] for e in events]
    if any(len(items) != 1 or items[0]['confidence'] != 'verified' for items in matches):
        raise ValueError('ทุกผล Web ต้องมีตัวนับที่ยืนยันแล้วเพียงหนึ่งค่า')
    if len({item[0]['source_path'] for item in matches}) != 1:
        raise ValueError('Source Path เปลี่ยนในช่วงนี้ ต้องตรวจแยกก่อน')
    if counter.subject_type and (not counter.subject_id or counter.subject_id.startswith('name:')):
        raise ValueError('ต้องมีรหัสผู้ใช้/บัญชีที่แน่นอน')
    projection = project_counter(events, slot=slot, serial=serial, epoch_id=epoch_id, counter=counter,
        calendar_timezone=zone, billing_day=_billing_day(conn), reviewed_epoch=epoch)
    if projection.issues or any(i.holds or i.amount.denominator != 1 for i in projection.intervals) or len(projection.points) < 2:
        raise ValueError('หลักฐานขัดแย้งหรือข้ามฐาน/รอบบิล ต้องตรวจแยกก่อน')
    key = _json(identity)
    kinds = ['raw']
    if counter.subject_type in {'user', 'track', 'account'} and counter.field == f'counter.{counter.subject_type}.total.total':
        kinds.append('subject')
    before = {}
    for kind in kinds:
        selected = [item for item in _records(conn, path, kind, slot, start, end)
                    if _key(kind, item['row'])[:3] == (slot, serial, key)]
        if len({_key(kind, item['row']) for item in selected}) != len(selected):
            raise ValueError('มีรายละเอียดตัวนับซ้ำในวันเดียว ต้องตรวจแยกก่อน')
        before[kind] = sorted((_portable(item) for item in selected), key=lambda i: i['row']['record_date'])
        # A shorter selection cannot silently discard usage outside the proof.
        physical = [i['row'] for i in selected if i['row'].get('opening_value' if kind == 'raw' else 'opening_total') is not None]
        if physical:
            physical.sort(key=lambda r: r['record_date'])
            opening, closing = ('opening_value', 'closing_value') if kind == 'raw' else ('opening_total', 'closing_total')
            if physical[0][opening] < float(projection.points[0].value) or physical[-1][closing] > float(projection.points[-1].value):
                raise ValueError('หลักฐานต้น–ปลายไม่ครอบคลุมรายละเอียดเดิม กรุณาขยายช่วง')
    by_day, allocation = {}, {}
    for event, items in zip(events, matches):
        stamp = datetime.fromisoformat(event['payload']['observed_at']).astimezone(zone)
        if start <= stamp.date() <= end:
            by_day.setdefault(stamp.date().isoformat(), []).append((event, items[0]))
    for interval in projection.intervals:
        if not start <= interval.allocation_day <= end:
            if interval.amount:
                raise ValueError('วันลงยอดอยู่นอกช่วง กรุณาขยายช่วง')
            continue
        bucket = allocation.setdefault(interval.allocation_day.isoformat(), {'delta': 0, 'remarks': []})
        bucket['delta'] += int(interval.amount)
        if interval.remark:
            bucket['remarks'].append(interval.remark)
    periods = {r[0]: list(r[1:]) for r in conn.execute('SELECT record_date,period_start,period_end FROM billing_ledger WHERE device_slot=? ORDER BY id', (slot,))}
    original_periods = {}
    for items in before.values():
        for item in items:
            day = item['row']['record_date']
            if day in original_periods and original_periods[day] != item['period']:
                raise ValueError('รอบบิลรายละเอียดเดิมไม่ตรงกัน ต้องตรวจแยกก่อน')
            original_periods[day] = item['period']
    days = sorted(set(by_day) | set(allocation) | {i['row']['record_date'] for items in before.values() for i in items})
    after = {kind: [] for kind in kinds}
    previous = float(projection.points[0].value)
    for day in days:
        readings = by_day.get(day, [])
        meta = readings[-1][1] if readings else matches[-1][0]
        physical = [float(pair[1]['count']) for pair in readings]
        opening, closing = (previous, max(physical)) if physical else (None, None)
        if physical:
            previous = max(previous, closing)
        delta = allocation.get(day, {}).get('delta', 0)
        first = readings[0][0]['payload']['observed_at'] if readings else None
        last = readings[-1][0]['payload']['observed_at'] if readings else None
        audit = {'format': FORMAT, 'events': [e['id'] for e in events], 'epoch': epoch_id,
                 'remarks': list(dict.fromkeys(allocation.get(day, {}).get('remarks', []))),
                 'allocation_only': not bool(readings)}
        period = periods.get(day) or original_periods.get(day)
        if period is None:
            candidates = {tuple(p) for p in original_periods.values() if p[0] <= day <= p[1]}
            if len(candidates) > 1:
                raise ValueError('รอบบิลของวันจัดสรรขัดแย้ง ต้องตรวจแยกก่อน')
            period = list(next(iter(candidates))) if candidates else [v.isoformat() for v in billing_month_range(date.fromisoformat(day), _billing_day(conn))]
        common = {'device_slot': slot, 'record_date': day, 'subject_type': counter.subject_type or '',
                  'subject_id': counter.subject_id or '', 'subject_name': meta['subject_name'] or '',
                  'sample_count': len(readings), 'first_success': first, 'last_success': last, 'incomplete': 0}
        raw = {**common, 'canonical_field': counter.field, 'label': meta['label'], 'source_path': meta['source_path'],
            'opening_value': opening, 'closing_value': closing, 'delta_value': delta, 'reset_count': 0,
            'source_name': events[-1]['payload']['reading']['source'], 'device_name_snapshot': events[-1]['payload']['printer_name'],
            'device_serial_snapshot': serial, 'counter_review_json': 'null', 'counter_resolutions_json': _json([audit])}
        after['raw'].append({'row': raw, 'period': period})
        if 'subject' in kinds:
            subject = {**common, 'opening_total': opening, 'closing_total': closing, 'delta_total': delta,
                'reset_count': 0, 'missing_baseline': 0, 'warnings_json': '[]',
                'source_json': _json({'device_identity': {'serial': serial, 'name': events[-1]['payload']['printer_name']},
                                      'report_amendment': audit})}
            after['subject'].append({'row': subject, 'period': period})
    payload = {'format': FORMAT, 'scope': [slot, epoch_id, start.isoformat(), end.isoformat()], 'serial': serial,
        'counter': identity, 'calendar': {'name': str(zone), 'iana': getattr(zone, 'key', None),
            'offset_seconds': int(datetime.combine(start, time.min, zone).utcoffset().total_seconds())},
        'events': [e['id'] for e in events], 'before': before, 'after': after}
    revision = hashlib.sha256(_json(payload).encode()).hexdigest()
    changed = []
    for kind in kinds:
        old = {i['row']['record_date']: i['row'] for i in before[kind]}
        field = 'delta_value' if kind == 'raw' else 'delta_total'
        compared = [field, 'sample_count', 'first_success', 'last_success', 'subject_name', 'reset_count']
        compared += ['opening_value', 'closing_value', 'label'] if kind == 'raw' else ['opening_total', 'closing_total', 'missing_baseline']
        for item in after[kind]:
            row = item['row']
            original = old.get(row['record_date'], {})
            if not original or any(original.get(key) != row[key] for key in compared):
                changed.append({'kind': kind, 'day': row['record_date'], 'before': old.get(row['record_date'], {}).get(field), 'after': row[field]})
    return {'revision': revision, 'payload': payload, 'changed': changed}


def document_for(preview, actor, reason):
    payload = {**preview['payload'], 'actor': actor.strip(), 'reason': reason.strip()}
    document = {'id': hashlib.sha256(_json(payload).encode()).hexdigest(), 'payload': payload}
    validate(document)
    return document


def validate(document):
    if not isinstance(document, dict) or set(document) != {'id', 'payload'}:
        raise ValueError('Invalid detail amendment envelope')
    payload = document['payload']
    if not isinstance(payload, dict) or set(payload) != {'format', 'scope', 'serial', 'counter', 'calendar', 'events', 'before', 'after', 'actor', 'reason'} or payload['format'] != FORMAT:
        raise ValueError('Invalid detail amendment format')
    if any(not isinstance(payload[k], str) or not payload[k].strip() or len(payload[k]) > 1000 for k in ('actor', 'reason', 'serial')):
        raise ValueError('Invalid detail amendment review')
    encoded = _json(document)
    if len(encoded.encode()) > MAX_BYTES or hashlib.sha256(_json(payload).encode()).hexdigest() != document['id']:
        raise ValueError('Altered or oversized detail amendment')
    return encoded


def commit(conn, path, document):
    from services.billing_period_amendment import rebuild_archives
    payload = document['payload']
    results, now = [], datetime.now().astimezone().isoformat()
    for kind, items in payload['after'].items():
        for item in items:
            row = item['row']
            result = conn.execute('''INSERT INTO report_detail_revisions(amendment_id,kind,device_slot,serial,counter_key,
                record_date,row_json,period_start,period_end) VALUES(?,?,?,?,?,?,?,?,?)''',
                (document['id'], kind, row['device_slot'], payload['serial'], _json(payload['counter']),
                 row['record_date'], _json(row), *item['period'])).lastrowid
            results.append({'kind': 'detail', 'id': result, 'key': document['id']})
    # Rebuild only affected subject archives during this explicit confirmation.
    if 'subject' in payload['after']:
        archive = ReportDetailArchive(path)
        start, end = payload['scope'][2:4]
        files = conn.execute("SELECT id,relative_path,sha256 FROM report_detail_archives WHERE kind='subject' AND last_day>=? AND first_day<=?", (start, end)).fetchall()
        if len(files) > 32:
            raise ValueError('Archive มากเกินไป กรุณาเลือกช่วงสั้นลง')
        from services.report_detail_archive import _digest
        from contextlib import closing
        import sqlite3
        prepared, size = [], 0
        for archive_id, relative, digest in files:
            file = archive._file(relative)
            if _digest(file) != digest:
                raise ValueError('Report archive checksum mismatch')
            with closing(sqlite3.connect(file.as_uri() + '?mode=ro', uri=True)) as cold:
                items = []
                for item in archive._file_documents(cold):
                    size += len(_json(item).encode())
                    if size > 64 * 1024 * 1024:
                        raise ValueError('Archive ใหญ่เกินไป กรุณาเลือกช่วงสั้นลง')
                    items.append(item)
            prepared.append((archive_id, items))
        rebuild_archives(conn, prepared)
        refresh_subject_summaries(conn, {(payload['scope'][0], payload['serial'], _json(payload['counter']))})
    conn.execute('''INSERT INTO peer_billing_amendments(amendment_id,document_json,results_json,created_at)
        VALUES(?,?,?,?)''', (document['id'], _json(document), _json(results), now))
    reviewed = {k: v for k, v in payload.items() if k not in {'actor', 'reason'}}
    revision = hashlib.sha256(_json(reviewed).encode()).hexdigest()
    conn.execute('INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)',
                 ('report_detail_amendment', revision, _json({'id': document['id'], 'actor': payload['actor'], 'reason': payload['reason']}), now))
    return tuple(row['id'] for row in results)


class ReportDetailAmendment(BillingWebAmendmentService):
    def preview(self, slot, epoch_id, start, end, zone, counter):
        with self._connection() as conn:
            return preview(conn, self.path, slot, epoch_id, start, end, zone, counter, self.today())

    @notify_local_change
    def confirm(self, slot, epoch_id, start, end, zone, counter, *, expected_revision, actor, reason):
        with self._connection(write=True) as conn:
            saved = conn.execute("SELECT new_value FROM config_log WHERE config_key='report_detail_amendment' AND old_value=? ORDER BY id DESC LIMIT 1",
                                 (expected_revision,)).fetchone()
            if saved:
                receipt = json.loads(saved[0])
                queue = conn.execute('SELECT document_json,results_json FROM peer_billing_amendments WHERE amendment_id=?', (receipt['id'],)).fetchone()
                if queue:
                    original = json.loads(queue[0])['payload']
                    expected = [slot, epoch_id, start.isoformat(), end.isoformat()]
                    if (original['scope'] == expected and original['calendar']['name'] == str(zone)
                            and original['counter'] == [counter.field, counter.subject_type, counter.subject_id]
                            and (receipt['actor'], receipt['reason']) == (actor.strip(), reason.strip())):
                        from services.peer_billing_amendments import PeerBillingAmendments
                        results = json.loads(queue[1])
                        if all(PeerBillingAmendments._result_present(conn, row) for row in results):
                            return tuple(row['id'] for row in results)
                raise ValueError('คำขอยืนยันซ้ำไม่ตรงหรือฉบับแก้ไขเดิมไม่ครบ')
            current = preview(conn, self.path, slot, epoch_id, start, end, zone, counter, self.today())
            if current['revision'] != expected_revision:
                raise ValueError('หลักฐานหรือรายละเอียดเดิมเปลี่ยน กรุณาตรวจใหม่')
            if not current['changed']:
                raise ValueError('ไม่มีรายละเอียดที่ต้องแก้ไข')
            return commit(conn, self.path, document_for(current, actor, reason))
