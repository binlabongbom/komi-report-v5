"""Immutable local billing postings.

Raw meter records remain operational evidence.  This module freezes the
billable interpretation once, with integer money and an auditable hold reason.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from database import _open as _database_open, get_billing_day, get_waste_paper_pct
from services.billing_periods import billing_month_range
from services.pricing import CostCategory, PricingRepository

FORMULA_VERSION = "komi.billing.v1"
_posting_connection = ContextVar('billing_posting_connection', default=None)


@contextmanager
def _open(commit=True):
    connection = _posting_connection.get()
    if connection is None:
        with _database_open(commit=commit) as conn:
            yield conn
    else:
        yield connection  # The caller owns commit/rollback of source + ledger.
REVERSAL_VERSION = "komi.billing.reversal.v1"
MANUAL_ADJUSTMENT_VERSION = "komi.billing.manual-adjustment.v1"
# This legacy value remains part of the idempotency-key contract. New rows use
# MANUAL_ADJUSTMENT_VERSION as their truthful formula version, but a retry after
# an application upgrade must still find an older immutable approval row.
MANUAL_APPROVAL_VERSION = "komi.billing.hold-approval.v1"


@dataclass(frozen=True)
class AuditCoverage:
    """Coverage of source days and their currently effective ledger state."""

    legacy_uncovered: int
    expected_missing: int
    ledger_sources: int
    effective_posted: int
    open_holds: int
    open_reversals: int
    corrected_sources: int


@dataclass(frozen=True)
class AuditRow:
    """Complete, immutable audit projection for one ledger event."""

    id: int
    entry_kind: str
    effective_state: str
    device_slot: int
    device_identity: str
    device_name_snapshot: str
    device_serial_snapshot: str
    record_date: str
    period_start: str
    period_end: str
    source_daily_record_id: int | None
    source_hash: str
    idempotency_key: str
    replaces_ledger_id: int | None
    delta_json: str
    category_json: str
    price_cents_json: str
    gross_cents: int
    waste_basis_points: int
    net_cents: int
    billing_day: int
    currency: str
    formula_version: str
    hold_reason: str | None
    attestation_json: str
    created_at: str


def _cents(value: float) -> int:
    if not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError("price must be finite and non-negative")
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _basis_points(value: float) -> int:
    if not math.isfinite(float(value)) or not 0 <= float(value) <= 100:
        raise ValueError("waste percentage must be between 0 and 100")
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _device_snapshot(slot: int, source: dict | None = None) -> tuple[str, str, str]:
    captured = source.get("device_identity") if isinstance(source, dict) else None
    if isinstance(captured, dict):
        name = str(captured.get("name") or "")
        serial = str(captured.get("serial") or "").strip()
        host = str(captured.get("host") or "").strip()
        if serial or host:
            return (f"serial:{serial}" if serial else f"host:{host}"), name, serial
    with _open(commit=False) as conn:
        row = conn.execute("SELECT name,serial,host FROM devices WHERE slot=?", (slot,)).fetchone()
    name, serial, host = row or ("", "", "")
    # A serial is the immutable identity; host is only a safe fallback for an
    # unprovisioned test/local device and is deliberately captured in the entry.
    return (f"serial:{serial.strip()}" if serial and serial.strip() else f"host:{host.strip()}"), name or "", serial or ""


def _decode_mapping(raw: str) -> tuple[dict, object, bool]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}, {"invalid_json": raw}, False
    return (value, value, True) if isinstance(value, dict) else ({}, value, False)


def _source_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def hold_reason(*, source: dict, incomplete: bool, categories: dict[str, str]) -> str | None:
    if isinstance(source, dict) and source.get("missing_web_success") is True:
        return "missing_web_success"
    reconciliation = source.get("reconciliation") if isinstance(source, dict) else None
    if not isinstance(reconciliation, dict) or reconciliation.get("billing_safe") is not True:
        return "missing_or_unsafe_attestation"
    if incomplete:
        return "incomplete_day"
    if source.get("identity_conflict") or source.get("identity_baseline_mismatch"):
        return "device_identity_conflict"
    if source.get("reset_detected") or source.get("out_of_order"):
        return "counter_reset_or_out_of_order"
    if source.get("unsafe_reconciliation_seen"):
        return "unsafe_attestation_seen_during_day"
    if not categories:
        return "missing_category_snapshot"
    return None


def post_daily_record(record_id: int, *, connection=None) -> int | None:
    if connection is None:
        return _post_daily_record(record_id)
    from pathlib import Path
    from database import get_db_path
    if (not connection.in_transaction or Path(connection.execute('PRAGMA database_list').fetchone()[2]).resolve()
            != Path(get_db_path()).resolve()):
        raise ValueError('Posting requires a transaction in the active database')
    token = _posting_connection.set(connection)
    try:
        return _post_daily_record(record_id)
    finally:
        _posting_connection.reset(token)


def _post_daily_record(record_id: int) -> int | None:
    """Create exactly one posting for a safe daily source row, otherwise hold it.

    An unsafe source becomes a visible zero-value hold. It can be approved later
    with an explicit replacement, never by editing an existing ledger row.
    """
    with _open(commit=False) as conn:
        row = conn.execute(
            """SELECT device_slot,record_date,opening_json,closing_json,delta_json,category_json,source_json,
                      first_success,last_success,sample_count,error_count,incomplete
               FROM daily_meter_records WHERE id=?""", (record_id,)
        ).fetchone()
    if row is None:
        return None
    (
        slot,
        record_date,
        opening_json,
        closing_json,
        delta_json,
        category_json,
        source_json,
        first_success,
        last_success,
        sample_count,
        error_count,
        incomplete,
    ) = row
    _opening, opening_evidence, opening_ok = _decode_mapping(opening_json)
    _closing, closing_evidence, closing_ok = _decode_mapping(closing_json)
    deltas, delta_evidence, delta_ok = _decode_mapping(delta_json)
    categories, category_evidence, category_ok = _decode_mapping(category_json)
    source, source_evidence, source_ok = _decode_mapping(source_json)
    identity, device_name, serial = _device_snapshot(slot, source)
    raw_source = {
        "record_date": record_date,
        "opening": opening_evidence,
        "closing": closing_evidence,
        "delta": delta_evidence,
        "category": category_evidence,
        "source": source_evidence,
        "first_success": first_success,
        "last_success": last_success,
        "sample_count": sample_count,
        "error_count": error_count,
        "incomplete": bool(incomplete),
    }
    source_hash = _source_hash(raw_source)
    with _open(commit=False) as conn:
        existing = conn.execute(
            """SELECT id,source_hash FROM billing_ledger
               WHERE source_daily_record_id=? AND entry_kind IN ('posting','hold')""",
            (record_id,),
        ).fetchone()
    if existing is not None:
        if existing[1] != source_hash:
            raise ValueError("daily source evidence changed after its initial ledger event")
        return int(existing[0])

    valid_source_json = opening_ok and closing_ok and delta_ok and category_ok and source_ok
    reason = None if valid_source_json else "invalid_source_json"
    reason = reason or hold_reason(source=source, incomplete=bool(incomplete), categories=categories)
    if not identity or identity == "host:":
        reason = reason or "missing_device_identity"
    allowed = {item.value for item in CostCategory}
    if any(key not in categories or categories[key] not in allowed for key in deltas):
        reason = reason or "missing_or_invalid_category_snapshot"
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in deltas.values()):
        reason = reason or "invalid_delta"
    try:
        parsed_date = date.fromisoformat(record_date)
    except (TypeError, ValueError):
        parsed_date = None
        reason = reason or "invalid_record_date"
    pricing = PricingRepository()
    with _open(commit=False) as conn:
        price_row = conn.execute(
            "SELECT 1 FROM price_history WHERE device_slot=? AND effective_date<=? LIMIT 1",
            (slot, record_date),
        ).fetchone()
    if price_row is None:
        reason = reason or "missing_price_snapshot"
    billing_day = get_billing_day()
    if parsed_date is None:
        period_start = period_end = date.today()
    else:
        period_start, period_end = billing_month_range(parsed_date, billing_day)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if reason:
        key = f"daily:{record_id}:{source_hash}:hold:{reason}:{FORMULA_VERSION}"
        with _open() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
                   record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,replaces_ledger_id,
                   delta_json,category_json,price_cents_json,gross_cents,waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("hold", slot, identity, device_name, serial, record_date, period_start.isoformat(), period_end.isoformat(), record_id, source_hash, key, None,
                 json.dumps(deltas, sort_keys=True), json.dumps(categories, sort_keys=True), '{}', 0, 0, 0, billing_day,
                 "THB", FORMULA_VERSION, reason, json.dumps({"source_attestation": source.get("reconciliation")}, sort_keys=True), now),
            )
            result = conn.execute("SELECT id FROM billing_ledger WHERE idempotency_key=?", (key,)).fetchone()
        return int(result[0]) if result else None
    try:
        prices = pricing.get_prices(slot, parsed_date)
        price_cents = {category.value: _cents(prices.price(category)) for category in CostCategory}
        gross = sum(int(value) * price_cents.get(category, 0) for key, value in deltas.items() for category in [categories.get(key, "no_charge")])
        waste_bp = _basis_points(get_waste_paper_pct())
    except (TypeError, ValueError, ArithmeticError):
        return _append_hold(record_id, slot, identity, device_name, serial, record_date, period_start, period_end, source_hash, billing_day,
                            deltas, categories, source, "invalid_price_or_waste")
    net = (gross * (10_000 - waste_bp) + 5_000) // 10_000
    attestation = {"billing_safe": True, "reconciliation": source["reconciliation"]}
    # Stable per raw source + formula version. Formula inputs are captured on
    # the entry but never add wall-clock time to the retry key.
    idempotency_key = f"daily:{record_id}:{source_hash}:posting:{FORMULA_VERSION}"
    with _open() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
               record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,replaces_ledger_id,delta_json,category_json,
               price_cents_json,gross_cents,waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("posting", slot, identity, device_name, serial, record_date, period_start.isoformat(), period_end.isoformat(), record_id, source_hash, idempotency_key, None,
             json.dumps(deltas, sort_keys=True), json.dumps(categories, sort_keys=True), json.dumps(price_cents, sort_keys=True),
             gross, waste_bp, net, billing_day, "THB", FORMULA_VERSION, None, json.dumps(attestation, sort_keys=True), now),
        )
        result = conn.execute("SELECT id FROM billing_ledger WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    return int(result[0]) if result else None


def _append_hold(record_id: int, slot: int, identity: str, device_name: str, serial: str, record_date: str,
                 period_start: date, period_end: date, source_hash: str, billing_day: int,
                 deltas: dict, categories: dict, source: dict, reason: str) -> int | None:
    """Fallback hold for validation paths that cannot calculate a formula."""
    key = f"daily:{record_id}:{source_hash}:hold:{reason}:{FORMULA_VERSION}"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        conn.execute("""INSERT OR IGNORE INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
            record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,replaces_ledger_id,delta_json,category_json,
            price_cents_json,gross_cents,waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("hold", slot, identity, device_name, serial, record_date, period_start.isoformat(), period_end.isoformat(), record_id, source_hash, key, None,
             json.dumps(deltas, sort_keys=True), json.dumps(categories, sort_keys=True), '{}', 0, 0, 0, billing_day,
             "THB", FORMULA_VERSION, reason, json.dumps({"source_attestation": source.get("reconciliation")}, sort_keys=True), now))
        row = conn.execute("SELECT id FROM billing_ledger WHERE idempotency_key=?", (key,)).fetchone()
    return int(row[0]) if row else None


