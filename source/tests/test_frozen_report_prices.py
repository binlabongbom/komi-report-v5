import json
from datetime import date

import pytest

from database import _open, init_db, set_db_path, set_cfg
from services.billing_ledger import post_daily_record, replace_entry, reverse_entry
from services.billing_repricing import BillingRepricingService
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import load_usage_history
from services.pricing import PriceList, PricingRepository
from services.report_excel_export import build_daily_category_costs


@pytest.fixture
def posted(tmp_path):
    set_db_path(tmp_path / 'synthetic.db')
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Synthetic', '192.0.2.10', serial='SYNTHETIC')])
    set_cfg('waste_paper_pct', '0')
    prices = PricingRepository()
    prices.set_prices(0, date(2026, 7, 1), PriceList(a4_bw=1, a4_color=2))
    with _open() as conn:
        record = conn.execute('''INSERT INTO daily_meter_records(device_slot,record_date,
            opening_json,closing_json,delta_json,category_json,source_json,first_success,last_success,
            sample_count,error_count,incomplete,created_at) VALUES(0,'2026-07-16','{}','{}',?,?,?,
            '2026-07-16T08:00:00','2026-07-16T09:00:00',2,0,0,'2026-07-16T09:00:00') RETURNING id''',
            (json.dumps({'a4_bw': 100, 'a4_color': 100}), json.dumps({'a4_bw': 'a4_bw', 'a4_color': 'a4_color'}),
             json.dumps({'reconciliation': {'billing_safe': True}}))).fetchone()[0]
    return post_daily_record(record), prices


def costs():
    records = tuple(load_usage_history([0], granularity='daily', today=date(2026, 7, 17)))
    return build_daily_category_costs(records)


def test_historical_price_edit_cannot_shift_frozen_report_allocation(posted):
    _entry, prices = posted
    before = costs()
    assert (before[0].a4_bw, before[0].a4_color, before[0].total) == (100, 200, 300)
    prices.set_prices(0, date(2026, 7, 1), PriceList(a4_bw=1, a4_color=3))
    assert costs() == before


def test_reviewed_reprice_uses_replacement_snapshot(posted):
    entry, prices = posted
    prices.set_prices(0, date(2026, 7, 1), PriceList(a4_bw=1, a4_color=3))
    service = BillingRepricingService()
    preview = service.preview(entry)
    service.confirm(entry, expected_revision=preview['revision'], actor='synthetic', reason='synthetic review')
    result = costs()[0]
    assert (result.a4_bw, result.a4_color, result.total) == (100, 300, 400)
    prices.set_prices(0, date(2026, 7, 1), PriceList(a4_bw=9, a4_color=9))
    assert costs()[0] == result


def test_manual_amount_remains_unallocated_instead_of_inventing_price(posted):
    entry, _prices = posted
    replace_entry(entry, gross_cents=1000, net_cents=1000, reason='synthetic manual amount')
    result = costs()[0]
    assert result.unallocated == 10
    assert result.a4_bw == result.a4_color == 0


def test_reversal_does_not_resurrect_old_category_amount(posted):
    entry, _prices = posted
    reverse_entry(entry, reason='synthetic reversal')
    assert all(result.total == 0 for result in costs())


def test_quantity_rounded_categories_are_not_redistributed_using_gross_weights(posted):
    entry, _prices = posted
    from services.billing_repricing import BillingRepricingService
    set_cfg('waste_paper_pct', '99.5')
    service = BillingRepricingService()
    preview = service.preview(entry, apply_current_discount=True)
    service.confirm(entry, expected_revision=preview['revision'], actor='synthetic', reason='rounding test', apply_current_discount=True)
    result = costs()[0]
    # Each 100-page category becomes 1 billable page (.5 rounds up).
    assert (result.a4_bw, result.a4_color, result.total) == (1, 2, 3)
