"""Reviewed redistribution of already accounted usage from persisted Web evidence.

This does not infer missing money, approve a reset, or price graph averages.
It preserves raw readings and issued ledger entries. An allocation-only source
has no invented opening/closing meter or successful read timestamp.
"""
from datetime import date, datetime, time, timedelta, tzinfo
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

from services.peer_change_events import notify_local_change
from database import get_db_path
from komi_snmp_profiler.models import Confidence
from services.billing_ledger import FORMULA_VERSION, _source_hash, _load_correction_source, _ensure_reversal
from services.billing_periods import billing_month_range
from services.reconciliation import reconcile_web_counters
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore, validate_event
from services.web_usage_projection import CounterIdentity, project_counter

WEB_AMENDMENT_VERSION = "komi.billing.web-allocation.v1"
MAX_EVENTS = 4096
MAX_BYTES = 32 * 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _evidence(conn, path, slot, epoch_id, start, end, zone):
    epoch = SlotEpochStore._epoch(conn, epoch_id)
    anchor = epoch["document"]["baseline_event"]["payload"]
    if anchor["slot"] != slot:
        raise ValueError("ฐานมิเตอร์ไม่ตรงกับ Slot ที่เลือก")
    state = conn.execute("SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?", (epoch_id,)).fetchone()
    if not state or json.loads(state[0]):
        raise ValueError("ฐาน Slot มีข้อขัดแย้งที่ยังไม่ได้ตรวจสอบ")
    first = datetime.combine(start, time.min, zone).isoformat()
    last = datetime.combine(end + timedelta(days=1), time.min, zone).isoformat()
    # Retain all readings at the preceding instant, including conflicts. A
    # LIMIT 1 baseline would conceal two different readings with equal clocks.
    preceding = conn.execute("""SELECT MAX(julianday(w.observed_at)) FROM web_observations w
        JOIN slot_meter_assignments a ON a.event_id=w.event_id
        WHERE a.epoch_id=? AND julianday(w.observed_at)<julianday(?)""", (epoch_id, first)).fetchone()[0]
    rows = conn.execute("""SELECT w.event_id,w.document_json,w.archive_id FROM web_observations w
        JOIN slot_meter_assignments a ON a.event_id=w.event_id WHERE a.epoch_id=?
        AND julianday(w.observed_at)<julianday(?)
        AND (julianday(w.observed_at)>=julianday(?) OR julianday(w.observed_at)=?)
        ORDER BY julianday(w.observed_at),w.event_id LIMIT ?""", (epoch_id, last, first, preceding, MAX_EVENTS + 1)).fetchall()
    if len(rows) > MAX_EVENTS:
        raise ValueError("หลักฐานมากเกินไป กรุณาเลือกช่วงสั้นลง")
    store, events, size = WebObservationStore(path), [], 0
    for event_id, raw, archive_id in rows:
        raw = store._document(event_id, raw, archive_id)
        size += len(raw.encode("utf-8"))
        if size > MAX_BYTES:
            raise ValueError("หลักฐานมากเกินไป กรุณาเลือกช่วงสั้นลง")
        event = json.loads(raw)
        validate_event(event)
        if event["id"] != event_id:
            raise ValueError("รหัสหลักฐานไม่ตรงกับข้อมูลที่บันทึก")
        counters = {}
        for item in event["payload"]["reading"]["counters"]:
            if item["subject_type"] is None and item["canonical_field"].startswith("counter."):
                key, value = item["canonical_field"], item["count"]
                if Confidence(item["confidence"]) != Confidence.VERIFIED:
                    raise ValueError("หลักฐานมีตัวนับที่ยังไม่ผ่านการยืนยัน")
                if key in counters and counters[key] != value:
                    raise ValueError("พบค่ามิเตอร์ซ้ำที่ขัดแย้งกัน")
                counters[key] = value
        if not reconcile_web_counters(counters).billing_safe:
            raise ValueError("หลักฐาน Web ตรวจผลรวมมิเตอร์ไม่ผ่าน")
        events.append(event)
    if len(events) < 2:
        raise ValueError("ต้องมีหลักฐาน Web ต้นและปลายของช่วงที่แก้ไข")
    return epoch, events


def _validate_source_hash(conn, record_id, expected):
    row = conn.execute("""SELECT record_date,opening_json,closing_json,delta_json,category_json,source_json,
        first_success,last_success,sample_count,error_count,incomplete FROM daily_meter_records WHERE id=?""", (record_id,)).fetchone()
    payload = dict(zip(("record_date", "opening", "closing", "delta", "category", "source", "first_success",
                        "last_success", "sample_count", "error_count", "incomplete"), row))
    for key in ("opening", "closing", "delta", "category", "source"):
        payload[key] = json.loads(payload[key])
    payload["incomplete"] = bool(payload["incomplete"])
    if _source_hash(payload) != expected:
        raise ValueError("ข้อมูลรายวันต้นฉบับไม่ตรงกับหลักฐานที่ลงบัญชีไว้")


