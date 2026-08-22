from __future__ import annotations

import asyncio
import threading

import pytest

from komi_snmp_profiler.models import ConnectionSettings, ScanMode
from komi_snmp_profiler.snmp_client import DEEP_ROOTS, DEFAULT_ROOTS, PySnmpCollector, SnmpScanCancelled


def test_quick_and_deep_modes_choose_different_roots() -> None:
    quick = PySnmpCollector(scan_mode=ScanMode.QUICK)
    deep = PySnmpCollector(scan_mode=ScanMode.DEEP)
    assert quick.roots == DEFAULT_ROOTS
    assert deep.roots == DEEP_ROOTS
    assert DEEP_ROOTS[0] == "1.3.6.1"
    assert "1.3.6.1.2.1.43" in DEEP_ROOTS
    assert "1.3.6.1.4.1.18334" in DEEP_ROOTS


def test_explicit_roots_override_mode_defaults() -> None:
    collector = PySnmpCollector(("1.2.3",), scan_mode=ScanMode.DEEP)
    assert collector.roots == ("1.2.3",)


def test_cancelled_scan_stops_before_sending_walk() -> None:
    cancelled = threading.Event()
    cancelled.set()
    collector = PySnmpCollector(cancel_event=cancelled)
    settings = ConnectionSettings("127.0.0.1", "public", timeout=0.1, retries=0)
    with pytest.raises(SnmpScanCancelled):
        asyncio.run(collector.collect(settings))
