from __future__ import annotations

import asyncio

from .connectors import AccountCounterConnector, WebConnectionError
from .counter_analyzer import analyze_counter_candidates
from .models import ConnectionSettings, DeviceSnapshot, ScanMode
from .oid_dictionary import interpret_all
from .snmp_client import SnmpCollector
from .table_decoder import decode_tables


class ProfilerService:
    def __init__(self, collector: SnmpCollector, counter_connector: AccountCounterConnector | None = None) -> None:
        self.collector = collector
        self.counter_connector = counter_connector

    async def scan(self, settings: ConnectionSettings) -> DeviceSnapshot:
        raw_values, warnings = await self.collector.collect(settings)
        web_counters = []
        if self.counter_connector is not None:
            try:
                web_counters = await asyncio.to_thread(self.counter_connector.collect, settings.host)
            except WebConnectionError as err:
                warnings.append(str(err))
        return DeviceSnapshot.create(
            settings.host,
            interpret_all(raw_values),
            warnings,
            scan_mode=getattr(self.collector, "scan_mode", ScanMode.QUICK),
            roots_scanned=getattr(self.collector, "roots", ()),
            entities=decode_tables(raw_values),
            counter_candidates=analyze_counter_candidates(raw_values),
            web_counters=web_counters,
        )
