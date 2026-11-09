from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pytest

from database import _open, init_db, set_cfg, set_db_path
from services.billing_ledger import (
    FORMULA_VERSION,
    MANUAL_ADJUSTMENT_VERSION,
    REVERSAL_VERSION,
    approve_held_entry,
    audit_coverage,
    count_audit_rows,
    get_audit_row,
    ledger_totals,
    list_audit_rows,
    post_daily_record,
    replace_entry,
    reverse_entry,
)
from services.billing_periods import billing_month_range
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository


def _daily(conn, source: dict, *, incomplete: int = 0, slot: int = 0, record_date: str = "2026-07-16") -> int:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return conn.execute(
        """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,category_json,
             source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (slot, record_date, "{}", "{}", json.dumps({"counter.paper.full_color.a4": 3}),
         json.dumps({"counter.paper.full_color.a4": "a4_color"}), json.dumps(source), now, now, 2, 0, incomplete, now),
    ).fetchone()[0]


def test_safe_posting_is_integer_frozen_and_retry_idempotent(tmp_path):
    set_db_path(tmp_path / "ledger.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.005))
    set_cfg("waste_paper_pct", "2.5")
    with _open() as conn:
        record_id = _daily(conn, {"reconciliation": {"billing_safe": True}})
    first, second = post_daily_record(record_id), post_daily_record(record_id)
    assert first == second
    with _open(commit=False) as conn:
        row = conn.execute("SELECT entry_kind,gross_cents,net_cents,device_serial_snapshot FROM billing_ledger").fetchone()
        assert row == ("posting", 303, 303, "SERIAL-1")
        with __import__("pytest").raises(sqlite3.DatabaseError):
            conn.execute("UPDATE billing_ledger SET gross_cents=0")
        with __import__("pytest").raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM billing_ledger")


def test_missing_attestation_creates_visible_hold(tmp_path):
    set_db_path(tmp_path / "hold.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    with _open() as conn:
        record_id = _daily(conn, {})
    post_daily_record(record_id)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT entry_kind,hold_reason FROM billing_ledger").fetchone() == ("hold", "missing_or_unsafe_attestation")


def test_replacement_and_reversal_retries_require_identical_payload(tmp_path):
    set_db_path(tmp_path / "correction.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    set_cfg("billing_day", "31")
    set_cfg("waste_paper_pct", "0")
    with _open() as conn:
        record_id = _daily(conn, {"reconciliation": {"billing_safe": True}})

    posting_id = post_daily_record(record_id)
    replacement_id = replace_entry(posting_id, gross_cents=250, net_cents=240, reason="approved meter correction")

    assert replace_entry(posting_id, gross_cents=250, net_cents=240, reason="approved meter correction") == replacement_id
    with pytest.raises(ValueError, match="idempotency conflict"):
        replace_entry(posting_id, gross_cents=251, net_cents=240, reason="approved meter correction")
    with pytest.raises(ValueError, match="idempotency conflict"):
        replace_entry(posting_id, gross_cents=250, net_cents=240, reason="different reason")
    with pytest.raises(ValueError, match="idempotency conflict"):
        reverse_entry(posting_id, reason="different reason")

    start, end = billing_month_range(date(2026, 7, 16), 31)
    assert ledger_totals(0, start, end) == (250, 240)

    with _open(commit=False) as conn:
        correction_rows = conn.execute(
            """SELECT id,entry_kind,replaces_ledger_id,formula_version,waste_basis_points,attestation_json
               FROM billing_ledger WHERE entry_kind IN ('reversal','replacement') ORDER BY id"""
        ).fetchall()
    reversal, replacement = correction_rows
    assert reversal[2] == posting_id
    assert reversal[3] == REVERSAL_VERSION
    reversal_attestation = json.loads(reversal[5])
    assert reversal_attestation["calculation_mode"] == "exact_reversal"
    assert reversal_attestation["correction"]["target_ledger_id"] == posting_id
    assert replacement[2] == reversal[0]
    assert replacement[3] == MANUAL_ADJUSTMENT_VERSION
    assert replacement[4] == 400
    manual_attestation = json.loads(replacement[5])
    assert manual_attestation["billing_safe"] is False
    assert manual_attestation["calculation_mode"] == "manual_adjustment"
    assert manual_attestation["manual_adjustment"]["amount_origin"] == "operator_entered"
    assert manual_attestation["manual_adjustment"]["source_delta_used_for_amounts"] is False
    assert manual_attestation["manual_adjustment"]["source_price_used_for_amounts"] is False


def test_replacement_reversal_and_manual_amount_commit_atomically(tmp_path):
    set_db_path(tmp_path / "atomic-correction.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    with _open() as conn:
        record_id = _daily(conn, {"reconciliation": {"billing_safe": True}})
    posting_id = post_daily_record(record_id)
    with _open() as conn:
        conn.execute(
            """CREATE TRIGGER fail_manual_replacement
               BEFORE INSERT ON billing_ledger
               WHEN NEW.entry_kind='replacement'
               BEGIN SELECT RAISE(ABORT, 'synthetic replacement failure'); END"""
        )

    with pytest.raises(sqlite3.DatabaseError, match="synthetic replacement failure"):
        replace_entry(posting_id, gross_cents=250, net_cents=240, reason="atomic correction")

    with _open(commit=False) as conn:
        assert conn.execute(
            "SELECT entry_kind FROM billing_ledger ORDER BY id"
        ).fetchall() == [("posting",)]
    with _open() as conn:
        conn.execute("DROP TRIGGER fail_manual_replacement")
    replace_entry(posting_id, gross_cents=250, net_cents=240, reason="atomic correction")
    with _open(commit=False) as conn:
        assert conn.execute(
            "SELECT entry_kind FROM billing_ledger ORDER BY id"
        ).fetchall() == [("posting",), ("reversal",), ("replacement",)]


def test_explicit_hold_approval_appends_audited_replacement_without_reversal(tmp_path):
    set_db_path(tmp_path / "hold-approval.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    with _open() as conn:
        record_id = _daily(conn, {})
    hold_id = post_daily_record(record_id)

    replacement_id = approve_held_entry(hold_id, gross_cents=300, net_cents=294, reason="manager approved source evidence")
    assert approve_held_entry(hold_id, gross_cents=300, net_cents=294, reason="manager approved source evidence") == replacement_id
    with pytest.raises(ValueError, match="idempotency conflict"):
        approve_held_entry(hold_id, gross_cents=301, net_cents=294, reason="manager approved source evidence")

    with _open(commit=False) as conn:
        rows = conn.execute(
            "SELECT id,entry_kind,replaces_ledger_id,hold_reason,attestation_json FROM billing_ledger ORDER BY id"
        ).fetchall()
    assert [row[1] for row in rows] == ["hold", "replacement"]
    assert rows[1][2] == hold_id
    assert rows[1][3] == "manager approved source evidence"
    approval = json.loads(rows[1][4])["hold_approval"]
    assert approval["hold_ledger_id"] == hold_id
    assert approval["original_hold_reason"] == "missing_or_unsafe_attestation"
    with _open(commit=False) as conn:
        formula, waste_bp, attestation_json = conn.execute(
            "SELECT formula_version,waste_basis_points,attestation_json FROM billing_ledger WHERE id=?",
            (replacement_id,),
        ).fetchone()
    attestation = json.loads(attestation_json)
    assert formula == MANUAL_ADJUSTMENT_VERSION
    assert waste_bp == 200
    assert attestation["billing_safe"] is False
    assert attestation["calculation_mode"] == "manual_adjustment"
    assert attestation["manual_adjustment"]["source_delta_used_for_amounts"] is False


def test_source_hash_detects_mutation_after_initial_post(tmp_path):
    set_db_path(tmp_path / "source-mutation.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    with _open() as conn:
        record_id = _daily(conn, {"reconciliation": {"billing_safe": True}})
    post_daily_record(record_id)
    with _open() as conn:
        conn.execute(
            "UPDATE daily_meter_records SET closing_json=? WHERE id=?",
            (json.dumps({"counter.paper.full_color.a4": 999}), record_id),
        )

    with pytest.raises(ValueError, match="source evidence changed"):
        post_daily_record(record_id)


def test_retry_keeps_original_hash_and_identity_after_device_metadata_change(tmp_path):
    set_db_path(tmp_path / "device-change-retry.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office A", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    with _open() as conn:
        record_id = _daily(conn, {"reconciliation": {"billing_safe": True}})
    first_id = post_daily_record(record_id)
    with _open(commit=False) as conn:
        original = conn.execute(
            "SELECT source_hash,device_identity FROM billing_ledger WHERE id=?",
            (first_id,),
        ).fetchone()

    repository.replace_all([DeviceConfig(0, "Office B", "192.0.2.11", serial="SER-B")])
    assert post_daily_record(record_id) == first_id
    with _open(commit=False) as conn:
        retried = conn.execute(
            "SELECT source_hash,device_identity FROM billing_ledger WHERE id=?",
            (first_id,),
        ).fetchone()
    assert retried == original
    assert retried[1] == "serial:SER-A"


def test_identical_content_on_two_source_rows_has_distinct_idempotency_keys(tmp_path):
    set_db_path(tmp_path / "idempotency-collision.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [
            DeviceConfig(0, "Office A", "192.0.2.10", serial="SHARED-SERIAL"),
            DeviceConfig(1, "Office B", "192.0.2.11", serial="SHARED-SERIAL"),
        ]
    )
    pricing = PricingRepository()
    pricing.set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    pricing.set_prices(1, date(2026, 7, 1), PriceList(a4_color=1.0))
    source = {"reconciliation": {"billing_safe": True}}
    with _open() as conn:
        first_record = _daily(conn, source, slot=0)
        second_record = _daily(conn, source, slot=1)

    first_ledger = post_daily_record(first_record)
    second_ledger = post_daily_record(second_record)
    assert first_ledger != second_ledger
    with _open(commit=False) as conn:
        rows = conn.execute(
            "SELECT source_hash,idempotency_key,source_daily_record_id FROM billing_ledger ORDER BY id"
        ).fetchall()
    assert rows[0][0] == rows[1][0]
    assert rows[0][1] != rows[1][1]
    assert [row[2] for row in rows] == [first_record, second_record]


def test_audit_coverage_separates_legacy_expected_and_effective_lifecycle(tmp_path):
    set_db_path(tmp_path / "audit-coverage.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    safe = {"reconciliation": {"billing_safe": True}}
    with _open() as conn:
        _daily(conn, {}, record_date="2026-07-01")
        _daily(conn, {"billing_ledger_expected": FORMULA_VERSION}, record_date="2026-07-02")
        corrected_record = _daily(conn, safe, record_date="2026-07-03")
        approved_hold_record = _daily(conn, {}, record_date="2026-07-04")
        open_hold_record = _daily(conn, {}, record_date="2026-07-05")
        open_reversal_record = _daily(conn, safe, record_date="2026-07-06")

    corrected_posting = post_daily_record(corrected_record)
    replace_entry(corrected_posting, gross_cents=200, net_cents=196, reason="corrected")
    approved_hold = post_daily_record(approved_hold_record)
    approve_held_entry(approved_hold, gross_cents=100, net_cents=98, reason="approved")
    post_daily_record(open_hold_record)
    reversed_posting = post_daily_record(open_reversal_record)
    reverse_entry(reversed_posting, reason="void pending review")

    coverage = audit_coverage()
    assert coverage.legacy_uncovered == 1
    assert coverage.expected_missing == 1
    assert coverage.ledger_sources == 4
    assert coverage.effective_posted == 2
    assert coverage.open_holds == 1
    assert coverage.open_reversals == 1
    assert coverage.corrected_sources == 3

    rows = list_audit_rows(limit=None)
    assert count_audit_rows() == len(rows) == 8
    assert {row.effective_state for row in rows} >= {
        "effective",
        "open_hold",
        "open_reversal",
        "paired_reversal",
        "resolved_hold",
        "superseded",
    }
    assert count_audit_rows(state="effective") == 2
    assert count_audit_rows(state="correction") == 4
    assert len(list_audit_rows(2, offset=2)) == 2
    selected = get_audit_row(rows[0].id)
    assert selected == rows[0]
    assert len(selected.source_hash) == 64
    assert list_audit_rows(limit=None, search="SERIAL-1") == rows


def test_quantity_formula_upgrade_preserves_existing_v1_posting_and_raw_meter(tmp_path, monkeypatch):
    import services.billing_ledger as ledger
    from services.billing_repricing import BillingRepricingService
    set_db_path(tmp_path / 'old-ledger.db')
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, 'Synthetic', '192.0.2.10', serial='SYNTHETIC')])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.005))
    set_cfg('waste_paper_pct', '2.5')
    with _open() as conn:
        record_id = _daily(conn, {'reconciliation': {'billing_safe': True}})
    # Construct a pre-upgrade immutable posting through the real insert path.
    with monkeypatch.context() as old:
        old.setattr(ledger, 'FORMULA_VERSION', 'komi.billing.v1')
        old.setattr(ledger, 'quantity_first_amounts', lambda *args: (303, 295, {}))
        original = ledger.post_daily_record(record_id)
    assert ledger.post_daily_record(record_id) == original
    with _open(commit=False) as conn:
        assert conn.execute('SELECT gross_cents,net_cents,formula_version FROM billing_ledger').fetchone() == (303, 295, 'komi.billing.v1')
        assert json.loads(conn.execute('SELECT delta_json FROM daily_meter_records').fetchone()[0]) == {'counter.paper.full_color.a4': 3}
    preview = BillingRepricingService().preview(original)
    assert preview['old_net_cents'] == 295
    assert preview['net_cents'] == 303
    assert preview['changed']
