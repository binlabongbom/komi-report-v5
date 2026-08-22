from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from services.registration_client import (
    NetworkTransportError,
    RegistrationClient,
    TransportResponse,
    UrllibRegistrationTransport,
)
from services.registration_envelope import build_registration_envelope
from services.registration_policy import (
    REQUIRED_NOTICE_FIELDS,
    PrivacyNotice,
    RegistrationRuntimePolicy,
)
from services.registration_repository import RegistrationRepository


class FakeTransport:
    def __init__(self, response: TransportResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _policy(*, bootstrap_mode="vault_header") -> RegistrationRuntimePolicy:
    return RegistrationRuntimePolicy(
        base_url="https://staging.invalid.example",
        environment="staging",
        bootstrap_mode=bootstrap_mode,
        bootstrap_header="X-Synthetic-Bootstrap",
        bootstrap_ref="registration-bootstrap-reference",
        notice=PrivacyNotice(
            version="notice-2026-08",
            approved=True,
            purpose="Synthetic registration contract test",
            fields=REQUIRED_NOTICE_FIELDS,
            retention="Synthetic retention policy",
            deletion_contact="privacy@example.invalid",
            legal_basis="Synthetic approved test basis",
            access_export="Synthetic access and export workflow",
            approval_reference="SYNTHETIC-DPO-TEST-REFERENCE",
            approved_at="2026-08-22T00:00:00+00:00",
            approval_owner="Synthetic Test Approver",
        ),
    )


def _operation():
    payload = build_registration_envelope(
        installation_id="install-client",
        company_name="KOMI-UAT-CLIENT",
        first_started_at="2026-08-22",
        app_version="5.1.0",
        devices=[
            {"serial_number": "SYNTHETIC-1", "model": "bizhub UAT", "selected": True, "device_slot": 1}
        ],
        platform_name="TestOS",
        architecture="test64",
        created_at="2026-08-22T01:00:00+00:00",
    )
    repository = RegistrationRepository()
    repository.upsert_profile_and_enqueue_register(
        payload,
        notice_version="notice-2026-08",
        notice_accepted_at="2026-08-22T00:59:00+00:00",
        now=datetime(2026, 8, 22, 1, tzinfo=UTC),
    )
    return repository.claim_due(now=datetime(2026, 8, 22, 1, tzinfo=UTC))


def test_register_client_sends_exact_payload_and_idempotency_without_returning_raw_body():
    operation = _operation()
    assert operation is not None
    token = "synthetic-scoped-token"
    response = {
        "schema_version": 2,
        "installation_id": "install-client",
        "registration_status": "registered",
        "registered_at": "2026-08-22T01:00:01+00:00",
        "installation_token": token,
        "next_heartbeat_after_seconds": 3600,
    }
    transport = FakeTransport(
        TransportResponse(201, {"X-Request-ID": "request-1"}, json.dumps(response).encode())
    )

    result = RegistrationClient(transport).send(
        operation,
        _policy(),
        bootstrap_secret="synthetic-bootstrap-secret",
    )

    assert result.success is True
    assert result.installation_token == token
    call = transport.calls[0]
    assert call["headers"]["Idempotency-Key"] == operation.idempotency_key
    assert call["headers"]["X-Synthetic-Bootstrap"] == "synthetic-bootstrap-secret"
    assert json.loads(call["body"]) == operation.payload
    assert not hasattr(result, "raw_body")


def test_client_respects_retry_after_and_typed_retryable_error():
    operation = _operation()
    assert operation is not None
    body = {
        "error": {
            "code": "RATE_LIMITED",
            "message": "safe",
            "request_id": "request-rate",
            "retryable": True,
        }
    }
    transport = FakeTransport(
        TransportResponse(429, {"Retry-After": "123"}, json.dumps(body).encode())
    )

    result = RegistrationClient(transport).send(
        operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret"
    )

    assert result.success is False
    assert result.error_code == "rate_limited"
    assert result.retryable is True
    assert result.retry_after_seconds == 123


def test_bad_or_revoked_token_is_action_required_and_never_echoed():
    operation = _operation()
    assert operation is not None
    body = {"error": {"code": "TOKEN_REVOKED", "retryable": True}}
    result = RegistrationClient(
        FakeTransport(TransportResponse(401, {}, json.dumps(body).encode()))
    ).send(operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret")

    assert result.error_code == "token_rejected"
    assert result.retryable is False
    assert result.installation_token == ""


def test_invalid_success_contract_fails_closed():
    operation = _operation()
    assert operation is not None
    transport = FakeTransport(TransportResponse(201, {}, b'{"status":"ok"}'))

    result = RegistrationClient(transport).send(
        operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret"
    )

    assert result.error_code == "contract_invalid"
    assert result.retryable is False


def test_client_revalidates_outbox_payload_before_transport():
    operation = _operation()
    assert operation is not None
    corrupted = replace(operation, payload={**operation.payload, "hostname": "must-not-send"})
    transport = FakeTransport(TransportResponse(201, {}, b"{}"))

    result = RegistrationClient(transport).send(
        corrupted, _policy(), bootstrap_secret="synthetic-bootstrap-secret"
    )

    assert result.error_code == "payload_invalid"
    assert transport.calls == []


def test_client_rejects_non_object_corrupt_outbox_payload():
    operation = _operation()
    assert operation is not None
    corrupted = replace(operation, payload=["not-an-object"])  # type: ignore[arg-type]
    transport = FakeTransport(TransportResponse(201, {}, b"{}"))

    result = RegistrationClient(transport).send(
        corrupted, _policy(), bootstrap_secret="synthetic-bootstrap-secret"
    )

    assert result.error_code == "payload_invalid"
    assert transport.calls == []


def test_success_response_rejects_uncontracted_extra_fields():
    operation = _operation()
    assert operation is not None
    response = {
        "schema_version": 2,
        "installation_id": "install-client",
        "registration_status": "registered",
        "registered_at": "2026-08-22T01:00:01+00:00",
        "installation_token": "synthetic-scoped-token",
        "next_heartbeat_after_seconds": 3600,
        "unexpected": "contract drift",
    }

    result = RegistrationClient(
        FakeTransport(TransportResponse(201, {}, json.dumps(response).encode()))
    ).send(operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret")

    assert result.error_code == "contract_invalid"


def test_offline_transport_is_retryable_without_response_leakage():
    operation = _operation()
    assert operation is not None
    result = RegistrationClient(FakeTransport(NetworkTransportError("offline"))).send(
        operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret"
    )

    assert result.error_code == "offline"
    assert result.retryable is True
    assert result.http_status is None


def test_client_rejects_payload_that_no_longer_matches_idempotency_fingerprint():
    operation = _operation()
    assert operation is not None
    altered = replace(
        operation,
        payload={**operation.payload, "company_name": "KOMI-UAT-ALTERED"},
    )
    transport = FakeTransport(TransportResponse(201, {}, b"{}"))

    result = RegistrationClient(transport).send(
        altered, _policy(), bootstrap_secret="synthetic-bootstrap-secret"
    )

    assert result.error_code == "request_fingerprint_mismatch"
    assert transport.calls == []


def test_untrusted_error_identifier_is_replaced_before_persistence_boundary():
    operation = _operation()
    assert operation is not None
    body = {"error": {"code": "TOKEN secret with spaces", "request_id": "bad/request"}}

    result = RegistrationClient(
        FakeTransport(TransportResponse(400, {}, json.dumps(body).encode()))
    ).send(operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret")

    assert result.error_code == "http_error"
    assert result.request_id == ""


def test_default_transport_refuses_redirect_following():
    handler = UrllibRegistrationTransport._NoRedirect()
    assert handler.redirect_request(
        None, None, 307, "redirect", {}, "https://elsewhere.invalid"
    ) is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", 2.9),
        ("next_heartbeat_after_seconds", 60.9),
        ("installation_token", {"token": "malformed"}),
        ("registered_at", 12345),
        ("registered_at", "not-a-timestamp"),
        ("registered_at", "2026-08-22T08:00:00+07:00"),
    ),
)
def test_success_response_rejects_type_coercion_before_vault_boundary(field, value):
    operation = _operation()
    assert operation is not None
    response = {
        "schema_version": 2,
        "installation_id": "install-client",
        "registration_status": "registered",
        "registered_at": "2026-08-22T01:00:01+00:00",
        "installation_token": "synthetic-scoped-token",
        "next_heartbeat_after_seconds": 3600,
    }
    response[field] = value

    result = RegistrationClient(
        FakeTransport(TransportResponse(201, {}, json.dumps(response).encode()))
    ).send(operation, _policy(), bootstrap_secret="synthetic-bootstrap-secret")

    assert result.error_code == "contract_invalid"
    assert result.installation_token == ""
