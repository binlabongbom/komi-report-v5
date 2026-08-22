from __future__ import annotations

from datetime import UTC, datetime, timedelta

from database import _open
from services.registration_envelope import build_registration_envelope
from services.registration_repository import RegistrationRepository


def _registration(created_at: str = "2026-08-22T01:00:00+00:00") -> dict[str, object]:
    return build_registration_envelope(
        installation_id="install-repository",
        company_name="KOMI-UAT-REPOSITORY",
        first_started_at="2026-08-22",
        app_version="5.1.0",
        devices=[
            {"serial_number": "SYNTHETIC-1", "model": "bizhub UAT", "selected": True, "device_slot": 1},
            {"serial_number": "SYNTHETIC-2", "model": "bizhub UAT", "selected": False, "device_slot": None},
        ],
        platform_name="TestOS",
        architecture="test64",
        created_at=created_at,
    )


def test_register_enqueue_is_durable_and_reuses_idempotency_for_duplicate_payload():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)

    first = repository.upsert_profile_and_enqueue_register(
        _registration(),
        notice_version="notice-2026-08",
        notice_accepted_at="2026-08-22T00:59:00+00:00",
        now=now,
    )
    replay = RegistrationRepository().upsert_profile_and_enqueue_register(
        _registration(),
        notice_version="notice-2026-08",
        notice_accepted_at="2026-08-22T00:59:00+00:00",
        now=now + timedelta(minutes=1),
    )

    assert replay.operation_id == first.operation_id
    assert replay.idempotency_key == first.idempotency_key
    assert replay.request_fingerprint == first.request_fingerprint
    assert RegistrationRepository().claim_due(now=now + timedelta(minutes=2)).operation_id == first.operation_id


def test_restart_recovery_returns_in_flight_operation_to_retry():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    operation = repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    assert repository.claim_due(now=now).state == "in_flight"

    assert RegistrationRepository().recover_in_flight(now=now + timedelta(seconds=5)) == 1
    recovered = RegistrationRepository().claim_due(now=now + timedelta(seconds=5))

    assert recovered is not None
    assert recovered.operation_id == operation.operation_id
    assert recovered.last_error_code == "restart_recovery"


def test_success_schedules_restart_safe_heartbeat_without_copying_company_name():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    operation = repository.claim_due(now=now)
    assert operation is not None
    repository.complete_success(
        operation,
        http_status=201,
        duration_ms=12,
        token_ref="registration-token-reference",
        registered_at=now.isoformat(),
        next_heartbeat_after_seconds=60,
        now=now,
    )

    assert repository.enqueue_heartbeat_if_due(now=now + timedelta(seconds=59)) is None
    heartbeat = RegistrationRepository().enqueue_heartbeat_if_due(now=now + timedelta(seconds=60))

    assert heartbeat is not None
    assert heartbeat.event_type == "heartbeat"
    assert "company_name" not in heartbeat.payload
    assert heartbeat.payload["device_inventory"] == operation.payload["device_inventory"]


def test_retry_history_is_typed_and_manual_retry_keeps_same_idempotency_key():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    operation = repository.claim_due(now=now)
    assert operation is not None
    repository.complete_failure(
        operation,
        error_code="offline",
        retryable=True,
        next_attempt_at=now + timedelta(minutes=2),
        http_status=None,
        retry_after_seconds=None,
        duration_ms=8,
        now=now,
    )

    assert repository.summary().status == "offline_retry"
    assert repository.manual_retry(now=now + timedelta(seconds=10)) == 1
    replay = repository.claim_due(now=now + timedelta(seconds=10))

    assert replay is not None
    assert replay.idempotency_key == operation.idempotency_key
    assert repository.attempts_for(operation.operation_id) == [
        ("retry", None, "offline", 1, None, 8)
    ]


def test_registration_sqlite_contains_token_reference_but_not_token_value():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    operation = repository.claim_due(now=now)
    assert operation is not None
    repository.complete_success(
        operation,
        http_status=201,
        duration_ms=1,
        token_ref="registration-token-reference",
        registered_at=now.isoformat(),
        next_heartbeat_after_seconds=3600,
        now=now,
    )
    secret_value = "synthetic-secret-must-never-enter-sqlite"

    with _open(commit=False) as connection:
        dump = "\n".join(connection.iterdump())

    assert "registration-token-reference" in dump
    assert secret_value not in dump


