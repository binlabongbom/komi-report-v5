from datetime import date
import json
import sqlite3

import pytest

from database import _open
from services.billing_ledger import get_audit_row, post_daily_record, replace_entry
from services.billing_repricing import BillingRepricingService, REPRICE_VERSION
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PricingRepository, PriceList
from test_billing_ledger import _daily


def posting():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1))
    with _open() as conn:
        record_id = _daily(conn, {"reconciliation": {"billing_safe": True}})
    ledger_id = post_daily_record(record_id)
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2))
    return ledger_id


def confirm(service, ledger_id, preview):
    return service.confirm(ledger_id, expected_revision=preview["revision"], actor="TEST-PC", reason="Correct dated price")


def test_reprice_appends_exact_reversal_and_dated_replacement():
    ledger_id = posting()
    original = get_audit_row(ledger_id)
    PricingRepository().set_prices(0, date(2026, 8, 1), PriceList(a4_color=99))
    service = BillingRepricingService()
    preview = service.preview(ledger_id)
    assert preview["price_effective_date"] == "2026-07-01"
    assert (preview["old_gross_cents"], preview["gross_cents"]) == (300, 600)
    replacement_id = confirm(service, ledger_id, preview)
    assert confirm(service, ledger_id, preview) == replacement_id
    corrected = get_audit_row(replacement_id)
    assert corrected.formula_version == REPRICE_VERSION
    assert corrected.gross_cents == 600
    assert corrected.period_start == original.period_start
    assert corrected.waste_basis_points == original.waste_basis_points
    assert corrected.delta_json == original.delta_json
    assert get_audit_row(ledger_id).gross_cents == original.gross_cents
    with _open(commit=False) as conn:
        rows = conn.execute("SELECT entry_kind,gross_cents FROM billing_ledger ORDER BY id").fetchall()
    assert rows == [("posting", 300), ("reversal", -300), ("replacement", 600)]
    audit = json.loads(corrected.attestation_json)
    assert audit["repricing"]["actor"] == "TEST-PC"
    assert audit["repricing"]["source_delta_used_for_amounts"]
    assert not service.preview(replacement_id)["changed"]


def test_price_change_after_preview_is_rejected_without_reversal():
    ledger_id = posting()
    service = BillingRepricingService()
    preview = service.preview(ledger_id)
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=3))
    with pytest.raises(ValueError, match="changed after preview"):
        confirm(service, ledger_id, preview)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 1


def test_repricing_failure_rolls_back_compensating_entry():
    ledger_id = posting()
    service = BillingRepricingService()
    preview = service.preview(ledger_id)
    with _open() as conn:
        conn.execute("""CREATE TRIGGER fail_reprice BEFORE INSERT ON billing_ledger
            WHEN NEW.entry_kind='replacement' BEGIN SELECT RAISE(ABORT,'injected reprice failure'); END""")
    with pytest.raises(sqlite3.Error):
        confirm(service, ledger_id, preview)
    assert service.preview(ledger_id) == preview
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 1


def test_manual_adjustment_cannot_be_relabelled_as_automatic_safe_usage():
    ledger_id = posting()
    replacement = replace_entry(ledger_id, gross_cents=400, net_cents=400, reason="Manually reviewed")
    service = BillingRepricingService()
    with pytest.raises(ValueError):
        service.preview(ledger_id)
    with pytest.raises(ValueError, match="verified automatic"):
        service.preview(replacement)


def test_second_price_correction_uses_latest_revision_without_double_counting():
    ledger_id = posting()
    service = BillingRepricingService()
    first = confirm(service, ledger_id, service.preview(ledger_id))
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=3))
    second = confirm(service, first, service.preview(first))
    assert get_audit_row(second).gross_cents == 900
    with _open(commit=False) as conn:
        assert conn.execute("SELECT SUM(gross_cents) FROM billing_ledger").fetchone()[0] == 900


def test_dialog_cancel_and_stale_preview_cannot_write():
    from PyQt6.QtWidgets import QApplication
    from ui.billing_repricing import BillingRepricingDialog
    app = QApplication.instance() or QApplication([])
    ledger_id = posting()
    dialog = BillingRepricingDialog(ledger_id)
    assert not dialog.confirm_button.isEnabled()
    dialog.reason.setText("Correct prices")
    assert dialog.confirm_button.isEnabled()
    dialog.reject()
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 1
    dialog = BillingRepricingDialog(ledger_id)
    dialog.reason.setText("Correct prices")
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=4))
    dialog.confirm_button.click()
    assert dialog.error.text()
    assert dialog.result_id is None
    dialog.close()
    app.processEvents()


def test_audit_page_opens_and_applies_reviewed_price_correction():
    from PyQt6.QtWidgets import QApplication
    from ui.billing_repricing import BillingRepricingDialog
    from v5_pages import PageBillingAudit
    app = QApplication.instance() or QApplication([])
    ledger_id = posting()
    page = PageBillingAudit()
    page.table.selectRow(0)
    assert page.reprice_button.isEnabled()
    page.reprice_button.click()
    dialog = page.findChild(BillingRepricingDialog)
    assert dialog is not None and dialog.ledger_id == ledger_id
    dialog.reason.setText("Correct dated price")
    dialog.confirm_button.click()
    assert dialog.result_id is not None
    assert page.table.rowCount() == 3
    page.close()
    app.processEvents()
