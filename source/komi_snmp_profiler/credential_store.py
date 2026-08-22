from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Protocol

DEFAULT_ADMIN_USERNAME = "administrator"


class CredentialStoreError(RuntimeError):
    """Raised when a credential store cannot be used."""


@dataclass(frozen=True)
class AdminCredential:
    password: str
    username: str = DEFAULT_ADMIN_USERNAME

    def __post_init__(self) -> None:
        if not self.password:
            raise ValueError("กรุณาระบุ Administrator password")
        if self.username.lower() != DEFAULT_ADMIN_USERNAME:
            raise ValueError("Web Connection account ต้องเป็น Administrator")
        object.__setattr__(self, "username", DEFAULT_ADMIN_USERNAME)


class CredentialStore(Protocol):
    def save(self, host: str, credential: AdminCredential) -> None: ...

    def load(self, host: str) -> AdminCredential | None: ...

    def delete(self, host: str) -> None: ...


class SessionCredentialStore:
    """Keep explicit per-host Administrator credentials only in process memory."""

    def __init__(self) -> None:
        self._credentials: dict[str, AdminCredential] = {}

    def save(self, host: str, credential: AdminCredential) -> None:
        self._credentials[host] = credential

    def load(self, host: str) -> AdminCredential | None:
        return self._credentials.get(host)

    def delete(self, host: str) -> None:
        self._credentials.pop(host, None)

    def clear(self) -> None:
        self._credentials.clear()


class KeyringCredentialStore:
    """Persist credentials in macOS Keychain or Windows Credential Manager."""

    SERVICE_NAME = "KOMI Report V5 Printer Credentials"

    def __init__(self) -> None:
        if sys.platform != "darwin" and not sys.platform.startswith("win"):
            raise CredentialStoreError("OS credential vault รองรับ production บน macOS และ Windows เท่านั้น")
        try:
            import keyring

            backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                raise CredentialStoreError("OS credential vault ไม่พร้อมใช้งาน")
        except (ImportError, RuntimeError) as err:
            raise CredentialStoreError("OS credential vault ไม่พร้อมใช้งาน") from err
        self._keyring = keyring

    def save(self, reference: str, credential: AdminCredential) -> None:
        payload = json.dumps(
            {"username": credential.username, "password": credential.password},
            separators=(",", ":"),
        )
        try:
            self._keyring.set_password(self.SERVICE_NAME, reference, payload)
        except Exception as err:
            raise CredentialStoreError("บันทึก credential ลง OS vault ไม่สำเร็จ") from err

    def load(self, reference: str) -> AdminCredential | None:
        try:
            payload = self._keyring.get_password(self.SERVICE_NAME, reference)
        except Exception as err:
            raise CredentialStoreError("อ่าน credential จาก OS vault ไม่สำเร็จ") from err
        if payload is None:
            return None
        try:
            values = json.loads(payload)
            return AdminCredential(username=values["username"], password=values["password"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
            raise CredentialStoreError("ข้อมูล credential ใน OS vault ไม่ถูกต้อง") from err

    def delete(self, reference: str) -> None:
        try:
            self._keyring.delete_password(self.SERVICE_NAME, reference)
        except self._keyring.errors.PasswordDeleteError:
            return
        except Exception as err:
            raise CredentialStoreError("ลบ credential จาก OS vault ไม่สำเร็จ") from err


def platform_credential_store() -> CredentialStore:
    """Return the supported production vault or fail closed."""

    return KeyringCredentialStore()
