from __future__ import annotations

import pytest

from komi_snmp_profiler.connectors import (
    ReadOnlyWebConnectionSession,
    TlsPolicy,
    WebConnectionCounterConnector,
)


def test_web_connection_tls_verification_is_default() -> None:
    session = ReadOnlyWebConnectionSession("192.0.2.10")
    connector = WebConnectionCounterConnector()

    assert session.tls_policy == TlsPolicy(mode="system")
    assert connector.tls_policy == TlsPolicy(mode="system")


def test_insecure_tls_requires_explicit_setting_and_emits_warning() -> None:
    with pytest.warns(RuntimeWarning, match="verification disabled"):
        session = ReadOnlyWebConnectionSession("192.0.2.10", verify_tls=False)

    assert session.tls_policy.mode == "insecure"


def test_fingerprint_policy_normalizes_colon_separated_sha256() -> None:
    fingerprint = ":".join(["ab"] * 32)

    assert TlsPolicy(mode="fingerprint", fingerprint_sha256=fingerprint).fingerprint_sha256 == "ab" * 32

    with pytest.raises(ValueError, match="SHA-256"):
        TlsPolicy(mode="fingerprint", fingerprint_sha256="too-short")


def test_parse_counter_info_extracts_a3_a4_by_color() -> None:
    info = {
        "TotalCounterList": {
            "TotalCounter": [
                {"Type": "Total", "Count": "2339"},
                {"Type": "Paper", "Count": "2041"},
            ]
        },
        "PaperSheetCounter": {
            "BlackCounterList": {
                "BlackCounter": [
                    {"Type": "A3", "Count": "9"},
                    {"Type": "A4", "Count": "453"},
                ]
            },
            "FullColorCounterList": {
                "FullColorCounter": [
                    {"Type": "A3", "Count": "151"},
                    {"Type": "A4", "Count": "1416"},
                ]
            },
            "DoubleColorCounterList": {
                "DoubleColorCounter": [{"Type": "A4", "Count": "9"}]
            },
        },
    }

    values = WebConnectionCounterConnector._parse_counter_info(info)
    by_field = {item.canonical_field: item.count for item in values}

    assert by_field["counter.paper.black.a3"] == 9
    assert by_field["counter.paper.black.a4"] == 453
    assert by_field["counter.paper.full_color.a3"] == 151
    assert by_field["counter.paper.full_color.a4"] == 1416
    assert by_field["counter.paper.single_two_color.a4"] == 9
    assert by_field["counter.total.total"] == 2339


def test_parse_counter_info_includes_copy_print_and_scan() -> None:
    info = {
        "CopyCounterList": {"CopyCounter": [{"Type": "BwTotal", "Count": "124"}]},
        "PrintCounterList": {"PrintCounter": [{"Type": "FullColorTotal", "Count": "1759"}]},
        "ScanFaxCounterList": {"ScanFaxCounter": [{"Type": "DocumentReadTotal", "Count": "1483"}]},
    }

    values = WebConnectionCounterConnector._parse_counter_info(info)
    by_field = {item.canonical_field: item.count for item in values}

    assert by_field["counter.copy.bw_total"] == 124
    assert by_field["counter.print.full_color_total"] == 1759
    assert by_field["counter.scan_fax.document_read_total"] == 1483
