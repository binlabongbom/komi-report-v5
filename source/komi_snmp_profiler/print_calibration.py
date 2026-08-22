from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .calibration import compare_snapshots
from .connectors import AccountCounterConnector
from .models import ConnectionSettings, CounterDelta, DeviceSnapshot
from .service import ProfilerService
from .snmp_client import SnmpCollector
from .system_print import PrintBackend, PrintTestRequest


@dataclass(frozen=True)
class PrintCalibrationResult:
    request: PrintTestRequest
    job_id: str
    before: DeviceSnapshot
    after: DeviceSnapshot
    deltas: tuple[CounterDelta, ...]


async def run_print_calibration(
    settings: ConnectionSettings,
    collector: SnmpCollector,
    backend: PrintBackend,
    request: PrintTestRequest,
    *,
    counter_connector: AccountCounterConnector | None = None,
    settle_seconds: float = 3.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> PrintCalibrationResult:
    if settle_seconds < 0:
        raise ValueError("settle time ต้องไม่ติดลบ")
    service = ProfilerService(collector, counter_connector)
    before = await service.scan(settings)
    job_id = backend.submit(request)
    backend.wait_for_completion(request.printer, job_id)
    sleeper(settle_seconds)
    after = await service.scan(settings)
    deltas = compare_snapshots(before, after, request.pages)
    return PrintCalibrationResult(
        request=request,
        job_id=job_id,
        before=before,
        after=after,
        deltas=tuple(deltas),
    )
