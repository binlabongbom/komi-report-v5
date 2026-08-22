"""Independent registration scheduler with durable retry and vault ordering."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from komi_snmp_profiler.credential_store import CredentialStoreError
from services.registration_client import RegistrationClient, RegistrationClientResult
from services.registration_policy import RegistrationRuntimePolicy, load_registration_policy
from services.registration_repository import (
    OutboxOperation,
    RegistrationRepository,
    utc_now,
)
from services.registration_vault import (
    RegistrationSecretStore,
    installation_token_reference,
    platform_registration_secret_store,
    registration_state_lock,
)

log = logging.getLogger(__name__)


class RegistrationProcessor:
    def __init__(
        self,
        repository: RegistrationRepository | None = None,
        client: RegistrationClient | None = None,
        *,
        policy_loader: Callable[[], RegistrationRuntimePolicy | None] = load_registration_policy,
        vault_factory: Callable[[], RegistrationSecretStore] = platform_registration_secret_store,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        self.repository = repository or RegistrationRepository()
        self.client = client or RegistrationClient()
        self.policy_loader = policy_loader
        self.vault_factory = vault_factory
        self.jitter = jitter or (lambda upper: random.SystemRandom().uniform(0, upper))
        self._vault: RegistrationSecretStore | None = None

    def recover_after_restart(self, *, now: datetime | None = None) -> int:
        return self.repository.recover_in_flight(now=now)

    def run_once(self, *, now: datetime | None = None) -> bool:
        current = now or utc_now()
        self.repository.enqueue_heartbeat_if_due(now=current)
        operation = self.repository.claim_due(now=current)
        if operation is None:
            return False
        try:
            # Factory Reset must not return while an already-claimed request can
            # still create a remote side effect. The policy caps this wait at 60s.
            with registration_state_lock:
                self._run_claimed(operation, current)
        except Exception:
            retry_at = current + self._retry_delay(operation, None)
            self.repository.complete_failure(
                operation,
                error_code="worker_unexpected_error",
                retryable=True,
                next_attempt_at=retry_at,
                http_status=None,
                retry_after_seconds=None,
                duration_ms=0,
                now=current,
            )
            log.error(
                "registration worker recovered an unexpected failure",
                extra={"event": "registration_worker", "status": "retry"},
            )
        return True

    def _run_claimed(self, operation: OutboxOperation, current: datetime) -> None:
        policy = self._load_policy(operation, current)
        if policy is None:
            return
        profile = self.repository.profile()
        if profile is None:
            self._fail_local(operation, "registration_profile_missing", current)
            return
        blocker = policy.sending_blocker(
            accepted_notice_version=profile.notice_version,
            accepted_at=profile.notice_accepted_at,
        )
        if blocker:
            self._fail_local(operation, blocker, current)
            return
        try:
            vault = self._secret_store()
            bootstrap = (
                vault.load(policy.bootstrap_ref)
                if operation.event_type == "register" and policy.bootstrap_mode == "vault_header"
                else None
            )
            token = (
                vault.load(profile.token_ref)
                if operation.event_type == "heartbeat" and profile.token_ref
                else None
            )
        except CredentialStoreError:
            self._fail_local(operation, "vault_unavailable", current)
            return

        result = self.client.send(
            operation,
            policy,
            bootstrap_secret=bootstrap,
            installation_token=token,
        )
        response_time = current + timedelta(milliseconds=max(0, result.duration_ms))
        if result.success:
            self._complete_success(operation, result, profile.token_ref, response_time)
        else:
            self._complete_failure(operation, result, response_time)

    def _load_policy(
        self,
        operation: OutboxOperation,
        current: datetime,
    ) -> RegistrationRuntimePolicy | None:
        try:
            policy = self.policy_loader()
        except ValueError:
            self._fail_local(operation, "registration_policy_invalid", current)
            return None
        if policy is None:
            self._fail_local(operation, "registration_policy_unavailable", current)
            return None
        return policy

    def _secret_store(self) -> RegistrationSecretStore:
        if self._vault is None:
            self._vault = self.vault_factory()
        return self._vault

    def _complete_success(
        self,
        operation: OutboxOperation,
        result: RegistrationClientResult,
        existing_token_ref: str,
        current: datetime,
    ) -> None:
        with registration_state_lock:
            self._complete_success_locked(
                operation, result, existing_token_ref, current
            )

    def _complete_success_locked(
        self,
        operation: OutboxOperation,
        result: RegistrationClientResult,
        existing_token_ref: str,
        current: datetime,
    ) -> None:
        token_ref = existing_token_ref
        previous_secret: str | None = None
        wrote_secret = False
        try:
            if result.installation_token:
                token_ref = token_ref or installation_token_reference(
                    str(operation.payload["installation_id"])
                )
                vault = self._secret_store()
                previous_secret = vault.load(token_ref)
                vault.save(token_ref, result.installation_token)
                wrote_secret = True
            if operation.event_type == "register" and not token_ref:
                raise CredentialStoreError("Registration token reference is unavailable")
            accepted = self.repository.complete_success(
                operation,
                http_status=result.http_status or 200,
                duration_ms=result.duration_ms,
                token_ref=token_ref,
                registered_at=result.registered_at,
                last_heartbeat_at=result.last_seen_at,
                next_heartbeat_after_seconds=result.next_heartbeat_after_seconds,
                now=current,
            )
            if not accepted:
                self._rollback_vault_write(token_ref, previous_secret, wrote_secret)
                return
        except CredentialStoreError:
            self._rollback_vault_write(token_ref, previous_secret, wrote_secret)
            self._fail_local(operation, "vault_unavailable", current)
            return
        except Exception:
            self._rollback_vault_write(token_ref, previous_secret, wrote_secret)
            retry_at = current + self._retry_delay(operation, None)
            self.repository.complete_failure(
                operation,
                error_code="local_persistence_error",
                retryable=True,
                next_attempt_at=retry_at,
                http_status=result.http_status,
                retry_after_seconds=None,
                duration_ms=result.duration_ms,
                now=current,
            )
            return
        log.info(
            "registration operation succeeded",
            extra={
                "event": "registration_operation",
                "operation": operation.event_type,
                "status": "succeeded",
                "http_status": result.http_status,
                "duration_ms": result.duration_ms,
            },
        )

    def _rollback_vault_write(
        self,
        reference: str,
        previous_secret: str | None,
        wrote_secret: bool,
    ) -> None:
        if not wrote_secret or not reference:
            return
        try:
            vault = self._secret_store()
            if previous_secret is None:
                vault.delete(reference)
            else:
                vault.save(reference, previous_secret)
        except CredentialStoreError:
            log.error(
                "registration vault rollback failed",
                extra={"event": "registration_vault", "status": "rollback_failed"},
            )

    def _complete_failure(
        self,
        operation: OutboxOperation,
        result: RegistrationClientResult,
        current: datetime,
    ) -> None:
        delay = self._retry_delay(operation, result.retry_after_seconds)
        self.repository.complete_failure(
            operation,
            error_code=result.error_code,
            retryable=result.retryable,
            next_attempt_at=current + delay,
            http_status=result.http_status,
            retry_after_seconds=result.retry_after_seconds,
            duration_ms=result.duration_ms,
            now=current,
        )
        log.warning(
            "registration operation did not complete",
            extra={
                "event": "registration_operation",
                "operation": operation.event_type,
                "status": "retry" if result.retryable else "action_required",
                "error_code": result.error_code,
                "http_status": result.http_status,
                "duration_ms": result.duration_ms,
            },
        )

    def _fail_local(self, operation: OutboxOperation, error_code: str, current: datetime) -> None:
        self.repository.complete_failure(
            operation,
            error_code=error_code,
            retryable=False,
            next_attempt_at=current,
            http_status=None,
            retry_after_seconds=None,
            duration_ms=0,
            now=current,
        )
        log.warning(
            "registration operation blocked locally",
            extra={
                "event": "registration_operation",
                "operation": operation.event_type,
                "status": "action_required",
                "error_code": error_code,
            },
        )

    def _retry_delay(
        self,
        operation: OutboxOperation,
        retry_after_seconds: int | None,
    ) -> timedelta:
        exponent = min(operation.attempt_count, 10)
        base = min(21_600.0, 30.0 * (2**exponent))
        jittered = base + max(0.0, self.jitter(base * 0.25))
        if retry_after_seconds is not None:
            jittered = max(jittered, float(retry_after_seconds))
        return timedelta(seconds=jittered)


class RegistrationCoordinator(QObject):
    """Qt lifecycle wrapper; it never shares the printer polling executor."""

    status_changed = pyqtSignal(str)
    _work_finished = pyqtSignal()

    def __init__(
        self,
        processor: RegistrationProcessor | None = None,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.processor = processor or RegistrationProcessor()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-registration")
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.tick)
        self._future: Future | None = None
        self._work_finished.connect(self._after_work)

    def start(self) -> None:
        self.processor.recover_after_restart()
        self.timer.start()
        QTimer.singleShot(500, self.tick)

    def stop(self) -> int:
        self.timer.stop()
        remaining = int(self._future is not None and not self._future.done())
        if self._future is not None:
            self._future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        return remaining

    def tick(self) -> None:
        if self._future is not None and not self._future.done():
            return
        self._future = self.executor.submit(self.processor.run_once)
        self._future.add_done_callback(lambda _future: self._work_finished.emit())

    def retry_now(self) -> int:
        retried = self.processor.repository.manual_retry()
        self.tick()
        return retried

    def _after_work(self) -> None:
        future = self._future
        if future is not None:
            try:
                future.result()
            except Exception:
                log.error(
                    "registration worker failed",
                    extra={"event": "registration_worker", "status": "failed"},
                )
                self.processor.recover_after_restart()
        self.status_changed.emit(self.processor.repository.summary().status)
