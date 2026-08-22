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
        "ip",
        "ip_address",
        "host",
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
    }
)


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
        serial_number = " ".join(str(raw_device.get("serial_number") or "").split()).strip()
        if not serial_number or serial_number == "—":
            raise ValueError("registration device missing serial_number")
        serial_key = serial_number.casefold()
        if serial_key in serials:
            raise ValueError(f"registration device serial_number duplicated: {serial_number}")
        serials.add(serial_key)

        model = " ".join(str(raw_device.get("model") or "").split()).strip()
        if not model or model in {"—", "ไม่ทราบรุ่น"}:
            model = "Unknown"
        selected = bool(raw_device.get("selected"))
        raw_slot = raw_device.get("device_slot")
        if selected:
            try:
                device_slot = int(raw_slot)
            except (TypeError, ValueError):
                raise ValueError("selected registration device missing device_slot") from None
            if not 1 <= device_slot <= MAX_SELECTED_DEVICES:
                raise ValueError("registration device_slot must be between 1 and 3")
            if device_slot in selected_slots:
                raise ValueError(f"registration device_slot duplicated: {device_slot}")
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
    assert_registration_boundary(envelope)
    return envelope


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
