from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from database import _open, get_cfg, get_db_path
from komi_snmp_profiler.models import MeterReading
from services.pricing import PricingRepository
from services.reconciliation import ReconciliationReport

log = logging.getLogger(__name__)


def _counter_reviews_before(slot: int, day: date, identity: dict) -> dict:
    """Carry unresolved reviews even when Web succeeds without an SNMP heartbeat."""
    with _open(commit=False) as conn:
        row = conn.execute(
            "SELECT source_json FROM daily_meter_records WHERE device_slot=? AND record_date<? ORDER BY record_date DESC LIMIT 1",
            (slot, day.isoformat()),
        ).fetchone()
    if row is None:
        return {}
    try:
        source = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(source, dict) or not isinstance(source.get("device_identity"), dict):
        return {}
    reviews = source.get("counter_review", {})
    return reviews if isinstance(reviews, dict) and _identity_matches(source["device_identity"], identity) else {}


def _device_identity_snapshot(slot: int) -> dict[str, str]:
    with _open(commit=False) as conn:
        row = conn.execute("SELECT name,serial,host FROM devices WHERE slot=?", (slot,)).fetchone()
    name, serial, host = row or ("", "", "")
    return {"name": name or "", "serial": serial or "", "host": host or ""}


def _identity_conflicts(captured: dict, current: dict) -> bool:
    old_serial = str(captured.get("serial") or "").strip()
    new_serial = str(current.get("serial") or "").strip()
    if old_serial and new_serial:
        return old_serial != new_serial
    old_host = str(captured.get("host") or "").strip()
    new_host = str(current.get("host") or "").strip()
    return bool(old_host and new_host and old_host != new_host)


def _identity_matches(captured: dict, current: dict) -> bool:
    old_serial = str(captured.get("serial") or "").strip()
    new_serial = str(current.get("serial") or "").strip()
    if old_serial and new_serial:
        return old_serial == new_serial
    old_host = str(captured.get("host") or "").strip()
    new_host = str(current.get("host") or "").strip()
    return bool(old_host and new_host and old_host == new_host)


def _timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.timestamp()


def _counter_map(reading: MeterReading) -> dict[str, int | float]:
    return {
        item.canonical_field: item.count
        for item in reading.counters
        if item.subject_type is None
    }


@dataclass(frozen=True)
class DailyMeterRecord:
    device_slot: int
    record_date: str
    opening: dict[str, int | float]
    closing: dict[str, int | float]
    delta: dict[str, int | float]
    first_success: str | None
    last_success: str | None
    sample_count: int
    error_count: int
    incomplete: bool


