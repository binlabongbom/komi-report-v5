import json

import pytest

from database import _open, get_db_path
from services.billing_ledger import post_daily_record, get_audit_row, audit_coverage
from services.billing_manual_review import BillingManualReview
from test_billing_ledger import _daily
from test_billing_repricing import posting
from test_peer_billing_amendments import counts, peer, clone


def held():
    posting()
    with _open() as conn:
        record = _daily(conn, {}, record_date='2026-07-17')
    return post_daily_record(record)


def test_closed_hold_review_preserves_source_flags_and_can_be_shared(tmp_path):
    target = held()
    b = peer(clone(tmp_path, 'B'))
    service = BillingManualReview()
    preview = service.preview(target)
    with _open(commit=False) as conn:
        original = conn.execute('SELECT * FROM daily_meter_records ORDER BY id').fetchall()
    options = dict(expected_revision=preview['revision'], actor='TEST-PC', reason='Reviewed document', gross_cents=150, net_cents=140)
    result = service.confirm(target, **options)
    assert service.confirm(target, **options) == result
    assert audit_coverage().open_holds == 0
    assert json.loads(get_audit_row(result).attestation_json)['billing_safe'] is False
    assert get_audit_row(target).effective_state == 'resolved_hold'
    with _open(commit=False) as conn:
        assert conn.execute('SELECT * FROM daily_meter_records ORDER BY id').fetchall() == original
    b.receive('A', peer().pending('B'))
    with b.service._connection() as conn:
        proof = json.loads(conn.execute('SELECT attestation_json FROM billing_ledger ORDER BY id DESC LIMIT 1').fetchone()[0])
        assert proof['manual_adjustment']['actor'] == 'TEST-PC'
        assert proof['manual_adjustment']['amount_origin'] == 'operator_entered'


def test_stale_evidence_and_retry_difference_cannot_write():
    target, service = held(), BillingManualReview()
    preview = service.preview(target)
    options = dict(expected_revision=preview['revision'], actor='A', reason='Reviewed', gross_cents=100, net_cents=90)
    with _open() as conn:
        conn.execute('UPDATE daily_meter_records SET sample_count=sample_count+1 WHERE record_date=?', (preview['day'],))
    before = counts(get_db_path())
    with pytest.raises(ValueError, match='changed'):
        service.confirm(target, **options)
    assert counts(get_db_path()) == before
    options['expected_revision'] = service.preview(target)['revision']
    service.confirm(target, **options)
    before = counts(get_db_path())
    with pytest.raises(ValueError, match='retry'):
        service.confirm(target, **{**options, 'actor': 'different-reviewer'})
    assert counts(get_db_path()) == before


def test_audit_dialog_cancel_review_then_confirm():
    from PyQt6.QtWidgets import QApplication
    from ui.billing_manual_review import BillingManualReviewDialog
    from v5_pages import PageBillingAudit
    app = QApplication.instance() or QApplication([])
    target = held()
    page = PageBillingAudit()
    page.table.selectRow(next(i for i, row in enumerate(page._rows) if row.id == target))
    page.manual_review_button.click()
    dialog = page.findChild(BillingManualReviewDialog)
    assert dialog is not None and not dialog.confirm_button.isEnabled()
    dialog.reason.setText('Reviewed source document')
    dialog.gross.setValue(2)
    dialog.net.setValue(1.9)
    assert not dialog.confirm_button.isEnabled()
    dialog.reviewed.setChecked(True)
    assert dialog.confirm_button.isEnabled()
    before = counts(get_db_path())
    dialog.reject()
    assert counts(get_db_path()) == before
    dialog = BillingManualReviewDialog(target, page)
    dialog.reason.setText('Reviewed source document')
    dialog.gross.setValue(2)
    dialog.net.setValue(1.9)
    dialog.reviewed.setChecked(True)
    dialog.confirm_button.click()
    assert dialog.result_id and audit_coverage().open_holds == 0
    page.close()
    app.processEvents()
