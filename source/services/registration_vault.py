"""OS-vault boundary for registration bootstrap credentials and scoped tokens."""

from __future__ import annotations

import sys
import threading
from typing import Protocol

from komi_snmp_profiler.credential_store import CredentialStoreError

registration_state_lock = threading.RLock()


class RegistrationSecretStore(Protocol):
    def save(self, reference: str, secret: str) -> None: ...

    def load(self, reference: str) -> str | None: ...

    def delete(self, reference: str) -> None: ...


class SessionRegistrationSecretStore:
    """In-memory test/development store; never selected by production code."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def save(self, reference: str, secret: str) -> None:
        if not reference or not secret:
            raise CredentialStoreError("Registration secret reference/value is empty")
        self._values[reference] = secret

    def load(self, reference: str) -> str | None:
        return self._values.get(reference)

    def delete(self, reference: str) -> None:
        self._values.pop(reference, None)


class KeyringRegistrationSecretStore:
    """Use a dedicated keyring service, separate from printer credentials."""

    SERVICE_NAME = "KOMI Report V5 Registration Credentials"

    def __init__(self) -> None:
        if sys.platform != "darwin" and not sys.platform.startswith("win"):
            raise CredentialStoreError("OS credential vault supports registration on macOS and Windows only")
        try:
            import keyring

            backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                raise CredentialStoreError("OS credential vault is unavailable")
        except (ImportError, RuntimeError) as err:
            raise CredentialStoreError("OS credential vault is unavailable") from err
        self._keyring = keyring

    def save(self, reference: str, secret: str) -> None:
        if not reference or not secret:
            raise CredentialStoreError("Registration secret reference/value is empty")
        try:
            self._keyring.set_password(self.SERVICE_NAME, reference, secret)
        except Exception as err:
            raise CredentialStoreError("Cannot save registration secret to OS vault") from err

    def load(self, reference: str) -> str | None:
        if not reference:
            return None
        try:
            return self._keyring.get_password(self.SERVICE_NAME, reference)
        except Exception as err:
            raise CredentialStoreError("Cannot read registration secret from OS vault") from err

    def delete(self, reference: str) -> None:
        if not reference:
            return
        try:
            self._keyring.delete_password(self.SERVICE_NAME, reference)
        except self._keyring.errors.PasswordDeleteError:
            return
        except Exception as err:
            raise CredentialStoreError("Cannot delete registration secret from OS vault") from err


def platform_registration_secret_store() -> RegistrationSecretStore:
    return KeyringRegistrationSecretStore()


def installation_token_reference(installation_id: str) -> str:
    if not installation_id.strip():
        raise ValueError("installation_id is required for the token reference")
    return f"komi-report-v5:registration:{installation_id.strip()}:token"
