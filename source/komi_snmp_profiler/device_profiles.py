from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re


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
    model_pattern: str = ""
    allow_factory_admin_credentials: bool = True

    def matches(self, model: str) -> bool:
        normalized = " ".join(model.casefold().split())
        return (
            bool(normalized)
            and all(token in normalized for token in self.model_tokens)
            and (not self.model_pattern or re.search(self.model_pattern, normalized) is not None)
        )


PRINTER_MIB_TOTAL_OID = "1.3.6.1.2.1.43.10.2.1.4.1.1"
KM_PRIVATE_TOTAL_OID = "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0"

CONFIRMED_DEVICE_PROFILES = (
    DeviceMeterProfile(
        profile_id="bizhub-287-admin-legacy-xml",
        model_tokens=("bizhub", "287"),
        model_pattern=r"\bbizhub\s*287\b",
        # The device UI confirms Administrator /wcd/a_system_counter.xml.
        # Reuse the existing XML connector; payload/login acceptance remains
        # a candidate test. Do not inherit another model's legacy TLS or OID.
        web_protocol=WebMeterProtocol.LEGACY_XML_ADMIN,
        web_scheme="https",
        allow_factory_admin_credentials=False,
    ),
    DeviceMeterProfile(
        profile_id="accuriopress-c84hc-public-legacy-xml",
        model_tokens=("accuriopress", "c84hc"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        # The current device proves exact Total and public legacy XML.  Keep
        # optional walks off because this model has also shown intermittent
        # response timeouts; status detail can be added after a bounded read.
        snmp_walk_policy=SnmpWalkPolicy.TARGETED_ONLY,
        web_protocol=WebMeterProtocol.LEGACY_XML_PUBLIC,
        web_scheme="http",
    ),
    DeviceMeterProfile(
        profile_id="accuriopress-c12010s-public-legacy-xml",
        model_tokens=("accuriopress", "c12010s"),
        preferred_total_oid=KM_PRIVATE_TOTAL_OID,
        # Real-device Printer-MIB evidence confirms direct toner percentage
        # rows and paper-input levels.  These optional walks run only after
        # the calibrated exact Total GET and can never make Total fail.
        snmp_walk_policy=SnmpWalkPolicy.SUPPLEMENTAL,
        web_protocol=WebMeterProtocol.LEGACY_XML_PUBLIC,
        web_scheme="http",
    ),
    DeviceMeterProfile(
        profile_id="accuriopress-c7090-public-legacy-xml",
        model_tokens=("accuriopress", "c7090"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        snmp_walk_policy=SnmpWalkPolicy.SUPPLEMENTAL,
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
        # Real-device verification confirms that this legacy Admin family
        # exposes standard Printer-MIB supply and input-tray tables.  Keep the
        # exact Total GET as the billing-safe primary read, then collect these
        # optional tables for Toner/Paper UI.  A supplemental failure never
        # changes the Total Meter result or marks the device offline.
        snmp_walk_policy=SnmpWalkPolicy.SUPPLEMENTAL,
        web_protocol=WebMeterProtocol.LEGACY_XML_ADMIN,
        web_scheme="https",
        tls_compatibility=TlsCompatibility.TLS11_LEGACY,
    ),
    DeviceMeterProfile(
        profile_id="bizhub-c368-admin-legacy-xml",
        model_tokens=("bizhub", "c368"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        # Use the same optional supply/tray capability as the confirmed C458
        # Web Connection family.  Future LEGACY_XML_ADMIN profiles inherit
        # SUPPLEMENTAL by default unless real-device evidence requires a
        # targeted-only exception.
        snmp_walk_policy=SnmpWalkPolicy.SUPPLEMENTAL,
        web_protocol=WebMeterProtocol.LEGACY_XML_ADMIN,
        web_scheme="https",
        # The real device negotiates TLS 1.2 but requires legacy server
        # connection support. This remains isolated to the C368 profile.
        tls_compatibility=TlsCompatibility.TLS11_LEGACY,
    ),
    DeviceMeterProfile(
        profile_id="bizhub-c3350i-public-modern-http",
        model_tokens=("bizhub", "c3350i"),
        preferred_total_oid=PRINTER_MIB_TOTAL_OID,
        snmp_walk_policy=SnmpWalkPolicy.SUPPLEMENTAL,
        web_protocol=WebMeterProtocol.MODERN_JSON,
        web_scheme="http",
    ),
)

GENERIC_DEVICE_PROFILE = DeviceMeterProfile(profile_id="generic")


def resolve_device_meter_profile(model: str, *, web_protocol: str = "auto") -> DeviceMeterProfile:
    """Resolve measured model defaults or an explicit user-selected XML protocol."""
    if web_protocol not in {"auto", "legacy_xml_public", "legacy_xml_admin"}:
        raise ValueError("Unsupported Web Connection protocol")
    profile = next(
        (profile for profile in CONFIRMED_DEVICE_PROFILES if profile.matches(model)),
        GENERIC_DEVICE_PROFILE,
    )
    if web_protocol == "auto":
        return profile
    return replace(
        profile,
        profile_id=f"explicit-{web_protocol}",
        web_protocol=WebMeterProtocol(web_protocol),
        allow_factory_admin_credentials=False,
    )
