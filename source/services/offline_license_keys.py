"""Load Host Offline License verification keys from a public-only bundle.

The file contains Ed25519 *public* keys only.  It is safe to distribute with
the Desktop application and is deliberately separate from Windows/macOS code
signing.  Host private signing material must never be present on Desktop.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

PUBLIC_KEYS_FILENAME = "public-verification-keys.json"
MAX_PUBLIC_KEYS_BYTES = 65_536
_KID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "algorithm", "keys"})
_KEY_FIELDS = frozenset({"kid", "public_key_base64url"})


class OfflineLicensePublicKeyConfigurationError(ValueError):
    """Raised when a supplied public-key bundle is malformed or unsafe."""


def public_key_candidates(
    environ: Mapping[str, str] | None = None,
    *,
    bundle_root: Path | None = None,
) -> tuple[Path, ...]:
    values = environ if environ is not None else os.environ
    candidates: list[Path] = []
    explicit = str(values.get("KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_FILE", "")).strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    project_root = str(values.get("KOMI_PROJECT_ROOT", "")).strip()
    if project_root:
        candidates.append(
            Path(project_root).expanduser() / "runtime-config" / PUBLIC_KEYS_FILENAME
        )
    root = bundle_root
    if root is None and getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    if root is not None:
        candidates.append(root / "runtime-config" / PUBLIC_KEYS_FILENAME)
        candidates.append(root / PUBLIC_KEYS_FILENAME)
    return tuple(dict.fromkeys(path.resolve(strict=False) for path in candidates))


def _decode_ed25519_public_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not _BASE64URL_PATTERN.fullmatch(value)
    ):
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public key must be unpadded base64url"
        )
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public key is not valid base64url"
        ) from exc
    if len(decoded) != 32:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License Ed25519 public key must be 32 bytes"
        )
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != value:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public key is not canonical base64url"
        )
    return canonical


def _object_without_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise OfflineLicensePublicKeyConfigurationError(
                "Offline License public-key file contains duplicate fields"
            )
        result[name] = value
    return result


def parse_offline_license_public_keys(raw: bytes) -> dict[str, str]:
    if not raw or len(raw) > MAX_PUBLIC_KEYS_BYTES or b"\x00" in raw:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public-key file is empty or too large"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object_without_duplicate_fields
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public-key file is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public-key file has unexpected fields"
        )
    if payload.get("schema_version") != 1 or payload.get("algorithm") != "Ed25519":
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public-key contract is unsupported"
        )
    rows = payload.get("keys")
    if not isinstance(rows, list) or not rows:
        raise OfflineLicensePublicKeyConfigurationError(
            "Offline License public-key file contains no keys"
        )
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _KEY_FIELDS:
            raise OfflineLicensePublicKeyConfigurationError(
                "Offline License key entry has unexpected fields"
            )
        kid = row.get("kid")
        if not isinstance(kid, str) or not _KID_PATTERN.fullmatch(kid):
            raise OfflineLicensePublicKeyConfigurationError(
                "Offline License key id is invalid"
            )
        if kid in result:
            raise OfflineLicensePublicKeyConfigurationError(
                "Offline License key id is duplicated"
            )
        result[kid] = _decode_ed25519_public_key(row.get("public_key_base64url"))
    return result


def load_offline_license_public_keys(
    environ: Mapping[str, str] | None = None,
    *,
    bundle_root: Path | None = None,
) -> dict[str, str]:
    """Return the first configured public-key set, or an empty set if absent.

    Missing public keys disable Offline License import but do not block Online
    Registration.  A present but invalid file fails closed.
    """

    values = environ if environ is not None else os.environ
    explicit = str(values.get("KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_FILE", "")).strip()
    candidates = public_key_candidates(values, bundle_root=bundle_root)
    for index, candidate in enumerate(candidates):
        try:
            raw = candidate.read_bytes()
        except FileNotFoundError:
            if explicit and index == 0:
                raise OfflineLicensePublicKeyConfigurationError(
                    "Configured Offline License public-key file does not exist"
                ) from None
            continue
        except OSError as exc:
            raise OfflineLicensePublicKeyConfigurationError(
                "Offline License public-key file cannot be read"
            ) from exc
        return parse_offline_license_public_keys(raw)
    return {}
