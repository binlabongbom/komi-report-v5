from __future__ import annotations

from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue
from services.meter_telemetry import observation_from_meter_reading


def test_multi_model_meter_maps_only_aggregate_total_and_identity():
    reading = MeterReading(
        host="192.0.2.10",
        collected_at="2026-08-25T03:00:00Z",
        counters=(
            WebCounterValue(
                canonical_field="counter.total.total",
                label="Total",
                count=12345,
                category="total",
                source_path="synthetic",
            ),
            WebCounterValue(
                canonical_field="counter.print.color",
                label="Color",
                count=999,
                category="detail",
                source_path="synthetic",
            ),
        ),
        source="synthetic",
        auth_state=WebAuthState.PUBLIC,
        warnings=("synthetic raw detail must not leave Desktop",),
    )

    observation = observation_from_meter_reading(
        reading,
        serial_number="SYNTH-001",
        model="bizhub C450i",
        device_slot=1,
    )

    assert observation == {
        "serial_number": "SYNTH-001",
        "model": "bizhub C450i",
        "device_slot": 1,
        "total_meter": 12345,
        "meter_observed_at": "2026-08-25T03:00:00Z",
        "meter_status": "ok",
    }
    assert "host" not in observation and "warnings" not in observation


def test_missing_aggregate_total_becomes_unavailable_without_raw_error():
    reading = MeterReading(
        host="192.0.2.10",
        collected_at="2026-08-25T03:00:00Z",
        counters=(),
        source="synthetic",
        auth_state=WebAuthState.PUBLIC,
        warnings=("credential/raw protocol detail",),
    )

    observation = observation_from_meter_reading(
        reading,
        serial_number="SYNTH-001",
        model="bizhub C450i",
        device_slot=1,
    )

    assert observation["meter_status"] == "unavailable"
    assert observation["total_meter"] is None
    assert "error" not in observation and "warnings" not in observation