def ledger_totals(
    slot: int,
    start: date,
    end: date,
    *,
    device_identity: str | None = None,
) -> tuple[int, int]:
    """Return corrections for every frozen billing period active on ``end``.

    A settings change can make multiple frozen cycles overlap temporarily. Each
    immutable entry remains in its original period and is counted once while
    that stored period is active; mutable current settings never move it.
    """
    identity_clause = " AND device_identity=?" if device_identity is not None else ""
    params: tuple[object, ...] = (
        slot,
        end.isoformat(),
        end.isoformat(),
        end.isoformat(),
    )
    if device_identity is not None:
        params += (device_identity,)
    with _open(commit=False) as conn:
        row = conn.execute(
            f"""SELECT COALESCE(SUM(gross_cents),0), COALESCE(SUM(net_cents),0)
                FROM billing_ledger WHERE device_slot=?
                AND period_start<=? AND period_end>=?
                AND record_date<=?
                AND entry_kind IN ('posting','replacement','reversal')
                {identity_clause}""",
            params,
        ).fetchone()
    return int(row[0]), int(row[1])


_AUDIT_SELECT = """
    SELECT
        l.id,
        l.entry_kind,
        CASE
            WHEN l.entry_kind='hold' AND EXISTS(
                SELECT 1 FROM billing_ledger child
                WHERE child.replaces_ledger_id=l.id AND child.entry_kind='replacement'
            ) THEN 'resolved_hold'
            WHEN l.entry_kind='hold' THEN 'open_hold'
            WHEN l.entry_kind IN ('posting','replacement') AND EXISTS(
                SELECT 1 FROM billing_ledger child
                WHERE child.replaces_ledger_id=l.id AND child.entry_kind='reversal'
            ) THEN 'superseded'
            WHEN l.entry_kind='reversal' AND EXISTS(
                SELECT 1 FROM billing_ledger child
                WHERE child.replaces_ledger_id=l.id AND child.entry_kind='replacement'
            ) THEN 'paired_reversal'
            WHEN l.entry_kind='reversal' THEN 'open_reversal'
            ELSE 'effective'
        END AS effective_state,
        l.device_slot,
        l.device_identity,
        l.device_name_snapshot,
        l.device_serial_snapshot,
        l.record_date,
        l.period_start,
        l.period_end,
        l.source_daily_record_id,
        l.source_hash,
        l.idempotency_key,
        l.replaces_ledger_id,
        l.delta_json,
        l.category_json,
        l.price_cents_json,
        l.gross_cents,
        l.waste_basis_points,
        l.net_cents,
        l.billing_day,
        l.currency,
        l.formula_version,
        l.hold_reason,
        l.attestation_json,
        l.created_at
    FROM billing_ledger l
"""


