from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.installation_identity import load_or_create_installation_identity
from services.offline_license import (
    create_offline_request,
    import_offline_license,
    verify_offline_license,
    write_offline_request,
)
from services.registration_vault import SessionRegistrationSecretStore


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _host_key() -> Ed25519PrivateKey:
    seed = hashlib.sha256(b"KOMI-V5.2-SYNTHETIC-HOST-TEST-ONLY").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def test_offline_request_is_signed_by_installation_and_contains_no_telemetry():
    identity = load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "66666666-6666-4666-8666-666666666666"
    )
    request = create_offline_request(
        identity=identity,
        company_name="Synthetic Offline Company",
        app_version="5.2.0",
        platform_name="TestOS",
        architecture="test64",
        selected_devices=[
            {"serial_number": "SYNTH-OFF-001", "model": "bizhub C450i", "device_slot": 1}
        ],
        request_id="00000000-0000-4000-8000-000000000001",
        created_at="2026-08-25T03:00:00Z",
    )

    assert DraftV1SigningAdapter().verify_envelope(
        request,
        signature_field="request_signature",
        public_key_base64url=identity.public_key_base64url,
    )
    serialized = DraftV1SigningAdapter().canonical_bytes(request).decode("utf-8")
    assert "total_meter" not in serialized
    assert "heartbeat" not in serialized


def test_offline_request_file_is_atomic_and_license_import_uses_bounded_json(tmp_path):
    identity = load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "77777777-7777-4777-8777-777777777777"
    )
    request = create_offline_request(
        identity=identity,
        company_name="Synthetic Offline Company",
        app_version="5.2.0",
        platform_name="TestOS",
        architecture="test64",
        selected_devices=[
            {"serial_number": "SYNTH-OFF-001", "model": "bizhub C450i", "device_slot": 1}
        ],
        request_id="00000000-0000-4000-8000-000000000011",
        created_at="2026-08-25T03:00:00Z",
    )
    request_path = write_offline_request(tmp_path / "desktop.komirequest", request)
    assert request_path.is_file()
    assert request_path.read_text(encoding="utf-8").endswith("\n")

    host_private = _host_key()
    host_public = _b64url(host_private.public_key().public_bytes_raw())
    license_payload = {
        "license_version": 1,
        "license_id": "00000000-0000-4000-8000-000000000012",
        "request_id": request["request_id"],
        "company_name": request["company_name"],
        "installation_id": request["installation_id"],
        "installation_public_key_sha256": hashlib.sha256(identity.public_key_bytes).hexdigest(),
        "selected_devices": request["selected_devices"],
        "max_desktop_installations": 1,
        "max_selected_printers": 3,
        "issued_at": "2026-08-25T03:01:00Z",
        "valid_from": "2026-08-25T00:00:00Z",
        "expires_at": "2031-08-25T00:00:00Z",
        "algorithm": "Ed25519",
        "kid": "synthetic-host-test-v1",
    }
    license_payload["signature"] = DraftV1SigningAdapter().sign_envelope(
        license_payload, signature_field="signature", private_key=host_private
    )
    license_path = tmp_path / "desktop.komilicense"
    license_path.write_text(json.dumps(license_payload), encoding="utf-8")

    verified = import_offline_license(
        license_path,
        identity=identity,
        request_payload=request,
        host_public_keys={"synthetic-host-test-v1": host_public},
        now=datetime(2026, 8, 25, 4, tzinfo=UTC),
    )
    assert verified.telemetry_enabled is False


