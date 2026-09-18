from datetime import date
import sqlite3

import pytest

from database import _open
from services.billing_ledger import post_daily_record, get_audit_row
from services.billing_repricing_batch import BatchRepricingService
from services.pricing import PricingRepository, PriceList
from test_billing_ledger import _daily
from test_shared_settings import configured
from ui.billing_repricing_batch import BatchRepricingDialog

SCOPE = date(2026, 7, 1), date(2026, 7, 31), [0]


def postings():
    configured()
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1))
    ids = []
    for day, safe in (("2026-07-15", True), ("2026-07-16", True), ("2026-07-17", False)):
        with _open() as conn:
            record_id = _daily(conn, {"reconciliation": {"billing_safe": safe}}, record_date=day)
        ids.append(post_daily_record(record_id))
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=2))
    return ids


def confirm(service, preview):
    return service.confirm(*SCOPE, expected_revision=preview["revision"], actor="Fixture PC", reason="Correct dated prices")


def test_batch_preview_confirm_retry_preserves_originals_and_skips_held():
    original = postings()
    service = BatchRepricingService()
    preview = service.preview(*SCOPE)
    assert [p["ledger_id"] for p in preview["changed"]] == original[:2]
    assert preview["skipped"] == [original[2]]
    results = confirm(service, preview)
    assert confirm(service, preview) == results
    assert len(results) == 2
    assert all(get_audit_row(i).gross_cents == 600 for i in results)
    assert all(get_audit_row(i).gross_cents == 300 for i in original[:2])
    after = service.preview(*SCOPE)
    assert not after["changed"] and after["unchanged"] == 2
    assert after["skipped"] == [original[2]]


def test_second_replacement_failure_rolls_back_entire_batch_and_receipt():
    postings()
    service = BatchRepricingService()
    preview = service.preview(*SCOPE)
    with _open() as conn:
        conn.execute("""CREATE TRIGGER fail_second_replacement BEFORE INSERT ON billing_ledger
            WHEN NEW.entry_kind='replacement' AND NEW.record_date='2026-07-16'
            BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
    with pytest.raises(sqlite3.Error):
        confirm(service, preview)
    assert service.preview(*SCOPE) == preview
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM config_log WHERE config_key='billing_reprice_batch'").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["new_day", "new_price"])
def test_changed_range_after_preview_requires_review_again(change):
    postings()
    service = BatchRepricingService()
    preview = service.preview(*SCOPE)
    if change == "new_price":
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=3))
    else:
        with _open() as conn:
            record_id = _daily(conn, {"reconciliation": {"billing_safe": True}}, record_date="2026-07-18")
        post_daily_record(record_id)
    with pytest.raises(ValueError, match="changed after preview"):
        confirm(service, preview)


def test_batch_retry_with_different_reason_is_rejected():
    postings()
    service = BatchRepricingService()
    preview = service.preview(*SCOPE)
    confirm(service, preview)
    with pytest.raises(ValueError, match="retry differs"):
        service.confirm(*SCOPE, expected_revision=preview["revision"], actor="Fixture PC", reason="Different")


def test_dialog_preview_cancel_is_read_only_and_confirmation_requires_reason():
    original = postings()
    dialog = BatchRepricingDialog(today=date(2026, 7, 31))
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert not dialog.confirm_button.isEnabled()
    assert dialog.table.rowCount() == 3
    dialog.reason.setText("Price correction")
    assert dialog.confirm_button.isEnabled()
    dialog.reject()
    assert all(get_audit_row(i).gross_cents == 300 for i in original[:2])
    dialog.pool.shutdown(wait=True)


def test_dialog_confirmation_applies_all_changed_rows():
    postings()
    dialog = BatchRepricingDialog(today=date(2026, 7, 31))
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    dialog.reason.setText("Price correction")
    dialog.confirm()
    assert len(dialog.result_ids) == 2
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.pool.shutdown(wait=True)
