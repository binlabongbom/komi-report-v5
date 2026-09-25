from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from ipaddress import ip_address
from typing import Any

# Persisted reading evidence: emitted only for explicit disabled auth and track modes.
PUBLIC_USER_DISABLED_MARKER = "ยืนยันว่า User Authentication และ Account Track ปิดใช้งานบนเครื่อง"


class Confidence(StrEnum):
    VERIFIED = "verified"
    MAPPED = "mapped"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ScanMode(StrEnum):
    QUICK = "quick"
    DEEP = "deep"


class WebAuthState(StrEnum):
    PUBLIC = "public"
    ADMIN = "admin"
    PUBLIC_FALLBACK = "public_fallback"


@dataclass(frozen=True)
class ConnectionSettings:
    host: str
    community: str
    port: int = 161
    version: str = "2c"
    timeout: float = 2.0
    retries: int = 1
    max_rows_per_root: int = 2500
    v3_username: str = ""
    v3_security_level: str = "authPriv"
    v3_auth_password: str = ""
    v3_priv_password: str = ""
    v3_context: str = ""

    def __post_init__(self) -> None:
        host = self.host.strip()
        if not host:
            raise ValueError("กรุณาระบุ IP address หรือ hostname")
        try:
            ip_address(host)
        except ValueError:
            if any(char.isspace() for char in host) or "." not in host:
                raise ValueError("hostname ไม่ถูกต้อง") from None
        if self.version in {"1", "2c"} and not self.community:
            raise ValueError("กรุณาระบุ SNMP community")
        if not 1 <= self.port <= 65535:
            raise ValueError("port ต้องอยู่ระหว่าง 1–65535")
        if self.version not in {"1", "2c", "3"}:
            raise ValueError("รองรับ SNMP v1, v2c และ v3")
        if self.version == "3":
            if not self.v3_username:
                raise ValueError("กรุณาระบุ SNMP v3 read user")
            if self.v3_security_level not in {"noAuthNoPriv", "authNoPriv", "authPriv"}:
                raise ValueError("SNMP v3 security level ไม่ถูกต้อง")
            if self.v3_security_level in {"authNoPriv", "authPriv"} and len(self.v3_auth_password) < 8:
                raise ValueError("SNMP v3 auth password ต้องมีอย่างน้อย 8 ตัวอักษร")
            if self.v3_security_level == "authPriv" and len(self.v3_priv_password) < 8:
                raise ValueError("SNMP v3 privacy password ต้องมีอย่างน้อย 8 ตัวอักษร")
        if self.timeout <= 0 or self.retries < 0 or self.max_rows_per_root <= 0:
            raise ValueError("timeout, retries หรือ max rows ไม่ถูกต้อง")


@dataclass(frozen=True)
class RawOidValue:
    oid: str
    value: str
    data_type: str
    numeric_value: int | float | None = None


@dataclass(frozen=True)
class InterpretedOid:
    oid: str
    value: str
    data_type: str
    canonical_field: str | None
    label: str
    description_th: str
    source: str
    confidence: Confidence
    numeric_value: int | float | None = None


@dataclass(frozen=True)
class DecodedEntity:
    category: str
    index: str
    name: str
    fields: tuple[tuple[str, str], ...]
    source_oids: tuple[str, ...]
    confidence: Confidence = Confidence.MAPPED


@dataclass(frozen=True)
class CounterCandidate:
    oid: str
    value: str
    numeric_value: int | float
    label: str
    unit: str
    reason: str
    confidence: Confidence


@dataclass(frozen=True)
class WebCounterValue:
    canonical_field: str
    label: str
    count: int | float
    category: str
    source_path: str
    confidence: Confidence = Confidence.VERIFIED
    subject_type: str | None = None
    subject_id: str | None = None
    subject_name: str | None = None


@dataclass(frozen=True)
class MeterReading:
    host: str
    collected_at: str
    counters: tuple[WebCounterValue, ...]
    source: str
    auth_state: WebAuthState
    warnings: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = "komi.meter.reading.v1"

    @classmethod
    def create(
        cls,
        host: str,
        counters: list[WebCounterValue],
        source: str,
        auth_state: WebAuthState,
        warnings: list[str] | None = None,
    ) -> MeterReading:
        return cls(
            host=host,
            collected_at=datetime.now(UTC).isoformat(),
            counters=tuple(counters),
            source=source,
            auth_state=auth_state,
            warnings=tuple(warnings or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeviceSnapshot:
    host: str
    collected_at: str
    values: tuple[InterpretedOid, ...]
    schema_version: str = "komi.snmp.snapshot.v1"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    scan_mode: ScanMode = ScanMode.QUICK
    roots_scanned: tuple[str, ...] = field(default_factory=tuple)
    entities: tuple[DecodedEntity, ...] = field(default_factory=tuple)
    counter_candidates: tuple[CounterCandidate, ...] = field(default_factory=tuple)
    web_counters: tuple[WebCounterValue, ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        host: str,
        values: list[InterpretedOid],
        warnings: list[str] | None = None,
        scan_mode: ScanMode = ScanMode.QUICK,
        roots_scanned: tuple[str, ...] = (),
        entities: list[DecodedEntity] | None = None,
        counter_candidates: list[CounterCandidate] | None = None,
        web_counters: list[WebCounterValue] | None = None,
    ) -> DeviceSnapshot:
        return cls(
            host=host,
            collected_at=datetime.now(UTC).isoformat(),
            values=tuple(values),
            warnings=tuple(warnings or []),
            scan_mode=scan_mode,
            roots_scanned=roots_scanned,
            entities=tuple(entities or []),
            counter_candidates=tuple(counter_candidates or []),
            web_counters=tuple(web_counters or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CounterDelta:
    oid: str
    canonical_field: str | None
    label: str
    before: int | float
    after: int | float
    delta: int | float
    confidence: Confidence
    matches_expected: bool = False
