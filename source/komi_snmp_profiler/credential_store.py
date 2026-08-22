from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

DEFAULT_ADMIN_USERNAME = "Administrator"


class CredentialStoreError(RuntimeError):
    """Raised when a credential store cannot be used."""


@dataclass(frozen=True)
class AdminCredential:
    password: str
    username: str = DEFAULT_ADMIN_USERNAME

    def __post_init__(self) -> None:
        if not self.password:
            raise ValueError("กรุณาระบุ Administrator password")
        if self.username != DEFAULT_ADMIN_USERNAME:
            raise ValueError("Web Connection account ต้องเป็น Administrator")


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
