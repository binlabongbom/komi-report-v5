"""Local-first Qt lifecycle coordinator for V5.2 Registration and Meter telemetry."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from komi_snmp_profiler.credential_store import CredentialStoreError
from komi_version import APP_VERSION
from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.device_config import DeviceConfigRepository
from services.installation_identity import (
    InstallationIdentity,
    load_or_create_installation_identity,
)
from services.offline_license import (
    VerifiedOfflineLicense,
    create_offline_request,
    import_offline_license,
    write_offline_request,
)
from services.registration_data_notice import DRAFT_NOTICE_VERSION
from services.registration_envelope import runtime_platform
from services.registration_vault import (
    RegistrationSecretStore,
    installation_token_reference,
    platform_registration_secret_store,
    registration_state_lock,
)
from services.v5_2_client import V52ContractClient
from services.v5_2_contract import (
    TelemetryPolicy,
    build_meter_payload,
    build_registration_payload,
    build_status_payload,
)
from services.v5_2_outbox import V52OutboxOperation, V52OutboxRepository
from services.v5_2_runtime_state import V52Mode, V52RuntimeStateRepository


class V52DeviceRepository(Protocol):
    def list(self, *, enabled_only: bool = False) -> list[object]: ...


class OfflineLicenseConfigurationError(ValueError):
    """Raised when Host verification material has not been supplied."""


class _LazyPlatformVault:
    """Delay OS-vault discovery so read-only Settings can always render safely."""

    def __init__(self) -> None:
        self._store: RegistrationSecretStore | None = None

    def _get(self) -> RegistrationSecretStore:
        if self._store is None:
            self._store = platform_registration_secret_store()
        return self._store

    def save(self, reference: str, secret: str) -> None:
        self._get().save(reference, secret)

    def load(self, reference: str) -> str | None:
        return self._get().load(reference)

    def delete(self, reference: str) -> None:
        self._get().delete(reference)


def _iso(value: datetime) -> str:
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


class V52RuntimeProcessor:
    """Synchronous business core; all network ability is explicitly injected."""

    def __init__(
        self,
        *,
        client: V52ContractClient | None,
        state_repository: V52RuntimeStateRepository,
        outbox: V52OutboxRepository,
        vault: RegistrationSecretStore,
        device_repository: V52DeviceRepository,
        clock: Callable[[], datetime],
        random_unit: Callable[[], float],
        adapter: DraftV1SigningAdapter,
        policy: TelemetryPolicy | None = None,
    ) -> None:
        self.client = client
        self.state = state_repository
        self.outbox = outbox
        self.vault = vault
        self.devices = device_repository
        self.clock = clock
        self.random_unit = random_unit
        self.adapter = adapter
        self.policy = policy or TelemetryPolicy()

    def recover_after_restart(self) -> int:
        state = self.state.internal()
        if state is None or state["mode"] != "online":
            return self.outbox.cancel_unsent(now=self.clock()) if state else 0
        return self.outbox.recover_in_flight(now=self.clock())

    def prepare_due(self, *, force_recovery: bool = False) -> int:
        state = self.state.internal()
        if state is None:
            return 0
        now = self.clock()
        if state["mode"] != "online":
            return self.outbox.cancel_unsent(now=now)
        if not state["notice_version"] or not state["notice_accepted_at"]:
            self.state.mark_status("needs_review", error_code="notice_required", now=now)
            return 0
        identity = self._identity(state)
        token = self._token(state)
        if not token:
            if self.outbox.active_count("register") == 0:
                self.outbox.coalesce(
                    "register",
                    build_registration_payload(
                        identity=identity,
                        company_name=str(state["company_name"]),
                        first_started_at=str(state["first_started_at"]),
                        app_version=APP_VERSION,
                        devices=self._registration_devices(),
                        platform_name=runtime_platform()[0],
                        architecture=runtime_platform()[1],
                        created_at=_iso(now),
                        adapter=self.adapter,
                    ),
                    now=now,
                )
            self.state.mark_status("waiting_for_internet", now=now)
            return 1

        queued = 0
        for event_type in ("status", "meter"):
            due = _parse(state[f"next_{event_type}_at"])
            recovery_allowed = force_recovery and self.outbox.recovery_send_allowed(
                event_type, now=now
            )
            if force_recovery and not recovery_allowed and (due is None or due > now):
                continue
            if not recovery_allowed and due is not None and due > now:
                continue
            if self.outbox.active_count(event_type) > 0:
                if recovery_allowed:
                    self.outbox.make_due(event_type, now=now)
                continue
            if event_type == "status":
                payload = build_status_payload(
                    installation_id=str(state["installation_id"]),
                    app_version=APP_VERSION,
                    platform_name=runtime_platform()[0],
                    architecture=runtime_platform()[1],
                    occurred_at=_iso(now),
                )
            else:
                observations = self._meter_observations(now)
                if not observations:
                    self._schedule(event_type, self.policy.meter_interval_seconds, now)
                    continue
                payload = build_meter_payload(
                    installation_id=str(state["installation_id"]),
                    observations=observations,
                    sent_at=_iso(now),
                )
            self.outbox.coalesce(event_type, payload, now=now)
            queued += 1
        return queued

    def run_once(self, *, force_recovery: bool = False) -> bool:
        try:
            queued = self.prepare_due(force_recovery=force_recovery)
        except CredentialStoreError:
            self.state.mark_status(
                "needs_review", error_code="vault_unavailable", now=self.clock()
            )
            return False
        state = self.state.internal()
        if state is None or state["mode"] != "online":
            return False
        if self.client is None:
            if queued:
                self.state.mark_status(
                    "waiting_for_internet", error_code="client_not_configured", now=self.clock()
                )
            return False
        operation = self.outbox.claim_due(now=self.clock())
        if operation is None:
            return False
        with registration_state_lock:
            current = self.state.internal()
            if current is None or current["mode"] != "online":
                self.outbox.cancel_unsent(now=self.clock())
                return False
            try:
                self._send(operation, current)
            except CredentialStoreError:
                now = self.clock()
                self.outbox.complete_retry(
                    operation,
                    error_code="vault_unavailable",
                    retry_after_seconds=None,
                    random_unit=self.random_unit(),
                    now=now,
                )
                self.state.mark_status(
                    "needs_review", error_code="vault_unavailable", now=now
                )
        return True

    def _send(self, operation: V52OutboxOperation, state: Mapping[str, object]) -> None:
        now = self.clock()
        token = None if operation.event_type == "register" else self._token(state)
        result = self.client.send(operation, installation_token=token)
        if result.success:
            if operation.event_type == "register":
                self.vault.save(
                    installation_token_reference(str(state["installation_id"])),
                    result.installation_token,
                )
                self._schedule("status", 0, now)
                self._schedule("meter", 0, now)
            elif operation.event_type == "status":
                if result.installation_token:
                    self.vault.save(
                        installation_token_reference(str(state["installation_id"])),
                        result.installation_token,
                    )
                self._schedule("status", result.next_status_after_seconds, now)
            else:
                self._schedule("meter", result.next_meter_after_seconds, now)
            self.outbox.complete_success(operation, observed_at=now)
            self.state.mark_status("registered", last_sent_at=_iso(now), now=now)
            return
        if result.retryable:
            error_code = self._curated_error(result.error_code, retryable=True)
            self.outbox.complete_retry(
                operation,
                error_code=error_code,
                retry_after_seconds=result.retry_after_seconds,
                random_unit=self.random_unit(),
                now=now,
            )
            self.state.mark_status("retrying", error_code=error_code, now=now)
        else:
            error_code = self._curated_error(result.error_code, retryable=False)
            self.outbox.complete_terminal(operation, error_code=error_code, now=now)
            self.state.mark_status("needs_review", error_code=error_code, now=now)

    def _identity(self, state: Mapping[str, object]) -> InstallationIdentity:
        return load_or_create_installation_identity(self.vault, str(state["installation_id"]))

    def _token(self, state: Mapping[str, object]) -> str | None:
        return self.vault.load(installation_token_reference(str(state["installation_id"])))

    def _registration_devices(self) -> list[dict[str, object]]:
        return [
            {
                "serial_number": str(getattr(device, "serial", "")).strip(),
                "model": str(getattr(device, "model", "") or "Unknown").strip(),
                "selected": True,
                "device_slot": int(device.slot) + 1,
            }
            for device in self.devices.list(enabled_only=True)[:3]
            if str(getattr(device, "serial", "")).strip()
        ]

    def _meter_observations(self, now: datetime) -> list[dict[str, object]]:
        observations: list[dict[str, object]] = []
        for device in self.devices.list(enabled_only=True)[:3]:
            serial = str(getattr(device, "serial", "")).strip()
            if not serial:
                continue
            total = getattr(device, "last_total", None)
            observed_at = (
                _parse(getattr(device, "last_success_at", None))
                or _parse(getattr(device, "last_checked_at", None))
                or now
            )
            observations.append(
                {
                    "serial_number": serial,
                    "model": str(getattr(device, "model", "") or "Unknown").strip(),
                    "device_slot": int(device.slot) + 1,
                    "total_meter": int(total) if type(total) is int and total >= 0 else None,
                    "meter_observed_at": _iso(observed_at),
                    "meter_status": "ok" if type(total) is int and total >= 0 else "unavailable",
                }
            )
        return observations

    def _schedule(self, event_type: str, seconds: int, now: datetime) -> None:
        delay = 0 if seconds <= 0 else self.policy.with_jitter(
            self.policy.clamp_server_interval(seconds), random_unit=self.random_unit()
        )
        self.state.set_schedule(event_type, _iso(now + timedelta(seconds=delay)), now=now)  # type: ignore[arg-type]

    @staticmethod
    def _curated_error(value: str, *, retryable: bool) -> str:
        allowed = {
            "contract_invalid",
            "http_error",
            "installation_token_unavailable",
            "offline",
            "request_fingerprint_mismatch",
            "validation_error",
        }
        candidate = value.strip().lower()
        if candidate in allowed:
            return candidate
        return "http_error" if retryable else "contract_invalid"


class V52RuntimeCoordinator(QObject):
    """Qt wrapper; Offline mode and a missing client are hard no-send gates."""

    status_changed = pyqtSignal(str)
    _work_finished = pyqtSignal()

    def __init__(
        self,
        client: V52ContractClient | None = None,
        *,
        state_repository: V52RuntimeStateRepository | None = None,
        outbox: V52OutboxRepository | None = None,
        vault: RegistrationSecretStore | None = None,
        device_repository: V52DeviceRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        random_unit: Callable[[], float] | None = None,
        adapter: DraftV1SigningAdapter | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.state_repository = state_repository or V52RuntimeStateRepository()
        self.outbox = outbox or V52OutboxRepository()
        self.vault = vault or _LazyPlatformVault()
        self.device_repository = device_repository or DeviceConfigRepository()
        self.adapter = adapter or DraftV1SigningAdapter()
        self.processor = V52RuntimeProcessor(
            client=client,
            state_repository=self.state_repository,
            outbox=self.outbox,
            vault=self.vault,
            device_repository=self.device_repository,
            clock=self.clock,
            random_unit=random_unit or random.SystemRandom().random,
            adapter=self.adapter,
        )
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.tick)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-v52-runtime")
        self._future: Future | None = None
        self._work_finished.connect(self._after_work)

    def start(self) -> None:
        self.processor.recover_after_restart()
        if self.snapshot().get("mode") != "online":
            self.timer.stop()
            self.status_changed.emit(str(self.snapshot()["status"]))
            return
        self.timer.start()
        QTimer.singleShot(250, lambda: self.tick(force_recovery=True))

    def stop(self) -> int:
        self.timer.stop()
        remaining = int(self._future is not None and not self._future.done())
        self.executor.shutdown(wait=False, cancel_futures=True)
        return remaining

    def tick(self, *, force_recovery: bool = False) -> None:
        if self._future is not None and not self._future.done():
            return
        self._future = self.executor.submit(
            self.processor.run_once, force_recovery=force_recovery
        )
        self._future.add_done_callback(lambda _future: self._work_finished.emit())

    def configuration_changed(self) -> None:
        if self.snapshot().get("mode") != "online":
            self.timer.stop()
            return
        if not self.timer.isActive():
            self.timer.start()
        self.retry_now()

    def meter_observed(self, _slot: int) -> None:
        """Record the lifecycle signal only; the 6-hour batch reads latest totals.

        DeviceConfigRepository is updated before this signal is emitted.  Do not
        enqueue or send here, otherwise active printers could exceed the normal
        request budget.
        """

    def network_recovered(self) -> int:
        state = self.state_repository.internal()
        if state is None or state["mode"] != "online":
            return 0
        now = self.clock()
        queued = 0
        for event_type in ("register", "status", "meter"):
            if self.outbox.recovery_send_allowed(event_type, now=now):
                queued += self.outbox.make_due(event_type, now=now)
        self.tick(force_recovery=True)
        return queued

    def retry_now(self) -> int:
        if self.snapshot().get("mode") != "online":
            return 0
        changed = self.outbox.make_due(now=self.clock())
        self.tick()
        return changed

    def set_mode(self, mode: V52Mode) -> None:
        with registration_state_lock:
            self.state_repository.set_mode(mode, now=self.clock())
            if mode == "offline":
                self.outbox.cancel_unsent(now=self.clock())
        if mode == "online":
            if not self.timer.isActive():
                self.timer.start()
            self.tick()
        else:
            self.timer.stop()
        self.status_changed.emit(str(self.snapshot()["status"]))

    def accept_notice(self, version: str, accepted_at: str) -> None:
        if version != DRAFT_NOTICE_VERSION:
            raise ValueError("Registration Data Notice version is not current")
        self.state_repository.accept_notice(version, accepted_at, now=self.clock())
        self.retry_now()

    def snapshot(self) -> dict[str, object]:
        return self.state_repository.snapshot()

    def create_offline_request(self, path: Path) -> Path:
        state = self._configured_state()
        identity = self.processor._identity(state)
        payload = create_offline_request(
            identity=identity,
            company_name=str(state["company_name"]),
            app_version=APP_VERSION,
            platform_name=runtime_platform()[0],
            architecture=runtime_platform()[1],
            selected_devices=[
                {
                    "serial_number": item["serial_number"],
                    "model": item["model"],
                    "device_slot": item["device_slot"],
                }
                for item in self.processor._registration_devices()
            ],
            request_id=str(uuid4()),
            created_at=_iso(self.clock()),
            adapter=self.adapter,
        )
        written = write_offline_request(path, payload)
        self.state_repository.save_offline_request(payload, now=self.clock())
        return written

    def import_offline_license(
        self,
        path: Path,
        host_public_keys: Mapping[str, str],
    ) -> VerifiedOfflineLicense:
        if not host_public_keys:
            raise OfflineLicenseConfigurationError(
                "Host Offline License verification key is not configured"
            )
        state = self._configured_state()
        request = self.state_repository.offline_request()
        if request is None:
            raise ValueError("Create an Offline License request before importing a license")
        verified = import_offline_license(
            path,
            identity=self.processor._identity(state),
            request_payload=request,
            host_public_keys=host_public_keys,
            now=self.clock(),
            adapter=self.adapter,
        )
        devices = request.get("selected_devices")
        with registration_state_lock:
            self.state_repository.save_offline_license(
                license_id=verified.license_id,
                expires_at=verified.expires_at,
                kid=verified.kid,
                bound_devices=list(devices) if isinstance(devices, list) else [],
                now=self.clock(),
            )
            self.outbox.cancel_unsent(now=self.clock())
        self.status_changed.emit("offline_license")
        return verified

    def _configured_state(self) -> dict[str, object]:
        state = self.state_repository.internal()
        if state is None:
            raise ValueError("V5.2 runtime is not configured")
        return state

    def _after_work(self) -> None:
        future = self._future
        if future is not None:
            try:
                future.result()
            except Exception:
                self.state_repository.mark_status(
                    "needs_review", error_code="contract_invalid", now=self.clock()
                )
        self.status_changed.emit(str(self.snapshot()["status"]))
