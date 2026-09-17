from dataclasses import replace
import json

import pytest

from services.registration_recovery import RegistrationRecovery
from services.v5_2_client import V52ContractClient, V52RuntimeConfig, V52NetworkError, V52TransportResponse
from services.v5_2_outbox import V52OutboxRepository, request_fingerprint
from services.v5_2_contract import build_registration_payload
from komi_version import APP_VERSION
from test_v5_2_contract import _identity, _devices

ENDPOINT = "https://www.dmskm.com/api/v1/installations/register"


class Transport:
    def __init__(self, error=None):
        self.error = error
        self.requests = []

    def request(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise V52NetworkError(self.error)
        body = json.loads(kwargs["body"])
        return V52TransportResponse(200, {}, json.dumps({
            "schema_version": 3, "installation_id": body["installation_id"],
            "registration_status": "registered", "registered_at": "2026-09-17T00:00:00Z",
            "installation_token": "test-token", "token_type": "Bearer", "expires_in": 2592000,
            "next_status_after_seconds": 21600, "next_meter_after_seconds": 21600,
        }).encode())


def operation():
    payload = build_registration_payload(identity=_identity(), company_name="Synthetic",
        first_started_at="2026-08-25", app_version=APP_VERSION, devices=_devices(),
        platform_name="TestOS", architecture="test64", created_at="2026-09-17T00:00:00Z")
    return V52OutboxRepository().coalesce("register", payload)


def client(recovery, normal=None):
    return V52ContractClient(V52RuntimeConfig("https://www.dmskm.com", "production"),
        transport=normal or Transport("tls_certificate_error"),
        registration_recovery=RegistrationRecovery(recovery, endpoint=ENDPOINT))


def test_success_closes_durably_after_restart():
    op = operation()
    recovery = Transport()
    assert client(recovery).send(op).success
    assert not client(recovery).send(op).success
    assert len(recovery.requests) == 1


def test_timeout_retries_identical_request_and_key_after_restart():
    op = operation()
    recovery = Transport("connection_timeout")
    assert client(recovery).send(op).retryable
    assert not client(recovery).send(replace(op, idempotency_key="different")).success
    recovery.error = None
    assert client(recovery).send(op).success
    assert recovery.requests[0] == recovery.requests[1]


@pytest.mark.parametrize("event", ["status", "meter"])
def test_monitoring_never_uses_recovery(event):
    op = replace(operation(), event_type=event)
    recovery = Transport()
    result = client(recovery).send(op, installation_token="test-token")
    assert result.error_code == "tls_certificate_error"
    assert result.retryable
    assert not recovery.requests


def test_normal_registration_success_also_closes_recovery():
    op = operation()
    recovery = Transport()
    assert client(recovery, Transport()).send(op).success
    assert not client(recovery).send(op).success
    assert not recovery.requests


def test_existing_installation_upgrade_cannot_use_recovery():
    op = operation()
    from datetime import datetime, UTC
    op = V52OutboxRepository().claim_due()
    assert V52OutboxRepository().complete_success(op, observed_at=datetime.now(UTC))
    recovery = Transport()
    assert not client(recovery).send(op).success
    assert not recovery.requests


def test_recovery_rejects_extra_sensitive_payload_fields():
    op = operation()
    payload = dict(op.payload, ip_address="192.0.2.1")
    op = replace(op, payload=payload, request_fingerprint=request_fingerprint(payload))
    recovery = Transport()
    assert client(recovery).send(op).error_code == "payload_invalid"
    assert not recovery.requests


def test_network_errors_other_than_certificate_do_not_trigger_recovery():
    recovery = Transport()
    assert client(recovery, Transport("connection_timeout")).send(operation()).retryable
    assert not recovery.requests


def test_default_client_does_not_enable_recovery():
    normal = Transport("tls_certificate_error")
    result = V52ContractClient(V52RuntimeConfig("https://www.dmskm.com", "production"),
                               transport=normal).send(operation())
    assert result.error_code == "tls_certificate_error"
    assert len(normal.requests) == 1


def test_recovery_rejects_other_endpoint():
    with pytest.raises(ValueError):
        RegistrationRecovery(Transport(), endpoint="https://example.com/api/v1/installations/register")


def test_invalid_host_acknowledgement_does_not_close_gate():
    class InvalidResponse(Transport):
        def request(self, **kwargs):
            return V52TransportResponse(200, {}, b'{}')
    op = operation()
    assert client(InvalidResponse()).send(op).error_code == "contract_invalid"
    assert client(Transport()).send(op).success