def _audit_filters(*, state: str | None, search: str) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    allowed_states = {
        "effective",
        "open_hold",
        "open_reversal",
        "resolved_hold",
        "superseded",
        "paired_reversal",
    }
    allowed_kinds = {"posting", "hold", "reversal", "replacement"}
    if state == "correction":
        clauses.append("entry_kind IN ('reversal','replacement')")
    elif state in allowed_states:
        clauses.append("effective_state=?")
        params.append(state)
    elif state in allowed_kinds:
        clauses.append("entry_kind=?")
        params.append(state)
    elif state not in (None, ""):
        raise ValueError(f"unknown audit state: {state}")
    query = search.strip()
    if query:
        needle = f"%{query}%"
        clauses.append(
            "(CAST(id AS TEXT) LIKE ? OR device_identity LIKE ? OR device_name_snapshot LIKE ? "
            "OR device_serial_snapshot LIKE ? OR source_hash LIKE ? OR idempotency_key LIKE ? "
            "OR COALESCE(hold_reason,'') LIKE ? OR record_date LIKE ? OR period_start LIKE ? OR period_end LIKE ?)"
        )
        params.extend([needle] * 10)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def list_audit_rows(
    limit: int | None = 100,
    *,
    offset: int = 0,
    state: str | None = None,
    search: str = "",
) -> list[AuditRow]:
    """Return full-fidelity audit events, newest first.

    ``limit=None`` is intended for an explicit export.  The interactive UI
    pages in batches so installations with years of entries remain responsive.
    """
    if limit is not None and limit <= 0:
        raise ValueError("audit limit must be positive or None")
    if offset < 0:
        raise ValueError("audit offset must be non-negative")
    where, params = _audit_filters(state=state, search=search)
    sql = f"SELECT * FROM ({_AUDIT_SELECT}) audit{where} ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend((limit, offset))
    with _open(commit=False) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [AuditRow(*row) for row in rows]


