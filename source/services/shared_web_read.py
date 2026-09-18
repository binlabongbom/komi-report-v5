"""Execute or join one elected Web job from the existing polling worker.

An authenticated adapter supplies publish/fetch. Both operate on immutable
parsed observations, not HTML or databases. No configured provider means the
legacy local collector is used; this module never invents LAN membership.
"""
from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import math
import json
import hashlib
import sqlite3
from threading import Lock
from time import monotonic, sleep

from komi_snmp_profiler.models import MeterReading, WebCounterValue, Confidence, WebAuthState
from services.web_observations import validate_event


@dataclass(frozen=True)
class SharedWebResult:
    reading: MeterReading
    event: dict
    local: bool


class SharedReadExpired(TimeoutError):
    def __init__(self, job_id):
        super().__init__("Shared reader grant expired")
        self.job_id = job_id


class SharedAuthorityUnavailable(ConnectionError):
    def __init__(self, job_id):
        super().__init__("Shared reader authority is unavailable")
        self.job_id = job_id


class SharedWebRead:
    def __init__(self, *, router, current_scope, observations, publish, fetch,
                 wait_seconds=125, clock=monotonic, pause=sleep):
        if not all(callable(value) for value in (current_scope, publish, fetch, clock, pause)):
            raise TypeError("Scoped authenticated Web transfer providers are required")
        if type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds) or not 1 <= wait_seconds <= 300:
            raise ValueError("Invalid shared read wait budget")
        self.router, self.current_scope, self.observations = router, current_scope, observations
        self.publish, self.fetch = publish, fetch
        self.wait_seconds, self.clock, self.pause = wait_seconds, clock, pause
        self._locks = [Lock() for _ in range(3)]
        self._status_lock = Lock()
        self._status = {}

    def _remember(self, routed, job):
        self._job(job, routed.scope)
        now = self.clock()
        with self._status_lock:
            self._status[routed.scope.slot] = {"slot": routed.scope.slot, "authority": routed.authority,
                "reader": job["reader_id"], "job_id": job["job_id"], "phase": job["phase"],
                "observed_at": datetime.now().astimezone().isoformat(),
                "deadline": now + job["remaining_seconds"], "event_id": job["event_id"]}

    def snapshot(self):
        """Last observed job state only; no peer probe, election or DB scan."""
        now = self.clock()
        with self._status_lock:
            rows = [dict(row) for _, row in sorted(self._status.items())]
        for row in rows:
            if row["phase"] == "reading" and row.pop("deadline") <= now:
                row["phase"] = "expired"
            row.pop("deadline", None)
        return rows

    def scheduled_owner(self, slot, *, cancelled=lambda: False):
        scope = self.current_scope(slot)
        chosen = self.router.election.select(scope, cancelled=cancelled)
        return chosen.member_id == self.router.election.member_id

    def prepare(self, slot, *, manual, request_id, cancelled=lambda: False, probe_only=False):
        scope = self.current_scope(slot)
        self._check(scope, cancelled)
        routed = self.router.request(scope, request_id, manual=manual, cancelled=cancelled, probe_only=probe_only)
        if routed is not None:
            self._job(routed.job, scope)
            self._remember(routed, routed.job)
        self._check(scope, cancelled)
        return routed

    def finish_probe(self, routed, *, request_web, cancelled=lambda: False):
        from dataclasses import replace
        self._check(routed.scope, cancelled)
        self.router.election._authorize(routed.authority, routed.scope)
        job = self.router.endpoint(routed.authority).finish_probe(self.router.election.member_id,
            routed.job["job_id"], routed.scope, request_web=request_web)
        self._check(routed.scope, cancelled)
        if job is None:
            with self._status_lock:
                row = self._status.get(routed.scope.slot)
                if row and row["job_id"] == routed.job["job_id"]:
                    row["phase"] = "probe_complete"
            return None
        self._remember(routed, job)
        return replace(routed, job=job)

    def _check(self, scope, cancelled):
        if cancelled():
            raise CancelledError()
        if self.current_scope(scope.slot).document() != scope.document():
            raise PermissionError("Shared read scope changed")
        self.router.election._authorize(self.router.election.member_id, scope)

    def _job(self, job, scope):
        required = {"job_id", "reader_id", "phase", "event_id", "granted", "can_read", "remaining_seconds", "joined"}
        if not isinstance(job, dict) or set(job) != required:
            raise ValueError("Invalid shared read response")
        from services.reader_jobs import _text
        _text(job["job_id"])
        _text(job["reader_id"])
        if (job["phase"] not in {"reading", "complete", "failed", "expired"}
                or any(type(job[key]) is not bool for key in ("granted", "can_read", "joined"))
                or type(job["remaining_seconds"]) not in (float, int)
                or not math.isfinite(job["remaining_seconds"]) or not 0 <= job["remaining_seconds"] <= 300
                or job["can_read"] != (job["phase"] == "reading" and job["reader_id"] == self.router.election.member_id)
                or job["joined"] != (job["reader_id"] != self.router.election.member_id)
                or (job["phase"] == "complete") != (job["event_id"] is not None)):
            raise ValueError("Inconsistent shared read response")
        return self.router.election._authorize(job["reader_id"], scope)

    def _event(self, event, job, scope):
        validate_event(event)
        member = self._job(job, scope)
        p = event["payload"]
        if (p["slot"], p["serial"], p.get("meter_epoch_id"), p["origin"], p["read_id"]) != (
                scope.slot, scope.serial, scope.epoch_id, member.observation_origin, job["job_id"]):
            raise ValueError("Web result does not match the granted job")
        if job["event_id"] is not None and event["id"] != job["event_id"]:
            raise ValueError("Web result does not match the committed result")
        if datetime.fromisoformat(p["observed_at"]) != datetime.fromisoformat(p["reading"]["collected_at"]):
            raise ValueError("Web result time differs from its recorded reading")

    @staticmethod
    def _reading(event):
        p = event["payload"]["reading"]
        return MeterReading(host=p["host"], collected_at=p["collected_at"], source=p["source"],
            auth_state=WebAuthState(p["auth_state"]), warnings=tuple(p["warnings"]), schema_version=p["schema_version"],
            counters=tuple(WebCounterValue(**{**c, "confidence": Confidence(c["confidence"])}) for c in p["counters"]))

    def _read_status(self, routed):
        for attempt in range(2):
            try:
                return self.router.status(routed)
            except (TimeoutError, ConnectionError) as error:
                if attempt:
                    raise SharedAuthorityUnavailable(routed.job["job_id"]) from error

    def collect(self, slot, *, manual, request_id, read, printer_name, cancelled=lambda: False, prepared=None):
        original_scope = self.current_scope(slot)
        self._check(original_scope, cancelled)
        try:
            return self._collect_once(slot, manual=manual, request_id=request_id, read=read,
                printer_name=printer_name, cancelled=cancelled, prepared=prepared)
        except (SharedReadExpired, SharedAuthorityUnavailable) as error:
            # One bounded recovery in the active request, never a new polling
            # timer. Stable recovery IDs keep a retried original request from
            # generating yet another read after recovery already succeeded.
            self._check(original_scope, cancelled)
            if isinstance(error, SharedAuthorityUnavailable):
                self.router.election.invalidate(slot)
            recovery = hashlib.sha256(f"komi.read.recovery:{request_id}:{error.job_id}".encode()).hexdigest()
            return self._collect_once(slot, manual=manual, request_id=recovery, read=read,
                printer_name=printer_name, cancelled=cancelled)

    def _collect_once(self, slot, *, manual, request_id, read, printer_name, cancelled=lambda: False, prepared=None):
        if type(slot) is not int or slot not in range(3):
            raise ValueError("Invalid shared Slot")
        # The outer polling coordinator already joins local requests. Reject
        # accidental concurrent invocation rather than queueing another read.
        if not self._locks[slot].acquire(blocking=False):
            raise RuntimeError("This PC is already handling the Slot read")
        try:
            scope = self.current_scope(slot)
            self._check(scope, cancelled)
            routed = prepared or self.prepare(slot, manual=manual, request_id=request_id, cancelled=cancelled)
            if routed is None:
                return None
            if routed.scope.document() != scope.document():
                raise PermissionError("Prepared read scope changed")
            # Revalidate a prepared grant after SNMP; the lease may have elapsed
            # or another process may have taken over while the probe ran.
            job = self._read_status(routed) if prepared is not None else routed.job
            self._job(job, scope)
            self._remember(routed, job)
            self._check(scope, cancelled)
            if job["phase"] == "reading" and job["remaining_seconds"] <= 0:
                raise SharedReadExpired(job["job_id"])
            if job["can_read"]:
                try:
                    member = self._job(job, scope)
                    with closing(sqlite3.connect(self.observations.path)) as conn:
                        origin = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
                        if not origin or origin[0] != member.observation_origin:
                            raise PermissionError("Local observation identity differs from verified membership")
                        existing = conn.execute("SELECT event_id,document_json,archive_id FROM web_observations WHERE origin_id=? AND read_id=?",
                            (member.observation_origin, job["job_id"])).fetchone()
                    if existing:
                        # Resume after a lost acknowledgement/process crash without
                        # reading the printer again under the same immutable job ID.
                        event = json.loads(self.observations._document(*existing))
                        reading = self._reading(event)
                    else:
                        reading = read()
                        self._check(scope, cancelled)
                        # Local commit includes outgoing evidence and pinned epoch.
                        event = self.observations.record(slot, reading, serial=scope.serial, printer_name=printer_name,
                            at=datetime.fromisoformat(reading.collected_at), read_id=job["job_id"], epoch_id=scope.epoch_id)
                    self._event(event, job, scope)
                except Exception:
                    try:
                        self.router.endpoint(routed.authority).fail(self.router.election.member_id,
                            job["job_id"], scope, reason="web")
                    except Exception:
                        pass  # The bounded lease recovers an unavailable authority.
                    raise
                self._check(scope, cancelled)
                self.router.election._authorize(routed.authority, scope)
                # The authority imports and commits before complete() can expose it.
                if routed.authority != self.router.election.member_id:
                    receipts = self.publish(routed.authority, event, scope)
                    self._check(scope, cancelled)
                    self.router.election._authorize(routed.authority, scope)
                    if not isinstance(receipts, (list, tuple)) or tuple(receipts) != (event["id"],):
                        raise ValueError("Authority did not acknowledge the committed observation")
                    self.observations.acknowledge(routed.authority, receipts)
                self._check(scope, cancelled)
                done = self.router.endpoint(routed.authority).complete(self.router.election.member_id,
                    job["job_id"], scope, event_id=event["id"])
                self._job(done, scope)
                if done["phase"] != "complete" or done["job_id"] != job["job_id"]:
                    raise ValueError("Authority did not confirm the requested read")
                self._event(event, done, scope)
                self._remember(routed, done)
                return SharedWebResult(reading, event, True)
            deadline = self.clock() + min(self.wait_seconds, job["remaining_seconds"] or self.wait_seconds)
            while job["phase"] == "reading":
                self._check(scope, cancelled)
                if self.clock() >= deadline:
                    raise TimeoutError("Timed out waiting for the shared Web result")
                self.pause(min(.25, max(0, deadline - self.clock())))
                updated = self._read_status(routed)
                self._job(updated, scope)
                if updated["job_id"] != job["job_id"] or updated["reader_id"] != job["reader_id"]:
                    raise ValueError("Authority changed the joined read")
                job = updated
                self._remember(routed, job)
            self._check(scope, cancelled)
            if job["phase"] == "expired":
                raise SharedReadExpired(job["job_id"])
            if job["phase"] != "complete":
                raise RuntimeError("Shared Web read failed or expired")
            event = self.fetch(routed.authority, job["event_id"], scope)
            self._check(scope, cancelled)
            self.router.election._authorize(routed.authority, scope)
            self._event(event, job, scope)
            self.observations.receive([event], expected_slot=slot, expected_serial=scope.serial, expected_epoch=scope.epoch_id)
            return SharedWebResult(self._reading(event), event, False)
        finally:
            self._locks[slot].release()
