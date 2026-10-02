from datetime import date
from pathlib import Path
import sqlite3

import pytest

from database import _open, set_cfg
from services.billing_ledger import post_daily_record, get_audit_row
from services.billing_repricing_batch import BatchRepricingService
from services.pricing import PricingRepository, PriceList
from services.subject_history import load_subject_history
from test_billing_ledger import _daily
from test_report_detail_archive import fixture, archive_all


def setup():
    _, _, archive = fixture()
    set_cfg("billing_day", "25")
    PricingRepository().set_prices(0, date(2024, 1, 1), PriceList(a4_color=1))
    ids = []
    for day in ("2024-01-03", "2024-01-04"):
        with _open() as conn:
            row = _daily(conn, {"reconciliation": {"billing_safe": True}}, record_date=day)
        ids.append(post_daily_record(row))
    files = archive_all(archive)
    return ids, files


def scope(day=3):
    return date(2024, 1, day), date(2024, 1, day), [0]


def confirm(service, preview, day=3):
    return service.confirm(*scope(day), expected_revision=preview["revision"], actor="PC", reason="Reviewed cutoff",
                           apply_current_period=True)


def test_archive_rebucket_keeps_files_amounts_totals_and_prior_amendments(monkeypatch):
    ids, files = setup()
    originals = {f["path"]: Path(f["path"]).read_bytes() for f in files}
    total = sum(row.period_usage for row in load_subject_history([0]))
    service = BatchRepricingService()
    set_cfg("billing_day", "10")
    preview = service.preview(*scope(), apply_current_period=True)
    assert preview["archive_count"] >= 1
    changed = confirm(service, preview)
    assert get_audit_row(changed[0]).period_start == "2023-12-11"
    assert get_audit_row(ids[0]).period_start == "2023-12-26"
    set_cfg("billing_day", "20")
    confirm(service, service.preview(*scope(4), apply_current_period=True), 4)
    assert all(Path(path).read_bytes() == content for path, content in originals.items())
    # Monthly views must still work without reopening any immutable archive file.
    from services.report_detail_archive import ReportDetailArchive
    def forbidden(*args):
        raise AssertionError("Unexpected cold detail read")
    monkeypatch.setattr(ReportDetailArchive, "_file", forbidden)
    monthly = load_subject_history([0])
    assert sum(row.period_usage for row in monthly) == total
    assert load_subject_history([0], only_period=(date(2023, 12, 11), date(2024, 1, 10)))[0].period_usage == 10
    assert load_subject_history([0], only_period=(date(2023, 12, 21), date(2024, 1, 20)))[0].period_usage == 10


def test_summary_failure_rolls_back_ledger_and_receipt():
    ids, _ = setup()
    set_cfg("billing_day", "10")
    service = BatchRepricingService()
    preview = service.preview(*scope(), apply_current_period=True)
    before = load_subject_history([0])
    with _open() as conn:
        conn.execute("CREATE TRIGGER fail_rebucket BEFORE INSERT ON archived_subject_periods BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.Error):
        confirm(service, preview)
    assert load_subject_history([0]) == before
    assert get_audit_row(ids[0]).period_start == "2023-12-26"
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM config_log WHERE config_key='billing_reprice_batch'").fetchone()[0] == 0


def test_corrupt_archive_after_preview_prevents_ledger_writes():
    _, files = setup()
    set_cfg("billing_day", "10")
    service = BatchRepricingService()
    preview = service.preview(*scope(), apply_current_period=True)
    for item in files:
        if item["kind"] == "subject":
            Path(item["path"]).write_bytes(b"corrupt fixture")
    with pytest.raises(ValueError, match="checksum"):
        confirm(service, preview)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 2
