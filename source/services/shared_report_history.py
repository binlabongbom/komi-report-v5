"""Read shared journal usage through the ordinary reporting boundary.

Results are derived usage, not issued invoices. Immutable ledger/detail revisions
take priority; overlapping closed days are never summed with this projection.
"""
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
import hashlib
import json
from bisect import bisect_left, bisect_right

from services.billing_periods import effective_billing_day
from services.slot_meter_continuity import _number
from services.web_usage_projection import CounterPoint, project_points


SHARED_REMARK = 'ข้อมูลจากหลักฐาน Web ที่ใช้ร่วมกัน'


@dataclass(frozen=True)
class SharedCounterDay:
    slot: int
    serial: str
    epoch_id: str
    day: date
    field: str
    subject_type: str | None
    subject_id: str | None
    metadata: dict
    opening: Fraction | None
    closing: Fraction | None
    delta: Fraction
    count: int
    first_at: str | None
    last_at: str | None
    evidence_ids: tuple[str, ...]
    remarks: tuple[str, ...]
    issues: tuple[str, ...]
    covered_days: tuple[date, ...]
    billing_safe: bool
    estimated: bool = False


def load_shared_counter_days(conn, slots, *, start=None, end=None, kind='all', graph=False):
    """Read compact summaries only; normal reports never unpack archived Web JSON.

    Follow accepted heads and their parents. An orphan competing epoch cannot
    introduce a second usage stream. Every counter is reduced independently;
    names, paths and arrival times are not counter identities.
    """
    from database import report_read_checkpoint, report_read_components
    report_read_checkpoint()
    cache = report_read_components()
    key = ('shared-counter-days', conn.execute('PRAGMA database_list').fetchone()[2], tuple(sorted(slots)), start, end, kind, graph)
    if cache is not None and key in cache:
        return cache[key]
    result = _load_shared_counter_days(conn, slots, start=start, end=end, kind=kind, graph=graph)
    if cache is not None:
        cache[key] = result
    return result