class DailyCacheStore:
    _path_locks_guard = threading.Lock()
    _path_locks: dict[str, threading.RLock] = {}

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_db_path().parent / "runtime-cache"

    def path(self, slot: int, day: date) -> Path:
        return self.root / f"device-{slot + 1}" / f"{day.isoformat()}.json"

    def load(self, slot: int, day: date) -> dict | None:
        path = self.path(slot, day)
        with self._path_lock(path):
            return self._load_unlocked(slot, day, path)

    @staticmethod
    def _review_revision(state: dict) -> str:
        return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _review_candidate(self, slot: int, day: date, key: str, path: Path) -> tuple[dict, dict]:
        with _open(commit=False) as conn:
            if conn.execute("SELECT 1 FROM daily_meter_records WHERE device_slot=? AND record_date=?", (slot, day.isoformat())).fetchone():
                raise ValueError("Finalized days require a separate amended-report workflow")
        state = self._load_unlocked(slot, day, path)
        if not state or key not in state.get("counter_review", {}):
            raise ValueError("No unresolved review for this counter")
        identity = _device_identity_snapshot(slot)
        if not identity.get("serial") or not _identity_matches(state.get("device_identity", {}), identity):
            raise ValueError("Read and confirm the current printer serial before resolving a counter")
        if not state.get("sample_count") or key not in state.get("latest", {}):
            raise ValueError("A current Web counter observation is required")
        return state, identity

    def preview_counter_baseline(self, slot: int, day: date, key: str) -> dict:
        """Prepare review data only; never clears a hold or edits usage."""
        path = self.path(slot, day)
        with self._path_lock(path):
            state, identity = self._review_candidate(slot, day, key, path)
            issue = state["counter_review"][key]
            return {"revision": self._review_revision(state), "device_identity": identity,
                    "label": state.get("source", {}).get("counter_sources", {}).get(key, {}).get("label", key),
                    "key": key, "before": issue["before"], "detected_at": issue["at"],
                    "baseline": state["latest"][key], "observed_at": state["last_success"],
                    "preserved_delta": state["delta"].get(key, 0)}

    def confirm_counter_baseline(self, slot: int, day: date, key: str, *,
                                 expected_revision: str, actor: str, reason: str,
                                 at: datetime | None = None) -> dict:
        """Resume future counting from the reviewed observation, with atomic audit.

        The resolution day remains held for billing; historical totals are never
        recalculated here. Call only after the user confirms the preview.
        """
        stamp = at or datetime.now().astimezone()
        if stamp.date() != day or not actor.strip() or not reason.strip():
            raise ValueError("Resolution needs today's observation, actor and reason")
        path = self.path(slot, day)
        with self._path_lock(path):
            state, identity = self._review_candidate(slot, day, key, path)
            if self._review_revision(state) != expected_revision:
                raise ValueError("Counter changed after preview; review the latest values again")
            if _timestamp(stamp.isoformat()) < _timestamp(state["last_success"]):
                raise ValueError("Resolution cannot precede its observation")
            issue = state["counter_review"][key]
            resolution = {"id": str(uuid.uuid4()), "key": key, "review_at": issue["at"],
                          "previous_counter": issue["before"], "baseline": state["latest"][key],
                          "observed_at": state["last_success"], "resolved_at": stamp.isoformat(),
                          "actor": actor.strip(), "reason": reason.strip(), "device_identity": identity,
                          "preserved_delta": state["delta"].get(key, 0)}
            state.setdefault("counter_resolutions", []).append(resolution)
            del state["counter_review"][key]
            self._atomic_write(path, state)
            return resolution

    @classmethod
    def _path_lock(cls, path: Path) -> threading.RLock:
        key = str(path.absolute())
        with cls._path_locks_guard:
            return cls._path_locks.setdefault(key, threading.RLock())

    def _load_unlocked(self, slot: int, day: date, path: Path) -> dict | None:
        if not path.exists():
            return None
        raw = path.read_bytes()
        try:
            state = json.loads(raw)
            self._validate_state(state, slot=slot, day=day)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            return self._quarantine_corrupt_unlocked(
                path,
                slot=slot,
                day=day,
                raw=raw,
                reason=f"{type(exc).__name__}: {exc}",
            )
        return state

    @staticmethod
    def _validate_state(state: object, *, slot: int, day: date) -> None:
        if not isinstance(state, dict):
            raise ValueError("cache root must be an object")
        if int(state.get("device_slot", -1)) != slot:
            raise ValueError("cache device_slot does not match its path")
        if state.get("record_date") != day.isoformat():
            raise ValueError("cache record_date does not match its path")
        for key in ("opening", "latest", "delta", "source"):
            if not isinstance(state.get(key), dict):
                raise ValueError(f"cache {key} must be an object")
        for key in ("sample_count", "error_count"):
            value = int(state.get(key, 0))
            if value < 0:
                raise ValueError(f"cache {key} cannot be negative")

    def _quarantine_corrupt_unlocked(
        self,
        path: Path,
        *,
        slot: int,
        day: date,
        raw: bytes,
        reason: str,
    ) -> dict:
        detected_at = datetime.now().astimezone().isoformat(timespec="seconds")
        digest = hashlib.sha256(raw).hexdigest()
        quarantine = path.with_name(f"{path.name}.corrupt-{uuid.uuid4().hex}")
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        # Copy first and fsync before replacing the working path. A crash can
        # therefore leave duplicate evidence, but can never erase the only copy.
        with quarantine.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        identity = _device_identity_snapshot(slot)
        state = {
            "schema_version": "komi.daily.cache.v2",
            "device_slot": slot,
            "record_date": day.isoformat(),
            "opening": {},
            "latest": {},
            "delta": {},
            "resets": [],
            "first_success": None,
            "last_success": None,
            "sample_count": 0,
            "error_count": 1,
            "source": {},
            "heartbeat_count": 0,
            "last_checked": detected_at,
            "last_status": "cache_corrupt",
            "last_error": {
                "at": detected_at,
                "message": "Daily cache JSON corrupt; original preserved for review",
            },
            "device_identity": identity,
            "unsafe_reconciliation_seen": True,
            "cache_corruption": {
                "detected_at": detected_at,
                "reason": reason[:500],
                "sha256": digest,
                "byte_count": len(raw),
                "quarantine_path": str(quarantine),
            },
        }
        self._atomic_write(path, state)
        log.error(
            "daily cache corrupt; evidence quarantined: path=%s quarantine=%s sha256=%s",
            path,
            quarantine,
            digest,
        )
        try:
            from services.pipeline_log import pipeline_log

            pipeline_log.append(
                stage="RAM",
                action="Daily cache corruption quarantined",
                device_slot=slot,
                device_name=identity.get("name", ""),
                host=identity.get("host", ""),
                target=str(quarantine),
                value=f"sha256={digest}",
                detail=f"working cache replaced by review marker · {reason[:300]}",
                status="error",
            )
        except Exception:
            log.exception("could not append cache corruption event to Sync Log")
        return state

    def update_reading(
        self,
        slot: int,
        reading: MeterReading,
        *,
        at: datetime | None = None,
        reconciliation: ReconciliationReport | None = None,
    ) -> dict:
        stamp = at or datetime.fromisoformat(reading.collected_at.replace("Z", "+00:00")).astimezone()
        path = self.path(slot, stamp.date())
        with self._path_lock(path):
            return self._update_reading_unlocked(
                slot,
                reading,
                stamp=stamp,
                reconciliation=reconciliation,
            )

    def _update_reading_unlocked(
        self,
        slot: int,
        reading: MeterReading,
        *,
        stamp: datetime,
        reconciliation: ReconciliationReport | None,
    ) -> dict:
        day = stamp.date()
        current = _counter_map(reading)
        loaded = self._load_unlocked(slot, day, self.path(slot, day))
        identity = _device_identity_snapshot(slot)
        state = loaded or {
            "schema_version": "komi.daily.cache.v2",
            "device_slot": slot,
            "record_date": day.isoformat(),
            "opening": current,
            "latest": current,
            "delta": {key: 0 for key in current},
            "resets": [],
            "first_success": stamp.isoformat(timespec="seconds"),
            "last_success": stamp.isoformat(timespec="seconds"),
            "sample_count": 0,
            "error_count": 0,
            "source": {},
            "heartbeat_count": 0,
            "last_checked": None,
            "last_status": "pending",
            "device_identity": identity,
            "counter_review": _counter_reviews_before(slot, day, identity),
        }
        from services.slot_cache_bridge import bridge_device_state
        bridge_device_state(slot, state, reading, stamp)
        captured_identity = state.get("device_identity")
        if isinstance(captured_identity, dict) and _identity_conflicts(captured_identity, identity):
            from services.slot_replacement import capture_candidate
            capture_candidate(state, identity, reading, stamp, current)
            state["identity_conflict"] = {
                "captured": captured_identity,
                "current": identity,
                "at": stamp.isoformat(timespec="seconds"),
            }
            self._atomic_write(self.path(slot, day), state)
            return state
        if not isinstance(captured_identity, dict):
            state["device_identity"] = identity
        elif not captured_identity.get("serial") and identity.get("serial"):
            state["device_identity"] = identity
        if not state.get("first_success"):
            state["opening"] = current
            state["latest"] = current
            state["first_success"] = stamp.isoformat(timespec="seconds")
        previous = state.get("latest", {})
        previous_stamp = state.get("last_success")
        incoming_stamp = stamp.isoformat(timespec="seconds")
        if loaded is not None and int(state.get("sample_count", 0)) > 0 and previous_stamp:
            try:
                ordering = (_timestamp(incoming_stamp) > _timestamp(previous_stamp)) - (
                    _timestamp(incoming_stamp) < _timestamp(previous_stamp)
                )
            except (TypeError, ValueError):
                ordering = -1
            if ordering < 0 or (ordering == 0 and current != previous):
                state["out_of_order"] = True
                state["rejected_sample_count"] = int(state.get("rejected_sample_count", 0)) + 1
                state.setdefault("ordering_issues", []).append(
                    {
                        "at": incoming_stamp,
                        "last_success": previous_stamp,
                        "reason": "late_sample" if ordering < 0 else "same_timestamp_conflict",
                    }
                )
                self._atomic_write(self.path(slot, day), state)
                return state
            if ordering == 0:
                state["duplicate_sample_count"] = int(state.get("duplicate_sample_count", 0)) + 1
                self._atomic_write(self.path(slot, day), state)
                return state

        previous_source = state.get("source")
        previous_schema = (
            str(previous_source.get("schema_version") or "")
            if isinstance(previous_source, dict)
            else ""
        )
        if (
            loaded is not None
            and int(state.get("sample_count", 0)) > 0
            and previous_schema
            and previous_schema != reading.schema_version
        ):
            # A parser override (or any other normalization schema) changed
            # after this day's baseline was captured.  Mixing the two counter
            # sets could turn an absolute meter from the new schema into usage
            # and could reuse a billing-safe attestation from the old schema.
            # Start a fresh zero-delta baseline and keep the day fail-closed.
            state["normalization_rebaseline"] = {
                "at": incoming_stamp,
                "from_schema": previous_schema,
                "to_schema": reading.schema_version,
            }
            state["unsafe_reconciliation_seen"] = True
            state["opening"] = current
            state["latest"] = current
            state["delta"] = {key: 0 for key in current}
            state["resets"] = []
            previous = current
        delta = state.setdefault("delta", {})
        if "counter_review" not in state:
            state["counter_review"] = _counter_reviews_before(slot, day, identity)
        pending = state["counter_review"]
        # A smaller absolute counter is not proof that counting restarted at
        # zero. Keep observations, but require an explicit baseline decision.
        for reset in state.get("resets", []):
            if any(item["key"] == reset["key"] and item["review_at"] == reset["at"]
                   for item in state.get("counter_resolutions", [])):
                continue
            pending.setdefault(reset["key"], dict(reset))
        for key, value in current.items():
            old = previous.get(key)
            if key in pending:
                pending[key]["latest_observed"] = value
                pending[key]["last_observed_at"] = incoming_stamp
                delta.setdefault(key, 0)
            elif old is None:
                delta.setdefault(key, 0)
            elif value >= old:
                delta[key] = delta.get(key, 0) + (value - old)
            else:
                issue = {"key": key, "before": old, "after": value, "at": stamp.isoformat()}
                state.setdefault("resets", []).append(issue)
                pending[key] = {**issue, "latest_observed": value, "last_observed_at": incoming_stamp}
                delta.setdefault(key, 0)
                from services.pipeline_log import pipeline_log
                pipeline_log.append(
                    stage="CACHE", action="มิเตอร์ลดลง · รอตรวจสอบค่าเริ่มต้น",
                    device_slot=slot, target=key, value=f"{old} → {value}",
                    detail="ไม่นำมิเตอร์เดิมมาบวกเป็นยอดใช้งาน และยังไม่ตั้ง baseline ใหม่อัตโนมัติ",
                    status="warning", at=stamp,
                )
        state["latest"] = current
        state["schema_version"] = "komi.daily.cache.v2"
        state["last_success"] = incoming_stamp
        state["sample_count"] = int(state.get("sample_count", 0)) + 1
        state["source"] = {
            "name": reading.source,
            "auth_state": reading.auth_state.value,
            "schema_version": reading.schema_version,
            "counter_sources": {
                item.canonical_field: {
                    "label": item.label,
                    "source_path": item.source_path,
                }
                for item in reading.counters
                if item.subject_type is None
            },
            "device_identity": state.get("device_identity", identity),
        }
        if reconciliation is not None:
            state["source"]["reconciliation"] = {
                "profile_id": reconciliation.profile_id,
                "checked_count": reconciliation.checked_count,
                "needs_review": reconciliation.needs_review,
                "billing_safe": reconciliation.billing_safe,
                "issues": [
                    {
                        "code": issue.code,
                        "message": issue.message(),
                        "breakdown": issue.breakdown(),
                    }
                    for issue in reconciliation.issues
                ],
            }
            if not reconciliation.billing_safe:
                state["unsafe_reconciliation_seen"] = True
        self._atomic_write(self.path(slot, day), state)
        return state

    def record_heartbeat(
        self,
        slot: int,
        *,
        total: int,
        toner: dict[str, int] | None = None,
        paper: list[dict[str, int | str | None]] | None = None,
        paper_alerts: list[str] | None = None,
        at: datetime | None = None,
    ) -> dict:
        stamp = at or datetime.now().astimezone()
        path = self.path(slot, stamp.date())
        with self._path_lock(path):
            return self._record_heartbeat_unlocked(
                slot,
                total=total,
                toner=toner,
                paper=paper,
                paper_alerts=paper_alerts,
                stamp=stamp,
            )

    def _record_heartbeat_unlocked(
        self,
        slot: int,
        *,
        total: int,
        toner: dict[str, int] | None,
        paper: list[dict[str, int | str | None]] | None,
        paper_alerts: list[str] | None,
        stamp: datetime,
    ) -> dict:
        day = stamp.date()
        state = self._load_unlocked(slot, day, self.path(slot, day))
        identity = _device_identity_snapshot(slot)
        if state is None:
            with _open(commit=False) as conn:
                previous = conn.execute(
                    """SELECT closing_json,source_json FROM daily_meter_records
                       WHERE device_slot=? ORDER BY record_date DESC LIMIT 1""",
                    (slot,),
                ).fetchone()
            previous_identity: dict = {}
            previous_source: dict = {}
            if previous:
                try:
                    previous_source = json.loads(previous[1])
                except (TypeError, json.JSONDecodeError):
                    previous_source = {}
                if isinstance(previous_source, dict) and isinstance(previous_source.get("device_identity"), dict):
                    previous_identity = previous_source["device_identity"]
            identity_matches = bool(previous and _identity_matches(previous_identity, identity))
            carried = json.loads(previous[0]) if identity_matches else {}
            state = {
                "schema_version": "komi.daily.cache.v1",
                "device_slot": slot,
                "record_date": day.isoformat(),
                "opening": carried,
                "latest": carried,
                "delta": {key: 0 for key in carried},
                "resets": [],
                "first_success": stamp.isoformat(timespec="seconds") if carried else None,
                "last_success": stamp.isoformat(timespec="seconds") if carried else None,
                "sample_count": 0,
                "error_count": 0,
                "source": {"name": "carry_forward_snmp", "schema_version": "komi.daily.cache.v1"},
                "device_identity": identity,
                "counter_review": _counter_reviews_before(slot, day, identity),
            }
            if previous and not identity_matches:
                state["identity_baseline_mismatch"] = {
                    "previous": previous_identity,
                    "current": identity,
                    "at": stamp.isoformat(timespec="seconds"),
                }
        captured_identity = state.get("device_identity")
        if isinstance(captured_identity, dict) and _identity_conflicts(captured_identity, identity):
            state["identity_conflict"] = {
                "captured": captured_identity,
                "current": identity,
                "at": stamp.isoformat(timespec="seconds"),
            }
            self._atomic_write(self.path(slot, day), state)
            return state
        if not isinstance(captured_identity, dict):
            state["device_identity"] = identity
        elif not captured_identity.get("serial") and identity.get("serial"):
            state["device_identity"] = identity
        state["heartbeat_count"] = int(state.get("heartbeat_count", 0)) + 1
        state["last_checked"] = stamp.isoformat(timespec="seconds")
        state["last_status"] = "online"
        state["last_snmp_total"] = max(0, int(total))
        if toner:
            state["snmp_toner"] = {
                color: max(0, min(100, int(toner[color])))
                for color in ("C", "Y", "M", "K")
                if color in toner
            }
        if paper is not None:
            # Status telemetry is independent from billing counters. An empty
            # result means this model did not expose the optional input table;
            # replace old data so the UI says it cannot read a current status.
            state["snmp_paper"] = paper
        if paper_alerts is not None:
            state["snmp_paper_alerts"] = paper_alerts
        self._atomic_write(self.path(slot, day), state)
        return state

    def record_error(self, slot: int, day: date, message: str, *, at: datetime | None = None) -> dict:
        stamp = at or datetime.now().astimezone()
        path = self.path(slot, day)
        with self._path_lock(path):
            return self._record_error_unlocked(slot, day, message, stamp=stamp)

    def _record_error_unlocked(
        self,
        slot: int,
        day: date,
        message: str,
        *,
        stamp: datetime,
    ) -> dict:
        stamp_text = stamp.isoformat(timespec="seconds")
        state = self._load_unlocked(slot, day, self.path(slot, day)) or {
            "schema_version": "komi.daily.cache.v1",
            "device_slot": slot,
            "record_date": day.isoformat(),
            "opening": {},
            "latest": {},
            "delta": {},
            "resets": [],
            "first_success": None,
            "last_success": None,
            "sample_count": 0,
            "error_count": 0,
            "source": {},
            "heartbeat_count": 0,
            "last_checked": None,
            "last_status": "pending",
            "device_identity": _device_identity_snapshot(slot),
        }
        state["error_count"] = int(state.get("error_count", 0)) + 1
        state["last_error"] = {"at": stamp_text, "message": message[:500]}
        state["last_checked"] = stamp_text
        state["last_status"] = "offline"
        self._atomic_write(self.path(slot, day), state)
        return state

    def finalize(self, slot: int, day: date, *, incomplete: bool = False) -> DailyMeterRecord | None:
        path = self.path(slot, day)
        with self._path_lock(path):
            return self._finalize_unlocked(slot, day, incomplete=incomplete)

    def _finalize_unlocked(self, slot: int, day: date, *, incomplete: bool) -> DailyMeterRecord | None:
        state = self._load_unlocked(slot, day, self.path(slot, day))
        if state is None:
            return None
        has_web_success = bool(state.get("first_success"))
        has_observation = bool(state.get("heartbeat_count") or state.get("error_count"))
        if not has_web_success and not has_observation:
            return None
        # A heartbeat/error proves that the device was polled, but cannot be
        # promoted into meter usage when Web Connection returned no counters.
        if "counter_review" not in state:
            state["counter_review"] = _counter_reviews_before(slot, day, state.get("device_identity", {}))
        incomplete = bool(incomplete or not has_web_success)
        opening = state.get("opening", {}) if has_web_success else {}
        closing = state.get("latest", {}) if has_web_success else {}
        delta = state.get("delta", {}) if has_web_success else {}
        from services.billing_ledger import FORMULA_VERSION

        pricing = PricingRepository()
        categories = {
            key: pricing.get_category(slot, key, day).value
            for key in delta
        }
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        source_payload = {
            **state.get("source", {}),
            "billing_ledger_expected": FORMULA_VERSION,
            "device_identity": state.get("device_identity", {}),
            "identity_conflict": state.get("identity_conflict"),
            "identity_baseline_mismatch": state.get("identity_baseline_mismatch"),
            "replacement_candidate": state.get("replacement_candidate"),
            "device_segments": state.get("device_segments", []),
            "slot_replacements": state.get("slot_replacements", []),
            "slot_epoch": state.get("slot_epoch"),
            "reset_detected": bool(state.get("resets") or state.get("counter_review") or state.get("counter_resolutions")),
            "counter_review": state.get("counter_review", {}),
            "counter_resolutions": state.get("counter_resolutions", []),
            "out_of_order": bool(state.get("out_of_order")),
            "ordering_issues": state.get("ordering_issues", []),
            "unsafe_reconciliation_seen": bool(state.get("unsafe_reconciliation_seen")),
            "cache_corruption": state.get("cache_corruption"),
            "heartbeat_count": int(state.get("heartbeat_count", 0)),
            "last_checked": state.get("last_checked"),
            "last_status": state.get("last_status", "pending"),
        }
        if not has_web_success:
            source_payload["missing_web_success"] = True
            for evidence_key in ("last_error", "last_snmp_total", "snmp_toner"):
                if evidence_key in state:
                    source_payload[evidence_key] = state[evidence_key]
        payload = (
            json.dumps(opening, ensure_ascii=False, sort_keys=True),
            json.dumps(closing, ensure_ascii=False, sort_keys=True),
            json.dumps(delta, ensure_ascii=False, sort_keys=True),
            json.dumps(categories, ensure_ascii=False, sort_keys=True),
            json.dumps(source_payload, ensure_ascii=False, sort_keys=True),
            state.get("first_success"),
            state.get("last_success"),
            int(state.get("sample_count", 0)),
            int(state.get("error_count", 0)),
            int(incomplete),
        )
        with _open() as conn:
            result = conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(device_slot,record_date) DO NOTHING
                   RETURNING id""",
                (
                    slot,
                    day.isoformat(),
                    *payload,
                    now,
                ),
            )
            inserted = result.fetchone()
            existing = None if inserted else conn.execute(
                """SELECT id,opening_json,closing_json,delta_json,category_json,source_json,
                          first_success,last_success,sample_count,error_count,incomplete
                   FROM daily_meter_records WHERE device_slot=? AND record_date=?""",
                (slot, day.isoformat()),
            ).fetchone()
        record = DailyMeterRecord(
            device_slot=slot,
            record_date=day.isoformat(),
            opening=opening,
            closing=closing,
            delta=delta,
            first_success=state.get("first_success"),
            last_success=state.get("last_success"),
            sample_count=int(state.get("sample_count", 0)),
            error_count=int(state.get("error_count", 0)),
            incomplete=incomplete,
        )
        if inserted:
            from services.billing_ledger import post_daily_record
            ledger_id = post_daily_record(int(inserted[0]))
            if ledger_id is None:
                return None
            self.path(slot, day).unlink(missing_ok=True)
            return record

        if existing is None or tuple(existing[1:]) != payload:
            state["finalization_conflict"] = {
                "detected_at": now,
                "existing_record_id": int(existing[0]) if existing else None,
                "reason": "same_day_source_evidence_differs",
            }
            self._atomic_write(self.path(slot, day), state)
            return None

        # Crash-safe retry: the immutable daily row already exists and matches
        # the cache exactly. Ensure its ledger event exists before deleting cache.
        from services.billing_ledger import post_daily_record
        if post_daily_record(int(existing[0])) is not None:
            self.path(slot, day).unlink(missing_ok=True)
        return None

    def finalize_before(
        self,
        today: date,
        *,
        exclude_slots: set[int] | frozenset[int] | None = None,
    ) -> list[DailyMeterRecord]:
        records: list[DailyMeterRecord] = []
        if not self.root.exists():
            return records
        excluded = exclude_slots or set()
        for path in sorted(self.root.glob("device-*/*.json")):
            try:
                slot = int(path.parent.name.removeprefix("device-")) - 1
                day = date.fromisoformat(path.stem)
            except ValueError:
                log.error("daily cache path is not recognizable; preserving evidence: path=%s", path)
                continue
            if slot in excluded or day >= today:
                continue
            try:
                with self._path_lock(path):
                    state = self._load_unlocked(slot, day, path)
                    if state is None:
                        continue
                    last_checked = state.get("last_checked")
                    complete = state.get("last_status") == "online" and bool(last_checked)
                    if complete:
                        try:
                            work_end = get_cfg("work_end", "17:00")
                            hour, minute = (int(part) for part in work_end.split(":", 1))
                            checked = datetime.fromisoformat(last_checked)
                            complete = checked.timetz().replace(tzinfo=None) >= time(hour, minute)
                        except (TypeError, ValueError):
                            complete = False
                    record = self._finalize_unlocked(slot, day, incomplete=not complete)
            except OSError:
                log.exception("daily cache finalization failed; preserving evidence: path=%s", path)
                continue
            if record:
                records.append(record)
        return records

    def repair_pending_ledger(self) -> int:
        """Recover safely after a crash between source insert and ledger post."""
        from services.billing_ledger import FORMULA_VERSION, post_daily_record
        with _open(commit=False) as conn:
            rows = conn.execute("""SELECT d.id,d.source_json FROM daily_meter_records d
                WHERE NOT EXISTS (SELECT 1 FROM billing_ledger l WHERE l.source_daily_record_id=d.id)""").fetchall()
        repaired = 0
        for record_id, source_json in rows:
            try:
                source = json.loads(source_json)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(source, dict) or source.get("billing_ledger_expected") != FORMULA_VERSION:
                continue
            try:
                repaired += int(post_daily_record(int(record_id)) is not None)
            except Exception:
                log.exception("pending billing ledger repair failed: daily_record_id=%s", record_id)
        return repaired

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
