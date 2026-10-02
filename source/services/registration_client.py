"""Typed, redacted HTTPS client for Registration schema v2."""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from services.host_tls import create_host_tls_context

from services.registration_envelope import (
    validate_heartbeat_envelope,
    validate_registration_envelope,
)
from services.registration_policy import RegistrationRuntimePolicy
from services.registration_repository import OutboxOperation, canonical_payload, request_fingerprint

MAX_RESPONSE_BYTES = 1_048_576
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class NetworkTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class RegistrationTransport(Protocol):
    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> TransportResponse: ...


class UrllibRegistrationTransport:
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
    ) -> TransportResponse:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with self._opener.open(request, timeout=timeout) as response:  # noqa: S310
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise NetworkTransportError("Registration response exceeds size limit")
                return TransportResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=response_body,
                )
        except HTTPError as err:
            response_body = err.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                response_body = b""
            return TransportResponse(
                status=int(err.code),
                headers=dict(err.headers.items()) if err.headers else {},
                body=response_body,
            )
        except (URLError, TimeoutError, OSError) as err:
            raise NetworkTransportError("Registration network request failed") from err


@dataclass(frozen=True)
class RegistrationClientResult:
    success: bool
    http_status: int | None
    error_code: str
    retryable: bool
    retry_after_seconds: int | None
    request_id: str
    duration_ms: int
    installation_token: str
    registered_at: str
    last_seen_at: str
    next_heartbeat_after_seconds: int


