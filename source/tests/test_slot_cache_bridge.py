from datetime import datetime, UTC
import json

from database import _open
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.raw_counter_history import RawCounterHistoryStore
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore
from test_daily_cache import _reading

KEY = 'counter.paper.full_color.a4'
STAMP = datetime(2026, 9, 18, 8, tzinfo=UTC)


def test_confirmed_reset_resumes_open_cache_and_raw_without_releasing_old_bill(tmp_path):
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='SER')])
    cache, raw, epochs = DailyCacheStore(tmp_path / 'cache'), RawCounterHistoryStore(), SlotEpochStore()
    def read(value, hour):
        at = STAMP.replace(hour=hour)
        reading = _reading(value, at)
        head = epochs.head(0)
        event = WebObservationStore().record(0, reading, serial='SER', printer_name='Office', at=at,
                                             epoch_id=head['id'] if head else None)
        return event, cache.update_reading(0, reading, at=at), raw.update_reading(0, reading, at=at)
    first, _, _ = read(100, 8)
    epochs.confirm(epochs.preview(0, first['id'], operation='initial', actor='A', reason='initial'))
    read(120, 9)
    reduced, held, _ = read(5, 10)
    assert held['delta'][KEY] == 20 and held['counter_review']
    new_head = epochs.confirm(epochs.preview(0, reduced['id'], operation='reset', actor='A', reason='checked reset'))
    _, resumed, _ = read(15, 11)
    assert resumed['slot_epoch'] == new_head
    assert resumed['delta'][KEY] == 30 and not resumed['counter_review']
    assert resumed['device_segments'][0]['counter_review']
    assert resumed['unsafe_reconciliation_seen'] is True
    with _open(commit=False) as conn:
        row = conn.execute('SELECT delta_value,counter_review_json,counter_resolutions_json FROM daily_raw_counter_records').fetchone()
    assert row[0] == 30 and row[1] == 'null' and json.loads(row[2])[0]['epoch_id'] == new_head
    # The same event/restart cannot apply the baseline a second time.
    at = STAMP.replace(hour=11)
    assert DailyCacheStore(cache.root).update_reading(0, _reading(15, at), at=at)['delta'][KEY] == 30
    raw.update_reading(0, _reading(15, at), at=at)
    cache.finalize(0, STAMP.date())
    with _open(commit=False) as conn:
        assert conn.execute('SELECT entry_kind FROM billing_ledger').fetchone()[0] == 'hold'
        original = conn.execute('SELECT source_json FROM daily_meter_records').fetchone()[0]
        assert json.loads(original)['slot_epoch'] == new_head
    next_day = STAMP.replace(day=19)
    cache.record_heartbeat(0, total=15, at=next_day)
    later = next_day.replace(hour=9)
    assert cache.update_reading(0, _reading(25, later), at=later)['delta'][KEY] == 10
    with _open(commit=False) as conn:
        assert conn.execute('SELECT source_json FROM daily_meter_records').fetchone()[0] == original


def test_used_replacement_keeps_old_segment_and_does_not_jump(tmp_path):
    repo = DeviceConfigRepository()
    repo.replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='OLD')])
    cache, epochs = DailyCacheStore(tmp_path / 'cache'), SlotEpochStore()
    def observe(value, hour, serial, epoch=None):
        at = STAMP.replace(hour=hour)
        reading = _reading(value, at)
        event = WebObservationStore().record(0, reading, serial=serial, printer_name='Office', at=at, epoch_id=epoch)
        return event, cache.update_reading(0, reading, at=at)
    first, _ = observe(100, 8, 'OLD')
    old = epochs.confirm(epochs.preview(0, first['id'], operation='initial', actor='A', reason='initial'))
    observe(120, 9, 'OLD', old)
    repo.update_runtime(0, serial='USED', status='online', checked_at=STAMP.isoformat())
    used, held = observe(9000, 10, 'USED')
    assert held['delta'][KEY] == 20
    new = epochs.confirm(epochs.preview(0, used['id'], operation='replacement', actor='A', reason='used replacement'))
    _, state = observe(9015, 11, 'USED', new)
    assert state['delta'][KEY] == 35
    assert state['device_segments'][0]['device_identity']['serial'] == 'OLD'
    assert state['device_identity']['serial'] == 'USED'
    assert state['unsafe_reconciliation_seen'] is True


