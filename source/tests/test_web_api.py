from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient

import web_api
from services import peer_sync_authorization
from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.subject_history import SubjectPeriodUsage


def test_health_never_exposes_credentials(monkeypatch):
    monkeypatch.setattr(web_api, "_devices", lambda: [])
    response = TestClient(web_api.app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["device_count"] == 0
    assert "password" not in response.text.casefold()


def test_peer_discovery_is_minimal_and_snapshot_is_allow_listed(monkeypatch):
    discovery = {
        "contract": "komi-secondary-setup/v1",
        "ready": True,
        "company_name": "บริษัท ทดสอบ จำกัด",
        "printer_count": 1,
        "version": "5.2.5",
    }
    snapshot = {
        "contract": "komi-secondary-setup/v1",
        "generated_at": "2026-08-26T10:00:00+07:00",
        "organization": {
            "company_name": "บริษัท ทดสอบ จำกัด",
            "first_started_at": "2026-08-26",
            "primary_installation_id": "primary-id",
        },
        "settings": {
            "pricing_mode": "shared",
            "billing_day": 31,
            "waste_paper_pct": 2.0,
            "work_start": "08:00",
            "work_end": "17:00",
            "sync_schedule_windows": "",
        },
        "devices": [
            {
                "slot": 0,
                "name": "บัญชี",
                "host": "192.0.2.10",
                "model": "bizhub C450i",
                "serial": "SER-001",
                "tls_mode": "system",
                "tls_fingerprint": "",
                "prices": {
                    "a3_color": 4.0,
                    "a3_bw": 1.0,
                    "a4_color": 2.0,
                    "a4_bw": 0.2,
                },
            }
        ],
    }
    monkeypatch.setattr(web_api, "primary_discovery_payload", lambda: discovery)
    monkeypatch.setattr(web_api, "primary_setup_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        web_api,
        "get_cfg",
        lambda key, default="": "primary-id" if key == "installation_id" else default,
    )
    state_path = __import__("pathlib").Path(
        __import__("tempfile").mkdtemp()
    ) / "peer-sync.json"
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(state_path))
    client = TestClient(web_api.app)

    assert client.get("/api/v1/peer/discovery").json() == discovery
    assert client.get("/api/v1/peer/setup-snapshot").status_code == 401

    token = "a" * 43
    assert client.post("/api/v1/peer/claim", json={"token": token}).status_code == 423
    peer_sync_authorization.open_pairing_window("primary-id")
    claim = client.post("/api/v1/peer/claim", json={"token": token})
    assert claim.status_code == 202
    response = client.get(
        "/api/v1/peer/setup-snapshot",
        headers={"X-KOMI-Peer-Sync-Token": token},
    )

    assert response.status_code == 200
    assert response.json() == snapshot
    assert "password" not in response.text.casefold()
    assert "token" not in response.text.casefold()
    assert (
        client.get(
            "/api/v1/peer/setup-snapshot",
            headers={"X-KOMI-Peer-Sync-Token": token},
        ).status_code
        == 401
    )


def test_empty_overview_is_explicit(monkeypatch):
    monkeypatch.setattr(web_api, "_devices", lambda: [])
    monkeypatch.setattr(web_api, "load_usage_history", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: ())
    response = TestClient(web_api.app).get("/api/reports/overview")
    assert response.status_code == 200
    assert response.json()["empty"] is True
    assert response.json()["totals"]["net_cost"] == 0


def test_device_status_detail_redacts_credentials(monkeypatch):
    device = DeviceConfig(
        0,
        "Printer 1",
        "192.0.2.10",
        username="administrator",
        password="super-secret",
        last_error="password=super-secret Authorization: Bearer abc123 administrator",
    )
    monkeypatch.setattr(web_api, "_devices", lambda: [device])

    response = TestClient(web_api.app).get("/api/devices")

    assert response.status_code == 200
    body = response.text.casefold()
    assert "super-secret" not in body
    assert "administrator" not in body
    assert "abc123" not in body


def test_openapi_endpoints_have_concrete_response_schemas():
    schema = TestClient(web_api.app).get("/api/openapi.json").json()
    api_paths = [path for path in schema["paths"] if path.startswith("/api/")]

    assert api_paths
    for path in api_paths:
        for operation in schema["paths"][path].values():
            successful = next(
                response
                for code, response in operation["responses"].items()
                if str(code).startswith("2")
            )
            response_schema = successful["content"]["application/json"]["schema"]
            assert response_schema.get("$ref") or response_schema.get("type") not in (
                None,
                "object",
            )


