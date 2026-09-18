from datetime import date, datetime, UTC
import sqlite3
import zlib

import pytest

from database import _open
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.web_observations import WebObservationStore
from services.web_observation_archive import WebObservationArchive, detail_cutoff
from test_subject_history import _reading


def history():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SER-A")])
    store = WebObservationStore()
    events = []
    for day, count in (("2023-12-31", 100), ("2024-01-01", 110), ("2025-09-17", 120), ("2025-09-18", 130), ("2026-09-18", 140)):
        at = datetime.fromisoformat(day + "T10:00:00+00:00")
        events.append(store.record(0, _reading(count, collected_at=at), serial="SER-A", printer_name="Fixture", at=at))
    return store, events, WebObservationArchive()


def archive_all(archive):
    batches = []
    while batch := archive.archive_batch(today=date(2026, 9, 18)):
        batches.append(batch)
    return batches


def test_archiving_preserves_points_cursors_and_unacknowledged_deliveries():
    store, events, archive = history()
    store.acknowledge("PC-B", [events[0]["id"]])
    before = store.page()
    batches = archive_all(archive)
    assert [item["year"] for item in batches] == [2023, 2024, 2025]
    assert sum(item["events"] for item in batches) == 3
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM web_observations WHERE document_json='' AND archive_id IS NOT NULL").fetchone()[0] == 3
    store = WebObservationStore()
    assert store.page() == before
    assert store.pending("PC-B") == events[1:]
    assert store.pending("PC-C") == events
    store.acknowledge("PC-C", [event["id"] for event in events])
    assert store.pending("PC-C") == []
    assert archive.archive_batch(today=date(2026, 9, 18)) is None


def test_failed_file_verification_cannot_clear_live_payload(monkeypatch):
    store, _, archive = history()
    before = store.page()
    def fail(*args):
        raise ValueError("damaged archive")
    monkeypatch.setattr(archive, "_verify_file", fail)
    with pytest.raises(ValueError):
        archive.archive_batch(today=date(2026, 9, 18))
    assert store.page() == before
    assert archive.list() == []


def test_failed_catalog_commit_keeps_all_live_payloads():
    store, _, archive = history()
    before = store.page()
    with _open() as conn:
        conn.execute("""CREATE TRIGGER fail_archive_commit BEFORE UPDATE OF archive_id ON web_observations
            BEGIN SELECT RAISE(ABORT,'injected catalog failure'); END""")
    with pytest.raises(sqlite3.Error):
        archive.archive_batch(today=date(2026, 9, 18))
    assert store.page() == before
    assert archive.list() == []


def test_missing_archive_does_not_break_metadata_or_recent_only_history():
    from pathlib import Path
    store, _, archive = history()
    batches = archive_all(archive)
    # Simulate unavailable media, never silently return an empty old report.
    target = Path(batches[0]["path"])
    target.rename(target.with_suffix(".unavailable"))
    assert len(archive.list()) == 3
    assert len(store.page(after=3)["events"]) == 2
    with pytest.raises(sqlite3.Error):
        store.page()


def test_tampered_payload_is_rejected_when_requested():
    store, _, archive = history()
    batch = archive.archive_batch(today=date(2026, 9, 18))
    with sqlite3.connect(batch["path"]) as conn:
        conn.execute("UPDATE observations SET payload=x'0001'")
    with pytest.raises((zlib.error, ValueError, sqlite3.Error)):
        store.page()


def test_month_cutoff_handles_leap_day_and_path_escape_is_rejected():
    _, _, archive = history()
    assert detail_cutoff(date(2024, 2, 29)) == date(2023, 2, 28)
    with pytest.raises(ValueError):
        archive._file("../../outside.sqlite3")
