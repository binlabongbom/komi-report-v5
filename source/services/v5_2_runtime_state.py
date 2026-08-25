"""Durable, redacted state for the Desktop V5.2 lifecycle coordinator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from database import _open

V52Mode = Literal["online", "offline"]


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds")


class V52RuntimeStateRepository:
    """Stores no token, private key, credential, or raw error.

    A signed Offline License request is public material and may be retained for
    strict request/license binding; it is never exposed through ``snapshot``.
    """

    def configure(
        self,
        mode: V52Mode,
        company_name: str,
        installation_id: str,
        first_started_at: str,
        notice_version: str,
        notice_accepted_at: str,
        *,
        now: datetime | None = None,
    ) -> None:
        self._mode(mode)
        company = " ".join(company_name.split())
        installation = installation_id.strip()
        if not company or not installation or not first_started_at.strip():
            raise ValueError("V5.2 runtime configuration is incomplete")
        stamp = _iso(now)
        with _open() as connection:
            connection.execute(
                """INSERT INTO v52_runtime_state(
                       singleton_id,mode,company_name,installation_id,first_started_at,
                       notice_version,notice_accepted_at,status,updated_at
                   ) VALUES(1,?,?,?,?,?,?,?,?)
                   ON CONFLICT(singleton_id) DO UPDATE SET
                       mode=excluded.mode,company_name=excluded.company_name,
                       installation_id=excluded.installation_id,
                       first_started_at=excluded.first_started_at,
                       notice_version=excluded.notice_version,
                       notice_accepted_at=excluded.notice_accepted_at,
                       status=CASE
                           WHEN excluded.mode='offline'
                                AND v52_runtime_state.installation_id=excluded.installation_id
                                AND v52_runtime_state.offline_license_id<>''
                               THEN 'offline_license'
                           WHEN excluded.mode='offline' THEN 'offline_request_required'
                           WHEN v52_runtime_state.installation_id=excluded.installation_id
                                AND v52_runtime_state.status='registered' THEN 'registered'
                           ELSE 'waiting_for_internet'
                       END,
                       next_status_at=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.next_status_at ELSE '' END,
                       next_meter_at=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.next_meter_at ELSE '' END,
                       offline_request_json=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.offline_request_json ELSE '' END,
                       offline_license_id=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.offline_license_id ELSE '' END,
                       offline_license_expires_at=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.offline_license_expires_at ELSE '' END,
                       offline_license_kid=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.offline_license_kid ELSE '' END,
                       offline_bound_devices_json=CASE WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.offline_bound_devices_json ELSE '[]' END,
                       updated_at=excluded.updated_at""",
                (
                    mode,
                    company,
                    installation,
                    first_started_at.strip(),
                    notice_version.strip(),
                    notice_accepted_at.strip(),
                    "offline_request_required" if mode == "offline" else "waiting_for_internet",
                    stamp,
                ),
            )

    def set_mode(self, mode: V52Mode, *, now: datetime | None = None) -> None:
        self._mode(mode)
        status = "offline_request_required" if mode == "offline" else "waiting_for_internet"
        with _open() as connection:
            row = connection.execute(
                "SELECT offline_license_id FROM v52_runtime_state WHERE singleton_id=1"
            ).fetchone()
            if row is None:
                raise ValueError("V5.2 runtime is not configured")
            if mode == "offline" and row[0]:
                status = "offline_license"
            connection.execute(
                """UPDATE v52_runtime_state
                   SET mode=?,status=?,last_error_code='',updated_at=? WHERE singleton_id=1""",
                (mode, status, _iso(now)),
            )

    def accept_notice(
        self, version: str, accepted_at: str, *, now: datetime | None = None
    ) -> None:
        if not version.strip() or not accepted_at.strip():
            raise ValueError("Registration Data Notice acceptance is incomplete")
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_runtime_state SET notice_version=?,notice_accepted_at=?,updated_at=?
                   WHERE singleton_id=1""",
                (version.strip(), accepted_at.strip(), _iso(now)),
            )
            if changed.rowcount != 1:
                raise ValueError("V5.2 runtime is not configured")

    def internal(self) -> dict[str, object] | None:
        with _open(commit=False) as connection:
            row = connection.execute(
                """SELECT mode,company_name,installation_id,first_started_at,notice_version,
                          notice_accepted_at,status,last_sent_at,next_status_at,next_meter_at,
                          last_error_code,offline_request_json,offline_license_id,
                          offline_license_expires_at,offline_license_kid,
                          offline_bound_devices_json
                   FROM v52_runtime_state WHERE singleton_id=1"""
            ).fetchone()
        if row is None:
            return None
        keys = (
            "mode",
            "company_name",
            "installation_id",
            "first_started_at",
            "notice_version",
            "notice_accepted_at",
            "status",
            "last_sent_at",
            "next_status_at",
            "next_meter_at",
            "last_error_code",
            "offline_request_json",
            "offline_license_id",
            "offline_license_expires_at",
            "offline_license_kid",
            "offline_bound_devices_json",
        )
        return dict(zip(keys, row, strict=True))

    def snapshot(self) -> dict[str, object]:
        state = self.internal()
        if state is None:
            return {
                "mode": "online",
                "status": "not_configured",
                "last_sent_at": "",
                "next_attempt_at": "",
                "last_error_code": "",
                "support_code": "",
                "notice_accepted": False,
                "offline_license": None,
            }
        next_values = [
            str(value)
            for value in (state["next_status_at"], state["next_meter_at"])
            if value
        ]
        devices = self._json_list(str(state["offline_bound_devices_json"] or "[]"))
        license_metadata = None
        if state["offline_license_id"]:
            license_metadata = {
                "expires_at": state["offline_license_expires_at"],
                "bound_devices": devices,
            }
        support_code = self._curated_support_code(str(state["last_error_code"] or ""))
        return {
            "mode": state["mode"],
            "status": state["status"],
            "last_sent_at": state["last_sent_at"],
            "next_attempt_at": min(next_values) if next_values else "",
            "last_error_code": support_code,
            "support_code": support_code,
            "notice_accepted": bool(state["notice_version"] and state["notice_accepted_at"]),
            "offline_license": license_metadata,
        }

    def save_offline_request(
        self, payload: Mapping[str, object], *, now: datetime | None = None
    ) -> None:
        with _open() as connection:
            connection.execute(
                """UPDATE v52_runtime_state SET offline_request_json=?,status='offline_request_ready',
                       last_error_code='',updated_at=? WHERE singleton_id=1""",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), _iso(now)),
            )

    def offline_request(self) -> dict[str, object] | None:
        state = self.internal()
        raw = str(state["offline_request_json"] or "") if state else ""
        if not raw:
            return None
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("stored Offline License request is invalid")
        return value

    def save_offline_license(
        self,
        *,
        license_id: str,
        expires_at: str,
        kid: str,
        bound_devices: list[Mapping[str, object]],
        now: datetime | None = None,
    ) -> None:
        with _open() as connection:
            connection.execute(
                """UPDATE v52_runtime_state SET mode='offline',status='offline_license',
                       offline_license_id=?,offline_license_expires_at=?,offline_license_kid=?,
                       offline_bound_devices_json=?,last_error_code='',updated_at=?
                   WHERE singleton_id=1""",
                (
                    license_id,
                    expires_at,
                    kid,
                    json.dumps(bound_devices, ensure_ascii=False, sort_keys=True),
                    _iso(now),
                ),
            )

    def mark_status(
        self,
        status: str,
        *,
        error_code: str = "",
        last_sent_at: str | None = None,
        now: datetime | None = None,
    ) -> None:
        values: list[object] = [status.strip(), error_code.strip()]
        assignment = "status=?,last_error_code=?"
        if last_sent_at is not None:
            assignment += ",last_sent_at=?"
            values.append(last_sent_at)
        values.extend((_iso(now), 1))
        with _open() as connection:
            connection.execute(
                f"UPDATE v52_runtime_state SET {assignment},updated_at=? WHERE singleton_id=?",
                values,
            )

    def set_schedule(
        self,
        event_type: Literal["status", "meter"],
        when: str,
        *,
        now: datetime | None = None,
    ) -> None:
        column = "next_status_at" if event_type == "status" else "next_meter_at"
        with _open() as connection:
            connection.execute(
                f"UPDATE v52_runtime_state SET {column}=?,updated_at=? WHERE singleton_id=1",
                (when, _iso(now)),
            )

    @staticmethod
    def _mode(mode: str) -> None:
        if mode not in {"online", "offline"}:
            raise ValueError("V5.2 mode must be online or offline")

    @staticmethod
    def _json_list(raw: str) -> list[object]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    @staticmethod
    def _curated_support_code(value: str) -> str:
        allowed = {
            "",
            "client_not_configured",
            "contract_invalid",
            "http_error",
            "installation_token_unavailable",
            "network_unavailable",
            "notice_required",
            "offline",
            "request_fingerprint_mismatch",
            "retryable_error",
            "vault_unavailable",
            "validation_error",
        }
        return value if value in allowed else "needs_review"
