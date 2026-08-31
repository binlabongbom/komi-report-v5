"""Durable, redacted state for the Desktop V5.2 lifecycle coordinator."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Literal

from database import _open
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION
from services.registration_envelope import normalize_device_inventory

V52Mode = Literal["online", "offline"]


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _licensed_devices_match_inventory(state: Mapping[str, object]) -> bool:
    """Require the current selected printers to match the Host-signed binding."""

    try:
        inventory_raw = json.loads(str(state.get("registration_inventory_json") or "[]"))
        bound_raw = json.loads(str(state.get("offline_bound_devices_json") or "[]"))
    except json.JSONDecodeError:
        return False
    if not isinstance(inventory_raw, list) or not isinstance(bound_raw, list):
        return False
    try:
        inventory = normalize_device_inventory(inventory_raw)
    except ValueError:
        return False
    current = [
        {
            "serial_number": str(item["serial_number"]),
            "model": str(item["model"]),
            "device_slot": item["device_slot"],
        }
        for item in inventory["devices"]
        if bool(item["selected"])
    ]
    expected: list[dict[str, object]] = []
    for item in bound_raw:
        if not isinstance(item, Mapping) or set(item) != {
            "serial_number",
            "model",
            "device_slot",
        }:
            return False
        serial = item.get("serial_number")
        model = item.get("model")
        slot = item.get("device_slot")
        if (
            not isinstance(serial, str)
            or not serial.strip()
            or not isinstance(model, str)
            or not model.strip()
            or type(slot) is not int
            or not 1 <= slot <= 3
        ):
            return False
        expected.append(
            {
                "serial_number": serial.strip(),
                "model": model.strip(),
                "device_slot": slot,
            }
        )
    if not current or not expected:
        return False
    return sorted(current, key=lambda item: int(item["device_slot"])) == sorted(
        expected, key=lambda item: int(item["device_slot"])
    )


def _canonical_inventory_json(
    devices: Iterable[Mapping[str, object]],
) -> str:
    """Serialize one semantic inventory independent of discovery row order."""

    inventory = normalize_device_inventory(devices)
    ordered = sorted(
        inventory["devices"],
        key=lambda item: str(item["serial_number"]).casefold(),
    )
    return json.dumps(
        ordered,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stored_inventory_matches(
    raw: object,
    devices: Iterable[Mapping[str, object]],
) -> bool:
    """Treat corrupt durable state as changed so registration fails closed."""

    try:
        value = json.loads(str(raw or "[]"))
        if not isinstance(value, list):
            return False
        return _canonical_inventory_json(value) == _canonical_inventory_json(devices)
    except (json.JSONDecodeError, ValueError):
        return False


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
        registration_devices: Iterable[Mapping[str, object]] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._mode(mode)
        company = " ".join(company_name.split())
        installation = installation_id.strip()
        if not company or not installation or not first_started_at.strip():
            raise ValueError("V5.2 runtime configuration is incomplete")
        inventory = normalize_device_inventory(registration_devices or ())
        inventory_json = json.dumps(
            inventory["devices"], ensure_ascii=False, sort_keys=True
        )
        stamp = _iso(now)
        with _open() as connection:
            connection.execute(
                """INSERT INTO v52_runtime_state(
                       singleton_id,mode,company_name,installation_id,first_started_at,
                       notice_version,notice_accepted_at,status,registration_inventory_json,
                       updated_at
                   ) VALUES(1,?,?,?,?,?,?,?,?,?)
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
                       last_registered_inventory_json=CASE
                           WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.last_registered_inventory_json ELSE '[]' END,
                       last_registration_terminal_inventory_json=CASE
                           WHEN v52_runtime_state.installation_id=excluded.installation_id
                           THEN v52_runtime_state.last_registration_terminal_inventory_json
                           ELSE '[]' END,
                       registration_inventory_json=excluded.registration_inventory_json,
                       updated_at=excluded.updated_at""",
                (
                    mode,
                    company,
                    installation,
                    first_started_at.strip(),
                    notice_version.strip(),
                    notice_accepted_at.strip(),
                    "offline_request_required" if mode == "offline" else "waiting_for_internet",
                    inventory_json,
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
                          offline_bound_devices_json,registration_inventory_json,
                          last_registered_inventory_json,
                          last_registration_terminal_inventory_json
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
            "registration_inventory_json",
            "last_registered_inventory_json",
            "last_registration_terminal_inventory_json",
        )
        return dict(zip(keys, row, strict=True))

    def registration_devices(self) -> list[dict[str, object]]:
        state = self.internal()
        raw = str(state["registration_inventory_json"] or "[]") if state else "[]"
        value = self._json_list(raw)
        inventory = normalize_device_inventory(value)
        return list(inventory["devices"])

    def update_registration_devices(
        self,
        registration_devices: Iterable[Mapping[str, object]],
        *,
        now: datetime | None = None,
    ) -> None:
        """Refresh inventory without changing the registration lifecycle.

        Settings may edit a printer after an installation has received an
        Offline License.  Re-running ``configure`` for that edit would reset
        the lifecycle (and historically forced Online mode).  This narrow
        update deliberately preserves mode, status, notice, schedules, and
        Offline License binding while keeping the local inventory current.
        """

        inventory = normalize_device_inventory(registration_devices)
        inventory_json = json.dumps(
            inventory["devices"], ensure_ascii=False, sort_keys=True
        )
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_runtime_state
                   SET registration_inventory_json=?,updated_at=?
                   WHERE singleton_id=1""",
                (inventory_json, _iso(now)),
            )
            if changed.rowcount != 1:
                raise ValueError("V5.2 runtime is not configured")

    def registration_inventory_changed(
        self,
        registration_devices: Iterable[Mapping[str, object]],
    ) -> bool:
        state = self.internal()
        if state is None:
            return True
        return not _stored_inventory_matches(
            state["last_registered_inventory_json"], registration_devices
        )

    def registration_inventory_was_terminal(
        self,
        registration_devices: Iterable[Mapping[str, object]],
    ) -> bool:
        state = self.internal()
        if state is None:
            return False
        terminal_raw = state["last_registration_terminal_inventory_json"]
        if str(terminal_raw or "[]") == "[]" and not (
            state["status"] == "needs_review" and state["last_error_code"]
        ):
            # ``[]`` is also the migration/default value.  It only represents
            # an actual empty-inventory terminal result when the durable
            # lifecycle status confirms that a terminal response occurred.
            return False
        return _stored_inventory_matches(
            terminal_raw,
            registration_devices,
        )

    def mark_registration_succeeded(
        self,
        registration_devices: Iterable[Mapping[str, object]],
        *,
        now: datetime | None = None,
    ) -> None:
        baseline = _canonical_inventory_json(registration_devices)
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_runtime_state
                   SET last_registered_inventory_json=?,
                       last_registration_terminal_inventory_json='[]',
                       status='registered',last_error_code='',updated_at=?
                   WHERE singleton_id=1""",
                (baseline, _iso(now)),
            )
            if changed.rowcount != 1:
                raise ValueError("V5.2 runtime is not configured")

    def mark_registration_terminal(
        self,
        registration_devices: Iterable[Mapping[str, object]],
        *,
        error_code: str,
        now: datetime | None = None,
    ) -> None:
        terminal = _canonical_inventory_json(registration_devices)
        with _open() as connection:
            changed = connection.execute(
                """UPDATE v52_runtime_state
                   SET last_registration_terminal_inventory_json=?,
                       status='needs_review',last_error_code=?,updated_at=?
                   WHERE singleton_id=1""",
                (terminal, error_code.strip(), _iso(now)),
            )
            if changed.rowcount != 1:
                raise ValueError("V5.2 runtime is not configured")

    def usage_eligibility(
        self, *, now: datetime | None = None
    ) -> tuple[bool, str]:
        """Return the local lifecycle gate used before opening the workspace."""

        state = self.internal()
        if state is None:
            return False, "not_configured"
        if state["mode"] == "online":
            notice_time = _parse_timestamp(state["notice_accepted_at"])
            if (
                state["notice_version"] != REGISTRATION_NOTICE_VERSION
                or notice_time is None
            ):
                return False, "notice_required"
            # Delivery state is not the same thing as local entitlement.  Once
            # this exact inventory has registered successfully, a transient
            # Status/Meter outage must not send the user back through first
            # run.  Terminal Host responses remain ``needs_review`` and an
            # edited inventory no longer matches the durable success baseline,
            # so both still fail closed.
            if state["status"] not in {
                "registered",
                "retrying",
                "waiting_for_internet",
            }:
                return False, "registration_required"
            try:
                current_inventory = json.loads(
                    str(state["registration_inventory_json"] or "[]")
                )
                registered_inventory = json.loads(
                    str(state["last_registered_inventory_json"] or "[]")
                )
            except json.JSONDecodeError:
                return False, "registration_required"
            if (
                not isinstance(current_inventory, list)
                or not isinstance(registered_inventory, list)
                or not registered_inventory
                or not _stored_inventory_matches(
                    state["last_registered_inventory_json"], current_inventory
                )
            ):
                return False, "registration_required"
            return True, "registered"

        expires_at = _parse_timestamp(state["offline_license_expires_at"])
        if not state["offline_license_id"]:
            return False, "offline_license_required"
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if expires_at is None or current.astimezone(UTC) >= expires_at:
            return False, "offline_license_expired"
        if not _licensed_devices_match_inventory(state):
            return False, "offline_license_device_mismatch"
        return True, "offline_license"

    def snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
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
        effective_status = str(state["status"])
        effective_error = str(state["last_error_code"] or "")
        if state["mode"] == "offline" and state["offline_license_id"]:
            eligible, reason = self.usage_eligibility(now=now)
            if not eligible and reason in {
                "offline_license_expired",
                "offline_license_device_mismatch",
            }:
                effective_status = reason
                effective_error = reason
        support_code = self._curated_support_code(effective_error)
        return {
            "mode": state["mode"],
            "status": effective_status,
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
            "offline_license_expired",
            "offline_license_device_mismatch",
            "offline_license_required",
            "registration_conflict",
            "registration_required",
            "request_fingerprint_mismatch",
            "retryable_error",
            "vault_unavailable",
            "validation_error",
        }
        return value if value in allowed else "needs_review"
