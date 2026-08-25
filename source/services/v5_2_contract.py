"""Strict Desktop-side draft contract for V5.2 Registration/Status/Meter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from komi_version import APP_VERSION
from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.registration_envelope import normalize_device_inventory

SCHEMA_VERSION = 3
CLIENT_ID = "komi-report-desktop"
CONTRACT_VERSION = "v5.2-draft-2026-08-25"
CONTRACT_SHA256 = "4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd"
MAX_SELECTED_DEVICES = 3

FORBIDDEN_FIELDS = frozenset(
    {
        "ip",
        "ip_address",
        "mac",
        "mac_address",
        "host",
        "hostname",
        "credential",
        "credentials",
        "password",
        "username",
        "user",
        "users",
        "document",
        "documents",
        "job",
        "jobs",
        "application_log",
        "logs",
        "raw_log",
        "raw_xml",
        "raw_snmp",
        "counter_detail",
        "detailed_counter",
        "authorization",
        "installation_token",
    }
)

REGISTRATION_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "client_id",
        "installation_id",
        "installation_public_key",
        "proof_algorithm",
        "company_name",
        "client_first_started_at",
        "app_version",
        "platform",
        "architecture",
        "device_inventory",
        "created_at",
        "request_signature",
    }
)
STATUS_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "installation_id",
        "app_version",
        "platform",
        "architecture",
        "occurred_at",
    }
)
METER_FIELDS = frozenset(
    {"schema_version", "event_type", "installation_id", "observations", "sent_at"}
)
OBSERVATION_FIELDS = frozenset(
    {
        "serial_number",
        "model",
        "device_slot",
        "total_meter",
        "meter_observed_at",
        "meter_status",
    }
)


class InstallationSigner(Protocol):
    installation_id: str
    public_key_base64url: str

    def sign(self, value: bytes) -> str: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_exact(value: Mapping[str, object], fields: frozenset[str], path: str) -> None:
    unexpected = sorted(str(key) for key in value if str(key) not in fields)
    if unexpected:
        raise ValueError(f"contract contains unexpected field at {path}: {', '.join(unexpected)}")
    missing = sorted(field for field in fields if field not in value)
    if missing:
        raise ValueError(f"contract missing field at {path}: {', '.join(missing)}")


def _assert_privacy(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in FORBIDDEN_FIELDS:
                raise ValueError(f"contract contains excluded field: {key}")
            _assert_privacy(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_privacy(nested)


def _valid_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _validate_common(value: Mapping[str, object], *, event_type: str) -> None:
    _assert_privacy(value)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    if value.get("event_type") != event_type:
        raise ValueError("unsupported event_type")
    if not isinstance(value.get("installation_id"), str) or not str(
        value["installation_id"]
    ).strip():
        raise ValueError("installation_id is required")


@dataclass(frozen=True)
class TelemetryPolicy:
    status_interval_seconds: int = 21_600
    meter_interval_seconds: int = 21_600
    offline_threshold_seconds: int = 259_200
    no_print_threshold_seconds: int = 86_400
    startup_recovery_cooldown_seconds: int = 900
    minimum_server_interval_seconds: int = 3_600
    maximum_server_interval_seconds: int = 43_200
    jitter_ratio: float = 0.10
    max_normal_requests_per_day: int = 8

    def clamp_server_interval(self, value: object) -> int:
        if type(value) is not int:
            return self.status_interval_seconds
        return min(self.maximum_server_interval_seconds, max(self.minimum_server_interval_seconds, value))

    def with_jitter(self, seconds: int, *, random_unit: float) -> int:
        unit = min(1.0, max(0.0, float(random_unit)))
        factor = 1.0 + ((unit * 2.0) - 1.0) * self.jitter_ratio
        return max(1, int(round(seconds * factor)))


def build_registration_payload(
    *,
    identity: InstallationSigner,
    company_name: str,
    first_started_at: str,
    app_version: str,
    devices: Iterable[Mapping[str, object]],
    platform_name: str,
    architecture: str,
    created_at: str | None = None,
    adapter: DraftV1SigningAdapter | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "installation_registered",
        "client_id": CLIENT_ID,
        "installation_id": identity.installation_id,
        "installation_public_key": identity.public_key_base64url,
        "proof_algorithm": "Ed25519",
        "company_name": " ".join(company_name.split()),
        "client_first_started_at": first_started_at.strip(),
        "app_version": app_version.strip(),
        "platform": platform_name.strip(),
        "architecture": architecture.strip(),
        "device_inventory": normalize_device_inventory(devices),
        "created_at": created_at or _now(),
    }
    signing = adapter or DraftV1SigningAdapter()
    payload["request_signature"] = identity.sign(
        signing.canonical_bytes(payload, exclude_fields=frozenset({"request_signature"}))
    )
    validate_registration_payload(payload, adapter=signing)
    return payload


def validate_registration_payload(
    value: Mapping[str, object], *, adapter: DraftV1SigningAdapter | None = None
) -> None:
    _require_exact(value, REGISTRATION_FIELDS, "registration")
    _validate_common(value, event_type="installation_registered")
    if value.get("client_id") != CLIENT_ID or value.get("proof_algorithm") != "Ed25519":
        raise ValueError("registration client proof is invalid")
    if value.get("app_version") != APP_VERSION:
        raise ValueError("registration app_version is not current V5.2")
    for field in (
        "installation_public_key",
        "company_name",
        "client_first_started_at",
        "platform",
        "architecture",
        "request_signature",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise ValueError(f"registration {field} is required")
    if not _valid_utc_timestamp(value.get("created_at")):
        raise ValueError("registration created_at must be UTC")
    inventory = value.get("device_inventory")
    if normalize_device_inventory(inventory.get("devices", [])) != inventory:  # type: ignore[union-attr]
        raise ValueError("registration device inventory is invalid")
    signing = adapter or DraftV1SigningAdapter()
    if not signing.verify_envelope(
        value,
        signature_field="request_signature",
        public_key_base64url=str(value["installation_public_key"]),
    ):
        raise ValueError("registration signature is invalid")


def build_status_payload(
    *,
    installation_id: str,
    app_version: str,
    platform_name: str,
    architecture: str,
    occurred_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "installation_status",
        "installation_id": installation_id.strip(),
        "app_version": app_version.strip(),
        "platform": platform_name.strip(),
        "architecture": architecture.strip(),
        "occurred_at": occurred_at or _now(),
    }
    validate_status_payload(payload)
    return payload


def validate_status_payload(value: Mapping[str, object]) -> None:
    _require_exact(value, STATUS_FIELDS, "status")
    _validate_common(value, event_type="installation_status")
    if value.get("app_version") != APP_VERSION:
        raise ValueError("status app_version is not current V5.2")
    if not _valid_utc_timestamp(value.get("occurred_at")):
        raise ValueError("status occurred_at must be UTC")
    for field in ("platform", "architecture"):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise ValueError(f"status {field} is required")


def _normalize_observations(
    observations: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for raw in observations:
        candidate = {field: raw.get(field) for field in OBSERVATION_FIELDS}
        _require_exact(raw, OBSERVATION_FIELDS, "observations")
        serial = str(candidate.get("serial_number") or "").strip()
        if not serial:
            raise ValueError("meter serial_number is required")
        previous = latest.get(serial.casefold())
        if previous is None or str(candidate.get("meter_observed_at") or "") >= str(
            previous.get("meter_observed_at") or ""
        ):
            latest[serial.casefold()] = candidate
    return sorted(latest.values(), key=lambda item: int(item["device_slot"]))


def build_meter_payload(
    *,
    installation_id: str,
    observations: Iterable[Mapping[str, object]],
    sent_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "meter_observed",
        "installation_id": installation_id.strip(),
        "observations": _normalize_observations(observations),
        "sent_at": sent_at or _now(),
    }
    validate_meter_payload(payload)
    return payload


def validate_meter_payload(value: Mapping[str, object]) -> None:
    _require_exact(value, METER_FIELDS, "meter")
    _validate_common(value, event_type="meter_observed")
    if not _valid_utc_timestamp(value.get("sent_at")):
        raise ValueError("meter sent_at must be UTC")
    observations = value.get("observations")
    if not isinstance(observations, list) or not 1 <= len(observations) <= MAX_SELECTED_DEVICES:
        raise ValueError("meter observations must contain one to three devices")
    serials: set[str] = set()
    slots: set[int] = set()
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise ValueError("meter observation must be an object")
        _require_exact(observation, OBSERVATION_FIELDS, "observations")
        _assert_privacy(observation)
        serial = observation.get("serial_number")
        model = observation.get("model")
        slot = observation.get("device_slot")
        status = observation.get("meter_status")
        total = observation.get("total_meter")
        if not isinstance(serial, str) or not serial.strip() or serial.casefold() in serials:
            raise ValueError("meter serial_number is missing or duplicated")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("meter model is required")
        if type(slot) is not int or not 1 <= slot <= 3 or slot in slots:
            raise ValueError("meter device_slot is invalid or duplicated")
        if status not in {"ok", "unavailable"}:
            raise ValueError("meter_status is invalid")
        if status == "ok" and (type(total) is not int or total < 0):
            raise ValueError("ok total_meter must be a non-negative integer")
        if status == "unavailable" and total is not None:
            raise ValueError("unavailable total_meter must be null")
        if not _valid_utc_timestamp(observation.get("meter_observed_at")):
            raise ValueError("meter_observed_at must be UTC")
        serials.add(serial.casefold())
        slots.add(slot)