def _preview(conn, slot, epoch_id, start, end, zone, today):
    if (type(slot) is not int or slot not in range(3) or type(start) is not date or type(end) is not date
            or not 0 <= (end - start).days <= 92 or end >= today or not isinstance(zone, tzinfo)):
        raise ValueError("เลือกวันที่ปิดแล้ว ไม่เกิน 93 วัน และ Slot ที่ถูกต้อง")
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    epoch, events = _evidence(conn, path, slot, epoch_id, start, end, zone)
    serial = epoch["document"]["baseline_event"]["payload"]["serial"]
    rows = conn.execute("""SELECT d.id,d.record_date,d.opening_json,d.closing_json,d.source_json,
        (SELECT MAX(b.id) FROM billing_ledger b WHERE b.source_daily_record_id=d.id)
        FROM daily_meter_records d WHERE d.device_slot=? AND d.record_date BETWEEN ? AND ?
        ORDER BY d.record_date""", (slot, start.isoformat(), end.isoformat())).fetchall()
    if not rows:
        raise ValueError("ไม่มีรายการบัญชีเดิมในช่วงนี้ให้แก้การแบ่งยอด")
    sources, categories, policy = {}, None, None
    scope = [slot, epoch_id, start.isoformat(), end.isoformat(), str(zone)]
    for record_id, day, opening, closing, raw, ledger_id in rows:
        if ledger_id is None:
            raise ValueError("ช่วงนี้มีข้อมูลที่ยังไม่ได้ลงบัญชี ต้องตรวจรายการเดิมก่อน")
        source = _load_correction_source(conn, ledger_id)
        _validate_source_hash(conn, record_id, source[9])
        formula = conn.execute("SELECT formula_version FROM billing_ledger WHERE id=?", (ledger_id,)).fetchone()[0]
        attestation = json.loads(source[18])
        if (source[0] not in {"posting", "replacement"} or source[4] != serial
                or formula not in {FORMULA_VERSION, "komi.billing.reprice.v1", WEB_AMENDMENT_VERSION}
                or attestation.get("billing_safe") is not True):
            raise ValueError("มีรายการรอตรวจ แก้ด้วยมือ หรือ Serial ต่างกัน ต้องตรวจแยกก่อน")
        # Repricing wraps the original proof; do not permit a smaller window to
        # reuse just part of an already redistributed interval.
        proof = attestation
        while isinstance(proof, dict):
            if "web_allocation" in proof and proof["web_allocation"]["scope"] != scope:
                raise ValueError("เลือกช่วงเดียวกับฉบับแก้ไขเดิม เพื่อไม่แบ่งหลักฐานซ้ำ")
            proof = proof.get("original_attestation")
        delta, cats, prices = (json.loads(source[index]) for index in (10, 11, 12))
        if (not delta or any(type(v) is not int or v < 0 or not k.startswith("counter.") for k, v in delta.items())
                or any(cats.get(k) not in prices for k in delta)):
            raise ValueError("ตัวนับหรือราคาที่บันทึกเดิมไม่ครบ")
        cats = {k: cats[k] for k in delta}
        current_policy = (prices, source[14], source[16], source[17])
        if categories is not None and (categories != cats or policy != current_policy):
            raise ValueError("ช่วงนี้มีหมวดราคา อัตรา ส่วนลด หรือรอบบิลต่างกัน ต้องตรวจแยกก่อน")
        categories, policy = cats, current_policy
        sources[day] = {"ledger_id": ledger_id, "source": source, "record_id": record_id,
                        "delta": delta, "opening": json.loads(opening), "closing": json.loads(closing), "raw": raw}
    prices, discount, billing_day, currency = policy
    if (type(discount) is not int or not 0 <= discount <= 10000
            or any(type(v) is not int or v < 0 for v in prices.values())):
        raise ValueError("นโยบายราคาเดิมไม่ถูกต้อง")
    from services.pricing import price_change_dates
    changes = price_change_dates(conn, slot)
    allocations, intervals, revisions = {}, {}, {}
    for key in categories:
        projection = project_counter(events, slot=slot, serial=serial, epoch_id=epoch_id,
            counter=CounterIdentity(key), calendar_timezone=zone, reviewed_epoch=epoch,
            billing_day=billing_day, price_change_dates=changes)
        if (projection.issues or any(item.holds for item in projection.intervals)
                or len(projection.points) < 2 or any(item.amount.denominator != 1 for item in projection.intervals)):
            raise ValueError("หลักฐานยังขัดแย้ง คร่อมราคา/รอบบิล หรือตัวนับไม่ครบ ต้องตรวจสอบก่อน")
        # Every actual result must carry each frozen device counter, including
        # multiple reads on one day (day-level projection guards alone cannot).
        if any(not any(c["canonical_field"] == key and c["subject_type"] is None
                       for c in e["payload"]["reading"]["counters"]) for e in events):
            raise ValueError("บางผล Web ไม่มีตัวนับที่ใช้ในบัญชีเดิม")
        first_sources = [s for s in sources.values() if key in s["opening"]]
        last_sources = [s for s in sources.values() if key in s["closing"]]
        if (not first_sources or not last_sources
                or first_sources[0]["opening"][key] != projection.points[0].value
                or last_sources[-1]["closing"][key] != projection.points[-1].value
                or sum(s["delta"][key] for s in sources.values()) != projection.total_usage):
            raise ValueError("หลักฐานต้น–ปลายหรือยอดรวมไม่ตรงบัญชีเดิม เลือกช่วงให้ครอบคลุมก่อนแก้")
        revisions[key] = projection.revision
        for item in projection.intervals:
            if not start <= item.allocation_day <= end:
                if item.amount:
                    raise ValueError("วันลงยอดอยู่นอกช่วงที่เลือก กรุณาขยายช่วงวันที่")
                continue
            day = item.allocation_day.isoformat()
            allocations.setdefault(day, {k: 0 for k in categories})[key] += int(item.amount)
            detail = {"from": item.start.at.isoformat(), "to": item.end.at.isoformat(),
                      "remark": item.remark, "start_evidence": item.start.evidence_ids, "end_evidence": item.end.evidence_ids}
            intervals.setdefault(day, {})[_source_hash(detail)] = detail
    changed = []
    for day in sorted(sources.keys() | allocations.keys()):
        old = sources.get(day)
        delta = allocations.get(day, {k: 0 for k in categories})
        if (old and delta == old["delta"]) or (not old and not any(delta.values())):
            continue
        gross = sum(value * prices[categories[key]] for key, value in delta.items())
        if gross > 2**63 - 1:
            raise ValueError("ยอดเงินเกินขนาดที่รองรับ")
        period = tuple(d.isoformat() for d in billing_month_range(date.fromisoformat(day), billing_day))
        # Frozen period overrides are meaningful; never silently undo them.
        if old and period != tuple(old["source"][6:8]):
            raise ValueError("รอบบิลเดิมไม่ตรงนโยบายที่บันทึก ต้องตรวจรายการเดิมก่อน")
        changed.append({"day": day, "ledger_id": old["ledger_id"] if old else None,
            "source": old["source"] if old else None, "delta": delta, "period": period,
            "gross_cents": gross, "net_cents": (gross * (10000 - discount) + 5000) // 10000,
            "old_net_cents": old["source"][15] if old else 0,
            "intervals": list(intervals.get(day, {}).values())})
    revision = _source_hash({"database": str(path), "scope": scope, "rows": rows, "sources": sources,
        "evidence": [e["id"] for e in events], "epoch": epoch, "projections": revisions, "prices": changes and [d.isoformat() for d in changes]})
    return {"revision": revision, "scope": scope, "changed": changed, "categories": categories,
        "calendar": {"name": str(zone), "iana": getattr(zone, "key", None),
                     "offset_seconds": int(datetime.combine(start, time.min, zone).utcoffset().total_seconds())},
        "price_cents": prices, "discount": discount, "billing_day": billing_day, "currency": currency,
        "before": [{"day": day, "delta": item["delta"], "net_cents": item["source"][15],
                    "gross_cents": item["source"][13], "period": list(item["source"][6:8])}
                   for day, item in sorted(sources.items())],
        "template": next(iter(sources.values()))["source"], "events": [e["id"] for e in events],
        "old_net_cents": sum(c["old_net_cents"] for c in changed), "net_cents": sum(c["net_cents"] for c in changed)}


