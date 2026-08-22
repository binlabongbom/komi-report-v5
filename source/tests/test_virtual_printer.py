from __future__ import annotations

import hashlib
import socket
import ssl

import pytest

from komi_snmp_profiler.connectors import TlsPolicy, WebConnectionCounterConnector, WebConnectionError
from komi_snmp_profiler.credential_store import SessionCredentialStore
from komi_snmp_profiler.meter import MeterReader
from services.device_config import DeviceConfig
from services.snmp_probe import SnmpTotalProbe
from tools.setup_lab import lab_network
from tools.virtual_printer import VirtualPrinterProfile, VirtualPrinterService
from v5_pages import DeviceTestWorker, NetworkDiscoveryWorker


def _free_port(*, udp: bool = False) -> int:
    kind = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_virtual_printer_answers_real_snmp_and_web_connection_clients():
    snmp_port = _free_port(udp=True)
    https_port = _free_port()
    profile = VirtualPrinterProfile(
        model="KONICA MINOLTA bizhub C450i Virtual",
        serial="KOMI-DEMO-001",
        total=125430,
        color=38210,
        black=87220,
    )
    with VirtualPrinterService(
        bind_host="127.0.0.1",
        snmp_port=snmp_port,
        https_port=https_port,
        profile=profile,
    ):
        snmp = SnmpTotalProbe(timeout=1.0, retries=0, port=snmp_port).read("127.0.0.1")
        host = f"127.0.0.1:{https_port}"
        credentials = SessionCredentialStore()
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", https_port), timeout=2) as raw:
            with context.wrap_socket(raw, server_hostname="127.0.0.1") as secured:
                fingerprint = hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest()
        public_connector = WebConnectionCounterConnector(
            tls_policy=TlsPolicy(mode="fingerprint", fingerprint_sha256=fingerprint)
        )
        web = MeterReader(credentials, public_connector=public_connector).read(host)
        wrong_pin = WebConnectionCounterConnector(
            tls_policy=TlsPolicy(mode="fingerprint", fingerprint_sha256="00" * 32)
        )
        with pytest.raises(WebConnectionError, match="fingerprint"):
            wrong_pin.collect_result(host)
        discovered = NetworkDiscoveryWorker(
            ["127.0.0.1"], snmp_port=snmp_port
        )._probe("127.0.0.1")
        tested = DeviceTestWorker(
            [DeviceConfig(0, "Virtual Printer", "127.0.0.1")],
            snmp_port=snmp_port,
            web_port=https_port,
        )._test(DeviceConfig(0, "Virtual Printer", "127.0.0.1"))

    assert snmp.model == profile.model
    assert snmp.serial == profile.serial
    assert snmp.total == profile.total
    assert any(counter.canonical_field == "counter.total.total" for counter in web.counters)
    assert any(counter.count == profile.total for counter in web.counters)
    assert web.source == "web_connection_public"
    assert discovered == {
        "host": "127.0.0.1",
        "model": profile.model,
        "serial": profile.serial,
        "total": profile.total,
    }
    assert tested["online"] is True
    assert tested["web_ok"] is True
    assert tested["model"] == profile.model


def test_setup_lab_uses_standard_windows_ports_and_unprivileged_local_ports_elsewhere():
    assert lab_network("win32").snmp_port == 161
    assert lab_network("win32").web_port == 443
    assert lab_network("win32").discovery_hosts is None
    assert lab_network("darwin").snmp_port == 1161
    assert lab_network("darwin").web_port == 8443
    assert lab_network("darwin").discovery_hosts == ["127.0.0.1"]
