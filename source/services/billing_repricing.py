"""Reviewed repricing of safe postings, without rewriting issued ledger evidence."""
from datetime import datetime
import json

from database import _open
from services.billing_ledger import FORMULA_VERSION, _cents, _source_hash, _load_correction_source, _ensure_reversal
from services.pricing import CostCategory

REPRICE_VERSION = "komi.billing.reprice.v1"


def _preview(conn, ledger_id):
    source = _load_correction_source(conn, ledger_id)
    formula = conn.execute("SELECT formula_version FROM billing_ledger WHERE id=?", (ledger_id,)).fetchone()[0]
    attestation = json.loads(source[18])
    if (source[0] not in {"posting", "replacement"} or formula not in {FORMULA_VERSION, REPRICE_VERSION}
            or not isinstance(attestation, dict) or attestation.get("billing_safe") is not True):
        raise ValueError("Only a verified automatic posting can be repriced")
    latest = conn.execute("SELECT MAX(id) FROM billing_ledger WHERE source_daily_record_id=?", (source[8],)).fetchone()[0]
    if latest != ledger_id:
        raise ValueError("The selected posting has already been superseded")
    prices = conn.execute("""SELECT effective_date,a3_color,a3_bw,a4_color,a4_bw FROM price_history
        WHERE device_slot=? AND effective_date<=? ORDER BY effective_date DESC LIMIT 1""", (source[1], source[5])).fetchone()
    if prices is None:
        raise ValueError("No dated price applies to this usage day")
    cents = dict(zip(("a3_color", "a3_bw", "a4_color", "a4_bw"), (_cents(value) for value in prices[1:])))
    cents["no_charge"] = 0
    deltas, categories = json.loads(source[10]), json.loads(source[11])
    if not isinstance(deltas, dict) or not isinstance(categories, dict):
        raise ValueError("Invalid frozen billing evidence")
    if any(type(value) is not int or value < 0 or categories.get(key) not in {item.value for item in CostCategory}
           for key, value in deltas.items()):
        raise ValueError("Invalid frozen counter/category")
    if type(source[14]) is not int or not 0 <= source[14] <= 10000:
        raise ValueError("Invalid frozen discount")
    gross = sum(value * cents[categories[key]] for key, value in deltas.items())
    if gross > 2**63 - 1:
        raise ValueError("Recalculated amount exceeds supported storage range")
    net = (gross * (10000 - source[14]) + 5000) // 10000
    revision = _source_hash({"ledger_id": ledger_id, "source": source, "formula": formula, "prices": prices})
    return {"ledger_id": ledger_id, "revision": revision, "device_name": source[3], "serial": source[4],
            "record_date": source[5], "price_effective_date": prices[0], "old_gross_cents": source[13],
            "old_net_cents": source[15], "gross_cents": gross, "net_cents": net,
            "price_cents": cents, "waste_basis_points": source[14],
            "period_start": source[6], "period_end": source[7],
            "changed": (source[13], source[15], json.loads(source[12])) != (gross, net, cents)}, source


class BillingRepricingService:
    def preview(self, ledger_id):
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            preview, _ = _preview(conn, ledger_id)
            return preview

    def confirm(self, ledger_id, *, expected_revision, actor, reason):
        if not actor.strip() or not reason.strip():
            raise ValueError("Actor and reason are required")
        key = f"reprice:{ledger_id}:{expected_revision}:{REPRICE_VERSION}"
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with _open() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT id,attestation_json FROM billing_ledger WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                audit = json.loads(existing[1])["repricing"]
                if (audit["actor"], audit["reason"]) != (actor.strip(), reason.strip()):
                    raise ValueError("Repricing retry differs from the confirmed request")
                return existing[0]
            preview, source = _preview(conn, ledger_id)
            if preview["revision"] != expected_revision:
                raise ValueError("Prices or posting changed after preview")
            if not preview["changed"]:
                raise ValueError("No price change to apply")
            reversal = _ensure_reversal(conn, ledger_id, source, reason=reason.strip(), now=now)
            attestation = {"billing_safe": True, "calculation_mode": "dated_price_recalculation",
                "original_attestation": json.loads(source[18]),
                "repricing": {"actor": actor.strip(), "reason": reason.strip(), "target_ledger_id": ledger_id,
                    "price_effective_date": preview["price_effective_date"], "preview_revision": expected_revision,
                    "created_at": now, "source_delta_used_for_amounts": True,
                    "preserved_discount_and_period": True}}
            cursor = conn.execute("""INSERT INTO billing_ledger
                (entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
                 record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,
                 replaces_ledger_id,delta_json,category_json,price_cents_json,gross_cents,waste_basis_points,
                 net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("replacement", *source[1:10], key, reversal, source[10], source[11],
                 json.dumps(preview["price_cents"], sort_keys=True), preview["gross_cents"], source[14],
                 preview["net_cents"], source[16], source[17], REPRICE_VERSION, reason.strip(),
                 json.dumps(attestation, sort_keys=True, ensure_ascii=False), now))
            return int(cursor.lastrowid)
