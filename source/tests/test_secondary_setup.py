from __future__ import annotations

import ipaddress
from dataclasses import dataclass

import pytest

from services import secondary_setup
from services.device_config import DeviceConfig
from services.pricing import PriceList
from services.sync_schedule import default_schedule_windows, dump_schedule_windows

SCHEDULE_JSON = dump_schedule_windows(default_schedule_windows())


def test_secondary_discovery_uses_all_active_interface_prefixes(monkeypatch):
    monkeypatch.setattr(
        secondary_setup,
        "_active_ipv4_subnets",
        lambda: [
            (
                ipaddress.IPv4Address("10.0.0.2"),
                ipaddress.IPv4Network("10.0.0.0/30"),
            ),
            (
                ipaddress.IPv4Address("192.168.50.5"),
                ipaddress.IPv4Network("192.168.50.0/29"),
            ),
            (
                ipaddress.IPv4Address("192.168.50.6"),
                ipaddress.IPv4Network("192.168.50.0/29"),
            ),
        ],
    )

    assert secondary_setup.local_ipv4_hosts() == [
        "10.0.0.1",
        "192.168.50.1",
        "192.168.50.2",
        "192.168.50.3",
        "192.168.50.4",
    ]


def test_secondary_discovery_fails_closed_for_unbounded_subnet(monkeypatch):
    monkeypatch.setattr(
        secondary_setup,
        "_active_ipv4_subnets",
        lambda: [
            (
                ipaddress.IPv4Address("10.20.30.40"),
                ipaddress.IPv4Network("10.20.0.0/16"),
            )
        ],
    )

    with pytest.raises(secondary_setup.SecondarySetupError, match="Primary IP"):
        secondary_setup.local_ipv4_hosts()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" 192.168.1.25 ", "192.168.1.25"),
        ("10.244.116.8", "10.244.116.8"),
    ],
)
def test_manual_primary_ip_is_normalized(raw, expected):
    assert secondary_setup.normalize_primary_ipv4(raw) == expected


@pytest.mark.parametrize("raw", ["", "primary.local", "::1", "127.0.0.1", "224.0.0.1"])
def test_manual_primary_ip_fails_closed(raw):
    with pytest.raises(secondary_setup.SecondarySetupError, match="Primary IP"):
        secondary_setup.normalize_primary_ipv4(raw)


@dataclass
class _Devices:
    items: list[DeviceConfig]

    def list(self, *, enabled_only: bool = False) -> list[DeviceConfig]:
        assert enabled_only
        return list(self.items)


class _Pricing:
    def get_prices(self, slot: int, _on_date) -> PriceList:
        return PriceList(
            a3_color=4.0 + slot,
            a3_bw=1.0 + slot,
            a4_color=2.0 + slot,
            a4_bw=0.2 + slot,
        )


def _valid_snapshot() -> dict[str, object]:
    return {
        "contract": secondary_setup.SECONDARY_SETUP_CONTRACT,
        "generated_at": "2026-08-26T10:00:00+07:00",
        "organization": {
            "company_name": "บริษัท ทดสอบ จำกัด",
            "first_started_at": "2026-08-26",
            "primary_installation_id": "primary-installation",
        },
        "settings": {
            "pricing_mode": "shared",
            "billing_day": 31,
            "waste_paper_pct": 2.0,
            "work_start": "08:00",
            "work_end": "17:00",
            "sync_schedule_windows": SCHEDULE_JSON,
        },
        "devices": [
            {
                "slot": 0,
                "name": "บัญชี",
                "host": "192.0.2.10",
                "model": "KONICA MINOLTA bizhub C450i",
                "serial": "SERIAL-001",
                "tls_mode": "fingerprint",
                "tls_fingerprint": "a" * 64,
                "prices": {
                    "a3_color": 4.0,
                    "a3_bw": 1.0,
                    "a4_color": 2.0,
                    "a4_bw": 0.2,
                },
            }
        ],
    }


def test_primary_snapshot_is_an_exact_setup_allow_list(monkeypatch):
    device = DeviceConfig(
        0,
        "บัญชี",
        "192.0.2.10",
        username="Administrator",
        password="must-never-leave-primary",
        model="KONICA MINOLTA bizhub C450i",
        serial="SERIAL-001",
        tls_mode="fingerprint",
        tls_fingerprint="a" * 64,
    )
    values = {
        "company_name": "บริษัท ทดสอบ จำกัด",
        "client_first_started_at": "2026-08-26",
        "installation_id": "primary-installation",
        "pricing_mode": "shared",
        "billing_day": "31",
        "waste_paper_pct": "2",
        "work_start": "08:00",
        "work_end": "17:00",
        "sync_schedule_windows": SCHEDULE_JSON,
    }
    monkeypatch.setattr(secondary_setup, "DeviceConfigRepository", lambda: _Devices([device]))
    monkeypatch.setattr(secondary_setup, "PricingRepository", _Pricing)
    monkeypatch.setattr(
        secondary_setup,
        "get_cfg",
        lambda key, default="": values.get(key, default),
    )

    snapshot = secondary_setup.primary_setup_snapshot()
    serialized = repr(snapshot).casefold()

    assert secondary_setup.validate_setup_snapshot(snapshot) == snapshot
    assert "must-never-leave-primary" not in serialized
    assert "credential" not in serialized
    assert "token" not in serialized
    assert "history" not in serialized
    assert "log" not in serialized


