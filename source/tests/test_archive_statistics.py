"""Display counts must match the rows actual archive pruning can select."""
from datetime import date
import sqlite3

import pytest

import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.history_archive import HistoryArchive
from services.report_detail_archive import ReportDetailArchive, TABLES, _anchor_condition
from services.web_observation_archive import detail_cutoff


TODAY = date(2026, 9, 18)


def devices():
    DeviceConfigRepository().replace_all([
        DeviceConfig(slot, f"Archive fixture {slot}", f"192.0.2.{10 + slot}", serial=f"FIXTURE-{slot}")
        for slot in range(2)
    ])


def insert(kind, day, *, review=False, **identity):
    values = dict(device_slot=0, record_date=day, subject_type="user", subject_id="7",
                  subject_name="Fixture user", created_at=day + "T10:00:00+00:00")
    if kind == "subject":
        values.update(opening_total=100, closing_total=110, delta_total=10,
                      source_json='{"counter_review":{}}' if review else '{}')
    else:
        values.update(canonical_field="counter.user.total.total", source_path="fixture.total",
                      label="Total", opening_value=100, closing_value=110,
                      device_serial_snapshot="FIXTURE-0", updated_at=values["created_at"],
                      counter_review_json='{}' if review else 'null')
    values.update(identity)
    with database._open() as conn:
        return conn.execute(f"INSERT INTO {TABLES[kind]} ({','.join(values)}) VALUES (" +
                            ','.join('?' for _ in values) + ')', list(values.values())).lastrowid


def pruning_count(today=TODAY):
    """Use the pruning predicate as an independent eligibility oracle."""
    with database._open(commit=False) as conn:
        return sum(conn.execute(
            f"SELECT COUNT(*) FROM {table} r WHERE r.record_date<? AND {_anchor_condition(kind)}",
            (detail_cutoff(today).isoformat(),),
        ).fetchone()[0] for kind, table in TABLES.items())


@pytest.mark.parametrize("kind", ["subject", "raw"])
@pytest.mark.parametrize("rows", [
    (),
    (("2024-01-01", False),),
    (("2026-01-01", False),),
    (("2024-01-01", False), ("2024-01-02", False)),
    (("2024-01-01", False), ("2024-01-02", False), ("2026-01-01", False)),
    (("2025-09-17", False), ("2025-09-18", False), ("2025-09-19", False)),
    (("2024-01-01", True), ("2024-01-02", False), ("2024-01-03", True)),
    (("2024-01-01", False), ("2024-01-02", True), ("2026-01-01", False)),
])
def test_stats_match_pruning_for_empty_singleton_boundary_and_review_rows(kind, rows):
    devices()
    for day, review in rows:
        insert(kind, day, review=review)
    assert ReportDetailArchive().stats(today=TODAY) == {
        "eligible": pruning_count(), "archived": 0, "files": 0,
    }


@pytest.mark.parametrize("kind", ["subject", "raw"])
def test_distinct_identity_anchors_do_not_hide_each_other(kind):
    devices()
    identities = [{}, {"device_slot": 1}, {"subject_id": "8"}, {"subject_type": "track"}]
    if kind == "raw":
        identities += [{"device_serial_snapshot": "REPLACEMENT"}, {"source_path": "other.path"},
                       {"canonical_field": "counter.user.print.color"}]
    for index, identity in enumerate(identities):
        for day in ("2024-01-01", "2024-01-02", "2024-01-03")[:1 + index % 3]:
            insert(kind, day, **identity)
    assert ReportDetailArchive().stats(today=TODAY)["eligible"] == pruning_count()


def test_subject_invalid_and_explicit_null_review_metadata_match_pruning():
    devices()
    for index, source in enumerate(('not-json', '{}', '{"counter_review":null}',
                                    '{"counter_review":false}', '{"counter_review":0}',
                                    '{"counter_review":{}}')):
        insert("subject", "2024-01-01", subject_id=str(index), source_json=source)
        insert("subject", "2026-01-01", subject_id=str(index))
    assert ReportDetailArchive().stats(today=TODAY)["eligible"] == pruning_count() == 2


def test_stats_reread_external_changes_and_date_cutoff_without_stale_counts():
    devices()
    insert("subject", "2025-09-18")
    insert("subject", "2026-09-18")
    archive = ReportDetailArchive()
    assert archive.stats(today=TODAY)["eligible"] == 0
    assert archive.stats(today=date(2026, 9, 19))["eligible"] == 1
    # Independent connection represents polling or a review in another process.
    with sqlite3.connect(database.get_db_path()) as conn:
        conn.execute("UPDATE daily_subject_records SET source_json=? WHERE record_date=?",
                     ('{"counter_review":{}}', '2025-09-18'))
    assert archive.stats(today=date(2026, 9, 19))["eligible"] == 0
    insert("subject", "2024-01-01")
    assert archive.stats(today=TODAY)["eligible"] == 1
    with sqlite3.connect(database.get_db_path()) as conn:
        conn.execute("DELETE FROM daily_subject_records WHERE record_date='2024-01-01'")
    assert archive.stats(today=TODAY)["eligible"] == 0


def test_catalog_counts_are_current_without_opening_archive_payloads(monkeypatch):
    archive = HistoryArchive()
    def no_payload(*_args):
        raise AssertionError("Statistics must not open an archived payload")
    for store in archive.archives:
        monkeypatch.setattr(store, "_file", no_payload)
    assert archive.stats(today=TODAY) == {"eligible": 0, "archived": 0, "files": 0}
    with database._open() as conn:
        conn.execute("INSERT INTO report_detail_archives VALUES(?,?,?,?,?,?,?,?,?)",
                     ('detail-fixture', 'subject', 'missing-details.sqlite3', 'hash', 13,
                      2024, '2024-01-01', '2024-12-31', '2026-09-18'))
        conn.execute("INSERT INTO web_observation_archives VALUES(?,?,?,?,?,?)",
                     ('web-fixture', 'missing-web.sqlite3', 'hash', 17, 2024, '2026-09-18'))
    assert archive.stats(today=TODAY) == {"eligible": 0, "archived": 30, "files": 2}


def test_stats_follow_committed_pruning_and_ignore_failed_pruning(monkeypatch):
    from test_report_detail_archive import fixture
    _, _, archive = fixture()
    before = archive.stats(today=TODAY)
    assert before["eligible"] == pruning_count() == 9
    verify = archive._verify_file
    def fail_verification(*_args):
        raise ValueError("Injected verification failure")
    monkeypatch.setattr(archive, "_verify_file", fail_verification)
    with pytest.raises(ValueError, match="Injected"):
        archive.archive_batch(today=TODAY, limit=2)
    assert archive.stats(today=TODAY) == before
    monkeypatch.setattr(archive, "_verify_file", verify)
    archived = archive.archive_batch(today=TODAY, limit=2)
    after = archive.stats(today=TODAY)
    assert after["eligible"] == pruning_count() == before["eligible"] - archived["events"]
    assert after["archived"] == archived["events"]
    assert after["files"] == 1
