from __future__ import annotations

import json
from datetime import date, datetime

from database import _open, init_db, set_cfg, set_db_path
from services.billing_v5 import period_gross_cost, period_net_cost
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository


def test_period_cost_uses_effective_price_and_global_discount(tmp_path):
    set_db_path(tmp_path / "billing.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2.0))
    set_cfg("billing_day", "25")
    set_cfg("waste_paper_pct", "2")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        conn.execute(
            """INSERT INTO daily_meter_records(
                   device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                   source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                0,
                "2026-07-16",
                "{}",
                "{}",
                json.dumps({"counter.paper.full_color.a4": 100}),
                json.dumps({"counter.paper.full_color.a4": "a4_color"}),
                json.dumps({"reconciliation": {"billing_safe": True}}),
                now,
                now,
                1,
                0,
                0,
                now,
            ),
        )

    from services.billing_ledger import post_daily_record
    with _open(commit=False) as conn:
        record_id = conn.execute("SELECT id FROM daily_meter_records").fetchone()[0]
    post_daily_record(record_id)
    assert period_gross_cost(0, today=date(2026, 7, 16)) == 200.0
    assert period_net_cost([0], today=date(2026, 7, 16)) == (200.0, 2.0, 196.0)

    # Mutable settings must not move already-frozen money out of the active view.
    set_cfg("billing_day", "1")
    assert period_gross_cost(0, today=date(2026, 7, 16)) == 200.0
    assert period_net_cost([0], today=date(2026, 7, 16)) == (200.0, 2.0, 196.0)


def test_current_device_cost_excludes_old_identity_but_overall_total_keeps_it(tmp_path):
    set_db_path(tmp_path / "slot-reuse-cost.db")
    init_db()
    set_cfg("billing_day", "31")
    set_cfg("waste_paper_pct", "0")
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    source_rows = (
        ("2026-07-15", 10, "Printer A", "192.0.2.10", "SER-A"),
        ("2026-07-16", 20, "Printer B", "192.0.2.20", "SER-B"),
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
                    "{}",
                    json.dumps({"billing.a4_color.pages": pages}),
                    json.dumps({"billing.a4_color.pages": "a4_color"}),
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
                    now,
                    now,
                    1,
                    0,
                    0,
                    now,
                ),
            ).fetchone()[0]
            for record_day, pages, name, host, serial in source_rows
        ]
    from services.billing_ledger import post_daily_record

    for record_id in record_ids:
        post_daily_record(record_id)

    assert period_gross_cost(0, today=date(2026, 7, 16)) == 20.0
    assert period_net_cost([0], today=date(2026, 7, 16)) == (30.0, 0.0, 30.0)