def _monthly_identity(
    identity: str,
    name: str,
    serial: str,
    total: float,
    *,
    slot: int = 0,
) -> MonthlyUsage:
    return MonthlyUsage(
        device_slot=slot,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        total=total,
        a3_color=0,
        a3_bw=0,
        a4_color=total,
        a4_bw=0,
        scan=0,
        gross_cost=total,
        net_cost=total,
        day_count=1,
        incomplete_days=0,
        device_identity=identity,
        device_name_snapshot=name,
        device_serial_snapshot=serial,
    )


def test_report_api_separates_historical_and_current_slot_identities(monkeypatch):
    device = DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")
    records = (
        _monthly_identity("serial:SER-A", "Printer A", "SER-A", 10),
        _monthly_identity("serial:SER-B", "Printer B", "SER-B", 20),
    )
    monkeypatch.setattr(web_api, "_devices", lambda: [device])
    monkeypatch.setattr(web_api, "load_usage_history", lambda *_args, **_kwargs: records)
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(web_api, "current_device_identity", lambda _slot: "serial:SER-B")
    client = TestClient(web_api.app)

    overview = client.get("/api/reports/overview").json()

    assert overview["totals"]["usage"] == 30
    assert overview["data_quality"]["mixed_identity_slots"] == [0]
    assert overview["data_quality"]["historical_identity_slots"] == [0]
    devices_by_identity = {item["device_identity"]: item for item in overview["devices"]}
    assert devices_by_identity["serial:SER-A"]["name"] == "Printer A"
    assert devices_by_identity["serial:SER-A"]["serial"] == "SER-A"
    assert devices_by_identity["serial:SER-A"]["status"] == "historical"
    assert devices_by_identity["serial:SER-A"]["is_current_identity"] is False
    assert devices_by_identity["serial:SER-B"]["name"] == "Printer B"
    assert devices_by_identity["serial:SER-B"]["is_current_identity"] is True

    history = client.get("/api/reports/history").json()["items"][0]
    assert history["usage"] == 30
    assert history["device_identities"] == ["serial:SER-A", "serial:SER-B"]
    assert history["mixed_identity_slots"] == [0]


def test_report_overview_selects_exact_start_and_end_period(monkeypatch):
    first = replace(
        _monthly_identity("serial:SER-A", "Printer A", "SER-A", 10),
        period_end=date(2026, 7, 25),
    )
    second = _monthly_identity("serial:SER-A", "Printer A", "SER-A", 20)
    monkeypatch.setattr(
        web_api,
        "_devices",
        lambda: [DeviceConfig(0, "Printer A", "192.0.2.10", serial="SER-A")],
    )
    monkeypatch.setattr(
        web_api,
        "load_usage_history",
        lambda *_args, **_kwargs: (first, second),
    )
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(web_api, "current_device_identity", lambda _slot: "serial:SER-A")

    response = TestClient(web_api.app).get(
        "/api/reports/overview"
        "?period_start=2026-07-01&period_end=2026-07-25"
    )

    assert response.status_code == 200
    assert response.json()["period"] == {
        "start": "2026-07-01",
        "end": "2026-07-25",
    }
    assert response.json()["totals"]["usage"] == 10


