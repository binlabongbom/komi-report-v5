from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address

from config import DEFAULT_ADMIN_USERNAME
from database import _open
from komi_snmp_profiler.connectors import TlsPolicy
from komi_snmp_profiler.credential_store import (
    AdminCredential,
    CredentialStore,
    CredentialStoreError,
    platform_credential_store,
)


@dataclass(frozen=True)
class DeviceConfig:
    slot: int
    name: str
    host: str
    username: str = DEFAULT_ADMIN_USERNAME
    password: str = ""
    enabled: bool = True
    model: str = ""
    serial: str = ""
    connection_status: str = "pending"
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_error: str = ""
    last_total: int | None = None
    credential_ref: str = ""
    tls_mode: str = "system"
    tls_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.slot <= 2:
            raise ValueError("slot ต้องอยู่ระหว่าง 0–2")
        if not self.name.strip():
            raise ValueError("กรุณาระบุชื่อเรียกเครื่อง")
        host = self.host.strip()
        if not host:
            raise ValueError("กรุณาระบุ IP address")
        try:
            ip_address(host)
        except ValueError:
            if any(char.isspace() for char in host) or "." not in host or "/" in host:
                raise ValueError("IP address หรือ hostname ไม่ถูกต้อง") from None
        TlsPolicy(mode=self.tls_mode, fingerprint_sha256=self.tls_fingerprint)


