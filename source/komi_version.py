"""Canonical runtime version authority for new KOMI Report builds."""

APP_VERSION = "5.2.11"


def require_v5_2(version: str = APP_VERSION) -> str:
    """Fail closed when a new-build caller is not using the V5.2 line."""

    if not version.startswith("5.2."):
        raise RuntimeError("new KOMI Report builds require version 5.2.x")
    return version
