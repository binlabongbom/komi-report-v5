from datetime import date, datetime, UTC
import json
import sqlite3

import pytest

from database import _open, set_cfg
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.billing_ledger import post_daily_record, replace_entry
from services.billing_web_amendment import BillingWebAmendmentService
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import load_usage_history
from services.pricing import PriceList, PricingRepository
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore

KEY = "counter.print.full_color.a4"


def event(day, value, epoch=None, hour=8):
    at = datetime(2026, 9, day, hour, tzinfo=UTC)
    counts = {KEY: value, "counter.total.total": value, "counter.print.total": value,
              "counter.copy.total": 0, "counter.print.full_color_total": value, "counter.print.bw_total": 0}
    reading = MeterReading(host="192.0.2.10", collected_at=at.isoformat(),
        counters=tuple(WebCounterValue(k, k, v, "Meter", "fixture", Confidence.VERIFIED) for k, v in counts.items()),
        source="fixture", auth_state=WebAuthState.ADMIN)
    return WebObservationStore().record(0, reading, at=at, serial="SER-1", printer_name="Office", epoch_id=epoch)


def setup():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-1")])
    set_cfg("billing_day", "31")
    set_cfg("waste_paper_pct", "0")
    PricingRepository().set_prices(0, date(2026, 9, 1), PriceList(a4_color=1.0))
    store = SlotEpochStore()
    first = event(18, 1000)
    epoch = store.confirm(store.preview(0, first["id"], operation="initial", actor="A", reason="review"))
    event(21, 1301, epoch)
    with _open() as conn:
        raw = {"reconciliation": {"billing_safe": True}, "device_identity": {"serial": "SER-1", "name": "Office"}}
        record = conn.execute("""INSERT INTO daily_meter_records
            (device_slot,record_date,opening_json,closing_json,delta_json,category_json,source_json,
             first_success,last_success,sample_count,error_count,incomplete,created_at)
            VALUES(0,'2026-09-21',?,?,?,?,?,'2026-09-21T08:00:00+00:00','2026-09-21T08:00:00+00:00',1,0,0,'2026-09-22')""",
            tuple(json.dumps(v) for v in ({KEY: 1000}, {KEY: 1301}, {KEY: 301}, {KEY: "a4_color"}, raw))).lastrowid
    ledger = post_daily_record(record)
    service = BillingWebAmendmentService(today=lambda: date(2026, 9, 25))
    args = (0, epoch, date(2026, 9, 18), date(2026, 9, 21), UTC)
    return service, args, ledger


def confirm(service, args, preview):
    return service.confirm(*args, expected_revision=preview["revision"], actor="A", reason="ตรวจหลักฐานย้อนหลัง")


def snapshot():
    with _open(commit=False) as conn:
        return tuple(conn.execute(f"SELECT * FROM {table}").fetchall() for table in ("billing_ledger", "daily_meter_records", "config_log"))


def test_gap_allocation_and_later_backfill_preserve_total_and_issued_evidence():
    service, args, ledger = setup()
    before = snapshot()
    p = service.preview(*args)
    assert [r["day"] for r in p["changed"]] == ["2026-09-20", "2026-09-21"]
    assert p["old_net_cents"] == p["net_cents"] == 30100
    assert "ไม่ใช่ยอดที่ยืนยัน" in p["changed"][0]["intervals"][0]["remark"]
    result = confirm(service, args, p)
    assert confirm(service, args, p) == result
    assert snapshot()[0][0] == before[0][0]
    assert snapshot()[1][0] == before[1][0]
    with _open(commit=False) as conn:
        allocation = conn.execute("SELECT opening_json,closing_json,first_success,last_success,sample_count FROM daily_meter_records WHERE record_date='2026-09-20'").fetchone()
        assert allocation == ("{}", "{}", None, None, 0)
        new_id = conn.execute("SELECT id FROM daily_meter_records WHERE record_date='2026-09-20'").fetchone()[0]
    assert post_daily_record(new_id) == result[0]  # normal retry cannot duplicate allocation
    daily = load_usage_history([0], granularity="daily", today=date(2026, 9, 25))
    assert sum(r.a4_color for r in daily) == 301
    assert sum(r.net_cost for r in daily) == 301
    assert next(r for r in daily if r.period_start.day == 20).a4_color == 301
    assert any("ไม่ใช่ยอดที่ยืนยัน" in note for r in daily for note in r.remarks)
    event(19, 1100, args[1])
    event(20, 1250, args[1])
    p2 = service.preview(*args)
    confirm(service, args, p2)
    daily = load_usage_history([0], granularity="daily", today=date(2026, 9, 25))
    assert {r.period_start.day: r.a4_color for r in daily} == {19: 100, 20: 150, 21: 51}
    assert sum(r.net_cost for r in daily) == 301
    assert not any("ไม่ใช่ยอดที่ยืนยัน" in note for r in daily for note in r.remarks)
    assert not service.preview(*args)["changed"]


@pytest.mark.parametrize("change", ["new_evidence", "manual", "price_boundary"])
def test_changes_after_preview_do_not_write_partial_amendments(change):
    service, args, ledger = setup()
    preview = service.preview(*args)
    if change == "new_evidence":
        event(19, 1100, args[1])
    elif change == "manual":
        replace_entry(ledger, gross_cents=30000, net_cents=30000, reason="manual")
    else:
        PricingRepository().set_prices(0, date(2026, 9, 20), PriceList(a4_color=2))
    before = snapshot()
    with pytest.raises(ValueError):
        confirm(service, args, preview)
    assert snapshot() == before