def _load_shared_counter_days(conn, slots, *, start, end, kind, graph):
    from database import report_read_checkpoint
    if not slots:
        return ()
    placeholders = ','.join('?' for _ in slots)
    epochs = conn.execute(f'''WITH RECURSIVE chain(id) AS (
        SELECT epoch_id FROM slot_meter_heads WHERE device_slot IN ({placeholders})
        UNION SELECT e.parent_id FROM slot_meter_epochs e JOIN chain c ON c.id=e.id
        WHERE e.parent_id IS NOT NULL)
        SELECT e.id,e.device_slot,e.document_json,s.issues_json FROM chain c
        JOIN slot_meter_epochs e ON e.id=c.id JOIN slot_meter_epoch_state s ON s.epoch_id=e.id''', list(slots)).fetchall()
    cfg = conn.execute("SELECT value FROM settings WHERE key='billing_day'").fetchone()
    billing_day = effective_billing_day(cfg[0] if cfg else None)
    prices = {}
    result = []
    for epoch_id, slot, raw_epoch, raw_issues in epochs:
        report_read_checkpoint()
        epoch = json.loads(raw_epoch)
        anchor = epoch['document']['baseline_event']['payload']
        serial = anchor['serial']
        column = 'device_json' if kind == 'device' else 'document_json'
        clauses, parameters = ['epoch_id=?'], [epoch_id]
        if start is not None:
            clauses.append('record_date>=?')
            parameters.append(start.strftime('%Y-%m') + '-01')
        if end is not None:
            clauses.append('record_date<=?')
            parameters.append(end.strftime('%Y-%m') + '-31')
        summary_rows = [(d, raw, 0) for d, raw in conn.execute(
            f'SELECT record_date,{column} FROM shared_report_days WHERE {" AND ".join(clauses)} ORDER BY record_date', parameters)]
        # Whole months outside the selected window provide previous maxima and
        # the next actual point. No daily detail for those months is decoded.
        for bound, operator, position in ((start, '<', -1), (end, '>', 1)):
            if bound is not None:
                summary_rows.extend((d, raw, position) for d, raw in conn.execute(
                    f'SELECT record_date,{column} FROM shared_report_months WHERE epoch_id=? AND record_date {operator} ? ORDER BY record_date',
                    (epoch_id, bound.strftime('%Y-%m'))))
        summary_rows.sort(key=lambda row: row[0])
        if not summary_rows:
            continue
        web_days, counters, schemas = set(), {}, set()
        billing_safe = True
        digest = hashlib.sha256()
        epoch_issues = set(json.loads(raw_issues))
        from services.shared_report_index import epoch_calendar
        offset = int(epoch_calendar(conn, epoch).utcoffset(None).total_seconds())
        unindexed_days = conn.execute('''SELECT DISTINCT date(w.observed_at,?)
            FROM slot_meter_assignments a JOIN web_observations w ON w.event_id=a.event_id
            LEFT JOIN shared_report_events s ON s.epoch_id=a.epoch_id AND s.event_id=a.event_id
            WHERE a.epoch_id=? AND s.event_id IS NULL''', (f'{offset} seconds', epoch_id)).fetchall()
        if unindexed_days:
            epoch_issues.add('shared_report_index_incomplete')
            # Known archived Web days are not days without any Web reading.
            web_days.update(date.fromisoformat(row[0]) for row in unindexed_days)
        for day_text, raw, position in summary_rows:
            report_read_checkpoint()
            data = json.loads(raw)
            digest.update(raw.encode())
            web_days.update(date.fromisoformat(d) for d in data['days'])
            schemas.update(data['schemas'])
            billing_safe &= data.get('billing_safe', False)
            epoch_issues.update(data['issues'])
            for key, item in data['counters'].items():
                day = date.fromisoformat(day_text) if position == 0 else datetime.fromisoformat(
                    item['last' if position < 0 else 'first']['at']).date()
                field, subject_type, subject_id = json.loads(key)
                if kind == 'device' and subject_type is not None:
                    continue
                if kind == 'subject' and (subject_type not in {'user', 'account', 'track'}
                        or field != f'counter.{subject_type}.total.total'):
                    continue
                counters.setdefault(key, []).append((day, item, data['count']))
        if len(schemas) > 1:
            epoch_issues.add('normalization_schema_changed')
        changes = prices.setdefault(slot, tuple(date.fromisoformat(r[0]) for r in conn.execute(
            'SELECT DISTINCT effective_date FROM price_history WHERE device_slot=?', (slot,))))
        for key, days in counters.items():
            report_read_checkpoint()
            field, subject_type, subject_id = json.loads(key)
            by_time, details, issues = {}, {}, set(epoch_issues)
            dates = [day for day, _, _ in days]
            first_index = bisect_left(dates, start) if start is not None else 0
            last_index = bisect_right(dates, end) if end is not None else len(days)
            high_before = Fraction()
            # Preserve the maximum before the selected window without replaying
            # its intervals or fabricating a new reading at the window boundary.
            for _, item, _ in days[:first_index]:
                high_before = max(high_before, _number(item['high']['value']))
            selected_indexes = set(range(max(0, first_index - 1), min(len(days), last_index + 1)))
            for index, (day, item, observed_count) in enumerate(days):
                issues.update(item['issues'])
                if index not in selected_indexes:
                    continue
                details[day] = item
                if item['count'] < observed_count:
                    issues.add('selected_counter_missing_on_observed_days')
                selected_points = ('last',) if index < first_index else ('first',) if index >= last_index else ('first', 'high', 'last')
                for which in selected_points:
                    p = item[which]
                    stamp = datetime.fromisoformat(p['at'])
                    previous = by_time.get(stamp)
                    value = _number(p['value'])
                    if previous is None or value > previous[0]:
                        by_time[stamp] = (value, {p['id']})
                    elif value == previous[0]:
                        previous[1].add(p['id'])
            points = tuple(CounterPoint(at, value, tuple(sorted(ids))) for at, (value, ids) in sorted(by_time.items()))
            projection = project_points(points, epoch_id=epoch_id, web_days=web_days, issues=issues,
                billing_day=billing_day, price_change_dates=changes,
                revision_data={'epoch': epoch_id, 'counter': key, 'summaries': digest.hexdigest(),
                               'start': str(start), 'end': str(end), 'billing_day': billing_day,
                               'price_dates': [d.isoformat() for d in changes]}, opening_high=high_before)
            daily = {}
            for interval in projection.intervals:
                allocation_days = interval.empty_days if graph and interval.empty_days else (interval.allocation_day,)
                amount = interval.amount / len(allocation_days)
                for day in allocation_days:
                    bucket = daily.setdefault(day, [Fraction(), set(), set(), set(), False, set()])
                    bucket[0] += amount
                    if interval.remark:
                        bucket[1].add(interval.remark)
                    bucket[2].update(interval.holds)
                    bucket[3].update(interval.start.evidence_ids + interval.end.evidence_ids)
                    bucket[4] |= bool(graph and interval.empty_days)
                    bucket[5].update((*interval.empty_days, interval.end.at.date()))
            # Include actual first readings even at zero usage; a used printer's
            # opening meter is a baseline, never a new usage charge.
            for day in details:
                daily.setdefault(day, [Fraction(), set(), set(), set(), False, {day}])
            for day, (amount, remarks, holds, evidence, estimated, covered) in sorted(daily.items()):
                if (start is not None and day < start) or (end is not None and day > end):
                    continue
                item = details.get(day)
                # Allocation-only rows use the interval's next real metadata;
                # they never invent an opening/closing read or sample timestamp.
                metadata_item = item or next((entry for d, entry, _ in days if d > day), days[-1][1])
                metadata = metadata_item['metadata']
                flags = holds | set(projection.issues) | issues
                result.append(SharedCounterDay(slot, serial, epoch_id, day, field, subject_type, subject_id,
                    metadata, _number(item['first']['value']) if item else None,
                    _number(item['high']['value']) if item else None, amount,
                    item['count'] if item else 0, item['first']['at'] if item else None,
                    item['last']['at'] if item else None,
                    tuple(sorted(evidence | ({item['first']['id'], item['high']['id'], item['last']['id']} if item else set()))),
                    tuple(sorted({SHARED_REMARK} | remarks)), tuple(sorted(flags)), tuple(sorted(covered)), billing_safe, estimated))
    return tuple(result)


