import json
from datetime import date, datetime

import pytest

from database import _open
from komi_snmp_profiler.models import (
    Confidence,
    MeterReading,
    WebAuthState,
    WebCounterValue,
)
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.raw_counter_history import (
    RawCounterHistoryStore,
    load_raw_counter_history,
    load_usage_meter_baselines,
)


def _reading(at: datetime, value: int, *, label: str = "A5") -> MeterReading:
    return MeterReading(
        host="192.0.2.10",
        collected_at=at.isoformat(),
        counters=(
            WebCounterValue(
                canonical_field="paper.a5",
                label=label,
                count=value,
                category="paper",
                source_path="/wcd/system_counter.xml",
                confidence=Confidence.VERIFIED,
            ),
        ),
        source="legacy_xml",
        auth_state=WebAuthState.PUBLIC,
    )


def _total_reading(at: datetime, value: int) -> MeterReading:
    return MeterReading(
        host="192.0.2.10",
        collected_at=at.isoformat(),
        counters=(
            WebCounterValue(
                canonical_field="counter.total.total",
                label="Total",
                count=value,
                category="total",
                source_path="/wcd/system_counter.xml",
                confidence=Confidence.VERIFIED,
            ),
        ),
        source="legacy_xml",
        auth_state=WebAuthState.PUBLIC,
    )


def test_raw_counter_history_keeps_exact_identity_and_carries_daily_baseline():
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Production 1", "192.0.2.10", serial="SER-001")]
    )
    store = RawCounterHistoryStore()
    day_one = datetime.fromisoformat("2026-08-25T08:00:00+07:00")
    day_two = datetime.fromisoformat("2026-08-26T08:00:00+07:00")

    assert store.update_reading(0, _reading(day_one, 100), at=day_one) == 1
    assert store.update_reading(0, _reading(day_one.replace(hour=16), 110), at=day_one.replace(hour=16)) == 1
    assert store.update_reading(0, _reading(day_two, 115), at=day_two) == 1

    records = load_raw_counter_history([0])
    assert len(records) == 2
    assert records[0].record_date == date(2026, 8, 25)
    assert records[0].label == "A5"
    assert records[0].source_path == "/wcd/system_counter.xml"
    assert records[0].opening_value == 100
    assert records[0].closing_value == 110
    assert records[0].delta_value == 10
    assert records[1].opening_value == 110
    assert records[1].closing_value == 115
    assert records[1].delta_value == 5
    assert records[1].device_name_snapshot == "Production 1"
    assert records[1].device_serial_snapshot == "SER-001"


def test_raw_counter_history_records_reset_without_negative_usage():
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Production 1", "192.0.2.10", serial="SER-001")]
    )
    store = RawCounterHistoryStore()
    first = datetime.fromisoformat("2026-08-25T08:00:00+07:00")
    second = datetime.fromisoformat("2026-08-26T08:00:00+07:00")
    store.update_reading(0, _reading(first, 999), at=first)
    store.update_reading(0, _reading(second, 4), at=second)

    latest = load_raw_counter_history([0])[-1]
    assert latest.opening_value == 999
    assert latest.closing_value == 4
    assert latest.delta_value == 0
    assert latest.pending_review
    assert latest.reset_count == 1


def test_raw_counter_history_fails_closed_without_printer_serial():
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Unknown Printer", "192.0.2.10", serial="")]
    )
    stamp = datetime.fromisoformat("2026-08-25T08:00:00+07:00")

    with pytest.raises(ValueError, match="Serial Number identity"):
        RawCounterHistoryStore().update_reading(0, _reading(stamp, 100), at=stamp)

    assert load_raw_counter_history([0]) == ()


