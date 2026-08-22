from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from database import _open, factory_reset_v5
from komi_snmp_profiler.credential_store import CredentialStoreError
from services.registration_client import RegistrationClientResult
from services.registration_envelope import build_registration_envelope
from services.registration_policy import (
    REQUIRED_NOTICE_FIELDS,
    PrivacyNotice,
    RegistrationRuntimePolicy,
)
from services.registration_repository import RegistrationRepository
from services.registration_vault import (
    SessionRegistrationSecretStore,
    installation_token_reference,
)
from services.registration_worker import RegistrationProcessor

NOW = datetime(2026, 8, 22, 1, tzinfo=UTC)


def _policy(*, approved: bool = True) -> RegistrationRuntimePolicy:
    return RegistrationRuntimePolicy(
        base_url="https://staging.invalid.example",
        environment="staging",
        bootstrap_mode="vault_header",
        bootstrap_header="X-Synthetic-Bootstrap",
        bootstrap_ref="registration-bootstrap-reference",
        notice=PrivacyNotice(
            version="notice-2026-08",
            approved=approved,
            purpose="Synthetic registration test",
            fields=REQUIRED_NOTICE_FIELDS,
            retention="Synthetic retention",
            deletion_contact="privacy@example.invalid",
            legal_basis="Synthetic legal basis",
            access_export="Synthetic access/export workflow",
            approval_reference="SYNTHETIC-DPO-TEST-REFERENCE",
            approved_at="2026-08-22T00:00:00+00:00",
            approval_owner="Synthetic Test Approver",
        ),
    )


def _seed(repository: RegistrationRepository | None = None) -> RegistrationRepository:
    repository = repository or RegistrationRepository()
    payload = build_registration_envelope(
        installation_id="install-worker",
        company_name="KOMI-UAT-WORKER",
        first_started_at="2026-08-22",
        app_version="5.1.0",
        devices=[
            {"serial_number": "SYNTHETIC-1", "model": "bizhub UAT", "selected": True, "device_slot": 1}
        ],
        platform_name="TestOS",
        architecture="test64",
        created_at=NOW.isoformat(),
    )
    repository.upsert_profile_and_enqueue_register(
        payload,
        notice_version="notice-2026-08",
        notice_accepted_at=NOW.isoformat(),
        now=NOW,
    )
    return repository


class FakeClient:
    def __init__(self, result: RegistrationClientResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def send(self, operation, policy, **kwargs):
        self.calls.append({"operation": operation, "policy": policy, **kwargs})
        return self.result


class SequenceClient:
    def __init__(self, *results: RegistrationClientResult) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def send(self, operation, policy, **kwargs):
        self.calls.append({"operation": operation, "policy": policy, **kwargs})
        return self.results.pop(0)


def _result(
    *,
    success: bool,
    token: str = "",
    retryable: bool = False,
    retry_after: int | None = None,
    error_code: str = "",
) -> RegistrationClientResult:
    return RegistrationClientResult(
        success=success,
        http_status=201 if success else 503,
        error_code=error_code,
        retryable=retryable,
        retry_after_seconds=retry_after,
        request_id="synthetic-request",
        duration_ms=9,
        installation_token=token,
        registered_at=NOW.isoformat() if success else "",
        last_seen_at="",
        next_heartbeat_after_seconds=3600,
    )


def test_missing_policy_blocks_before_network_and_keeps_setup_data():
    repository = _seed()
    client = FakeClient(_result(success=True, token="unused"))
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=lambda: None,
        vault_factory=SessionRegistrationSecretStore,
    )

    assert processor.run_once(now=NOW) is True

    assert client.calls == []
    assert repository.summary().status == "action_required"
    assert repository.profile().company_name == "KOMI-UAT-WORKER"


def test_unapproved_notice_fails_closed_before_vault_or_network():
    repository = _seed()
    client = FakeClient(_result(success=True, token="unused"))
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=lambda: _policy(approved=False),
        vault_factory=lambda: (_ for _ in ()).throw(AssertionError("vault must not open")),
    )

    processor.run_once(now=NOW)

    assert client.calls == []
    assert repository.summary().last_error_code == "privacy_notice_unapproved"


