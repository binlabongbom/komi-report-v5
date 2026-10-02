import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import database
from services.billing_ledger import post_daily_record
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository
from services.summary_service import build_overview_summary, months_ago


def _reading(date: str, *, total: int, color: int, bw: int) -> dict:
    return {
        "machine_name": "Service Test",
        "serial": "SN-SVC",
        "date": date,
        "mode": "summary",
        "total_counter": total,
        "summary": {"total_color": color, "total_bw": bw, "total": total},
        "paper_color": {"a4_color": color, "a4_bw": bw, "a3_color": 0, "a3_bw": 0},
        "detail": {},
        "warnings": [],
    }


class SummaryServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_path = database.get_db_path()
        self.tmp = tempfile.TemporaryDirectory()
        database.set_db_path(Path(self.tmp.name) / "summary.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "25")

    def tearDown(self):
        database.set_db_path(self.original_path)
        self.tmp.cleanup()

    def test_months_ago_crosses_year(self):
        self.assertEqual(months_ago("2026-01", 3), "2025-10")

    def test_build_overview_summary_current_uses_latest_data_when_current_empty(self):
        database.save_reading(0, _reading("2026/06/20", total=100, color=40, bw=60), "june.txt")

        summary = build_overview_summary("current", now=datetime(2026, 7, 9))

        self.assertEqual(summary["filtered_months"], ["2026-06"])
        self.assertEqual(summary["metrics"]["total"], 100)
        self.assertEqual(summary["machine_values"], [100, 0, 0])

    def test_build_overview_summary_all_combines_slots(self):
        database.save_reading(0, _reading("2026/07/20", total=100, color=40, bw=60), "slot0.txt")
        database.save_reading(1, _reading("2026/07/20", total=50, color=20, bw=30), "slot1.txt")

        summary = build_overview_summary("all", now=datetime(2026, 7, 21))

        self.assertEqual(summary["metrics"]["total"], 150)
        self.assertEqual(summary["metrics"]["total_color"], 60)
        self.assertEqual(summary["machine_values"], [100, 50, 0])

    def test_v5_overview_uses_frozen_ledger_and_excludes_held_usage(self):
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Ledger Printer", "192.0.2.10", serial="SER-A")]
        )
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2.0))
        database.set_cfg("billing_day", "31")
        database.set_cfg("waste_paper_pct", "10")
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        record_ids = []
        with database._open() as conn:
            for record_day, total, safe in (
                ("2026-07-15", 10, True),
                ("2026-07-16", 99, False),
            ):
                deltas = {
                    "counter.total.total": total,
                    "counter.print.total": total,
                    "counter.print.full_color_total": total,
                    "counter.print.full_color_large": 0,
                    "billing.a4_color.pages": total,
                }
                categories = {key: "no_charge" for key in deltas}
                categories["billing.a4_color.pages"] = "a4_color"
                record_ids.append(
                    conn.execute(
                        """INSERT INTO daily_meter_records(
                               device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                               source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                        (
                            0,
                            record_day,
                            "{}",
                            "{}",
                            json.dumps(deltas),
                            json.dumps(categories),
                            json.dumps({"reconciliation": {"billing_safe": safe}}),
                            stamp,
                            stamp,
                            1,
                            0,
                            0,
                            stamp,
                        ),
                    ).fetchone()[0]
                )
        for record_id in record_ids:
            post_daily_record(record_id)

        before = build_overview_summary("current", now=datetime(2026, 7, 16, 12, 0))
        PricingRepository().set_prices(0, date(2026, 7, 16), PriceList(a4_color=9.0))
        database.set_cfg("waste_paper_pct", "50")
        after = build_overview_summary("current", now=datetime(2026, 7, 16, 12, 0))

        self.assertEqual(before["source"], "billing_ledger")
        self.assertEqual(before["metrics"]["total"], 10)
        self.assertEqual(before["metrics"]["cost"], 18)
        self.assertEqual(before["quality"]["held_days"], 1)
        self.assertEqual(after["metrics"]["total"], 10)
        self.assertEqual(after["metrics"]["cost"], 18)

    def test_v5_current_overview_includes_all_overlapping_frozen_cycles(self):
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Ledger Printer", "192.0.2.10", serial="SER-A")]
        )
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")

        def post_day(record_day: str, total: int, billing_day: int) -> None:
            database.set_cfg("billing_day", str(billing_day))
            with database._open() as conn:
                record_id = conn.execute(
                    """INSERT INTO daily_meter_records(
                           device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                           source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                    (
                        0,
                        record_day,
                        "{}",
                        "{}",
                        json.dumps({"counter.total.total": total}),
                        json.dumps({"counter.total.total": "no_charge"}),
                        json.dumps({"reconciliation": {"billing_safe": True}}),
                        stamp,
                        stamp,
                        1,
                        0,
                        0,
                        stamp,
                    ),
                ).fetchone()[0]
            post_daily_record(record_id)

        post_day("2026-07-14", 10, 25)
        post_day("2026-07-15", 20, 1)

        summary = build_overview_summary("current", now=datetime(2026, 7, 16, 12, 0))

        self.assertEqual(set(summary["filtered_months"]), {"2026-07", "2026-08"})
        self.assertEqual(summary["metrics"]["total"], 30)

    def test_v5_current_overview_does_not_include_expired_cycle_with_same_month_key(self):
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Ledger Printer", "192.0.2.10", serial="SER-A")]
        )
        PricingRepository().set_prices(0, date(2026, 6, 1), PriceList())
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")

        def post_day(record_day: str, total: int, billing_day: int) -> None:
            database.set_cfg("billing_day", str(billing_day))
            with database._open() as conn:
                record_id = conn.execute(
                    """INSERT INTO daily_meter_records(
                           device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                           source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                    (
                        0,
                        record_day,
                        "{}",
                        "{}",
                        json.dumps({"counter.total.total": total}),
                        json.dumps({"counter.total.total": "no_charge"}),
                        json.dumps({"reconciliation": {"billing_safe": True}}),
                        stamp,
                        stamp,
                        1,
                        0,
                        0,
                        stamp,
                    ),
                ).fetchone()[0]
            post_daily_record(record_id)

        # Both frozen periods end in July, but only the latter is active on 16 July.
        post_day("2026-07-01", 10, 1)
        post_day("2026-07-15", 20, 31)

        summary = build_overview_summary("current", now=datetime(2026, 7, 16, 12, 0))

        self.assertEqual(summary["filtered_months"], ["2026-07"])
        self.assertEqual(summary["metrics"]["total"], 20)

    def test_v5_overview_flags_mixed_identities_without_losing_frozen_totals(self):
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")]
        )
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
        database.set_cfg("billing_day", "31")
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        source_rows = (
            ("2026-07-15", 10, "Printer A", "192.0.2.10", "SER-A"),
            ("2026-07-16", 20, "Printer B", "192.0.2.20", "SER-B"),
        )
        with database._open() as conn:
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
                        "{}",
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
                for record_day, total, name, host, serial in source_rows
            ]
        for record_id in record_ids:
            post_daily_record(record_id)

        summary = build_overview_summary("current", now=datetime(2026, 7, 16, 12, 0))

        self.assertEqual(summary["metrics"]["total"], 30)
        self.assertEqual(summary["machine_values"], [30])
        self.assertIn("Printer A (SER-A)", summary["machine_names"][0])
        self.assertIn("Printer B (SER-B)", summary["machine_names"][0])
        self.assertEqual(summary["quality"]["mixed_identity_slots"], [0])
        self.assertEqual(summary["quality"]["historical_identity_slots"], [0])

    def test_v5_overview_keeps_frozen_history_after_slot_is_disabled(self):
        repository = DeviceConfigRepository()
        repository.replace_all(
            [
                DeviceConfig(0, "Current Printer", "192.0.2.10", serial="SER-CURRENT"),
                DeviceConfig(1, "Retired Printer", "192.0.2.11", serial="SER-OLD"),
            ]
        )
        PricingRepository().set_prices(1, date(2026, 7, 1), PriceList())
        database.set_cfg("billing_day", "31")
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    1,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps({"counter.total.total": 40}),
                    json.dumps({"counter.total.total": "no_charge"}),
                    json.dumps(
                        {
                            "device_identity": {
                                "name": "Retired Printer",
                                "host": "192.0.2.11",
                                "serial": "SER-OLD",
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
        post_daily_record(record_id)
        repository.replace_all(
            [DeviceConfig(0, "Current Printer", "192.0.2.10", serial="SER-CURRENT")]
        )

        summary = build_overview_summary("current", now=datetime(2026, 7, 16, 12, 0))

        self.assertEqual(summary["metrics"]["total"], 40)
        self.assertEqual(summary["machine_values"], [0, 40])
        self.assertEqual(summary["machine_names"][1], "Retired Printer (SER-OLD)")
        self.assertEqual(summary["quality"]["historical_identity_slots"], [1])

    def test_v5_overview_separates_confirmed_and_current_cache(self):
        DeviceConfigRepository().replace_all(
            [
                DeviceConfig(
                    0,
                    "Today Printer",
                    "192.0.2.10",
                    serial="SER-TODAY",
                    connection_status="online",
                    last_checked_at="2026-07-16T11:59:00+07:00",
                    last_success_at="2026-07-16T11:59:00+07:00",
                )
            ]
        )
        PricingRepository().set_prices(
            0,
            date(2026, 7, 1),
            PriceList(a3_color=3.0, a4_color=2.0),
        )
        database.set_cfg("billing_day", "31")
        database.set_cfg("waste_paper_pct", "2")
        cache_path = (
            database.get_db_path().parent
            / "runtime-cache"
            / "device-1"
            / "2026-07-16.json"
        )
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": "komi.daily.cache.v2",
                    "device_slot": 0,
                    "record_date": "2026-07-16",
                    "opening": {},
                    "latest": {},
                    "delta": {
                        "counter.total.total": 10,
                        "counter.print.total": 10,
                        "counter.print.full_color_total": 10,
                        "counter.print.full_color_large": 2,
                        "counter.paper.full_color.a4": 8,
                        "counter.paper.full_color.a3": 2,
                    },
                    "source": {"reconciliation": {"billing_safe": True}},
                    "first_success": "2026-07-16T08:00:00+07:00",
                    "last_success": "2026-07-16T11:59:00+07:00",
                    "sample_count": 2,
                    "error_count": 0,
                    "resets": [],
                    "device_identity": {
                        "name": "Today Printer",
                        "host": "192.0.2.10",
                        "serial": "SER-TODAY",
                    },
                }
            ),
            encoding="utf-8",
        )

        summary = build_overview_summary(
            "current",
            now=datetime.fromisoformat("2026-07-16T12:00:00+07:00"),
        )

        self.assertEqual(summary["metrics"]["total"], 0)
        self.assertEqual(summary["metrics"]["provisional_total"], 10)
        self.assertEqual(summary["metrics"]["display_total"], 10)
        self.assertEqual(summary["metrics"]["provisional_cost"], 21.56)
        self.assertEqual(summary["machine_values"], [10])
        self.assertEqual(summary["quality"]["provisional_days"], 1)
        self.assertEqual(summary["quality"]["status_counts"]["online"], 1)
        self.assertEqual(summary["devices"][0]["provisional_total"], 10)
        self.assertEqual(summary["devices"][0]["display_cost"], 21.56)


if __name__ == "__main__":
    unittest.main()
