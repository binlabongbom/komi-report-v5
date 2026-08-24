"""Provision the packaged Registration bootstrap into the platform OS vault.

The packaged value is deliberately treated as a limited public bootstrap
identifier, not an administrator secret.  The API must exchange it for a
scoped per-installation token and must never grant dashboard, delete, update,
or remote-command authority to this value.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from services.registration_policy import RegistrationRuntimePolicy
from services.registration_vault import (
    RegistrationSecretStore,
    platform_registration_secret_store,
)

BUNDLED_BOOTSTRAP_FILENAME = "komi-registration-bootstrap.dat"
LEGACY_KEYRING_SERVICE = "com.konicaminolta.komi-report.registration"
LEGACY_KEYRING_ACCOUNT = "bootstrap-key"
MAX_BOOTSTRAP_BYTES = 4096


def _bundled_candidates(
    environ: dict[str, str],
    *,
    bundle_root: Path | None = None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    explicit = environ.get("KOMI_REGISTRATION_BOOTSTRAP_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    project_root = environ.get("KOMI_PROJECT_ROOT", "").strip()
    if project_root:
        candidates.append(
            Path(project_root).expanduser()
            / "runtime-config"
            / BUNDLED_BOOTSTRAP_FILENAME
        )
    root = bundle_root
    if root is None and getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    if root is not None:
        candidates.append(root / "runtime-config" / BUNDLED_BOOTSTRAP_FILENAME)
        candidates.append(root / BUNDLED_BOOTSTRAP_FILENAME)
    return tuple(dict.fromkeys(path.resolve(strict=False) for path in candidates))


def _read_packaged_value(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > MAX_BOOTSTRAP_BYTES or b"\x00" in raw:
        return None
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return value or None


def _load_legacy_keyring_value() -> str | None:
    """Migrate the already tested macOS bootstrap without exposing its value."""

    try:
        import keyring

        value = keyring.get_password(LEGACY_KEYRING_SERVICE, LEGACY_KEYRING_ACCOUNT)
    except Exception:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def provision_registration_bootstrap(
    policy: RegistrationRuntimePolicy | None,
    *,
    vault: RegistrationSecretStore | None = None,
    environ: dict[str, str] | None = None,
    bundle_root: Path | None = None,
    legacy_loader: Callable[[], str | None] = _load_legacy_keyring_value,
) -> str:
    """Provision once and return a non-secret state label.

    No secret value or path is returned or logged.  Existing OS-vault content
    always wins, so an installer upgrade cannot silently rotate credentials.
    """

    if policy is None or policy.bootstrap_mode != "vault_header":
        return "not-required"
    store = vault or platform_registration_secret_store()
    if store.load(policy.bootstrap_ref):
        return "already-provisioned"
    values = environ if environ is not None else os.environ
    secret = None
    for candidate in _bundled_candidates(values, bundle_root=bundle_root):
        secret = _read_packaged_value(candidate)
        if secret:
            break
    if not secret:
        secret = legacy_loader()
    if not secret:
        return "bootstrap-unavailable"
    store.save(policy.bootstrap_ref, secret)
    return "provisioned"
