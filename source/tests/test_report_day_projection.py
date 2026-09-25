"""Incremental report preparation must preserve fresh evidence and exact values."""
from concurrent.futures import CancelledError
from dataclasses import replace
from datetime import date
import json
import pickle
import sqlite3
from threading import Event
import zlib

import pytest

import database
from excel_export_fixture import report_for
from services import report_day_projection as projection
from services.report_models import build_user_rows
from services.report_operation_breakdown import _counter_breakdown, breakdown_from_counters
from services.report_user_counters import load_user_counter_history
from services.subject_history import SUBJECT_COLUMNS, load_subject_history
from test_report_user_counters import store
from test_subject_history_performance import _row


START, END = date(2026, 7, 1), date(2026, 7, 3)


@pytest.fixture(autouse=True)
def clean_projection_cache():
    projection.DAY_PROJECTIONS.clear()
    _counter_breakdown.cache_clear()
    yield
    projection.DAY_PROJECTIONS.clear()
    _counter_breakdown.cache_clear()


def seed(kind):
    report = report_for(users=2, days=3, printers=2)
    store(report)
    if kind == 'subject':
        rows = []
        for slot in range(2):
            for day in range(1, 4):
                for user in range(2):
                    row = list(_row(slot=slot, day=f'2026-07-{day:02}', name=f'User {user:03}',
                                    source=json.dumps({'device_identity': {'serial': f'SYNTH-{slot}'}})))
                    row[3] = str(user)
                    rows.append((*row, '2026-07-01T10:00:00'))
        with database._open() as conn:
            conn.executemany('INSERT INTO daily_subject_records (' + ','.join(SUBJECT_COLUMNS) +
                             ',created_at) VALUES (' + ','.join('?' for _ in range(17)) + ')', rows)
    return report


def load(kind, incremental=True, **period):
    period = period or dict(period_start=START, period_end=END)
    if kind == 'subject':
        return load_subject_history([0, 1], incremental=incremental, today=date(2026, 8, 1), **period)
    return load_user_counter_history([0, 1], incremental=incremental, **period)


@pytest.mark.parametrize('kind', ['subject', 'raw'])
@pytest.mark.parametrize('change', ['delta', 'name', 'identity', 'review', 'delete', 'insert'])
def test_only_changed_device_day_is_rebuilt_even_without_timestamp_change(kind, change):
    seed(kind)
    cache = projection.DAY_PROJECTIONS
    before = load(kind)
    assert before == load(kind, False)
    assert cache.misses == 6 and cache.hits == 0
    assert load(kind) == before
    assert cache.misses == 6 and cache.hits == 6
    table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
    # The period summary intentionally uses the latest day's subject name.
    changed_day = '2026-07-03' if change == 'name' else '2026-07-02'
    where = f"device_slot=0 AND record_date='{changed_day}' AND subject_id='0'"
    with database._open() as conn:
        if change == 'delete':
            conn.execute(f'DELETE FROM {table} WHERE {where}')
        elif change == 'insert':
            columns = [item[1] for item in conn.execute(f'PRAGMA table_info({table})') if item[1] != 'id']
            selected = ['?' if name == 'subject_id' else name for name in columns]
            conn.execute(f"INSERT INTO {table} ({','.join(columns)}) SELECT {','.join(selected)} "
                         f"FROM {table} WHERE {where}", ('new-user',))
        else:
            if change == 'delta':
                field, value = ('delta_total' if kind == 'subject' else 'delta_value'), 7.25
            elif change == 'name':
                field, value = 'subject_name', 'Changed name'
            elif change == 'review':
                field, value = 'reset_count', 1
            elif kind == 'subject':
                field, value = 'source_json', '{"device_identity":{"serial":"REPLACEMENT"}}'
            else:
                field, value = 'device_serial_snapshot', 'REPLACEMENT'
            # Deliberately leave every timestamp unchanged.
            conn.execute(f'UPDATE {table} SET {field}=? WHERE {where}', (value,))
    actual = load(kind)
    assert actual == load(kind, False)
    assert actual != before
    assert cache.misses == 7 and cache.hits == 11


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_deleted_day_is_not_replayed_and_reinserted_content_is_checked(kind):
    seed(kind)
    before = load(kind)
    table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
    with database._open() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE device_slot=0 AND record_date='2026-07-02' LIMIT 1").fetchone()
        conn.execute(f"DELETE FROM {table} WHERE device_slot=0 AND record_date='2026-07-02'")
    assert load(kind) == load(kind, False) != before
    with database._open() as conn:
        conn.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})", row)
    assert load(kind) == load(kind, False)


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_database_paths_have_separate_projection_namespaces(kind, tmp_path):
    seed(kind)
    original = load(kind)
    clone = tmp_path / 'other-report.sqlite3'
    with sqlite3.connect(database.get_db_path()) as source, sqlite3.connect(clone) as target:
        source.backup(target)
    with database.report_read_database(clone):
        assert load(kind) == original
    assert projection.DAY_PROJECTIONS.misses == 12
    with sqlite3.connect(clone) as conn:
        table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
        conn.execute(f"UPDATE {table} SET subject_name='Other database'")
    with database.report_read_database(clone):
        assert load(kind) == load(kind, False) != original
    assert load(kind) == original


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_real_values_keep_exact_binary64_precision_and_addition_order(kind):
    seed(kind)
    field = 'delta_total' if kind == 'subject' else 'delta_value'
    table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
    numbers = [0.10000000000000002, 1.2345678901234567, 2.2250738585072014e-308]
    with database._open() as conn:
        for day, number in enumerate(numbers, 1):
            conn.execute(f"UPDATE {table} SET {field}=? WHERE record_date=?", (number, f'2026-07-{day:02}'))
    expected = load(kind, False)
    actual = load(kind)
    assert actual == expected
    values = (lambda row: row.period_usage) if kind == 'subject' else (lambda row: row.delta_value)
    assert [values(row).hex() for row in actual] == [values(row).hex() for row in expected]
    assert load(kind) == expected


