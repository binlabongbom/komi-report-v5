from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SnmpWalkPolicy(StrEnum):
    SUPPLEMENTAL = "supplemental"
    TARGETED_ONLY = "targeted_only"


class WebMeterProtocol(StrEnum):
    MODERN_JSON = "modern_json"
    LEGACY_XML_PUBLIC = "legacy_xml_public"
    LEGACY_XML_ADMIN = "legacy_xml_admin"


class TlsCompatibility(StrEnum):
    DEFAULT = "default"
    TLS11_LEGACY = "tls11_legacy"


@dataclass(frozen=True)
class DeviceMeterProfile:
    profile_id: str
    model_tokens: tuple[str, ...] = ()
    preferred_total_oid: str = ""
    snmp_walk_policy: SnmpWalkPolicy = SnmpWalkPolicy.SUPPLEMENTAL
    web_protocol: WebMeterProtocol = WebMeterProtocol.MODERN_JSON
    web_scheme: str = "https"
    tls_compatibility: TlsCompatibility = TlsCompatibility.DEFAULT

    def matches(self, model: str) -> bool:
        normalized = " ".join(model.casefold().split())
        return bool(normalized) and all(token in normalized for token in self.model_tokens)


PRINTER_MIB_TOTAL_OID = "1.3.6.1.2.1.43.10.2.1.4.1.1"
KM_PRIVATE_TOTAL_OID = "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0"

CONFIRMED_DEVICE_PROFILES = (
    DeviceMeterProfile(
        profile_id="accuriopress-c12010s-public-legacy-xml",
        model_tokens=("accuriopress", "c12010s"),
        preferred_total_oid=KM_PRIVATE_TOTAL_OID,
        snmp_walk_policy=SnmpWalkPolicy.TARGETED_ONLY,
        web_protocol=WebMeterProtocol.LEGACY_XML_PUBLIC,
        web_scheme="http",
    ),
    DeviceMeterProfile(
        profile_id="accuriopress-c7090-public-legacy-xml",
        model_tokens=("accuriopress", "c7090"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        snmp_walk_policy=SnmpWalkPolicy.TARGETED_ONLY,
        web_protocol=WebMeterProtocol.LEGACY_XML_PUBLIC,
        web_scheme="http",
    ),
    DeviceMeterProfile(
        profile_id="accuriopress-c5070-public-legacy-xml",
        model_tokens=("accuriopress", "c5070"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        snmp_walk_policy=SnmpWalkPolicy.TARGETED_ONLY,
        web_protocol=WebMeterProtocol.LEGACY_XML_PUBLIC,
        web_scheme="http",
    ),
    DeviceMeterProfile(
        profile_id="bizhub-c458-admin-legacy-xml",
        model_tokens=("bizhub", "c458"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        snmp_walk_policy=SnmpWalkPolicy.TARGETED_ONLY,
        web_protocol=WebMeterProtocol.LEGACY_XML_ADMIN,
        web_scheme="https",
        tls_compatibility=TlsCompatibility.TLS11_LEGACY,
    ),
)

GENERIC_DEVICE_PROFILE = DeviceMeterProfile(profile_id="generic")


def resolve_device_meter_profile(model: str) -> DeviceMeterProfile:
    """Return only profiles backed by captured real-device evidence."""
    return next(
        (profile for profile in CONFIRMED_DEVICE_PROFILES if profile.matches(model)),
        GENERIC_DEVICE_PROFILE,
    )
