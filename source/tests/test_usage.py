import json
from datetime import date, datetime

from database import _open, init_db, set_cfg, set_db_path
from services.billing_ledger import post_daily_record
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository
from services.usage import (
    billing_period,
    current_period_counters,
    current_period_counters_by_identity,
    default_usage_groups,
    latest_counters,
)


def test_default_usage_groups_preserve_unknown_when_cross_dimension_missing():
    groups = default_usage_groups(
        {
            "counter.print.a4_full_color": 10,
            "counter.copy.a3_black": 5,
            "counter.scan_fax.scan_total": 9,
        }
    )

    assert groups["A4 Color (Print)"] == 10
    assert groups["A3 B&W (Copy)"] == 5
    assert groups["A3 Color (Print)"] is None
    assert groups["SCAN"] == 9


def test_default_usage_groups_derive_a3_a4_from_total_and_large_pairs():
    groups = default_usage_groups(
        {
            "counter.print.total": 2140,
            "counter.print.full_color_total": 1760,
            "counter.print.full_color_large": 177,
            "counter.print.full_color_long_size": 0,
            "counter.print.bi_color_total": 8,
            "counter.print.bi_color_large": 0,
            "counter.print.bw_total": 372,
            "counter.print.bw_large": 4,
            "counter.copy.total": 200,
            "counter.copy.full_color_total": 71,
            "counter.copy.full_color_large": 0,
            "counter.copy.bi_color_total": 5,
            "counter.copy.bi_color_large": 0,
            "counter.copy.bw_total": 124,
            "counter.copy.bw_large": 5,
            "counter.scan_fax.document_read_total": 1483,
        }
    )

    assert groups == {
        "A3 Color (Print)": 177,
        "A3 B&W (Print)": 4,
        "A4 Color (Print)": 1591,
        "A4 B&W (Print)": 368,
        "A3 Color (Copy)": 0,
        "A3 B&W (Copy)": 5,
        "A4 Color (Copy)": 76,
        "A4 B&W (Copy)": 119,
        "Other size (Print)": 0,
        "Other size (Copy)": 0,
        "SCAN": 1483,
    }


def test_default_usage_groups_show_zero_for_a_baseline_reading():
    groups = default_usage_groups(
        {
            "counter.print.total": 0,
            "counter.print.full_color_total": 0,
            "counter.print.full_color_large": 0,
            "counter.print.bw_total": 0,
            "counter.print.bw_large": 0,
            "counter.copy.total": 0,
            "counter.copy.full_color_total": 0,
            "counter.copy.full_color_large": 0,
            "counter.copy.bw_total": 0,
            "counter.copy.bw_large": 0,
            "counter.scan_fax.document_read_total": 0,
        }
    )

    assert all(value == 0 for value in groups.values())


def test_current_period_usage_excludes_held_unposted_and_mutated_daily_rows(tmp_path):
    set_db_path(tmp_path / "current-usage.db")
    init_db()
    set_cfg("billing_day", "31")
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    record_ids = []
    with _open() as conn:
        for record_day, total, billing_safe in (
            ("2026-07-14", 10, True),
            ("2026-07-15", 20, False),
            ("2026-07-16", 30, True),
        ):
            record_ids.append(
                conn.execute(
                    """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,
                           category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                    (
                        0,
                        record_day,
                        "{}",
                        "{}",
                        json.dumps({"counter.total.total": total}),
                        json.dumps({"counter.total.total": "no_charge"}),
                        json.dumps({"reconciliation": {"billing_safe": billing_safe}}),
                        now,
                        now,
                        1,
                        0,
                        0,
                        now,
                    ),
                ).fetchone()[0]
            )
    post_daily_record(record_ids[0])
    post_daily_record(record_ids[1])
    # The third row models a crash gap/pending legacy row and has no ledger event.
    # Mutating operational evidence after posting must not change frozen usage.
    with _open() as conn:
        conn.execute(
            "UPDATE daily_meter_records SET delta_json=? WHERE id=?",
            (json.dumps({"counter.total.total": 99}), record_ids[0]),
        )

    assert current_period_counters(0, today=date(2026, 7, 16)) == {"counter.total.total": 10.0}
    set_cfg("billing_day", "1")
    assert current_period_counters(0, today=date(2026, 7, 16)) == {"counter.total.total": 10.0}


def test_current_and_latest_counters_do_not_attach_old_identity_to_reused_slot(tmp_path):
    set_db_path(tmp_path / "slot-reuse-usage.db")
    init_db()
    set_cfg("billing_day", "31")
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = (
        ("2026-07-18", 10, "Printer A", "192.0.2.10", "SER-A"),
        ("2026-07-17", 20, "Printer B", "192.0.2.20", "SER-B"),
    )
    with _open() as conn:
        record_ids = [
            conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    0,
                    record_day,
                    "{}",
                    json.dumps({"counter.total.total": total + 100}),
                    json.dumps({"counter.total.total": total}),
                    json.dumps({"counter.total.total": "no_charge"}),
                    json.dumps(
                        {
                            "device_identity": {
                                "name": name,
                                "host": host,
                                "serial": serial,
                            },
                            "reconciliation": {"billing_safe": True},
                        }
                    ),
                    stamp,
                    stamp,
                    1,
                    0,
                    0,
                    stamp,
                ),
            ).fetchone()[0]
            for record_day, total, name, host, serial in rows
        ]
    for record_id in record_ids:
        post_daily_record(record_id)

    by_identity = current_period_counters_by_identity(0, today=date(2026, 7, 18))

    assert {
        item.device_identity: item.counters["counter.total.total"] for item in by_identity
    } == {"serial:SER-A": 10.0, "serial:SER-B": 20.0}
    assert current_period_counters(0, today=date(2026, 7, 18)) == {
        "counter.total.total": 20.0
    }
    assert latest_counters(0, today=date(2026, 7, 18)) == {
        "counter.total.total": 120.0
    }


def test_billing_period_uses_canonical_default_when_setting_is_absent(tmp_path):
    set_db_path(tmp_path / "default-billing-day.db")
    init_db()
    assert billing_period(date(2026, 7, 16)) == (date(2026, 6, 26), date(2026, 7, 16))
