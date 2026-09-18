from datetime import date, datetime, UTC
from pathlib import Path
import sqlite3

import pytest

import database
from database import _open
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.subject_history import SubjectDailyCacheStore, load_subject_history
from services.raw_counter_history import RawCounterHistoryStore, load_raw_counter_history, load_usage_meter_baselines
from services.report_detail_archive import ReportDetailArchive
from test_subject_history import _reading
from test_raw_counter_history import _total_reading


def fixture():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Archive fixture", "192.0.2.10", serial="SER-A")])
    cache, raw = SubjectDailyCacheStore(), RawCounterHistoryStore()
    for index, day in enumerate(("2024-01-02", "2024-01-03", "2024-01-04", "2024-02-01", "2025-08-01", "2026-09-18")):
        stamp = datetime.fromisoformat(day + "T10:00:00+00:00")
        reading = _reading(100 + index * 10, collected_at=stamp)
        cache.update_reading(0, reading, at=stamp)
        cache.finalize(0, stamp.date())
        raw.update_reading(0, _total_reading(stamp, 1000 + index * 10), at=stamp)
    return cache, raw, ReportDetailArchive()


def archive_all(archive):
    batches = []
    while batch := archive.archive_batch(today=date(2026, 9, 18), limit=2):
        batches.append(batch)
    return batches


def test_monthly_custom_and_exact_raw_results_survive_archive(monkeypatch):
    cache, _, archive = fixture()
    monthly = load_subject_history([0])
    custom = load_subject_history([0], period_start=date(2024, 1, 3), period_end=date(2024, 2, 1))
    raw = load_raw_counter_history([0])
    baseline = load_usage_meter_baselines([0])
    batches = archive_all(archive)
    assert sum(batch["events"] for batch in batches) == 9  # 5 subjects + 4 raw; anchors stay hot
    assert load_subject_history([0]) == monthly
    assert load_subject_history([0], period_start=date(2024, 1, 3), period_end=date(2024, 2, 1)) == custom
    assert load_raw_counter_history([0]) == raw
    assert load_usage_meter_baselines([0]) == baseline
    def no_old_files(*args):
        raise AssertionError("Monthly reports must use hot summaries")
    monkeypatch.setattr(archive.__class__, "_file", no_old_files)
    assert load_subject_history([0]) == monthly
    for period in {(item.period_start, item.period_end) for item in monthly}:
        assert load_subject_history([0], only_period=period) == tuple(item for item in monthly if (item.period_start, item.period_end) == period)


def test_next_read_uses_retained_anchor_without_archive_io(monkeypatch):
    cache, raw, archive = fixture()
    archive_all(archive)
    def no_archive(*args):
        raise AssertionError("Collection must not load old files")
    monkeypatch.setattr(archive.__class__, "_file", no_archive)
    stamp = datetime(2026, 9, 19, 10, tzinfo=UTC)
    cache.update_reading(0, _reading(175, collected_at=stamp), at=stamp)
    records = cache.finalize(0, stamp.date())
    assert records[0].delta_total == 25
    raw.update_reading(0, _total_reading(stamp, 1080), at=stamp)
    assert load_raw_counter_history([0], period_start=stamp.date())[0].delta_value == 30


@pytest.mark.parametrize("failure", ["verify", "prune"])
def test_archive_failure_leaves_all_live_evidence_and_no_summary(monkeypatch, failure):
    _, _, archive = fixture()
    before = load_subject_history([0])
    if failure == "verify":
        def fail(*args):
            raise ValueError("Injected verification failure")
        monkeypatch.setattr(archive, "_verify_file", fail)
    else:
        with _open() as conn:
            conn.execute("CREATE TRIGGER fail_prune BEFORE DELETE ON daily_subject_records BEGIN SELECT RAISE(ABORT,'injected prune failure'); END")
    with pytest.raises((ValueError, sqlite3.Error)):
        archive.archive_batch(today=date(2026, 9, 18))
    assert load_subject_history([0]) == before
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_subject_records").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM archived_subject_periods").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM report_detail_archives").fetchone()[0] == 0


