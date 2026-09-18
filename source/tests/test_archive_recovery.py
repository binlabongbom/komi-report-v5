from pathlib import Path
from contextlib import closing
import sqlite3

import pytest

import database
from services.web_observation_archive import WebObservationArchive
from test_web_observation_archive import history, archive_all
from tools.db_recovery import backup_database, restore_database, inspect_database


@pytest.mark.parametrize("method", ["backup", "first_run"])
def test_portable_copy_preserves_archived_events_and_pending_queue(tmp_path, method):
    store, events, archive = history()
    archive_all(archive)
    destination = tmp_path / method / "restored.sqlite3"
    if method == "backup":
        assert backup_database(database.get_db_path(), destination)["archive_files"] == 3
    else:
        database.copy_database_for_first_run(destination)
    restored = WebObservationArchive(destination)
    for event in events[:3]:
        with sqlite3.connect(destination) as conn:
            archive_id = conn.execute("SELECT archive_id FROM web_observations WHERE event_id=?", (event["id"],)).fetchone()[0]
        import json
        assert json.loads(restored.read_document(archive_id, event["id"])) == event
    assert store.pending("PC-B") == events


def test_restore_to_different_folder_copies_archive_and_preserves_rollback(tmp_path):
    _, _, archive = history()
    archive_all(archive)
    backup = tmp_path / "backup" / "komi.db"
    backup_database(database.get_db_path(), backup)
    destination = tmp_path / "restored" / "komi.db"
    backup_database(database.get_db_path(), destination)
    with closing(sqlite3.connect(destination)) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('company_name','Before restore')")
    result = restore_database(backup, destination)
    assert result["after"]["archive_files"] == 3
    assert result["critical_counts_match_backup"]
    rollback = Path(result["rollback_backup"])
    assert inspect_database(rollback)["archive_files"] == 3
    with sqlite3.connect(rollback) as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='company_name'").fetchone()[0] == "Before restore"


@pytest.mark.parametrize("failure", ["missing", "tampered", "collision", "escape"])
def test_bad_archive_never_publishes_new_database(tmp_path, failure):
    _, _, archive = history()
    batch = archive_all(archive)[0]
    source_file = Path(batch["path"])
    destination = tmp_path / "backup" / "komi.db"
    if failure == "missing":
        source_file.rename(source_file.with_suffix(".unavailable"))
    elif failure == "tampered":
        source_file.write_bytes(b"damaged fixture")
    elif failure == "collision":
        target = destination.parent / "archives" / "web-observations" / source_file.relative_to(archive.root)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"other fixture")
    else:
        with sqlite3.connect(database.get_db_path()) as conn:
            conn.execute("UPDATE web_observation_archives SET relative_path='../outside.db' WHERE id=?", (batch["id"],))
    with pytest.raises((OSError, ValueError)):
        backup_database(database.get_db_path(), destination)
    assert not destination.exists()
    assert database.get_db_path().exists()
    if failure == "collision":
        assert target.read_bytes() == b"other fixture"


def test_usage_reset_clears_catalog_but_preserves_backup_files():
    store, _, archive = history()
    batches = archive_all(archive)
    database.reset_usage_data()
    assert archive.list() == []
    assert store.page()["events"] == []
    assert all(Path(batch["path"]).exists() for batch in batches)
