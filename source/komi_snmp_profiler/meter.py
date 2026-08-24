from __future__ import annotations

from dataclasses import replace
from ipaddress import ip_address
from typing import Protocol

from .connectors import (
    AuthenticatedWebConnectionCounterConnector,
    TlsPolicy,
    WebConnectionCounterConnector,
    WebConnectionAuthenticationError,
    WebConnectionError,
)
from .credential_store import AdminCredential, CredentialStore, CredentialStoreError
from .meter_export import (
    MeterCountExportConnector,
    MeterExportKind,
    MeterExportReader,
    MeterExportTable,
    subject_name_map,
)
from .models import MeterReading, WebAuthState


class MeterExportReaderLike(Protocol):
    def read(self, host: str, kind: MeterExportKind) -> MeterExportTable: ...


class MeterReader:
    """Select one Administrator read attempt when available, otherwise use the public counter API."""

    def __init__(
        self,
        credential_store: CredentialStore,
        *,
        public_connector: WebConnectionCounterConnector | None = None,
        admin_connector: AuthenticatedWebConnectionCounterConnector | None = None,
        export_reader: MeterExportReaderLike | None = None,
    ) -> None:
        self.credential_store = credential_store
        self.public_connector = public_connector
        self.admin_connector = admin_connector
        self.export_reader = export_reader

    def save_credential(self, host: str, credential: AdminCredential) -> None:
        self.credential_store.save(self._host(host), credential)

    def delete_credential(self, host: str) -> None:
        self.credential_store.delete(self._host(host))

    def has_credential(self, host: str) -> bool:
        return self.credential_store.load(self._host(host)) is not None

    def read(self, host: str) -> MeterReading:
        host = self._host(host)
        warnings: list[str] = []
        policy_provider = getattr(self.credential_store, "tls_policy", None)
        tls_policy = policy_provider(host) if callable(policy_provider) else TlsPolicy()
        if tls_policy.mode == "insecure":
            warnings.append(
                "คำเตือน: ปิดการตรวจสอบ TLS certificate แบบ explicit compatibility; "
                "ควรเปลี่ยนเป็น trusted certificate หรือ fingerprint pinning"
            )
        public_connector = self.public_connector or WebConnectionCounterConnector(tls_policy=tls_policy)
        admin_connector = self.admin_connector or AuthenticatedWebConnectionCounterConnector(
            tls_policy=tls_policy
        )
        credential: AdminCredential | None = None
        try:
            credential = self.credential_store.load(host)
        except CredentialStoreError:
            warnings.append("อ่าน session credential ไม่สำเร็จ จึงใช้ public counter เท่านั้น")
        admin_failure: WebConnectionError | None = None
        if credential is not None:
            try:
                result = admin_connector.collect_with_credential(host, credential)
                counters = list(result.counters)
                counters, identity_warnings = self._enrich_subject_names(host, counters, tls_policy)
                return MeterReading.create(
                    host,
                    counters,
                    result.source,
                    result.auth_state,
                    warnings + list(result.warnings) + identity_warnings,
                )
            except WebConnectionError as err:
                admin_failure = err
                warnings.append(
                    "Administrator session ใช้งานไม่ได้หลังลองเพียงหนึ่งครั้ง; ใช้ public fallback เพื่อหลีกเลี่ยง lockout"
                )
        try:
            result = public_connector.collect_result(host)
        except WebConnectionError:
            if isinstance(admin_failure, WebConnectionAuthenticationError):
                raise admin_failure
            raise
        auth_state = WebAuthState.PUBLIC_FALLBACK if warnings else WebAuthState.PUBLIC
        return MeterReading.create(
            host,
            list(result.counters),
            result.source,
            auth_state,
            warnings + list(result.warnings),
        )

    def _enrich_subject_names(
        self,
        host: str,
        counters: list,
        tls_policy: TlsPolicy,
    ) -> tuple[list, list[str]]:
        kinds: set[MeterExportKind] = set()
        for counter in counters:
            if counter.subject_name or not counter.subject_id:
                continue
            if counter.subject_type == "user":
                kinds.add("User")
            elif counter.subject_type in {"account", "track"}:
                kinds.add("Track")
        if not kinds:
            return counters, []

        names_by_type: dict[str, dict[str, str]] = {}
        warnings: list[str] = []
        export_reader = self.export_reader or MeterExportReader(
            self.credential_store,
            connector=MeterCountExportConnector(tls_policy=tls_policy),
        )
        for kind in sorted(kinds):
            subject_type = "user" if kind == "User" else "account"
            try:
                names = subject_name_map(export_reader.read(host, kind))
            except (CredentialStoreError, WebConnectionError, ValueError):
                warnings.append(f"อ่านชื่อ {kind} จาก RAM Meter export ไม่สำเร็จ; คง subject ID ไว้")
                continue
            if not names:
                warnings.append(f"RAM Meter export ไม่มีชื่อ {kind}; คง subject ID ไว้")
                continue
            names_by_type[subject_type] = names

        enriched = []
        for counter in counters:
            lookup_type = "account" if counter.subject_type == "track" else counter.subject_type
            name = names_by_type.get(lookup_type or "", {}).get(counter.subject_id or "")
            enriched.append(replace(counter, subject_name=name) if name and not counter.subject_name else counter)
        return enriched, warnings

    @staticmethod
    def _host(value: str) -> str:
        host = value.strip()
        if not host:
            raise ValueError("กรุณาระบุ IP address หรือ hostname")
        try:
            ip_address(host)
        except ValueError:
            if any(char.isspace() for char in host) or "." not in host or "/" in host:
                raise ValueError("hostname ไม่ถูกต้อง") from None
        return host
