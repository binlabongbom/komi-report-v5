"""Deterministic continuity across explicitly reviewed physical-counter epochs.

This reducer never guesses epoch membership from a timestamp or a smaller
counter. The caller must supply verified epoch assignments. Creating a reviewed
definition does not change devices, settings, invoices or the active epoch.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import json

from services.web_observations import validate_event


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fraction(value):
    return Fraction(Decimal(str(value)))


def counter_key(counter):
    return _json([counter["canonical_field"], counter["subject_type"], counter["subject_id"]])


def counter_values(event):
    validate_event(event)
    result = {}
    for counter in event["payload"]["reading"]["counters"]:
        if not counter["canonical_field"].startswith("counter."):
            continue
        if counter["subject_type"] and not counter["subject_id"]:
            raise ValueError("A stable subject ID is required before carrying its meter")
        key, value = counter_key(counter), _fraction(counter["count"])
        if key in result and result[key] != value:
            raise ValueError("Conflicting values for one stable counter identity")
        result[key] = value
    if not result:
        raise ValueError("No cumulative Web counters in baseline")
    return result


def _encoded_number(value):
    return [value.numerator, value.denominator]


def _number(pair):
    if (not isinstance(pair, list) or len(pair) != 2 or any(type(value) is not int for value in pair)
            or pair[0] < 0 or pair[1] <= 0):
        raise ValueError("Invalid exact meter amount")
    return Fraction(*pair)


def validate_epoch(epoch):
    if not isinstance(epoch, dict) or set(epoch) != {"id", "document"}:
        raise ValueError("Invalid meter epoch envelope")
    doc = epoch["document"]
    if (not isinstance(doc, dict) or set(doc) != {"format", "parent", "operation", "baseline_event",
            "carried", "parent_evidence", "actor", "reason"}
            or doc["format"] != "komi.slot-meter-epoch.v1"
            or doc["operation"] not in {"initial", "replacement", "reset"}
            or not isinstance(doc["carried"], dict) or not doc["carried"]
            or not isinstance(doc["parent_evidence"], list)
            or any(not isinstance(value, str) or len(value) != 64 for value in doc["parent_evidence"])
            or doc["parent_evidence"] != sorted(set(doc["parent_evidence"]))):
        raise ValueError("Invalid meter epoch definition")
    for key in ("actor", "reason"):
        if not isinstance(doc[key], str) or not doc[key].strip() or len(doc[key]) > 1000:
            raise ValueError("Epoch review actor and reason are required")
    if doc["operation"] == "initial":
        if doc["parent"] is not None or doc["parent_evidence"]:
            raise ValueError("Initial epoch cannot have a parent")
    elif not isinstance(doc["parent"], str) or len(doc["parent"]) != 64:
        raise ValueError("A reviewed parent epoch is required")
    baseline = counter_values(doc["baseline_event"])
    for key, pair in doc["carried"].items():
        if not isinstance(key, str):
            raise ValueError("Invalid stable counter identity")
        parts = json.loads(key)
        if (not isinstance(parts, list) or len(parts) != 3 or not isinstance(parts[0], str)
                or not parts[0].startswith("counter.") or _json(parts) != key
                or any(value is not None and not isinstance(value, str) for value in parts[1:])
                or (parts[1] and not parts[2])):
            raise ValueError("Invalid stable counter identity")
        _number(pair)
    if not baseline.keys() <= doc["carried"].keys():
        raise ValueError("Baseline counters have no reviewed carried value")
    if doc["operation"] == "initial" and {key: _number(value) for key, value in doc["carried"].items()} != baseline:
        raise ValueError("Initial slot meter must start from the observed physical meter")
    encoded = _json(doc).encode("utf-8")
    if len(encoded) > 8 * 1024 * 1024 or hashlib.sha256(encoded).hexdigest() != epoch["id"]:
        raise ValueError("Altered meter epoch")
    return doc


@dataclass(frozen=True)
class EpochObservation:
    epoch_id: str
    event: dict


@dataclass(frozen=True)
class SlotCounter:
    key: str
    physical_maximum: Fraction | None
    slot_total: Fraction
    epoch_usage: Fraction
    observed_at: str | None
    evidence_id: str | None


@dataclass(frozen=True)
class SlotProjection:
    epoch_id: str
    counters: tuple[SlotCounter, ...]
    evidence_ids: tuple[str, ...]
    issues: tuple[str, ...]


def project_epoch(epoch, observations):
    doc = validate_epoch(epoch)
    anchor = doc["baseline_event"]
    payload = anchor["payload"]
    baseline = counter_values(anchor)
    unique = {anchor["id"]: anchor}
    jobs = {(payload["origin"], payload["read_id"]): anchor["id"]}
    for assigned in observations:
        if not isinstance(assigned, EpochObservation) or assigned.epoch_id != epoch["id"]:
            raise ValueError("Observation has no matching reviewed epoch assignment")
        event = assigned.event
        validate_event(event)
        other = event["payload"]
        if (other["slot"], other["serial"]) != (payload["slot"], payload["serial"]):
            raise ValueError("Observation belongs to a different slot or physical printer")
        job = (other["origin"], other["read_id"])
        if job in jobs and jobs[job] != event["id"]:
            raise ValueError("Conflicting results for the same read job")
        jobs[job] = event["id"]
        unique[event["id"]] = event
    schemas = {event["payload"]["reading"]["schema_version"] for event in unique.values()}
    issues = set()
    if len(schemas) != 1:
        issues.add("normalization_schema_changed")
    series = {}
    for event_id, event in unique.items():
        at = event["payload"]["observed_at"]
        for key, value in counter_values(event).items():
            if key not in baseline:
                issues.add("counter_without_reviewed_baseline")
                continue
            series.setdefault(key, []).append((datetime.fromisoformat(at), value, event_id, at))
    counters = []
    for key, encoded in sorted(doc["carried"].items()):
        carry = _number(encoded)
        if key not in baseline:
            counters.append(SlotCounter(key, None, carry, Fraction(), None, None))
            issues.add("counter_missing_on_replacement")
            continue
        points = series[key]
        best = max(points, key=lambda point: (point[1], point[0], point[2]))
        usage = max(Fraction(), best[1] - baseline[key])
        high = baseline[key]
        # Values determine the current meter; timestamps only flag an ambiguous
        # history. A fall never starts a new epoch or adds the next absolute.
        for _at, value, _id, _text in sorted(points):
            if value < high:
                issues.add("lower_counter_or_clock_conflict")
            high = max(high, value)
        counters.append(SlotCounter(key, best[1], carry + usage, usage, best[3], best[2]))
    return SlotProjection(epoch["id"], tuple(counters), tuple(sorted(unique)), tuple(sorted(issues)))


def reviewed_epoch(baseline_event, *, actor, reason, parent=None, parent_observations=(), operation="initial"):
    """Prepare a content-addressed review decision; caller commits it atomically.

    Replacement carry is computed from the parent's evidence, not user-entered
    arithmetic. Late parent evidence needs a separate amendment, never a silent
    rewrite of an already-confirmed carry or issued financial report.
    """
    values = counter_values(baseline_event)
    if parent is None:
        if operation != "initial" or parent_observations:
            raise ValueError("Initial epoch cannot inherit another reading history")
        carried, evidence, parent_id = values, [], None
    else:
        previous = validate_epoch(parent)
        left, right = previous["baseline_event"]["payload"], baseline_event["payload"]
        if left["slot"] != right["slot"]:
            raise ValueError("A replacement must preserve its shared slot")
        if left["reading"]["schema_version"] != right["reading"]["schema_version"]:
            raise ValueError("Review normalization mappings before carrying slot meters")
        if operation not in {"replacement", "reset"} or (left["serial"] == right["serial"]) != (operation == "reset"):
            raise ValueError("Review must distinguish a replacement from a same-printer reset")
        projection = project_epoch(parent, parent_observations)
        if {"normalization_schema_changed", "counter_without_reviewed_baseline"}.intersection(projection.issues):
            raise ValueError("Review counter mappings and missing baselines first")
        carried = {item.key: item.slot_total for item in projection.counters}
        for key in values:
            carried.setdefault(key, Fraction())
        evidence, parent_id = list(projection.evidence_ids), parent["id"]
    doc = {"format": "komi.slot-meter-epoch.v1", "parent": parent_id, "operation": operation,
        "baseline_event": baseline_event, "carried": {key: _encoded_number(value) for key, value in sorted(carried.items())},
        "parent_evidence": evidence, "actor": actor, "reason": reason}
    epoch = {"id": hashlib.sha256(_json(doc).encode("utf-8")).hexdigest(), "document": doc}
    validate_epoch(epoch)
    return epoch


def verify_parent_carry(epoch, parent, parent_observations):
    """Require the exact reviewed parent evidence when accepting a decision."""
    doc = validate_epoch(epoch)
    rebuilt = reviewed_epoch(doc["baseline_event"], actor=doc["actor"], reason=doc["reason"],
        parent=parent, parent_observations=parent_observations, operation=doc["operation"])
    if rebuilt != epoch:
        raise ValueError("Parent evidence or carried slot meter changed; review an amendment")
