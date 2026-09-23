from datetime import date, datetime, UTC
from pathlib import Path
import json
import sqlite3
from unittest.mock import patch

import pytest

from database import _open, get_db_path, set_cfg
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.subject_history import SubjectDailyCacheStore, load_subject_history
from services.raw_counter_history import RawCounterHistoryStore, load_raw_counter_history
from services.report_detail_archive import ReportDetailArchive
from services.report_detail_amendment import ReportDetailAmendment
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore
from services.web_usage_projection import CounterIdentity
from test_report_detail_archive import archive_all
from test_peer_billing_amendments import clone, peer
from test_peer_https import certificates, server, client

COUNTER = CounterIdentity('counter.user.total.total', 'user', '7')


def reading(day, value):
    stamp = datetime(2024, 1, day, 8, tzinfo=UTC)
    values = {'counter.total.total': 1000, 'counter.print.total': 1000,
              'counter.copy.total': 0, 'counter.print.full_color_total': 1000, 'counter.print.bw_total': 0}
    counters = tuple(WebCounterValue(k, k, v, 'Meter', 'fixture', Confidence.VERIFIED) for k, v in values.items())
    counters += (WebCounterValue(COUNTER.field, 'Total', value, 'User', 'User.Total', Confidence.VERIFIED,
                                subject_type='user', subject_id='7', subject_name='Fixture user'),)
    return MeterReading(host='192.0.2.10', collected_at=stamp.isoformat(), counters=counters,
                        source='fixture', auth_state=WebAuthState.ADMIN)


def record(day, value, epoch=None):
    value = reading(day, value)
    return WebObservationStore().record(0, value, at=datetime.fromisoformat(value.collected_at),
                                        serial='SER-1', printer_name='Fixture', epoch_id=epoch)


def setup(archived=False):
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Fixture', '192.0.2.10', serial='SER-1')])
    set_cfg('billing_day', '31')
    first = record(5, 100)
    epochs = SlotEpochStore()
    epoch = epochs.confirm(epochs.preview(0, first['id'], operation='initial', actor='A', reason='Reviewed'))
    record(8, 130, epoch)
    cache, raw = SubjectDailyCacheStore(), RawCounterHistoryStore()
    for day, value in ((5, 100), (8, 130), (9, 130)):
        current = reading(day, value)
        stamp = datetime.fromisoformat(current.collected_at)
        cache.update_reading(0, current, at=stamp)
        # Represent immutable subject rows created by an older installation
        # before group-day local finalization was disabled.
        with patch('services.group_meter_scope.group_epoch_covers_day', return_value=False):
            cache.finalize(0, stamp.date())
        raw.update_reading(0, current, at=stamp)
    files = archive_all(ReportDetailArchive()) if archived else []
    return ReportDetailAmendment(), (0, epoch, date(2024, 1, 5), date(2024, 1, 8), UTC, COUNTER), files


def confirm(service, args, preview=None):
    preview = preview or service.preview(*args)
    return service.confirm(*args, expected_revision=preview['revision'], actor='A', reason='Reviewed Web details')


def state():
    with _open(commit=False) as conn:
        return tuple(conn.execute('SELECT * FROM ' + table).fetchall() for table in
            ('daily_subject_records', 'daily_raw_counter_records', 'report_detail_revisions',
             'archived_subject_periods', 'peer_billing_amendments', 'config_log'))


@pytest.mark.parametrize('archived', [False, True])
def test_gap_and_backfill_revision_preserve_originals_and_monthly_totals(archived, monkeypatch):
    service, args, files = setup(archived)
    originals = state()[:2]
    frozen = {item['path']: Path(item['path']).read_bytes() for item in files}
    preview = service.preview(*args)
    assert confirm(service, args, preview) == confirm(service, args, preview)
    assert state()[:2] == originals
    raw = [row for row in load_raw_counter_history([0]) if row.subject_id == '7']
    gap = next(row for row in raw if row.record_date.day == 7)
    assert (gap.delta_value, gap.opening_value, gap.closing_value, gap.first_success, gap.last_success, gap.sample_count) == (30, None, None, None, None, 0)
    assert gap.remarks and not gap.needs_review
    assert sum(row.delta_value for row in raw) == 30
    subjects = load_subject_history([0])
    assert sum(row.period_usage for row in subjects) == 30
    assert subjects[0].latest_total == 130
    selected = load_subject_history([0], period_start=date(2024, 1, 7), period_end=date(2024, 1, 7))
    assert selected[0].period_usage == 30 and selected[0].latest_total is None
    record(6, 110, args[1])
    record(7, 125, args[1])
    confirm(service, args)
    raw = [row for row in load_raw_counter_history([0]) if row.subject_id == '7']
    assert {r.record_date.day: r.delta_value for r in raw} == {5: 0, 6: 10, 7: 15, 8: 5, 9: 0}
    assert all(Path(path).read_bytes() == content for path, content in frozen.items())
    # Archiving originals after their amendment cannot count them a second time.
    if not archived:
        archive_all(ReportDetailArchive())
    def forbid(*args):
        raise AssertionError('Monthly view decoded cold files')
    monkeypatch.setattr(ReportDetailArchive, '_file', forbid)
    subjects = load_subject_history([0])
    assert sum(row.period_usage for row in subjects) == 30
    assert subjects[0].latest_total == 130