def test_success_saves_scoped_token_to_vault_before_marking_registered():
    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    token = "synthetic-installation-token"
    client = FakeClient(_result(success=True, token=token))
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
    )

    processor.run_once(now=NOW)

    profile = repository.profile()
    assert profile is not None and profile.status == "registered"
    assert profile.token_ref == installation_token_reference("install-worker")
    assert vault.load(profile.token_ref) == token
    with _open(commit=False) as connection:
        dump = "\n".join(connection.iterdump())
    assert token not in dump
    assert client.calls[0]["bootstrap_secret"] == "synthetic-bootstrap"


def test_vault_unavailable_keeps_operation_action_required_and_no_token_reference():
    repository = _seed()
    client = FakeClient(_result(success=True, token="synthetic-installation-token"))

    class FailingVault(SessionRegistrationSecretStore):
        def load(self, reference: str):
            raise CredentialStoreError("vault unavailable")

    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=FailingVault,
    )

    processor.run_once(now=NOW)

    assert repository.summary().last_error_code == "vault_unavailable"
    assert repository.profile().token_ref == ""
    assert client.calls == []


def test_retry_after_wins_over_exponential_backoff_and_restart_recovers_same_key():
    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    client = FakeClient(
        _result(success=False, retryable=True, retry_after=900, error_code="rate_limited")
    )
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
        jitter=lambda _upper: 0,
    )

    processor.run_once(now=NOW)
    summary = repository.summary()
    original_key = client.calls[0]["operation"].idempotency_key

    assert summary.status == "offline_retry"
    assert summary.next_attempt_at >= (NOW + timedelta(seconds=900)).isoformat(timespec="seconds")
    assert RegistrationRepository().claim_due(now=NOW + timedelta(seconds=899)) is None
    replay = RegistrationRepository().claim_due(now=NOW + timedelta(seconds=900))
    assert replay is not None and replay.idempotency_key == original_key


def test_vault_write_is_rolled_back_when_local_success_commit_fails():
    class FailingSuccessRepository(RegistrationRepository):
        def complete_success(self, *args, **kwargs):
            raise RuntimeError("synthetic database failure")

    repository = _seed(FailingSuccessRepository())
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    token_ref = installation_token_reference("install-worker")
    vault.save(token_ref, "previous-token")
    client = FakeClient(_result(success=True, token="replacement-token"))
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
        jitter=lambda _upper: 0,
    )

    processor.run_once(now=NOW)

    assert vault.load(token_ref) == "previous-token"
    assert repository.summary().last_error_code == "local_persistence_error"


def test_heartbeat_uses_scoped_token_rotates_in_vault_and_keeps_cadence():
    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    first_token = "synthetic-installation-token-a"
    rotated_token = "synthetic-installation-token-b"
    heartbeat_success = RegistrationClientResult(
        success=True,
        http_status=200,
        error_code="",
        retryable=False,
        retry_after_seconds=None,
        request_id="synthetic-heartbeat",
        duration_ms=7,
        installation_token=rotated_token,
        registered_at="",
        last_seen_at=(NOW + timedelta(hours=1)).isoformat(),
        next_heartbeat_after_seconds=7200,
    )
    client = SequenceClient(
        _result(success=True, token=first_token),
        heartbeat_success,
    )
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
    )

    processor.run_once(now=NOW)
    processor.run_once(now=NOW + timedelta(hours=1))

    profile = repository.profile()
    assert profile is not None
    assert client.calls[1]["installation_token"] == first_token
    assert client.calls[1]["operation"].event_type == "heartbeat"
    assert vault.load(profile.token_ref) == rotated_token
    assert profile.last_heartbeat_at == (NOW + timedelta(hours=1)).isoformat()
    assert profile.next_heartbeat_at == (NOW + timedelta(hours=3)).isoformat(timespec="seconds")


