"""Offline request creation and Host-signed license verification for V5.2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.installation_identity import InstallationIdentity

REQUEST_FIELDS = frozenset(
    {
        "request_version",
        "request_id",
        "company_name",
        "installation_id",
        "installation_public_key",
        "app_version",
        "platform",
        "architecture",
        "selected_devices",
        "created_at",
        "request_signature",
    }
)
LICENSE_FIELDS = frozenset(
    {
        "license_version",
        "license_id",
        "request_id",
        "company_name",
        "installation_id",
        "installation_public_key_sha256",
        "selected_devices",
        "max_desktop_installations",
        "max_selected_printers",
        "issued_at",
        "valid_from",
        "expires_at",
        "kid",
        "signature",
    }
)
DEVICE_FIELDS = frozenset({"serial_number", "model", "device_slot"})
MAX_OFFLINE_FILE_BYTES = 262_144


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_exact(value: Mapping[str, object], fields: frozenset[str], path: str) -> None:
    if set(value) != fields:
        unexpected = sorted(set(value) - fields)
        missing = sorted(fields - set(value))
        raise ValueError(f"offline {path} fields invalid; unexpected={unexpected}; missing={missing}")


def _devices(values: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    serials: set[str] = set()
    slots: set[int] = set()
    for raw in values:
        _require_exact(raw, DEVICE_FIELDS, "device")
        serial = str(raw.get("serial_number") or "").strip()
        model = str(raw.get("model") or "").strip()
        slot = raw.get("device_slot")
        if not serial or serial.casefold() in serials:
            raise ValueError("offline device serial_number is missing or duplicated")
        if not model or type(slot) is not int or not 1 <= slot <= 3 or slot in slots:
            raise ValueError("offline device model/slot is invalid or duplicated")
        serials.add(serial.casefold())
        slots.add(slot)
        normalized.append({"serial_number": serial, "model": model, "device_slot": slot})
    if not 1 <= len(normalized) <= 3:
        raise ValueError("offline request requires one to three selected devices")
    return sorted(normalized, key=lambda item: int(item["device_slot"]))


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"offline {field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"offline {field} must be a UTC timestamp") from err
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"offline {field} must be a UTC timestamp")
    return parsed.astimezone(UTC)


def create_offline_request(
    *,
    identity: InstallationIdentity,
    company_name: str,
    app_version: str,
    platform_name: str,
    architecture: str,
    selected_devices: Iterable[Mapping[str, object]],
    request_id: str,
    created_at: str | None = None,
    adapter: DraftV1SigningAdapter | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_version": 1,
        "request_id": request_id.strip(),
        "company_name": " ".join(company_name.split()),
        "installation_id": identity.installation_id,
        "installation_public_key": identity.public_key_base64url,
        "app_version": app_version.strip(),
        "platform": platform_name.strip(),
        "architecture": architecture.strip(),
        "selected_devices": _devices(selected_devices),
        "created_at": created_at or _now(),
    }
    signing = adapter or DraftV1SigningAdapter()
    payload["request_signature"] = identity.sign(
        signing.canonical_bytes(payload, exclude_fields=frozenset({"request_signature"}))
    )
    validate_offline_request(payload, adapter=signing)
    return payload


def validate_offline_request(
    payload: Mapping[str, object], *, adapter: DraftV1SigningAdapter | None = None
) -> None:
    _require_exact(payload, REQUEST_FIELDS, "request")
    if payload.get("request_version") != 1:
        raise ValueError("offline request_version is invalid")
    for field in (
        "request_id",
        "company_name",
        "installation_id",
        "installation_public_key",
        "app_version",
        "platform",
        "architecture",
    ):
        if not isinstance(payload.get(field), str) or not str(payload[field]).strip():
            raise ValueError(f"offline request {field} is required")
    _timestamp(payload.get("created_at"), "created_at")
    devices = payload.get("selected_devices")
    if not isinstance(devices, list) or _devices(devices) != devices:
        raise ValueError("offline request selected_devices are invalid")
    signing = adapter or DraftV1SigningAdapter()
    if not signing.verify_envelope(
        payload,
        signature_field="request_signature",
        public_key_base64url=str(payload["installation_public_key"]),
    ):
        raise ValueError("offline request signature is invalid")


def write_offline_request(path: Path, payload: Mapping[str, object]) -> Path:
    """Atomically write one validated, signed ``.komirequest`` file."""

    if path.suffix.casefold() != ".komirequest":
        raise ValueError("offline request file must use .komirequest")
    validate_offline_request(payload)
    raw = DraftV1SigningAdapter().canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as temporary:
        temporary.write(raw)
        temporary.flush()
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
    return path


def load_offline_license(path: Path) -> dict[str, object]:
    """Load a bounded ``.komilicense`` envelope without executing any content."""

    if path.suffix.casefold() != ".komilicense":
        raise ValueError("offline license file must use .komilicense")
    try:
        size = path.stat().st_size
        if not 1 <= size <= MAX_OFFLINE_FILE_BYTES:
            raise ValueError("offline license file size is invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ValueError("offline license file is invalid") from err
    if not isinstance(payload, dict):
        raise ValueError("offline license file must contain an object")
    return payload


@dataclass(frozen=True)
class VerifiedOfflineLicense:
    license_id: str
    request_id: str
    expires_at: str
    kid: str
    telemetry_enabled: bool = False


def _five_year_limit(valid_from: datetime) -> datetime:
    try:
        return valid_from.replace(year=valid_from.year + 5)
    except ValueError:
        return valid_from.replace(month=2, day=28, year=valid_from.year + 5)


def verify_offline_license(
    payload: Mapping[str, object],
    *,
    identity: InstallationIdentity,
    request_payload: Mapping[str, object],
    host_public_keys: Mapping[str, str],
    now: datetime | None = None,
    adapter: DraftV1SigningAdapter | None = None,
) -> VerifiedOfflineLicense:
    validate_offline_request(request_payload, adapter=adapter)
    _require_exact(payload, LICENSE_FIELDS, "license")
    if payload.get("license_version") != 1:
        raise ValueError("offline license_version is invalid")
    kid = payload.get("kid")
    if not isinstance(kid, str) or kid not in host_public_keys:
        raise ValueError("offline license kid is unknown")
    signing = adapter or DraftV1SigningAdapter()
    if not signing.verify_envelope(
        payload,
        signature_field="signature",
        public_key_base64url=host_public_keys[kid],
    ):
        raise ValueError("offline license signature is invalid")
    if payload.get("installation_id") != identity.installation_id:
        raise ValueError("offline license installation does not match this Desktop")
    expected_key_hash = hashlib.sha256(identity.public_key_bytes).hexdigest()
    if payload.get("installation_public_key_sha256") != expected_key_hash:
        raise ValueError("offline license installation public key does not match")
    for field in ("request_id", "company_name", "installation_id", "selected_devices"):
        if payload.get(field) != request_payload.get(field):
            raise ValueError(f"offline license {field} does not match its request")
    if payload.get("max_desktop_installations") != 1 or payload.get("max_selected_printers") != 3:
        raise ValueError("offline license limits are invalid")
    devices = payload.get("selected_devices")
    if not isinstance(devices, list) or _devices(devices) != devices:
        raise ValueError("offline license selected_devices are invalid")
    issued_at = _timestamp(payload.get("issued_at"), "issued_at")
    valid_from = _timestamp(payload.get("valid_from"), "valid_from")
    expires_at = _timestamp(payload.get("expires_at"), "expires_at")
    if issued_at > expires_at or expires_at <= valid_from:
        raise ValueError("offline license dates are invalid")
    if expires_at > _five_year_limit(valid_from):
        raise ValueError("offline license validity exceeds five years")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if current < valid_from or current >= expires_at:
        raise ValueError("offline license is not currently valid")
    license_id = payload.get("license_id")
    request_id = payload.get("request_id")
    if not isinstance(license_id, str) or not license_id or not isinstance(request_id, str):
        raise ValueError("offline license identity is invalid")
    return VerifiedOfflineLicense(
        license_id=license_id,
        request_id=request_id,
        expires_at=str(payload["expires_at"]),
        kid=kid,
    )


def import_offline_license(
    path: Path,
    *,
    identity: InstallationIdentity,
    request_payload: Mapping[str, object],
    host_public_keys: Mapping[str, str],
    now: datetime | None = None,
    adapter: DraftV1SigningAdapter | None = None,
) -> VerifiedOfflineLicense:
    return verify_offline_license(
        load_offline_license(path),
        identity=identity,
        request_payload=request_payload,
        host_public_keys=host_public_keys,
        now=now,
        adapter=adapter,
    )
