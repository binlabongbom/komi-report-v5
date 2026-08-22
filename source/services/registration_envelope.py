"""Build the minimal, privacy-bounded installation registration payload.

The desktop owns this schema.  Network transport and server credentials are
deliberately kept out of this module so setup can be completed while offline.
"""

from __future__ import annotations

import platform
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

REGISTRATION_SCHEMA_VERSION = 2
MAX_SELECTED_DEVICES = 3
EXCLUDED_REGISTRATION_FIELDS = frozenset(
    {
        "account",
        "accounts",
        "application_log",
        "authorization",
        "bootstrap_credential",
        "bearer_token",
        "credential_ref",
        "ip",
        "ip_address",
        "host",
        "hostname",
        "log",
        "logs",
        "mac",
        "mac_address",
        "serial",
        "username",
        "password",
        "credential",
        "credentials",
        "meter",
        "counter",
        "user",
        "users",
        "document",
        "documents",
        "installation_token",
        "raw_payload",
        "raw_request",
        "raw_response",
        "token",
    }
)

REGISTER_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "installation_id",
        "company_name",
        "client_first_started_at",
        "app_version",
        "platform",
        "architecture",
        "device_inventory",
        "created_at",
    }
)
HEARTBEAT_FIELDS = frozenset(
    {
        "schema_version",
        "installation_id",
        "app_version",
        "platform",
        "architecture",
        "device_inventory",
        "occurred_at",
    }
)
DEVICE_INVENTORY_FIELDS = frozenset({"konica_discovered_count", "devices"})
DEVICE_FIELDS = frozenset({"serial_number", "model", "selected", "device_slot"})


def runtime_platform() -> tuple[str, str]:
    """Return stable, human-readable OS and CPU architecture labels."""
    return platform.system() or "Unknown", platform.machine() or "Unknown"


def normalize_device_models(models: Iterable[str]) -> list[dict[str, object]]:
    """Aggregate models for the local review UI without exposing device identity."""
    counts: dict[str, int] = {}
    for raw_model in models:
        model = " ".join(str(raw_model or "").split()).strip()
        if not model or model in {"—", "ไม่ทราบรุ่น"}:
            model = "Unknown"
        counts[model] = counts.get(model, 0) + 1
    return [
        {"model": model, "quantity": quantity}
        for model, quantity in sorted(counts.items(), key=lambda item: item[0].casefold())
    ]