def _blocked_source_days(conn, rows, kind, blocked):
    """Include a resumed read just outside the selected report window.

    A legacy Monday row may already contain the entire weekend delta. Selecting
    Sunday alone must not bypass that overlap guard and charge it again.
    """
    if not rows:
        return set()
    slots = sorted({r.slot for r in rows})
    start = min(d for r in rows for d in r.covered_days).isoformat()
    end = max(d for r in rows for d in r.covered_days).isoformat()
    placeholders = ','.join('?' for _ in slots)
    if kind == 'raw':
        query = f'''SELECT device_slot,device_serial_snapshot,canonical_field,subject_type,subject_id,record_date
            FROM daily_raw_counter_records WHERE device_slot IN ({placeholders}) AND record_date BETWEEN ? AND ?'''
        for slot, serial, field, subject, subject_id, day in conn.execute(query, [*slots, start, end]):
            blocked.setdefault((slot, serial, field, subject or None, subject_id or None), set()).add(date.fromisoformat(day))
    else:
        query = f'''SELECT device_slot,source_json,subject_type,subject_id,record_date FROM daily_subject_records
            WHERE device_slot IN ({placeholders}) AND record_date BETWEEN ? AND ?'''
        from services.subject_history import _source_identity
        for slot, raw, subject, subject_id, day in conn.execute(query, [*slots, start, end]):
            serial = _source_identity(raw, slot)[2]
            blocked.setdefault((slot, serial, subject, subject_id), set()).add(date.fromisoformat(day))
    # Closed archived detail is an overlap boundary without unpacking its file.
    return {(slot, date.fromisoformat(day)) for slot, day in conn.execute(f'''
        SELECT device_slot,record_date FROM report_archive_days WHERE kind=?
        AND device_slot IN ({placeholders}) AND record_date BETWEEN ? AND ?''', [kind, *slots, start, end])}