def test_missing_or_changed_old_file_is_never_an_empty_success():
    _, _, archive = fixture()
    batches = archive_all(archive)
    target = Path(batches[0]["path"])
    target.write_bytes(b"damaged fixture")
    assert load_subject_history([0])  # Metadata-only monthly view still available.
    with pytest.raises(ValueError, match="checksum"):
        load_subject_history([0], period_start=date(2024, 1, 1), period_end=date(2024, 1, 31))
    assert load_subject_history([0], period_start=date(2026, 1, 1), period_end=date(2026, 12, 31))


def test_archived_days_cannot_be_reinserted_or_changed_silently():
    _, raw, archive = fixture()
    archive_all(archive)
    stamp = datetime(2024, 1, 3, 12, tzinfo=UTC)
    with pytest.raises(sqlite3.IntegrityError, match="amendment"):
        raw.update_reading(0, _total_reading(stamp, 1020), at=stamp)


def test_source_change_between_file_verification_and_prune_aborts(monkeypatch):
    _, _, archive = fixture()
    verify = archive._verify_file
    def changed(path, expected):
        digest = verify(path, expected)
        with _open() as conn:
            conn.execute("UPDATE daily_subject_records SET delta_total=delta_total+1 WHERE record_date='2024-01-02'")
        return digest
    monkeypatch.setattr(archive, "_verify_file", changed)
    with pytest.raises(ValueError, match="changed"):
        archive.archive_batch(today=date(2026, 9, 18))
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_subject_records").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM report_detail_archives").fetchone()[0] == 0


def test_frozen_billing_period_does_not_follow_current_settings():
    import json
    from services.billing_ledger import post_daily_record
    _, _, archive = fixture()
    with _open() as conn:
        record_id = conn.execute("""INSERT INTO daily_meter_records(
            device_slot,record_date,opening_json,closing_json,delta_json,category_json,
            source_json,first_success,last_success,sample_count,created_at)
            VALUES(0,'2024-01-03','{}','{}',?,?,?,?,?,2,?)""", (
            '{"counter.total.total":10}', '{"counter.total.total":"no_charge"}',
            json.dumps({"reconciliation": {"billing_safe": True}}),
            '2024-01-03T10:00:00+00:00', '2024-01-03T10:00:00+00:00', '2024-01-03T10:00:00+00:00')).lastrowid
    post_daily_record(record_id)
    database.set_cfg("billing_day", "10")
    before = load_subject_history([0])
    archive_all(archive)
    assert load_subject_history([0]) == before
    assert sum(row.period_usage for row in before) == 50
    old_period = (date(2023, 12, 26), date(2024, 1, 25))
    assert load_subject_history([0], only_period=old_period)[0].period_usage == 10


def test_unresolved_raw_review_stays_hot_and_reported():
    _, _, archive = fixture()
    with _open() as conn:
        conn.execute("""UPDATE daily_raw_counter_records SET counter_review_json='{"before":1010,"after":5}'
            WHERE record_date='2024-01-03'""")
    before = load_raw_counter_history([0])
    archive_all(archive)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_raw_counter_records WHERE counter_review_json!='null'").fetchone()[0] == 1
    assert load_raw_counter_history([0]) == before


def test_backup_restore_and_usage_reset_preserve_archive_contract(tmp_path):
    from tools.db_recovery import backup_database, restore_database
    _, _, archive = fixture()
    monthly, raw = load_subject_history([0]), load_raw_counter_history([0])
    batches = archive_all(archive)
    backup = tmp_path / "backup" / "copy.sqlite3"
    assert backup_database(database.get_db_path(), backup)["archive_files"] == len(batches)
    target = tmp_path / "restore" / "restored.sqlite3"
    assert restore_database(backup, target)["critical_counts_match_backup"]
    original = database.get_db_path()
    try:
        database.set_db_path(target)
        assert load_subject_history([0]) == monthly
        assert load_raw_counter_history([0]) == raw
        database.reset_usage_data()
        assert load_subject_history([0]) == ()
        assert load_raw_counter_history([0]) == ()
        assert list((target.parent / "archives").rglob("*.sqlite3"))  # immutable backup files retained
    finally:
        database.set_db_path(original)
