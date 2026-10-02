"""Verify archival on a COPY of benchmark_five_years.py's synthetic database."""
from contextlib import closing
from datetime import date
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(source, output):
    import database
    from services.subject_history import load_subject_history
    from services.raw_counter_history import load_raw_counter_history
    from services.report_detail_archive import ReportDetailArchive

    source, output = source.resolve(strict=True), output.resolve()
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as conn:
        devices = conn.execute("SELECT slot,serial,host FROM devices").fetchall()
        if not devices or any(serial != f"FIXTURE-{slot}" or host != f"192.0.2.{slot + 10}" for slot, serial, host in devices):
            raise ValueError("Only the documented synthetic fixture is accepted")
        expected_total = conn.execute("SELECT SUM(delta_total) FROM daily_subject_records").fetchone()[0]
        output.mkdir(parents=True, exist_ok=False)
        path = output / "synthetic-archived.sqlite3"
        with closing(sqlite3.connect(path)) as dest:
            conn.backup(dest)
    database.set_db_path(path)
    database.init_db()
    slots = [row[0] for row in devices]
    period = (date(2024, 1, 1), date(2024, 1, 31))
    custom = dict(period_start=date(2024, 1, 3), period_end=date(2024, 1, 9))
    canonical = load_subject_history(slots, only_period=period)
    before_custom = load_subject_history(slots, **custom)
    before_raw = load_raw_counter_history(slots, **custom)
    archive, batches = ReportDetailArchive(), []
    started = perf_counter()
    while batch := archive.archive_batch(today=date(2026, 9, 18)):
        batches.append(batch)
        if len(batches) % 20 == 0:
            print(f"archived_batches={len(batches)} rows={sum(item['events'] for item in batches)}", flush=True)
    elapsed = perf_counter() - started
    timings = {}
    def measure(name, callback):
        began = perf_counter()
        result = callback()
        timings[name] = round((perf_counter() - began) * 1000, 2)
        return result
    all_months = measure("all_subject_months_ms", lambda: load_subject_history(slots))
    assert sum(row.period_usage for row in all_months) == expected_total
    assert measure("old_canonical_month_ms", lambda: load_subject_history(slots, only_period=period)) == canonical
    assert measure("old_custom_week_ms", lambda: load_subject_history(slots, **custom)) == before_custom
    assert measure("old_raw_week_ms", lambda: load_raw_counter_history(slots, **custom)) == before_raw
    with database._open() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        remaining = {table: conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("daily_subject_records", "daily_raw_counter_records", "archived_subject_periods")}
    result = {"synthetic": True, "input": str(source), "copy": str(path), "source_bytes": source.stat().st_size,
        "hot_file_bytes": path.stat().st_size, "reusable_hot_bytes": free_pages * page_size,
        "archive_bytes": sum(batch["archive_bytes"] for batch in batches), "archive_files": len(batches),
        "archived_rows": sum(batch["events"] for batch in batches), "archive_seconds": round(elapsed, 3),
        "remaining_rows": remaining, "verified_total_pages": expected_total, "timings": timings,
        "verified": ["all monthly page totals", "old canonical month exact equality", "old custom week exact equality",
            "old raw week exact equality", "quick_check"],
        "notes": ["Original synthetic fixture opened read-only; archive ran on a new copy",
            "No VACUUM: freed SQLite pages are reusable; file does not shrink immediately",
            "Query measurements are single runs after archival, not cold-start or real-printer timings"]}
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)
