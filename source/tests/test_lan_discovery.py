import asyncio
import ipaddress
import json
import socket
import threading

import pytest

from services import lan_discovery as lan
from services import secondary_setup as setup


NETWORK = ipaddress.IPv4Network("127.0.0.0/8")
INTERFACES = [(ipaddress.IPv4Address("127.0.0.2"), NETWORK)]


def responder(**kwargs):
    instance = lan.DiscoveryResponder([NETWORK], https_port=lambda: 3443, ready=lambda: True,
                                      bind_host="127.0.0.1", port=0, **kwargs)
    assert instance.start()
    return instance


def test_loopback_discovery_returns_only_source_and_https_port_and_stops():
    server = responder()
    thread = server._thread
    try:
        assert server.start()  # Repeated lifecycle start does not add a listener.
        assert server._thread is thread
        assert lan.discover(INTERFACES, timeout=.15, port=server.port, targets=["127.0.0.1"]) == [("127.0.0.1", 3443)]
    finally:
        server.stop()
    assert not thread.is_alive()
    server.stop()


def test_response_contains_no_company_serial_setting_or_identity():
    server = responder()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(1)
            client.sendto(lan._encode({"contract": lan.CONTRACT, "kind": "discover", "nonce": "a" * 32}),
                          ("127.0.0.1", server.port))
            raw, _ = client.recvfrom(1024)
        assert json.loads(raw) == {"contract": lan.CONTRACT, "kind": "reply", "nonce": "a" * 32, "https_port": 3443}
        assert len(raw) <= lan.MAX_DATAGRAM
    finally:
        server.stop()


def test_busy_udp_port_is_nonfatal_and_does_not_replace_existing_listener():
    first = responder()
    second = lan.DiscoveryResponder([NETWORK], https_port=lambda: 3000, ready=lambda: True,
                                   bind_host="127.0.0.1", port=first.port)
    try:
        assert second.start() is False
        assert lan.discover(INTERFACES, timeout=.15, port=first.port, targets=["127.0.0.1"]) == [("127.0.0.1", 3443)]
    finally:
        first.stop()
        second.stop()


@pytest.mark.parametrize("packet", [b"not json", b"x" * 513, b"[]",
    lan._encode({"contract": lan.CONTRACT, "kind": "discover", "nonce": "wrong"}),
    lan._encode({"contract": lan.CONTRACT, "kind": "discover", "nonce": "b" * 32, "settings": {}})])
def test_invalid_or_oversized_requests_are_ignored(packet):
    server = responder()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(.1)
            client.sendto(packet, ("127.0.0.1", server.port))
            with pytest.raises(socket.timeout):
                client.recvfrom(1024)
    finally:
        server.stop()


def test_wrong_nonce_unsolicited_and_nonlocal_replies_are_not_discovery():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(1)
        def answer():
            _, address = sock.recvfrom(1024)
            sock.sendto(lan._encode({"contract": lan.CONTRACT, "kind": "reply", "nonce": "f" * 32, "https_port": 3443}), address)
        worker = threading.Thread(target=answer)
        worker.start()
        assert lan.discover(INTERFACES, timeout=.15, port=sock.getsockname()[1], targets=["127.0.0.1"]) == []
        worker.join(timeout=1)
    assert not lan._allowed_source("192.0.2.1", [NETWORK])
    assert not lan._allowed_source("224.0.0.1", [NETWORK])


def test_unready_and_disconnected_network_does_not_answer():
    server = responder()
    try:
        server.ready = lambda: False
        assert lan.discover(INTERFACES, timeout=.1, port=server.port, targets=["127.0.0.1"]) == []
        server.ready = lambda: True
        server.networks = lambda: []
        assert lan.discover(INTERFACES, timeout=.1, port=server.port, targets=["127.0.0.1"]) == []
    finally:
        server.stop()


def test_broadcast_targets_are_https_probed_on_the_advertised_port(monkeypatch):
    monkeypatch.setattr(setup, "_active_ipv4_subnets", lambda: INTERFACES)
    monkeypatch.setattr(lan, "discover", lambda *_: [("192.0.2.20", 3443)])
    calls = []
    def probe(self, host):
        calls.append((host, self.port))
        return setup.SecondaryPeerCandidate(f"https://{host}:{self.port}", "Synthetic", 1, "test", "a" * 64)
    monkeypatch.setattr(setup.SecondaryPeerClient, "discover_one", probe)
    monkeypatch.setattr(setup, "local_ipv4_hosts", lambda: pytest.fail("No scan needed after verified broadcast candidate"))
    assert setup.SecondaryPeerClient().discover_lan()[0].base_url == "https://192.0.2.20:3443"
    assert calls == [("192.0.2.20", 3443)]


@pytest.mark.parametrize("failure", ["blocked", "no_reply", "https_failed"])
def test_missing_or_unverified_broadcast_uses_existing_scan(monkeypatch, failure):
    monkeypatch.setattr(setup, "_active_ipv4_subnets", lambda: INTERFACES)
    def broadcast(*_args):
        if failure == "blocked":
            raise OSError("synthetic blocked socket")
        return [("192.0.2.20", 3443)] if failure == "https_failed" else []
    monkeypatch.setattr(lan, "discover", broadcast)
    monkeypatch.setattr(setup.SecondaryPeerClient, "discover_one", lambda *_: None)
    monkeypatch.setattr(setup, "local_ipv4_hosts", lambda: ["192.0.2.30"])
    monkeypatch.setattr(setup.SecondaryPeerClient, "discover", lambda self, hosts: list(hosts))
    assert setup.SecondaryPeerClient().discover_lan() == ["192.0.2.30"]


def test_api_owns_and_stops_responder_with_its_lifespan(monkeypatch):
    import database
    import web_api
    from services.device_config import DeviceConfig, DeviceConfigRepository
    database.set_cfg("company_name", "Synthetic")
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Synthetic", "192.0.2.10")])
    calls = []
    class FakeResponder:
        def __init__(self, networks, *, https_port, ready):
            assert https_port() == "3443"
            assert ready() is True
        def start(self):
            calls.append("start")
        def stop(self):
            calls.append("stop")
    monkeypatch.setattr(lan, "DiscoveryResponder", FakeResponder)
    monkeypatch.delenv("KOMI_DISCOVERY_DISABLED", raising=False)
    monkeypatch.setenv("KOMI_WEB_PORT", "3443")
    async def run():
        async with web_api.lifespan(web_api.app):
            assert calls == ["start"]
    asyncio.run(run())
    assert calls == ["start", "stop"]
