from __future__ import annotations

from komi_snmp_profiler.counter_analyzer import analyze_counter_candidates
from komi_snmp_profiler.models import Confidence, RawOidValue


def value(oid: str, raw: str, data_type: str = "Integer32") -> RawOidValue:
    return RawOidValue(oid, raw, data_type, int(raw))


def test_decodes_standard_marker_life_count_and_unit() -> None:
    candidates = analyze_counter_candidates(
        [
            value("1.3.6.1.2.1.43.10.2.1.3.1.1", "7"),
            value("1.3.6.1.2.1.43.10.2.1.4.1.1", "12345", "Counter32"),
        ]
    )

    assert len(candidates) == 1
    assert candidates[0].label == "ปริมาณสะสมตลอดอายุเครื่อง"
    assert candidates[0].unit == "impressions"
    assert candidates[0].numeric_value == 12345
    assert candidates[0].confidence == Confidence.MAPPED


def test_surfaces_vendor_numeric_values_without_claiming_their_meaning() -> None:
    candidates = analyze_counter_candidates(
        [value("1.3.6.1.4.1.18334.9.9.1", "6789")]
    )

    assert len(candidates) == 1
    assert candidates[0].label == "Konica Minolta numeric candidate"
    assert candidates[0].unit == "unknown"
    assert candidates[0].confidence == Confidence.UNKNOWN


def test_ignores_non_km_integer_that_is_not_an_snmp_counter() -> None:
    assert analyze_counter_candidates([value("1.3.6.1.2.1.1.7.0", "72")]) == []


def test_prioritizes_known_km_counter_profile_over_unknown_private_candidate() -> None:
    candidates = analyze_counter_candidates(
        [value("1.3.6.1.4.1.18334.1.1.1.5.7.2.2.1.5.2.2", "146436")]
    )

    assert len(candidates) == 1
    assert candidates[0].label == "Print Color counter"
    assert candidates[0].confidence == Confidence.MAPPED
