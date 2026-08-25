from __future__ import annotations

import json

from services.installation_identity import load_or_create_installation_identity
from services.registration_vault import (
    SessionRegistrationSecretStore,
    installation_token_reference,
)
from services.v5_2_client import (
    V52ContractClient,
    V52RuntimeConfig,
    V52TransportResponse,
)
from services.v5_2_contract import (
    build_meter_payload,
    build_registration_payload,
    build_status_payload,
    validate_registration_payload,
)
from services.v5_2_outbox import V52OutboxRepository


class ContractStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def request(self, *, url, headers, body, timeout):
        payload = json.loads(body)
        self.calls.append((url, dict(headers), payload))
        installation_id = payload["installation_id"]
        if url.endswith("/register"):
            validate_registration_payload(payload)
            assert "Authorization" not in headers
            response = {
                "schema_version": 3,
                "installation_id": installation_id,
                "registration_status": "registered",
                "registered_at": "2026-08-25T03:00:01Z",
                "installation_token": "synthetic-installation-token",
                "token_type": "Bearer",
                "expires_in": 2_592_000,
                "next_status_after_seconds": 21_600,
                "next_meter_after_seconds": 21_600,
            }
            return V52TransportResponse(201, {}, json.dumps(response).encode())
        assert headers["Authorization"] == "Bearer synthetic-installation-token"
        if url.endswith("/status"):
            response = {
                "schema_version": 3,
                "installation_id": installation_id,
                "received_at": "2026-08-25T03:02:01Z",
                "next_status_after_seconds": 21_600,
            }
        else:
            response = {
                "schema_version": 3,
                "installation_id": installation_id,
                "received_at": "2026-08-25T03:03:01Z",
                "next_meter_after_seconds": 21_600,
            }
        return V52TransportResponse(200, {}, json.dumps(response).encode())


def test_local_fixture_register_status_meter_e2e_without_shared_api_key():
    vault = SessionRegistrationSecretStore()
    identity = load_or_create_installation_identity(vault, "install-local-e2e-v52")
    repository = V52OutboxRepository()
    stub = ContractStub()
    client = V52ContractClient(
        V52RuntimeConfig("http://127.0.0.1:9876", "local"),
        transport=stub,
    )
    registration = build_registration_payload(
        identity=identity,
        company_name="Synthetic E2E Company",
        first_started_at="2026-08-25",
        app_version="5.2.0",
        devices=[
            {"serial_number": "SYNTH-001", "model": "bizhub C450i", "selected": True, "device_slot": 1}
        ],
        platform_name="TestOS",
        architecture="test64",
        created_at="2026-08-25T03:00:00Z",
    )
    repository.coalesce("register", registration)
    register_operation = repository.claim_due()
    assert register_operation is not None
    registered = client.send(register_operation)
    assert registered.success and registered.installation_token
    token_ref = installation_token_reference(identity.installation_id)
    vault.save(token_ref, registered.installation_token)
    assert repository.complete_success(register_operation)

    repository.coalesce(
        "status",
        build_status_payload(
            installation_id=identity.installation_id,
            app_version="5.2.0",
            platform_name="TestOS",
            architecture="test64",
            occurred_at="2026-08-25T03:02:00Z",
        ),
    )
    status_operation = repository.claim_due()
    assert status_operation is not None
    assert client.send(status_operation, installation_token=vault.load(token_ref)).success
    assert repository.complete_success(status_operation)

    repository.coalesce(
        "meter",
        build_meter_payload(
            installation_id=identity.installation_id,
            observations=[
                {
                    "serial_number": "SYNTH-001",
                    "model": "bizhub C450i",
                    "device_slot": 1,
                    "total_meter": 123,
                    "meter_observed_at": "2026-08-25T03:03:00Z",
                    "meter_status": "ok",
                }
            ],
            sent_at="2026-08-25T03:03:01Z",
        ),
    )
    meter_operation = repository.claim_due()
    assert meter_operation is not None
    assert client.send(meter_operation, installation_token=vault.load(token_ref)).success
    assert repository.complete_success(meter_operation)

    assert len(stub.calls) == 3
    serialized_headers = json.dumps([headers for _, headers, _ in stub.calls])
    assert "bootstrap" not in serialized_headers.casefold()
    assert all("Idempotency-Key" in headers for _, headers, _ in stub.calls)


def test_client_fails_closed_when_queued_body_changes_after_claim():
    identity = load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "install-tamper-v52"
    )
    repository = V52OutboxRepository()
    stub = ContractStub()
    client = V52ContractClient(
        V52RuntimeConfig("http://127.0.0.1:9876", "local"), transport=stub
    )
    payload = build_registration_payload(
        identity=identity,
        company_name="Synthetic E2E Company",
        first_started_at="2026-08-25",
        app_version="5.2.0",
        devices=[
            {"serial_number": "SYNTH-001", "model": "bizhub C450i", "selected": True, "device_slot": 1}
        ],
        platform_name="TestOS",
        architecture="test64",
        created_at="2026-08-25T03:00:00Z",
    )
    repository.coalesce("register", payload)
    operation = repository.claim_due()
    assert operation is not None
    operation.payload["company_name"] = "Changed after claim"

    result = client.send(operation)

    assert result.success is False
    assert result.error_code == "request_fingerprint_mismatch"
    assert result.retryable is False
    assert stub.calls == []


def test_client_honors_retry_after_and_treats_validation_as_terminal():
    class ErrorStub:
        def __init__(self, status: int, retryable: bool, headers=None) -> None:
            self.status = status
            self.retryable = retryable
            self.headers = headers or {}

        def request(self, **_kwargs):
            body = {
                "error": {
                    "code": "RATE_LIMITED" if self.retryable else "VALIDATION_ERROR",
                    "message": "Synthetic safe message",
                    "request_id": "synthetic-request",
                    "retryable": self.retryable,
                }
            }
            return V52TransportResponse(self.status, self.headers, json.dumps(body).encode())

    repository = V52OutboxRepository()
    repository.coalesce(
        "status",
        build_status_payload(
            installation_id="install-error-v52",
            app_version="5.2.0",
            platform_name="TestOS",
            architecture="test64",
            occurred_at="2026-08-25T03:02:00Z",
        ),
    )
    operation = repository.claim_due()
    assert operation is not None
    config = V52RuntimeConfig("http://127.0.0.1:9876", "local")

    limited = V52ContractClient(
        config, transport=ErrorStub(429, True, {"Retry-After": "900"})
    ).send(operation, installation_token="synthetic-installation-token")
    assert limited.retryable is True and limited.retry_after_seconds == 900

    terminal = V52ContractClient(config, transport=ErrorStub(422, False)).send(
        operation, installation_token="synthetic-installation-token"
    )
    assert terminal.retryable is False and terminal.error_code == "validation_error"
