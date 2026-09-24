from dataclasses import replace
from datetime import date
from threading import Event
from types import SimpleNamespace

import pytest

from services.report_models import RawCell, build_legacy_raw_tables
from services.report_snapshot import SnapshotDataCache, load_report_snapshot
from test_cloud_reports_ui import _raw


def test_raw_index_preserves_zero_missing_review_sources_and_slot_replacement():
    day = date(2026, 8, 6)
    old = _raw(day, slot=0, field='counter.print.total', label='Print', delta=7)
    new = replace(old, device_serial_snapshot='REPLACEMENT', opening_value=90000,
                  closing_value=90003, delta_value=3, pending_review=True)
    zero = replace(old, device_slot=1, delta_value=0, source_path='/alternate')
    user = replace(old, subject_type='user', subject_id='u-1', subject_name='A', delta_value=2)
    account = replace(user, subject_type='account', delta_value=5)
    records = (old, new, zero, user, account)
    class Once:
        def __iter__(self):
            assert not getattr(self, 'iterated', False), 'Raw records must be indexed once'
            self.iterated = True
            return iter(records)
    machine, users, daily = build_legacy_raw_tables(Once(), ())
    assert '[/alternate]' in machine.rows[0][1]
    assert '[/' in machine.rows[1][1]
    assert machine.rows[0][2:] == (None, RawCell(0, False))
    assert machine.rows[1][2:] == (RawCell(10, True), None)
    assert {row[0]: row[1:] for row in users.rows} == {'A (user)': (RawCell(2, False),), 'A (account)': (RawCell(5, False),)}
    assert daily.rows[0][1:] == (RawCell(10, True), RawCell(0, False))
    assert new.opening_value == 90000  # absolute meter was never counted as usage


def test_snapshot_tabs_share_immutable_raw_and_invalidate_by_database(monkeypatch, tmp_path):
    from services import report_snapshot as module
    from database import get_db_path
    period = ('2026-08-01', '2026-08-31')
    raw = (_raw(date(2026, 8, 6), slot=0, field='counter.print.total', label='Print', delta=7),)
    monthly = SimpleNamespace(period_start=date(2026, 8, 1), period_end=date(2026, 8, 31))
    calls = []
    monkeypatch.setattr(module, 'report_slots', lambda: [0])
    monkeypatch.setattr(module, 'load_usage_history', lambda *a, **kw: (monthly,))
    monkeypatch.setattr(module, 'load_subject_history', lambda *a, **kw: ())
    monkeypatch.setattr(module, 'load_imported_legacy_history', lambda: ())
    def read(*args, **kwargs):
        calls.append(str(get_db_path()))
        return tuple(list(raw))
    monkeypatch.setattr(module, 'load_raw_counter_history', read)
    shared = SnapshotDataCache()
    kwargs = dict(cache=None, subject_cache=None, repository=SimpleNamespace(list=lambda **kw: ()), cancelled=Event(), shared=shared)
    users = load_report_snapshot(1, period, **kwargs)
    legacy = load_report_snapshot(4, period, **kwargs)
    assert users.data['raw_counter_records'] is legacy.data['raw_counter_records']
    assert users.data['monthly_records'] is legacy.data['monthly_records']
    assert len(calls) == 1
    with pytest.raises(TypeError):
        users.data['raw_counter_records'] = ()
    with pytest.raises(TypeError):
        legacy.data['prepared_models']['legacy_raw'] = ()
    load_report_snapshot(4, period, database_path=tmp_path / 'other.db', **kwargs)
    assert len(calls) == 2 and calls[0] != calls[1]
    kwargs['shared'] = SnapshotDataCache()
    load_report_snapshot(4, period, **kwargs)
    assert len(calls) == 3


def test_warm_tab_restores_completed_render_without_rebuilding(staged, monkeypatch):
    from test_cloud_reports_staged import deliver
    from PyQt6.QtTest import QTest
    deliver(staged, tab_index=0, snapshot_token=('revision', 0))
    for _ in range(100):
        if not staged._pending_render_tail:
            break
        QTest.qWait(5)
    assert 0 in staged._rendered_tokens
    staged.tabs.setCurrentIndex(1)
    deliver(staged, tab_index=1, snapshot_token=('revision', 1))
    staged.tabs.setCurrentIndex(0)
    monkeypatch.setattr(staged, '_render_selected_tab', lambda: pytest.fail('Warm tab rebuilt'))
    deliver(staged, tab_index=0, snapshot_token=('revision', 0))


from test_cloud_reports_staged import staged