def test_new_profile_payload_supersedes_stale_action_and_manual_retry_ignores_it():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    first = repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    claimed = repository.claim_due(now=now)
    assert claimed is not None
    repository.complete_failure(
        claimed,
        error_code="payload_rejected",
        retryable=False,
        next_attempt_at=now,
        http_status=422,
        retry_after_seconds=None,
        duration_ms=1,
        now=now,
    )
    newer = repository.upsert_profile_and_enqueue_register(
        _registration("2026-08-22T02:00:00+00:00"),
        notice_version="notice-1",
        notice_accepted_at=now.isoformat(),
        now=now + timedelta(hours=1),
    )

    assert repository.get_operation(first.operation_id) is None
    assert repository.summary().status == "pending"
    assert repository.manual_retry(now=now + timedelta(hours=1)) == 0
    assert repository.claim_due(now=now + timedelta(hours=1)).operation_id == newer.operation_id


def test_privacy_acceptance_requeues_current_action_required_operation():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="", notice_accepted_at="", now=now
    )
    operation = repository.claim_due(now=now)
    assert operation is not None
    repository.complete_failure(
        operation,
        error_code="privacy_notice_not_accepted",
        retryable=False,
        next_attempt_at=now,
        http_status=None,
        retry_after_seconds=None,
        duration_ms=0,
        now=now,
    )

    assert repository.accept_privacy_notice(
        "notice-2", accepted_at=(now + timedelta(minutes=1)).isoformat(), now=now
    )
    assert repository.profile().notice_version == "notice-2"
    assert repository.summary().status == "pending"


def test_success_prunes_obsolete_serial_bearing_operations():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    old = repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    current = repository.upsert_profile_and_enqueue_register(
        _registration("2026-08-22T02:00:00+00:00"),
        notice_version="notice-1",
        notice_accepted_at=now.isoformat(),
        now=now + timedelta(hours=1),
    )
    claimed = repository.claim_due(now=now + timedelta(hours=1))
    assert claimed is not None
    assert repository.complete_success(
        claimed,
        http_status=201,
        duration_ms=1,
        token_ref="registration-token-reference",
        next_heartbeat_after_seconds=3600,
        now=now + timedelta(hours=1),
    )

    assert repository.get_operation(old.operation_id) is None
    assert repository.get_operation(current.operation_id).state == "succeeded"


def test_due_heartbeat_never_supersedes_a_newer_active_register():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository.upsert_profile_and_enqueue_register(
        _registration(), notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    old = repository.claim_due(now=now)
    assert old is not None
    repository.complete_success(
        old,
        http_status=201,
        duration_ms=1,
        token_ref="registration-token-reference",
        next_heartbeat_after_seconds=60,
        now=now,
    )
    newer = repository.upsert_profile_and_enqueue_register(
        _registration("2026-08-22T01:01:00+00:00"),
        notice_version="notice-1",
        notice_accepted_at=now.isoformat(),
        now=now + timedelta(seconds=60),
    )

    assert repository.enqueue_heartbeat_if_due(now=now + timedelta(seconds=60)) is None
    claimed = repository.claim_due(now=now + timedelta(seconds=60))
    assert claimed is not None
    assert claimed.operation_id == newer.operation_id
    assert claimed.event_type == "register"


def test_repeated_blocked_edits_do_not_accumulate_serial_bearing_payloads():
    repository = RegistrationRepository()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    for index in range(5):
        repository.upsert_profile_and_enqueue_register(
            _registration(f"2026-08-22T0{index + 1}:00:00+00:00"),
            notice_version="",
            notice_accepted_at="",
            now=now + timedelta(hours=index),
        )

    with _open(commit=False) as connection:
        rows = connection.execute(
            "SELECT state,payload_json FROM registration_outbox ORDER BY created_at"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "pending"
    assert "2026-08-22T05:00:00+00:00" in rows[0][1]
