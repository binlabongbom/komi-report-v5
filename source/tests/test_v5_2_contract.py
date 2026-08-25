from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.installation_identity import load_or_create_installation_identity
from services.registration_vault import SessionRegistrationSecretStore
from services.v5_2_contract import (
    CONTRACT_SHA256,
    CONTRACT_VERSION,
    TelemetryPolicy,
    build_meter_payload,
    build_registration_payload,
    build_status_payload,
    validate_meter_payload,
    validate_registration_payload,
    validate_status_payload,
)


def _identity():
    return load_or_create_installation_identity(
        SessionRegistrationSecretStore(), "11111111-1111-4111-8111-111111111111"
    )


def _devices():
    return [
        {"serial_number": "SYNTH-001", "model": "bizhub C450i", "selected": True, "device_slot": 1},
        {"serial_number": "SYNTH-002", "model": "bizhub C750i", "selected": False, "device_slot": None},
    ]


def test_registration_v3_is_signed_and_keeps_strict_serial_privacy_boundary():
    identity = _identity()
    payload = build_registration_payload(
        identity=identity,
        company_name="Synthetic Company",
        first_started_at="2026-08-25",
        app_version="5.2.0",
        devices=_devices(),
        platform_name="TestOS",
        architecture="test64",
        created_at="2026-08-25T03:00:00Z",
    )

    validate_registration_payload(payload)
    assert payload["schema_version"] == 3
    assert payload["client_id"] == "komi-report-desktop"
    assert payload["device_inventory"]["devices"][0]["serial_number"] == "SYNTH-001"
    assert DraftV1SigningAdapter().verify_envelope(
        payload,
        signature_field="request_signature",
        public_key_base64url=identity.public_key_base64url,
    )
    serialized = DraftV1SigningAdapter().canonical_bytes(payload).decode("utf-8")
    for forbidden in ("ip_address", "mac_address", "hostname", "password", "raw_xml", "job"):
        assert forbidden not in serialized


def test_status_has_no_online_boolean_and_policy_uses_six_hour_cadence():
    payload = build_status_payload(
        installation_id="11111111-1111-4111-8111-111111111111",
        app_version="5.2.0",
        platform_name="TestOS",
        architecture="test64",
        occurred_at="2026-08-25T03:02:00Z",
    )
    validate_status_payload(payload)
    assert "online" not in payload and "offline" not in payload

    policy = TelemetryPolicy()
    assert policy.status_interval_seconds == 21_600
    assert policy.meter_interval_seconds == 21_600
    assert policy.offline_threshold_seconds == 259_200
    assert policy.no_print_threshold_seconds == 86_400
    assert policy.startup_recovery_cooldown_seconds == 900
    assert policy.clamp_server_interval(1) == 3_600
    assert policy.clamp_server_interval(99_999) == 43_200
    assert 19_440 <= policy.with_jitter(21_600, random_unit=0.0) <= 23_760
    assert CONTRACT_SHA256 == "4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd"
    assert CONTRACT_VERSION == "v5.2-shared-2026-08-25-r2"


def test_meter_batch_is_latest_selected_aggregate_only_and_counter_reset_is_not_delta():
    payload = build_meter_payload(
        installation_id="11111111-1111-4111-8111-111111111111",
        observations=[
            {
                "serial_number": "SYNTH-001",
                "model": "bizhub C450i",
                "device_slot": 1,
                "total_meter": 100,
                "meter_observed_at": "2026-08-25T03:00:00Z",
                "meter_status": "ok",
            },
            {
                "serial_number": "SYNTH-001",
                "model": "bizhub C450i",
                "device_slot": 1,
                "total_meter": 90,
                "meter_observed_at": "2026-08-25T03:05:00Z",
                "meter_status": "ok",
            },
        ],
        sent_at="2026-08-25T03:05:01Z",
    )
    validate_meter_payload(payload)
    assert len(payload["observations"]) == 1
    assert payload["observations"][0]["total_meter"] == 90
    assert payload["observations"][0]["meter_status"] == "ok"
    assert "delta" not in payload["observations"][0]

    unavailable = build_meter_payload(
        installation_id="11111111-1111-4111-8111-111111111111",
        observations=[
            {
                "serial_number": "SYNTH-002",
                "model": "bizhub C750i",
                "device_slot": 2,
                "total_meter": None,
                "meter_observed_at": "2026-08-25T03:05:00Z",
                "meter_status": "unavailable",
            }
        ],
        sent_at="2026-08-25T03:05:01Z",
    )
    validate_meter_payload(unavailable)
    assert unavailable["observations"][0]["total_meter"] is None


def test_contract_rejects_forbidden_or_detailed_counter_fields():
    payload = build_status_payload(
        installation_id="11111111-1111-4111-8111-111111111111",
        app_version="5.2.0",
        platform_name="TestOS",
        architecture="test64",
    )
    payload["hostname"] = "forbidden"
    with pytest.raises(ValueError, match="unexpected|excluded"):
        validate_status_payload(payload)

    meter = build_meter_payload(
        installation_id="11111111-1111-4111-8111-111111111111",
        observations=[
            {
                "serial_number": "SYNTH-001",
                "model": "bizhub C450i",
                "device_slot": 1,
                "total_meter": 100,
                "meter_observed_at": datetime.now(UTC).isoformat(),
                "meter_status": "ok",
            }
        ],
    )
    meter["observations"][0]["color_counter"] = 10
    with pytest.raises(ValueError, match="unexpected|excluded"):
        validate_meter_payload(meter)
