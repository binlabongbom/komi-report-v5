from __future__ import annotations

import pytest

from komi_snmp_profiler.connectors import (
    LegacyWebConnectionCounterConnector,
    ReadOnlyWebConnectionSession,
    TlsPolicy,
    WebConnectionCounterConnector,
    WebConnectionError,
    WebConnectionSessionBusyError,
)
from komi_snmp_profiler.device_profiles import TlsCompatibility


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


def test_tls11_legacy_compatibility_is_explicit_and_profile_scoped() -> None:
    default = ReadOnlyWebConnectionSession("192.0.2.10")
    legacy = ReadOnlyWebConnectionSession(
        "192.0.2.10",
        tls_policy=TlsPolicy(compatibility=TlsCompatibility.TLS11_LEGACY),
    )

    assert default.tls_policy.compatibility == TlsCompatibility.DEFAULT
    assert legacy.tls_policy.compatibility == TlsCompatibility.TLS11_LEGACY
    assert legacy.ssl_context.minimum_version.name == "TLSv1_1"
    assert legacy.ssl_context.maximum_version.name == "MAXIMUM_SUPPORTED"


def test_legacy_xml_parser_extracts_same_canonical_total_contract() -> None:
    payload = b"""<?xml version='1.0'?>
    <MFP><LoginMode>PublicUser</LoginMode><UserCounterInfo>
      <TotalCounterList>
        <TotalCounter><Type>Total</Type><Count>25121</Count></TotalCounter>
        <TotalCounter><Type>DuplexTotal</Type><Count>7335</Count></TotalCounter>
      </TotalCounterList>
      <CopyCounterList><CopyCounter><Type>Total</Type><Count>5478</Count></CopyCounter></CopyCounterList>
      <PrintCounterList><PrintCounter><Type>Total</Type><Count>19643</Count></PrintCounter></PrintCounterList>
    </UserCounterInfo></MFP>"""

    values = LegacyWebConnectionCounterConnector.parse_xml(payload)
    by_field = {item.canonical_field: item.count for item in values}

    assert by_field["counter.total.total"] == 25_121
    assert by_field["counter.total.duplex_total"] == 7_335
    assert by_field["counter.copy.total"] == 5_478
    assert by_field["counter.print.total"] == 19_643


def test_legacy_xml_parser_accepts_aggregate_lists_without_user_counter_wrapper() -> None:
    payload = b"""<?xml version='1.0'?>
    <MFP><CounterInfo>
      <TotalCounterList>
        <TotalCounter><Type>Total</Type><Count>250206</Count></TotalCounter>
      </TotalCounterList>
      <PrintCounterList>
        <PrintCounter><Type>Total</Type><Count>224150</Count></PrintCounter>
      </PrintCounterList>
    </CounterInfo></MFP>"""

    values = LegacyWebConnectionCounterConnector.parse_xml(payload)
    by_field = {item.canonical_field: item.count for item in values}

    assert by_field["counter.total.total"] == 250_206
    assert by_field["counter.print.total"] == 224_150


def test_legacy_xml_parser_reports_session_busy_separately() -> None:
    with pytest.raises(WebConnectionSessionBusyError, match="session"):
        LegacyWebConnectionCounterConnector.parse_xml(
            b"<MFP><DirectAccessError>Another user session is active</DirectAccessError></MFP>"
        )


def test_legacy_xml_parser_does_not_call_direct_access_error_session_busy() -> None:
    with pytest.raises(WebConnectionError, match="direct|Web session") as raised:
        LegacyWebConnectionCounterConnector.parse_xml(
            b"<MFP><DirectAccessError><Redirect>/wcd/index.html</Redirect></DirectAccessError></MFP>"
        )

    assert not isinstance(raised.value, WebConnectionSessionBusyError)


def test_legacy_connector_opens_entry_page_before_counter() -> None:
    class Session:
        def __init__(self, _host: str, **_kwargs) -> None:
            self.calls: list[str] = []
            self.cleared = False

        def get_bytes(self, path: str) -> bytes:
            self.calls.append(path)
            if path == "system_counter.xml":
                return b"""<MFP><UserCounterInfo><TotalCounterList>
                <TotalCounter><Type>Total</Type><Count>219546</Count></TotalCounter>
                </TotalCounterList></UserCounterInfo></MFP>"""
            return b"<html/>"

        def clear(self) -> None:
            self.cleared = True

    sessions: list[Session] = []

    def factory(host: str, **kwargs) -> Session:
        session = Session(host, **kwargs)
        sessions.append(session)
        return session

    result = LegacyWebConnectionCounterConnector(session_factory=factory).collect_result(
        "192.0.2.16"
    )

    assert result.counters[0].count == 219_546
    assert sessions[0].calls == ["index.html", "system_counter.xml"]
    assert sessions[0].cleared is True


def test_legacy_admin_preparation_uses_fixed_meter_route_and_ephemeral_cookies(monkeypatch) -> None:
    session = ReadOnlyWebConnectionSession("127.0.0.1")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        session,
        "_request",
        lambda path, *, method, **_kwargs: calls.append((method, path)) or b"<MFP/>",
    )

    session.prepare_legacy_admin_login()

    assert calls == [
        ("GET", "index.html?access=ASYS_COU"),
        ("GET", "login.xml"),
    ]
    cookies = {cookie.name: cookie.value for cookie in session.cookies}
    assert cookies["access"] == "ASYS_COU"
    assert cookies["adm"] == "AS_COU"
    assert cookies["usr"] == ""
    assert cookies["srv"] == ""
    assert cookies["param"] == ""


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
