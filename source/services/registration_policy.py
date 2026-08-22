"""Fail-closed runtime policy for Registration and Privacy.

The file referenced by ``KOMI_REGISTRATION_POLICY_FILE`` is configuration, not
a credential container. It may hold a non-public endpoint and vault reference,
but never a bootstrap value or bearer token.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

RegistrationEnvironment = Literal["staging", "production"]
BootstrapMode = Literal["anonymous", "vault_header"]

REQUIRED_NOTICE_FIELDS = frozenset(
    {
        "installation_id",
        "company_name",
        "client_first_started_at",
        "app_version",
        "platform",
        "architecture",
        "serial_number",
        "model",
        "selected",
        "device_slot",
        "timestamps",
        "status",
    }
)
HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
RESERVED_BOOTSTRAP_HEADERS = frozenset(
    {
        "accept",
        "authorization",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "idempotency-key",
        "proxy-authorization",
    }
)


@dataclass(frozen=True)
class PrivacyNotice:
    version: str
    approved: bool
    purpose: str
    fields: frozenset[str]
    retention: str
    deletion_contact: str
    legal_basis: str
    access_export: str
    approval_reference: str
    approved_at: str
    approval_owner: str

    @property
    def complete(self) -> bool:
        return bool(
            self.version.strip()
            and self.approved
            and self.purpose.strip()
            and REQUIRED_NOTICE_FIELDS == self.fields
            and self.retention.strip()
            and self.deletion_contact.strip()
            and self.legal_basis.strip()
            and self.access_export.strip()
            and self.approval_reference.strip()
            and self.approved_at.strip()
            and self.approval_owner.strip()
        )


@dataclass(frozen=True)
class RegistrationRuntimePolicy:
    base_url: str
    environment: RegistrationEnvironment
    bootstrap_mode: BootstrapMode
    bootstrap_header: str
    bootstrap_ref: str
    notice: PrivacyNotice
    request_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Registration API must use an absolute HTTPS URL")
        try:
            hostname = parsed.hostname
            _port = parsed.port
        except ValueError:
            raise ValueError("Registration API URL host or port is invalid") from None
        if not hostname or any(character.isspace() for character in self.base_url):
            raise ValueError("Registration API URL host is invalid")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Registration API URL must not contain userinfo, query, or fragment")
        if not math.isfinite(self.request_timeout_seconds) or not 1 <= self.request_timeout_seconds <= 60:
            raise ValueError("Registration request timeout must be between 1 and 60 seconds")
        if self.environment not in {"staging", "production"}:
            raise ValueError("Registration environment must be staging or production")
        if self.bootstrap_mode not in {"anonymous", "vault_header"}:
            raise ValueError("Registration bootstrap mode is unsupported")
        if self.bootstrap_mode == "anonymous" and self.environment != "staging":
            raise ValueError("Anonymous registration is allowed only in staging")
        if self.bootstrap_mode == "vault_header" and (
            not self.bootstrap_header.strip() or not self.bootstrap_ref.strip()
        ):
            raise ValueError("Vault bootstrap policy requires header and reference")
        if self.bootstrap_mode == "vault_header" and not HTTP_HEADER_NAME.fullmatch(
            self.bootstrap_header
        ):
            raise ValueError("Registration bootstrap header name is invalid")
        if self.bootstrap_mode == "vault_header" and (
            self.bootstrap_header.casefold() in RESERVED_BOOTSTRAP_HEADERS
        ):
            raise ValueError("Registration bootstrap header collides with a reserved header")

    def sending_blocker(self, *, accepted_notice_version: str, accepted_at: str) -> str:
        if not self.notice.complete:
            return "privacy_notice_unapproved"
        if accepted_notice_version != self.notice.version or not accepted_at.strip():
            return "privacy_notice_not_accepted"
        return ""

    def endpoint(self, event_type: Literal["register", "heartbeat"]) -> str:
        suffix = "register" if event_type == "register" else "heartbeat"
        return f"{self.base_url.rstrip('/')}/api/v1/installations/{suffix}"


def load_registration_policy(environ: dict[str, str] | None = None) -> RegistrationRuntimePolicy | None:
    """Load a non-secret policy artefact; return disabled when none is configured."""

    values = environ if environ is not None else os.environ
    raw_path = values.get("KOMI_REGISTRATION_POLICY_FILE", "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError("Registration policy artefact is unavailable or invalid") from err
    if not isinstance(payload, dict):
        raise ValueError("Registration policy artefact must be an object")
    allowed_root = {
        "base_url",
        "environment",
        "bootstrap",
        "privacy_notice",
        "request_timeout_seconds",
    }
    if set(payload) != allowed_root:
        raise ValueError("Registration policy artefact fields do not match the approved schema")
    bootstrap = payload.get("bootstrap")
    notice_payload = payload.get("privacy_notice")
    if not isinstance(bootstrap, dict) or not isinstance(notice_payload, dict):
        raise ValueError("Registration bootstrap and privacy notice must be objects")
    if set(bootstrap) != {"mode", "header", "vault_ref"}:
        raise ValueError("Registration bootstrap policy fields do not match the approved schema")
    notice_fields = {
        "version",
        "approved",
        "purpose",
        "fields",
        "retention",
        "deletion_contact",
        "legal_basis",
        "access_export",
        "approval_reference",
        "approved_at",
        "approval_owner",
    }
    if set(notice_payload) != notice_fields or not isinstance(notice_payload.get("fields"), list):
        raise ValueError("Privacy Notice policy fields do not match the approved schema")
    if type(payload["request_timeout_seconds"]) not in {int, float}:
        raise ValueError("Registration request timeout must be numeric")
    if any(
        not isinstance(value, str)
        for value in (
            payload["base_url"],
            payload["environment"],
            bootstrap["mode"],
            bootstrap["header"],
            bootstrap["vault_ref"],
            notice_payload["version"],
            notice_payload["purpose"],
            notice_payload["retention"],
            notice_payload["deletion_contact"],
            notice_payload["legal_basis"],
            notice_payload["access_export"],
            notice_payload["approval_reference"],
            notice_payload["approved_at"],
            notice_payload["approval_owner"],
        )
    ):
        raise ValueError("Registration policy text fields must be strings")
    if type(notice_payload["approved"]) is not bool or any(
        not isinstance(field, str) for field in notice_payload["fields"]
    ):
        raise ValueError("Privacy Notice approved and fields values are invalid")
    try:
        request_timeout = float(payload["request_timeout_seconds"])
    except (OverflowError, TypeError, ValueError):
        raise ValueError("Registration request timeout must be numeric") from None
    return RegistrationRuntimePolicy(
        base_url=str(payload["base_url"]),
        environment=str(payload["environment"]),  # type: ignore[arg-type]
        bootstrap_mode=str(bootstrap["mode"]),  # type: ignore[arg-type]
        bootstrap_header=str(bootstrap["header"]),
        bootstrap_ref=str(bootstrap["vault_ref"]),
        notice=PrivacyNotice(
            version=str(notice_payload["version"]),
            approved=notice_payload["approved"] is True,
            purpose=str(notice_payload["purpose"]),
            fields=frozenset(str(field) for field in notice_payload["fields"]),
            retention=str(notice_payload["retention"]),
            deletion_contact=str(notice_payload["deletion_contact"]),
            legal_basis=str(notice_payload["legal_basis"]),
            access_export=str(notice_payload["access_export"]),
            approval_reference=str(notice_payload["approval_reference"]),
            approved_at=str(notice_payload["approved_at"]),
            approval_owner=str(notice_payload["approval_owner"]),
        ),
        request_timeout_seconds=request_timeout,
    )
