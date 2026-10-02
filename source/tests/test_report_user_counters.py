"""Compact Users evidence must produce the same results as exact Raw history."""
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
from threading import Event
from concurrent.futures import CancelledError

import pytest

import database
from excel_export_fixture import report_for
from services.device_config import DeviceConfigRepository
from services.raw_counter_history import load_raw_counter_history
from services.report_models import build_user_rows
from services.report_user_counters import load_user_counter_history


def project(records):
    return [(r.device_slot, r.record_date, r.canonical_field, r.label, r.subject_type,
             r.subject_id, r.subject_name, r.delta_value, r.device_serial_snapshot,
             r.needs_review) for r in records]


def store(report):
    DeviceConfigRepository().replace_all(list(report.devices))
    columns = ('device_slot', 'record_date', 'canonical_field', 'label', 'source_path',
               'subject_type', 'subject_id', 'subject_name', 'opening_value', 'closing_value',
               'delta_value', 'reset_count', 'sample_count', 'first_success', 'last_success',
               'source_name', 'device_name_snapshot', 'device_serial_snapshot', 'incomplete')
    with database._open() as conn:
        for record in report.raw_counter_records:
            values = [getattr(record, key) for key in columns]
            values[1] = values[1].isoformat()
            conn.execute('INSERT INTO daily_raw_counter_records (' + ','.join(columns) +
                         ',counter_review_json,counter_resolutions_json,created_at,updated_at) VALUES (' +
                         ','.join('?' for _ in range(len(columns) + 4)) + ')',
                         [*values, json.dumps({} if record.pending_review else None),
                          json.dumps([{'format': 'reviewed-baseline'}] if record.baseline_reviewed else []),
                          '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00'])


@pytest.mark.parametrize('case', ['priced', 'missing_cost', 'review', 'baseline', 'reset', 'replacement', 'fallback'])
def test_compact_counter_results_match_full_raw_including_daily_costs(case):
    report = report_for(users=2, days=3, printers=3)
    costs = tuple(replace(c, a4_color=c.a4_color * (c.record_date.day + .123))
                  for c in report.category_costs)
    raw = report.raw_counter_records
    if case == 'missing_cost':
        costs = costs[1:]
    elif case in {'review', 'baseline', 'reset'}:
        flag = {'review': 'pending_review', 'baseline': 'baseline_reviewed', 'reset': 'reset_count'}[case]
        raw = tuple(replace(r, **{flag: 1})
                    if r.subject_id == '0' and r.record_date.day == 2 else r for r in raw)
    elif case == 'replacement':
        raw = tuple(replace(r, device_serial_snapshot='REPLACEMENT')
                    if r.device_slot == 1 and r.record_date.day == 3 else r for r in raw)
    elif case == 'fallback':
        # Blank canonical key, negative deltas, zero and measured/missing fields.
        raw = tuple(replace(r, label=r.canonical_field, canonical_field='', delta_value=-1)
                    if r.canonical_field == 'counter.copy.black.a3' else r for r in raw)
    report = replace(report, raw_counter_records=raw, category_costs=costs)
    store(report)
    kwargs = dict(period_start=date(2026, 7, 1), period_end=date(2026, 7, 3))
    full = load_raw_counter_history([0, 1, 2], **kwargs)
    compact = load_user_counter_history([0, 1, 2], **kwargs)
    assert project(compact) == project(full)
    actual = build_user_rows(report.subjects, compact, category_costs=costs)
    expected = build_user_rows(report.subjects, full, category_costs=costs)
    assert actual == expected
    assert len(actual) == 2
    if case == 'priced':
        assert all(slot['cost_available'] for row in actual for slot in row['by_slot'].values())
        assert actual[0]['by_slot'][0]['cost'] > 0
    if case == 'missing_cost':
        assert not actual[0]['by_slot'][0]['cost_available']
    with pytest.raises(AttributeError):
        compact[0].delta_value = 99


@pytest.mark.parametrize('archived', [False, True])
def test_compact_read_preserves_reviewed_revisions_and_archive_precedence(archived):
    from test_report_detail_amendment import setup, confirm, record
    service, args, _files = setup(archived)
    confirm(service, args)
    record(6, 110, args[1])
    record(7, 125, args[1])
    confirm(service, args)
    for kwargs in ({}, {'period_start': date(2024, 1, 6), 'period_end': date(2024, 1, 7)}):
        full = load_raw_counter_history([0], **kwargs)
        compact = load_user_counter_history([0], **kwargs)
        assert project(compact) == project(full)
        assert sum(r.delta_value for r in compact if r.subject_id == '7') == (25 if kwargs else 30)


def test_compact_read_keeps_shared_evidence_and_selected_date_boundaries():
    from test_shared_report_history import setup, event_at, receive
    anchor, epoch = setup(datetime(2026, 9, 18, 10, tzinfo=UTC))
    receive(event_at(anchor, epoch, 125, datetime(2026, 9, 18, 11, tzinfo=UTC)), epoch)
    kwargs = dict(period_start=date(2026, 9, 18), period_end=date(2026, 9, 18))
    full = load_raw_counter_history([0], **kwargs)
    compact = load_user_counter_history([0], **kwargs)
    assert compact and project(compact) == project(full)
    assert not load_user_counter_history([0], period_start=date(2026, 9, 19))


def test_compact_read_honors_worker_cancellation():
    store(report_for(users=2, days=1, printers=1))
    cancelled = Event()
    cancelled.set()
    with database.report_read_database(database.get_db_path(), cancelled=cancelled):
        with pytest.raises(CancelledError):
            load_user_counter_history([0])


def test_compact_read_does_not_duplicate_shared_gap_with_local_row_outside_range():
    from services.device_config import DeviceConfig
    from services.raw_counter_history import RawCounterHistoryStore
    from test_shared_report_history import setup, reading, event_at, receive
    monday = datetime(2026, 9, 21, 9, tzinfo=UTC)
    DeviceConfigRepository().replace_all([
        DeviceConfig(0, 'Shared printer', '192.0.2.10', serial='REPORT-A')])
    raw = RawCounterHistoryStore()
    raw.update_reading(0, reading(100, monday), at=monday)
    later = monday + timedelta(minutes=1)
    raw.update_reading(0, reading(401, later), at=later)
    anchor, epoch = setup()
    receive(event_at(anchor, epoch, 401, monday), epoch)
    kwargs = dict(period_start=date(2026, 9, 20), period_end=date(2026, 9, 20))
    assert not load_raw_counter_history([0], **kwargs)
    assert not load_user_counter_history([0], **kwargs)
    assert project(load_user_counter_history([0])) == project(load_raw_counter_history([0]))