class DeviceConfigRepository:
    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self.credential_store = credential_store or platform_credential_store()
        self._migration_checked = False

    @staticmethod
    def _credential_reference(connection, slot: int) -> str:
        row = connection.execute(
            "SELECT value FROM settings WHERE key='credential_vault_id'"
        ).fetchone()
        vault_id = str(row[0]) if row and row[0] else secrets.token_hex(16)
        if not row or not row[0]:
            connection.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES('credential_vault_id',?)",
                (vault_id,),
            )
        return f"komi-report-v5:{vault_id}:device:{slot}"

    def migrate_legacy_plaintext_credentials(self) -> int:
        """Move legacy passwords to the vault and undo vault writes if migration fails."""

        with _open(commit=False) as connection:
            rows = connection.execute(
                "SELECT slot,username,password,credential_ref FROM devices WHERE password<>''"
            ).fetchall()
        if not rows:
            self._migration_checked = True
            return 0

        staged: list[tuple[str, AdminCredential | None]] = []
        updates: list[tuple[str, int]] = []
        try:
            with _open() as connection:
                for slot, username, password, existing_ref in rows:
                    reference = existing_ref or self._credential_reference(connection, int(slot))
                    previous = self.credential_store.load(reference)
                    self.credential_store.save(
                        reference,
                        AdminCredential(username=username, password=password),
                    )
                    staged.append((reference, previous))
                    updates.append((reference, int(slot)))
                connection.executemany(
                    "UPDATE devices SET credential_ref=?,password='' WHERE slot=?",
                    updates,
                )
        except Exception as err:
            for reference, previous in reversed(staged):
                try:
                    if previous is None:
                        self.credential_store.delete(reference)
                    else:
                        self.credential_store.save(reference, previous)
                except CredentialStoreError:
                    pass
            if isinstance(err, CredentialStoreError):
                raise
            raise CredentialStoreError(
                "ย้าย legacy credential ไป OS vault ไม่สำเร็จ; Database เดิมไม่ถูกแก้"
            ) from err
        self._migration_checked = True
        return len(updates)

    def _ensure_migrated(self) -> None:
        if not self._migration_checked:
            self.migrate_legacy_plaintext_credentials()

    def list(self, *, enabled_only: bool = False) -> list[DeviceConfig]:
        self._ensure_migrated()
        where = "WHERE enabled=1" if enabled_only else ""
        with _open(commit=False) as conn:
            rows = conn.execute(
                f"""SELECT slot,name,host,username,credential_ref,tls_mode,tls_fingerprint,enabled,model,serial,
                           connection_status,last_checked_at,last_success_at,last_error,last_total
                    FROM devices {where} ORDER BY slot"""
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, slot: int) -> DeviceConfig | None:
        self._ensure_migrated()
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT slot,name,host,username,credential_ref,tls_mode,tls_fingerprint,enabled,model,serial,
                          connection_status,last_checked_at,last_success_at,last_error,last_total
                   FROM devices WHERE slot=?""",
                (slot,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_host(self, host: str) -> DeviceConfig | None:
        self._ensure_migrated()
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT slot,name,host,username,credential_ref,tls_mode,tls_fingerprint,enabled,model,serial,
                          connection_status,last_checked_at,last_success_at,last_error,last_total
                   FROM devices WHERE host=?""",
                (host.strip(),),
            ).fetchone()
        return self._from_row(row) if row else None

    def replace_all(self, devices: list[DeviceConfig]) -> None:
        if not 1 <= len(devices) <= 3:
            raise ValueError("ต้องตั้งค่าเครื่องอย่างน้อย 1 และไม่เกิน 3 เครื่อง")
        slots = [item.slot for item in devices]
        hosts = [item.host.strip() for item in devices]
        if len(set(slots)) != len(slots) or len(set(hosts)) != len(hosts):
            raise ValueError("slot และ IP address ห้ามซ้ำกัน")
        self._ensure_migrated()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        staged: list[tuple[str, AdminCredential | None]] = []
        try:
            with _open() as conn:
                placeholders = ",".join("?" for _ in slots)
                conn.execute(f"UPDATE devices SET enabled=0 WHERE slot NOT IN ({placeholders})", slots)
                for item in devices:
                    existing = conn.execute(
                        "SELECT credential_ref FROM devices WHERE slot=?", (item.slot,)
                    ).fetchone()
                    reference = item.credential_ref or (existing[0] if existing else "")
                    if item.password:
                        reference = reference or self._credential_reference(conn, item.slot)
                        previous = self.credential_store.load(reference)
                        self.credential_store.save(
                            reference,
                            AdminCredential(username=item.username, password=item.password),
                        )
                        staged.append((reference, previous))
                    conn.execute(
                        """INSERT INTO devices(
                               slot,name,host,username,password,credential_ref,tls_mode,tls_fingerprint,enabled,model,serial,
                               connection_status,last_checked_at,last_success_at,last_error,last_total,updated_at
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(slot) DO UPDATE SET
                             name=excluded.name,host=excluded.host,username=excluded.username,
                             password='',credential_ref=excluded.credential_ref,
                             tls_mode=excluded.tls_mode,tls_fingerprint=excluded.tls_fingerprint,
                             enabled=excluded.enabled,
                             model=excluded.model,serial=excluded.serial,
                             connection_status=excluded.connection_status,
                             last_checked_at=excluded.last_checked_at,last_success_at=excluded.last_success_at,
                             last_error=excluded.last_error,last_total=excluded.last_total,updated_at=excluded.updated_at""",
                        (
                            item.slot,
                            item.name.strip(),
                            item.host.strip(),
                            item.username,
                            "",
                            reference,
                            item.tls_mode,
                            item.tls_fingerprint,
                            int(item.enabled),
                            item.model,
                            item.serial,
                            item.connection_status,
                            item.last_checked_at,
                            item.last_success_at,
                            item.last_error,
                            item.last_total,
                            now,
                        ),
                    )
        except Exception:
            for reference, previous in reversed(staged):
                try:
                    if previous is None:
                        self.credential_store.delete(reference)
                    else:
                        self.credential_store.save(reference, previous)
                except CredentialStoreError:
                    pass
            raise

    def save_credential(self, host: str, credential: AdminCredential) -> None:
        self._ensure_migrated()
        previous: AdminCredential | None = None
        reference = ""
        try:
            with _open() as connection:
                row = connection.execute(
                    "SELECT slot,credential_ref FROM devices WHERE host=?", (host.strip(),)
                ).fetchone()
                if row is None:
                    raise ValueError("ยังไม่มีเครื่องนี้ใน Settings")
                reference = row[1] or self._credential_reference(connection, int(row[0]))
                previous = self.credential_store.load(reference)
                self.credential_store.save(reference, credential)
                connection.execute(
                    "UPDATE devices SET username=?,credential_ref=?,password='' WHERE slot=?",
                    (credential.username, reference, int(row[0])),
                )
        except Exception:
            if reference:
                try:
                    if previous is None:
                        self.credential_store.delete(reference)
                    else:
                        self.credential_store.save(reference, previous)
                except CredentialStoreError:
                    pass
            raise

    def load_credential(self, host: str) -> AdminCredential | None:
        self._ensure_migrated()
        with _open(commit=False) as connection:
            row = connection.execute(
                "SELECT credential_ref FROM devices WHERE host=?", (host.strip(),)
            ).fetchone()
        if row is None or not row[0]:
            return None
        return self.credential_store.load(str(row[0]))

    def delete_credential(self, host: str) -> None:
        self._ensure_migrated()
        reference = ""
        previous: AdminCredential | None = None
        try:
            with _open() as connection:
                row = connection.execute(
                    "SELECT slot,credential_ref FROM devices WHERE host=?", (host.strip(),)
                ).fetchone()
                if row is None:
                    return
                reference = str(row[1] or "")
                if reference:
                    previous = self.credential_store.load(reference)
                    self.credential_store.delete(reference)
                connection.execute(
                    "UPDATE devices SET credential_ref='',password='' WHERE slot=?", (int(row[0]),)
                )
        except Exception:
            if reference and previous is not None:
                try:
                    self.credential_store.save(reference, previous)
                except CredentialStoreError:
                    pass
            raise

    def tls_policy(self, host: str) -> TlsPolicy:
        with _open(commit=False) as connection:
            row = connection.execute(
                "SELECT tls_mode,tls_fingerprint FROM devices WHERE host=?", (host.strip(),)
            ).fetchone()
        if row is None:
            return TlsPolicy()
        return TlsPolicy(mode=row[0] or "system", fingerprint_sha256=row[1] or "")

    def update_runtime(
        self,
        slot: int,
        *,
        status: str,
        checked_at: str,
        success_at: str | None = None,
        error: str = "",
        total: int | None = None,
        model: str | None = None,
        serial: str | None = None,
    ) -> None:
        assignments = ["connection_status=?", "last_checked_at=?", "last_error=?", "updated_at=?"]
        values: list[object] = [status, checked_at, error, checked_at]
        if success_at is not None:
            assignments.append("last_success_at=?")
            values.append(success_at)
        if total is not None:
            assignments.append("last_total=?")
            values.append(int(total))
        if model:
            assignments.append("model=?")
            values.append(model)
        if serial:
            assignments.append("serial=?")
            values.append(serial)
        values.append(slot)
        with _open() as conn:
            conn.execute(f"UPDATE devices SET {','.join(assignments)} WHERE slot=?", values)

    def setup_complete(self) -> bool:
        with _open(commit=False) as conn:
            return bool(conn.execute("SELECT 1 FROM devices LIMIT 1").fetchone())

    def _from_row(self, row: tuple) -> DeviceConfig:
        reference = row[4] or ""
        credential = self.credential_store.load(reference) if reference else None
        return DeviceConfig(
            slot=row[0],
            name=row[1],
            host=row[2],
            username=row[3],
            password=credential.password if credential else "",
            credential_ref=reference,
            tls_mode=row[5] or "system",
            tls_fingerprint=row[6] or "",
            enabled=bool(row[7]),
            model=row[8] or "",
            serial=row[9] or "",
            connection_status=row[10] or "pending",
            last_checked_at=row[11],
            last_success_at=row[12],
            last_error=row[13] or "",
            last_total=row[14],
        )


class DatabaseCredentialStore(CredentialStore):
    """Compatibility facade backed by the repository OS vault, never SQLite plaintext."""

    def __init__(self, repository: DeviceConfigRepository) -> None:
        self.repository = repository

    def save(self, host: str, credential: AdminCredential) -> None:
        self.repository.save_credential(host, credential)

    def load(self, host: str) -> AdminCredential | None:
        return self.repository.load_credential(host)

    def delete(self, host: str) -> None:
        self.repository.delete_credential(host)

    def tls_policy(self, host: str) -> TlsPolicy:
        return self.repository.tls_policy(host)
