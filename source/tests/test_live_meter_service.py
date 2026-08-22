from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import database
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.live_meter_service import LiveMeterService, meter_reading_to_report


def counter(
    field: str,
    count: int,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    subject_name: str | None = None,
) -> WebCounterValue:
    return WebCounterValue(
        canonical_field=field,
        label=field,
        count=count,
        category="test",
        source_path=f"MFP.{field}",
        confidence=Confidence.VERIFIED,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_name=subject_name,
    )


def sample_reading() -> MeterReading:
    return MeterReading(
        host="10.0.0.5",
        collected_at="2026-07-16T06:00:00+00:00",
        counters=(
            counter("counter.total.total", 2339),
            counter("counter.paper.black.a3", 9),
            counter("counter.paper.black.a4", 453),
            counter("counter.paper.full_color.a3", 151),
            counter("counter.paper.full_color.a4", 1416),
            counter("counter.paper.single_two_color.a3", 4),
            counter("counter.paper.single_two_color.a4", 9),
            counter("counter.copy.bw_total", 124),
            counter("counter.print.full_color_total", 1759),
            counter(
                "counter.user.total.total",
                42,
                subject_type="user",
                subject_id="7",
                subject_name="operator-a",
            ),
        ),
        source="web_connection_admin_read_only",
        auth_state=WebAuthState.ADMIN,
        warnings=("fixture warning",),
    )


class FakeReader:
    def read(self, host: str) -> MeterReading:
        assert host == "10.0.0.5"
        return sample_reading()


def test_meter_reading_maps_to_v4_report_shape_and_preserves_evidence() -> None:
    parsed = meter_reading_to_report(sample_reading(), machine_name="C450i Lab")

    assert parsed["machine_name"] == "C450i Lab"
    assert parsed["serial"] == "10.0.0.5"
    assert parsed["date"] == "2026/07/16"
    assert parsed["total_counter"] == 2339
    assert parsed["paper_color"] == {
        "a4_color": 1425,
        "a4_bw": 453,
        "a3_color": 155,
        "a3_bw": 9,
    }
    assert parsed["summary"] == {"total_color": 1580, "total_bw": 462, "total": 2339}
    assert parsed["accounts"][0]["name"] == "operator-a"
    assert parsed["accounts"][0]["total"] == 42
    assert parsed["source_metadata"]["auth_state"] == "admin"
    assert parsed["source_metadata"]["schema_version"] == "komi.meter.reading.v1"
    assert len(parsed["counter_evidence"]) == 10
    assert parsed["counter_evidence"][0]["confidence"] == "verified"


def test_live_reading_saves_into_existing_report_database_and_rejects_duplicate() -> None:
    original_path = database.get_db_path()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            database.set_db_path(Path(temp_dir) / "v5.sqlite3")
            database.init_db()
            service = LiveMeterService(FakeReader())
            preview = service.read("10.0.0.5", machine_name="C450i Lab")

            saved = service.save(0, preview)
            current, previous = database.get_last_two(0)

            assert saved.reading_id > 0
            assert previous is None
            assert current["mode"] == "live_meter"
            assert current["paper_color"]["a4_color"] == 1425
            assert current["parser_name"] == "KOMI Live Meter"
            with pytest.raises(ValueError, match="มี Meter"):
                service.save(0, preview)
    finally:
        database.set_db_path(original_path)