def test_projection_preserves_float_zero_null_and_empty_strings():
    columns = ('device_slot', 'record_date', 'opening_total', 'closing_total', 'delta_total', 'subject_name')
    row = (0, '2026-07-01', None, 0.0, 0.10000000000000002, '')
    def decode(values):
        return tuple(float(value) if index in (2, 3, 4) and value is not None else value
                     for index, value in enumerate(values))
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE evidence(device_slot,record_date,opening_total,closing_total,delta_total,subject_name)')
        conn.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)', row)
        # This generic projection fixture has an empty amendment catalog and
        # one token for its hot device/day, like the production readers.
        conn.execute('CREATE TABLE report_detail_revisions(id,kind,device_slot,serial,counter_key,record_date,row_json,period_start,period_end)')
        conn.execute('CREATE TABLE report_projection_generation(singleton,token)')
        conn.execute("INSERT INTO report_projection_generation VALUES(1,'float-fixture')")
        conn.execute('CREATE TABLE report_day_revisions(kind,device_slot,record_date,token)')
        conn.execute("INSERT INTO report_day_revisions VALUES('subject',0,'2026-07-01','first')")
        actual = list(projection.iter_projected_days(conn, 'subject', 'SELECT * FROM evidence', (), columns, decode))
    assert actual == [(row, None)]
    assert actual[0][0][4].hex() == row[4].hex()


@pytest.mark.parametrize('archived', [False, True])
def test_amendment_and_archive_precedence_match_uncached_readers(archived):
    from test_report_detail_amendment import setup, confirm, record
    service, args, _files = setup(archived)
    period = dict(period_start=date(2024, 1, 5), period_end=date(2024, 1, 9))
    for kind in ('subject', 'raw'):
        assert load(kind, **period) == load(kind, False, **period)
    confirm(service, args)
    for kind in ('subject', 'raw'):
        assert load(kind, **period) == load(kind, False, **period)
    record(6, 110, args[1])
    record(7, 125, args[1])
    confirm(service, args)
    for kind in ('subject', 'raw'):
        assert load(kind, **period) == load(kind, False, **period)
    assert load_subject_history([0], incremental=True) == load_subject_history([0])


def test_warm_counter_and_category_cache_never_freezes_changed_prices():
    report = seed('raw')
    counters = load('raw')
    before = build_user_rows(report.subjects, counters, category_costs=report.category_costs)
    costs = tuple(replace(cost, a4_color=cost.a4_color * 2) for cost in report.category_costs)
    warm = load('raw')
    assert projection.DAY_PROJECTIONS.hits == 6
    after = build_user_rows(report.subjects, warm, category_costs=costs)
    fresh = build_user_rows(report.subjects, load('raw', False), category_costs=costs)
    assert after == fresh
    assert after[0]['by_slot'][0]['cost'] > before[0]['by_slot'][0]['cost']
    assert _counter_breakdown.cache_info().hits > 0


