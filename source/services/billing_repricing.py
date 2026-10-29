"""Reviewed repricing of safe postings, without rewriting issued ledger evidence."""
from datetime import date, datetime
import json

from database import _open
from config import DEFAULT_WASTE_PCT
from services.billing_ledger import AUTOMATIC_FORMULA_VERSIONS, _basis_points, _cents, _source_hash, _load_correction_source, _ensure_reversal
from services.pricing import CostCategory, quantity_first_amounts
from services.billing_periods import billing_month_range, effective_billing_day
from services.peer_change_events import notify_local_change

REPRICE_VERSION = "komi.billing.reprice.quantity-first.v2"


def _discount_policy(conn, apply_current_discount):
    if type(apply_current_discount) is not bool:
        raise ValueError("Discount selection must be boolean")
    if not apply_current_discount:
        return None
    row = conn.execute("SELECT value FROM settings WHERE key='waste_paper_pct'").fetchone()
    return _basis_points(row[0] if row else DEFAULT_WASTE_PCT)


def _period_policy(conn, apply_current_period):
    if type(apply_current_period) is not bool:
        raise ValueError("Period selection must be boolean")
    if not apply_current_period:
        return None
    row = conn.execute("SELECT value FROM settings WHERE key='billing_day'").fetchone()
    return effective_billing_day(row[0] if row else None)


def _preview(conn, ledger_id, *, apply_current_discount=False, apply_current_period=False):
    discount = _discount_policy(conn, apply_current_discount)
    billing_day = _period_policy(conn, apply_current_period)
    source = _load_correction_source(conn, ledger_id)
    formula = conn.execute("SELECT formula_version FROM billing_ledger WHERE id=?", (ledger_id,)).fetchone()[0]
    attestation = json.loads(source[18])
    if (source[0] not in {"posting", "replacement"} or formula not in AUTOMATIC_FORMULA_VERSIONS
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
    discount = source[14] if discount is None else discount
    gross, net, quantity_audit = quantity_first_amounts(deltas, categories, cents, discount)
    revision_data = {"ledger_id": ledger_id, "source": source, "formula": formula, "prices": prices}
    if apply_current_discount:
        revision_data["current_discount_basis_points"] = discount
    period = (source[6], source[7])
    if apply_current_period:
        period = tuple(value.isoformat() for value in billing_month_range(date.fromisoformat(source[5]), billing_day))
        revision_data["current_billing_day"] = billing_day
    else:
        billing_day = source[16]
    revision = _source_hash(revision_data)
    return {"ledger_id": ledger_id, "revision": revision, "device_slot": source[1], "device_name": source[3], "serial": source[4],
            "record_date": source[5], "price_effective_date": prices[0], "old_gross_cents": source[13],
            "old_net_cents": source[15], "gross_cents": gross, "net_cents": net,
            "price_cents": cents, "waste_basis_points": discount, "quantity_pricing": quantity_audit,
            "old_waste_basis_points": source[14], "apply_current_discount": apply_current_discount,
            "old_period_start": source[6], "old_period_end": source[7],
            "period_start": period[0], "period_end": period[1], "billing_day": billing_day,
            "apply_current_period": apply_current_period,
            "changed": (source[13], source[15], json.loads(source[12]), source[14], source[6], source[7], source[16])
                != (gross, net, cents, discount, *period, billing_day)}, source


class BillingRepricingService:
    def preview(self, ledger_id, *, apply_current_discount=False):
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            preview, _ = _preview(conn, ledger_id, apply_current_discount=apply_current_discount)
            return preview

    @notify_local_change
    def confirm(self, ledger_id, *, expected_revision, actor, reason, apply_current_discount=False):
        with _open() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return confirm_in_transaction(conn, ledger_id, expected_revision=expected_revision, actor=actor, reason=reason,
                                          apply_current_discount=apply_current_discount)


def confirm_in_transaction(conn, ledger_id, *, expected_revision, actor, reason, apply_current_discount=False,
                           apply_current_period=False, enqueue=True):
    if type(apply_current_discount) is not bool:
        raise ValueError("Discount selection must be boolean")
    if type(apply_current_period) is not bool:
        raise ValueError("Period selection must be boolean")
    if not actor.strip() or not reason.strip():
        raise ValueError("Actor and reason are required")
    key = f"reprice:{ledger_id}:{expected_revision}:{REPRICE_VERSION}"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    existing = conn.execute("SELECT id,attestation_json FROM billing_ledger WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        audit = json.loads(existing[1])["repricing"]
        if ((audit["actor"], audit["reason"]) != (actor.strip(), reason.strip())
                or audit.get("apply_current_discount", False) != apply_current_discount
                or audit.get("apply_current_period", False) != apply_current_period):
            raise ValueError("Repricing retry differs from the confirmed request")
        return existing[0]
    preview, source = _preview(conn, ledger_id, apply_current_discount=apply_current_discount,
                               apply_current_period=apply_current_period)
    if preview["revision"] != expected_revision:
        raise ValueError("Prices, discount, period or posting changed after preview")
    if not preview["changed"]:
        raise ValueError("No price, discount or period change to apply")
    reversal = _ensure_reversal(conn, ledger_id, source, reason=reason.strip(), now=now)
    attestation = {"billing_safe": True, "calculation_mode": "dated_price_recalculation",
        "original_attestation": json.loads(source[18]), "quantity_pricing": preview["quantity_pricing"],
        "repricing": {"actor": actor.strip(), "reason": reason.strip(), "target_ledger_id": ledger_id,
            "price_effective_date": preview["price_effective_date"], "preview_revision": expected_revision,
            "created_at": now, "source_delta_used_for_amounts": True,
            "preserved_discount_and_period": not (apply_current_discount or apply_current_period),
            "preserved_period": not apply_current_period, "apply_current_discount": apply_current_discount,
            "apply_current_period": apply_current_period, "old_billing_day": source[16], "billing_day": preview["billing_day"],
            "old_period": [source[6], source[7]], "period": [preview["period_start"], preview["period_end"]],
            "old_discount_basis_points": source[14], "discount_basis_points": preview["waste_basis_points"]}}
    cursor = conn.execute("""INSERT INTO billing_ledger
        (entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
         record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,
         replaces_ledger_id,delta_json,category_json,price_cents_json,gross_cents,waste_basis_points,
         net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("replacement", *source[1:6], preview["period_start"], preview["period_end"], *source[8:10], key, reversal, source[10], source[11],
         json.dumps(preview["price_cents"], sort_keys=True), preview["gross_cents"], preview["waste_basis_points"],
         preview["net_cents"], preview["billing_day"], source[17], REPRICE_VERSION, reason.strip(),
         json.dumps(attestation, sort_keys=True, ensure_ascii=False), now))
    result = int(cursor.lastrowid)
    if enqueue:
        from services.billing_correction_transfer import enqueue_corrections
        enqueue_corrections(conn, [(ledger_id, result, 'reprice')], actor=actor, reason=reason, created_at=now)
    return result
