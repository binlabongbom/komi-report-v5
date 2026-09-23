"""Verified TLS for public Host APIs, isolated from LAN peer trust/pinning.

On Windows use CryptoAPI chain building, including OS-managed CA retrieval,
instead of copying the certificates currently cached in Windows into OpenSSL.
Never patch global SSL defaults or learn trust anchors from a remote endpoint.
"""
from __future__ import annotations

import ssl
import sys


def host_tls_backend() -> str:
    return "windows-cryptoapi" if sys.platform == "win32" else "openssl-system"


def create_host_tls_context():
    if sys.platform == "win32":
        import truststore

        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    else:
        context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    # Supplying an explicit context to urllib otherwise omits its HTTP/1.1 ALPN.
    context.set_alpn_protocols(["http/1.1"])
    return context