def test_registration_logs_never_include_token_or_serial_list(caplog):
    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    token = "synthetic-installation-token-log-boundary"
    client = FakeClient(_result(success=True, token=token))
    processor = RegistrationProcessor(
        repository,
        client,  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
    )

    processor.run_once(now=NOW)

    assert token not in caplog.text
    assert "SYNTHETIC-1" not in caplog.text
    assert "KOMI-UAT-WORKER" not in caplog.text


def test_unexpected_client_error_is_recovered_to_retry_without_restart():
    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")

    class ExplodingClient:
        def send(self, *args, **kwargs):
            raise RuntimeError("synthetic unexpected failure")

    processor = RegistrationProcessor(
        repository,
        ExplodingClient(),  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
        jitter=lambda _upper: 0,
    )

    assert processor.run_once(now=NOW) is True
    assert repository.summary().status == "offline_retry"
    assert repository.summary().last_error_code == "worker_unexpected_error"


def test_retry_after_is_measured_from_response_receipt():
    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    slow = RegistrationClientResult(
        success=False,
        http_status=503,
        error_code="rate_limited",
        retryable=True,
        retry_after_seconds=900,
        request_id="synthetic-slow-request",
        duration_ms=5_000,
        installation_token="",
        registered_at="",
        last_seen_at="",
        next_heartbeat_after_seconds=3600,
    )
    processor = RegistrationProcessor(
        repository,
        FakeClient(slow),  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
        jitter=lambda _upper: 0,
    )

    processor.run_once(now=NOW)

    assert repository.summary().next_attempt_at >= (
        NOW + timedelta(seconds=905)
    ).isoformat(timespec="seconds")


def test_factory_reset_serializes_with_in_flight_token_commit():
    entered = threading.Event()
    release = threading.Event()

    class BlockingSuccessRepository(RegistrationRepository):
        def complete_success(self, *args, **kwargs):
            entered.set()
            assert release.wait(timeout=2)
            return super().complete_success(*args, **kwargs)

    repository = _seed(BlockingSuccessRepository())
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    processor = RegistrationProcessor(
        repository,
        FakeClient(_result(success=True, token="synthetic-installation-token")),  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
    )
    worker = threading.Thread(target=lambda: processor.run_once(now=NOW))
    worker.start()
    assert entered.wait(timeout=2)
    reset = threading.Thread(
        target=lambda: factory_reset_v5(registration_secret_store=vault)
    )
    reset.start()
    reset.join(timeout=0.05)
    assert reset.is_alive()

    release.set()
    worker.join(timeout=2)
    reset.join(timeout=2)

    assert not worker.is_alive()
    assert not reset.is_alive()
    assert RegistrationRepository().profile() is None
    assert vault.load(installation_token_reference("install-worker")) is None


def test_factory_reset_waits_for_claimed_network_request_before_returning():
    entered = threading.Event()
    release = threading.Event()

    class BlockingClient:
        def send(self, *args, **kwargs):
            entered.set()
            assert release.wait(timeout=2)
            return _result(success=True, token="synthetic-installation-token")

    repository = _seed()
    vault = SessionRegistrationSecretStore()
    vault.save("registration-bootstrap-reference", "synthetic-bootstrap")
    processor = RegistrationProcessor(
        repository,
        BlockingClient(),  # type: ignore[arg-type]
        policy_loader=_policy,
        vault_factory=lambda: vault,
    )
    worker = threading.Thread(target=lambda: processor.run_once(now=NOW))
    worker.start()
    assert entered.wait(timeout=2)
    reset = threading.Thread(
        target=lambda: factory_reset_v5(registration_secret_store=vault)
    )
    reset.start()
    reset.join(timeout=0.05)
    assert reset.is_alive()

    release.set()
    worker.join(timeout=2)
    reset.join(timeout=2)

    assert not worker.is_alive()
    assert not reset.is_alive()
    assert RegistrationRepository().profile() is None
    assert vault.load(installation_token_reference("install-worker")) is None