def count_audit_rows(*, state: str | None = None, search: str = "") -> int:
    where, params = _audit_filters(state=state, search=search)
    with _open(commit=False) as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM ({_AUDIT_SELECT}) audit{where}",
                params,
            ).fetchone()[0]
        )


def get_audit_row(ledger_id: int) -> AuditRow | None:
    with _open(commit=False) as conn:
        row = conn.execute(
            f"SELECT * FROM ({_AUDIT_SELECT}) audit WHERE id=?",
            (ledger_id,),
        ).fetchone()
    return AuditRow(*row) if row is not None else None


_CORRECTION_SOURCE_SQL = """
    SELECT entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
           record_date,period_start,period_end,source_daily_record_id,source_hash,delta_json,
           category_json,price_cents_json,gross_cents,waste_basis_points,net_cents,billing_day,
           currency,attestation_json,hold_reason
    FROM billing_ledger WHERE id=?
"""


def _load_correction_source(conn: sqlite3.Connection, ledger_id: int) -> tuple:
    row = conn.execute(_CORRECTION_SOURCE_SQL, (ledger_id,)).fetchone()
    if row is None:
        raise ValueError("ledger entry does not exist")
    return row


def _manual_waste_basis_points(gross_cents: int, net_cents: int) -> int:
    if gross_cents == 0:
        return 0
    discount = (gross_cents - net_cents) * 10_000
    return (discount + gross_cents // 2) // gross_cents


def _attestation_evidence(raw: str) -> object:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"invalid_json": raw}


