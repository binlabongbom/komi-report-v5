from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from database import _open
from services.billing_ledger import get_audit_row, post_daily_record, replace_entry
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository
from v5_pages import PageBillingAudit, audit_row_detail_text


def _daily(*, record_date: str, source: dict) -> int:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        return int(
            conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    0,
                    record_date,
                    "{}",
                    "{}",
                    json.dumps({"counter.paper.full_color.a4": 3}),
                    json.dumps({"counter.paper.full_color.a4": "a4_color"}),
                    json.dumps(source),
                    now,
                    now,
                    2,
                    0,
                    0,
                    now,
                ),
            ).fetchone()[0]
        )


def _insert_direct_events(count: int, *, printer_name: str | None = None) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        for index in range(count):
            conn.execute(
                """INSERT INTO billing_ledger(
                       entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,
                       record_date,period_start,period_end,source_daily_record_id,source_hash,idempotency_key,
                       replaces_ledger_id,delta_json,category_json,price_cents_json,gross_cents,
                       waste_basis_points,net_cents,billing_day,currency,formula_version,hold_reason,
                       attestation_json,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "posting",
                    0,
                    "serial:AUDIT-SERIAL",
                    printer_name if printer_name is not None else f"Audit Printer {index:03d}",
                    "AUDIT-SERIAL",
                    "2026-07-16",
                    "2026-07-01",
                    "2026-07-31",
                    None,
                    f"{index:064x}",
                    f"audit-{index:03d}",
                    None,
                    '{"counter.paper.full_color.a4": 1}',
                    '{"counter.paper.full_color.a4": "a4_color"}',
                    '{"a4_color": 100}',
                    100,
                    200,
                    98,
                    31,
                    "THB",
                    "komi.billing.v1",
                    None,
                    '{"billing_safe": true}',
                    now,
                ),
            )


def test_billing_audit_ui_shows_effective_correction_and_open_hold_lifecycle():
    app = QApplication.instance() or QApplication([])
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SERIAL-1")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    posting_id = post_daily_record(
        _daily(record_date="2026-07-16", source={"reconciliation": {"billing_safe": True}})
    )
    replacement_id = replace_entry(
        posting_id,
        gross_cents=250,
        net_cents=240,
        reason="approved meter correction",
    )
    post_daily_record(_daily(record_date="2026-07-17", source={}))

    page = PageBillingAudit()
    page.resize(1200, 760)
    page.show()
    app.processEvents()

    assert page.table.rowCount() == 4
    events = [page.table.item(row, 3).text() for row in range(page.table.rowCount())]
    assert any("REPLACEMENT · มีผล" in event for event in events)
    assert any("REVERSAL · Reversal จับคู่แล้ว" in event for event in events)
    assert any("POSTING · ถูกแทนที่" in event for event in events)
    assert any("HOLD · Hold รอตรวจ" in event for event in events)
    assert "Hold รอตรวจ 1 วัน" in page.coverage.text()

    page.state_filter.setCurrentIndex(page.state_filter.findData("open_hold"))
    app.processEvents()
    assert page.table.rowCount() == 1
    assert "HOLD · Hold รอตรวจ" in page.table.item(0, 3).text()

    replacement = get_audit_row(replacement_id)
    assert replacement is not None
    detail = audit_row_detail_text(replacement)
    assert f"Ledger ID: #{replacement_id}" in detail
    assert f"Ledger #{replacement.replaces_ledger_id}" in detail
    assert "Daily Record #" in detail
    assert replacement.source_hash in detail
    assert "รอบบิลที่ถูกตรึง:" in detail
    assert "Delta snapshot:" in detail
    assert "Category snapshot:" in detail
    assert "Price snapshot (cents):" in detail
    assert "กระดาษเสีย:" in detail
    assert "Formula version: komi.billing.manual-adjustment.v1" in detail
    assert "Attestation:" in detail
    assert "บันทึกเมื่อ:" in detail
    page.close()
    app.processEvents()


def test_billing_audit_load_more_search_and_export_include_over_100_rows(tmp_path):
    app = QApplication.instance() or QApplication([])
    _insert_direct_events(105)
    page = PageBillingAudit()
    page.resize(1200, 760)
    page.show()
    app.processEvents()

    assert page.table.rowCount() == 100
    assert "100 จาก 105" in page.row_count.text()
    assert page.load_more_button.isVisible()
    page._load_more()
    assert page.table.rowCount() == 105
    assert "105 จาก 105" in page.row_count.text()

    page.search.setText("audit-104")
    page._reset_and_refresh()
    assert page.table.rowCount() == 1
    assert "Audit Printer 104" == page.table.item(0, 2).text()

    page.search.clear()
    page._reset_and_refresh()
    export_path = tmp_path / "billing-audit.csv"
    assert page._export_rows_to(str(export_path)) == 105
    with export_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 106
    assert rows[0][0:4] == ["id", "entry_kind", "effective_state", "device_slot"]
    assert "attestation_json" in rows[0]
    assert "source_hash" in rows[0]
    page.close()
    app.processEvents()
