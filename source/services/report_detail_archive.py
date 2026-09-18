"""Immutable yearly daily details, with hot billing-period subject summaries.

Only explicit detail/date-range requests open old files. Collection baselines,
latest counter anchors, daily device financial evidence and ledgers stay hot.
Files are verified before an atomic summary/catalog/prune transaction.
"""
from contextlib import closing
from datetime import date, datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
import zlib

from database import get_db_path
from services.billing_periods import billing_month_range, effective_billing_day
from services.web_observation_archive import detail_cutoff, _digest

TABLES = {"subject": "daily_subject_records", "raw": "daily_raw_counter_records"}
MAX_ROW_BYTES = 1024 * 1024
MAX_BLOCK_BYTES = 2 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _billing_day(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='billing_day'").fetchone()
    return effective_billing_day(row[0] if row else None)


def _decode(blob, length, digest):
    if type(length) is not int or not 0 < length <= MAX_BLOCK_BYTES:
        raise ValueError("Invalid report archive row size")
    decoder = zlib.decompressobj()
    data = decoder.decompress(blob, length + 1)
    if (len(data) != length or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or hashlib.sha256(data).hexdigest() != digest):
        raise ValueError("Damaged report archive row")
    return json.loads(data)


def _anchor_condition(kind):
    keys = ["device_slot", "subject_type", "subject_id"]
    if kind == "raw":
        keys += ["device_serial_snapshot", "canonical_field", "source_path"]
    table = TABLES[kind]
    match = " AND ".join(f"a.{key}=r.{key}" for key in keys)
    # Keep the latest value/review state for subsequent collection.
    condition = f"EXISTS(SELECT 1 FROM {table} a WHERE {match} AND a.record_date>r.record_date)"
    if kind == "raw":
        # Keep first values too: absolute meter baselines must remain available
        # to startup and normal reports without opening cold storage.
        condition += f" AND EXISTS(SELECT 1 FROM {table} a WHERE {match} AND a.record_date<r.record_date)"
        condition += " AND r.counter_review_json='null'"
    else:
        # Preserve unresolved reviews for the current review UI.
        condition += " AND json_valid(r.source_json) AND json_extract(r.source_json,'$.counter_review') IS NULL"
    return condition


class ReportDetailArchive:
    def __init__(self, database_path=None):
        self.path = Path(database_path or get_db_path()).resolve()
        self.root = self.path.parent / "archives" / "report-details"

    def _file(self, relative):
        target = (self.root / relative).resolve()
        if Path(relative).is_absolute() or not target.is_relative_to(self.root.resolve()) or target == self.root.resolve():
            raise ValueError("Report archive path escapes its directory")
        return target

    def stats(self, *, today=None):
        cutoff = detail_cutoff(today or date.today()).isoformat()
        with closing(sqlite3.connect(self.path)) as conn:
            eligible = sum(conn.execute(f"SELECT COUNT(*) FROM {table} r WHERE r.record_date<? AND {_anchor_condition(kind)}",
                (cutoff,)).fetchone()[0] for kind, table in TABLES.items())
            archived, files = conn.execute("SELECT COALESCE(SUM(row_count),0),COUNT(*) FROM report_detail_archives").fetchone()
        return {"eligible": eligible, "archived": archived, "files": files}

    def archive_batch(self, *, today=None, limit=4000):
        if type(limit) is not int or not 1 <= limit <= 4000:
            raise ValueError("Invalid report archive batch size")
        cutoff = detail_cutoff(today or date.today()).isoformat()
        documents, size, year = [], 0, None
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            billing_day = _billing_day(conn)
            periods = {(row[0], row[1]): (row[2], row[3]) for row in conn.execute(
                "SELECT device_slot,record_date,period_start,period_end FROM billing_ledger ORDER BY id")}
            for kind, table in TABLES.items():
                rows = conn.execute(f"SELECT r.* FROM {table} r WHERE r.record_date<? AND {_anchor_condition(kind)} "
                    "ORDER BY r.record_date,r.id LIMIT ?", (cutoff, limit))
                for result in rows:
                    row = dict(result)
                    day = date.fromisoformat(row["record_date"])
                    period = periods.get((row["device_slot"], row["record_date"]))
                    if period is None:
                        period = tuple(value.isoformat() for value in billing_month_range(day, billing_day))
                    document = {"row": row, "period": period}
                    encoded = _json(document).encode("utf-8")
                    if len(encoded) > MAX_ROW_BYTES:
                        raise ValueError("Daily evidence is too large to archive safely")
                    if documents and (year != day.year or size + len(encoded) > MAX_CHUNK_BYTES):
                        break
                    year = day.year
                    size += len(encoded)
                    documents.append((document, encoded))
                if documents:
                    break
        if not documents:
            return None
        archive_id = uuid.uuid4().hex
        relative = f"{year}/{kind}-{archive_id}.sqlite3"
        target = self._file(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        with closing(sqlite3.connect(temporary)) as archive, archive:
            archive.execute("PRAGMA synchronous=FULL")
            archive.execute("""CREATE TABLE detail_blocks(
                block_number INTEGER PRIMARY KEY,first_day TEXT NOT NULL,last_day TEXT NOT NULL,
                payload BLOB NOT NULL,uncompressed_bytes INTEGER NOT NULL,sha256 TEXT NOT NULL)""")
            block, block_size, number = [], 2, 0
            def write_block():
                nonlocal block, block_size, number
                encoded = _json(block).encode("utf-8")
                days = [item["row"]["record_date"] for item in block]
                archive.execute("INSERT INTO detail_blocks VALUES(?,?,?,?,?,?)", (number, min(days), max(days),
                    zlib.compress(encoded), len(encoded), hashlib.sha256(encoded).hexdigest()))
                number += 1
                block, block_size = [], 2
            for document, encoded in documents:
                if block and (len(block) >= 128 or block_size + len(encoded) + 1 > MAX_BLOCK_BYTES):
                    write_block()
                block.append(document)
                block_size += len(encoded) + 1
            if block:
                write_block()
        digest = self._verify_file(temporary, {document["row"]["id"]: document for document, _ in documents})
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            # Summaries must freeze the exact same financial periods verified
            # with the file, even if another process posts corrections meanwhile.
            for document, _ in documents:
                row = document["row"]
                live = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row["id"],)).fetchone()
                if live is None or dict(live) != row:
                    raise ValueError("Daily evidence changed during archive preparation")
                frozen = conn.execute("""SELECT period_start,period_end FROM billing_ledger
                    WHERE device_slot=? AND record_date=? ORDER BY id DESC LIMIT 1""",
                    (row["device_slot"], row["record_date"])).fetchone()
                if frozen and list(frozen) != list(document["period"]):
                    raise ValueError("Billing period changed during archive preparation")
            if _billing_day(conn) != billing_day:
                raise ValueError("Billing settings changed during archive preparation")
            days = [document["row"]["record_date"] for document, _ in documents]
            conn.execute("INSERT INTO report_detail_archives VALUES(?,?,?,?,?,?,?,?,?)", (
                archive_id, kind, relative, digest, len(documents), year, min(days), max(days), datetime.now(UTC).isoformat()))
            if kind == "subject":
                self._store_summaries(conn, archive_id, [document for document, _ in documents], billing_day)
            for document, _ in documents:
                row = document["row"]
                conn.execute("INSERT OR IGNORE INTO report_archive_days VALUES(?,?,?)", (kind, row["device_slot"], row["record_date"]))
                conn.execute(f"DELETE FROM {table} WHERE id=?", (row["id"],))
        return {"id": archive_id, "kind": kind, "events": len(documents), "year": year,
            "source_bytes": size, "archive_bytes": target.stat().st_size, "path": str(target)}

    @staticmethod
    def _verify_file(path, expected):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Report archive integrity check failed")
            found = {}
            for document in ReportDetailArchive._file_documents(conn):
                source_id = document["row"]["id"]
                if source_id in found:
                    raise ValueError("Duplicate daily evidence in archive")
                found[source_id] = document
            # Canonical JSON also normalizes period tuples to lists.
            if _json(found) != _json(expected):
                raise ValueError("Report archive differs from live evidence")
        return _digest(path)

    @staticmethod
    def _file_documents(conn, *, start=None, end=None):
        # Retain read support for earlier source-only row archives. New files
        # compress bounded groups to share repeated labels and JSON field names.
        blocked = conn.execute("SELECT 1 FROM sqlite_master WHERE name='detail_blocks'").fetchone()
        table = "detail_blocks" if blocked else "details"
        filters, values = [], []
        if start:
            filters.append(("last_day" if blocked else "record_date") + ">=?")
            values.append(start.isoformat())
        if end:
            filters.append(("first_day" if blocked else "record_date") + "<=?")
            values.append(end.isoformat())
        where = " WHERE " + " AND ".join(filters) if filters else ""
        for blob, length, digest in conn.execute("SELECT payload,uncompressed_bytes,sha256 FROM " + table + where, values):
            decoded = _decode(blob, length, digest)
            if blocked:
                if not isinstance(decoded, list) or not 1 <= len(decoded) <= 128:
                    raise ValueError("Invalid report archive block")
                yield from decoded
            else:
                yield decoded

    @staticmethod
    def _store_summaries(conn, archive_id, documents, billing_day):
        from services.subject_history import SUBJECT_COLUMNS, subject_record_from_row, aggregate_subject_days
        daily = [(subject_record_from_row([item["row"][key] for key in SUBJECT_COLUMNS]),
            tuple(date.fromisoformat(value) for value in item["period"])) for item in documents]
        for key, bucket in aggregate_subject_days(daily, billing_day).items():
            start, end, slot, identity, kind, subject_id = key
            bucket = {**bucket, "warnings": sorted(bucket["warnings"]), "latest_date": bucket["latest_date"].isoformat()}
            conn.execute("INSERT INTO archived_subject_periods VALUES(?,?,?,?,?,?,?,?)",
                (archive_id, slot, start.isoformat(), end.isoformat(), identity, kind, subject_id, _json(bucket)))

    @staticmethod
    def subject_summaries(conn, slots, *, only_period=None):
        if not slots:
            return {}
        filters = "device_slot IN (" + ",".join("?" for _ in slots) + ")"
        parameters = list(slots)
        if only_period:
            filters += " AND period_start=? AND period_end=?"
            parameters += [value.isoformat() for value in only_period]
        buckets = {}
        for row in conn.execute("SELECT period_start,period_end,device_slot,device_identity,subject_type,subject_id,summary_json "
                "FROM archived_subject_periods WHERE " + filters, parameters):
            key = (date.fromisoformat(row[0]), date.fromisoformat(row[1]), *row[2:6])
            item = json.loads(row[6])
            item["latest_date"] = date.fromisoformat(item["latest_date"])
            item["warnings"] = set(item["warnings"])
            if key not in buckets:
                buckets[key] = item
                continue
            current = buckets[key]
            for name in ("period_usage", "reset_count", "missing_baseline_days", "incomplete_days", "sample_count"):
                current[name] += item[name]
            current["warnings"].update(item["warnings"])
            if item["latest_date"] >= current["latest_date"]:
                for name in ("latest_date", "latest_at", "latest_total", "name", "device_name_snapshot", "device_serial_snapshot"):
                    current[name] = item[name]
        return buckets

    def details(self, conn, kind, slots=None, *, start=None, end=None):
        if kind not in TABLES:
            raise ValueError("Unknown report detail kind")
        query, parameters = "SELECT relative_path,sha256 FROM report_detail_archives WHERE kind=?", [kind]
        if start:
            query += " AND last_day>=?"
            parameters.append(start.isoformat())
        if end:
            query += " AND first_day<=?"
            parameters.append(end.isoformat())
        for relative, digest in conn.execute(query, parameters).fetchall():
            path = self._file(relative)
            if _digest(path) != digest:
                raise ValueError("Report archive checksum mismatch")
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as archive:
                for item in self._file_documents(archive, start=start, end=end):
                    row = item["row"]
                    if slots and row["device_slot"] not in slots:
                        continue
                    day = date.fromisoformat(row["record_date"])
                    if (start and day < start) or (end and day > end):
                        continue
                    yield item
