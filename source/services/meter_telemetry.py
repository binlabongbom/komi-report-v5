"""Privacy-bounded mapping from multi-model Meter readings to V5.2 telemetry."""

from __future__ import annotations

from komi_snmp_profiler.models import MeterReading


def observation_from_meter_reading(
    reading: MeterReading,
    *,
    serial_number: str,
    model: str,
    device_slot: int,
) -> dict[str, object]:
    total = next(
        (
            counter.count
            for counter in reading.counters
            if counter.canonical_field == "counter.total.total"
        ),
        None,
    )
    if type(total) not in {int, float} or int(total) != total or total < 0:
        return unavailable_meter_observation(
            serial_number=serial_number,
            model=model,
            device_slot=device_slot,
            observed_at=reading.collected_at,
        )
    return {
        "serial_number": serial_number.strip(),
        "model": model.strip(),
        "device_slot": device_slot,
        "total_meter": int(total),
        "meter_observed_at": reading.collected_at,
        "meter_status": "ok",
    }

def unavailable_meter_observation(
    *,
    serial_number: str,
    model: str,
    device_slot: int,
    observed_at: str,
) -> dict[str, object]:
    return {
        "serial_number": serial_number.strip(),
        "model": model.strip(),
        "device_slot": device_slot,
        "total_meter": None,
        "meter_observed_at": observed_at,
        "meter_status": "unavailable",
    }