def test_offline_license_verifies_host_signature_binding_and_five_year_limit():
    identity = load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "66666666-6666-4666-8666-666666666666"
    )
    request = create_offline_request(
        identity=identity,
        company_name="Synthetic Offline Company",
        app_version="5.2.0",
        platform_name="TestOS",
        architecture="test64",
        selected_devices=[
            {"serial_number": "SYNTH-OFF-001", "model": "bizhub C450i", "device_slot": 1}
        ],
        request_id="00000000-0000-4000-8000-000000000001",
        created_at="2026-08-25T03:00:00Z",
    )
    host_private = _host_key()
    host_public = _b64url(host_private.public_key().public_bytes_raw())
    license_payload = {
        "license_version": 1,
        "license_id": "00000000-0000-4000-8000-000000000002",
        "request_id": request["request_id"],
        "company_name": request["company_name"],
        "installation_id": request["installation_id"],
        "installation_public_key_sha256": hashlib.sha256(
            identity.public_key_bytes
        ).hexdigest(),
        "selected_devices": request["selected_devices"],
        "max_desktop_installations": 1,
        "max_selected_printers": 3,
        "issued_at": "2026-08-25T03:01:00Z",
        "valid_from": "2026-08-25T00:00:00Z",
        "expires_at": "2031-08-25T00:00:00Z",
        "algorithm": "Ed25519",
        "kid": "synthetic-host-test-v1",
    }
    license_payload["signature"] = DraftV1SigningAdapter().sign_envelope(
        license_payload, signature_field="signature", private_key=host_private
    )

    verified = verify_offline_license(
        license_payload,
        identity=identity,
        request_payload=request,
        host_public_keys={"synthetic-host-test-v1": host_public},
        now=datetime(2026, 8, 25, 4, tzinfo=UTC),
    )
    assert verified.license_id == license_payload["license_id"]
    assert verified.telemetry_enabled is False

    license_payload["expires_at"] = "2031-08-26T00:00:00Z"
    license_payload["signature"] = DraftV1SigningAdapter().sign_envelope(
        license_payload, signature_field="signature", private_key=host_private
    )
    with pytest.raises(ValueError, match="five years"):
        verify_offline_license(
            license_payload,
            identity=identity,
            request_payload=request,
            host_public_keys={"synthetic-host-test-v1": host_public},
            now=datetime(2026, 8, 25, 4, tzinfo=UTC),
        )


def test_offline_license_rejects_tamper_or_another_desktop():
    identity = load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "66666666-6666-4666-8666-666666666666"
    )
    other = load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "88888888-8888-4888-8888-888888888888"
    )
    request = create_offline_request(
        identity=identity,
        company_name="Synthetic Offline Company",
        app_version="5.2.0",
        platform_name="TestOS",
        architecture="test64",
        selected_devices=[
            {"serial_number": "SYNTH-OFF-001", "model": "bizhub C450i", "device_slot": 1}
        ],
        request_id="00000000-0000-4000-8000-000000000001",
        created_at="2026-08-25T03:00:00Z",
    )
    host_private = _host_key()
    host_public = _b64url(host_private.public_key().public_bytes_raw())
    payload = {
        "license_version": 1,
        "license_id": "00000000-0000-4000-8000-000000000002",
        "request_id": request["request_id"],
        "company_name": request["company_name"],
        "installation_id": request["installation_id"],
        "installation_public_key_sha256": hashlib.sha256(identity.public_key_bytes).hexdigest(),
        "selected_devices": request["selected_devices"],
        "max_desktop_installations": 1,
        "max_selected_printers": 3,
        "issued_at": "2026-08-25T03:01:00Z",
        "valid_from": "2026-08-25T00:00:00Z",
        "expires_at": "2031-08-25T00:00:00Z",
        "algorithm": "Ed25519",
        "kid": "synthetic-host-test-v1",
    }
    payload["signature"] = DraftV1SigningAdapter().sign_envelope(
        payload, signature_field="signature", private_key=host_private
    )

    with pytest.raises(ValueError, match="installation"):
        verify_offline_license(
            payload,
            identity=other,
            request_payload=request,
            host_public_keys={"synthetic-host-test-v1": host_public},
            now=datetime(2026, 8, 25, 4, tzinfo=UTC),
        )
