from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address

from config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME
from database import _open
from komi_snmp_profiler.credential_store import AdminCredential, CredentialStore


@dataclass(frozen=True)
class DeviceConfig:
    slot: int
    name: str
    host: str
    username: str = DEFAULT_ADMIN_USERNAME
    password: str = DEFAULT_ADMIN_PASSWORD
    enabled: bool = True
    model: str = ""
    serial: str = ""
    connection_status: str = "pending"
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_error: str = ""
    last_total: int | None = None

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
        if not self.password:
            raise ValueError("กรุณาระบุ Administrator password")


class DeviceConfigRepository:
    def list(self, *, enabled_only: bool = False) -> list[DeviceConfig]:
        where = "WHERE enabled=1" if enabled_only else ""
        with _open(commit=False) as conn:
            rows = conn.execute(
                f"""SELECT slot,name,host,username,password,enabled,model,serial,
                           connection_status,last_checked_at,last_success_at,last_error,last_total
                    FROM devices {where} ORDER BY slot"""
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, slot: int) -> DeviceConfig | None:
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT slot,name,host,username,password,enabled,model,serial,
                          connection_status,last_checked_at,last_success_at,last_error,last_total
                   FROM devices WHERE slot=?""",
                (slot,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_host(self, host: str) -> DeviceConfig | None:
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT slot,name,host,username,password,enabled,model,serial,
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
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with _open() as conn:
            if slots:
                placeholders = ",".join("?" for _ in slots)
                conn.execute(f"UPDATE devices SET enabled=0 WHERE slot NOT IN ({placeholders})", slots)
            for item in devices:
                conn.execute(
                    """INSERT INTO devices(
                           slot,name,host,username,password,enabled,model,serial,
                           connection_status,last_checked_at,last_success_at,last_error,last_total,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(slot) DO UPDATE SET
                         name=excluded.name,host=excluded.host,username=excluded.username,
                         password=excluded.password,enabled=excluded.enabled,model=excluded.model,
                         serial=excluded.serial,connection_status=excluded.connection_status,
                         last_checked_at=excluded.last_checked_at,last_success_at=excluded.last_success_at,
                         last_error=excluded.last_error,last_total=excluded.last_total,updated_at=excluded.updated_at""",
                    (
                        item.slot,
                        item.name.strip(),
                        item.host.strip(),
                        item.username,
                        item.password,
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

    @staticmethod
    def _from_row(row: tuple) -> DeviceConfig:
        return DeviceConfig(
            slot=row[0],
            name=row[1],
            host=row[2],
            username=row[3],
            password=row[4],
            enabled=bool(row[5]),
            model=row[6] or "",
            serial=row[7] or "",
            connection_status=row[8] or "pending",
            last_checked_at=row[9],
            last_success_at=row[10],
            last_error=row[11] or "",
            last_total=row[12],
        )


class DatabaseCredentialStore(CredentialStore):
    """Credential store intentionally backed by the local application database."""

    def __init__(self, repository: DeviceConfigRepository) -> None:
        self.repository = repository

    def save(self, host: str, credential: AdminCredential) -> None:
        device = self.repository.get_by_host(host)
        if device is None:
            raise ValueError("ยังไม่มีเครื่องนี้ใน Settings")
        replacement = DeviceConfig(**{**device.__dict__, "password": credential.password})
        devices = [replacement if item.slot == device.slot else item for item in self.repository.list()]
        self.repository.replace_all(devices)

    def load(self, host: str) -> AdminCredential | None:
        device = self.repository.get_by_host(host)
        if device is None or not device.password:
            return None
        return AdminCredential(password=device.password)

    def delete(self, host: str) -> None:
        device = self.repository.get_by_host(host)
        if device is None:
            return
        replacement = DeviceConfig(**{**device.__dict__, "password": DEFAULT_ADMIN_PASSWORD})
        devices = [replacement if item.slot == device.slot else item for item in self.repository.list()]
        self.repository.replace_all(devices)