class RegistrationClient:
    def __init__(self, transport: RegistrationTransport | None = None) -> None:
        self.transport = transport or UrllibRegistrationTransport()

    def send(
        self,
        operation: OutboxOperation,
        policy: RegistrationRuntimePolicy,
        *,
        bootstrap_secret: str | None = None,
        installation_token: str | None = None,
    ) -> RegistrationClientResult:
        if not isinstance(operation.payload, Mapping):
            return self._local_error("payload_invalid")
        try:
            if operation.event_type == "register":
                validate_registration_envelope(operation.payload)
            else:
                validate_heartbeat_envelope(operation.payload)
        except (AttributeError, TypeError, ValueError):
            return self._local_error("payload_invalid")
        current_fingerprint = request_fingerprint(operation.payload)
        if not hmac.compare_digest(current_fingerprint, operation.request_fingerprint):
            return self._local_error("request_fingerprint_mismatch")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": operation.idempotency_key,
        }
        if operation.event_type == "register":
            if policy.bootstrap_mode == "vault_header":
                if not bootstrap_secret:
                    return self._local_error("bootstrap_unavailable")
                headers[policy.bootstrap_header] = bootstrap_secret
        else:
            if not installation_token:
                return self._local_error("installation_token_unavailable")
            headers["Authorization"] = f"Bearer {installation_token}"

        started = monotonic()
        try:
            response = self.transport.request(
                url=policy.endpoint(operation.event_type),
                headers=headers,
                body=canonical_payload(operation.payload).encode("utf-8"),
                timeout=policy.request_timeout_seconds,
            )
        except NetworkTransportError:
            return RegistrationClientResult(
                success=False,
                http_status=None,
                error_code="offline",
                retryable=True,
                retry_after_seconds=None,
                request_id="",
                duration_ms=max(0, int((monotonic() - started) * 1000)),
                installation_token="",
                registered_at="",
                last_seen_at="",
                next_heartbeat_after_seconds=86_400,
            )
        duration_ms = max(0, int((monotonic() - started) * 1000))
        payload = self._safe_json(response.body)
        if not 200 <= response.status < 300:
            return self._http_error(response, payload, duration_ms)
        return self._success(operation, response, payload, duration_ms)

    @staticmethod
    def _safe_json(body: bytes) -> dict[str, object]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str:
        target = name.casefold()
        for key, value in headers.items():
            if str(key).casefold() == target:
                return str(value)
        return ""

    @classmethod
    def _retry_after(cls, headers: Mapping[str, str]) -> int | None:
        raw = cls._header(headers, "Retry-After").strip()
        if not raw:
            return None
        try:
            return max(0, int(raw))
        except ValueError:
            try:
                target = parsedate_to_datetime(raw)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                return max(0, int((target - datetime.now(UTC)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                return None

    def _http_error(
        self,
        response: TransportResponse,
        payload: dict[str, object],
        duration_ms: int,
    ) -> RegistrationClientResult:
        error = payload.get("error")
        error_payload = error if isinstance(error, dict) else {}
        code = self._safe_identifier(error_payload.get("code"), fallback="http_error").lower()
        request_id = self._safe_identifier(error_payload.get("request_id"), fallback="")
        declared_retryable = error_payload.get("retryable")
        retryable = (
            bool(declared_retryable)
            if isinstance(declared_retryable, bool)
            else response.status in {408, 425, 429, 500, 502, 503, 504}
        )
        if response.status in {401, 403}:
            code = "token_rejected"
            retryable = False
        return RegistrationClientResult(
            success=False,
            http_status=response.status,
            error_code=code or "http_error",
            retryable=retryable,
            retry_after_seconds=self._retry_after(response.headers),
            request_id=request_id,
            duration_ms=duration_ms,
            installation_token="",
            registered_at="",
            last_seen_at="",
            next_heartbeat_after_seconds=86_400,
        )

    @staticmethod
    def _safe_identifier(value: object, *, fallback: str) -> str:
        candidate = str(value or "").strip()
        return candidate if SAFE_IDENTIFIER.fullmatch(candidate) else fallback

    def _success(
        self,
        operation: OutboxOperation,
        response: TransportResponse,
        payload: dict[str, object],
        duration_ms: int,
    ) -> RegistrationClientResult:
        try:
            register_fields = {
                "schema_version",
                "installation_id",
                "registration_status",
                "registered_at",
                "installation_token",
                "next_heartbeat_after_seconds",
            }
            heartbeat_required = {
                "schema_version",
                "installation_id",
                "status",
                "last_seen_at",
                "next_heartbeat_after_seconds",
            }
            if operation.event_type == "register" and set(payload) != register_fields:
                raise ValueError
            if operation.event_type == "heartbeat" and (
                not heartbeat_required <= set(payload)
                or not (set(payload) - heartbeat_required) <= {"installation_token"}
            ):
                raise ValueError
            schema_version = payload["schema_version"]
            installation_id = payload["installation_id"]
            cadence = payload["next_heartbeat_after_seconds"]
            if type(schema_version) is not int or not isinstance(installation_id, str):
                raise ValueError
            if type(cadence) is not int:
                raise ValueError
            if schema_version != 2 or installation_id != str(operation.payload["installation_id"]):
                raise ValueError
            if not 60 <= cadence <= 31_536_000:
                raise ValueError
            if operation.event_type == "register":
                if payload["registration_status"] != "registered":
                    raise ValueError
                token = payload["installation_token"]
                registered_at = payload["registered_at"]
                if not isinstance(token, str) or not token:
                    raise ValueError
                if not self._valid_timestamp(registered_at):
                    raise ValueError
                last_seen_at = ""
            else:
                if payload["status"] not in {"ok", "registered", "active"}:
                    raise ValueError
                raw_token = payload.get("installation_token", "")
                if not isinstance(raw_token, str):
                    raise ValueError
                token = raw_token
                registered_at = ""
                last_seen_at = payload["last_seen_at"]
                if not self._valid_timestamp(last_seen_at):
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            return RegistrationClientResult(
                success=False,
                http_status=response.status,
                error_code="contract_invalid",
                retryable=False,
                retry_after_seconds=None,
                request_id=self._safe_identifier(
                    self._header(response.headers, "X-Request-ID"), fallback=""
                ),
                duration_ms=duration_ms,
                installation_token="",
                registered_at="",
                last_seen_at="",
                next_heartbeat_after_seconds=86_400,
            )
        return RegistrationClientResult(
            success=True,
            http_status=response.status,
            error_code="",
            retryable=False,
            retry_after_seconds=None,
            request_id=self._safe_identifier(
                self._header(response.headers, "X-Request-ID"), fallback=""
            ),
            duration_ms=duration_ms,
            installation_token=token,
            registered_at=registered_at,
            last_seen_at=last_seen_at,
            next_heartbeat_after_seconds=cadence,
        )

    @staticmethod
    def _valid_timestamp(value: object) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)

    @staticmethod
    def _local_error(code: str) -> RegistrationClientResult:
        return RegistrationClientResult(
            success=False,
            http_status=None,
            error_code=code,
            retryable=False,
            retry_after_seconds=None,
            request_id="",
            duration_ms=0,
            installation_token="",
            registered_at="",
            last_seen_at="",
            next_heartbeat_after_seconds=86_400,
        )