def raw_records(conn, slots, *, start=None, end=None, existing=()):
    from services.raw_counter_history import RawCounterDailyRecord
    from services.web_evidence_report import review_labels
    rows = load_shared_counter_days(conn, slots, start=start, end=end)
    if not rows:
        return ()
    blocked = {}
    for r in existing:
        blocked.setdefault((r.device_slot, r.device_serial_snapshot, r.canonical_field,
                            r.subject_type or None, r.subject_id or None), set()).add(r.record_date)
    archived = _blocked_source_days(conn, rows, 'raw', blocked)
    return tuple(RawCounterDailyRecord(
        device_slot=r.slot, record_date=r.day, canonical_field=r.field,
        label=r.metadata['label'], source_path=r.metadata['source_path'],
        subject_type=r.subject_type or '', subject_id=r.subject_id or '',
        subject_name=r.metadata['subject_name'] or '',
        opening_value=float(r.opening) if r.opening is not None else None,
        closing_value=float(r.closing) if r.closing is not None else None,
        delta_value=float(r.delta), reset_count=0, sample_count=r.count,
        first_success=r.first_at, last_success=r.last_at, source_name='shared-web',
        device_name_snapshot=r.metadata['printer_name'], device_serial_snapshot=r.serial,
        incomplete=bool(r.issues), pending_review=bool(r.issues),
        remarks=r.remarks + ((review_labels(r.issues),) if r.issues else ()),
    ) for r in rows if not any((r.slot, d) in archived for d in r.covered_days)
        if not blocked.get((r.slot, r.serial, r.field, r.subject_type, r.subject_id), set()).intersection(r.covered_days))


def subject_records(conn, slots, *, start=None, end=None, existing=()):
    from services.subject_history import SubjectDailyRecord
    from services.web_evidence_report import review_labels
    rows = load_shared_counter_days(conn, slots, start=start, end=end, kind='subject')
    if not rows:
        return ()
    blocked = {}
    for r in existing:
        blocked.setdefault((r.device_slot, r.device_serial_snapshot, r.subject_type, r.subject_id), set()).add(r.record_date)
    archived = _blocked_source_days(conn, rows, 'subject', blocked)
    return tuple(SubjectDailyRecord(
        device_slot=r.slot, record_date=r.day, subject_type=r.subject_type,
        subject_id=r.subject_id, subject_name=r.metadata['subject_name'] or r.subject_id,
        opening_total=float(r.opening) if r.opening is not None else None,
        closing_total=float(r.closing) if r.closing is not None else None,
        delta_total=float(r.delta), reset_count=0,
        missing_baseline='counter_without_reviewed_baseline' in r.issues,
        sample_count=r.count, first_success=r.first_at, last_success=r.last_at,
        incomplete=bool(r.issues), warnings=r.remarks + ((review_labels(r.issues),) if r.issues else ()),
        device_identity=f'serial:{r.serial}', device_name_snapshot=r.metadata['printer_name'],
        device_serial_snapshot=r.serial,
    ) for r in rows if not any((r.slot, d) in archived for d in r.covered_days)
        if not blocked.get((r.slot, r.serial, r.subject_type, r.subject_id), set()).intersection(r.covered_days))
