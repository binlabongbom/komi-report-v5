"""Exercise real TLS handshakes without changing OS trust or contacting a Host."""

from __future__ import annotations

import ipaddress
import ssl
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


from services import v5_2_client
from urllib.request import build_opener, HTTPSHandler

@pytest.fixture
def tls_server(tmp_path, request):
    scenario = request.param
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KOMI test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    names = (
        [x509.DNSName("wrong.example.invalid")]
        if scenario == "wrong_hostname"
        else [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TLS test server")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=20))
        .not_valid_after(now + timedelta(days=-1 if scenario == "expired" else 10))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server-key.pem"
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    received = []

    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except ConnectionResetError:
                # A client rejecting our test certificate closes before HTTP.
                pass

        def do_HEAD(self):
            received.append(self.command)
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            received.append(self.command)
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args):
            pass

    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    original_factory = ssl.create_default_context

    def context_factory():
        context = original_factory()
        if scenario != "untrusted":
            # Test-only trust in this context, never install a root into Windows.
            context.load_verify_locations(cadata=ca.public_bytes(serialization.Encoding.PEM).decode("ascii"))
        return context
    try:
        yield SimpleNamespace(
            url=f"https://127.0.0.1:{server.server_port}",
            context_factory=context_factory, received=received, valid=scenario == "valid",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("tls_server", ["valid", "expired", "wrong_hostname", "untrusted"], indirect=True)
@pytest.mark.parametrize("endpoint", ["status", "meter-observations"])
def test_monitoring_tls_handshake(tls_server, endpoint, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    transport = v5_2_client.UrllibV52Transport()
    # Inject only test CA trust; retain the production urllib transport and
    # certificate/hostname verification. No OS root store changes.
    transport._opener = build_opener(transport._NoRedirect(), HTTPSHandler(context=tls_server.context_factory()))
    kwargs = dict(url=tls_server.url + "/api/v1/installations/" + endpoint,
                  headers={}, body=b"{}", timeout=3)
    if tls_server.valid:
        assert transport.request(**kwargs).status == 200
        assert tls_server.received == ["POST"]
    else:
        with pytest.raises(v5_2_client.V52NetworkError) as raised:
            transport.request(**kwargs)
        assert raised.value.code == "tls_certificate_error"
        assert not tls_server.received