class BillingWebAmendmentService:
    def __init__(self, *, today=date.today, database_path=None):
        self.today = today
        self.path = Path(database_path or get_db_path()).resolve()

    @contextmanager
    def _connection(self, *, write=False):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn

    def preview(self, slot, epoch_id, start, end, calendar_timezone):
        with self._connection() as conn:
            return _preview(conn, slot, epoch_id, start, end, calendar_timezone, self.today())

    @notify_local_change
    def confirm(self, slot, epoch_id, start, end, calendar_timezone, *, expected_revision, actor, reason):
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("ต้องระบุผู้ยืนยันและเหตุผล")
        request = {"scope": [slot, epoch_id, start.isoformat(), end.isoformat(), str(calendar_timezone)],
                   "actor": actor.strip(), "reason": reason.strip()}
        with self._connection(write=True) as conn:
            receipt = conn.execute("SELECT new_value FROM config_log WHERE config_key='billing_web_allocation' AND old_value=? ORDER BY id DESC LIMIT 1",
                                   (expected_revision,)).fetchone()
            if receipt:
                saved = json.loads(receipt[0])
                if saved["request"] != request:
                    raise ValueError("คำขอยืนยันซ้ำไม่ตรงกับฉบับที่บันทึก")
                if any(not conn.execute("SELECT 1 FROM billing_ledger WHERE id=? AND idempotency_key=?", (r["id"], r["key"])).fetchone() for r in saved["results"]):
                    raise ValueError("ไม่พบฉบับแก้ไขเดิมครบถ้วน")
                return tuple(r["id"] for r in saved["results"])
            preview = _preview(conn, slot, epoch_id, start, end, calendar_timezone, self.today())
            if preview["revision"] != expected_revision:
                raise ValueError("หลักฐานหรือรายการบัญชีเปลี่ยน กรุณาตรวจตัวอย่างใหม่")
            if not preview["changed"]:
                raise ValueError("ไม่มีการแบ่งยอดที่ต้องแก้ไข")
            return self._commit(conn, preview, actor=actor, reason=reason)

    @staticmethod
    def _commit(conn, preview, *, actor, reason):
        """Caller holds one write transaction for ledger, receipt and outbox."""
        if not conn.in_transaction:
            raise ValueError("An amendment transaction is required")
        expected_revision = preview["revision"]
        slot = preview["scope"][0]
        request = {"scope": preview["scope"], "actor": actor.strip(), "reason": reason.strip()}
        now, results = datetime.now().astimezone().isoformat(), []
        for item in preview["changed"]:
            source = item["source"]
            proof = {"scope": preview["scope"], "events": preview["events"], "intervals": item["intervals"],
                     "revision": expected_revision, "actor": actor.strip(), "reason": reason.strip(), "created_at": now}
            if source:
                record_id, source_hash = source[8:10]
                reversal = _ensure_reversal(conn, item["ledger_id"], source, reason=reason.strip(), now=now)
                kind = "replacement"
            else:
                source = preview["template"]
                raw = {"allocation_only": True, "web_allocation": proof,
                       "device_identity": {"serial": source[4], "name": source[3]}}
                # This is an accounting allocation, NOT a successful read.
                record_id = conn.execute("""INSERT INTO daily_meter_records
                    (device_slot,record_date,opening_json,closing_json,delta_json,category_json,source_json,
                     first_success,last_success,sample_count,error_count,incomplete,created_at)
                    VALUES(?,?, '{}','{}',?,?,?,NULL,NULL,0,0,0,?)""",
                    (slot, item["day"], _json(item["delta"]), _json(preview["categories"]), _json(raw), now)).lastrowid
                source_hash = _source_hash({"record_date": item["day"], "opening": {}, "closing": {},
                    "delta": item["delta"], "category": preview["categories"], "source": raw,
                    "first_success": None, "last_success": None, "sample_count": 0, "error_count": 0, "incomplete": False})
                reversal, kind = None, "posting"
            key = f"web-allocation:{expected_revision}:{item['day']}"
            attestation = {"billing_safe": True, "calculation_mode": "reviewed_web_redistribution",
                           "web_allocation": proof}
            cursor = conn.execute("""INSERT INTO billing_ledger
                (entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
                 record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,
                 replaces_ledger_id,delta_json,category_json,price_cents_json,gross_cents,waste_basis_points,
                 net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (kind, slot, source[2], source[3], source[4], item["day"], *item["period"], record_id, source_hash,
                 key, reversal, _json(item["delta"]), _json(preview["categories"]), _json(preview["price_cents"]),
                 item["gross_cents"], preview["discount"], item["net_cents"], preview["billing_day"], preview["currency"],
                 WEB_AMENDMENT_VERSION, reason.strip(), _json(attestation), now))
            results.append({"id": int(cursor.lastrowid), "key": key})
        conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
            ("billing_web_allocation", expected_revision, _json({"request": request, "results": results}), now))
        from services.peer_billing_amendments import enqueue_amendment
        enqueue_amendment(conn, preview, results, actor=actor, reason=reason, created_at=now)
        return tuple(r["id"] for r in results)