def _manual_adjustment_attestation(
    original_attestation: str,
    *,
    action: str,
    target_ledger_id: int,
    gross_cents: int,
    net_cents: int,
    waste_basis_points: int,
    reason: str,
    created_at: str,
    original_hold_reason: str | None = None,
) -> dict:
    manual = {
        "action": action,
        "amount_origin": "operator_entered",
        "created_at": created_at,
        "gross_cents": gross_cents,
        "net_cents": net_cents,
        "reason": reason,
        "source_delta_used_for_amounts": False,
        "source_price_used_for_amounts": False,
        "target_ledger_id": target_ledger_id,
        "waste_basis_points_derived_for_display": waste_basis_points,
    }
    if original_hold_reason is not None:
        manual["original_hold_reason"] = original_hold_reason
    result = {
        "billing_safe": False,
        "calculation_mode": "manual_adjustment",
        "manual_adjustment": manual,
        "original_attestation": _attestation_evidence(original_attestation),
    }
    if action == "approve_hold":
        # Backwards-compatible audit name, now carrying the same truthful
        # operator-entered calculation contract.
        result["hold_approval"] = {
            "approved_at": created_at,
            "hold_ledger_id": target_ledger_id,
            "original_hold_reason": original_hold_reason,
            "reason": reason,
        }
    return result


def _reversal_attestation(
    original_attestation: str,
    *,
    target_ledger_id: int,
    gross_cents: int,
    net_cents: int,
    reason: str,
    created_at: str,
) -> dict:
    return {
        "billing_safe": False,
        "calculation_mode": "exact_reversal",
        "correction": {
            "created_at": created_at,
            "gross_cents": -gross_cents,
            "net_cents": -net_cents,
            "reason": reason,
            "target_ledger_id": target_ledger_id,
        },
        "original_attestation": _attestation_evidence(original_attestation),
    }


