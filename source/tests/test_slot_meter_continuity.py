from copy import deepcopy
from datetime import datetime, UTC
import hashlib
import json

import pytest

from services.device_config import DeviceConfig, DeviceConfigRepository
from services.slot_meter_continuity import (
    EpochObservation, project_epoch, reviewed_epoch, verify_parent_carry, validate_epoch,
)
from services.web_observations import WebObservationStore, _json
from test_subject_history import _reading


def event(serial, value, day, *, slot=0):
    DeviceConfigRepository().replace_all([DeviceConfig(slot, "Fixture", "192.0.2.10", serial=serial)])
    at = datetime(2026, 9, day, 10, tzinfo=UTC)
    return WebObservationStore().record(slot, _reading(value, collected_at=at), at=at, serial=serial, printer_name="Fixture")


def initial(anchor):
    return reviewed_epoch(anchor, actor="PC-A", reason="Verified first printer")


def total(result):
    return next(item for item in result.counters if json.loads(item.key)[0] == "counter.user.total.total")


def assigned(epoch, *events):
    return [EpochObservation(epoch["id"], item) for item in events]


def test_used_replacement_counts_2000_plus_50100_minus_50000_across_days():
    old = initial(event("OLD", 1900, 16))
    old_final = event("OLD", 2000, 17)
    baseline = event("USED", 50000, 18)
    replacement = reviewed_epoch(baseline, parent=old, parent_observations=assigned(old, old_final),
        operation="replacement", actor="PC-A", reason="Old printer unavailable; use last recorded meter")
    assert total(project_epoch(replacement, [])).slot_total == 2000
    later = event("USED", 50100, 19)
    expected = project_epoch(replacement, assigned(replacement, later))
    assert total(expected).slot_total == 2100
    assert total(expected).physical_maximum == 50100
    assert total(expected).epoch_usage == 100
    assert project_epoch(replacement, assigned(replacement, later, baseline, later)) == expected
    verify_parent_carry(replacement, old, assigned(old, old_final))


def test_three_peers_converge_despite_reversed_duplicate_arrivals():
    old = initial(event("OLD", 2000, 16))
    replacement = reviewed_epoch(event("USED", 50000, 17), parent=old, operation="replacement", actor="A", reason="Verified replacement")
    one, two = event("USED", 50020, 18), event("USED", 50100, 19)
    projections = [project_epoch(replacement, assigned(replacement, *items))
        for items in ((one, two), (two, one, two), (one, one, two))]
    assert projections[0] == projections[1] == projections[2]
    assert total(projections[0]).slot_total == 2100


def test_same_serial_reset_requires_separate_explicit_epoch_and_preserves_total():
    old = initial(event("SAME", 2000, 16))
    low = event("SAME", 50, 17)
    unreviewed = project_epoch(old, assigned(old, low))
    assert total(unreviewed).slot_total == 2000
    assert "lower_counter_or_clock_conflict" in unreviewed.issues
    reset = reviewed_epoch(low, parent=old, parent_observations=assigned(old, low), operation="reset",
        actor="A", reason="Confirmed physical counter reset")
    later = event("SAME", 80, 18)
    assert total(project_epoch(reset, assigned(reset, later))).slot_total == 2030
    with pytest.raises(ValueError, match="assignment"):
        project_epoch(reset, assigned(old, later))
    with pytest.raises(ValueError, match="distinguish"):
        reviewed_epoch(low, parent=old, operation="replacement", actor="A", reason="wrong kind")


def test_late_old_evidence_requires_amendment_and_cannot_silently_change_carry():
    old = initial(event("OLD", 2000, 16))
    replacement = reviewed_epoch(event("USED", 50000, 18), parent=old, operation="replacement", actor="A", reason="Last recorded old meter")
    late_old = event("OLD", 2010, 17)
    with pytest.raises(ValueError, match="amendment"):
        verify_parent_carry(replacement, old, assigned(old, late_old))
    assert total(project_epoch(replacement, [])).slot_total == 2000
    with pytest.raises(ValueError, match="different"):
        project_epoch(replacement, assigned(replacement, late_old))


def test_two_replacements_retain_each_carry_without_adding_absolute_values():
    old = initial(event("OLD", 2000, 16))
    second = reviewed_epoch(event("USED", 50000, 17), parent=old, operation="replacement", actor="A", reason="second")
    second_final = event("USED", 50100, 18)
    third = reviewed_epoch(event("THIRD", 9000, 19), parent=second, parent_observations=assigned(second, second_final),
        operation="replacement", actor="B", reason="third")
    assert total(project_epoch(third, assigned(third, event("THIRD", 9050, 20)))).slot_total == 2150


def test_maximum_uses_its_own_observation_time_not_last_arrival_or_later_lower_value():
    epoch = initial(event("A", 2000, 16))
    high, later_low = event("A", 2100, 17), event("A", 2080, 18)
    result = project_epoch(epoch, assigned(epoch, later_low, high))
    counter = total(result)
    assert counter.slot_total == 2100
    assert counter.observed_at == high["payload"]["observed_at"]
    assert counter.evidence_id == high["id"]
    assert "lower_counter_or_clock_conflict" in result.issues


def test_tampered_carry_or_missing_subject_identity_cannot_be_accepted():
    epoch = initial(event("OLD", 2000, 16))
    changed = deepcopy(epoch)
    next(iter(changed["document"]["carried"].values()))[0] += 10
    with pytest.raises(ValueError):
        validate_epoch(changed)
    anonymous = deepcopy(epoch["document"]["baseline_event"])
    for counter in anonymous["payload"]["reading"]["counters"]:
        counter["subject_id"] = None
    anonymous["id"] = hashlib.sha256(_json(anonymous["payload"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="stable subject"):
        initial(anonymous)


def test_new_counter_needs_baseline_and_missing_old_counter_is_retained():
    old = initial(event("OLD", 2000, 16))
    baseline = event("USED", 50000, 17)
    baseline["payload"]["reading"]["counters"] = baseline["payload"]["reading"]["counters"][:1]
    baseline["id"] = hashlib.sha256(_json(baseline["payload"]).encode()).hexdigest()
    replacement = reviewed_epoch(baseline, parent=old, operation="replacement", actor="A", reason="Verified only available counters")
    before = project_epoch(replacement, [])
    assert "counter_missing_on_replacement" in before.issues
    missing = next(item for item in before.counters if item.physical_maximum is None)
    assert missing.slot_total == 1000  # Former print-bw meter is preserved, never zeroed.
    result = project_epoch(replacement, assigned(replacement, event("USED", 50100, 18)))
    assert "counter_without_reviewed_baseline" in result.issues
