"""Offline edition checks executed by the packaged startup smoke test."""
from __future__ import annotations

import os
from types import SimpleNamespace

from services.build_edition import BUILD_EDITION, is_offline_edition


def validate_edition() -> dict[str, object]:
    result: dict[str, object] = {"edition": BUILD_EDITION, "host_transport_calls": 0}
    if not is_offline_edition():
        result["offline_checks"] = "not-applicable"
        return result

    from services.v5_2_client import V52ContractClient, V52RuntimeConfig
    from services.v5_2_runtime import V52RuntimeCoordinator

    class ForbiddenTransport:
        def request(self, *args, **kwargs):
            raise AssertionError("Offline edition attempted Host transport")

    previous = os.environ.get("KOMI_BUILD_EDITION")
    try:
        os.environ["KOMI_BUILD_EDITION"] = "normal"
        if not is_offline_edition():
            raise AssertionError("Environment changed frozen edition")
        client = V52ContractClient(
            V52RuntimeConfig("https://example.invalid", "production"),
            transport=ForbiddenTransport(),
        )
        for event_type in ("register", "status", "meter"):
            response = client.send(SimpleNamespace(event_type=event_type))
            if response.success or response.error_code != "offline_edition":
                raise AssertionError(f"Offline guard failed for {event_type}")
        try:
            V52RuntimeCoordinator.set_mode(SimpleNamespace(), "online")
        except ValueError:
            pass
        else:
            raise AssertionError("Offline runtime accepted online mode")
    finally:
        if previous is None:
            os.environ.pop("KOMI_BUILD_EDITION", None)
        else:
            os.environ["KOMI_BUILD_EDITION"] = previous
    result["offline_checks"] = "passed"
    return result
