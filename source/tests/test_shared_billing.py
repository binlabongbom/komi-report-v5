from datetime import date
import json
import sqlite3

import pytest
import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository
from services.slot_epoch_store import SlotEpochStore
from services.shared_billing import SharedBillingService
from services.monthly_history import load_usage_history
from test_billing_web_amendment import event, KEY


def setup():
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Office', '192.0.2.10', serial='SER-1')])
    database.set_cfg('billing_day', '31')
    database.set_cfg('waste_paper_pct', '2.5')
    PricingRepository().set_prices(0, date(2026,9,1), PriceList(a4_color=1.0))
    first = event(18,1000)
    store = SlotEpochStore()
    epoch = store.confirm(store.preview(0,first['id'],operation='initial',actor='A',reason='review'))
    event(21,1301,epoch)
    return SharedBillingService(today=lambda:date(2026,9,25)), epoch


def review(service):
    return service.preview(0,date(2026,9,18),date(2026,9,21))


def test_shared_accounting_is_reviewed_atomic_idempotent_and_conserves_report():
    service, epoch = setup()
    p = review(service)
    assert not p['blocked'] and len(p['ready']) == 1
    assert p['ready'][0]['day'] == '2026-09-20'
    with database._open(commit=False) as conn:
        assert not conn.execute('SELECT 1 FROM daily_meter_records').fetchone()
    ids = service.confirm(p, actor='tester', reason='Verified shared evidence')
    assert service.confirm(p, actor='tester', reason='Verified shared evidence') == ids
    with database._open(commit=False) as conn:
        raw = conn.execute('SELECT source_json,first_success,last_success,sample_count FROM daily_meter_records').fetchone()
        assert json.loads(raw[0])['kind'] == 'shared-web-reviewed'
        assert raw[1:] == (None,None,0)
        assert conn.execute('SELECT gross_cents,net_cents FROM billing_ledger').fetchone() == (30100,29348)
    records = load_usage_history([0],today=date(2026,9,25))
    assert sum(r.total for r in records) == 301
    assert sum(r.provisional_total for r in records) == 0
    assert sum(r.net_cost for r in records) == 293.48
    assert not review(service)['ready']


@pytest.mark.parametrize('change', ['evidence','price','policy'])
def test_changed_evidence_or_policy_requires_fresh_review(change):
    service, epoch = setup()
    p = review(service)
    if change == 'evidence':
        event(19,1100,epoch)
    elif change == 'price':
        PricingRepository().set_prices(0,date(2026,9,1),PriceList(a4_color=2))
    else:
        database.set_cfg('billing_day','25')
    with pytest.raises(ValueError,match='ตรวจใหม่'):
        service.confirm(p,actor='A',reason='review')
    with database._open(commit=False) as conn:
        assert not conn.execute('SELECT 1 FROM daily_meter_records').fetchone()
        assert not conn.execute('SELECT 1 FROM billing_ledger').fetchone()


def test_failed_receipt_rolls_back_source_and_immutable_ledger():
    service, _ = setup()
    p = review(service)
    with database._open() as conn:
        conn.execute("CREATE TRIGGER fail_shared_receipt BEFORE INSERT ON config_log BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):
        service.confirm(p,actor='A',reason='review')
    with database._open(commit=False) as conn:
        assert not conn.execute('SELECT 1 FROM billing_ledger').fetchone()
        assert not conn.execute('SELECT 1 FROM daily_meter_records').fetchone()


def test_legacy_overlap_is_not_reposted():
    from test_billing_web_amendment import setup as legacy_setup
    legacy_setup()
    p = review(SharedBillingService(today=lambda:date(2026,9,25)))
    assert not p['ready']
    assert any('existing_account_or_legacy_source' in r['reasons'] for r in p['blocked'])
