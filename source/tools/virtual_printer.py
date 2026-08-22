#!/usr/bin/env python3
"""LAN-visible virtual bizhub used by the real KOMI Setup Wizard test lab.

The simulator answers the same read-only boundaries used by production setup:
SNMP v2c Printer-MIB on UDP/161 and Web Connection-compatible HTTPS on
TCP/443.  It never injects rows into the Wizard and never talks to a real MFP.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import ipaddress
import json
import ssl
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass(frozen=True)
class VirtualPrinterProfile:
    model: str = "KONICA MINOLTA bizhub C450i Virtual"
    serial: str = "KOMI-DEMO-001"
    total: int = 125_430
    color: int = 38_210
    black: int = 87_220


def _total_payload(profile: VirtualPrinterProfile) -> dict[str, object]:
    return {
        "MFP": {
            "Result": {"ResultInfo": "Ack"},
            "UserCounterInfo": {
                "TotalCounterList": {
                    "TotalCounter": [{"Type": "Total", "Count": str(profile.total)}]
                },
                "PrintCounterList": {
                    "PrintCounter": [
                        {"Type": "FullColor", "Count": str(profile.color)},
                        {"Type": "Black", "Count": str(profile.black)},
                        {"Type": "Total", "Count": str(profile.total)},
                    ]
                },
            },
        }
    }


def _handler(profile: VirtualPrinterProfile, *, verbose: bool = False):
    class VirtualPrinterHandler(BaseHTTPRequestHandler):
        server_version = "KOMI-Virtual-bizhub/1.0"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict[str, object]) -> None:
            self._send(
                200,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                "application/json",
            )

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            if self.path == "/wcd/index.html":
                self._send(200, b"KOMI Virtual bizhub", "text/html; charset=utf-8")
                return
            if self.path == "/wcd/api/AppReqGetCustomData/_A-00-00001":
                self._json(
                    {
                        "MFP": {
                            "LoginMode": "PublicUser",
                            "Token": "KOMI-DEMO",
                            "AuthSetting": {
                                "AuthMode": {"AuthType": "None"},
                                "TrackMode": {"TrackType": "None"},
                            },
                        }
                    }
                )
                return
            # Deliberately reject Administrator preparation. MeterReader then
            # follows its production public-counter fallback exactly once.
            self._send(404, b"not available in virtual public mode", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length:
                self.rfile.read(content_length)
            if self.path == "/wcd/api/AppReqGetCounterInfo/_Total":
                self._json(_total_payload(profile))
                return
            self._send(404, b"not available in virtual public mode", "text/plain")

        def log_message(self, format: str, *args: object) -> None:
            if verbose:
                super().log_message(format, *args)

    return VirtualPrinterHandler


class VirtualPrinterService:
    """Own the SNMP and HTTPS servers so tests and the Setup Lab can stop cleanly."""

    def __init__(
        self,
        *,
        bind_host: str = "0.0.0.0",
        snmp_port: int = 161,
        https_port: int = 443,
        community: str = "public",
        profile: VirtualPrinterProfile | None = None,
        verbose: bool = False,
    ) -> None:
        self.bind_host = bind_host
        self.snmp_port = snmp_port
        self.https_port = https_port
        self.community = community
        self.profile = profile or VirtualPrinterProfile()
        self.verbose = verbose
        self._snmp_engine = None
        self._snmp_loop: asyncio.AbstractEventLoop | None = None
        self._snmp_thread: threading.Thread | None = None
        self._https_server: ThreadingHTTPServer | None = None
        self._https_thread: threading.Thread | None = None
        self._certificate_dir: tempfile.TemporaryDirectory[str] | None = None

    @staticmethod
    def _export_scalar(mib_builder, name: str, base_oid: tuple[int, ...], suffix: tuple[int, ...], value) -> None:
        MibScalar, MibScalarInstance = mib_builder.import_symbols(
            "SNMPv2-SMI", "MibScalar", "MibScalarInstance"
        )
        scalar = MibScalar(base_oid, value.clone()).setMaxAccess("read-only")
        instance = MibScalarInstance(base_oid, suffix, value.clone())
        mib_builder.export_symbols(
            "KOMI-VIRTUAL-PRINTER-MIB",
            **{name: scalar, f"{name}Instance": instance},
        )

    def _build_snmp_engine(self):
        from pysnmp.carrier.asyncio.dgram import udp
        from pysnmp.entity import config, engine
        from pysnmp.entity.rfc3413 import cmdrsp, context

        try:
            previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            previous_loop = None
        self._snmp_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._snmp_loop)
        try:
            snmp_engine = engine.SnmpEngine()
            config.add_transport(
                snmp_engine,
                udp.DOMAIN_NAME,
                udp.UdpTransport().open_server_mode((self.bind_host, self.snmp_port)),
            )
        finally:
            asyncio.set_event_loop(previous_loop)
        security_name = "komi-virtual-area"
        config.add_v1_system(
            snmp_engine,
            security_name,
            self.community,
        )
        config.add_vacm_user(
            snmp_engine,
            2,
            security_name,
            "noAuthNoPriv",
            readSubTree=(1, 3, 6),
        )
        snmp_context = context.SnmpContext(snmp_engine)
        mib_builder = snmp_context.get_mib_instrum(b"").get_mib_builder()
        (Integer32,) = mib_builder.import_symbols("SNMPv2-SMI", "Integer32")
        (OctetString,) = mib_builder.import_symbols("ASN1", "OctetString")
        self._export_scalar(
            mib_builder,
            "markerLifeCount",
            (1, 3, 6, 1, 2, 1, 43, 10, 2, 1, 4, 1),
            (1,),
            Integer32(self.profile.total),
        )
        self._export_scalar(
            mib_builder,
            "deviceModel",
            (1, 3, 6, 1, 2, 1, 25, 3, 2, 1, 3),
            (1,),
            OctetString(self.profile.model),
        )
        self._export_scalar(
            mib_builder,
            "deviceSerial",
            (1, 3, 6, 1, 2, 1, 43, 5, 1, 1, 17),
            (1,),
            OctetString(self.profile.serial),
        )
        cmdrsp.GetCommandResponder(snmp_engine, snmp_context)
        cmdrsp.NextCommandResponder(snmp_engine, snmp_context)
        cmdrsp.BulkCommandResponder(snmp_engine, snmp_context)
        return snmp_engine

    def start(self) -> None:
        if self._snmp_thread is not None or self._https_thread is not None:
            return
        try:
            self._snmp_engine = self._build_snmp_engine()
            self._snmp_engine.transport_dispatcher.job_started(1)
            self._snmp_thread = threading.Thread(
                target=self._snmp_engine.transport_dispatcher.run_dispatcher,
                name="komi-virtual-printer-snmp",
                daemon=True,
            )
            self._snmp_thread.start()

            cert_path, key_path = self._create_ephemeral_certificate()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            self._https_server = ThreadingHTTPServer(
                (self.bind_host, self.https_port),
                _handler(self.profile, verbose=self.verbose),
            )
            self._https_server.socket = context.wrap_socket(
                self._https_server.socket, server_side=True
            )
            self._https_thread = threading.Thread(
                target=self._https_server.serve_forever,
                name="komi-virtual-printer-https",
                daemon=True,
            )
            self._https_thread.start()
        except Exception:
            self.stop()
            raise

    def _create_ephemeral_certificate(self) -> tuple[Path, Path]:
        """Create a disposable local TLS identity; no reusable private key enters source control."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        self._certificate_dir = tempfile.TemporaryDirectory(prefix="komi-virtual-printer-tls-")
        directory = Path(self._certificate_dir.name)
        key_path = directory / "key.pem"
        cert_path = directory / "cert.pem"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "KOMI Virtual Printer")]
        )
        now = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=7))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return cert_path, key_path

    def stop(self) -> None:
        if self._https_server is not None:
            self._https_server.shutdown()
            self._https_server.server_close()
        if self._snmp_engine is not None and self._snmp_engine.transport_dispatcher is not None:
            self._snmp_engine.transport_dispatcher.job_finished(1)
            self._snmp_engine.transport_dispatcher.close_dispatcher()
        for thread in (self._https_thread, self._snmp_thread):
            if thread is not None:
                thread.join(timeout=3)
        self._https_server = None
        self._https_thread = None
        self._snmp_engine = None
        self._snmp_thread = None
        if self._snmp_loop is not None and not self._snmp_loop.is_closed():
            self._snmp_loop.close()
        self._snmp_loop = None
        if self._certificate_dir is not None:
            self._certificate_dir.cleanup()
            self._certificate_dir = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--snmp-port", type=int, default=161)
    parser.add_argument("--https-port", type=int, default=443)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    service = VirtualPrinterService(
        bind_host=args.bind,
        snmp_port=args.snmp_port,
        https_port=args.https_port,
        verbose=args.verbose,
    )
    try:
        service.start()
    except OSError as exc:
        parser.error(f"เปิด Virtual Printer ports ไม่สำเร็จ: {exc}")
    print(
        "KOMI Virtual Printer พร้อมใช้งาน · "
        f"SNMP {args.bind}:{args.snmp_port}/UDP · HTTPS {args.bind}:{args.https_port}/TCP",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
