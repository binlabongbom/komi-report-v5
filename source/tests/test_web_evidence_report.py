from datetime import date
from threading import Event

from openpyxl import load_workbook
from PyQt6.QtWidgets import QApplication
import pytest

import database
from services.device_config import DeviceConfigRepository
from services.web_evidence_report import load_evidence, inspect_counter, export_evidence_xlsx
from services.web_usage_projection import CounterIdentity
from services.web_observation_archive import WebObservationArchive
from test_web_usage_projection import events_for, BANGKOK, project
from ui.web_evidence_report import WebEvidenceDialog, projection_pdf


def request():
    return dict(slot=0, serial="SER-A", start=date(2026, 9, 18), end=date(2026, 9, 21), calendar_timezone=BANGKOK)


def test_range_filter_uses_instants_and_archived_payload_is_loaded_only_on_request(monkeypatch):
    events = events_for(("2026-09-17T23:00", 999), ("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1301), ("2026-09-22T00:00", 1400))
    archive = WebObservationArchive()
    while archive.archive_batch(today=date(2028, 1, 1)):
        pass
    result = load_evidence(database.get_db_path(), **request(), cancelled=Event())
    assert [e["id"] for e in result["events"]] == [e["id"] for e in events[1:3]]
    counter = CounterIdentity("counter.user.total.total", "user", "u-1")
    projection = inspect_counter(result, counter, **request())
    assert projection.total_usage == 301
    assert projection.intervals[0].estimated_per_day == 150.5


def test_bounded_explicit_request_does_not_silently_truncate(monkeypatch):
    events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1301))
    monkeypatch.setattr("services.web_evidence_report.MAX_REPORT_EVENTS", 1)
    with pytest.raises(ValueError, match="ช่วงวันที่สั้นลง"):
        load_evidence(database.get_db_path(), **request(), cancelled=Event())


def test_exports_preserve_decimal_estimates_remarks_and_escape_labels(tmp_path):
    result = project(events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1301)))
    xlsx = tmp_path / "evidence.xlsx"
    export_evidence_xlsx(xlsx, result, printer="=1+1", serial="SER-A", counter_label="@UNTRUSTED")
    workbook = load_workbook(xlsx)
    assert workbook["ขอบเขตข้อมูล"]["B1"].data_type == "s"
    assert workbook["ขอบเขตข้อมูล"]["B1"].value == "'=1+1"
    graph = workbook["กราฟรายวัน"]
    assert graph["D2"].value == graph["D3"].value == 150.5
    assert graph["E2"].value == "ประมาณการ"
    assert "ไม่ใช่ยอดที่ยืนยัน" in workbook["ยอดตามช่วง"]["G2"].value
    workbook.close()
    pdf = tmp_path / "evidence.pdf"
    projection_pdf(pdf, result, title="Fixture <script> · รายงานหลักฐาน")
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert pdf.stat().st_size > 2000


def test_dialog_loads_only_on_click_and_resets_exports_after_date_change():
    events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1301))
    dialog = WebEvidenceDialog(DeviceConfigRepository().list(enabled_only=False), today=date(2026, 9, 21), calendar_timezone=BANGKOK)
    assert dialog.future is None and dialog.evidence is None
    assert not dialog.xlsx_button.isEnabled()
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert dialog.projection is not None
    assert dialog.xlsx_button.isEnabled() and dialog.pdf_button.isEnabled()
    assert dialog.table.rowCount() == 1
    assert len(dialog.cumulative.chart().series()) == 2
    dialog.start_date.setDate(dialog.start_date.date().addDays(1))
    assert dialog.projection is None
    assert not dialog.xlsx_button.isEnabled()
    dialog.pool.shutdown(wait=True)


def test_missing_history_shows_unavailable_instead_of_zero_result():
    events_for(("2026-08-01T17:00", 1000))
    dialog = WebEvidenceDialog(DeviceConfigRepository().list(enabled_only=False), today=date(2026, 9, 21), calendar_timezone=BANGKOK)
    dialog.load()
    dialog.future.result(timeout=10)
    dialog.collect()
    assert dialog.projection is None
    assert "ไม่มีผล Web" in dialog.status.text()
    assert not dialog.xlsx_button.isEnabled()
    dialog.pool.shutdown(wait=True)