def test_history_api_filters_to_the_selected_period_and_device(monkeypatch):
    selected = _monthly_identity("serial:SER-A", "Printer A", "SER-A", 10)
    same_period_other_device = _monthly_identity(
        "serial:SER-B", "Printer B", "SER-B", 20, slot=1
    )
    outside_period = replace(
        selected,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        total=30,
    )
    monkeypatch.setattr(
        web_api,
        "load_usage_history",
        lambda *_args, **_kwargs: (selected, same_period_other_device, outside_period),
    )

    response = TestClient(web_api.app).get(
        "/api/reports/history?granularity=daily"
        "&period_start=2026-07-01&period_end=2026-07-31"
        "&device_identity=serial%3ASER-A"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["usage"] == 10
    assert body["items"][0]["device_identities"] == ["serial:SER-A"]


def test_report_api_exposes_current_cache_as_separate_provisional_totals(monkeypatch):
    record = replace(
        _monthly_identity("serial:SER-A", "Printer A", "SER-A", 50),
        gross_cost=100,
        net_cost=98,
        print_color=30,
        print_bw=20,
        print_available=True,
        copy_available=True,
        provisional_total=10,
        provisional_a4_color=10,
        provisional_print_color=7,
        provisional_copy_color=3,
        provisional_gross_cost=20,
        provisional_net_cost=19.6,
        provisional_days=1,
    )
    monkeypatch.setattr(
        web_api,
        "_devices",
        lambda: [DeviceConfig(0, "Printer A", "192.0.2.10", serial="SER-A")],
    )
    monkeypatch.setattr(
        web_api,
        "load_usage_history",
        lambda *_args, **_kwargs: (record,),
    )
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(web_api, "current_device_identity", lambda _slot: "serial:SER-A")

    body = TestClient(web_api.app).get("/api/reports/overview").json()

    assert body["totals"]["usage"] == 60
    assert body["totals"]["confirmed_usage"] == 50
    assert body["totals"]["provisional_usage"] == 10
    assert body["totals"]["net_cost"] == 117.6
    assert body["totals"]["confirmed_net_cost"] == 98
    assert body["totals"]["provisional_net_cost"] == 19.6
    assert body["totals"]["provisional_days"] == 1
    assert body["totals"]["print_color"] == 37
    assert body["totals"]["print_bw"] == 20
    assert body["totals"]["copy_color"] == 3
    assert body["totals"]["copy_bw"] == 0
    assert body["totals"]["print_available"] is True
    assert body["totals"]["copy_available"] is True
    assert body["data_quality"]["status"] == "provisional"
    assert body["devices"][0]["usage"]["total"] == 60
    assert body["devices"][0]["usage"]["confirmed_total"] == 50
    assert body["devices"][0]["usage"]["provisional_total"] == 10
    assert body["devices"][0]["usage"]["provisional_print_color"] == 7
    assert body["devices"][0]["usage"]["provisional_copy_color"] == 3


def test_report_api_combines_complete_periods_inside_selected_range(monkeypatch):
    july = _monthly_identity("serial:SER-A", "Printer A", "SER-A", 10)
    august = replace(
        july,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        total=20,
        a4_color=20,
    )
    subjects = (
        SubjectPeriodUsage(
            device_slot=0,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            subject_type="user",
            subject_id="u-1",
            subject_name="alice",
            latest_total=4,
            period_usage=4,
            reset_count=0,
            missing_baseline_days=0,
            incomplete_days=0,
            sample_count=1,
            latest_at=None,
            warnings=(),
            device_identity="serial:SER-A",
            device_name_snapshot="Printer A",
            device_serial_snapshot="SER-A",
        ),
        SubjectPeriodUsage(
            device_slot=0,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            subject_type="user",
            subject_id="u-1",
            subject_name="alice",
            latest_total=10,
            period_usage=6,
            reset_count=0,
            missing_baseline_days=0,
            incomplete_days=0,
            sample_count=1,
            latest_at=None,
            warnings=(),
            device_identity="serial:SER-A",
            device_name_snapshot="Printer A",
            device_serial_snapshot="SER-A",
        ),
    )
    monkeypatch.setattr(
        web_api,
        "_devices",
        lambda: [DeviceConfig(0, "Printer A", "192.0.2.10", serial="SER-A")],
    )
    monkeypatch.setattr(web_api, "load_usage_history", lambda *_args, **_kwargs: (july, august))
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: subjects)
    monkeypatch.setattr(web_api, "current_device_identity", lambda _slot: "serial:SER-A")
    client = TestClient(web_api.app)
    query = "?period_start=2026-07-01&period_end=2026-08-31"

    overview = client.get(f"/api/reports/overview{query}").json()
    users = client.get(f"/api/reports/users{query}").json()

    assert overview["period"] == {"start": "2026-07-01", "end": "2026-08-31"}
    assert overview["totals"]["usage"] == 30
    assert overview["top_users"][0]["usage"] == 10
    assert users["total"] == 2
    assert sum(item["usage"] for item in users["items"]) == 10


