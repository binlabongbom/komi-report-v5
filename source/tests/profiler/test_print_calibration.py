from __future__ import annotations

import asyncio

from komi_snmp_profiler.models import ConnectionSettings, RawOidValue
from komi_snmp_profiler.print_calibration import run_print_calibration
from komi_snmp_profiler.system_print import PrintTestRequest


class SequenceCollector:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(self, settings: ConnectionSettings):
        self.calls += 1
        counter = 100 if self.calls == 1 else 103
        return [RawOidValue("1.3.6.1.4.1.18334.1", str(counter), "Counter32", counter)], []


class RecordingBackend:
    def __init__(self) -> None:
        self.events: list[str] = []

    def list_printers(self) -> list[str]:
        return ["KM-Lab"]

    def submit(self, request: PrintTestRequest) -> str:
        self.events.append(f"submit:{request.job_type}")
        return "KM-Lab-42"

    def wait_for_completion(self, printer: str, job_id: str, timeout: float = 180.0) -> None:
        self.events.append(f"wait:{job_id}")


def test_print_calibration_runs_before_print_wait_after_and_matches_pages() -> None:
    collector = SequenceCollector()
    backend = RecordingBackend()
    request = PrintTestRequest("KM-Lab", "A4", True, 3)
    result = asyncio.run(
        run_print_calibration(
            ConnectionSettings("10.0.0.5", "public"),
            collector,
            backend,
            request,
            settle_seconds=0,
        )
    )
    assert collector.calls == 2
    assert backend.events == ["submit:A4 Color", "wait:KM-Lab-42"]
    assert result.job_id == "KM-Lab-42"
    assert result.deltas[0].delta == 3
    assert result.deltas[0].matches_expected is True
