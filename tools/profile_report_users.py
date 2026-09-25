"""Measure Users report preparation using only the verified 200-user fixture.

The source database is opened read-only and backed up into a temporary runtime.
Each measured request gets fresh DailyCacheStore, SubjectDailyCacheStore and
SnapshotDataCache objects. Module/OS caches may warm between requests; use a new
process for each before/after comparison. Serialization and optional cProfile
run outside the snapshot timings. No Qt application, network or child process
is started.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import hashlib
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import closing
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
PERIOD = ("2025-09-18", "2026-09-17")
EXPECTED_DEVICES = [
    (slot, f"FIXTURE-{slot}", f"192.0.2.{slot + 10}") for slot in range(3)
]


def _json_bytes(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@lru_cache(maxsize=None)
def _dataclass_layout(kind):
    return (
        _json_bytes(f"{kind.__module__}.{kind.__qualname__}"),
        tuple((field.name, _json_bytes(field.name)) for field in fields(kind)),
    )


def _canonical_chunks(value):
    """Type-preserving canonical JSON, streamed to avoid copying all raw rows.

    Mapping keys and sets are sorted by their canonical encoding. Sequence order,
    all dataclass fields and exact float values are retained; an unknown type fails
    instead of using a lossy string representation.
    """
    if isinstance(value, Enum):
        yield b'["enum",'
        yield _json_bytes(f"{type(value).__module__}.{type(value).__qualname__}")
        yield b","
        yield from _canonical_chunks(value.value)
        yield b"]"
    elif value is None or isinstance(value, (bool, int, str)):
        yield _json_bytes(value)
    elif isinstance(value, float):
        yield _json_bytes(["float", value.hex()])
    elif isinstance(value, (datetime, date)):
        yield _json_bytes([type(value).__name__, value.isoformat()])
    elif isinstance(value, Decimal):
        yield _json_bytes(["decimal", str(value)])
    elif isinstance(value, Fraction):
        yield _json_bytes(["fraction", value.numerator, value.denominator])
    elif isinstance(value, bytes):
        yield _json_bytes(["bytes", value.hex()])
    elif is_dataclass(value) and not isinstance(value, type):
        kind, members = _dataclass_layout(type(value))
        yield b'["dataclass",'
        yield kind
        yield b",["
        for index, (name, encoded_name) in enumerate(members):
            if index:
                yield b","
            yield b"["
            yield encoded_name
            yield b","
            yield from _canonical_chunks(getattr(value, name))
            yield b"]"
        yield b"]]"
    elif isinstance(value, Mapping):
        entries = sorted(
            (b"".join(_canonical_chunks(key)), item) for key, item in value.items()
        )
        yield b'["mapping",['
        for index, (key, item) in enumerate(entries):
            if index:
                yield b","
            yield b"["
            yield key
            yield b","
            yield from _canonical_chunks(item)
            yield b"]"
        yield b"]]"
    elif isinstance(value, (tuple, list)):
        yield b'["tuple",[' if isinstance(value, tuple) else b'["list",['
        for index, item in enumerate(value):
            if index:
                yield b","
            yield from _canonical_chunks(item)
        yield b"]]"
    elif isinstance(value, (set, frozenset)):
        yield b'["frozenset",[' if isinstance(value, frozenset) else b'["set",['
        for index, item in enumerate(
            sorted(b"".join(_canonical_chunks(item)) for item in value)
        ):
            if index:
                yield b","
            yield item
        yield b"]]"
    else:
        raise TypeError(
            f"Unsupported snapshot value: {type(value).__module__}.{type(value).__qualname__}"
        )


def canonical_hash(value) -> dict[str, int | str]:
    digest = hashlib.sha256()
    size = 0
    for chunk in _canonical_chunks(value):
        digest.update(chunk)
        size += len(chunk)
    return {"sha256": digest.hexdigest(), "serialized_bytes": size}


def snapshot_fingerprint(snapshot) -> dict:
    parts = {
        "users_models": snapshot.data["prepared_models"]["users"],
        "subjects": snapshot.data["subjects"],
        "raw_counter_records": snapshot.data["raw_counter_records"],
    }
    fingerprints = {
        name: {"count": len(value), **canonical_hash(value)}
        for name, value in parts.items()
    }
    # Named component hashes cover every field, including sequence ordering.
    return {
        "serialization": "typed-canonical-json-v1",
        "components": fingerprints,
        "presentation_sha256": canonical_hash(
            {
                name: fingerprints[name]["sha256"]
                for name in ("users_models", "subjects")
            }
        )["sha256"],
        "sha256": canonical_hash(
            {name: item["sha256"] for name, item in fingerprints.items()}
        )["sha256"],
    }


def _isolate_runtime(directory: Path) -> None:
    for name in tuple(os.environ):
        if name.startswith("KOMI_"):
            del os.environ[name]
    home = directory / "home"
    roaming = home / "AppData" / "Roaming"
    local = home / "AppData" / "Local"
    for path in (home, roaming, local):
        path.mkdir(parents=True)
    os.environ.update(
        {
            "KOMI_APP_HOME": str(directory),
            "KOMI_DB_PATH": str(directory / "synthetic.sqlite3"),
            "KOMI_RUNTIME_CONFIG": str(directory / "runtime.toml"),
            "KOMI_LOG_DIR": str(directory / "logs"),
            "KOMI_PEER_SYNC_STATE_FILE": str(directory / "peer-state.json"),
            "KOMI_V46_DATABASE": str(directory / "absent-legacy.sqlite3"),
            "KOMI_DISCOVERY_DISABLED": "1",
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(roaming),
            "LOCALAPPDATA": str(local),
        }
    )
    sys.path.insert(0, str(ROOT / "source"))


def _verified_backup(source: Path, target: Path) -> dict:
    # Immutable read-only mode cannot create journal/WAL sidecars next to the
    # input. Reject an uncheckpointed fixture rather than ignore recent data.
    wal = source.with_name(source.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError(
            "Close/checkpoint the synthetic fixture first; a nonempty WAL is present"
        )
    with closing(
        sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as original:
        devices = original.execute(
            "SELECT slot,serial,host FROM devices ORDER BY slot"
        ).fetchall()
        if devices != EXPECTED_DEVICES:
            raise ValueError(
                "Only the documented three-printer FIXTURE database is accepted"
            )
        users = original.execute(
            "SELECT COUNT(DISTINCT subject_id) FROM daily_subject_records"
        ).fetchone()[0]
        if users != 200:
            raise ValueError(
                f"Expected the documented 200-user fixture, found {users} users"
            )
        metadata = {
            "source": str(source),
            "original_opened_read_only": True,
            "devices": devices,
            "users": users,
            "database_bytes": source.stat().st_size,
            "date_range": original.execute(
                "SELECT MIN(record_date),MAX(record_date) FROM daily_subject_records"
            ).fetchone(),
            "row_counts": {
                table: original.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "daily_meter_records",
                    "daily_subject_records",
                    "daily_raw_counter_records",
                )
            },
            "selected_period_sql": {
                "subject_daily_rows": original.execute(
                    "SELECT COUNT(*) FROM daily_subject_records WHERE record_date BETWEEN ? AND ?",
                    PERIOD,
                ).fetchone()[0],
                "subject_usage_by_slot": [
                    {"slot": slot, "rows": rows, "users": count, "delta_total": delta}
                    for slot, rows, count, delta in original.execute(
                        "SELECT device_slot,COUNT(*),COUNT(DISTINCT subject_id),SUM(delta_total) "
                        "FROM daily_subject_records WHERE record_date BETWEEN ? AND ? "
                        "GROUP BY device_slot ORDER BY device_slot",
                        PERIOD,
                    )
                ],
                "raw_by_category": [
                    {
                        "subject_type": kind,
                        "field": field,
                        "rows": count,
                        "delta_value": delta,
                    }
                    for kind, field, count, delta in original.execute(
                        "SELECT subject_type,canonical_field,COUNT(*),SUM(delta_value) "
                        "FROM daily_raw_counter_records WHERE record_date BETWEEN ? AND ? "
                        "GROUP BY subject_type,canonical_field ORDER BY subject_type,canonical_field",
                        PERIOD,
                    )
                ],
            },
        }
        with closing(sqlite3.connect(target)) as copied:
            original.backup(copied)
    return metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-db", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New JSON evidence file"
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--clear-day-cache", action="store_true",
                        help="Clear incremental day projections before every measured request")
    parser.add_argument("--incremental-change", action="store_true",
                        help="Also change one fixture day and compare the refresh with uncached readers")
    parser.add_argument(
        "--profile",
        nargs="?",
        const="",
        metavar="PATH",
        help="Extra cProfile iteration; defaults to OUTPUT.prof",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be positive")
    source = args.synthetic_db.resolve(strict=True)
    output = args.output.resolve()
    profile_path = (
        (Path(args.profile).resolve() if args.profile else output.with_suffix(".prof"))
        if args.profile is not None
        else None
    )
    destinations = [output] + ([profile_path] if profile_path else [])
    if len(set(destinations)) != len(destinations) or any(
        path == source or path.exists() for path in destinations
    ):
        parser.error(
            "Output/profile must be distinct new files and must not overwrite the source"
        )
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "synthetic": True,
        "complete": False,
        "python": sys.version,
        "platform": sys.platform,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT),
        "period": PERIOD,
        "runs": [],
        "blocked_operations": [],
        "scope": "Fresh request caches; module and OS caches may warm; no Qt/network/process launch",
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                'source/migrations.py', 'source/services/monthly_history.py',
                'source/services/report_snapshot.py', 'source/services/subject_history.py',
                'source/services/raw_counter_history.py', 'source/services/report_user_counters.py',
                'source/services/report_day_projection.py', 'source/services/report_operation_breakdown.py',
                'source/services/report_detail_archive.py',
            )
        },
    }

    def save():
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def guard(event, _args):
        if event in {
            "socket.connect",
            "socket.sendto",
            "socket.bind",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.getnameinfo",
            "subprocess.Popen",
            "os.system",
        }:
            result["blocked_operations"].append(event)
            raise PermissionError(
                "Users profiling forbids network and process launches"
            )

    sys.addaudithook(guard)
    save()
    try:
        with tempfile.TemporaryDirectory(prefix="komi-users-profile-") as temporary:
            directory = Path(temporary)
            _isolate_runtime(directory)
            result["fixture"] = _verified_backup(
                source, directory / "synthetic.sqlite3"
            )
            # All application imports follow fixture validation, backup and
            # environment isolation; import-time defaults cannot reach live DBs.
            import database
            from services.daily_cache import DailyCacheStore
            from services.device_config import DeviceConfigRepository
            from services.report_snapshot import SnapshotDataCache, load_report_snapshot
            from services.subject_history import SubjectDailyCacheStore
            from services.report_day_projection import DAY_PROJECTIONS

            database.set_db_path(directory / "synthetic.sqlite3")
            started = time.perf_counter()
            database.init_db()
            result["copy_migration_init_seconds"] = time.perf_counter() - started
            database.set_cfg("web_service_enabled", "0")

            def memory():
                if sys.platform != "win32":
                    return None
                from measure_idle_runtime import counters

                return counters()

            class TimedCache(SnapshotDataCache):
                def __init__(self):
                    super().__init__()
                    self.measurements = []

                def read(self, key, loader, cancelled):
                    def measured():
                        started = time.perf_counter()
                        value = loader()
                        self.measurements.append(
                            {
                                "component": key[1],
                                "period": key[2],
                                "seconds": time.perf_counter() - started,
                                "count": len(value)
                                if hasattr(value, "__len__")
                                else None,
                            }
                        )
                        return value

                    return super().read(key, measured, cancelled)

            def load(label, shared):
                cache_root = directory / label
                return load_report_snapshot(
                    1,
                    PERIOD,
                    cache=DailyCacheStore(cache_root / "daily"),
                    subject_cache=SubjectDailyCacheStore(cache_root / "subjects"),
                    repository=DeviceConfigRepository(),
                    cancelled=Event(),
                    shared=shared,
                    database_path=database.get_db_path(),
                )

            def projection_stats():
                return dict(hits=DAY_PROJECTIONS.hits, misses=DAY_PROJECTIONS.misses,
                            rows=DAY_PROJECTIONS.rows, compressed_bytes=DAY_PROJECTIONS.bytes,
                            entries=len(DAY_PROJECTIONS.entries))

            for iteration in range(1, args.runs + 1):
                if args.clear_day_cache:
                    DAY_PROJECTIONS.clear()
                gc.collect()
                shared = TimedCache()
                before = memory()
                projections_before = projection_stats()
                result["in_progress"] = f"timing-{iteration}"
                save()
                started = time.perf_counter()
                snapshot = load(f"request-{iteration}", shared)
                seconds = time.perf_counter() - started
                after = memory()
                row = {
                    "run": iteration,
                    "seconds": seconds,
                    "components": shared.measurements,
                    "memory_before": before,
                    "memory_after": after,
                    "day_projections_before": projections_before,
                    "day_projections_after": projection_stats(),
                    "day_projections_cleared": args.clear_day_cache,
                }
                result["runs"].append(row)
                result["in_progress"] = f"fingerprint-{iteration}"
                save()
                started = time.perf_counter()
                row["fingerprint"] = snapshot_fingerprint(snapshot)
                row["fingerprint_seconds"] = time.perf_counter() - started
                del snapshot, shared
                save()
                print(
                    json.dumps(
                        {
                            "run": iteration,
                            "seconds": seconds,
                            "sha256": row["fingerprint"]["sha256"],
                        }
                    ),
                    flush=True,
                )
            result["parity_between_runs"] = (
                len({row["fingerprint"]["sha256"] for row in result["runs"]}) == 1
            )
            result["timing_summary"] = {
                "minimum_seconds": min(row["seconds"] for row in result["runs"]),
                "median_seconds": statistics.median(
                    row["seconds"] for row in result["runs"]
                ),
                "maximum_seconds": max(row["seconds"] for row in result["runs"]),
            }
            if args.incremental_change:
                # Mutate only the verified temporary copy, preserving timestamps
                # to prove invalidation does not rely on their resolution.
                with closing(sqlite3.connect(database.get_db_path())) as conn, conn:
                    kind, identity = conn.execute(
                        'SELECT subject_type,subject_id FROM daily_subject_records '
                        'WHERE device_slot=0 AND record_date=? ORDER BY subject_id LIMIT 1',
                        (PERIOD[1],)).fetchone()
                    conn.execute('UPDATE daily_subject_records SET delta_total=delta_total+1,'
                                 'closing_total=closing_total+1 WHERE device_slot=0 AND record_date=? '
                                 'AND subject_type=? AND subject_id=?', (PERIOD[1], kind, identity))
                    conn.execute('UPDATE daily_raw_counter_records SET delta_value=delta_value+1,'
                                 'closing_value=closing_value+1 WHERE device_slot=0 AND record_date=? '
                                 'AND subject_type=? AND subject_id=?', (PERIOD[1], kind, identity))
                before = projection_stats()
                started = time.perf_counter()
                changed = load('changed-day', TimedCache())
                change = dict(seconds=time.perf_counter()-started, before=before,
                              after=projection_stats(), fingerprint=snapshot_fingerprint(changed))
                from unittest.mock import patch
                import services.report_snapshot as snapshot_module
                original_subjects = snapshot_module.load_subject_history
                original_counters = snapshot_module.load_user_counter_history

                def no_subject_cache(*args, **kwargs):
                    return original_subjects(*args, **{**kwargs, 'incremental': False})

                def no_counter_cache(*args, **kwargs):
                    return original_counters(*args, **{**kwargs, 'incremental': False})

                with patch.object(snapshot_module, 'load_subject_history', no_subject_cache), \
                     patch.object(snapshot_module, 'load_user_counter_history', no_counter_cache):
                    oracle = load('changed-day-oracle', TimedCache())
                change['oracle_fingerprint'] = snapshot_fingerprint(oracle)
                change['exact_parity'] = change['fingerprint'] == change['oracle_fingerprint']
                result['changed_day'] = change
                del changed, oracle
                save()
            if profile_path:
                gc.collect()
                result["in_progress"] = "separate-cprofile-iteration"
                save()
                profile = cProfile.Profile()
                shared = TimedCache()
                try:
                    snapshot = profile.runcall(load, "profile-request", shared)
                finally:
                    profile.dump_stats(str(profile_path))
                result["profile"] = {
                    "path": str(profile_path),
                    "components": shared.measurements,
                    "fingerprint": snapshot_fingerprint(snapshot),
                }
                result["profile"]["matches_measured_runs"] = (
                    result["profile"]["fingerprint"]["sha256"]
                    == result["runs"][0]["fingerprint"]["sha256"]
                )
                del snapshot, shared
            result["in_progress"] = None
            result["complete"] = True
            save()
        return (
            0
            if result["parity_between_runs"]
            and result.get('changed_day', {}).get('exact_parity', True)
            and result.get("profile", {}).get("matches_measured_runs", True)
            else 1
        )
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        save()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
