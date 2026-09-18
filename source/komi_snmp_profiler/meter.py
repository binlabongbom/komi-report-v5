from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from ipaddress import ip_address
from typing import Protocol

from .connectors import (
    AuthenticatedWebConnectionCounterConnector,
    LegacyAuthenticatedWebConnectionCounterConnector,
    LegacyWebConnectionCounterConnector,
    TlsPolicy,
    WebConnectionAuthenticationError,
    WebConnectionCounterConnector,
    WebConnectionError,
    WebCounterCollection,
)
from .credential_store import (
    PUBLIC_FACTORY_ADMIN_PASSWORDS,
    AdminCredential,
    CredentialStore,
    CredentialStoreError,
)
from .device_profiles import WebMeterProtocol, resolve_device_meter_profile
from .meter_export import (
    MeterCountExportConnector,
    MeterExportKind,
    MeterExportReader,
    MeterExportTable,
    subject_name_map,
)
from .models import MeterReading, WebAuthState
from .subject_identity import subject_name_is_placeholder as _subject_name_is_placeholder, numeric_name_aliases


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
        legacy_public_connector: LegacyWebConnectionCounterConnector | None = None,
        legacy_admin_connector: LegacyAuthenticatedWebConnectionCounterConnector | None = None,
        export_reader: MeterExportReaderLike | None = None,
        allow_implicit_name_export: bool = False,
        public_factory_credentials: tuple[AdminCredential, ...] | None = None,
    ) -> None:
        self.credential_store = credential_store
        self.public_connector = public_connector
        self.admin_connector = admin_connector
        self.legacy_public_connector = legacy_public_connector
        self.legacy_admin_connector = legacy_admin_connector
        self.export_reader = export_reader
        self.allow_implicit_name_export = allow_implicit_name_export
        self._subject_name_cache: dict[tuple[str, MeterExportKind], dict[str, str]] = {}
        self.public_factory_credentials = (
            tuple(AdminCredential(password=value) for value in PUBLIC_FACTORY_ADMIN_PASSWORDS)
            if public_factory_credentials is None
            else tuple(public_factory_credentials)
        )

    def save_credential(self, host: str, credential: AdminCredential) -> None:
        self.credential_store.save(self._host(host), credential)

    def delete_credential(self, host: str) -> None:
        self.credential_store.delete(self._host(host))

    def has_credential(self, host: str) -> bool:
        return self.credential_store.load(self._host(host)) is not None

    def read(self, host: str, *, model: str = "") -> MeterReading:
        host = self._host(host)
        warnings: list[str] = []
        profile = resolve_device_meter_profile(model)
        policy_provider = getattr(self.credential_store, "tls_policy", None)
        tls_policy = policy_provider(host) if callable(policy_provider) else TlsPolicy()
        tls_policy = replace(tls_policy, compatibility=profile.tls_compatibility)
        if tls_policy.mode == "insecure":
            warnings.append(
                "คำเตือน: ปิดการตรวจสอบ TLS certificate แบบ explicit compatibility; "
                "ควรเปลี่ยนเป็น trusted certificate หรือ fingerprint pinning"
            )
        public_connector = self.public_connector or WebConnectionCounterConnector(
            tls_policy=tls_policy,
            scheme=profile.web_scheme,
        )
        admin_connector = self.admin_connector or AuthenticatedWebConnectionCounterConnector(
            tls_policy=tls_policy,
            scheme=profile.web_scheme,
        )
        credential: AdminCredential | None = None
        try:
            credential = self.credential_store.load(host)
        except CredentialStoreError:
            warnings.append("อ่าน session credential ไม่สำเร็จ จึงใช้ public counter เท่านั้น")
        if profile.web_protocol == WebMeterProtocol.LEGACY_XML_PUBLIC:
            connector = self.legacy_public_connector or LegacyWebConnectionCounterConnector(
                tls_policy=tls_policy,
                scheme=profile.web_scheme,
            )
            result = connector.collect_result(host, scheme=profile.web_scheme)
            legacy_warnings = warnings + list(result.warnings)
            if not any(counter.subject_type for counter in result.counters):
                legacy_warnings.append(
                    "Legacy Web Connection ไม่เปิดเผยสถานะ User Authentication / Account Track ใน snapshot นี้"
                )
            return MeterReading.create(
                host,
                list(result.counters),
                result.source,
                result.auth_state,
                legacy_warnings,
            )
        if profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN:
            connector = self.legacy_admin_connector or LegacyAuthenticatedWebConnectionCounterConnector(
                tls_policy=tls_policy,
                scheme=profile.web_scheme,
            )
            if credential is None:
                result = self._read_with_public_factory_credentials(
                    host,
                    lambda candidate: connector.collect_with_credential(
                        host,
                        candidate,
                        scheme=profile.web_scheme,
                    ),
                    warnings,
                )
            else:
                result = connector.collect_with_credential(
                    host,
                    credential,
                    scheme=profile.web_scheme,
                )
            legacy_warnings = warnings + list(result.warnings)
            if not any(counter.subject_type for counter in result.counters):
                legacy_warnings.append(
                    "Legacy Web Connection ไม่เปิดเผยสถานะ User Authentication / Account Track ใน snapshot นี้"
                )
            return MeterReading.create(
                host,
                list(result.counters),
                result.source,
                result.auth_state,
                legacy_warnings,
            )
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
        except WebConnectionAuthenticationError:
            if credential is not None:
                if isinstance(admin_failure, WebConnectionAuthenticationError):
                    raise admin_failure from None
                raise
            result = self._read_with_public_factory_credentials(
                host,
                lambda candidate: admin_connector.collect_with_credential(host, candidate),
                warnings,
            )
            counters = list(result.counters)
            counters, identity_warnings = self._enrich_subject_names(host, counters, tls_policy)
            return MeterReading.create(
                host,
                counters,
                result.source,
                result.auth_state,
                warnings + list(result.warnings) + identity_warnings,
            )
        except WebConnectionError:
            if isinstance(admin_failure, WebConnectionAuthenticationError):
                raise admin_failure from None
            raise
        auth_state = WebAuthState.PUBLIC_FALLBACK if warnings else WebAuthState.PUBLIC
        counters = list(result.counters)
        counters, identity_warnings = self._enrich_subject_names(host, counters, tls_policy)
        return MeterReading.create(
            host,
            counters,
            result.source,
            auth_state,
            warnings + list(result.warnings) + identity_warnings,
        )

    def _read_with_public_factory_credentials(
        self,
        host: str,
        read: Callable[[AdminCredential], WebCounterCollection],
        warnings: list[str],
    ) -> WebCounterCollection:
        """Try exactly two public defaults, remember only the successful one."""

        for position, candidate in enumerate(self.public_factory_credentials, start=1):
            try:
                result = read(candidate)
            except WebConnectionAuthenticationError:
                continue
            try:
                self.credential_store.save(host, candidate)
            except CredentialStoreError:
                warnings.append(
                    "รหัสเริ่มต้นผ่าน แต่ OS Credential Vault ยังบันทึกไม่ได้; "
                    "รอบถัดไปอาจต้องตรวจใหม่"
                )
            warnings.append(f"ใช้รหัสเริ่มต้นสาธารณะชุดที่ {position}")
            return result
        raise WebConnectionAuthenticationError(
            "รหัสเริ่มต้นของเครื่องทั้ง 2 แบบไม่ผ่าน · "
            "กรุณากรอกรหัส Administrator ที่ลูกค้าตั้งไว้"
        ) from None

    def _enrich_subject_names(
        self,
        host: str,
        counters: list,
        tls_policy: TlsPolicy,
    ) -> tuple[list, list[str]]:
        kinds: set[MeterExportKind] = set()
        for counter in counters:
            if not counter.subject_id:
                continue
            if not _subject_name_is_placeholder(counter.subject_id, counter.subject_name):
                continue
            if counter.subject_type == "user":
                kinds.add("User")
            elif counter.subject_type in {"account", "track"}:
                kinds.add("Track")
        if not kinds:
            return counters, []

        names_by_type: dict[str, dict[str, str]] = {}
        warnings: list[str] = []
        # The device's normal counter JSON contains AuthNo/TrackNo but may omit
        # the visible names or echo the numeric ID as the visible name. Long-lived
        # polling callers may opt in to one bounded RAM Meter export per host/kind;
        # the result is cached so every polling cycle does not create a new job.
        export_reader = self.export_reader
        if export_reader is None and self.allow_implicit_name_export:
            export_reader = MeterExportReader(
                self.credential_store,
                connector=MeterCountExportConnector(tls_policy=tls_policy),
            )
        if export_reader is None:
            return counters, []
        for kind in sorted(kinds):
            subject_type = "user" if kind == "User" else "account"
            cache_key = (host, kind)
            cached_names = self._subject_name_cache.get(cache_key)
            if cached_names:
                names_by_type[subject_type] = cached_names
                continue
            try:
                names = subject_name_map(export_reader.read(host, kind))
            except (CredentialStoreError, WebConnectionError, ValueError):
                warnings.append(f"อ่านชื่อ {kind} จาก RAM Meter export ไม่สำเร็จ; คง subject ID ไว้")
                continue
            if not names:
                warnings.append(f"RAM Meter export ไม่มีชื่อ {kind}; คง subject ID ไว้")
                continue
            self._subject_name_cache[cache_key] = names
            names_by_type[subject_type] = names

        enriched = []
        aliases = {kind: numeric_name_aliases(names) for kind, names in names_by_type.items()}
        for counter in counters:
            lookup_type = "account" if counter.subject_type == "track" else counter.subject_type
            name = names_by_type.get(lookup_type or "", {}).get(counter.subject_id or "")
            if not name and str(counter.subject_id or "").isdecimal():
                name = aliases.get(lookup_type or "", {}).get(str(int(counter.subject_id)))
            should_replace = bool(name) and _subject_name_is_placeholder(
                counter.subject_id,
                counter.subject_name,
            )
            enriched.append(replace(counter, subject_name=name) if should_replace else counter)
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