def test_peer_recomputes_details_for_different_row_ids_and_forwards_once(tmp_path, certificates):
    service, args, _ = setup(True)
    b = peer(clone(tmp_path, 'B'))
    confirm(service, args)
    document = peer().pending('B')
    from services.peer_https import PeerDataEndpoint
    with server(certificates, PeerDataEndpoint(history=None, epochs=None, amendments=b)) as url:
        transport = client(certificates, url)
        receipt = transport.amendment(document)
        assert transport.amendment_contains(document)['present']
    assert b.receive('A', document) == receipt
    assert b.contains('A', document)['present']
    assert b.pending('A') is None and b.pending('C') == document
    with b.service._connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_detail_revisions').fetchone()[0] == 6
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_changed_evidence_failed_summary_and_missing_archive_roll_back():
    service, args, files = setup(True)
    preview = service.preview(*args)
    record(6, 110, args[1])
    before = state()
    with pytest.raises(ValueError, match='เปลี่ยน'):
        confirm(service, args, preview)
    assert state() == before
    preview = service.preview(*args)
    with _open() as conn:
        conn.execute("CREATE TRIGGER fail_detail_queue BEFORE INSERT ON peer_billing_amendments BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):
        confirm(service, args, preview)
    assert state() == before
    with _open() as conn:
        conn.execute('DROP TRIGGER fail_detail_queue')
    for file in files:
        if file['kind'] == 'subject':
            Path(file['path']).write_bytes(b'damaged fixture')
            break
    with pytest.raises(ValueError, match='checksum'):
        confirm(service, args, preview)
    assert state() == before


def test_revision_is_immutable_and_reset_clears_receipts():
    from database import reset_usage_data
    service, args, _ = setup()
    confirm(service, args)
    with _open() as conn:
        with pytest.raises(sqlite3.DatabaseError, match='append-only'):
            conn.execute("UPDATE report_detail_revisions SET row_json='{}'")
    reset_usage_data()
    with _open(commit=False) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_detail_revisions').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM peer_billing_amendments').fetchone()[0] == 0


def test_monthly_revision_summary_reads_no_detail_payload(monkeypatch):
    from services import report_detail_amendment as module
    service, args, _ = setup(True)
    confirm(service, args)
    original = module.current_revisions
    def keys_only(*args, **kwargs):
        assert kwargs.get('include_rows') is False
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'current_revisions', keys_only)
    subjects = load_subject_history([0])
    assert sum(item.period_usage for item in subjects) == 30
    assert load_subject_history([0], only_period=(date(2024, 1, 1), date(2024, 1, 31))) == subjects


def test_revision_summaries_follow_explicit_period_change_and_backup(tmp_path):
    from services.billing_ledger import post_daily_record
    from services.billing_repricing_batch import BatchRepricingService
    from services.pricing import PricingRepository, PriceList
    from test_billing_ledger import _daily
    from tools.db_recovery import backup_database, restore_database
    import database
    service, args, _ = setup(True)
    PricingRepository().set_prices(0, date(2024, 1, 1), PriceList(a4_color=1))
    with _open() as conn:
        row = _daily(conn, {'reconciliation': {'billing_safe': True}}, record_date='2024-01-07')
    post_daily_record(row)
    confirm(service, args)
    set_cfg('billing_day', '10')
    batch = BatchRepricingService()
    scope = (date(2024, 1, 7), date(2024, 1, 7), [0])
    preview = batch.preview(*scope, apply_current_period=True)
    batch.confirm(*scope, apply_current_period=True, expected_revision=preview['revision'], actor='A', reason='Reviewed period')
    period = (date(2023, 12, 11), date(2024, 1, 10))
    assert load_subject_history([0], only_period=period)[0].period_usage == 30
    original = get_db_path()
    target = tmp_path/'restored'/'database.db'
    backup = tmp_path/'backup'/'database.db'
    backup_database(original, backup)
    restore_database(backup, target)
    try:
        database.set_db_path(target)
        assert load_subject_history([0], only_period=period)[0].period_usage == 30
        assert next(r for r in load_raw_counter_history([0]) if r.subject_id == '7' and r.record_date.day == 7).delta_value == 30
    finally:
        database.set_db_path(original)


def test_detail_dialog_requires_review_and_can_cancel_without_writes():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    from time import monotonic
    from ui.report_detail_amendment import ReportDetailAmendmentDialog
    app = QApplication.instance() or QApplication([])
    service, args, _ = setup(True)
    before = state()
    dialog = ReportDetailAmendmentDialog(args, service=service)
    dialog.show()
    dialog.load()
    deadline = monotonic() + 10
    while dialog.future is not None and monotonic() < deadline:
        QTest.qWait(20)
    assert dialog.preview and not dialog.confirm_button.isEnabled()
    dialog.reason.setText('Reviewed fixture')
    assert dialog.confirm_button.isEnabled() and dialog.table.rowCount() > 0
    dialog.reject()
    dialog.pool.shutdown(wait=True)
    assert state() == before
    app.processEvents()
