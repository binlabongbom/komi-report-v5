"""Build-time edition; Offline cannot be enabled for Host traffic by config/env.

Only the packaging pipeline replaces BUILD_EDITION in the staged payload.
Offline activation still requires a valid Host-signed license.
"""
BUILD_EDITION = "normal"


def is_offline_edition() -> bool:
    if BUILD_EDITION not in {"normal", "offline"}:
        raise RuntimeError("Invalid KOMI build edition")
    return BUILD_EDITION == "offline"