def normalize_device_inventory(
    devices: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Return the complete IP-scan inventory and the selected report devices."""
    normalized: list[dict[str, object]] = []
    serials: set[str] = set()
    selected_slots: set[int] = set()
    selected_count = 0
    for raw_device in devices:
        if not isinstance(raw_device, Mapping):
            raise ValueError("registration device must be an object")
        if not isinstance(raw_device.get("serial_number"), str):
            raise ValueError("registration serial_number must be a string")
        if not isinstance(raw_device.get("model"), str):
            raise ValueError("registration model must be a string")
        serial_number = " ".join(str(raw_device.get("serial_number") or "").split()).strip()
        if not serial_number or serial_number == "—":
            raise ValueError("registration device missing serial_number")
        serial_key = serial_number.casefold()
        if serial_key in serials:
            raise ValueError("registration device serial_number duplicated")
        serials.add(serial_key)

        model = " ".join(str(raw_device.get("model") or "").split()).strip()
        if not model or model in {"—", "ไม่ทราบรุ่น"}:
            model = "Unknown"
        raw_selected = raw_device.get("selected")
        if type(raw_selected) is not bool:
            raise ValueError("registration selected must be a boolean")
        selected = raw_selected
        raw_slot = raw_device.get("device_slot")
        if selected:
            if type(raw_slot) is not int:
                raise ValueError("selected registration device missing device_slot or integer type")
            device_slot = raw_slot
            if not 1 <= device_slot <= MAX_SELECTED_DEVICES:
                raise ValueError("registration device_slot must be between 1 and 3")
            if device_slot in selected_slots:
                raise ValueError("registration device_slot duplicated")
            selected_slots.add(device_slot)
            selected_count += 1
        else:
            if raw_slot is not None:
                raise ValueError("unselected registration device must not have device_slot")
            device_slot = None
        normalized.append(
            {
                "serial_number": serial_number,
                "model": model,
                "selected": selected,
                "device_slot": device_slot,
            }
        )
    if selected_count > MAX_SELECTED_DEVICES:
        raise ValueError("registration supports at most 3 selected devices")
    return {
        "konica_discovered_count": len(normalized),
        "devices": normalized,
    }


def build_registration_envelope(
    *,
    installation_id: str,
    company_name: str,
    first_started_at: str,
    app_version: str,
    devices: Iterable[Mapping[str, object]],
    platform_name: str | None = None,
    architecture: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Create the exact allow-listed body for ``installations/register``."""
    detected_platform, detected_architecture = runtime_platform()
    envelope: dict[str, object] = {
        "schema_version": REGISTRATION_SCHEMA_VERSION,
        "event_type": "installation_registered",
        "installation_id": installation_id.strip(),
        "company_name": " ".join(company_name.split()),
        "client_first_started_at": first_started_at.strip(),
        "app_version": app_version.strip(),
        "platform": (platform_name or detected_platform).strip(),
        "architecture": (architecture or detected_architecture).strip(),
        "device_inventory": normalize_device_inventory(devices),
        "created_at": created_at or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    required = (
        "installation_id",
        "company_name",
        "client_first_started_at",
        "app_version",
    )
    missing = [key for key in required if not envelope[key]]
    if missing:
        raise ValueError(f"registration envelope missing: {', '.join(missing)}")
    validate_registration_envelope(envelope)
    return envelope


def build_heartbeat_envelope(
    registration: Mapping[str, object],
    *,
    occurred_at: str | None = None,
) -> dict[str, object]:
    """Build the strict lifecycle heartbeat from a validated registration body."""

    validate_registration_envelope(registration)
    envelope: dict[str, object] = {
        "schema_version": REGISTRATION_SCHEMA_VERSION,
        "installation_id": str(registration["installation_id"]),
        "app_version": str(registration["app_version"]),
        "platform": str(registration["platform"]),
        "architecture": str(registration["architecture"]),
        "device_inventory": registration["device_inventory"],
        "occurred_at": occurred_at or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    validate_heartbeat_envelope(envelope)
    return envelope


def _require_exact_fields(value: Mapping[str, object], allowed: frozenset[str], *, path: str) -> None:
    unexpected = sorted(str(key) for key in value if str(key) not in allowed)
    if unexpected:
        raise ValueError(f"registration envelope contains unexpected field at {path}")
    missing = sorted(field for field in allowed if field not in value)
    if missing:
        raise ValueError(f"registration envelope missing field at {path}")


def _validate_inventory(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("registration device_inventory must be an object")
    _require_exact_fields(value, DEVICE_INVENTORY_FIELDS, path="device_inventory")
    devices = value.get("devices")
    if not isinstance(devices, list):
        raise ValueError("registration device_inventory.devices must be a list")
    discovered_count = value.get("konica_discovered_count")
    if type(discovered_count) is not int or discovered_count < 0:
        raise ValueError("registration discovered count must be a non-negative integer")
    if discovered_count != len(devices):
        raise ValueError("registration discovered count does not match devices")
    for device in devices:
        if not isinstance(device, Mapping):
            raise ValueError("registration device must be an object")
        _require_exact_fields(device, DEVICE_FIELDS, path="device_inventory.devices")
        if not isinstance(device.get("serial_number"), str):
            raise ValueError("registration serial_number must be a string")
        if not isinstance(device.get("model"), str):
            raise ValueError("registration model must be a string")
        if type(device.get("selected")) is not bool:
            raise ValueError("registration selected must be a boolean")
        slot = device.get("device_slot")
        if device["selected"]:
            if type(slot) is not int:
                raise ValueError("registration device_slot must be an integer")
        elif slot is not None:
            raise ValueError("unselected registration device must not have device_slot")
    normalized = normalize_device_inventory(devices)
    if normalized != dict(value):
        raise ValueError("registration device inventory is not normalized")


def validate_registration_envelope(value: Mapping[str, object]) -> None:
    """Validate an exact schema-v2 register body before storage or transport."""

    assert_registration_boundary(value)
    _require_exact_fields(value, REGISTER_FIELDS, path="root")
    if value.get("schema_version") != REGISTRATION_SCHEMA_VERSION:
        raise ValueError("unsupported registration schema_version")
    if value.get("event_type") != "installation_registered":
        raise ValueError("unsupported registration event_type")
    for field in (
        "installation_id",
        "company_name",
        "client_first_started_at",
        "app_version",
        "platform",
        "architecture",
        "created_at",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise ValueError(f"registration envelope invalid field: {field}")
    _validate_inventory(value.get("device_inventory"))


def validate_heartbeat_envelope(value: Mapping[str, object]) -> None:
    """Validate an exact schema-v2 heartbeat body before storage or transport."""

    assert_registration_boundary(value)
    _require_exact_fields(value, HEARTBEAT_FIELDS, path="root")
    if value.get("schema_version") != REGISTRATION_SCHEMA_VERSION:
        raise ValueError("unsupported registration schema_version")
    for field in (
        "installation_id",
        "app_version",
        "platform",
        "architecture",
        "occurred_at",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise ValueError(f"registration heartbeat invalid field: {field}")
    _validate_inventory(value.get("device_inventory"))


def assert_registration_boundary(value: object) -> None:
    """Fail closed if a nested payload contains a forbidden field name."""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in EXCLUDED_REGISTRATION_FIELDS:
                raise ValueError(f"registration envelope contains excluded field: {key}")
            assert_registration_boundary(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            assert_registration_boundary(nested)
