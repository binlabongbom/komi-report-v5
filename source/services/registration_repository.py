"""Durable SQLite registration profile, outbox and attempt history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from database import _open
from services.registration_envelope import (
    build_heartbeat_envelope,
    validate_heartbeat_envelope,
    validate_registration_envelope,
)

EventType = Literal["register", "heartbeat"]
OutboxState = Literal[
    "pending", "in_flight", "retry", "succeeded", "action_required", "superseded"
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def canonical_payload(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_fingerprint(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegistrationProfile:
    installation_id: str
    company_name: str
    client_first_started_at: str
    notice_version: str
    notice_accepted_at: str
    token_ref: str
    status: str
    registered_at: str
    last_heartbeat_at: str
    next_heartbeat_at: str
    last_error_code: str
    updated_at: str


@dataclass(frozen=True)
class OutboxOperation:
    operation_id: str
    event_type: EventType
    idempotency_key: str
    request_fingerprint: str
    payload: dict[str, object]
    state: OutboxState
    attempt_count: int
    next_attempt_at: str
    last_error_code: str
    created_at: str
    updated_at: str
    completed_at: str


@dataclass(frozen=True)
class RegistrationSummary:
    status: Literal["not_configured", "pending", "offline_retry", "registered", "action_required"]
    notice_version: str
    notice_accepted_at: str
    last_error_code: str
    last_heartbeat_at: str
    next_attempt_at: str


class RegistrationRepository:
    def upsert_profile_and_enqueue_register(
        self,
        envelope: Mapping[str, object],
        *,
        notice_version: str,
        notice_accepted_at: str,
        now: datetime | None = None,
    ) -> OutboxOperation:
        validate_registration_envelope(envelope)
        stamp = to_utc_iso(now or utc_now())
        installation_id = str(envelope["installation_id"])
        with _open() as connection:
            existing = connection.execute(
                "SELECT installation_id FROM registration_profile WHERE singleton_id=1"
            ).fetchone()
            if existing and str(existing[0]) != installation_id:
                raise ValueError("Registration installation_id cannot change after initialization")
            connection.execute(
                """INSERT INTO registration_profile(
                       singleton_id,installation_id,company_name,client_first_started_at,
                       notice_version,notice_accepted_at,status,updated_at
                   ) VALUES(1,?,?,?,?,?,'pending',?)
                   ON CONFLICT(singleton_id) DO UPDATE SET
                       company_name=excluded.company_name,
                       client_first_started_at=excluded.client_first_started_at,
                       notice_version=excluded.notice_version,
                       notice_accepted_at=excluded.notice_accepted_at,
                       status=CASE
                           WHEN registration_profile.status='registered' THEN 'registered'
                           ELSE 'pending'
                       END,
                       updated_at=excluded.updated_at""",
                (
                    installation_id,
                    str(envelope["company_name"]),
                    str(envelope["client_first_started_at"]),
                    notice_version.strip(),
                    notice_accepted_at.strip(),
                    stamp,
                ),
            )
            return self._enqueue(connection, "register", envelope, stamp)

    def enqueue_heartbeat_if_due(self, *, now: datetime | None = None) -> OutboxOperation | None:
        current = now or utc_now()
        stamp = to_utc_iso(current)
        with _open() as connection:
            active_register = connection.execute(
                """SELECT 1 FROM registration_outbox
                   WHERE event_type='register'
                     AND state IN ('pending','in_flight','retry','action_required')
                   LIMIT 1"""
            ).fetchone()
            if active_register:
                return None
            profile = connection.execute(
                """SELECT status,next_heartbeat_at FROM registration_profile
                   WHERE singleton_id=1"""
            ).fetchone()
            if not profile or profile[0] != "registered" or not profile[1] or str(profile[1]) > stamp:
                return None
            active = connection.execute(
                """SELECT * FROM registration_outbox
                   WHERE event_type='heartbeat' AND state IN ('pending','in_flight','retry')
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
            if active:
                return self._operation_from_row(active)
            source = connection.execute(
                """SELECT payload_json FROM registration_outbox
                   WHERE event_type='register' AND state='succeeded'
                   ORDER BY completed_at DESC LIMIT 1"""
            ).fetchone()
            if not source:
                return None
            registration = json.loads(str(source[0]))
            heartbeat = build_heartbeat_envelope(registration, occurred_at=stamp)
            return self._enqueue(connection, "heartbeat", heartbeat, stamp)

    def recover_in_flight(self, *, now: datetime | None = None) -> int:
        stamp = to_utc_iso(now or utc_now())
        with _open() as connection:
            cursor = connection.execute(
                """UPDATE registration_outbox
                   SET state='retry',next_attempt_at=?,last_error_code='restart_recovery',updated_at=?
                   WHERE state='in_flight'""",
                (stamp, stamp),
            )
            return int(cursor.rowcount)

    def claim_due(self, *, now: datetime | None = None) -> OutboxOperation | None:
        stamp = to_utc_iso(now or utc_now())
        with _open() as connection:
            row = connection.execute(
                """SELECT * FROM registration_outbox
                   WHERE state IN ('pending','retry') AND next_attempt_at<=?
                   ORDER BY next_attempt_at,created_at LIMIT 1""",
                (stamp,),
            ).fetchone()
            if not row:
                return None
            operation_id = str(row[0])
            updated = connection.execute(
                """UPDATE registration_outbox SET state='in_flight',updated_at=?
                   WHERE operation_id=? AND state IN ('pending','retry')""",
                (stamp, operation_id),
            )
            if updated.rowcount != 1:
                return None
            return self.get_operation(operation_id, connection=connection)

    def complete_success(
        self,
        operation: OutboxOperation,
        *,
        http_status: int,
        duration_ms: int,
        token_ref: str = "",
        registered_at: str = "",
        last_heartbeat_at: str = "",
        next_heartbeat_after_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = now or utc_now()
        stamp = to_utc_iso(current)
        next_heartbeat = to_utc_iso(current + timedelta(seconds=max(1, next_heartbeat_after_seconds)))
        with _open() as connection:
            active = connection.execute(
                "SELECT state FROM registration_outbox WHERE operation_id=?",
                (operation.operation_id,),
            ).fetchone()
            if not active or active[0] != "in_flight":
                return False
            self._record_attempt(
                connection,
                operation,
                attempted_at=stamp,
                outcome="success",
                http_status=http_status,
                error_code="",
                retryable=False,
                retry_after_seconds=None,
                duration_ms=duration_ms,
            )
            connection.execute(
                """UPDATE registration_outbox
                   SET state='succeeded',attempt_count=attempt_count+1,last_error_code='',
                       updated_at=?,completed_at=? WHERE operation_id=?""",
                (stamp, stamp, operation.operation_id),
            )
            if operation.event_type == "register":
                connection.execute(
                    """UPDATE registration_profile
                       SET token_ref=?,status='registered',registered_at=?,next_heartbeat_at=?,
                           last_error_code='',updated_at=? WHERE singleton_id=1""",
                    (token_ref, registered_at or stamp, next_heartbeat, stamp),
                )
            else:
                connection.execute(
                    """UPDATE registration_profile
                       SET status='registered',last_heartbeat_at=?,next_heartbeat_at=?,
                           last_error_code='',updated_at=? WHERE singleton_id=1""",
                    (last_heartbeat_at or stamp, next_heartbeat, stamp),
                )
            self._prune_completed(connection, operation)
            return True

    def complete_failure(
        self,
        operation: OutboxOperation,
        *,
        error_code: str,
        retryable: bool,
        next_attempt_at: datetime,
        http_status: int | None,
        retry_after_seconds: int | None,
        duration_ms: int,
        now: datetime | None = None,
    ) -> bool:
        stamp = to_utc_iso(now or utc_now())
        state = "retry" if retryable else "action_required"
        with _open() as connection:
            active = connection.execute(
                "SELECT state FROM registration_outbox WHERE operation_id=?",
                (operation.operation_id,),
            ).fetchone()
            if not active or active[0] != "in_flight":
                return False
            self._record_attempt(
                connection,
                operation,
                attempted_at=stamp,
                outcome=state,
                http_status=http_status,
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=retry_after_seconds,
                duration_ms=duration_ms,
            )
            connection.execute(
                """UPDATE registration_outbox
                   SET state=?,attempt_count=attempt_count+1,next_attempt_at=?,
                       last_error_code=?,updated_at=? WHERE operation_id=?""",
                (
                    state,
                    to_utc_iso(next_attempt_at),
                    error_code,
                    stamp,
                    operation.operation_id,
                ),
            )
            connection.execute(
                """UPDATE registration_profile SET status=?,last_error_code=?,updated_at=?
                   WHERE singleton_id=1""",
                (state, error_code, stamp),
            )
            return True

    def manual_retry(self, *, now: datetime | None = None) -> int:
        stamp = to_utc_iso(now or utc_now())
        with _open() as connection:
            cursor = connection.execute(
                """UPDATE registration_outbox
                   SET state='pending',next_attempt_at=?,last_error_code='',updated_at=?
                   WHERE state IN ('retry','action_required')""",
                (stamp, stamp),
            )
            if cursor.rowcount:
                connection.execute(
                    """UPDATE registration_profile SET status='pending',last_error_code='',updated_at=?
                       WHERE singleton_id=1""",
                    (stamp,),
                )
            return int(cursor.rowcount)

    def accept_privacy_notice(
        self,
        notice_version: str,
        *,
        accepted_at: str,
        now: datetime | None = None,
    ) -> bool:
        """Persist explicit acceptance and make the current operation eligible to retry."""

        version = notice_version.strip()
        acceptance = accepted_at.strip()
        if not version or not acceptance:
            raise ValueError("Privacy Notice version and acceptance timestamp are required")
        stamp = to_utc_iso(now or utc_now())
        with _open() as connection:
            updated = connection.execute(
                """UPDATE registration_profile
                   SET notice_version=?,notice_accepted_at=?,status='pending',
                       last_error_code='',updated_at=? WHERE singleton_id=1""",
                (version, acceptance, stamp),
            )
            if updated.rowcount != 1:
                return False
            connection.execute(
                """UPDATE registration_outbox
                   SET state='pending',next_attempt_at=?,last_error_code='',updated_at=?
                   WHERE state IN ('retry','action_required')""",
                (stamp, stamp),
            )
            return True

    def profile(self) -> RegistrationProfile | None:
        with _open(commit=False) as connection:
            row = connection.execute(
                """SELECT installation_id,company_name,client_first_started_at,
                          notice_version,notice_accepted_at,token_ref,status,registered_at,
                          last_heartbeat_at,next_heartbeat_at,last_error_code,updated_at
                   FROM registration_profile WHERE singleton_id=1"""
            ).fetchone()
        return RegistrationProfile(*row) if row else None

    def summary(self) -> RegistrationSummary:
        profile = self.profile()
        if profile is None:
            return RegistrationSummary("not_configured", "", "", "", "", "")
        with _open(commit=False) as connection:
            row = connection.execute(
                """SELECT state,attempt_count,next_attempt_at,last_error_code
                   FROM registration_outbox
                   WHERE state NOT IN ('succeeded','superseded')
                   ORDER BY updated_at DESC LIMIT 1"""
            ).fetchone()
        if row and row[0] == "action_required":
            status = "action_required"
        elif row:
            status = "offline_retry" if row[0] == "retry" else "pending"
        elif profile.status == "registered":
            status = "registered"
        else:
            status = "pending"
        return RegistrationSummary(
            status=status,
            notice_version=profile.notice_version,
            notice_accepted_at=profile.notice_accepted_at,
            last_error_code=(str(row[3]) if row else profile.last_error_code),
            last_heartbeat_at=profile.last_heartbeat_at,
            next_attempt_at=(str(row[2]) if row else profile.next_heartbeat_at),
        )

    def get_operation(
        self,
        operation_id: str,
        *,
        connection=None,
    ) -> OutboxOperation | None:
        if connection is not None:
            row = connection.execute(
                "SELECT * FROM registration_outbox WHERE operation_id=?", (operation_id,)
            ).fetchone()
        else:
            with _open(commit=False) as opened:
                row = opened.execute(
                    "SELECT * FROM registration_outbox WHERE operation_id=?", (operation_id,)
                ).fetchone()
        return self._operation_from_row(row) if row else None

    def attempts_for(self, operation_id: str) -> list[tuple]:
        with _open(commit=False) as connection:
            return connection.execute(
                """SELECT outcome,http_status,error_code,retryable,retry_after_seconds,duration_ms
                   FROM registration_attempt_history WHERE operation_id=? ORDER BY id""",
                (operation_id,),
            ).fetchall()

    def _enqueue(
        self,
        connection,
        event_type: EventType,
        payload: Mapping[str, object],
        stamp: str,
    ) -> OutboxOperation:
        if event_type == "register":
            validate_registration_envelope(payload)
        else:
            validate_heartbeat_envelope(payload)
        fingerprint = request_fingerprint(payload)
        existing = connection.execute(
            """SELECT * FROM registration_outbox
               WHERE event_type=? AND request_fingerprint=?""",
            (event_type, fingerprint),
        ).fetchone()
        if existing:
            existing_operation = self._operation_from_row(existing)
            self._supersede_other_active(
                connection, event_type, existing_operation.operation_id, stamp
            )
            if existing_operation.state == "superseded":
                connection.execute(
                    """UPDATE registration_outbox
                       SET state='pending',next_attempt_at=?,last_error_code='',updated_at=?,completed_at=''
                       WHERE operation_id=?""",
                    (stamp, stamp, existing_operation.operation_id),
                )
                refreshed = self.get_operation(existing_operation.operation_id, connection=connection)
                assert refreshed is not None
                return refreshed
            return existing_operation
        self._supersede_other_active(connection, event_type, "", stamp)
        operation_id = str(uuid4())
        idempotency_key = str(uuid4())
        connection.execute(
            """INSERT INTO registration_outbox(
                   operation_id,event_type,idempotency_key,request_fingerprint,payload_json,
                   state,attempt_count,next_attempt_at,last_error_code,created_at,updated_at,completed_at
               ) VALUES(?,?,?,?,?,'pending',0,?,'',?,?,'')""",
            (
                operation_id,
                event_type,
                idempotency_key,
                fingerprint,
                canonical_payload(payload),
                stamp,
                stamp,
                stamp,
            ),
        )
        operation = self.get_operation(operation_id, connection=connection)
        assert operation is not None
        return operation

    @staticmethod
    def _supersede_other_active(
        connection,
        event_type: EventType,
        keep_operation_id: str,
        stamp: str,
    ) -> None:
        connection.execute(
            """DELETE FROM registration_outbox
                WHERE operation_id<>? AND state IN ('pending','retry','action_required')
                  AND (?='register' OR event_type='heartbeat')""",
            (keep_operation_id, event_type),
        )
        connection.execute(
            """UPDATE registration_outbox
               SET state='superseded',last_error_code='',updated_at=?,completed_at=?
               WHERE operation_id<>? AND state='in_flight'
                 AND (?='register' OR event_type='heartbeat')""",
            (stamp, stamp, keep_operation_id, event_type),
        )

    @staticmethod
    def _prune_completed(connection, operation: OutboxOperation) -> None:
        """Bound local serial-bearing payload retention to the current successful lifecycle."""

        connection.execute(
            """DELETE FROM registration_outbox
               WHERE operation_id<>? AND state IN ('succeeded','superseded')
                 AND (event_type=? OR ?='register')""",
            (operation.operation_id, operation.event_type, operation.event_type),
        )

    @staticmethod
    def _record_attempt(
        connection,
        operation: OutboxOperation,
        *,
        attempted_at: str,
        outcome: str,
        http_status: int | None,
        error_code: str,
        retryable: bool,
        retry_after_seconds: int | None,
        duration_ms: int,
    ) -> None:
        connection.execute(
            """INSERT INTO registration_attempt_history(
                   operation_id,attempted_at,outcome,http_status,error_code,retryable,
                   retry_after_seconds,duration_ms
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                operation.operation_id,
                attempted_at,
                outcome,
                http_status,
                error_code,
                int(retryable),
                retry_after_seconds,
                max(0, int(duration_ms)),
            ),
        )
        connection.execute(
            """DELETE FROM registration_attempt_history
               WHERE operation_id=? AND id NOT IN (
                   SELECT id FROM registration_attempt_history
                   WHERE operation_id=? ORDER BY id DESC LIMIT 50
               )""",
            (operation.operation_id, operation.operation_id),
        )

    @staticmethod
    def _operation_from_row(row) -> OutboxOperation:
        return OutboxOperation(
            operation_id=str(row[0]),
            event_type=str(row[1]),  # type: ignore[arg-type]
            idempotency_key=str(row[2]),
            request_fingerprint=str(row[3]),
            payload=json.loads(str(row[4])),
            state=str(row[5]),  # type: ignore[arg-type]
            attempt_count=int(row[6]),
            next_attempt_at=str(row[7]),
            last_error_code=str(row[8]),
            created_at=str(row[9]),
            updated_at=str(row[10]),
            completed_at=str(row[11]),
        )
