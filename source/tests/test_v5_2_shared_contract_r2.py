from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.installation_identity import load_or_create_installation_identity
from services.offline_license import create_offline_request, verify_offline_license
from services.registration_vault import SessionRegistrationSecretStore
from services.v5_2_client import (
    V52ContractClient,
    V52RuntimeConfig,
    V52TransportResponse,
)
from services.v5_2_outbox import V52OutboxOperation, request_fingerprint

INSTALLATION_ID = "11111111-1111-4111-8111-111111111111"
GOLDEN_PUBLIC_KEY = "9b_FUDgwK9eBjnOgF7caNdDfHkijdmdFYAtuWJpdffY"
GOLDEN_SIGNATURE = (
    "mZPjRq3loU6fmAzeAjQuAAiPz11LgUVxUSgdftJrEfr2u3cH7Szh7CbZP5H7N44WH3x74H4v0MRvX_ufn4zkDA"
)
GOLDEN_PAYLOAD = {
    "schema_version": 3,
    "event_type": "installation_status",
    "installation_id": INSTALLATION_ID,
    "app_version": "5.2.0",
    "platform": "Golden",
    "architecture": "x64",
    "occurred_at": "2026-08-25T03:02:00Z",
    "request_signature": GOLDEN_SIGNATURE,
}


class _ResponseTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def request(self, **_kwargs) -> V52TransportResponse:
        return V52TransportResponse(
            status=200,
            headers={},
            body=json.dumps(self.payload).encode("utf-8"),
        )


def _operation(event_type: str, payload: dict[str, object]) -> V52OutboxOperation:
    return V52OutboxOperation(
        operation_id="22222222-2222-4222-8222-222222222222",
        event_type=event_type,  # type: ignore[arg-type]
        idempotency_key="33333333-3333-4333-8333-333333333333",
        request_fingerprint=request_fingerprint(payload),
        payload=payload,
        state="pending",
        attempt_count=0,
        next_attempt_at="2026-08-25T03:02:00Z",
        last_error_code="",
        created_at="2026-08-25T03:02:00Z",
        updated_at="2026-08-25T03:02:00Z",
        completed_at="",
    )


def _client(response: dict[str, object]) -> V52ContractClient:
    return V52ContractClient(
        V52RuntimeConfig("http://127.0.0.1:8080", "local"),
        transport=_ResponseTransport(response),
    )


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_shared_golden_vector_uses_raw_32_byte_ed25519_key_and_canonical_json():
    raw_public = base64.urlsafe_b64decode(GOLDEN_PUBLIC_KEY + "=")
    assert len(raw_public) == 32
    assert hashlib.sha256(raw_public).hexdigest() == (
        "3ed4ffe5f106cdf450f5f6e41d5bbbf3e0e5081fd00766e86348352f6f9a9700"
    )
    assert DraftV1SigningAdapter().verify_envelope(
        GOLDEN_PAYLOAD,
        signature_field="request_signature",
        public_key_base64url=GOLDEN_PUBLIC_KEY,
    )


def test_desktop_accepts_declared_meter_response_and_status_token_rotation():
    meter_payload = {"installation_id": INSTALLATION_ID, "observations": [{}, {}, {}]}
    meter = _client(
        {
            "schema_version": 3,
            "installation_id": INSTALLATION_ID,
            "received_at": "2026-08-25T03:02:01Z",
            "accepted_observations": 3,
            "next_meter_after_seconds": 21_600,
        }
    ).send(_operation("meter", meter_payload), installation_token="current-token")
    assert meter.success

    status_payload = {"installation_id": INSTALLATION_ID}
    status = _client(
        {
            "schema_version": 3,
            "installation_id": INSTALLATION_ID,
            "received_at": "2026-08-25T03:02:01Z",
            "next_status_after_seconds": 21_600,
            "rotated_installation_token": "rotated-token",
        }
    ).send(_operation("status", status_payload), installation_token="current-token")
    assert status.success
    assert status.installation_token == "rotated-token"


def test_desktop_accepts_host_offline_license_algorithm_and_raw_key_hash():
    vault = SessionRegistrationSecretStore()
    identity = load_or_create_installation_identity(vault, INSTALLATION_ID)
    request = create_offline_request(
        identity=identity,
        company_name="Synthetic Shared Contract",
        app_version="5.2.0",
        platform_name="Synthetic",
        architecture="x64",
        selected_devices=[
            {"serial_number": "SYNTH-R2-001", "model": "bizhub C450i", "device_slot": 1}
        ],
        request_id="44444444-4444-4444-8444-444444444444",
        created_at="2026-08-25T03:00:00Z",
    )
    host_private = Ed25519PrivateKey.generate()
    host_public = _b64url(host_private.public_key().public_bytes_raw())
    license_payload: dict[str, object] = {
        "license_version": 1,
        "license_id": "55555555-5555-4555-8555-555555555555",
        "request_id": request["request_id"],
        "company_name": request["company_name"],
        "installation_id": INSTALLATION_ID,
        "installation_public_key_sha256": hashlib.sha256(identity.public_key_bytes).hexdigest(),
        "selected_devices": request["selected_devices"],
        "max_desktop_installations": 1,
        "max_selected_printers": 3,
        "issued_at": "2026-08-25T03:01:00Z",
        "valid_from": "2026-08-25T00:00:00Z",
        "expires_at": "2031-08-25T00:00:00Z",
        "algorithm": "Ed25519",
        "kid": "synthetic-host-r2",
    }
    license_payload["signature"] = DraftV1SigningAdapter().sign_envelope(
        license_payload,
        signature_field="signature",
        private_key=host_private,
    )
    verified = verify_offline_license(
        license_payload,
        identity=identity,
        request_payload=request,
        host_public_keys={"synthetic-host-r2": host_public},
        now=datetime(2026, 8, 25, 4, tzinfo=UTC),
    )
    assert UUID(verified.license_id)
