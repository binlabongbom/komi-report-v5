"""Durable first-grant/join semantics at an already authorized coordinator.

This is NOT membership, discovery or reader election. Callers must inject a
verified member+scope provider and an elected authority's current scope. No
production network endpoint or collection suppression is enabled by this module.
Each authority process uses a fresh boot ID; monotonic leases never survive a
restart. Partitioned authorities can both read; immutable Web evidence converges
later by the counter rules, not by summing their observations.
"""
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import json
import math
import sqlite3
from time import monotonic
import uuid

from database import get_db_path


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Invalid reader job identity")
    return value


@dataclass(frozen=True)
class ReadScope:
    company_id: str
    slot: int
    serial: str
    settings_revision: str
    epoch_id: str

    def document(self):
        if type(self.slot) is not int or self.slot not in range(3):
            raise ValueError("Invalid reader slot")
        for value in (self.company_id, self.serial, self.settings_revision, self.epoch_id):
            _text(value)
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class VerifiedReader:
    member_id: str
    observation_origin: str
    scope: ReadScope


class ReaderJobs:
    def __init__(self, *, authorize, current_scope, path=None, clock=monotonic, authority_ready=None):
        if not callable(authorize) or not callable(current_scope):
            raise ValueError("Verified membership and current scope providers are required")
        self.path = path or get_db_path()
        self.authorize = authorize
        self.current_scope = current_scope
        self.clock = clock
        if authority_ready is not None and not callable(authority_ready):
            raise TypeError("Reader authority check must be callable")
        self.authority_ready = authority_ready
        self.boot_id = uuid.uuid4().hex
        # One instance per authority lifetime, constructed only after runtime
        # ownership is acquired. Fence an accidentally surviving old instance.
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO reader_authority_state VALUES(1,?)", (self.boot_id,))

    @contextmanager
    def _write(self, scope):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT boot_id FROM reader_authority_state WHERE singleton_id=1").fetchone()
            if current is None or current[0] != self.boot_id:
                raise ValueError("Reader authority ownership changed")
            yield conn
            if (self.current_scope(scope.slot).document() != scope.document()
                    or (self.authority_ready is not None and self.authority_ready(scope) is not True)):
                raise PermissionError("Reader authority or scope changed during transaction")
            self._active_epoch(conn, scope)

    def _member(self, member_id, scope):
        _text(member_id)
        expected = scope.document()
        if self.authority_ready is not None and self.authority_ready(scope) is not True:
            raise PermissionError("This member no longer owns reader coordination")
        member = self.authorize(member_id, scope.slot)
        if (not isinstance(member, VerifiedReader) or member.member_id != member_id
                or member.scope.document() != expected
                or self.current_scope(scope.slot).document() != expected):
            raise PermissionError("Reader membership or shared slot scope is not current")
        _text(member.observation_origin)
        return member, expected

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid authority clock")
        return value

    @staticmethod
    def _active_epoch(conn, scope):
        from services.slot_epoch_store import SlotEpochStore
        if SlotEpochStore._head(conn, scope.slot) != scope.epoch_id:
            raise ValueError("Reviewed slot epoch is not active for this read")
        epoch = SlotEpochStore._epoch(conn, scope.epoch_id)
        anchor = epoch["document"]["baseline_event"]["payload"]
        if (anchor["slot"], anchor["serial"]) != (scope.slot, scope.serial):
            raise ValueError("Reviewed slot epoch does not match the granted printer")

    def _expire(self, conn, slot, scope, now):
        conn.execute("""UPDATE reader_jobs SET phase='expired',reason='authority_restart_or_scope_or_deadline'
            WHERE device_slot=? AND phase='reading'
              AND (authority_boot!=? OR scope_json!=? OR deadline<=?)""",
            (slot, self.boot_id, scope, now))

    @staticmethod
    def _result(row, member_id, now, *, granted=False):
        return {"job_id": row["id"], "reader_id": row["reader_id"], "phase": row["phase"],
            "event_id": row["event_id"], "granted": granted,
            "can_read": row["phase"] == "reading" and row["reader_id"] == member_id,
            "remaining_seconds": max(0.0, row["deadline"] - now) if row["phase"] == "reading" else 0,
            "joined": row["reader_id"] != member_id}

    def request(self, member_id, request_id, scope, *, lease_seconds=120):
        """First accepted request gets one job; later requests join it.

        A repeated request ID returns its original job even after completion or
        expiry. A new deliberate read uses a new request ID. Never use client
        timestamps to decide who was first. Schedule anchors live in the caller.
        """
        _text(request_id)
        if type(lease_seconds) not in (float, int) or not math.isfinite(lease_seconds) or not 5 <= lease_seconds <= 300:
            raise ValueError("Reader lease must be between 5 and 300 seconds")
        with self._write(scope) as conn:
            member, encoded = self._member(member_id, scope)
            self._active_epoch(conn, scope)
            now = self._now()
            self._expire(conn, scope.slot, encoded, now)
            previous = conn.execute("SELECT scope_json,job_id FROM reader_job_requests WHERE member_id=? AND request_id=?",
                (member_id, request_id)).fetchone()
            if previous:
                if previous[0] != encoded:
                    raise ValueError("Read request ID was reused for a different scope")
                row = conn.execute("SELECT * FROM reader_jobs WHERE id=?", (previous[1],)).fetchone()
                return self._result(row, member_id, now)
            row = conn.execute("SELECT * FROM reader_jobs WHERE device_slot=? AND phase='reading'", (scope.slot,)).fetchone()
            granted = row is None
            if granted:
                job_id = uuid.uuid4().hex
                conn.execute("""INSERT INTO reader_jobs(id,authority_boot,scope_json,device_slot,reader_id,reader_origin,
                    created_at,deadline,phase) VALUES(?,?,?,?,?,?,?,?, 'reading')""",
                    (job_id, self.boot_id, encoded, scope.slot, member_id, member.observation_origin,
                     datetime.now(UTC).isoformat(), now + lease_seconds))
                row = conn.execute("SELECT * FROM reader_jobs WHERE id=?", (job_id,)).fetchone()
            conn.execute("INSERT INTO reader_job_requests VALUES(?,?,?,?)", (member_id, request_id, encoded, row["id"]))
            return self._result(row, member_id, now, granted=granted)

    def status(self, member_id, job_id, scope):
        _text(job_id)
        with self._write(scope) as conn:
            _, encoded = self._member(member_id, scope)
            now = self._now()
            self._expire(conn, scope.slot, encoded, now)
            row = conn.execute("SELECT * FROM reader_jobs WHERE id=? AND scope_json=?", (job_id, encoded)).fetchone()
            if row is None:
                raise ValueError("Unknown reader job for this scope")
            return self._result(row, member_id, now)

    def complete(self, member_id, job_id, scope, *, event_id):
        """Expose a result only after its Web observation is durably committed.

        A stale reader cannot complete a newer grant. Its late Web evidence may
        still be retained and shared independently for later reconciliation.
        """
        _text(job_id)
        _text(event_id)
        with self._write(scope) as conn:
            member, encoded = self._member(member_id, scope)
            self._active_epoch(conn, scope)
            now = self._now()
            row = conn.execute("SELECT * FROM reader_jobs WHERE id=? AND scope_json=?", (job_id, encoded)).fetchone()
            if row is None or row["reader_id"] != member_id or row["reader_origin"] != member.observation_origin:
                raise PermissionError("Only the granted reader may complete this job")
            if row["phase"] == "complete" and row["event_id"] == event_id:
                return self._result(row, member_id, now)
            if row["phase"] != "reading" or row["authority_boot"] != self.boot_id or row["deadline"] <= now:
                raise ValueError("Reader grant expired or was already completed")
            event = conn.execute("SELECT origin_id,read_id,device_slot,device_serial FROM web_observations WHERE event_id=?",
                (event_id,)).fetchone()
            if event is None or tuple(event) != (member.observation_origin, job_id, scope.slot, scope.serial):
                raise ValueError("Committed Web observation does not match the granted read")
            assigned = conn.execute("SELECT 1 FROM slot_meter_assignments WHERE event_id=? AND epoch_id=?",
                (event_id, scope.epoch_id)).fetchone()
            if assigned is None:
                raise ValueError("Committed Web observation has no matching reviewed epoch")
            conn.execute("UPDATE reader_jobs SET phase='complete',event_id=? WHERE id=?", (event_id, job_id))
            row = conn.execute("SELECT * FROM reader_jobs WHERE id=?", (job_id,)).fetchone()
            return self._result(row, member_id, now)

    def fail(self, member_id, job_id, scope, *, reason):
        if reason not in {"snmp", "web", "timeout", "cancelled", "storage"}:
            raise ValueError("Unknown reader failure reason")
        with self._write(scope) as conn:
            _, encoded = self._member(member_id, scope)
            row = conn.execute("SELECT * FROM reader_jobs WHERE id=? AND scope_json=?", (job_id, encoded)).fetchone()
            if row is None or row["reader_id"] != member_id:
                raise PermissionError("Only the granted reader may fail this job")
            if row["phase"] == "reading" and row["authority_boot"] == self.boot_id:
                conn.execute("UPDATE reader_jobs SET phase='failed',reason=? WHERE id=?", (reason, job_id))
