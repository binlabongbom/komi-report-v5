"""LAN setup handoff used when a second KOMI Desktop joins a customer site.

The handoff is deliberately narrower than a database backup.  A Secondary
receives only the customer-visible setup required to rebuild its own local
database.  Printer credentials, registration secrets, usage history and logs
never cross the LAN through this contract.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import ssl
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface

from config import PACKAGE_VERSION
from database import get_cfg
from services.device_config import DeviceConfigRepository
from services.peer_sync_authorization import new_claim_token
from services.pricing import PriceList, PricingRepository
from services.web_port import validate_web_port
from services.sync_schedule import dump_schedule_windows, load_schedule_windows
from services.billing_periods import effective_billing_day

SECONDARY_SETUP_CONTRACT = "komi-secondary-setup/v1"
DEFAULT_WEB_PORT = 3000
MAX_RESPONSE_BYTES = 128 * 1024
PEER_SYNC_TOKEN_HEADER = "X-KOMI-Peer-Sync-Token"
MAX_AUTO_DISCOVERY_HOSTS = 4096


class SecondarySetupError(RuntimeError):
    """A bounded, user-actionable peer setup failure."""


@dataclass(frozen=True)
class SecondaryPeerCandidate:
    base_url: str
    company_name: str
    printer_count: int
    version: str
    certificate_sha256: str


def _active_ipv4_subnets() -> list[
    tuple[ipaddress.IPv4Address, ipaddress.IPv4Network]
]:
    """Read every active broadcast interface with its OS-reported prefix."""

    found: list[tuple[ipaddress.IPv4Address, ipaddress.IPv4Network]] = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not flags & QNetworkInterface.InterfaceFlag.IsUp:
            continue
        if not flags & QNetworkInterface.InterfaceFlag.IsRunning:
            continue
        if flags & (
            QNetworkInterface.InterfaceFlag.IsLoopBack
            | QNetworkInterface.InterfaceFlag.IsPointToPoint
        ):
            continue
        for entry in interface.addressEntries():
            if (
                entry.ip().protocol()
                != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol
            ):
                continue
            try:
                address = ipaddress.IPv4Address(entry.ip().toString())
                prefix = int(entry.prefixLength())
                network = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
                continue
            if address.is_loopback or address.is_unspecified or address.is_link_local:
                continue
            found.append((address, network))
    return found


def local_ipv4_hosts() -> list[str]:
    """Return bounded hosts from all active LAN subnets using their real CIDR."""

    interfaces = _active_ipv4_subnets()
    if not interfaces:
        raise SecondarySetupError("ไม่พบเครือข่าย LAN ที่เครื่องนี้เชื่อมต่อ")
    local_addresses = {address for address, _network in interfaces}
    hosts: set[ipaddress.IPv4Address] = set()
    seen_networks: set[ipaddress.IPv4Network] = set()
    skipped_wide_network = False
    for _address, network in interfaces:
        if network in seen_networks:
            continue
        seen_networks.add(network)
        network_hosts = max(
            0,
            int(network.num_addresses) - (2 if network.prefixlen <= 30 else 0),
        )
        if network_hosts > MAX_AUTO_DISCOVERY_HOSTS:
            skipped_wide_network = True
            continue
        candidate_hosts = set(network.hosts()) - local_addresses
        if len(hosts | candidate_hosts) > MAX_AUTO_DISCOVERY_HOSTS:
            skipped_wide_network = True
            continue
        hosts.update(candidate_hosts)
    if not hosts:
        if skipped_wide_network:
            raise SecondarySetupError(
                "วง LAN กว้างเกินกว่าจะค้นหาอัตโนมัติ กรุณาระบุ Primary IP"
            )
        raise SecondarySetupError("ไม่พบ IP อื่นในเครือข่าย LAN ที่เครื่องนี้เชื่อมต่อ")
    return [str(host) for host in sorted(hosts, key=int)]


def normalize_primary_ipv4(value: str) -> str:
    """Validate the explicit Primary IP before making one bounded LAN request."""

    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise SecondarySetupError("Primary IP ไม่ถูกต้อง") from exc
    if not isinstance(address, ipaddress.IPv4Address) or any(
        (address.is_loopback, address.is_multicast, address.is_unspecified)
    ):
        raise SecondarySetupError("Primary IP ต้องเป็น IPv4 ที่ใช้งานได้ใน LAN")
    return str(address)


def primary_discovery_payload() -> dict[str, object]:
    """Minimal unauthenticated LAN beacon; never includes serials or credentials."""

    devices = DeviceConfigRepository().list(enabled_only=True)
    company = " ".join((get_cfg("company_name", "") or "").split())
    return {
        "contract": SECONDARY_SETUP_CONTRACT,
        "ready": bool(company and devices),
        "company_name": company,
        "printer_count": len(devices),
        "version": PACKAGE_VERSION,
    }


def primary_setup_snapshot() -> dict[str, object]:
    """Build the exact allow-listed setup snapshot shared on the trusted LAN."""

    devices = DeviceConfigRepository().list(enabled_only=True)
    pricing = PricingRepository()
    return _setup_snapshot(devices, pricing, get_cfg)


def setup_snapshot_from_connection(connection) -> dict[str, object]:
    """Read shared values within the caller's SQLite transaction, without secrets.

    Do not consult the process config cache or open repository connections here:
    both would let a preview/journal describe a different commit from its writes.
    """
    settings = dict(connection.execute("SELECT key,value FROM settings"))
    columns = ("slot", "name", "host", "model", "serial", "tls_mode", "tls_fingerprint")
    devices = [SimpleNamespace(**dict(zip(columns, row))) for row in connection.execute(
        "SELECT slot,name,host,model,serial,tls_mode,tls_fingerprint "
        "FROM devices WHERE enabled=1 ORDER BY slot"
    )]

    class TransactionPricing:
        def get_prices(self, slot, on_date):
            row = connection.execute(
                "SELECT a3_color,a3_bw,a4_color,a4_bw FROM price_history "
                "WHERE device_slot=? AND effective_date<=? ORDER BY effective_date DESC LIMIT 1",
                (slot, on_date.isoformat()),
            ).fetchone()
            return PriceList(*row) if row else PriceList()

    return _setup_snapshot(devices, TransactionPricing(), settings.get)


def _setup_snapshot(devices, pricing, config) -> dict[str, object]:
    today = date.today()
    company = " ".join((config("company_name", "") or "").split())
    if not company or not devices:
        raise SecondarySetupError("เครื่องหลักยังตั้งค่าไม่เสร็จ")
    return {
        "contract": SECONDARY_SETUP_CONTRACT,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "organization": {
            "company_name": company,
            "first_started_at": config("client_first_started_at", "") or today.isoformat(),
            "primary_installation_id": config("installation_id", ""),
        },
        "settings": {
            "pricing_mode": config("pricing_mode", "shared") or "shared",
            "billing_day": effective_billing_day(config("billing_day", "25")),
            "waste_paper_pct": float(config("waste_paper_pct", "2") or 2),
            "work_start": config("work_start", "08:00") or "08:00",
            "work_end": config("work_end", "17:00") or "17:00",
            "sync_schedule_windows": config("sync_schedule_windows", "") or "",
        },
        "devices": [
            {
                "slot": device.slot,
                "name": device.name,
                "host": device.host,
                "model": device.model,
                "serial": device.serial,
                "tls_mode": device.tls_mode,
                "tls_fingerprint": device.tls_fingerprint,
                "prices": {
                    "a3_color": pricing.get_prices(device.slot, today).a3_color,
                    "a3_bw": pricing.get_prices(device.slot, today).a3_bw,
                    "a4_color": pricing.get_prices(device.slot, today).a4_color,
                    "a4_bw": pricing.get_prices(device.slot, today).a4_bw,
                },
            }
            for device in devices
        ],
    }


def validate_setup_snapshot(payload: object) -> dict[str, object]:
    """Validate and normalize a peer snapshot before it touches Wizard state."""

    if not isinstance(payload, dict) or payload.get("contract") != SECONDARY_SETUP_CONTRACT:
        raise SecondarySetupError("รูปแบบข้อมูลจากเครื่องหลักไม่ตรงกับ KOMI V5.2")
    expected_top = {"contract", "generated_at", "organization", "settings", "devices"}
    if set(payload) != expected_top:
        raise SecondarySetupError("ข้อมูลจากเครื่องหลักมีช่องที่ไม่ได้รับอนุญาต")
    organization = payload.get("organization")
    settings = payload.get("settings")
    devices = payload.get("devices")
    if not isinstance(organization, dict) or set(organization) != {
        "company_name",
        "first_started_at",
        "primary_installation_id",
    }:
        raise SecondarySetupError("ข้อมูลองค์กรจากเครื่องหลักไม่สมบูรณ์")
    company_name = " ".join(str(organization.get("company_name") or "").split())
    if not company_name or len(company_name) > 160:
        raise SecondarySetupError("ชื่อบริษัทจากเครื่องหลักไม่ถูกต้อง")
    required_settings = {
        "pricing_mode",
        "billing_day",
        "waste_paper_pct",
        "work_start",
        "work_end",
    }
    allowed_settings = required_settings | {"sync_schedule_windows"}
    if (
        not isinstance(settings, dict)
        or not required_settings.issubset(settings)
        or not set(settings).issubset(allowed_settings)
    ):
        raise SecondarySetupError("การตั้งค่าจากเครื่องหลักไม่สมบูรณ์")
    if not isinstance(devices, list) or not 1 <= len(devices) <= 3:
        raise SecondarySetupError("เครื่องหลักต้องเลือกเครื่องพิมพ์ 1–3 เครื่อง")

    normalized_devices: list[dict[str, object]] = []
    slots: set[int] = set()
    hosts: set[str] = set()
    for raw in devices:
        allowed = {
            "slot",
            "name",
            "host",
            "model",
            "serial",
            "tls_mode",
            "tls_fingerprint",
            "prices",
        }
        if not isinstance(raw, dict) or set(raw) != allowed:
            raise SecondarySetupError("ข้อมูลเครื่องพิมพ์มีช่องที่ไม่ได้รับอนุญาต")
        slot = int(raw["slot"])
        host = str(raw["host"]).strip()
        if slot not in range(3) or slot in slots:
            raise SecondarySetupError("Slot จากเครื่องหลักไม่ถูกต้องหรือซ้ำกัน")
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise SecondarySetupError("IP เครื่องพิมพ์จากเครื่องหลักไม่ถูกต้อง") from exc
        if host in hosts:
            raise SecondarySetupError("IP เครื่องพิมพ์จากเครื่องหลักซ้ำกัน")
        prices = raw.get("prices")
        if not isinstance(prices, dict) or set(prices) != {
            "a3_color",
            "a3_bw",
            "a4_color",
            "a4_bw",
        }:
            raise SecondarySetupError("ราคาจากเครื่องหลักไม่สมบูรณ์")
        normalized_prices = {
            key: min(9999.0, max(0.0, float(value))) for key, value in prices.items()
        }
        normalized_devices.append(
            {
                "slot": slot,
                "name": str(raw["name"]).strip()[:160] or f"Slot {slot + 1}",
                "host": host,
                "model": str(raw["model"]).strip()[:160],
                "serial": str(raw["serial"]).strip()[:160],
                "tls_mode": str(raw["tls_mode"] or "system"),
                "tls_fingerprint": str(raw["tls_fingerprint"] or ""),
                "prices": normalized_prices,
            }
        )
        slots.add(slot)
        hosts.add(host)

    if any(
        str(device["tls_mode"]) not in {"system", "fingerprint"}
        for device in normalized_devices
    ):
        raise SecondarySetupError("โหมด TLS จากเครื่องหลักไม่ปลอดภัย")

    billing_day = int(settings["billing_day"])
    waste_pct = float(settings["waste_paper_pct"])
    if not 1 <= billing_day <= 31 or not 0 <= waste_pct <= 100:
        raise SecondarySetupError("รอบบิลหรือส่วนลดจากเครื่องหลักไม่ถูกต้อง")
    pricing_mode = str(settings["pricing_mode"])
    if pricing_mode not in {"shared", "per_device", "deferred"}:
        raise SecondarySetupError("รูปแบบราคาจากเครื่องหลักไม่รองรับ")
    schedule_raw = str(settings.get("sync_schedule_windows") or "").strip()
    if schedule_raw:
        schedule_windows = load_schedule_windows(schedule_raw)
        if schedule_windows is None:
            raise SecondarySetupError("ตารางเวลาอ่านข้อมูลจากเครื่องหลักไม่ถูกต้อง")
        schedule_raw = dump_schedule_windows(schedule_windows)
    return {
        "contract": SECONDARY_SETUP_CONTRACT,
        "generated_at": str(payload["generated_at"]),
        "organization": {
            "company_name": company_name,
            "first_started_at": str(organization["first_started_at"]),
            "primary_installation_id": str(organization["primary_installation_id"]),
        },
        "settings": {
            "pricing_mode": pricing_mode,
            "billing_day": billing_day,
            "waste_paper_pct": waste_pct,
            "work_start": str(settings["work_start"]),
            "work_end": str(settings["work_end"]),
            "sync_schedule_windows": schedule_raw,
        },
        "devices": sorted(normalized_devices, key=lambda item: int(item["slot"])),
    }


class SecondaryPeerClient:
    """Small HTTPS client using certificate TOFU for the one-time LAN handoff."""

    def __init__(self, *, port: int = DEFAULT_WEB_PORT, timeout: float = 0.8) -> None:
        self.port = validate_web_port(port)
        self.timeout = float(timeout)

    @staticmethod
    def _context() -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    def _request(
        self,
        host: str,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected_fingerprint: str = "",
        timeout: float | None = None,
        port: int | None = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> tuple[int, dict[str, object], str, list[str]]:
        connection = http.client.HTTPSConnection(
            host,
            self.port if port is None else port,
            context=self._context(),
            timeout=timeout or self.timeout,
        )
        try:
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True) if connection.sock else b""
            fingerprint = hashlib.sha256(certificate).hexdigest()
            if expected_fingerprint and fingerprint != expected_fingerprint:
                raise SecondarySetupError("Certificate ของเครื่องหลักเปลี่ยนระหว่างการ Sync")
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            raw = response.read(max_response_bytes + 1)
            if len(raw) > max_response_bytes:
                raise SecondarySetupError("ข้อมูลจากเครื่องหลักมีขนาดใหญ่เกินกำหนด")
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SecondarySetupError("เครื่องหลักส่งข้อมูลที่อ่านไม่ได้") from exc
            if not isinstance(payload, dict):
                raise SecondarySetupError("เครื่องหลักส่งข้อมูลผิดรูปแบบ")
            cookies = response.headers.get_all("Set-Cookie") or []
            return response.status, payload, fingerprint, cookies
        finally:
            connection.close()

    def discover_one(self, host: str) -> SecondaryPeerCandidate | None:
        try:
            status, payload, fingerprint, _cookies = self._request(
                host,
                "GET",
                "/api/v1/peer/discovery",
            )
            if status != 200 or payload.get("contract") != SECONDARY_SETUP_CONTRACT:
                return None
            if not payload.get("ready"):
                return None
            return SecondaryPeerCandidate(
                base_url=f"https://{host}:{self.port}",
                company_name=str(payload.get("company_name") or ""),
                printer_count=int(payload.get("printer_count") or 0),
                version=str(payload.get("version") or ""),
                certificate_sha256=fingerprint,
            )
        except (OSError, ssl.SSLError, SecondarySetupError, ValueError):
            return None

    def discover(self, hosts: Iterable[str]) -> list[SecondaryPeerCandidate]:
        candidates: list[SecondaryPeerCandidate] = []
        with ThreadPoolExecutor(max_workers=24) as executor:
            futures = {executor.submit(self.discover_one, host): host for host in hosts}
            for future in as_completed(futures):
                candidate = future.result()
                if candidate is not None:
                    candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.base_url)

    def discover_lan(self) -> list[SecondaryPeerCandidate]:
        """Use broadcast hints first, then the existing bounded IP fallback."""
        from services.lan_discovery import discover
        try:
            targets = discover(_active_ipv4_subnets())
        except OSError:
            targets = []
        candidates = []
        if targets:
            with ThreadPoolExecutor(max_workers=24) as executor:
                futures = [executor.submit(SecondaryPeerClient(port=port, timeout=self.timeout).discover_one, host)
                           for host, port in targets]
                for future in as_completed(futures):
                    candidate = future.result()
                    if candidate is not None:
                        candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.base_url) if candidates else self.discover(local_ipv4_hosts())

    def fetch_snapshot(self, candidate: SecondaryPeerCandidate) -> dict[str, object]:
        return validate_setup_snapshot(self._fetch_authorized(candidate, "/api/v1/peer/setup-snapshot"))

    def prepare_enrollment(self, candidate, *, cancelled=lambda: False):
        from services.peer_enrollment import prepare_enrollment, ROUTE, MAX_BYTES
        token = self._claim_authorization(candidate)
        host, port = self._peer_endpoint(candidate)
        binding = None
        begin_response = None
        def request(operation, data):
            nonlocal token, binding, begin_response
            if operation == 'begin':
                binding = dict(data)
            for attempt in range(2):
                try:
                    status, payload, _, _ = self._request(host, 'POST', ROUTE,
                        body=json.dumps({'operation': operation, 'data': data}).encode(),
                        headers={'Content-Type': 'application/json', PEER_SYNC_TOKEN_HEADER: token},
                        expected_fingerprint=candidate.certificate_sha256, port=port, timeout=15.0,
                        max_response_bytes=MAX_BYTES)
                    break
                except (OSError, ssl.SSLError):
                    if attempt:
                        raise
            if status == 401 and binding is not None:
                # Renew request credentials under persistent source access;
                # no source-side click is needed. Explicit off still rejects.
                token = self._claim_authorization(candidate)
                status, renewed, _, _ = self._request(host, 'POST', ROUTE,
                    body=json.dumps({'operation': 'begin', 'data': binding}).encode(),
                    headers={'Content-Type': 'application/json', PEER_SYNC_TOKEN_HEADER: token},
                    expected_fingerprint=candidate.certificate_sha256, port=port, timeout=15.0,
                    max_response_bytes=MAX_BYTES)
                if status == 200:
                    if begin_response is not None and renewed['invitation'] != begin_response['invitation']:
                        raise SecondarySetupError('กลุ่มต้นทางเปลี่ยน กรุณาตรวจและเข้าร่วมใหม่')
                    if operation == 'begin':
                        payload = renewed
                    else:
                        status, payload, _, _ = self._request(host, 'POST', ROUTE,
                            body=json.dumps({'operation': operation, 'data': data}).encode(),
                            headers={'Content-Type': 'application/json', PEER_SYNC_TOKEN_HEADER: token},
                            expected_fingerprint=candidate.certificate_sha256, port=port, timeout=15.0,
                            max_response_bytes=MAX_BYTES)
            if status != 200:
                raise SecondarySetupError(str(payload.get('detail') or 'เข้ากลุ่มไม่สำเร็จ กรุณาตรวจว่าเครื่องต้นทางออนไลน์และเปิดรับสมาชิกอยู่ แล้วลองใหม่'))
            if operation == 'begin':
                begin_response = payload
            return payload
        result = prepare_enrollment(request, cancelled=cancelled)
        if result.payload['organization']['company_name'] != candidate.company_name:
            result.close()
            raise SecondarySetupError('บริษัทต้นทางเปลี่ยน กรุณาค้นหาและเลือกกลุ่มใหม่')
        from dataclasses import asdict
        result.candidate = asdict(candidate)
        return result

    def finish_pending_enrollment(self, candidate, access, *, contact):
        """Resume a locally committed join using the persistent source policy."""
        from services.peer_enrollment import ROUTE, MAX_BYTES
        token = self._claim_authorization(candidate)
        host, port = self._peer_endpoint(candidate)
        def send(operation, data):
            status, result, _, _ = self._request(host, 'POST', ROUTE,
                body=json.dumps({'operation':operation, 'data':data}).encode(),
                headers={'Content-Type':'application/json', PEER_SYNC_TOKEN_HEADER:token},
                expected_fingerprint=candidate.certificate_sha256, port=port, timeout=15,
                max_response_bytes=MAX_BYTES)
            if status != 200:
                raise SecondarySetupError('ตรวจว่าเครื่องต้นทางออนไลน์และเปิดรับสมาชิกอยู่ แล้วลองเชื่อมต่อใหม่')
            return result
        result = send('begin', {'member_id':access.member_id, 'public_key':access.identity.public_key_base64url})
        if result['invitation'] != access.invitation():
            raise SecondarySetupError('กลุ่มต้นทางไม่ตรงกับกลุ่มที่ยืนยันไว้')
        access._checked_contact(result['source'])
        receipt = send('finish', {'contact':contact})
        if receipt != {'member_id':access.member_id, 'committed':True}:
            raise SecondarySetupError('ต้นทางยังไม่ยืนยันสมาชิก')
        from pathlib import Path
        from database import get_db_path, config_write_transaction
        if Path(get_db_path()).resolve() != access.path:
            raise SecondarySetupError('ฐานข้อมูลเปลี่ยนระหว่างยืนยันสมาชิก กรุณาลองใหม่')
        with config_write_transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key='peer_enrollment_pending'")

    def fetch_settings_history(self, candidate: SecondaryPeerCandidate) -> dict[str, object]:
        """Fetch only; SettingsHistory.receive validates before persisting."""
        return self._fetch_authorized(candidate, "/api/v2/peer/settings-history")

    def _fetch_authorized(self, candidate: SecondaryPeerCandidate, path: str) -> dict[str, object]:
        return self._fetch_with_token(candidate, path, self._claim_authorization(candidate))

    @staticmethod
    def _peer_endpoint(candidate):
        parsed = urlsplit(candidate.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SecondarySetupError("ที่อยู่ Primary ต้องเป็น HTTPS")
        return normalize_primary_ipv4(parsed.hostname), validate_web_port(parsed.port or DEFAULT_WEB_PORT)

    def _claim_authorization(self, candidate):
        host, port = self._peer_endpoint(candidate)
        token = new_claim_token()
        claim_body = json.dumps(
            {"token": token},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        claim_status, claim_payload, _fingerprint, _cookies = self._request(
            host,
            "POST",
            "/api/v1/peer/claim",
            body=claim_body,
            headers={"Content-Type": "application/json"},
            expected_fingerprint=candidate.certificate_sha256,
            port=port,
            timeout=4.0,
        )
        if claim_status == 423:
            raise SecondarySetupError(
                "ต้นทางปิดสิทธิ์เข้ากลุ่มอยู่ ตรวจการตั้งค่าเครือข่ายว่าไม่ได้เลือกปิดรับสมาชิก"
            )
        if claim_status != 202 or not claim_payload.get("accepted"):
            raise SecondarySetupError("เครื่อง Primary ไม่อนุญาต Secondary Sync")
        return token

    def _fetch_with_token(self, candidate, path, token):
        host, port = self._peer_endpoint(candidate)
        status, snapshot, _fingerprint, _cookies = self._request(
            host,
            "GET",
            path,
            headers={PEER_SYNC_TOKEN_HEADER: token},
            expected_fingerprint=candidate.certificate_sha256,
            port=port,
            timeout=4.0,
        )
        if status != 200:
            raise SecondarySetupError("ไม่สามารถดึงการตั้งค่าจากเครื่องหลักได้")
        return snapshot

    def iter_settings_history_pages(self, candidate):
        """One approval grants a bounded read of one pinned immutable ancestry.

        The caller imports each validated page before advancing. Lost responses
        may be retried with the same token; no new approval is consumed.
        """
        token = self._claim_authorization(candidate)
        head, offset = None, 0
        while True:
            query = {"offset": offset}
            if head is not None:
                query["head"] = head
            path = "/api/v2/peer/settings-history/page?" + urlencode(query)
            for attempt in range(2):
                try:
                    page = self._fetch_with_token(candidate, path, token)
                    break
                except (OSError, ssl.SSLError):
                    if attempt:
                        raise
            if (page.get("contract") != "komi-peer-settings-page/v1"
                    or page.get("offset") != offset
                    or not isinstance(page.get("head"), str)
                    or (head is not None and page["head"] != head)):
                raise SecondarySetupError("ประวัติที่รับไม่ตรงกับชุดที่กำลังรับ")
            head = page["head"]
            next_offset = page.get("next_offset")
            if next_offset is not None and (type(next_offset) is not int or next_offset <= offset):
                raise SecondarySetupError("ลำดับประวัติไม่ถูกต้อง")
            yield page
            if next_offset is None:
                return
            offset = next_offset
