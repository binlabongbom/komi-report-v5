"""Offline SQLite backup, integrity and rollback helper for Release UAT/support."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

CRITICAL_TABLES = (
    "devices",
    "price_snapshot",
    "price_history",
    "readings",
    "daily_meter_records",
    "daily_subject_records",
    "daily_raw_counter_records",
    "billing_ledger",
    "legacy_history_items",
    "web_observations",
    "web_observation_archives",
    "report_detail_archives",
    "archived_subject_periods",
    "report_archive_days",
    "web_observation_outbox",
    "web_observation_receipts",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_entries(snapshot: Path):
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as conn:
        entries = []
        for table, folder in (("web_observation_archives", "web-observations"), ("report_detail_archives", "report-details")):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                entries.extend((folder, *row) for row in conn.execute("SELECT relative_path,sha256 FROM " + table))
        return entries


def _archive_path(data_root: Path, relative: str, folder="web-observations") -> Path:
    if folder not in {"web-observations", "report-details"}:
        raise ValueError("Unknown archive folder")
    root = (data_root / "archives" / folder).resolve()
    target = (root / relative).resolve()
    if Path(relative).is_absolute() or not target.is_relative_to(root) or target == root:
        raise ValueError("Archive path is outside its data directory")
    return target


def copy_referenced_archives(snapshot: Path, source_root: Path, destination_root: Path) -> int:
    """Copy only immutable files referenced by the frozen database snapshot.

    Verify before publishing the database. Never overwrite a different archive;
    a failed copy may leave verified orphan files but cannot damage either DB.
    Kept dependency-free so the offline recovery CLI works without the app.
    """
    entries = _archive_entries(snapshot.resolve())
    for folder, relative, digest in entries:
        source = _archive_path(source_root, relative, folder)
        target = _archive_path(destination_root, relative, folder)
        if not isinstance(digest, str) or len(digest) != 64 or _sha256(source) != digest:
            raise ValueError("Source archive checksum mismatch")
        if target.exists():
            if _sha256(target) != digest:
                raise ValueError("Destination archive checksum mismatch; existing file was preserved")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".archive-", suffix=".pending", dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                with source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            if _sha256(temporary) != digest:
                raise ValueError("Copied archive checksum mismatch")
            # Publish without replacing a file created concurrently.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if _sha256(target) != digest:
                    raise ValueError("Concurrent archive destination differs")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return len(entries)


def inspect_database(path: Path) -> dict[str, object]:
    path = path.expanduser().resolve(strict=True)
    uri = f"{path.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).casefold() != "ok":
            raise sqlite3.DatabaseError("database integrity_check failed")
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in CRITICAL_TABLES
            if table in tables
        }
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "integrity": "ok",
        "user_version": user_version,
        "critical_counts": counts,
        "archive_files": copy_referenced_archives(path, path.parent, path.parent),
    }


def backup_database(source: Path, destination: Path) -> dict[str, object]:
    source = source.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve(strict=False)
    if destination.exists():
        raise FileExistsError(f"backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}-", suffix=".pending", dir=destination.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
        source_uri = f"{source.as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_db, closing(
            sqlite3.connect(temporary)
        ) as destination_db:
            source_db.backup(destination_db)
            result = destination_db.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("backup integrity_check failed")
        copy_referenced_archives(temporary, source.parent, destination.parent)
        os.link(temporary, destination)
        temporary.unlink()
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return inspect_database(destination)


def restore_database(backup: Path, destination: Path) -> dict[str, object]:
    backup = backup.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve(strict=False)
    before = inspect_database(destination) if destination.is_file() else None
    backup_inspection = inspect_database(backup)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    rollback = destination.with_name(f"{destination.stem}.before-restore-{stamp}{destination.suffix}")
    if destination.is_file():
        backup_database(destination, rollback)

    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}-", suffix=".restore-pending", dir=destination.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
        source_uri = f"{backup.as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_db, closing(
            sqlite3.connect(temporary)
        ) as destination_db:
            source_db.backup(destination_db)
            result = destination_db.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("restored database integrity_check failed")
        copy_referenced_archives(temporary, backup.parent, destination.parent)
        os.replace(temporary, destination)
        temporary = None
        after = inspect_database(destination)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return {
        "before": before,
        "backup": backup_inspection,
        "after": after,
        "rollback_backup": str(rollback) if rollback.is_file() else "",
        "critical_counts_match_backup": after["critical_counts"] == backup_inspection["critical_counts"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="KOMI Report V5 offline database recovery")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--database", required=True, type=Path)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", required=True, type=Path)
    backup_parser.add_argument("--output", required=True, type=Path)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True, type=Path)
    restore_parser.add_argument("--database", required=True, type=Path)
    restore_parser.add_argument("--confirm-offline-restore", action="store_true")
    args = parser.parse_args()

    if args.command == "inspect":
        result = inspect_database(args.database)
    elif args.command == "backup":
        result = backup_database(args.database, args.output)
    else:
        if not args.confirm_offline_restore:
            parser.error("restore requires --confirm-offline-restore after the app is fully closed")
        result = restore_database(args.backup, args.database)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
