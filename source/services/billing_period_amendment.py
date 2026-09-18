"""Rebuild hot archived subject summaries for explicitly reviewed period changes.

Cold files remain immutable. Call inside the same transaction as ledger
replacements, only in response to a requested historical recalculation.
"""
from contextlib import closing
from copy import deepcopy
from datetime import date
import sqlite3

from services.billing_ledger import _source_hash
from services.report_detail_archive import ReportDetailArchive, _billing_day, _json, _digest

MAX_ARCHIVES = 32
MAX_DETAIL_BYTES = 64 * 1024 * 1024


def prepare_archives(conn, changed):
    keys = {(row["device_slot"], row["record_date"]) for row in changed
            if (row["old_period_start"], row["old_period_end"]) != (row["period_start"], row["period_end"])}
    if not keys:
        return [], _source_hash([])
    archive = ReportDetailArchive(conn.execute("PRAGMA database_list").fetchone()[2])
    dates = [key[1] for key in keys]
    catalog = conn.execute("""SELECT id,relative_path,sha256,row_count FROM report_detail_archives
        WHERE kind='subject' AND last_day>=? AND first_day<=? ORDER BY id""",
        (min(dates), max(dates))).fetchall()
    if len(catalog) > MAX_ARCHIVES:
        raise ValueError("ช่วงนี้มี Archive มาก กรุณาเลือกช่วงวันที่สั้นลง")
    prepared, signatures, size = [], [], 0
    for archive_id, relative, digest, count in catalog:
        path = archive._file(relative)
        if _digest(path) != digest:
            raise ValueError("Report archive checksum mismatch")
        documents = []
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as cold:
            for document in archive._file_documents(cold):
                size += len(_json(document).encode("utf-8"))
                if size > MAX_DETAIL_BYTES:
                    raise ValueError("รายละเอียด Archive มากเกินไป กรุณาเลือกช่วงวันที่สั้นลง")
                documents.append(document)
        if len(documents) != count:
            raise ValueError("Report archive count mismatch")
        # Range overlap is conservative; only rebuild files containing changed days.
        if not any((item["row"]["device_slot"], item["row"]["record_date"]) in keys for item in documents):
            continue
        summaries = conn.execute("SELECT * FROM archived_subject_periods WHERE archive_id=? ORDER BY device_slot,period_start,period_end,device_identity,subject_type,subject_id",
                                 (archive_id,)).fetchall()
        signatures.append((archive_id, digest, count, summaries))
        prepared.append((archive_id, documents))
    return prepared, _source_hash(signatures)


def rebuild_archives(conn, prepared):
    archive = ReportDetailArchive(conn.execute("PRAGMA database_list").fetchone()[2])
    for archive_id, frozen in prepared:
        documents = deepcopy(frozen)
        periods = {}
        for item in documents:
            row = item["row"]
            key = row["device_slot"], row["record_date"]
            if key not in periods:
                periods[key] = conn.execute("""SELECT period_start,period_end FROM billing_ledger
                    WHERE device_slot=? AND record_date=? ORDER BY id DESC LIMIT 1""", key).fetchone()
            if periods[key]:
                item["period"] = list(periods[key])
            # Validate before deleting any summary (the outer transaction also rolls back).
            for value in item["period"]:
                date.fromisoformat(value)
        conn.execute("DELETE FROM archived_subject_periods WHERE archive_id=?", (archive_id,))
        archive._store_summaries(conn, archive_id, documents, _billing_day(conn))