def _existing_adjustment(
    conn: sqlite3.Connection,
    *,
    key: str,
    gross_cents: int,
    net_cents: int,
    reason: str,
    conflict: str,
) -> int | None:
    row = conn.execute(
        "SELECT id,gross_cents,net_cents,hold_reason FROM billing_ledger WHERE idempotency_key=?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    if (int(row[1]), int(row[2]), row[3]) != (gross_cents, net_cents, reason):
        raise ValueError(f"idempotency conflict: {conflict} payload differs from the original request")
    return int(row[0])


def _ensure_reversal(
    conn: sqlite3.Connection,
    ledger_id: int,
    source: tuple,
    *,
    reason: str,
    now: str,
) -> int:
    if source[0] not in {"posting", "replacement"}:
        raise ValueError("only a posting/replacement can be reversed")
    # Keep the original key shape across formula metadata upgrades. Changing it
    # would make a retry append a second correction to an existing database.
    key = f"reversal:{ledger_id}:{FORMULA_VERSION}"
    existing = _existing_adjustment(
        conn,
        key=key,
        gross_cents=-int(source[13]),
        net_cents=-int(source[15]),
        reason=reason,
        conflict="reversal",
    )
    if existing is not None:
        return existing
    if conn.execute('SELECT MAX(id) FROM billing_ledger WHERE source_daily_record_id=?', (source[8],)).fetchone()[0] != ledger_id:
        raise ValueError('The selected posting has already been superseded')
    attestation = _reversal_attestation(
        source[18],
        target_ledger_id=ledger_id,
        gross_cents=int(source[13]),
        net_cents=int(source[15]),
        reason=reason,
        created_at=now,
    )
    cursor = conn.execute(
        """INSERT INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
        record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,replaces_ledger_id,delta_json,category_json,price_cents_json,
        gross_cents,waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "reversal",
            *source[1:10],
            key,
            ledger_id,
            *source[10:13],
            -int(source[13]),
            int(source[14]),
            -int(source[15]),
            int(source[16]),
            source[17],
            REVERSAL_VERSION,
            reason,
            json.dumps(attestation, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    return int(cursor.lastrowid)


from services.peer_change_events import notify_local_change


@notify_local_change
def reverse_entry(ledger_id: int, *, reason: str, actor: str = "operator") -> int:
    with _open() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _reverse_entry(conn, ledger_id, reason=reason, actor=actor)


def _reverse_entry(conn, ledger_id: int, *, reason: str, actor: str = "operator") -> int:
    """Append one exact compensating entry; immutable rows are never edited."""
    reason = reason.strip()
    if not reason:
        raise ValueError("correction reason is required")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    source = _load_correction_source(conn, ledger_id)
    previous = conn.execute('SELECT MAX(id) FROM billing_ledger').fetchone()[0] or 0
    result = _ensure_reversal(conn, ledger_id, source, reason=reason, now=now)
    if result > previous:
        from services.billing_correction_transfer import enqueue_corrections
        enqueue_corrections(conn, [(ledger_id, result, 'reverse')], actor=actor, reason=reason, created_at=now)
    return result


@notify_local_change
def replace_entry(ledger_id: int, *, gross_cents: int, net_cents: int, reason: str, actor: str = "operator") -> int:
    with _open() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _replace_entry(conn, ledger_id, gross_cents=gross_cents, net_cents=net_cents, reason=reason, actor=actor)


def _replace_entry(conn, ledger_id: int, *, gross_cents: int, net_cents: int, reason: str, actor: str = "operator") -> int:
    """Atomically append an exact reversal and manual replacement.

    Both events commit together. Any failure while inserting the replacement
    rolls the newly-created reversal back as part of the same SQLite transaction.
    """
    if type(gross_cents) is not int or type(net_cents) is not int or not 0 <= net_cents <= gross_cents <= 2**63 - 1:
        raise ValueError("invalid replacement amounts")
    reason = reason.strip()
    if not reason:
        raise ValueError("correction reason is required")
    key = f"replacement:{ledger_id}:{FORMULA_VERSION}"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    existing = _existing_adjustment(
        conn,
        key=key,
        gross_cents=gross_cents,
        net_cents=net_cents,
        reason=reason,
        conflict="replacement",
    )
    if existing is not None:
        return existing
    source = _load_correction_source(conn, ledger_id)
    latest = conn.execute('SELECT id,entry_kind,replaces_ledger_id FROM billing_ledger WHERE source_daily_record_id=? ORDER BY id DESC LIMIT 1',
                          (source[8],)).fetchone()
    if latest[0] != ledger_id and not (latest[1] == 'reversal' and latest[2] == ledger_id):
        raise ValueError('The selected posting has already been superseded')
    reversal_id = _ensure_reversal(conn, ledger_id, source, reason=reason, now=now)
    waste_bp = _manual_waste_basis_points(gross_cents, net_cents)
    attestation = _manual_adjustment_attestation(
        source[18],
        action="replace_entry",
        target_ledger_id=ledger_id,
        gross_cents=gross_cents,
        net_cents=net_cents,
        waste_basis_points=waste_bp,
        reason=reason,
        created_at=now,
    )
    attestation['manual_adjustment']['actor'] = actor.strip()
    cursor = conn.execute(
        """INSERT INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
        record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,replaces_ledger_id,delta_json,category_json,price_cents_json,
        gross_cents,waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "replacement",
            *source[1:10],
            key,
            reversal_id,
            *source[10:13],
            gross_cents,
            waste_bp,
            net_cents,
            int(source[16]),
            source[17],
            MANUAL_ADJUSTMENT_VERSION,
            reason,
            json.dumps(attestation, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    result = int(cursor.lastrowid)
    from services.billing_correction_transfer import enqueue_corrections
    enqueue_corrections(conn, [(ledger_id, result, 'replace')], actor=actor, reason=reason, created_at=now)
    return result


@notify_local_change
def approve_held_entry(ledger_id: int, *, gross_cents: int, net_cents: int, reason: str, actor: str = "operator") -> int:
    with _open() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _approve_held_entry(conn, ledger_id, gross_cents=gross_cents, net_cents=net_cents, reason=reason, actor=actor)


def _approve_held_entry(conn, ledger_id: int, *, gross_cents: int, net_cents: int, reason: str, actor: str = "operator") -> int:
    """Approve a hold with a clearly marked operator-entered adjustment."""
    if type(gross_cents) is not int or type(net_cents) is not int or not 0 <= net_cents <= gross_cents <= 2**63 - 1:
        raise ValueError("invalid replacement amounts")
    reason = reason.strip()
    if not reason:
        raise ValueError("approval reason is required")
    key = f"hold-approval:{ledger_id}:{MANUAL_APPROVAL_VERSION}"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    existing = _existing_adjustment(
        conn,
        key=key,
        gross_cents=gross_cents,
        net_cents=net_cents,
        reason=reason,
        conflict="hold approval",
    )
    if existing is not None:
        return existing
    source = _load_correction_source(conn, ledger_id)
    if source[0] != "hold":
        raise ValueError("only a hold can be explicitly approved")
    if conn.execute('SELECT MAX(id) FROM billing_ledger WHERE source_daily_record_id=?', (source[8],)).fetchone()[0] != ledger_id:
        raise ValueError('The selected hold has already been superseded')
    waste_bp = _manual_waste_basis_points(gross_cents, net_cents)
    attestation = _manual_adjustment_attestation(
        source[18],
        action="approve_hold",
        target_ledger_id=ledger_id,
        gross_cents=gross_cents,
        net_cents=net_cents,
        waste_basis_points=waste_bp,
        reason=reason,
        created_at=now,
        original_hold_reason=source[19],
    )
    attestation['manual_adjustment']['actor'] = actor.strip()
    cursor = conn.execute(
        """INSERT INTO billing_ledger(entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
        record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,replaces_ledger_id,delta_json,category_json,price_cents_json,
        gross_cents,waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,attestation_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "replacement",
            *source[1:10],
            key,
            ledger_id,
            *source[10:13],
            gross_cents,
            waste_bp,
            net_cents,
            int(source[16]),
            source[17],
            MANUAL_ADJUSTMENT_VERSION,
            reason,
            json.dumps(attestation, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    result = int(cursor.lastrowid)
    from services.billing_correction_transfer import enqueue_corrections
    enqueue_corrections(conn, [(ledger_id, result, 'approve_hold')], actor=actor, reason=reason, created_at=now)
    return result


def audit_coverage() -> AuditCoverage:
    """Separate historical non-ledger rows from missing expected ledger work."""
    with _open(commit=False) as conn:
        uncovered = conn.execute(
            """SELECT d.source_json FROM daily_meter_records d WHERE NOT EXISTS
               (SELECT 1 FROM billing_ledger l WHERE l.source_daily_record_id=d.id)"""
        ).fetchall()
        state_rows = conn.execute(
            f"""SELECT source_daily_record_id,entry_kind,effective_state
                FROM ({_AUDIT_SELECT}) audit
                WHERE source_daily_record_id IS NOT NULL"""
        ).fetchall()
    legacy_uncovered = 0
    expected_missing = 0
    for (source_json,) in uncovered:
        try:
            source = json.loads(source_json)
        except (TypeError, json.JSONDecodeError):
            source = None
        if isinstance(source, dict) and source.get("billing_ledger_expected"):
            expected_missing += 1
        else:
            legacy_uncovered += 1
    ledger_sources = {int(row[0]) for row in state_rows}
    corrected_sources = {
        int(source_id)
        for source_id, kind, _state in state_rows
        if kind in {"reversal", "replacement"}
    }
    effective_posted = sum(
        1
        for _source_id, kind, state in state_rows
        if state == "effective" and kind in {"posting", "replacement"}
    )
    open_holds = sum(1 for _source_id, _kind, state in state_rows if state == "open_hold")
    open_reversals = sum(1 for _source_id, _kind, state in state_rows if state == "open_reversal")
    return AuditCoverage(
        legacy_uncovered=legacy_uncovered,
        expected_missing=expected_missing,
        ledger_sources=len(ledger_sources),
        effective_posted=effective_posted,
        open_holds=open_holds,
        open_reversals=open_reversals,
        corrected_sources=len(corrected_sources),
    )