def test_category_cache_keeps_canonical_availability_and_changed_values():
    first = breakdown_from_counters({'counter.print.full_color.a4': 0.0})
    assert first.print_available and 'print_a4_color' in first.available_fields
    assert not breakdown_from_counters({}).print_available
    assert breakdown_from_counters({'counter.print.full_color.a4': 0.0}) is first
    changed = breakdown_from_counters({'counter.print.full_color.a4': 0.10000000000000002})
    assert changed.print_a4_color.hex() == (0.10000000000000002).hex()
    assert first.print_a4_color == 0.0


def test_cache_evicts_lru_by_rows_and_bytes_and_rejects_oversized_blocks():
    size = lambda rows: len(zlib.compress(pickle.dumps(rows, protocol=5), level=1))
    cache = projection.DayProjectionCache(max_rows=3, max_bytes=1000)
    cache.read('a', 'first', lambda: (1,))
    cache.read('b', 'first', lambda: (2, 3))
    assert cache.bytes == size((1,)) + size((2, 3))
    assert cache.read('a', 'first', lambda: pytest.fail('hit decoded again')) == (1,)
    cache.read('c', 'first', lambda: (4,))
    assert list(cache.entries) == ['a', 'c']
    assert cache.rows == 2 and cache.bytes == size((1,)) + size((4,))
    assert cache.read('huge', 'first', lambda: (5, 6, 7, 8)) == (5, 6, 7, 8)
    assert 'huge' not in cache.entries
    cache.read('a', 'changed', lambda: (6, 7, 8))
    assert list(cache.entries) == ['a']
    assert cache.rows == 3 and cache.bytes == size((6, 7, 8))
    cache = projection.DayProjectionCache(max_bytes=size((1,)))
    cache.read('a', 'first', lambda: (1,))
    assert cache.read('huge', 'first', lambda: (tuple(range(100)),)) == (tuple(range(100)),)
    assert list(cache.entries) == ['a']


def test_cache_entry_limit_also_bounds_empty_projected_days():
    cache = projection.DayProjectionCache(max_entries=2)
    for key in range(5):
        assert cache.read(key, 'empty', tuple) == ()
    assert list(cache.entries) == [3, 4]
    assert cache.rows == 0
    assert cache.bytes == sum(len(item[1]) for item in cache.entries.values())
    cache.clear()
    assert not cache.entries and (cache.rows, cache.bytes, cache.hits, cache.misses) == (0, 0, 0, 0)


