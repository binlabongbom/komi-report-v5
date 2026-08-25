from komi_snmp_profiler.device_profiles import (
    SnmpWalkPolicy,
    TlsCompatibility,
    WebMeterProtocol,
    resolve_device_meter_profile,
)


def test_confirmed_accuriopress_profiles_use_public_legacy_xml_without_snmp_walk() -> None:
    for model in (
        "KONICA MINOLTA AccurioPress C5070",
        "KONICA MINOLTA AccurioPress C7090",
        "KONICA MINOLTA AccurioPress C12010S",
    ):
        profile = resolve_device_meter_profile(model)

        assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_PUBLIC
        assert profile.web_scheme == "http"
        assert profile.snmp_walk_policy == SnmpWalkPolicy.TARGETED_ONLY


def test_c12010s_profile_uses_web_calibrated_private_total_oid() -> None:
    profile = resolve_device_meter_profile("AccurioPress C12010S")

    assert profile.preferred_total_oid == "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0"


def test_c458_profile_is_admin_legacy_xml_with_scoped_tls11_compatibility() -> None:
    profile = resolve_device_meter_profile("KONICA MINOLTA bizhub C458")

    assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN
    assert profile.web_scheme == "https"
    assert profile.tls_compatibility == TlsCompatibility.TLS11_LEGACY
    assert profile.snmp_walk_policy == SnmpWalkPolicy.TARGETED_ONLY


def test_unproven_c368_and_c84hc_remain_generic_until_real_evidence_passes() -> None:
    assert resolve_device_meter_profile("KONICA MINOLTA bizhub C368").profile_id == "generic"
    assert resolve_device_meter_profile("KONICA MINOLTA AccurioPress C84hc").profile_id == "generic"
