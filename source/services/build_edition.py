"""Immutable build-time product edition.

Only the packaging pipeline replaces ``BUILD_EDITION`` in the staged payload.
The normal edition registers with the KOMI Host.  The offline edition is an
air-gapped installation: it never contacts the Host and local collection is
enabled as soon as first-run setup has been completed.

No environment variable or customer setting can switch editions at runtime.
"""
BUILD_EDITION = "normal"


def is_offline_edition() -> bool:
    if BUILD_EDITION not in {"normal", "offline"}:
        raise RuntimeError("Invalid KOMI build edition")
    return BUILD_EDITION == "offline"


def edition_label() -> str:
    """Return the stable user-facing edition name for diagnostics and UI."""

    return "Offline Installation" if is_offline_edition() else "Online Registration"
