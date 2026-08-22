from __future__ import annotations

from komi_snmp_profiler.models import Confidence, RawOidValue
from komi_snmp_profiler.oid_dictionary import interpret


def test_maps_printer_serial_number_with_any_index() -> None:
    result = interpret(RawOidValue(".1.3.6.1.2.1.43.5.1.1.17.1", "A12345", "OctetString"))
    assert result.canonical_field == "device.serial_number"
    assert result.confidence == Confidence.MAPPED


def test_konica_private_oid_stays_unknown() -> None:
    result = interpret(RawOidValue("1.3.6.1.4.1.18334.9.9.1", "42", "Counter32", 42))
    assert result.label == "Konica Minolta private OID"
    assert result.canonical_field is None
    assert result.confidence == Confidence.UNKNOWN


def test_maps_recovered_legacy_km_total_and_print_counters() -> None:
    total = interpret(
        RawOidValue("1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0", "219027", "Integer32", 219027)
    )
    print_black = interpret(
        RawOidValue("1.3.6.1.4.1.18334.1.1.1.5.7.2.2.1.5.1.2", "44988", "Integer32", 44988)
    )

    assert total.canonical_field == "counter.total"
    assert total.confidence == Confidence.MAPPED
    assert print_black.canonical_field == "counter.print.black"
    assert print_black.label == "Print Black counter"


def test_legacy_minolta_private_oid_stays_unknown_but_identified() -> None:
    result = interpret(RawOidValue("1.3.6.1.4.1.2590.1.2.3", "9", "Counter32", 9))
    assert result.label == "Konica Minolta private OID"
    assert "legacy" in result.source
    assert result.confidence == Confidence.UNKNOWN


def test_unrecognized_standard_oid_stays_unknown() -> None:
    result = interpret(RawOidValue("1.3.6.1.2.1.999.1", "hello", "OctetString"))
    assert result.confidence == Confidence.UNKNOWN
