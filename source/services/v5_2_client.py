"""Typed, redacted V5.2 Registration/Status/Meter client.

The transport is injectable so Desktop contract tests use a local stub. No
shared bootstrap or master credential exists in this client.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from services.build_edition import is_offline_edition
from services.registration_errors import RegistrationNetworkError, classify_network_error
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from services.host_tls import create_host_tls_context

from services.v5_2_contract import SCHEMA_VERSION, TelemetryPolicy
from services.v5_2_outbox import V52OutboxOperation, request_fingerprint

MAX_RESPONSE_BYTES = 1_048_576
Environment = Literal["local", "staging", "production"]


@dataclass(frozen=True)
class V52RuntimeConfig:
    base_url: str
    environment: Environment
    timeout_seconds: float = 15.0

    def endpoint(self, event_type: str) -> str:
        suffixes = {
            "register": "register",
            "status": "status",
            "meter": "meter-observations",
        }
        if event_type not in suffixes:
            raise ValueError("unsupported V5.2 endpoint")
        base = self.base_url.rstrip("/")
        if self.environment == "local":
            if not (base.startswith("http://127.0.0.1") or base.startswith("http://localhost")):
                raise ValueError("local V5.2 fixture must use loopback")
        elif not base.startswith("https://"):
            raise ValueError("staging/production V5.2 endpoint must use HTTPS")
        return f"{base}/api/v1/installations/{suffixes[event_type]}"


@dataclass(frozen=True)
class V52TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class V52Transport(Protocol):
    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> V52TransportResponse: ...


class V52NetworkError(RegistrationNetworkError):
    pass


class UrllibV52Transport:
    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
            return None

    def __init__(self) -> None:
        self._opener = build_opener(self._NoRedirect(), HTTPSHandler(context=create_host_tls_context()))

    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> V52TransportResponse:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with self._opener.open(request, timeout=timeout) as response:  # noqa: S310
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise V52NetworkError("response_too_large")
                return V52TransportResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=response_body,
                )
        except HTTPError as err:
            response_body = err.read(MAX_RESPONSE_BYTES + 1)
            return V52TransportResponse(
                status=int(err.code),
                headers=dict(err.headers.items()) if err.headers else {},
                body=response_body if len(response_body) <= MAX_RESPONSE_BYTES else b"",
            )
        except (OSError, TimeoutError, URLError) as err:
            raise V52NetworkError(classify_network_error(err)) from None


@dataclass(frozen=True)
class V52ClientResult:
    success: bool
    http_status: int | None
    error_code: str
    retryable: bool
    retry_after_seconds: int | None
    installation_token: str
    next_status_after_seconds: int
    next_meter_after_seconds: int


class V52ContractClient:
    def __init__(
        self,
        config: V52RuntimeConfig,
        *,
        transport: V52Transport | None = None,
        policy: TelemetryPolicy | None = None,
        registration_recovery=None,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibV52Transport()
        self.policy = policy or TelemetryPolicy()
        self.registration_recovery = registration_recovery

    def send(
        self,
        operation: V52OutboxOperation,
        *,
        installation_token: str | None = None,
        _record_registration: bool = True,
    ) -> V52ClientResult:
        if is_offline_edition():
            return self._failure("offline_edition", retryable=False)
        if request_fingerprint(operation.payload) != operation.request_fingerprint:
            return self._failure("request_fingerprint_mismatch", retryable=False)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": operation.idempotency_key,
        }
        if operation.event_type != "register":
            if not installation_token:
                return self._failure("installation_token_unavailable", retryable=False)
            headers["Authorization"] = f"Bearer {installation_token}"
        try:
            response = self.transport.request(
                url=self.config.endpoint(operation.event_type),
                headers=headers,
                body=json.dumps(
                    operation.payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                timeout=self.config.timeout_seconds,
            )
        except V52NetworkError as err:
            if (err.code == "tls_certificate_error" and operation.event_type == "register"
                    and self.registration_recovery is not None):
                return self.registration_recovery.send(self, operation)
            return self._failure(err.code, retryable=err.retryable,
                                 retry_after_seconds=300 if err.code.startswith("tls_") else None)
        payload = self._json(response.body)
        if not 200 <= response.status < 300:
            return self._error_response(response, payload)
        try:
            result = self._success_response(operation, response.status, payload)
        except (KeyError, TypeError, ValueError):
            return self._failure("contract_invalid", retryable=False, http_status=response.status)
        if result.success and operation.event_type == "register" and _record_registration:
            from services.registration_recovery import RegistrationRecovery
            RegistrationRecovery.close(str(operation.payload["installation_id"]))
        return result

    def _success_response(
        self,
        operation: V52OutboxOperation,
        status: int,
        payload: Mapping[str, object],
    ) -> V52ClientResult:
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError
        if payload.get("installation_id") != operation.payload.get("installation_id"):
            raise ValueError
        status_after = self.policy.status_interval_seconds
        meter_after = self.policy.meter_interval_seconds
        token = ""
        if operation.event_type == "register":
            fields = {
                "schema_version",
                "installation_id",
                "registration_status",
                "registered_at",
                "installation_token",
                "token_type",
                "expires_in",
                "next_status_after_seconds",
                "next_meter_after_seconds",
            }
            if set(payload) != fields or payload.get("registration_status") != "registered":
                raise ValueError
            token = payload["installation_token"]
            if not isinstance(token, str) or not token or payload.get("token_type") != "Bearer":
                raise ValueError
            status_after = self.policy.clamp_server_interval(payload["next_status_after_seconds"])
            meter_after = self.policy.clamp_server_interval(payload["next_meter_after_seconds"])
        elif operation.event_type == "status":
            fields = {"schema_version", "installation_id", "received_at", "next_status_after_seconds"}
            rotated_fields = fields | {"rotated_installation_token"}
            if frozenset(payload) not in {frozenset(fields), frozenset(rotated_fields)}:
                raise ValueError
            rotated_token = payload.get("rotated_installation_token", "")
            if not isinstance(rotated_token, str):
                raise ValueError
            if "rotated_installation_token" in payload and not rotated_token:
                raise ValueError
            token = rotated_token
            status_after = self.policy.clamp_server_interval(payload["next_status_after_seconds"])
        else:
            fields = {
                "schema_version",
                "installation_id",
                "received_at",
                "accepted_observations",
                "next_meter_after_seconds",
            }
            if set(payload) != fields:
                raise ValueError
            accepted = payload.get("accepted_observations")
            observations = operation.payload.get("observations")
            if (
                type(accepted) is not int
                or not 0 <= accepted <= 3
                or not isinstance(observations, list)
                or accepted != len(observations)
            ):
                raise ValueError
            meter_after = self.policy.clamp_server_interval(payload["next_meter_after_seconds"])
        return V52ClientResult(
            success=True,
            http_status=status,
            error_code="",
            retryable=False,
            retry_after_seconds=None,
            installation_token=token,
            next_status_after_seconds=status_after,
            next_meter_after_seconds=meter_after,
        )

    def _error_response(
        self, response: V52TransportResponse, payload: Mapping[str, object]
    ) -> V52ClientResult:
        error = payload.get("error")
        error_payload = error if isinstance(error, Mapping) else {}
        code = str(error_payload.get("code") or "http_error").strip().lower()
        if code == "http_error":
            code = ({407: "proxy_auth_required", 429: "rate_limited"}.get(response.status)
                    or ("host_redirect" if 300 <= response.status < 400 else "host_unavailable" if response.status >= 500 else "http_error"))
        declared = error_payload.get("retryable")
        retryable = (
            declared
            if isinstance(declared, bool)
            else response.status in {408, 425, 429, 500, 502, 503, 504}
        )
        if response.status in {400, 401, 403, 409, 422}:
            retryable = False
        retry_after = self._retry_after(response.headers)
        return self._failure(
            code,
            retryable=retryable,
            retry_after_seconds=retry_after,
            http_status=response.status,
        )

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> int | None:
        for key, value in headers.items():
            if str(key).casefold() == "retry-after":
                try:
                    return max(0, int(str(value).strip()))
                except ValueError:
                    try:
                        deadline = parsedate_to_datetime(str(value))
                        if deadline.tzinfo is None:
                            deadline = deadline.replace(tzinfo=UTC)
                        return max(0, int((deadline - datetime.now(UTC)).total_seconds()))
                    except (ValueError, TypeError, OverflowError):
                        return None
        return None

    @staticmethod
    def _json(body: bytes) -> Mapping[str, object]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _failure(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
        http_status: int | None = None,
    ) -> V52ClientResult:
        return V52ClientResult(
            success=False,
            http_status=http_status,
            error_code=code,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            installation_token="",
            next_status_after_seconds=self.policy.status_interval_seconds,
            next_meter_after_seconds=self.policy.meter_interval_seconds,
        )
