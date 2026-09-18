"""Verified compressed yearly Web evidence, read only when history is requested.

Files are immutable bounded chunks inside year folders. Hot sequence/identity
and delivery metadata stay in SQLite; only the large parsed payload moves.
"""
from calendar import monthrange
from contextlib import closing
from datetime import date, datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
import zlib
from time import monotonic

from database import get_db_path
from services.web_observations import MAX_EVENT_BYTES, MAX_PAGE_BYTES, validate_event


def detail_cutoff(today: date) -> date:
    return today.replace(year=today.year - 1, day=min(today.day, monthrange(today.year - 1, today.month)[1]))


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode(blob, expected_id, expected_bytes):
    if type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_EVENT_BYTES + 1024:
        raise ValueError("Invalid archived payload size")
    decoder = zlib.decompressobj()
    encoded = decoder.decompress(blob, expected_bytes + 1)
    if (len(encoded) != expected_bytes or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
        raise ValueError("Damaged or oversized archived payload")
    document = encoded.decode("utf-8")
    event = json.loads(document)
    validate_event(event)
    if event["id"] != expected_id:
        raise ValueError("Archived observation identity mismatch")
    return document


class WebObservationArchive:
    def __init__(self, database_path=None):
        self.path = Path(database_path or get_db_path()).resolve()
        self.root = self.path.parent / "archives" / "web-observations"

    def _file(self, relative):
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("Archive path is outside its data directory")
        return target

    def list(self):
        """Metadata-only; never open archive payload files during startup."""
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("SELECT id,year,event_count,relative_path,sha256 FROM web_observation_archives ORDER BY year,id").fetchall()

    def stats(self, *, today=None):
        with closing(sqlite3.connect(self.path)) as conn:
            eligible = conn.execute("SELECT COUNT(*) FROM web_observations WHERE archive_id IS NULL AND observed_at<?",
                (detail_cutoff(today or date.today()).isoformat(),)).fetchone()[0]
            archived, files = conn.execute("SELECT COALESCE(SUM(event_count),0),COUNT(*) FROM web_observation_archives").fetchone()
        return {"eligible": eligible, "archived": archived, "files": files}

    @staticmethod
    def _verify_file(path, expected):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as archive:
            if archive.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Archive SQLite integrity check failed")
            found = set()
            for event_id, blob, length in archive.execute("SELECT event_id,payload,uncompressed_bytes FROM observations"):
                document = _decode(blob, event_id, length)
                if expected.get(event_id) != document:
                    raise ValueError("Archive verification differs from live evidence")
                found.add(event_id)
            if found != set(expected):
                raise ValueError("Archive is missing observations")
        return _digest(path)

    def archive_batch(self, *, today=None, limit=128):
        """Archive one bounded chunk; retain every live payload on any failure.

        File verification and rename precede the hot-database transaction. A
        crash can leave an orphan archive copy, never a missing only copy.
        Current/recent payloads, queue state and sequence cursors stay intact.
        """
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("Invalid archive batch limit")
        cutoff = detail_cutoff(today or date.today()).isoformat()
        with closing(sqlite3.connect(self.path)) as conn:
            rows, size, year = [], 0, None
            for sequence, event_id, observed, document in conn.execute("""SELECT sequence,event_id,observed_at,document_json
                FROM web_observations WHERE archive_id IS NULL AND observed_at<? ORDER BY observed_at,sequence LIMIT ?""",
                (cutoff, limit)):
                event_year = date.fromisoformat(observed[:10]).year
                length = len(document.encode("utf-8"))
                if rows and (year != event_year or size + length > MAX_PAGE_BYTES):
                    break
                validate_event(json.loads(document))
                rows.append((sequence, event_id, document))
                size += length
                year = event_year
        if not rows:
            return None
        archive_id = uuid.uuid4().hex
        relative = f"{year}/{archive_id}.sqlite3"
        target = self._file(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        # A fresh random file; existing archives are never modified in place.
        with closing(sqlite3.connect(temporary)) as archive, archive:
            archive.execute("PRAGMA synchronous=FULL")
            archive.execute("CREATE TABLE observations(event_id TEXT PRIMARY KEY,payload BLOB NOT NULL,uncompressed_bytes INTEGER NOT NULL)")
            for _, event_id, document in rows:
                encoded = document.encode("utf-8")
                archive.execute("INSERT INTO observations VALUES(?,?,?)", (event_id, zlib.compress(encoded), len(encoded)))
        expected = {event_id: document for _, event_id, document in rows}
        digest = self._verify_file(temporary, expected)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO web_observation_archives VALUES(?,?,?,?,?,?)",
                         (archive_id, relative, digest, len(rows), year, datetime.now(UTC).isoformat()))
            for sequence, event_id, document in rows:
                changed = conn.execute("""UPDATE web_observations SET document_json='',archive_id=?
                    WHERE sequence=? AND event_id=? AND document_json=? AND archive_id IS NULL""",
                    (archive_id, sequence, event_id, document)).rowcount
                if changed != 1:
                    raise ValueError("Live observation changed while preparing archive")
        return {"id": archive_id, "year": year, "events": len(rows), "source_bytes": size,
                "archive_bytes": target.stat().st_size, "sha256": digest, "path": str(target)}

    def read_document(self, archive_id, event_id):
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute("SELECT relative_path FROM web_observation_archives WHERE id=?", (archive_id,)).fetchone()
        if row is None:
            raise ValueError("Missing archive catalog entry")
        path = self._file(row[0])
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as archive:
            row = archive.execute("SELECT payload,uncompressed_bytes FROM observations WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("Missing archived observation")
        return _decode(row[0], event_id, row[1])


def run_archive_batches(archive, cancelled, *, today=None, seconds=20):
    """Bound each maintenance job; cancellation waits only for its atomic chunk."""
    start = monotonic()
    events = 0
    while not cancelled.is_set() and monotonic() - start < seconds:
        batch = archive.archive_batch(today=today)
        if batch is None:
            break
        events += batch["events"]
    return {"events": events, **archive.stats(today=today)}
