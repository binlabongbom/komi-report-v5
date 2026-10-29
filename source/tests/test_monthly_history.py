import json
from datetime import date, datetime

import database
from services.billing_ledger import approve_held_entry, post_daily_record
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import (
    billing_month_range,
    history_period_range,
    load_monthly_usage,
    load_usage_history,
)
from services.pricing import PriceList, PricingRepository


def test_billing_month_range_uses_configured_end_day_and_month_end_fallback():
    assert billing_month_range(date(2026, 7, 16), 1) == (date(2026, 7, 2), date(2026, 8, 1))
    assert billing_month_range(date(2026, 7, 24), 25) == (date(2026, 6, 26), date(2026, 7, 25))
    assert billing_month_range(date(2026, 2, 28), 31) == (date(2026, 2, 1), date(2026, 2, 28))


def test_history_periods_follow_configured_billing_cycle():
    assert history_period_range(date(2026, 7, 3), 25, "daily") == (
        date(2026, 7, 3),
        date(2026, 7, 3),
    )
    assert history_period_range(date(2026, 7, 3), 25, "weekly") == (
        date(2026, 7, 3),
        date(2026, 7, 9),
    )
    assert history_period_range(date(2026, 7, 25), 25, "weekly") == (
        date(2026, 7, 24),
        date(2026, 7, 25),
    )
    assert history_period_range(date(2026, 7, 3), 25, "monthly") == (
        date(2026, 6, 26),
        date(2026, 7, 25),
    )
    assert history_period_range(date(2026, 7, 3), 25, "quarterly") == (
        date(2026, 6, 26),
        date(2026, 9, 25),
    )
    assert history_period_range(date(2026, 7, 3), 25, "yearly") == (
        date(2025, 12, 26),
        date(2026, 12, 25),
    )


def test_monthly_usage_aggregates_daily_records_with_effective_price(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "monthly.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "1")
        database.set_cfg("waste_paper_pct", "2")
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer 1", "192.0.2.10")])
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2.0))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        deltas = {
            "counter.total.total": 100,
            "counter.print.total": 100,
            "counter.print.full_color_total": 100,
            "counter.print.full_color_large": 10,
            "billing.a4_color.pages": 100,
            "counter.scan_fax.document_read_total": 7,
        }
        categories = {key: "no_charge" for key in deltas}
        categories["billing.a4_color.pages"] = "a4_color"
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps(deltas),
                    json.dumps(categories),
                    json.dumps({"reconciliation": {"billing_safe": True}}),
                    now,
                    now,
                    2,
                    0,
                    0,
                    now,
                ),
            ).lastrowid

        post_daily_record(record_id)

        records = load_monthly_usage([0], today=date(2026, 7, 16))

        assert len(records) == 1
        record = records[0]
        assert record.period_start == date(2026, 7, 2)
        assert record.period_end == date(2026, 8, 1)
        assert record.total == 100
        assert record.a3_color == 10
        assert record.a4_color == 90
        assert record.scan == 7
        assert record.gross_cost == 200
        assert record.net_cost == 196
    finally:
        database.set_db_path(original_path)


def test_fallback_total_includes_print_and_copy_other_sizes(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "other-fallback.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "31")
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Printer 1", "192.0.2.10", serial="SER-001")]
        )
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        deltas = {
            "mapped.print.other.total": 4,
            "mapped.copy.other.total": 6,
        }
        with database._open() as connection:
            record_id = connection.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,
                       category_json,source_json,first_success,last_success,
                       sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-15",
                    "{}",
                    "{}",
                    json.dumps(deltas),
                    json.dumps({key: "no_charge" for key in deltas}),
                    json.dumps(
                        {
                            "device_identity": {
                                "name": "Printer 1",
                                "serial": "SER-001",
                            },
                            "reconciliation": {"billing_safe": True},
                        }
                    ),
                    now,
                    now,
                    2,
                    0,
                    0,
                    now,
                ),
            ).lastrowid

        post_daily_record(record_id)
        record = load_monthly_usage([0], today=date(2026, 7, 16))[0]

        assert record.print_other == 4
        assert record.copy_other == 6
        assert record.total == 10
    finally:
        database.set_db_path(original_path)


