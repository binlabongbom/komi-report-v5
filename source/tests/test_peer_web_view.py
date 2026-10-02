from datetime import UTC, datetime
import sqlite3

import database
from services.peer_web_view import latest_shared_views
from services.runtime_snapshots import RuntimeSnapshotStore
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore
from test_reader_jobs import fixture
from test_subject_history import _reading


def saved(total, day=18):
    epoch = SlotEpochStore().head(0)['id']
    at = datetime(2026, 9, day, 10, tzinfo=UTC)
    return WebObservationStore().record(0, _reading(total, collected_at=at),
        serial='SER-A', printer_name='Fixture', epoch_id=epoch, at=at)


def test_live_view_uses_committed_maximum_and_original_web_time_not_receipt_time():
    fixture()
    event = saved(301)
    saved(200, 19)  # Later arrival/time but a smaller physical counter.
    view, = latest_shared_views(database.get_db_path())
    assert view['event_id'] == event['id']
    assert view['reading'].collected_at == event['payload']['observed_at']
    assert view['reading'].counters[0].count == 301
    with sqlite3.connect(database.get_db_path()) as conn:
        assert conn.execute('SELECT COUNT(*) FROM billing_ledger').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM daily_subject_records').fetchone()[0] == 0


def test_old_printer_observations_do_not_populate_new_serial_view():
    fixture()
    saved(301)
    with sqlite3.connect(database.get_db_path()) as conn:
        conn.execute("UPDATE devices SET serial='REPLACEMENT' WHERE slot=0")
    assert latest_shared_views(database.get_db_path()) == []


def test_archived_detail_is_not_opened_for_live_refresh(monkeypatch):
    fixture()
    event = saved(301)
    # Emulate the metadata condition without reading or modifying archive files.
    with sqlite3.connect(database.get_db_path()) as conn:
        conn.execute("UPDATE web_observations SET archive_id='unopened-fixture' WHERE event_id=?", (event['id'],))
    monkeypatch.setattr(WebObservationStore, '_document', lambda *_: (_ for _ in ()).throw(AssertionError('Archive opened')))
    assert latest_shared_views(database.get_db_path()) == []


def test_delayed_view_cannot_replace_larger_same_epoch_but_replacement_epoch_can():
    snapshots = RuntimeSnapshotStore()
    high = _reading(301, collected_at=datetime(2026, 9, 18, 10, tzinfo=UTC))
    low = _reading(20, collected_at=datetime(2026, 9, 18, 11, tzinfo=UTC))
    first = snapshots.update(0, high, serial='SER-A', epoch_id='epoch-1', event_id='high')
    assert snapshots.update(0, low, serial='SER-A', epoch_id='epoch-1', event_id='late', preserve_newer=True) is first
    replacement = snapshots.update(0, low, serial='SER-B', epoch_id='epoch-2', event_id='replacement', preserve_newer=True)
    assert replacement.event_id == 'replacement'
    assert replacement.subject_rows[0].count == 20
