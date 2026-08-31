from komi_snmp_profiler.device_profiles import (
    SnmpWalkPolicy,
    TlsCompatibility,
    WebMeterProtocol,
    resolve_device_meter_profile,
)


def test_confirmed_accuriopress_profiles_use_public_legacy_xml() -> None:
    for model in (
        "KONICA MINOLTA AccurioPress C5070",
        "KONICA MINOLTA AccurioPress C7090",
        "KONICA MINOLTA AccurioPress C12010S",
    ):
        profile = resolve_device_meter_profile(model)

        assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_PUBLIC
        assert profile.web_scheme == "http"


def test_confirmed_press_supply_policy_matches_real_device_capability() -> None:
    assert resolve_device_meter_profile(
        "KONICA MINOLTA AccurioPress C5070"
    ).snmp_walk_policy == SnmpWalkPolicy.TARGETED_ONLY
    for model in (
        "KONICA MINOLTA AccurioPress C7090",
        "KONICA MINOLTA AccurioPress C12010S",
    ):
        assert resolve_device_meter_profile(model).snmp_walk_policy == SnmpWalkPolicy.SUPPLEMENTAL


def test_c12010s_profile_uses_web_calibrated_private_total_oid() -> None:
    profile = resolve_device_meter_profile("AccurioPress C12010S")

    assert profile.preferred_total_oid == "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0"


def test_c458_profile_is_admin_legacy_xml_with_scoped_tls11_compatibility() -> None:
    profile = resolve_device_meter_profile("KONICA MINOLTA bizhub C458")

    assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN
    assert profile.web_scheme == "https"
    assert profile.tls_compatibility == TlsCompatibility.TLS11_LEGACY
    assert profile.snmp_walk_policy == SnmpWalkPolicy.SUPPLEMENTAL


def test_c368_profile_is_admin_legacy_xml_with_scoped_tls_compatibility() -> None:
    profile = resolve_device_meter_profile("KONICA MINOLTA bizhub C368")

    assert profile.profile_id == "bizhub-c368-admin-legacy-xml"
    assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN
    assert profile.web_scheme == "https"
    assert profile.tls_compatibility == TlsCompatibility.TLS11_LEGACY
    assert profile.snmp_walk_policy == SnmpWalkPolicy.SUPPLEMENTAL


def test_legacy_admin_profiles_collect_optional_toner_and_paper_status() -> None:
    profiles = tuple(
        resolve_device_meter_profile(model)
        for model in (
            "KONICA MINOLTA bizhub C458",
            "KONICA MINOLTA bizhub C368",
        )
    )

    assert all(profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN for profile in profiles)
    assert all(profile.snmp_walk_policy == SnmpWalkPolicy.SUPPLEMENTAL for profile in profiles)


def test_c84hc_uses_bounded_public_legacy_profile_after_real_device_proof() -> None:
    profile = resolve_device_meter_profile("KONICA MINOLTA AccurioPress C84hc")

    assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_PUBLIC
    assert profile.web_scheme == "http"
    assert profile.snmp_walk_policy == SnmpWalkPolicy.TARGETED_ONLY


def test_c3350i_uses_public_modern_http_profile_after_real_device_proof() -> None:
    profile = resolve_device_meter_profile("KONICA MINOLTA bizhub C3350i")

    assert profile.web_protocol == WebMeterProtocol.MODERN_JSON
    assert profile.web_scheme == "http"
