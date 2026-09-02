"""Durable coalescing Status/Meter outbox for the V5.2 Desktop contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from database import _open
from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.v5_2_contract import (
    validate_meter_payload,
    validate_registration_payload,
    validate_status_payload,
)

EventType = Literal["register", "status", "meter"]
OutboxState = Literal["pending", "in_flight", "retry", "terminal", "succeeded"]


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(payload: Mapping[str, object]) -> str:
    return DraftV1SigningAdapter().canonical_bytes(payload).decode("utf-8")


def request_fingerprint(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def compute_retry_delay_seconds(
    attempt_count: int,
    *,
    retry_after_seconds: int | None,
    random_unit: float,
) -> int:
    base = (
        min(21_600, max(0, retry_after_seconds))
        if retry_after_seconds is not None
        else (900, 3_600, 21_600)[min(max(0, attempt_count), 2)]
    )
    unit = min(1.0, max(0.0, float(random_unit)))
    jittered = int(round(base * (0.9 + (unit * 0.2))))
    return min(21_600, max(1, jittered))


@dataclass(frozen=True)
class V52OutboxOperation:
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


class V52OutboxRepository:
    def coalesce(
        self,
        event_type: EventType,
        payload: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> V52OutboxOperation:
        self._validate(event_type, payload)
        stamp = _iso(now or _now())
        fingerprint = request_fingerprint(payload)
        with _open() as connection:
            connection.execute("BEGIN IMMEDIATE")
            same = connection.execute(
                """SELECT * FROM v52_telemetry_outbox
                   WHERE event_type=? AND state IN ('pending','retry')
                     AND request_fingerprint=? LIMIT 1""",
                (event_type, fingerprint),
            ).fetchone()
            if same:
                return self._from_row(same)
            connection.execute(
                """DELETE FROM v52_telemetry_outbox
                   WHERE event_type=? AND state IN ('pending','retry')""",
                (event_type,),
            )
            operation_id = str(uuid4())
            connection.execute(
                """INSERT INTO v52_telemetry_outbox(
                       operation_id,event_type,idempotency_key,request_fingerprint,payload_json,
                       state,attempt_count,next_attempt_at,last_error_code,created_at,updated_at,completed_at
                   ) VALUES(?,?,?,?,?,'pending',0,?,'',?,?,'')""",
                (
                    operation_id,
                    event_type,
                    str(uuid4()),
                    fingerprint,
                    _canonical(payload),
                    stamp,
                    stamp,
                    stamp,
                ),
            )
            operation = self.get(operation_id, connection=connection)
            assert operation is not None
            return operation

    def claim_due(self, *, now: datetime | None = None) -> V52OutboxOperation | None:
        stamp = _iso(now or _now())
        with _open() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM v52_telemetry_outbox
                   WHERE state IN ('pending','retry') AND next_attempt_at<=?
                   ORDER BY CASE event_type
                                WHEN 'register' THEN 0
                                WHEN 'status' THEN 1
                                ELSE 2
                            END,
                            next_attempt_at,created_at LIMIT 1""",
                (stamp,),
            ).fetchone()
            if not row:
                return None
            operation_id = str(row[0])
            changed = connection.execute(
                """UPDATE v52_telemetry_outbox SET state='in_flight',updated_at=?
                   WHERE operation_id=? AND state IN ('pending','retry')""",
                (stamp, operation_id),
            )
            if changed.rowcount != 1:
                return None
            return self.get(operation_id, connection=connection)

    def recover_in_flight(self, *, now: datetime | None = None) -> int:
        stamp = _iso(now or _now())
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_telemetry_outbox
                   SET state='retry',next_attempt_at=?,last_error_code='restart_recovery',updated_at=?
                   WHERE state='in_flight'""",
                (stamp, stamp),
            )
            return int(changed.rowcount)

    def complete_success(
        self,
        operation: V52OutboxOperation,
        *,
        observed_at: datetime | None = None,
    ) -> bool:
        stamp = _iso(observed_at or _now())
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_telemetry_outbox
                   SET state='succeeded',attempt_count=attempt_count+1,last_error_code='',
                       updated_at=?,completed_at=?
                   WHERE operation_id=? AND state='in_flight'""",
                (stamp, stamp, operation.operation_id),
            )
            if changed.rowcount != 1:
                return False
            connection.execute(
                """INSERT INTO v52_telemetry_success(event_type,last_successful_at)
                   VALUES(?,?) ON CONFLICT(event_type) DO UPDATE SET
                       last_successful_at=excluded.last_successful_at""",
                (operation.event_type, stamp),
            )
            connection.execute(
                """DELETE FROM v52_telemetry_outbox
                   WHERE event_type=? AND state IN ('succeeded','terminal')
                     AND operation_id<>?""",
                (operation.event_type, operation.operation_id),
            )
            return True

    def complete_retry(
        self,
        operation: V52OutboxOperation,
        *,
        error_code: str,
        retry_after_seconds: int | None,
        random_unit: float,
        now: datetime | None = None,
    ) -> bool:
        current = now or _now()
        delay = compute_retry_delay_seconds(
            operation.attempt_count,
            retry_after_seconds=retry_after_seconds,
            random_unit=random_unit,
        )
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_telemetry_outbox
                   SET state='retry',attempt_count=attempt_count+1,next_attempt_at=?,
                       last_error_code=?,updated_at=?
                   WHERE operation_id=? AND state='in_flight'""",
                (
                    _iso(current + timedelta(seconds=delay)),
                    error_code.strip() or "retryable_error",
                    _iso(current),
                    operation.operation_id,
                ),
            )
            return changed.rowcount == 1

    def complete_terminal(
        self,
        operation: V52OutboxOperation,
        *,
        error_code: str,
        now: datetime | None = None,
    ) -> bool:
        stamp = _iso(now or _now())
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_telemetry_outbox
                   SET state='terminal',attempt_count=attempt_count+1,last_error_code=?,
                       updated_at=?,completed_at=?
                   WHERE operation_id=? AND state='in_flight'""",
                (error_code.strip() or "terminal_error", stamp, stamp, operation.operation_id),
            )
            return changed.rowcount == 1

    def recovery_send_allowed(
        self, event_type: EventType, *, now: datetime | None = None
    ) -> bool:
        current = now or _now()
        with _open(commit=False) as connection:
            row = connection.execute(
                "SELECT last_successful_at FROM v52_telemetry_success WHERE event_type=?",
                (event_type,),
            ).fetchone()
        if not row:
            return True
        observed = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        return current.astimezone(UTC) - observed.astimezone(UTC) >= timedelta(minutes=15)

    def pending_count(self, event_type: EventType) -> int:
        with _open(commit=False) as connection:
            row = connection.execute(
                """SELECT COUNT(*) FROM v52_telemetry_outbox
                   WHERE event_type=? AND state IN ('pending','retry')""",
                (event_type,),
            ).fetchone()
        return int(row[0]) if row else 0

    def active_count(self, event_type: EventType) -> int:
        with _open(commit=False) as connection:
            row = connection.execute(
                """SELECT COUNT(*) FROM v52_telemetry_outbox
                   WHERE event_type=? AND state IN ('pending','retry','in_flight')""",
                (event_type,),
            ).fetchone()
        return int(row[0]) if row else 0

    def make_due(
        self,
        event_type: EventType | None = None,
        *,
        now: datetime | None = None,
    ) -> int:
        stamp = _iso(now or _now())
        where = "state IN ('pending','retry')"
        values: list[object] = [stamp, stamp]
        if event_type is not None:
            where += " AND event_type=?"
            values.append(event_type)
        with _open() as connection:
            changed = connection.execute(
                f"UPDATE v52_telemetry_outbox SET next_attempt_at=?,updated_at=? WHERE {where}",
                values,
            )
            return int(changed.rowcount)

    def cancel_unsent(
        self,
        *,
        reason: str = "offline_mode",
        event_types: tuple[EventType, ...] | None = None,
        now: datetime | None = None,
    ) -> int:
        """Terminally close unsent telemetry, optionally for selected event types."""

        stamp = _iso(now or _now())
        clause = "state IN ('pending','retry','in_flight')"
        values: list[object] = [reason.strip() or "offline_mode", stamp, stamp]
        if event_types:
            placeholders = ",".join("?" for _event_type in event_types)
            clause += f" AND event_type IN ({placeholders})"
            values.extend(event_types)
        with _open() as connection:
            changed = connection.execute(
                f"""UPDATE v52_telemetry_outbox
                    SET state='terminal',last_error_code=?,updated_at=?,completed_at=?
                    WHERE {clause}""",
                values,
            )
            return int(changed.rowcount)

    def get(
        self, operation_id: str, *, connection=None
    ) -> V52OutboxOperation | None:
        if connection is not None:
            row = connection.execute(
                "SELECT * FROM v52_telemetry_outbox WHERE operation_id=?", (operation_id,)
            ).fetchone()
        else:
            with _open(commit=False) as opened:
                row = opened.execute(
                    "SELECT * FROM v52_telemetry_outbox WHERE operation_id=?", (operation_id,)
                ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _validate(event_type: EventType, payload: Mapping[str, object]) -> None:
        if event_type == "register":
            validate_registration_payload(payload)
        elif event_type == "status":
            validate_status_payload(payload)
        elif event_type == "meter":
            validate_meter_payload(payload)
        else:
            raise ValueError("unsupported V5.2 outbox event_type")

    @staticmethod
    def _from_row(row) -> V52OutboxOperation:
        payload = json.loads(str(row[4]))
        if not isinstance(payload, dict):
            raise ValueError("V5.2 outbox payload is invalid")
        return V52OutboxOperation(
            operation_id=str(row[0]),
            event_type=str(row[1]),  # type: ignore[arg-type]
            idempotency_key=str(row[2]),
            request_fingerprint=str(row[3]),
            payload=payload,
            state=str(row[5]),  # type: ignore[arg-type]
            attempt_count=int(row[6]),
            next_attempt_at=str(row[7]),
            last_error_code=str(row[8]),
            created_at=str(row[9]),
            updated_at=str(row[10]),
            completed_at=str(row[11]),
        )
