from __future__ import annotations

import json

import pytest

from services.registration_envelope import (
    assert_registration_boundary,
    build_registration_envelope,
    normalize_device_inventory,
)


def test_registration_envelope_reports_all_scanned_devices_and_selected_slots():
    envelope = build_registration_envelope(
        installation_id="install-123",
        company_name="  Example   Company  ",
        first_started_at="2026-08-20",
        app_version="5.1.0",
        devices=[
            {"serial_number": "SN-C450-01", "model": "bizhub C450i", "selected": True, "device_slot": 1},
            {"serial_number": "SN-C750-01", "model": "bizhub C750i", "selected": True, "device_slot": 2},
            {"serial_number": "SN-C450-02", "model": "bizhub C450i", "selected": False, "device_slot": None},
            {"serial_number": "SN-C650-01", "model": "bizhub C650i", "selected": False, "device_slot": None},
        ],
        platform_name="Darwin",
        architecture="arm64",
        created_at="2026-08-20T15:30:00+00:00",
    )

    assert envelope == {
        "schema_version": 2,
        "event_type": "installation_registered",
        "installation_id": "install-123",
        "company_name": "Example Company",
        "client_first_started_at": "2026-08-20",
        "app_version": "5.1.0",
        "platform": "Darwin",
        "architecture": "arm64",
        "device_inventory": {
            "konica_discovered_count": 4,
            "devices": [
                {"serial_number": "SN-C450-01", "model": "bizhub C450i", "selected": True, "device_slot": 1},
                {"serial_number": "SN-C750-01", "model": "bizhub C750i", "selected": True, "device_slot": 2},
                {"serial_number": "SN-C450-02", "model": "bizhub C450i", "selected": False, "device_slot": None},
                {"serial_number": "SN-C650-01", "model": "bizhub C650i", "selected": False, "device_slot": None},
            ],
        },
        "created_at": "2026-08-20T15:30:00+00:00",
    }
    serialized = json.dumps(envelope).lower()
    for excluded_key in ("ip_address", "host", "password", "meter", "user", "document", "application_log"):
        assert f'"{excluded_key}"' not in serialized
    assert '"serial_number"' in serialized


def test_registration_boundary_fails_closed_for_nested_sensitive_fields():
    with pytest.raises(ValueError, match="excluded field: ip_address"):
        assert_registration_boundary({"device_inventory": {"devices": [{"ip_address": "192.0.2.10"}]}})


@pytest.mark.parametrize(
    ("devices", "message"),
    [
        (
            [
                {"serial_number": "SN-1", "model": "C450i", "selected": False, "device_slot": None},
                {"serial_number": "sn-1", "model": "C450i", "selected": False, "device_slot": None},
            ],
            "serial_number duplicated",
        ),
        (
            [{"serial_number": "SN-1", "model": "C450i", "selected": True, "device_slot": None}],
            "missing device_slot",
        ),
        (
            [{"serial_number": "SN-1", "model": "C450i", "selected": False, "device_slot": 1}],
            "must not have device_slot",
        ),
    ],
)
def test_device_inventory_rejects_ambiguous_identity_or_selection(devices, message):
    with pytest.raises(ValueError, match=message):
        normalize_device_inventory(devices)


def test_device_inventory_allows_more_than_three_found_but_only_three_selected():
    devices = [
        {
            "serial_number": f"SN-{index}",
            "model": "bizhub C450i",
            "selected": index < 3,
            "device_slot": index + 1 if index < 3 else None,
        }
        for index in range(8)
    ]

    inventory = normalize_device_inventory(devices)

    assert inventory["konica_discovered_count"] == 8
    assert sum(bool(item["selected"]) for item in inventory["devices"]) == 3
