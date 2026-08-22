from __future__ import annotations

import hashlib
import ipaddress
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from services.lan_tls import LanTlsError, ensure_generated_certificate, resolve_lan_tls


def test_generated_certificate_has_localhost_hostname_and_lan_ip_sans(tmp_path):
    material = ensure_generated_certificate(
        tmp_path,
        hostname="komi-host",
        lan_ips=["192.0.2.40"],
    )

    assert material.source == "generated"
    assert material.dns_names == ("komi-host", "localhost")
    assert {"127.0.0.1", "192.0.2.40", "::1"}.issubset(material.ip_addresses)
    assert len(material.fingerprint_sha256) == 64
    assert hashlib.sha256(material.certificate_path.read_bytes()).hexdigest() != material.fingerprint_sha256
    assert material.private_key_path.stat().st_mode & 0o077 == 0


def test_generated_certificate_rotates_only_when_identity_changes(tmp_path):
    first = ensure_generated_certificate(tmp_path, hostname="komi-host", lan_ips=["192.0.2.40"])
    first_fingerprint = first.fingerprint_sha256

    unchanged = ensure_generated_certificate(tmp_path, hostname="komi-host", lan_ips=["192.0.2.40"])
    rotated = ensure_generated_certificate(tmp_path, hostname="komi-host", lan_ips=["192.0.2.41"])

    assert unchanged.fingerprint_sha256 == first_fingerprint
    assert rotated.fingerprint_sha256 != first_fingerprint
    assert "192.0.2.41" in rotated.ip_addresses


def test_customer_certificate_requires_a_matching_pair_and_san(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "komi.example")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("komi.example"), x509.IPAddress(ipaddress.ip_address("192.0.2.50"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = tmp_path / "customer.pem"
    key_path = tmp_path / "customer-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        other_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    with pytest.raises(LanTlsError, match="ไม่ใช่คู่เดียวกัน"):
        resolve_lan_tls(
            tmp_path / "runtime",
            configured_certificate=str(certificate_path),
            configured_private_key=str(key_path),
        )

    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    material = resolve_lan_tls(
        tmp_path / "runtime",
        configured_certificate=str(certificate_path),
        configured_private_key=str(key_path),
    )

    assert material.source == "customer"
    assert material.dns_names == ("komi.example",)
    assert material.ip_addresses == ("192.0.2.50",)


def test_partial_customer_certificate_config_fails_closed(tmp_path):
    with pytest.raises(LanTlsError, match="ให้ครบคู่"):
        resolve_lan_tls(tmp_path, configured_certificate=str(tmp_path / "cert.pem"))
