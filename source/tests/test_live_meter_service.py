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


@pytest.mark.parametrize("kind", ["user", "track", "account"])
def test_live_report_preserves_each_supported_subject_type(kind):
    from dataclasses import replace
    reading = replace(sample_reading(), counters=(
        counter(f"counter.{kind}.total.total", 42, subject_type=kind,
                subject_id="7", subject_name="operator-a"),
    ))
    accounts = meter_reading_to_report(reading)["accounts"]
    assert accounts and accounts[0]["subject_type"] == kind
    assert accounts[0]["total"] == 42


@pytest.mark.parametrize("value", [0, 123])
def test_missing_user_total_is_unknown_and_manual_save_is_blocked_before_database(monkeypatch, value):
    from dataclasses import replace

    from services import live_meter_service
    from services.live_meter_service import LiveMeterPreview

    reading = replace(sample_reading(), counters=(
        counter("counter.total.total", 900),
        counter("counter.user.total.bw", value, subject_type="user", subject_id="1", subject_name="Synthetic"),
        counter("counter.user.total.paper", value + 10, subject_type="user", subject_id="1", subject_name="Synthetic"),
    ))
    parsed = meter_reading_to_report(reading)
    account, = parsed["accounts"]
    assert account["total"] is None and not account["total_available"]
    assert account["color_a4"] is None and account["bw_a4"] is None
    assert any("ไม่แทนค่าที่ขาดด้วย 0" in warning for warning in parsed["warnings"])
    assert parsed["counter_evidence"][1]["count"] == value
    monkeypatch.setattr(live_meter_service, "check_duplicate", lambda *_args: pytest.fail("must not reach DB"))
    monkeypatch.setattr(live_meter_service, "save_reading", lambda *_args: pytest.fail("must not save unknown totals"))
    with pytest.raises(ValueError, match="ไม่มี Total"):
        LiveMeterService(FakeReader()).save(0, LiveMeterPreview(reading, parsed))


def test_explicit_zero_subject_total_is_still_available():
    from dataclasses import replace

    reading = replace(sample_reading(), counters=(
        counter("counter.user.total.total", 0, subject_type="user", subject_id="1", subject_name="Synthetic"),
        counter("counter.user.total.bw", 90, subject_type="user", subject_id="1", subject_name="Synthetic"),
    ))
    account, = meter_reading_to_report(reading)["accounts"]
    assert account["total"] == 0 and account["total_available"]


@pytest.mark.parametrize("value", [0, 17])
def test_verified_950i_total_does_not_invent_legacy_size_breakdown_or_save(monkeypatch, value):
    from dataclasses import replace

    from komi_snmp_profiler.mono_950i import SCHEMA_VERSION
    from services import live_meter_service
    from services.live_meter_service import LiveMeterPreview

    reading = replace(sample_reading(), schema_version=SCHEMA_VERSION, counters=(
        counter("counter.total.total", 900),
        counter("counter.user.total.total", value, subject_type="user", subject_id="1", subject_name="Synthetic"),
        counter("counter.user.total.bw", value, subject_type="user", subject_id="1", subject_name="Synthetic"),
    ))
    parsed = meter_reading_to_report(reading)
    account, = parsed["accounts"]
    assert account["total"] == value and account["total_available"]
    assert all(account[field] is None for field in ("color_a4", "bw_a4", "color_a3", "bw_a3"))
    assert any("ยังไม่มี A3/A4" in warning for warning in parsed["warnings"])
    monkeypatch.setattr(live_meter_service, "check_duplicate", lambda *_args: pytest.fail("must not reach DB"))
    monkeypatch.setattr(live_meter_service, "save_reading", lambda *_args: pytest.fail("must not invent sizes"))
    with pytest.raises(ValueError, match="A3/A4"):
        LiveMeterService(FakeReader()).save(0, LiveMeterPreview(reading, parsed))