def test_reviewed_subject_reset_survives_rollover_and_archive(tmp_path):
    from services.subject_history import SubjectDailyCacheStore, load_subject_history
    from services.report_detail_archive import ReportDetailArchive
    from test_subject_history import _reading as subject_reading
    from datetime import date
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='SER')])
    cache, epochs = SubjectDailyCacheStore(tmp_path / 'subjects'), SlotEpochStore()
    def read(value, hour):
        at = STAMP.replace(hour=hour)
        reading = subject_reading(value, collected_at=at)
        head = epochs.head(0)
        event = WebObservationStore().record(0, reading, serial='SER', printer_name='Office', at=at,
                                             epoch_id=head['id'] if head else None)
        return event, cache.update_reading(0, reading, at=at)
    first, _ = read(100, 8)
    epochs.confirm(epochs.preview(0, first['id'], operation='initial', actor='A', reason='initial'))
    read(120, 9)
    reset, state = read(6, 10)
    assert state['subjects']['user:u-1']['counter_review']
    epochs.confirm(epochs.preview(0, reset['id'], operation='reset', actor='A', reason='checked'))
    _, state = read(16, 11)
    assert state['subjects']['user:u-1']['delta_total'] == 30
    assert not state['subjects']['user:u-1'].get('counter_review')
    cache.finalize(0, STAMP.date())
    at = STAMP.replace(day=19)
    cache.update_reading(0, subject_reading(26, collected_at=at), at=at)
    cache.finalize(0, at.date())
    before = load_subject_history([0], cache=cache)
    assert sum(r.period_usage for r in before) == 40
    archive = ReportDetailArchive()
    while archive.archive_batch(today=date(2028, 1, 1)):
        pass
    assert load_subject_history([0], cache=cache) == before


def test_initial_epoch_does_not_hide_a_different_archived_subject_printer():
    import pytest
    from test_report_detail_archive import fixture, archive_all
    from test_slot_epoch_store import read
    _, _, archive = fixture()
    archive_all(archive)
    # Isolate the archived-subject identity check from the other retained anchors.
    with _open() as conn:
        conn.execute('DELETE FROM daily_subject_records')
        conn.execute('DELETE FROM daily_raw_counter_records')
    event = read('NEW', 50000, 19)
    with pytest.raises(ValueError, match='Historical slot identity'):
        SlotEpochStore().preview(0, event['id'], operation='initial', actor='A', reason='review')


def test_reviewed_raw_baseline_carries_across_days_without_rewriting_held_day():
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='SER')])
    raw, epochs = RawCounterHistoryStore(), SlotEpochStore()
    def read(value, at):
        reading = _reading(value, at)
        event = WebObservationStore().record(0, reading, serial='SER', printer_name='Office', at=at,
            epoch_id=epochs.head(0)['id'] if epochs.head(0) else None)
        raw.update_reading(0, reading, at=at)
        return event
    first = read(100, STAMP)
    epochs.confirm(epochs.preview(0, first['id'], operation='initial', actor='A', reason='initial'))
    read(120, STAMP.replace(hour=9))
    reset = read(5, STAMP.replace(hour=10))
    epoch = epochs.confirm(epochs.preview(0, reset['id'], operation='reset', actor='A', reason='checked'))
    with _open(commit=False) as conn:
        before = conn.execute('SELECT * FROM daily_raw_counter_records').fetchone()
    read(15, STAMP.replace(day=19))
    with _open(commit=False) as conn:
        assert conn.execute('SELECT * FROM daily_raw_counter_records WHERE record_date=?', (STAMP.date().isoformat(),)).fetchone() == before
        row = conn.execute('SELECT opening_value,delta_value,counter_review_json,counter_resolutions_json FROM daily_raw_counter_records WHERE record_date=?', ('2026-09-19',)).fetchone()
        assert row[:3] == (5, 10, 'null')
        assert json.loads(row[3])[0]['epoch_id'] == epoch


def test_first_raw_row_of_a_used_replacement_uses_the_shared_baseline():
    repo = DeviceConfigRepository()
    repo.replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='OLD')])
    epochs, raw = SlotEpochStore(), RawCounterHistoryStore()
    first = WebObservationStore().record(0, _reading(100, STAMP), serial='OLD', printer_name='Office', at=STAMP)
    epochs.confirm(epochs.preview(0, first['id'], operation='initial', actor='A', reason='initial'))
    raw.update_reading(0, _reading(100, STAMP), at=STAMP)
    at = STAMP.replace(hour=9)
    repo.update_runtime(0, serial='USED', status='online', checked_at=at.isoformat())
    baseline = WebObservationStore().record(0, _reading(9000, at), serial='USED', printer_name='Office', at=at)
    epochs.confirm(epochs.preview(0, baseline['id'], operation='replacement', actor='A', reason='checked'))
    # The reviewed baseline arrived via the shared journal, not local Raw cache.
    later = STAMP.replace(hour=10)
    raw.update_reading(0, _reading(9015, later), at=later)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT opening_value,closing_value,delta_value FROM daily_raw_counter_records WHERE device_serial_snapshot='USED'").fetchone() == (9000, 9015, 15)