def test_user_api_exposes_frozen_identity_for_same_subject_in_reused_slot(monkeypatch):
    device = DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")
    subjects = tuple(
        SubjectPeriodUsage(
            device_slot=0,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            subject_type="user",
            subject_id="u-1",
            subject_name="alice",
            latest_total=usage,
            period_usage=usage,
            reset_count=0,
            missing_baseline_days=0,
            incomplete_days=0,
            sample_count=1,
            latest_at=None,
            warnings=(),
            device_identity=identity,
            device_name_snapshot=name,
            device_serial_snapshot=serial,
        )
        for identity, name, serial, usage in (
            ("serial:SER-A", "Printer A", "SER-A", 10),
            ("serial:SER-B", "Printer B", "SER-B", 20),
        )
    )
    monkeypatch.setattr(web_api, "_devices", lambda: [device])
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: subjects)

    items = TestClient(web_api.app).get("/api/reports/users").json()["items"]

    assert {(item["device_identity"], item["usage"]) for item in items} == {
        ("serial:SER-A", 10),
        ("serial:SER-B", 20),
    }
    assert {item["device_name_snapshot"] for item in items} == {"Printer A", "Printer B"}


def test_user_pages_share_one_bounded_report_snapshot(monkeypatch):
    subject = SubjectPeriodUsage(
        device_slot=0, period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
        subject_type="user", subject_id="u-0", subject_name="User 0",
        latest_total=1, period_usage=1, reset_count=0, missing_baseline_days=0,
        incomplete_days=0, sample_count=1, latest_at=None, warnings=(),
        device_identity="serial:SER-A", device_name_snapshot="Printer A",
        device_serial_snapshot="SER-A",
    )
    subjects = tuple(replace(subject, subject_id=f"u-{i}") for i in range(1050))
    calls = []
    def load(_slots, **kwargs):
        calls.append(kwargs)
        return subjects
    monkeypatch.setattr(web_api, "report_slots", lambda: [0])
    monkeypatch.setattr(web_api, "load_subject_history", load)
    client = TestClient(web_api.app)
    base = "/api/reports/users?period_start=2026-07-01&period_end=2026-07-31&limit=500"
    first = client.get(base).json()
    token = first["snapshot_token"]
    second = client.get(f"{base}&offset=500&snapshot_token={token}").json()
    third = client.get(f"{base}&offset=1000&snapshot_token={token}").json()
    assert [len(page["items"]) for page in (first, second, third)] == [500, 500, 50]
    assert len({item["subject_id"] for page in (first, second, third) for item in page["items"]}) == 1050
    assert calls == [{"period_start": date(2026, 7, 1), "period_end": date(2026, 7, 31)}]


def test_versioned_api_returns_request_id_and_paged_history(monkeypatch):
    first = _monthly_identity("serial:SER-A", "Printer A", "SER-A", 10)
    second = replace(first, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
    monkeypatch.setattr(web_api, "load_usage_history", lambda *_args, **_kwargs: (first, second))

    response = TestClient(web_api.app).get("/api/v1/reports/history?limit=1&offset=1")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["next_offset"] is None
    assert len(body["items"]) == 1


def test_history_api_rejects_unbounded_page_size():
    response = TestClient(web_api.app).get("/api/reports/history?limit=501")

    assert response.status_code == 422


def test_report_api_keeps_frozen_device_after_its_slot_is_disabled(monkeypatch):
    current = DeviceConfig(0, "Current Printer", "192.0.2.10", serial="SER-CURRENT")
    retired = _monthly_identity(
        "serial:SER-OLD",
        "Retired Printer",
        "SER-OLD",
        40,
        slot=1,
    )
    monkeypatch.setattr(web_api, "_devices", lambda: [current])
    monkeypatch.setattr(web_api, "report_slots", lambda: [0, 1])
    monkeypatch.setattr(web_api, "load_usage_history", lambda *_args, **_kwargs: (retired,))
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        web_api,
        "current_device_identity",
        lambda slot: "serial:SER-CURRENT" if slot == 0 else "",
    )

    overview = TestClient(web_api.app).get("/api/reports/overview").json()

    assert overview["totals"]["usage"] == 40
    assert overview["devices"][0]["device_identity"] == "serial:SER-OLD"
    assert overview["devices"][0]["name"] == "Retired Printer"
    assert overview["devices"][0]["status"] == "historical"
    assert overview["devices"][0]["is_current_identity"] is False
    assert overview["data_quality"]["historical_identity_slots"] == [1]
