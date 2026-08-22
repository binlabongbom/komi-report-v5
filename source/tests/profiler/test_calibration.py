from __future__ import annotations

import pytest

from komi_snmp_profiler.calibration import compare_snapshots
from komi_snmp_profiler.models import Confidence, DeviceSnapshot, InterpretedOid, WebCounterValue


def value(oid: str, number: int) -> InterpretedOid:
    return InterpretedOid(
        oid=oid,
        value=str(number),
        data_type="Counter32",
        canonical_field=None,
        label="Candidate counter",
        description_th="test",
        source="test",
        confidence=Confidence.UNKNOWN,
        numeric_value=number,
    )


def test_compare_returns_only_positive_numeric_changes() -> None:
    before = DeviceSnapshot.create("10.0.0.5", [value("1.2.1", 100), value("1.2.2", 50)])
    after = DeviceSnapshot.create("10.0.0.5", [value("1.2.1", 102), value("1.2.2", 49)])
    deltas = compare_snapshots(before, after, expected_delta=2)
    assert [(item.oid, item.delta) for item in deltas] == [("1.2.1", 2)]
    assert deltas[0].matches_expected is True


def test_compare_rejects_different_devices() -> None:
    before = DeviceSnapshot.create("10.0.0.5", [value("1.2.1", 1)])
    after = DeviceSnapshot.create("10.0.0.6", [value("1.2.1", 2)])
    with pytest.raises(ValueError):
        compare_snapshots(before, after)


def test_compare_includes_verified_web_counter_changes() -> None:
    old = WebCounterValue(
        canonical_field="counter.paper.full_color.a4",
        label="Paper size full_color: A4",
        count=1416,
        category="Paper size full_color",
        source_path="MFP.UserCounterInfo.PaperSheetCounter.FullColorCounterList.FullColorCounter[Type=A4]",
    )
    new = WebCounterValue(
        canonical_field=old.canonical_field,
        label=old.label,
        count=1419,
        category=old.category,
        source_path=old.source_path,
    )
    before = DeviceSnapshot.create("10.0.0.5", [], web_counters=[old])
    after = DeviceSnapshot.create("10.0.0.5", [], web_counters=[new])

    deltas = compare_snapshots(before, after, expected_delta=3)

    assert [(item.canonical_field, item.delta) for item in deltas] == [(old.canonical_field, 3)]
    assert deltas[0].confidence == Confidence.VERIFIED
    assert deltas[0].matches_expected is True
