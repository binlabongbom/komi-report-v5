"""Installation-scoped Ed25519 identity backed only by the OS vault boundary."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.registration_vault import RegistrationSecretStore


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        candidate = value.strip().encode("ascii")
        return base64.urlsafe_b64decode(candidate + b"=" * (-len(candidate) % 4))
    except (UnicodeEncodeError, ValueError) as err:
        raise ValueError("installation private key is invalid") from err


def installation_private_key_reference(installation_id: str) -> str:
    candidate = installation_id.strip()
    if not candidate:
        raise ValueError("installation_id is required for the private key reference")
    return f"komi-report-v5:installation:{candidate}:ed25519-private"


@dataclass(frozen=True)
class InstallationIdentity:
    installation_id: str
    public_key_base64url: str
    key_reference: str = field(repr=False)
    _private_key: Ed25519PrivateKey = field(repr=False, compare=False)

    @property
    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, value: bytes) -> str:
        return _encode(self._private_key.sign(value))


def load_or_create_installation_identity(
    vault: RegistrationSecretStore,
    installation_id: str,
) -> InstallationIdentity:
    candidate = installation_id.strip()
    if not candidate:
        raise ValueError("installation_id is required")
    reference = installation_private_key_reference(candidate)
    stored = vault.load(reference)
    if stored:
        try:
            raw_private = _decode(stored)
            if len(raw_private) != 32:
                raise ValueError
            private_key = Ed25519PrivateKey.from_private_bytes(raw_private)
        except (TypeError, ValueError) as err:
            raise ValueError("installation private key is invalid") from err
    else:
        private_key = Ed25519PrivateKey.generate()
        raw_private = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        vault.save(reference, _encode(raw_private))
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return InstallationIdentity(
        installation_id=candidate,
        public_key_base64url=_encode(public_key),
        key_reference=reference,
        _private_key=private_key,
    )