@pytest.mark.parametrize('filtered', [False, True])
def test_raw_order_with_equal_sort_keys_preserves_source_iteration_and_float_sums(filtered):
    report = report_for(users=1, days=1, printers=1)
    template = next(row for row in report.raw_counter_records if row.subject_id == '0')
    # Same final sort keys but different source paths. The value order matters
    # when totals mix large and small positive binary64 numbers.
    rows = tuple(replace(template, source_path=path, delta_value=value)
                 for path, value in [('z', 1e16), ('a', 1.0), ('m', 1.0)])
    rows += tuple(replace(row, record_date=date(2026, 7, 2)) for row in rows)
    store(replace(report, raw_counter_records=rows))
    kwargs = dict(period_start=START, period_end=END) if filtered else {}
    expected = load_user_counter_history([0], **kwargs)
    actual = load_user_counter_history([0], incremental=True, **kwargs)
    assert actual == expected
    assert sum(row.delta_value for row in actual).hex() == sum(row.delta_value for row in expected).hex()
    with database._open() as conn:
        conn.execute("UPDATE daily_raw_counter_records SET delta_value=2.0 "
                     "WHERE source_path='m' AND record_date='2026-07-01'")
    fresh = load_user_counter_history([0], **kwargs)
    changed = load_user_counter_history([0], incremental=True, **kwargs)
    assert changed == fresh
    assert sum(row.delta_value for row in changed).hex() == sum(row.delta_value for row in fresh).hex()


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_dirty_refresh_decodes_only_changed_day_and_warm_refresh_decodes_nothing(kind, monkeypatch):
    from services import report_user_counters, subject_history
    owner = subject_history if kind == 'subject' else report_user_counters
    name = '_subject_day_from_row' if kind == 'subject' else '_user_counter_from_row'
    original = getattr(owner, name)
    decoded = []
    def track(row):
        decoded.append((row[0], row[1]))
        return original(row)
    monkeypatch.setattr(owner, name, track)
    seed(kind)
    load(kind)
    assert set(decoded) == {(slot, f'2026-07-{day:02}') for slot in range(2) for day in range(1, 4)}
    decoded.clear()
    load(kind)
    assert decoded == []
    table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
    with database._open() as conn:
        conn.execute(f"UPDATE {table} SET subject_name='Changed' WHERE device_slot=0 AND record_date='2026-07-02'")
    load(kind)
    assert decoded and set(decoded) == {(0, '2026-07-02')}


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_day_move_invalidates_old_and_new_locations(kind):
    seed(kind)
    load(kind)
    table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
    with database._open() as conn:
        previous = dict(((slot, day), token) for slot, day, token in conn.execute(
            'SELECT device_slot,record_date,token FROM report_day_revisions WHERE kind=?', (kind,)))
        conn.execute(f"UPDATE {table} SET device_slot=1,record_date='2026-07-04' "
                     "WHERE device_slot=0 AND record_date='2026-07-02'")
        changed = dict(((slot, day), token) for slot, day, token in conn.execute(
            'SELECT device_slot,record_date,token FROM report_day_revisions WHERE kind=?', (kind,)))
    assert changed.get((0, '2026-07-02')) != previous[(0, '2026-07-02')]
    assert (1, '2026-07-04') in changed
    for key in previous.keys() - {(0, '2026-07-02')}:
        assert changed[key] == previous[key]
    period = dict(period_start=START, period_end=date(2026, 7, 4))
    assert load(kind, **period) == load(kind, False, **period)


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_rolled_back_change_rolls_back_its_token_and_reuses_unchanged_cache(kind):
    seed(kind)
    before = load(kind)
    table = 'daily_subject_records' if kind == 'subject' else 'daily_raw_counter_records'
    with sqlite3.connect(database.get_db_path()) as conn:
        old = conn.execute('SELECT device_slot,record_date,token FROM report_day_revisions '
                           'WHERE kind=? ORDER BY device_slot,record_date', (kind,)).fetchall()
        conn.execute('BEGIN')
        conn.execute(f"UPDATE {table} SET subject_name='Rolled back' "
                     "WHERE device_slot=0 AND record_date='2026-07-03'")
        pending = conn.execute('SELECT device_slot,record_date,token FROM report_day_revisions '
                               'WHERE kind=? ORDER BY device_slot,record_date', (kind,)).fetchall()
        assert old != pending
        conn.rollback()
        assert conn.execute('SELECT device_slot,record_date,token FROM report_day_revisions '
                            'WHERE kind=? ORDER BY device_slot,record_date', (kind,)).fetchall() == old
    assert load(kind) == before
    assert projection.DAY_PROJECTIONS.misses == 6 and projection.DAY_PROJECTIONS.hits == 6


def test_failed_or_cancelled_block_never_publishes_partial_or_changed_content():
    cache = projection.DayProjectionCache()
    cache.read('day', 'old', lambda: (1,))
    def failed():
        yield 2
        raise ValueError('Failed decoder')
    with pytest.raises(ValueError, match='Failed decoder'):
        cache.read('day', 'new', failed)
    assert cache.entries['day'][0] == 'old'
    event = Event()
    def cancelled():
        yield 2
        event.set()
    with database.report_read_database(database.get_db_path(), cancelled=event):
        with pytest.raises(CancelledError):
            cache.read('day', 'new', cancelled)
    assert cache.entries['day'][0] == 'old'
    assert cache.read('day', 'new', lambda: (3,)) == (3,)


@pytest.mark.parametrize('kind', ['subject', 'raw'])
def test_cancelled_warm_loader_does_not_replay_cached_days(kind):
    seed(kind)
    load(kind)
    event = Event()
    event.set()
    with database.report_read_database(database.get_db_path(), cancelled=event):
        # Subject loading reads billing configuration before reaching its first
        # projection checkpoint; SQLite's progress handler may interrupt there.
        with pytest.raises((CancelledError, sqlite3.OperationalError)) as error:
            load(kind)
    if isinstance(error.value, sqlite3.OperationalError):
        assert str(error.value) == 'interrupted'
