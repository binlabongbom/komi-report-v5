from __future__ import annotations

from datetime import UTC, datetime, timedelta

from komi_version import APP_VERSION
from services.v5_2_contract import build_status_payload
from services.v5_2_outbox import V52OutboxRepository, compute_retry_delay_seconds

NOW = datetime(2026, 8, 25, 3, tzinfo=UTC)


def _status(second: int):
    return build_status_payload(
        installation_id="44444444-4444-4444-8444-444444444444",
        app_version=APP_VERSION,
        platform_name="TestOS",
        architecture="test64",
        occurred_at=f"2026-08-25T03:00:{second:02d}Z",
    )


def test_pending_status_coalesces_atomically_with_new_key_and_inflight_is_immutable():
    repository = V52OutboxRepository()
    first = repository.coalesce("status", _status(1), now=NOW)
    replacement = repository.coalesce("status", _status(2), now=NOW + timedelta(seconds=1))

    assert first.operation_id != replacement.operation_id
    assert first.idempotency_key != replacement.idempotency_key
    assert repository.pending_count("status") == 1
    claimed = repository.claim_due(now=NOW + timedelta(seconds=2))
    assert claimed is not None and claimed.operation_id == replacement.operation_id

    latest = repository.coalesce("status", _status(3), now=NOW + timedelta(seconds=3))
    assert latest.operation_id != claimed.operation_id
    assert repository.get(claimed.operation_id).state == "in_flight"
    assert repository.pending_count("status") == 1


def test_restart_recovery_keeps_same_body_fingerprint_and_idempotency_key():
    repository = V52OutboxRepository()
    queued = repository.coalesce("status", _status(1), now=NOW)
    claimed = repository.claim_due(now=NOW)
    assert claimed is not None

    assert V52OutboxRepository().recover_in_flight(now=NOW + timedelta(minutes=1)) == 1
    recovered = V52OutboxRepository().claim_due(now=NOW + timedelta(minutes=1))
    assert recovered is not None
    assert recovered.operation_id == queued.operation_id
    assert recovered.idempotency_key == queued.idempotency_key
    assert recovered.request_fingerprint == queued.request_fingerprint


def test_retry_schedule_uses_retry_after_then_15m_1h_6h_cap_with_jitter():
    assert compute_retry_delay_seconds(0, retry_after_seconds=1200, random_unit=0.5) == 1200
    assert compute_retry_delay_seconds(0, retry_after_seconds=None, random_unit=0.5) == 900
    assert compute_retry_delay_seconds(1, retry_after_seconds=None, random_unit=0.5) == 3600
    assert compute_retry_delay_seconds(2, retry_after_seconds=None, random_unit=0.5) == 21_600
    assert compute_retry_delay_seconds(99, retry_after_seconds=None, random_unit=0.5) == 21_600


def test_terminal_failure_does_not_retry_and_success_sets_cooldown_observation():
    repository = V52OutboxRepository()
    repository.coalesce("status", _status(1), now=NOW)
    claimed = repository.claim_due(now=NOW)
    assert claimed is not None
    assert repository.complete_terminal(claimed, error_code="validation_error", now=NOW)
    assert repository.claim_due(now=NOW + timedelta(days=1)) is None

    repository.coalesce("status", _status(2), now=NOW + timedelta(seconds=1))
    second = repository.claim_due(now=NOW + timedelta(seconds=1))
    assert second is not None
    assert repository.complete_success(second, observed_at=NOW + timedelta(seconds=1))
    assert repository.recovery_send_allowed("status", now=NOW + timedelta(minutes=14)) is False
    assert repository.recovery_send_allowed("status", now=NOW + timedelta(minutes=16)) is True
