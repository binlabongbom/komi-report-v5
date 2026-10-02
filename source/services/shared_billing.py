"""Explicit first accounting of shared Web history; issued rows stay immutable.

Derived daily sources are labelled with their real evidence. Missing-day
allocations have no invented successful reads. Closed/legacy overlaps must use
the existing amendment workflow, never a second first posting.
"""
from datetime import date, datetime, UTC
import hashlib
import json
from pathlib import Path

from database import _open, get_db_path, config_write_transaction
from services.billing_ledger import post_daily_record, _cents, _basis_points
from services.pricing import PricingRepository, CostCategory
from services.shared_report_history import load_shared_counter_days
from services.reconciliation import reconcile_web_counters
from services.peer_change_events import notify_local_change


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class SharedBillingService:
    def __init__(self, *, today=date.today):
        self.path = Path(get_db_path()).resolve()
        self.today = today

    def _preview(self, conn, slot, start, end):
        if type(slot) is not int or slot not in range(3) or not isinstance(start, date) or not isinstance(end, date) or not 0 <= (end-start).days <= 92:
            raise ValueError('เลือก Slot และช่วงวันที่ไม่เกิน 93 วัน')
        rows = load_shared_counter_days(conn, [slot], start=start, end=end, kind='device')
        groups = {}
        for row in rows:
            groups.setdefault(row.day, []).append(row)
        cfg = dict(conn.execute('SELECT key,value FROM settings'))
        policy = {k: cfg.get(k, d) for k, d in (('billing_day','25'), ('waste_paper_pct','0'), ('pricing_mode','shared'))}
        pricing = PricingRepository()
        ready, blocked = [], []
        for day, items in sorted(groups.items()):
            if not any(r.delta for r in items):
                continue
            reasons = {flag for r in items for flag in r.issues}
            if day >= self.today():
                reasons.add('day_not_closed')
            if len({(r.serial, r.epoch_id) for r in items}) != 1:
                reasons.add('multiple_slot_epochs')
            if not all(r.billing_safe for r in items):
                reasons.add('unverified_web_totals')
            if any(r.delta.denominator != 1 or r.delta < 0 for r in items):
                reasons.add('non_integer_or_negative_usage')
            covered = sorted({d.isoformat() for r in items for d in r.covered_days} | {day.isoformat()})
            placeholders = ','.join('?' for _ in covered)
            for table in ('daily_meter_records', 'billing_ledger', 'report_archive_days'):
                if conn.execute(f'SELECT 1 FROM {table} WHERE device_slot=? AND record_date IN ({placeholders}) LIMIT 1', [slot, *covered]).fetchone():
                    reasons.add('existing_account_or_legacy_source')
            delta = {r.field: int(r.delta) for r in items if r.delta.denominator == 1}
            if not reconcile_web_counters(delta).billing_safe:
                reasons.add('usage_totals_not_reconciled')
            categories = pricing.get_categories(slot, day, {r.field:(r.metadata['label'], r.metadata['source_path']) for r in items})
            categories = {k: v.value for k, v in categories.items()}
            price_row = conn.execute('SELECT 1 FROM price_history WHERE device_slot=? AND effective_date<=? LIMIT 1', (slot, day.isoformat())).fetchone()
            if not price_row or policy['pricing_mode'] == 'deferred':
                reasons.add('missing_price')
            prices = pricing.get_prices(slot, day)
            cents = {c.value: _cents(prices.price(c)) for c in CostCategory}
            if reasons:
                blocked.append({'day': day.isoformat(), 'reasons': sorted(reasons)})
                continue
            first = items[0]
            source = {'kind':'shared-web-reviewed', 'epoch':first.epoch_id,
                'evidence_ids': sorted({key for r in items for key in r.evidence_ids}),
                'covered_days': covered, 'remarks': sorted({s for r in items for s in r.remarks}),
                'reconciliation': {'billing_safe': True, 'basis': 'verified_shared_web_projection'},
                'device_identity': {'serial':first.serial, 'name':first.metadata['printer_name'], 'host':first.metadata['host']}}
            gross = sum(value * cents[categories[key]] for key, value in delta.items())
            discount = _basis_points(float(policy['waste_paper_pct']))
            ready.append({'day':day.isoformat(), 'delta':delta, 'categories':categories, 'prices':cents,
                'gross_cents':gross, 'net_cents':(gross*(10000-discount)+5000)//10000,
                'source':source,
                'opening': {r.field:int(r.opening) for r in items if r.opening is not None and r.opening.denominator == 1},
                'closing': {r.field:int(r.closing) for r in items if r.closing is not None and r.closing.denominator == 1},
                'first_success': min((r.first_at for r in items if r.first_at), default=None),
                'last_success': max((r.last_at for r in items if r.last_at), default=None),
                'sample_count': max(r.count for r in items)})
        body = {'path':str(self.path), 'slot':slot, 'start':start.isoformat(), 'end':end.isoformat(),
                'policy':policy, 'ready':ready, 'blocked':blocked}
        return {**body, 'digest': hashlib.sha256(_json(body).encode()).hexdigest()}

    def preview(self, slot, start, end):
        with _open(commit=False) as conn:
            conn.execute('BEGIN')
            return self._preview(conn, slot, start, end)

    @notify_local_change
    def confirm(self, review, *, actor, reason):
        if (Path(get_db_path()).resolve() != self.path or review.get('path') != str(self.path)
                or not isinstance(actor, str) or not 1 <= len(actor.strip()) <= 256
                or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300):
            raise ValueError('ต้องระบุผู้ยืนยันและเหตุผลในฐานข้อมูลที่ตรวจไว้')
        body = {k:v for k,v in review.items() if k != 'digest'}
        if hashlib.sha256(_json(body).encode()).hexdigest() != review.get('digest'):
            raise ValueError('รายการตรวจถูกเปลี่ยน กรุณาตรวจใหม่')
        key = 'shared_billing:' + review['digest']
        with config_write_transaction() as conn:
            receipt = conn.execute('SELECT new_value FROM config_log WHERE config_key=?', (key,)).fetchone()
            if receipt:
                saved = json.loads(receipt[0])
                if (saved['actor'], saved['reason']) != (actor.strip(), reason.strip()):
                    raise ValueError('คำยืนยันซ้ำต้องใช้เหตุผลเดิม')
                return saved['ledger_ids']
            current = self._preview(conn, review['slot'], date.fromisoformat(review['start']), date.fromisoformat(review['end']))
            if current != review:
                raise ValueError('หลักฐาน ราคา หรือบัญชีเปลี่ยนหลังตรวจ กรุณาตรวจใหม่')
            if not review['ready']:
                raise ValueError('ไม่มีรายการใหม่ที่พร้อมลงบัญชี')
            stamp = datetime.now(UTC).isoformat()
            ids = []
            for row in review['ready']:
                source = {**row['source'], 'review': {'actor':actor.strip(), 'reason':reason.strip(), 'digest':review['digest']}}
                record_id = conn.execute('''INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,
                    delta_json,category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,0,0,?) RETURNING id''',
                    (review['slot'], row['day'], _json(row['opening']), _json(row['closing']), _json(row['delta']),
                     _json(row['categories']), _json(source), row['first_success'], row['last_success'], row['sample_count'], stamp)).fetchone()[0]
                ledger_id = post_daily_record(record_id, connection=conn)
                actual = conn.execute('SELECT entry_kind,gross_cents,net_cents FROM billing_ledger WHERE id=?', (ledger_id,)).fetchone()
                if actual != ('posting', row['gross_cents'], row['net_cents']):
                    raise ValueError('ยอดบัญชีไม่ตรงกับรายการที่ตรวจ')
                ids.append(ledger_id)
            conn.execute('INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)',
                (key, '', _json({'actor':actor.strip(), 'reason':reason.strip(), 'ledger_ids':ids}), stamp))
            return ids
