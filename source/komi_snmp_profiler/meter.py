from __future__ import annotations

from dataclasses import replace
from ipaddress import ip_address
from typing import Protocol

from .connectors import (
    AuthenticatedWebConnectionCounterConnector,
    WebConnectionCounterConnector,
    WebConnectionError,
)
from .credential_store import AdminCredential, CredentialStore, CredentialStoreError
from .meter_export import MeterExportKind, MeterExportReader, MeterExportTable, subject_name_map
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
        self.public_connector = public_connector or WebConnectionCounterConnector()
        self.admin_connector = admin_connector or AuthenticatedWebConnectionCounterConnector()
        self.export_reader = export_reader or MeterExportReader(credential_store)

    def save_credential(self, host: str, credential: AdminCredential) -> None:
        self.credential_store.save(self._host(host), credential)

    def delete_credential(self, host: str) -> None:
        self.credential_store.delete(self._host(host))

    def has_credential(self, host: str) -> bool:
        return self.credential_store.load(self._host(host)) is not None

    def read(self, host: str) -> MeterReading:
        host = self._host(host)
        warnings: list[str] = []
        credential: AdminCredential | None = None
        try:
            credential = self.credential_store.load(host)
        except CredentialStoreError:
            warnings.append("อ่าน session credential ไม่สำเร็จ จึงใช้ public counter เท่านั้น")
        if credential is not None:
            try:
                result = self.admin_connector.collect_with_credential(host, credential)
                counters = list(result.counters)
                counters, identity_warnings = self._enrich_subject_names(host, counters)
                return MeterReading.create(
                    host,
                    counters,
                    result.source,
                    result.auth_state,
                    warnings + list(result.warnings) + identity_warnings,
                )
            except WebConnectionError:
                warnings.append(
                    "Administrator session ใช้งานไม่ได้หลังลองเพียงหนึ่งครั้ง; ใช้ public fallback เพื่อหลีกเลี่ยง lockout"
                )
        result = self.public_connector.collect_result(host)
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
        for kind in sorted(kinds):
            subject_type = "user" if kind == "User" else "account"
            try:
                names = subject_name_map(self.export_reader.read(host, kind))
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