@pytest.mark.parametrize("forbidden", ["password", "registration_token", "history", "raw_xml"])
def test_secondary_rejects_every_extra_field(forbidden):
    snapshot = _valid_snapshot()
    snapshot[forbidden] = "forbidden"

    with pytest.raises(secondary_setup.SecondarySetupError, match="ไม่ได้รับอนุญาต"):
        secondary_setup.validate_setup_snapshot(snapshot)


def test_secondary_rejects_malformed_schedule_in_allow_list():
    snapshot = _valid_snapshot()
    snapshot["settings"]["sync_schedule_windows"] = "not-json"

    with pytest.raises(secondary_setup.SecondarySetupError, match="ตารางเวลา"):
        secondary_setup.validate_setup_snapshot(snapshot)


def test_secondary_accepts_older_snapshot_without_schedule_as_empty():
    snapshot = _valid_snapshot()
    del snapshot["settings"]["sync_schedule_windows"]

    validated = secondary_setup.validate_setup_snapshot(snapshot)

    assert validated["settings"]["sync_schedule_windows"] == ""


def test_discovery_payload_contains_no_device_identity(monkeypatch):
    monkeypatch.setattr(
        secondary_setup,
        "DeviceConfigRepository",
        lambda: _Devices([DeviceConfig(0, "บัญชี", "192.0.2.10", serial="SECRET-SERIAL")]),
    )
    monkeypatch.setattr(
        secondary_setup,
        "get_cfg",
        lambda key, default="": "บริษัท ทดสอบ จำกัด" if key == "company_name" else default,
    )

    payload = secondary_setup.primary_discovery_payload()

    assert payload["ready"] is True
    assert payload["printer_count"] == 1
    assert "SECRET-SERIAL" not in repr(payload)
    assert "192.0.2.10" not in repr(payload)


def test_secondary_fetches_snapshot_with_one_time_primary_approval(monkeypatch):
    candidate = secondary_setup.SecondaryPeerCandidate(
        base_url="https://192.0.2.20:3000",
        company_name="บริษัท ทดสอบ จำกัด",
        printer_count=1,
        version=secondary_setup.PACKAGE_VERSION,
        certificate_sha256="b" * 64,
    )
    requests: list[tuple[str, str]] = []
    claim_token = ""

    def request(_host, method, path, **kwargs):
        nonlocal claim_token
        requests.append((method, path))
        assert kwargs["expected_fingerprint"] == "b" * 64
        if path == "/api/v1/peer/claim":
            claim_token = __import__("json").loads(kwargs["body"])["token"]
            assert len(claim_token) >= 43
            assert kwargs["headers"] == {"Content-Type": "application/json"}
            return 202, {"accepted": True, "expires_in_seconds": 300}, "b" * 64, []
        assert kwargs["headers"] == {
            secondary_setup.PEER_SYNC_TOKEN_HEADER: claim_token
        }
        return 200, _valid_snapshot(), "b" * 64, []

    client = secondary_setup.SecondaryPeerClient()
    monkeypatch.setattr(client, "_request", request)

    assert client.fetch_snapshot(candidate) == _valid_snapshot()
    assert requests == [
        ("POST", "/api/v1/peer/claim"),
        ("GET", "/api/v1/peer/setup-snapshot"),
    ]


def test_secondary_rejects_unsafe_tls_mode():
    snapshot = _valid_snapshot()
    snapshot["devices"][0]["tls_mode"] = "insecure"

    with pytest.raises(secondary_setup.SecondarySetupError, match="TLS"):
        secondary_setup.validate_setup_snapshot(snapshot)


def test_snapshot_uses_selected_candidate_port_even_with_default_client(monkeypatch):
    candidate = secondary_setup.SecondaryPeerCandidate(
        base_url="https://192.0.2.20:3443", company_name="Test", printer_count=1,
        version="5.2.9", certificate_sha256="b" * 64,
    )
    client = secondary_setup.SecondaryPeerClient()
    calls = []

    def request(host, method, path, **kwargs):
        assert host == "192.0.2.20"
        assert kwargs["port"] == 3443
        calls.append(path)
        if method == "POST":
            return 202, {"accepted": True}, "b" * 64, []
        return 200, _valid_snapshot(), "b" * 64, []

    monkeypatch.setattr(client, "_request", request)
    assert client.fetch_snapshot(candidate) == _valid_snapshot()
    assert len(calls) == 2