def test_raw_history_separates_replacement_serial_in_same_slot_and_day():
    store = RawCounterHistoryStore()
    first = datetime.fromisoformat("2026-08-25T08:00:00+07:00")

    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Old Printer", "192.0.2.10", serial="OLD-001")]
    )
    store.update_reading(0, _reading(first, 100), at=first)
    store.update_reading(0, _reading(first.replace(hour=9), 110), at=first.replace(hour=9))

    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "New Printer", "192.0.2.20", serial="NEW-002")]
    )
    store.update_reading(0, _reading(first.replace(hour=10), 5_000), at=first.replace(hour=10))
    store.update_reading(0, _reading(first.replace(hour=11), 5_010), at=first.replace(hour=11))

    records = load_raw_counter_history([0])

    assert len(records) == 2
    by_serial = {record.device_serial_snapshot: record for record in records}
    assert by_serial["OLD-001"].opening_value == 100
    assert by_serial["OLD-001"].closing_value == 110
    assert by_serial["OLD-001"].delta_value == 10
    assert by_serial["NEW-002"].opening_value == 5_000
    assert by_serial["NEW-002"].closing_value == 5_010
    assert by_serial["NEW-002"].delta_value == 10
    assert by_serial["NEW-002"].reset_count == 0


def test_usage_meter_baseline_uses_first_total_for_current_printer_serial():
    store = RawCounterHistoryStore()
    old_day = datetime.fromisoformat("2026-08-24T08:00:00+07:00")
    current_day = datetime.fromisoformat("2026-08-25T08:00:00+07:00")
    later = datetime.fromisoformat("2026-08-26T08:00:00+07:00")

    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Old Printer", "192.0.2.10", serial="OLD-001")]
    )
    store.update_reading(0, _total_reading(old_day, 900_000), at=old_day)
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Current Printer", "192.0.2.10", serial="NEW-002")]
    )
    store.update_reading(0, _total_reading(current_day, 125_000), at=current_day)
    store.update_reading(0, _total_reading(later, 125_500), at=later)

    baselines = load_usage_meter_baselines([0])

    assert len(baselines) == 1
    assert baselines[0].observed_on == date(2026, 8, 25)
    assert baselines[0].total_meter == 125_000
    assert baselines[0].device_name_snapshot == "Current Printer"
    assert baselines[0].device_serial_snapshot == "NEW-002"


def test_usage_meter_baseline_falls_back_to_first_daily_opening_for_older_database():
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Existing Printer", "192.0.2.10", serial="SER-001")]
    )
    stamp = "2026-08-25T08:00:00+07:00"
    with _open() as connection:
        connection.execute(
            """INSERT INTO daily_meter_records(
                   device_slot,record_date,opening_json,closing_json,delta_json,
                   category_json,source_json,first_success,last_success,
                   sample_count,error_count,incomplete,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                0,
                "2026-08-25",
                json.dumps({"counter.total.total": 42_000}),
                json.dumps({"counter.total.total": 42_100}),
                json.dumps({"counter.total.total": 100}),
                "{}",
                json.dumps(
                    {
                        "device_identity": {
                            "name": "Existing Printer",
                            "serial": "SER-001",
                        }
                    }
                ),
                stamp,
                stamp,
                2,
                0,
                0,
                stamp,
            ),
        )

    baselines = load_usage_meter_baselines([0])

    assert len(baselines) == 1
    assert baselines[0].observed_on == date(2026, 8, 25)
    assert baselines[0].total_meter == 42_000
    assert baselines[0].source == "daily_meter_opening"

def test_baseline_breakdown_uses_opening_not_latest_or_later_discovered_counter():
    from dataclasses import replace
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Printer', '192.0.2.10', serial='SER-001')])
    first = datetime.fromisoformat('2026-09-22T08:00:00+07:00')
    def reading(at, total, color, large, scan=None):
        base = _total_reading(at, total)
        values = {'counter.print.full_color_total':color,'counter.print.full_color_large':large,
                  'counter.print.bw_total':0,'counter.print.bw_large':0,'counter.print.total':color}
        if scan is not None:
            values['counter.scan_fax.document_read_total'] = scan
        return replace(base, counters=base.counters + tuple(replace(base.counters[0],canonical_field=k,label=k,count=v) for k,v in values.items()))
    store=RawCounterHistoryStore()
    store.update_reading(0,reading(first,1000,800,100),at=first)
    later=first.replace(hour=9)
    store.update_reading(0,reading(later,1050,850,120,500),at=later)
    baseline=load_usage_meter_baselines([0])[0]
    values=baseline.usage_values()
    assert values['total']==1000
    assert values['print_a3_color']==100
    assert values['print_a4_color']==700
    assert values['print_a3_bw']==values['print_a4_bw']==0
    assert values['scan'] is None
    assert values['copy_a3_color'] is None
    assert values['cost'] is None
