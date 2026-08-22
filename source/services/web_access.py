"""Machine-local credentials for the read-only KOMI Web viewer."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

ACCESS_HASH_KEY = "KOMI_WEB_ACCESS_HASH"
ACCESS_CONFIGURED_KEY = "KOMI_WEB_ACCESS_CONFIGURED"
AUTH_EPOCH_KEY = "KOMI_WEB_AUTH_EPOCH"
LEGACY_ACCESS_CODE_KEY = "KOMI_WEB_ACCESS_CODE"
SESSION_SECRET_KEY = "KOMI_WEB_SESSION_SECRET"
USER_KEY = "KOMI_WEB_USER"

MIN_ACCESS_CODE_LENGTH = 12
MAX_ACCESS_CODE_LENGTH = 128
SCRYPT_N = 1 << 17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 256 * 1024 * 1024

_PRIMARY_KEYS = (
    USER_KEY,
    ACCESS_HASH_KEY,
    ACCESS_CONFIGURED_KEY,
    SESSION_SECRET_KEY,
    AUTH_EPOCH_KEY,
)


@dataclass(frozen=True)
class WebAccessStatus:
    user: str
    configured: bool


def _read_values(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is None or not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def validate_web_access_code(access_code: str) -> str:
    if "\n" in access_code or "\r" in access_code:
        raise ValueError("รหัส Web ต้องอยู่ในบรรทัดเดียว")
    code = access_code.strip()
    if code != access_code:
        raise ValueError("รหัส Web ต้องไม่มีช่องว่างที่ต้นหรือท้าย")
    if len(code) < MIN_ACCESS_CODE_LENGTH:
        raise ValueError(f"รหัส Web ต้องยาวอย่างน้อย {MIN_ACCESS_CODE_LENGTH} ตัวอักษร")
    if len(code) > MAX_ACCESS_CODE_LENGTH:
        raise ValueError(f"รหัส Web ต้องไม่เกิน {MAX_ACCESS_CODE_LENGTH} ตัวอักษร")
    return code


def _encode_web_access_code(access_code: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        access_code.encode("utf-8"),
        salt=actual_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=SCRYPT_DKLEN,
    )
    # Next.js expands unescaped `$` characters while loading .env.local.
    # Use a colon delimiter so the encoded hash survives dotenv loading intact.
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}:{_encode(actual_salt)}:{_encode(digest)}"


def hash_web_access_code(access_code: str, *, salt: bytes | None = None) -> str:
    return _encode_web_access_code(validate_web_access_code(access_code), salt=salt)


def verify_web_access_code(access_code: str, encoded_hash: str) -> bool:
    try:
        delimiter = ":" if ":" in encoded_hash else "$"
        scheme, raw_n, raw_r, raw_p, encoded_salt, encoded_digest = encoded_hash.split(
            delimiter, 5
        )
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if scheme != "scrypt" or n != SCRYPT_N or r != SCRYPT_R or p != SCRYPT_P:
            return False
        salt = _decode(encoded_salt)
        expected = _decode(encoded_digest)
        if len(salt) != 16 or len(expected) != SCRYPT_DKLEN:
            return False
        actual = hashlib.scrypt(
            access_code.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=SCRYPT_MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError, UnicodeError):
        return False
    return hmac.compare_digest(actual, expected)


def _write_values(path: Path, values: dict[str, str]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    ordered_keys = [key for key in _PRIMARY_KEYS if key in values]
    ordered_keys.extend(
        key for key in sorted(values) if key not in _PRIMARY_KEYS and key != LEGACY_ACCESS_CODE_KEY
    )
    temporary.write_text(
        "\n".join(f"{key}={values[key]}" for key in ordered_keys) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


def read_web_runtime_values(env_path: Path) -> dict[str, str]:
    """Read machine-local runtime metadata; callers must never log secret values."""

    return _read_values(env_path.expanduser().resolve())


def update_web_runtime_values(env_path: Path, updates: dict[str, str]) -> None:
    """Atomically update non-plaintext runtime configuration beside auth secrets."""

    values = _read_values(env_path.expanduser().resolve())
    values.update(updates)
    values.pop(LEGACY_ACCESS_CODE_KEY, None)
    _write_values(env_path, values)


def ensure_web_access(env_path: Path, *, migrate_from: Path | None = None) -> dict[str, str]:
    """Create or migrate a credential file without persisting a plaintext access code."""

    env_path = env_path.expanduser().resolve()
    values = _read_values(env_path)
    if not values:
        values.update(_read_values(migrate_from))

    legacy_code = values.pop(LEGACY_ACCESS_CODE_KEY, "").strip()
    values.setdefault(USER_KEY, "admin")
    values.setdefault(SESSION_SECRET_KEY, secrets.token_hex(32))
    values.setdefault(AUTH_EPOCH_KEY, secrets.token_hex(16))

    if not values.get(ACCESS_HASH_KEY):
        if legacy_code:
            # Preserve a previously working code during one-time migration,
            # even when it predates the new minimum-length policy.
            values[ACCESS_HASH_KEY] = _encode_web_access_code(legacy_code)
            values[ACCESS_CONFIGURED_KEY] = "1"
        else:
            # New installs stay locked until the owner sets a code from Desktop Settings.
            values[ACCESS_HASH_KEY] = hash_web_access_code(secrets.token_urlsafe(24))
            values[ACCESS_CONFIGURED_KEY] = "0"
    values.setdefault(ACCESS_CONFIGURED_KEY, "1")

    _write_values(env_path, values)
    return {key: values[key] for key in _PRIMARY_KEYS}


def web_access_status(env_path: Path) -> WebAccessStatus:
    values = _read_values(env_path.expanduser().resolve())
    legacy_configured = bool(values.get(LEGACY_ACCESS_CODE_KEY))
    configured = (
        values.get(ACCESS_CONFIGURED_KEY) == "1" and bool(values.get(ACCESS_HASH_KEY))
    ) or legacy_configured
    return WebAccessStatus(user=values.get(USER_KEY, "admin"), configured=configured)


def set_web_access_code(env_path: Path, access_code: str) -> WebAccessStatus:
    """Replace the access hash atomically and rotate the session version."""

    code = validate_web_access_code(access_code)
    values = _read_values(env_path.expanduser().resolve())
    if not values:
        values.update(ensure_web_access(env_path))
    values.pop(LEGACY_ACCESS_CODE_KEY, None)
    values.setdefault(USER_KEY, "admin")
    values.setdefault(SESSION_SECRET_KEY, secrets.token_hex(32))
    values[ACCESS_HASH_KEY] = hash_web_access_code(code)
    values[ACCESS_CONFIGURED_KEY] = "1"
    values[AUTH_EPOCH_KEY] = secrets.token_hex(16)
    _write_values(env_path, values)
    return WebAccessStatus(user=values[USER_KEY], configured=True)
