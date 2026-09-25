"""Repeated setup prices must not manufacture meter-interval review holds."""
from dataclasses import replace
from datetime import UTC, date
from threading import Event

import pytest

import database
from komi_snmp_profiler.credential_store import SessionCredentialStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import load_usage_history
from services.pricing import PriceList, PricingRepository, price_change_dates
from services.setup_settings import SetupSettingsService
from services.shared_report_history import load_shared_counter_days
from services.slot_epoch_store import SlotEpochStore
from services.web_evidence_report import inspect_counter, load_evidence
from services.web_usage_projection import CounterIdentity
from test_billing_web_amendment import event, setup as amendment_setup


def test_rate_boundaries_keep_first_zero_real_changes_and_reversions():
    DeviceConfigRepository().replace_all([
        DeviceConfig(0, 'Office', '192.0.2.10'), DeviceConfig(1, 'Annex', '192.0.2.11')])
    repository = PricingRepository()
    rates = PriceList()
    for day, value in ((22, rates), (23, rates),
                       (24, replace(rates, a3_bw=.2)),
                       (25, replace(rates, a3_bw=.2)), (26, rates)):
        repository.set_prices(0, date(2026, 9, day), value)
    repository.set_prices(1, date(2026, 9, 25), PriceList(a4_color=9))
    with database._open(commit=False) as conn:
        before = conn.execute('SELECT * FROM price_history ORDER BY id').fetchall()
        assert price_change_dates(conn, 0) == tuple(date(2026, 9, day) for day in (22, 24, 26))
        assert price_change_dates(conn, 1) == (date(2026, 9, 25),)
        assert price_change_dates(conn, 2) == ()
        assert conn.execute('SELECT * FROM price_history ORDER BY id').fetchall() == before


@pytest.mark.parametrize('changed_field', [None, 'a3_color', 'a3_bw', 'a4_color', 'a4_bw'])
def test_wizard_resave_identical_prices_keeps_report_cost_and_inspection_available(changed_field):
    repository = DeviceConfigRepository(SessionCredentialStore())
    service = SetupSettingsService(repository)
    devices = [DeviceConfig(0, 'Office', '192.0.2.10', serial='SER-1')]
    settings = {'company_name': 'Synthetic company', 'client_first_started_at': '2026-09-22',
                'billing_day': '31', 'waste_paper_pct': '0'}
    original = PriceList(a4_color=1)
    service.commit(service.preview(devices, settings, [(0, date(2026, 9, 22), original)]))
    store = SlotEpochStore()
    anchor = event(24, 1000)
    epoch = store.confirm(store.preview(0, anchor['id'], operation='initial', actor='test', reason='initial meter'))
    event(25, 1025, epoch)
    updated = replace(original, **{changed_field: 2}) if changed_field else original
    # Exercise the same Wizard persistence path that adds a dated price row
    # when a user edits the device list and leaves the existing rates alone.
    service.commit(service.preview(repository.list(), settings, [(0, date(2026, 9, 25), updated)]))
    with database._open(commit=False) as conn:
        before = conn.execute('SELECT * FROM price_history ORDER BY id').fetchall()
        rows = load_shared_counter_days(conn, [0], kind='device')
    held = {flag for row in rows for flag in row.issues}
    assert ('interval_crosses_price_change' in held) == bool(changed_field)
    usage = load_usage_history([0], today=date(2026, 9, 25))
    assert len(usage) == 1 and usage[0].provisional_total == 25
    assert usage[0].provisional_cost_available == (changed_field is None)
    if changed_field is None:
        assert usage[0].provisional_net_cost == 25
        assert not usage[0].incomplete_days
    args = dict(slot=0, serial='SER-1', start=date(2026, 9, 24), end=date(2026, 9, 25),
                calendar_timezone=UTC)
    evidence = load_evidence(database.get_db_path(), **args, cancelled=Event())
    projection = inspect_counter(evidence, CounterIdentity('counter.total.total'), **args, epoch_id=epoch)
    assert projection.total_usage == 25
    assert any('interval_crosses_price_change' in interval.holds for interval in projection.intervals) == bool(changed_field)
    with database._open(commit=False) as conn:
        assert conn.execute('SELECT * FROM price_history ORDER BY id').fetchall() == before
        assert len(before) == 2  # Preserve both historical Wizard saves.


def test_first_price_still_holds_interval_starting_before_price_evidence():
    from test_shared_report_history import setup, receive, event_at, shared
    from datetime import datetime
    anchor, epoch = setup(datetime(2026, 9, 24, 8, tzinfo=UTC))
    receive(event_at(anchor, epoch, 125, datetime(2026, 9, 25, 8, tzinfo=UTC)), epoch)
    PricingRepository().set_prices(0, date(2026, 9, 25), PriceList())
    assert any('interval_crosses_price_change' in row.issues for row in shared())


def test_real_price_change_after_unchanged_overnight_meter_prices_later_usage():
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='SER-1')])
    database.set_cfg('billing_day', '31')
    database.set_cfg('waste_paper_pct', '0')
    pricing = PricingRepository()
    pricing.set_prices(0, date(2026, 9, 22), PriceList(a4_color=1))
    pricing.set_prices(0, date(2026, 9, 25), PriceList(a4_color=2))
    store = SlotEpochStore()
    anchor = event(24, 1000)
    epoch = store.confirm(store.preview(0, anchor['id'], operation='initial', actor='test', reason='initial meter'))
    event(25, 1000, epoch, hour=8)
    event(25, 1025, epoch, hour=9)
    with database._open(commit=False) as conn:
        rows = load_shared_counter_days(conn, [0], kind='device')
    assert not {flag for row in rows for flag in row.issues}
    usage = load_usage_history([0], today=date(2026, 9, 25))
    assert len(usage) == 1 and usage[0].provisional_total == 25
    assert usage[0].provisional_cost_available
    assert usage[0].provisional_net_cost == 50


@pytest.mark.parametrize('amount', [1, 2])
def test_amendment_ignores_duplicate_rates_but_keeps_real_boundary_blocked(amount):
    service, args, _ledger = amendment_setup()
    before = service.preview(*args)
    PricingRepository().set_prices(0, date(2026, 9, 20), PriceList(a4_color=amount))
    if amount == 2:
        with pytest.raises(ValueError, match='คร่อมราคา'):
            service.preview(*args)
    else:
        after = service.preview(*args)
        assert after['old_net_cents'] == after['net_cents'] == before['net_cents'] == 30100
        assert after['changed'] == before['changed']
