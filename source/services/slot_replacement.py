"""Local replacement review foundation; confirmation is never automatic.

Mixed-printer days remain held for billing. Peer decisions, subject counters and
the replacement UI must be integrated before this can be a complete workflow.
"""
from copy import deepcopy
from datetime import datetime
import math
import uuid

from database import _open


def capture_candidate(state, identity, reading, stamp, counters):
    """Quarantine a newer observation without changing the old printer's usage."""
    from services.daily_cache import _timestamp

    if not identity.get("serial") or reading.host != identity.get("host") or not counters:
        return
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < 0 for value in counters.values()):
        return
    observed = stamp.isoformat()
    previous = state.get("replacement_candidate", {}).get("observed_at") or state.get("last_success")
    if previous and _timestamp(observed) <= _timestamp(previous):
        return
    state["replacement_candidate"] = {
        "device_identity": deepcopy(identity), "baseline": dict(counters),
        "observed_at": observed, "schema_version": reading.schema_version,
        "source": {"name": reading.source, "auth_state": reading.auth_state.value,
                   "schema_version": reading.schema_version,
                   "counter_sources": {item.canonical_field: {"label": item.label,
                       "source_path": item.source_path} for item in reading.counters
                       if item.subject_type is None}},
    }


def _candidate(cache, slot, day, path):
    from services.daily_cache import _device_identity_snapshot

    with _open(commit=False) as conn:
        if conn.execute("SELECT 1 FROM daily_meter_records WHERE device_slot=? AND record_date=?",
                        (slot, day.isoformat())).fetchone():
            raise ValueError("Finalized days require an amended report")
    state = cache._load_unlocked(slot, day, path)
    candidate = (state or {}).get("replacement_candidate")
    if not candidate:
        raise ValueError("Read the replacement printer before reviewing")
    old = state.get("device_identity", {})
    current = _device_identity_snapshot(slot)
    captured = candidate["device_identity"]
    if (not old.get("serial") or not current.get("serial")
            or old["serial"] == current["serial"]
            or any(current.get(key) != captured.get(key) for key in ("serial", "host"))):
        raise ValueError("Replacement identity changed or is not a different known serial")
    if (candidate["schema_version"] != state.get("source", {}).get("schema_version")
            or set(candidate["baseline"]) != set(state.get("latest", {}))):
        raise ValueError("Counter mapping changed; review mappings before replacing")
    return state, candidate


def preview_replacement(cache, slot, day):
    path = cache.path(slot, day)
    with cache._path_lock(path):
        state, candidate = _candidate(cache, slot, day, path)
        return {"revision": cache._review_revision(state),
                "old_identity": deepcopy(state["device_identity"]),
                "new_identity": deepcopy(candidate["device_identity"]),
                "old_latest": deepcopy(state["latest"]),
                "baseline": deepcopy(candidate["baseline"]),
                "observed_at": candidate["observed_at"],
                "preserved_delta": deepcopy(state["delta"])}


def confirm_replacement(cache, slot, day, *, expected_revision, actor, reason, at=None):
    from services.daily_cache import _timestamp

    stamp = at or datetime.now().astimezone()
    if stamp.date() != day or not actor.strip() or not reason.strip():
        raise ValueError("Replacement needs today's observation, actor and reason")
    path = cache.path(slot, day)
    with cache._path_lock(path):
        state, candidate = _candidate(cache, slot, day, path)
        if cache._review_revision(state) != expected_revision:
            raise ValueError("Replacement changed after preview")
        if _timestamp(stamp.isoformat()) < _timestamp(candidate["observed_at"]):
            raise ValueError("Confirmation cannot precede observation")
        audit = {"id": str(uuid.uuid4()), "actor": actor.strip(), "reason": reason.strip(),
                 "confirmed_at": stamp.isoformat(), "old_identity": deepcopy(state["device_identity"]),
                 "new_identity": deepcopy(candidate["device_identity"]),
                 "baseline": deepcopy(candidate["baseline"]), "observed_at": candidate["observed_at"],
                 "preserved_delta": deepcopy(state["delta"])}
        # Preserve the old segment's evidence; do not nest prior segment lists.
        state.setdefault("device_segments", []).append({key: deepcopy(state.get(key)) for key in (
            "device_identity", "opening", "latest", "delta", "first_success", "last_success",
            "source", "resets", "counter_review", "counter_resolutions")})
        state.setdefault("slot_replacements", []).append(audit)
        state["device_identity"] = deepcopy(candidate["device_identity"])
        state["opening"] = deepcopy(candidate["baseline"])
        state["latest"] = deepcopy(candidate["baseline"])
        state["last_success"] = candidate["observed_at"]
        state["source"] = deepcopy(candidate["source"])
        state["resets"], state["counter_review"], state["counter_resolutions"] = [], {}, []
        state["sample_count"] = int(state.get("sample_count", 0)) + 1
        # Retain identity_conflict for the existing billing hold. This API must
        # never attest that a mixed-printer day is safe to invoice.
        state["unsafe_reconciliation_seen"] = True
        del state["replacement_candidate"]
        cache._atomic_write(path, state)
        return audit