def test_monthly_usage_keeps_slot_reuse_identities_as_separate_rows(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "identity-rollover.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "31")
        database.set_cfg("waste_paper_pct", "0")
        repository = DeviceConfigRepository()
        repository.replace_all(
            [DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")]
        )
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
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

        records = load_monthly_usage([0], today=date(2026, 7, 16))

        assert len(records) == 2
        assert {
            (
                record.device_identity,
                record.device_name_snapshot,
                record.device_serial_snapshot,
                record.total,
            )
            for record in records
        } == {
            ("serial:SER-A", "Printer A", "SER-A", 10),
            ("serial:SER-B", "Printer B", "SER-B", 20),
        }
        assert sum(record.total for record in records) == 30
    finally:
        database.set_db_path(original_path)


def test_usage_history_groups_daily_records_into_billing_aligned_weeks(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "weekly.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "25")
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer 1", "192.0.2.10")])
        PricingRepository().set_prices(0, date(2026, 6, 1), PriceList())
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with database._open() as conn:
            for record_day, total in (("2026-06-26", 2), ("2026-07-02", 3), ("2026-07-03", 5)):
                conn.execute(
                    """INSERT INTO daily_meter_records(
                           device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                           source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        0,
                        record_day,
                        "{}",
                        "{}",
                        json.dumps({"counter.total.total": total}),
                        json.dumps({"counter.total.total": "no_charge"}),
                        json.dumps({"reconciliation": {"billing_safe": True}}),
                        now,
                        now,
                        2,
                        0,
                        0,
                        now,
                    ),
                )

        with database._open(commit=False) as conn:
            record_ids = [row[0] for row in conn.execute("SELECT id FROM daily_meter_records ORDER BY id").fetchall()]
        for record_id in record_ids:
            post_daily_record(record_id)

        records = load_usage_history([0], granularity="weekly", today=date(2026, 7, 4))

        assert [(record.period_start, record.period_end, record.total) for record in records] == [
            (date(2026, 7, 3), date(2026, 7, 9), 5),
            (date(2026, 6, 26), date(2026, 7, 2), 5),
        ]
    finally:
        database.set_db_path(original_path)


def test_usage_history_holds_explicitly_unsafe_record_out_of_billing(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "unsafe.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "31")
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer 1", "192.0.2.10")])
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2.0))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps({"billing.a4_color.pages": 10, "counter.total.total": 10}),
                    json.dumps({"billing.a4_color.pages": "a4_color", "counter.total.total": "no_charge"}),
                    json.dumps({"reconciliation": {"billing_safe": False}}),
                    now,
                    now,
                    2,
                    0,
                    0,
                    now,
                ),
            ).lastrowid

        post_daily_record(record_id)

        records = load_monthly_usage([0], today=date(2026, 7, 16))

        assert len(records) == 1
        assert records[0].total == 0
        assert records[0].gross_cost == 0
        assert records[0].net_cost == 0
        assert records[0].day_count == 0
        assert records[0].held_days == 1
    finally:
        database.set_db_path(original_path)


def test_usage_history_holds_current_unsafe_cache_out_of_billing(tmp_path):
    class UnsafeCache:
        def load(self, _slot, _day):
            return {
                "delta": {"counter.total.total": 12},
                "source": {"reconciliation": {"billing_safe": False}},
            }

    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "unsafe-cache.sqlite3")
        database.init_db()
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer 1", "192.0.2.10")])

        records = load_monthly_usage([0], today=date(2026, 7, 16), cache=UnsafeCache())

        assert len(records) == 1
        assert records[0].total == 0
        assert records[0].held_days == 1
    finally:
        database.set_db_path(original_path)


def test_usage_history_shows_safe_current_cache_as_provisional_without_posting(tmp_path):
    class SafeCache:
        def load(self, _slot, _day):
            return {
                "first_success": "2026-07-16T08:00:00+07:00",
                "delta": {
                    "counter.total.total": 10,
                    "counter.print.total": 10,
                    "counter.print.full_color_total": 10,
                    "counter.print.full_color_large": 2,
                    "counter.paper.full_color.a4": 8,
                    "counter.paper.full_color.a3": 2,
                },
                "source": {"reconciliation": {"billing_safe": True}},
                "device_identity": {
                    "name": "Printer 1",
                    "host": "192.0.2.10",
                    "serial": "SER-A",
                },
            }

    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "safe-current-cache.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "31")
        database.set_cfg("waste_paper_pct", "2")
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Printer 1", "192.0.2.10", serial="SER-A")]
        )
        PricingRepository().set_prices(
            0,
            date(2026, 7, 1),
            PriceList(a3_color=3.0, a4_color=2.0),
        )

        record = load_monthly_usage(
            [0],
            today=date(2026, 7, 16),
            cache=SafeCache(),
        )[0]

        assert record.total == 0
        assert record.gross_cost == 0
        assert record.net_cost == 0
        assert record.day_count == 0
        assert record.held_days == 0
        assert record.provisional_total == 10
        assert record.provisional_a3_color == 2
        assert record.provisional_a4_color == 8
        assert record.provisional_print_color == 10
        assert record.provisional_print_bw == 0
        assert record.provisional_copy_color == 0
        assert record.provisional_copy_bw == 0
        assert record.provisional_gross_cost == 22
        assert record.provisional_net_cost == 22
        assert record.provisional_days == 1
        assert record.provisional_cost_available is True
        with database._open(commit=False) as conn:
            assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 0
    finally:
        database.set_db_path(original_path)


def test_usage_history_keeps_safe_current_usage_when_pricelist_is_missing(tmp_path):
    class SafeCache:
        def load(self, _slot, _day):
            return {
                "first_success": "2026-07-16T08:00:00+07:00",
                "delta": {
                    "counter.total.total": 4,
                    "counter.print.total": 4,
                    "counter.print.bw_total": 4,
                    "counter.paper.black.a4": 4,
                },
                "source": {"reconciliation": {"billing_safe": True}},
                "device_identity": {
                    "name": "Printer 1",
                    "host": "192.0.2.10",
                    "serial": "SER-A",
                },
            }

    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "missing-current-price.sqlite3")
        database.init_db()
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Printer 1", "192.0.2.10", serial="SER-A")]
        )

        record = load_monthly_usage(
            [0],
            today=date(2026, 7, 16),
            cache=SafeCache(),
        )[0]

        assert record.provisional_total == 4
        assert record.provisional_a4_bw == 4
        assert record.provisional_print_bw == 4
        assert record.provisional_cost_available is False
        assert record.provisional_gross_cost == 0
        assert record.held_days == 0
    finally:
        database.set_db_path(original_path)


def test_history_uses_frozen_ledger_price_waste_and_period_after_settings_change(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "frozen-history.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "25")
        database.set_cfg("waste_paper_pct", "2")
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer 1", "192.0.2.10", serial="SER-A")])
        pricing = PricingRepository()
        pricing.set_prices(0, date(2026, 7, 1), PriceList(a4_color=2.0))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        deltas = {"billing.a4_color.pages": 100, "counter.total.total": 100}
        categories = {"billing.a4_color.pages": "a4_color", "counter.total.total": "no_charge"}
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,
                       category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps(deltas),
                    json.dumps(categories),
                    json.dumps({"reconciliation": {"billing_safe": True}}),
                    now,
                    now,
                    1,
                    0,
                    0,
                    now,
                ),
            ).lastrowid
        post_daily_record(record_id)

        pricing.set_prices(0, date(2026, 7, 1), PriceList(a4_color=99.0))
        database.set_cfg("waste_paper_pct", "50")
        database.set_cfg("billing_day", "1")
        record = load_monthly_usage([0], today=date(2026, 7, 16))[0]

        assert (record.period_start, record.period_end) == (date(2026, 6, 26), date(2026, 7, 25))
        assert record.total == 100
        assert record.gross_cost == 200
        assert record.net_cost == 196
    finally:
        database.set_db_path(original_path)


def test_history_remains_from_ledger_after_daily_source_is_changed_or_deleted(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "ledger-is-canonical.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "31")
        DeviceConfigRepository().replace_all(
            [DeviceConfig(0, "Printer 1", "192.0.2.10", serial="SER-A")]
        )
        PricingRepository().set_prices(
            0, date(2026, 7, 1), PriceList(a4_color=2.0)
        )
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,
                       category_json,source_json,first_success,last_success,
                       sample_count,error_count,incomplete,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps(
                        {
                            "billing.a4_color.pages": 30,
                            "counter.total.total": 30,
                        }
                    ),
                    json.dumps(
                        {
                            "billing.a4_color.pages": "a4_color",
                            "counter.total.total": "no_charge",
                        }
                    ),
                    json.dumps({"reconciliation": {"billing_safe": True}}),
                    now,
                    now,
                    1,
                    0,
                    0,
                    now,
                ),
            ).lastrowid
        post_daily_record(record_id)

        baseline = load_monthly_usage([0], today=date(2026, 7, 16))[0]
        assert (baseline.total, baseline.gross_cost, baseline.net_cost) == (30, 60, 58)

        with database._open() as conn:
            conn.execute(
                "UPDATE daily_meter_records SET delta_json='{}', source_json='{}' WHERE id=?",
                (record_id,),
            )
        changed = load_monthly_usage([0], today=date(2026, 7, 16))[0]
        assert changed == baseline

        with database._open() as conn:
            conn.execute("DELETE FROM daily_meter_records WHERE id=?", (record_id,))
        deleted = load_monthly_usage([0], today=date(2026, 7, 16))[0]
        assert deleted == baseline
    finally:
        database.set_db_path(original_path)


def test_approved_hold_replacement_restores_usage_and_frozen_manual_cost(tmp_path):
    original_path = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "approved-hold-history.sqlite3")
        database.init_db()
        database.set_cfg("billing_day", "31")
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer 1", "192.0.2.10", serial="SER-A")])
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2.0))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        deltas = {"billing.a4_color.pages": 10, "counter.total.total": 10}
        categories = {"billing.a4_color.pages": "a4_color", "counter.total.total": "no_charge"}
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,
                       category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps(deltas),
                    json.dumps(categories),
                    json.dumps({"reconciliation": {"billing_safe": False}}),
                    now,
                    now,
                    1,
                    0,
                    0,
                    now,
                ),
            ).lastrowid
        hold_id = post_daily_record(record_id)
        approve_held_entry(hold_id, gross_cents=2_000, net_cents=1_900, reason="approved corrected evidence")

        record = load_monthly_usage([0], today=date(2026, 7, 16))[0]
        assert record.total == 10
        assert record.gross_cost == 20
        assert record.net_cost == 19
        assert record.day_count == 1
        assert record.held_days == 0
    finally:
        database.set_db_path(original_path)