def test_atomic_rollback_if_receipt_write_fails():
    service, args, _ = setup()
    preview = service.preview(*args)
    with _open() as conn:
        conn.execute("CREATE TRIGGER reject_amendment BEFORE INSERT ON config_log WHEN NEW.config_key='billing_web_allocation' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    before = snapshot()
    with pytest.raises(sqlite3.DatabaseError):
        confirm(service, args, preview)
    assert snapshot() == before


def test_partial_window_and_current_day_are_rejected():
    service, args, _ = setup()
    p = service.preview(*args)
    confirm(service, args, p)
    with pytest.raises(ValueError):
        service.preview(*args[:2], date(2026, 9, 20), args[3], UTC)
    with pytest.raises(ValueError):
        service.preview(*args[:3], date(2026, 9, 25), UTC)


def test_archive_evidence_keeps_amendment_available():
    from services.web_observation_archive import WebObservationArchive
    service, args, _ = setup()
    revision = service.preview(*args)["revision"]
    archive = WebObservationArchive()
    while archive.archive_batch(today=date(2028, 1, 1)):
        pass
    assert service.preview(*args)["revision"] == revision


def test_conflicting_same_instant_is_not_hidden_by_baseline_selection():
    service, args, _ = setup()
    event(18, 1001, args[1])
    before = snapshot()
    with pytest.raises(ValueError):
        service.preview(*args)
    assert snapshot() == before


def test_original_source_change_is_not_recertified():
    service, args, _ = setup()
    with _open() as conn:
        conn.execute("UPDATE daily_meter_records SET sample_count=sample_count+1")
    before = snapshot()
    with pytest.raises(ValueError, match="ต้นฉบับ"):
        service.preview(*args)
    assert snapshot() == before


def test_retry_requires_identical_actor_and_reason():
    service, args, _ = setup()
    p = service.preview(*args)
    confirm(service, args, p)
    with pytest.raises(ValueError, match="ยืนยันซ้ำ"):
        service.confirm(*args, expected_revision=p["revision"], actor="B", reason="different")


def test_repricing_uses_corrected_daily_delta_and_keeps_proof():
    from services.billing_repricing import BillingRepricingService
    service, args, _ = setup()
    amended = confirm(service, args, service.preview(*args))[0]
    PricingRepository().set_prices(0, date(2026, 9, 1), PriceList(a4_color=2))
    reprice = BillingRepricingService()
    preview = reprice.preview(amended)
    assert preview["net_cents"] == 60200
    reprice.confirm(amended, expected_revision=preview["revision"], actor="A", reason="price correction")
    assert sum(r.net_cost for r in load_usage_history([0], today=date(2026, 9, 25))) == 602


def test_dialog_cancel_preview_and_confirm_use_separate_steps():
    from ui.billing_web_amendment import BillingWebAmendmentDialog
    service, args, _ = setup()
    before = snapshot()
    dialog = BillingWebAmendmentDialog(args, service=service)
    dialog.reason.setText("review")
    assert not dialog.confirm_button.isEnabled()
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert dialog.confirm_button.isEnabled() and dialog.table.rowCount() == 2
    dialog.reject()
    dialog.pool.shutdown(wait=True)
    assert snapshot() == before
    dialog2 = BillingWebAmendmentDialog(args, service=service)
    dialog2.reason.setText("review")
    dialog2.load()
    dialog2.future.result(timeout=10)
    dialog2.collect()
    dialog2.confirm()
    assert not dialog2.cancel_button.isEnabled()
    dialog2.future.result(timeout=10)
    dialog2.collect()
    assert len(dialog2.result_ids) == 2
    dialog2.pool.shutdown(wait=True)


def test_excel_report_contains_current_amendment_notes(tmp_path):
    from openpyxl import load_workbook
    from services.report_excel_export import CloudReportsExportData, export_cloud_reports_xlsx
    service, args, _ = setup()
    confirm(service, args, service.preview(*args))
    daily = load_usage_history([0], granularity="daily", today=date(2026, 9, 25))
    report = CloudReportsExportData(selected_records=daily, selected_daily_records=daily,
        usage_daily_records=daily, monthly_records=daily, subjects=(), devices=tuple(DeviceConfigRepository().list()),
        period=("2026-09-18", "2026-09-21"), last_sync_at=None, generated_at=datetime(2026, 9, 25, tzinfo=UTC))
    path = export_cloud_reports_xlsx(tmp_path / "amended.xlsx", report)
    workbook = load_workbook(path)
    notes = workbook["หมายเหตุฉบับแก้ไข"]
    assert any("ไม่ใช่ยอดที่ยืนยัน" in str(row[4]) for row in notes.values)
    workbook.close()


def test_local_web_api_returns_amended_history_and_notes():
    from fastapi.testclient import TestClient
    import web_api
    service, args, _ = setup()
    confirm(service, args, service.preview(*args))
    response = TestClient(web_api.app).get("/api/reports/history?granularity=daily")
    assert response.status_code == 200
    data = response.json()["items"]
    assert sum(row["color"] for row in data) == 301
    assert any("ไม่ใช่ยอดที่ยืนยัน" in note for row in data for note in row["remarks"])
