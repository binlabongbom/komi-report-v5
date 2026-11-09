from datetime import date
import sqlite3

import pytest

from database import _open, set_cfg
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
    dialog.future.result(timeout=10)
    dialog.collect()
    assert len(dialog.result_ids) == 2
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.pool.shutdown(wait=True)


def test_discount_only_batch_preserves_issued_rows_and_periods_and_retry():
    original = postings()
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1))
    set_cfg("waste_paper_pct", "50")
    service = BatchRepricingService()
    assert not service.preview(*SCOPE)["changed"]
    preview = service.preview(*SCOPE, apply_current_discount=True)
    assert len(preview["changed"]) == 2
    assert preview["skipped"] == [original[2]]
    row = preview["changed"][0]
    assert (row["old_waste_basis_points"], row["waste_basis_points"]) == (200, 5000)
    assert (row["old_net_cents"], row["net_cents"]) == (300, 200)
    args = dict(expected_revision=preview["revision"], actor="Fixture PC", reason="Discount correction", apply_current_discount=True)
    results = service.confirm(*SCOPE, **args)
    set_cfg("waste_paper_pct", "20")
    assert service.confirm(*SCOPE, **args) == results
    with pytest.raises(ValueError, match="retry differs"):
        service.confirm(*SCOPE, **{**args, "apply_current_discount": False})
    for old_id, new_id in zip(original, results):
        old, new = get_audit_row(old_id), get_audit_row(new_id)
        assert old.net_cents == 300 and new.net_cents == 200
        assert old.period_start == new.period_start and old.period_end == new.period_end
        assert old.delta_json == new.delta_json
    with _open(commit=False) as conn:
        assert conn.execute("SELECT SUM(net_cents) FROM billing_ledger WHERE entry_kind!='hold'").fetchone()[0] == 400


def test_discount_change_after_preview_rejects_without_writing_anything():
    postings()
    set_cfg("waste_paper_pct", "10")
    service = BatchRepricingService()
    preview = service.preview(*SCOPE, apply_current_discount=True)
    set_cfg("waste_paper_pct", "20")
    with pytest.raises(ValueError, match="changed after preview"):
        service.confirm(*SCOPE, expected_revision=preview["revision"], actor="PC", reason="test", apply_current_discount=True)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 3


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "101", "invalid"])
def test_invalid_current_discount_does_not_silently_skip_postings(value):
    postings()
    set_cfg("waste_paper_pct", value)
    service = BatchRepricingService()
    with pytest.raises(ValueError):
        service.preview(*SCOPE, apply_current_discount=True)
    assert len(service.preview(*SCOPE)["changed"]) == 2


def test_discount_batch_failure_rolls_back_all_changes():
    postings()
    set_cfg("waste_paper_pct", "10")
    service = BatchRepricingService()
    preview = service.preview(*SCOPE, apply_current_discount=True)
    with _open() as conn:
        conn.execute("""CREATE TRIGGER fail_discount BEFORE INSERT ON billing_ledger
            WHEN NEW.entry_kind='replacement' AND NEW.record_date='2026-07-16'
            BEGIN SELECT RAISE(ABORT,'injected'); END""")
    with pytest.raises(sqlite3.Error):
        service.confirm(*SCOPE, expected_revision=preview["revision"], actor="PC", reason="test", apply_current_discount=True)
    assert service.preview(*SCOPE, apply_current_discount=True) == preview
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM config_log WHERE config_key='billing_reprice_batch'").fetchone()[0] == 0


def test_dialog_discount_toggle_invalidates_preview_and_displays_reviewed_rate():
    postings()
    set_cfg("waste_paper_pct", "10")
    dialog = BatchRepricingDialog(today=date(2026, 7, 31))
    try:
        dialog.load()
        dialog.future.result(timeout=10)
        dialog.collect()
        dialog.reason.setText("Reviewed discount")
        assert dialog.confirm_button.isEnabled()
        dialog.current_discount.setChecked(True)
        assert not dialog.confirm_button.isEnabled() and dialog.preview is None
        dialog.load()
        dialog.future.result(timeout=10)
        dialog.collect()
        assert dialog.table.item(0, 3).text() == "2.00% → 10.00%"
        dialog.confirm()
        dialog.future.result(timeout=10)
        dialog.collect()
        assert all(get_audit_row(i).waste_basis_points == 1000 for i in dialog.result_ids)
        assert len(dialog.result_ids) == 2
    finally:
        dialog.close()
        dialog.pool.shutdown(wait=True)


def test_current_period_is_opt_in_stale_checked_and_keeps_amounts():
    original = postings()
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1))
    set_cfg("billing_day", "10")
    service = BatchRepricingService()
    assert not service.preview(*SCOPE)["changed"]
    p = service.preview(*SCOPE, apply_current_period=True)
    assert p["changed"][0]["period_start"] == "2026-07-11"
    assert p["changed"][0]["period_end"] == "2026-08-10"
    set_cfg("billing_day", "20")
    with pytest.raises(ValueError, match="changed after preview"):
        service.confirm(*SCOPE, expected_revision=p["revision"], actor="PC", reason="period", apply_current_period=True)
    p = service.preview(*SCOPE, apply_current_period=True)
    args = dict(expected_revision=p["revision"], actor="PC", reason="period", apply_current_period=True)
    result = service.confirm(*SCOPE, **args)
    assert service.confirm(*SCOPE, **args) == result
    assert get_audit_row(result[0]).period_start == "2026-06-21"
    assert get_audit_row(original[0]).period_start == "2026-07-01"
    assert get_audit_row(original[0]).net_cents == get_audit_row(result[0]).net_cents
    with pytest.raises(ValueError, match="retry differs"):
        service.confirm(*SCOPE, **{**args, "apply_current_period": False})


def test_dialog_remains_responsive_and_cannot_dismiss_pending_commit():
    from concurrent.futures import Future
    from PyQt6.QtWidgets import QDialogButtonBox
    postings()
    dialog = BatchRepricingDialog(today=date(2026, 7, 31))
    dialog.current_period.setChecked(True)
    set_cfg("billing_day", "10")
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert "2026-08-10" in dialog.table.item(0, 6).text()
    dialog.reason.setText("Reviewed period")
    dialog.pool.shutdown(wait=True)
    pending = Future()
    class DeferredPool:
        def submit(self, *args, **kwargs):
            assert kwargs["apply_current_period"] is True
            return pending
    dialog.pool = DeferredPool()
    dialog.show()
    dialog.confirm()
    assert dialog.future is pending
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).isEnabled()
    dialog.reject()
    assert dialog.isVisible()
    pending.set_exception(ValueError("changed after preview"))
    dialog.collect()
    assert dialog.preview is None and not dialog.confirm_button.isEnabled()
    assert dialog.load_button.isEnabled()
    dialog.reject()
    assert not dialog.isVisible()
