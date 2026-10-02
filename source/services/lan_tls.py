"""Per-install TLS material for the LAN report viewer.

Generated certificates encrypt LAN traffic without changing the OS trust store.
Customers may instead configure a certificate/key pair issued by their own PKI.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

TlsSource = Literal["generated", "customer"]


class LanTlsError(RuntimeError):
    """Raised when TLS material is missing, invalid, or unsafe to use."""


@dataclass(frozen=True)
class LanTlsMaterial:
    certificate_path: Path
    private_key_path: Path
    fingerprint_sha256: str
    source: TlsSource
    dns_names: tuple[str, ...]
    ip_addresses: tuple[str, ...]


def discover_primary_lan_ip() -> str:
    """Return the preferred local address without sending application data."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"


def _atomic_write(path: Path, data: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    try:
        os.chmod(temporary, mode)
    except OSError:
        pass
    temporary.replace(path)


def _local_identities(
    *, hostname: str | None = None, lan_ips: Iterable[str] | None = None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    actual_hostname = (hostname or socket.gethostname()).strip().lower()
    dns_names = {"localhost"}
    if actual_hostname and actual_hostname != "localhost":
        dns_names.add(actual_hostname)
    ip_addresses = {"127.0.0.1", "::1"}
    for value in lan_ips or ():
        try:
            ip_addresses.add(str(ipaddress.ip_address(value.strip())))
        except ValueError as err:
            raise LanTlsError("LAN IP สำหรับ certificate ไม่ถูกต้อง") from err
    return tuple(sorted(dns_names)), tuple(sorted(ip_addresses))


def _load_pair(certificate_path: Path, private_key_path: Path) -> tuple[x509.Certificate, object]:
    try:
        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as err:
        raise LanTlsError("อ่าน LAN HTTPS certificate/private key ไม่สำเร็จ") from err
    if certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ) != private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ):
        raise LanTlsError("LAN HTTPS certificate และ private key ไม่ใช่คู่เดียวกัน")
    now = datetime.now(UTC)
    if certificate.not_valid_before_utc > now or certificate.not_valid_after_utc <= now:
        raise LanTlsError("LAN HTTPS certificate อยู่นอกช่วงเวลาที่ใช้งานได้")
    return certificate, private_key


def _certificate_names(certificate: x509.Certificate) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        extension = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return (), ()
    dns_names = tuple(sorted(name.lower() for name in extension.get_values_for_type(x509.DNSName)))
    ip_addresses = tuple(sorted(str(value) for value in extension.get_values_for_type(x509.IPAddress)))
    return dns_names, ip_addresses


def _material(certificate_path: Path, private_key_path: Path, source: TlsSource) -> LanTlsMaterial:
    certificate, _ = _load_pair(certificate_path, private_key_path)
    dns_names, ip_addresses = _certificate_names(certificate)
    return LanTlsMaterial(
        certificate_path=certificate_path.resolve(),
        private_key_path=private_key_path.resolve(),
        fingerprint_sha256=hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest(),
        source=source,
        dns_names=dns_names,
        ip_addresses=ip_addresses,
    )


def validate_customer_certificate(certificate_path: Path, private_key_path: Path) -> LanTlsMaterial:
    """Validate an explicitly configured customer pair without modifying trust settings."""

    material = _material(certificate_path.expanduser(), private_key_path.expanduser(), "customer")
    if not material.dns_names and not material.ip_addresses:
        raise LanTlsError("Customer certificate ต้องมี Subject Alternative Name (SAN)")
    return material


def _generate_pair(
    certificate_path: Path,
    private_key_path: Path,
    *,
    dns_names: tuple[str, ...],
    ip_addresses: tuple[str, ...],
    client_auth: bool = False,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[-1])])
    san_values: list[x509.GeneralName] = [x509.DNSName(name) for name in dns_names]
    san_values.extend(x509.IPAddress(ipaddress.ip_address(value)) for value in ip_addresses)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH] +
            ([ExtendedKeyUsageOID.CLIENT_AUTH] if client_auth else [])), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    _atomic_write(
        private_key_path,
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        mode=0o600,
    )
    _atomic_write(certificate_path, certificate.public_bytes(serialization.Encoding.PEM), mode=0o644)


def ensure_generated_certificate(
    runtime_root: Path,
    *,
    hostname: str | None = None,
    lan_ips: Iterable[str] | None = None,
    client_auth: bool = False,
) -> LanTlsMaterial:
    """Create or safely rotate a per-install leaf certificate when local identities change."""

    runtime_root = runtime_root.expanduser().resolve()
    tls_root = runtime_root / "security" / "lan-tls"
    certificate_path = tls_root / "certificate.pem"
    private_key_path = tls_root / "private-key.pem"
    metadata_path = tls_root / "metadata.json"
    dns_names, ip_addresses = _local_identities(hostname=hostname, lan_ips=lan_ips)
    expected = {"dns_names": list(dns_names), "ip_addresses": list(ip_addresses)}
    if client_auth:
        expected['client_auth'] = True
    regenerate = True
    if certificate_path.is_file() and private_key_path.is_file() and metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            certificate, _ = _load_pair(certificate_path, private_key_path)
            regenerate = (
                metadata.get("dns_names") != expected["dns_names"]
                or metadata.get("ip_addresses") != expected["ip_addresses"]
                or bool(metadata.get('client_auth')) != client_auth
                or certificate.not_valid_after_utc <= datetime.now(UTC) + timedelta(days=30)
            )
        except (LanTlsError, OSError, json.JSONDecodeError, TypeError):
            regenerate = True
    if regenerate:
        _generate_pair(
            certificate_path,
            private_key_path,
            dns_names=dns_names,
            ip_addresses=ip_addresses,
            client_auth=client_auth,
        )
        _atomic_write(
            metadata_path,
            (json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
            mode=0o600,
        )
    return _material(certificate_path, private_key_path, "generated")


def resolve_lan_tls(
    runtime_root: Path,
    *,
    configured_certificate: str = "",
    configured_private_key: str = "",
    hostname: str | None = None,
    lan_ips: Iterable[str] | None = None,
) -> LanTlsMaterial:
    """Use a complete customer pair or fall back to the per-install certificate."""

    if bool(configured_certificate) != bool(configured_private_key):
        raise LanTlsError("Customer certificate config ต้องระบุ certificate และ private key ให้ครบคู่")
    if configured_certificate:
        return validate_customer_certificate(Path(configured_certificate), Path(configured_private_key))
    return ensure_generated_certificate(runtime_root, hostname=hostname, lan_ips=lan_ips)
