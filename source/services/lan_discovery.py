"""Small UDP discovery hints. No settings, secrets or authority cross broadcast.

Replies are used only as HTTPS probe targets. A nonce correlates responses with
one search; neither the nonce nor a reply establishes membership or TLS trust.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import secrets
import socket
import threading
import time

from services.web_port import validate_web_port

DISCOVERY_PORT = 37852
CONTRACT = "komi-discovery/v1"
MAX_DATAGRAM = 512
log = logging.getLogger(__name__)


def _decode(raw):
    if len(raw) > MAX_DATAGRAM:
        return None
    try:
        packet = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(packet, dict) or packet.get("contract") != CONTRACT:
        return None
    nonce = packet.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce):
        return None
    return packet


def _encode(packet):
    return json.dumps(packet, separators=(",", ":")).encode("ascii")


def _allowed_source(host, networks):
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return not (address.is_multicast or address.is_unspecified) and any(
        address in network and (network.prefixlen >= 31 or address not in (network.network_address, network.broadcast_address))
        for network in networks
    )


def discover(interfaces, *, timeout=1.2, port=DISCOVERY_PORT, targets=None):
    """Search all active directed broadcasts, bounded by one monotonic deadline.

    Explicit targets exist for isolated loopback tests. The normal caller only
    supplies OS-discovered local interfaces; reply-provided URLs are never used.
    """
    interfaces = list(interfaces)
    if not interfaces:
        return []
    if not 0 < timeout <= 10:
        raise ValueError("Invalid discovery timeout")
    networks = [network for _, network in interfaces]
    local = {str(address) for address, _ in interfaces}
    destinations = targets if targets is not None else sorted({str(n.broadcast_address) for n in networks if n.prefixlen < 31})
    nonce = secrets.token_hex(16)
    request = _encode({"contract": CONTRACT, "kind": "discover", "nonce": nonce})
    found = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        for host in destinations:
            try:
                sock.sendto(request, (host, port))
            except OSError:
                continue  # One unavailable adapter must not hide the others.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                raw, (host, _) = sock.recvfrom(MAX_DATAGRAM + 1)
            except socket.timeout:
                break
            if host in local or not _allowed_source(host, networks):
                continue
            packet = _decode(raw)
            if (packet is None or set(packet) != {"contract", "kind", "nonce", "https_port"}
                    or packet["kind"] != "reply" or packet["nonce"] != nonce
                    or type(packet["https_port"]) is not int):
                continue
            try:
                https_port = validate_web_port(packet["https_port"])
            except ValueError:
                continue
            found.add((host, https_port))
    return sorted(found)


class DiscoveryResponder:
    def __init__(self, networks, *, https_port, ready, bind_host="0.0.0.0", port=DISCOVERY_PORT):
        self.networks = networks if callable(networks) else lambda: tuple(networks)
        self.https_port = https_port
        self.ready = ready
        self.bind_host, self.port = bind_host, port
        self._stop = threading.Event()
        self._thread = None
        self._socket = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return True
        if not self.networks():
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No SO_REUSEADDR: duplicate Agent/Web processes cannot both answer.
            sock.bind((self.bind_host, self.port))
            sock.settimeout(0.25)
        except OSError:
            sock.close()
            log.warning("LAN discovery unavailable; use retry or manual IP")
            return False
        self.port = sock.getsockname()[1]
        self._socket = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="komi-lan-discovery", daemon=True)
        self._thread.start()
        return True

    def _run(self):
        window, count = time.monotonic(), 0
        sock = self._socket
        while not self._stop.is_set():
            try:
                raw, address = sock.recvfrom(MAX_DATAGRAM + 1)
            except socket.timeout:
                continue
            except OSError:
                break
            now = time.monotonic()
            if now - window >= 1:
                window, count = now, 0
            if count >= 8:
                continue
            count += 1
            if not _allowed_source(address[0], self.networks()):
                continue
            packet = _decode(raw)
            if packet is None or set(packet) != {"contract", "kind", "nonce"} or packet["kind"] != "discover":
                continue
            try:
                if not self.ready():
                    continue
                port = validate_web_port(self.https_port())
                sock.sendto(_encode({"contract": CONTRACT, "kind": "reply", "nonce": packet["nonce"],
                                     "https_port": port}), address)
            except (OSError, ValueError):
                log.debug("LAN discovery reply unavailable", exc_info=True)

    def stop(self):
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._socket = None
        self._thread = None
