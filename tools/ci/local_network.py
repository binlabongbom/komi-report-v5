"""Restrict Python test traffic to loopback; never probe customer printers."""

import ipaddress
import socket
import sys

_installed = False


def is_loopback_host(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


def local_only_network(event: str, args: tuple) -> None:
    if event in ("socket.connect", "socket.sendto", "socket.bind"):
        address = args[1]
        # AF_UNIX paths are local IPC, not printer or Internet endpoints.
        if not isinstance(address, tuple):
            return
        host = address[0]
    elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
        host = args[0]
        if host is None:
            return
    else:
        return
    if not is_loopback_host(host):
        raise PermissionError("Desktop regression permits loopback networking only")


def install() -> None:
    global _installed
    if _installed:
        return
    original_bind = socket.socket.bind

    def loopback_bind(sock: socket.socket, address):
        # Discovery fixtures bind wildcard client ports. Keep those sockets
        # local rather than exposing a CI listener on every network interface.
        if isinstance(address, tuple):
            host, *rest = address
            if sock.family == socket.AF_INET and host in ("", "0.0.0.0"):
                address = ("127.0.0.1", *rest)
            elif sock.family == socket.AF_INET6 and host in ("", "::"):
                address = ("::1", *rest)
        return original_bind(sock, address)

    socket.socket.bind = loopback_bind
    sys.addaudithook(local_only_network)
    _installed = True
