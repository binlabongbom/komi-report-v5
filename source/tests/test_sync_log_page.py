import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractButton, QApplication, QHeaderView, QLabel, QMessageBox

import v5_pages
from i18n import ENGLISH, THAI, apply_language, set_language
from services.device_config import DeviceConfig
from services.pipeline_log import pipeline_log
from v5_pages import PagePipelineLog


class _Repository:
    def list(self, *, enabled_only: bool = False):
        return [DeviceConfig(0, "DMS Printer", "192.0.2.10")]


class _Cache:
    def load(self, _slot, _day):
        return None


def test_sync_log_opens_with_a_plain_language_status_and_compact_event_history():
    app = QApplication.instance() or QApplication([])
    set_language(THAI)
    pipeline_log.clear()
    pipeline_log.append(
        stage="SNMP",
        action="Toner response",
        device_slot=0,
        device_name="DMS Printer",
        host="192.0.2.10",
        value="C=81%",
        status="ok",
    )
    page = PagePipelineLog(repository=_Repository(), cache=_Cache())

    assert page.tabs.tabText(0) == "สถานะการอ่าน"
    assert page.tabs.tabText(1) == "ประวัติการอ่าน"
    assert page.tabs.tabText(3) == "การทำงานอัตโนมัติ"
    assert page.tabs.count() == 5
    assert page.tabs.widget(4) is page.counter_reviews
    assert page.status_rows.count() == 1
    assert "กำลังเริ่มต้นการอ่าน" in page.status_banner.text()
    status_card = page.status_rows.itemAt(0).widget()
    assert any("รอรอบแรก" in label.text() for label in status_card.findChildren(type(page.status_banner)))
    page.tabs.setCurrentIndex(3)
    page.refresh_timeline()
    assert page.timeline_table.rowCount() >= 6
    assert page.schedule_band_layout.count() >= 5
    timeline_text = "\n".join(
        label.text()
        for segment_index in range(page.schedule_band_layout.count())
        for label in page.schedule_band_layout.itemAt(segment_index).widget().findChildren(type(page.status_banner))
    )
    assert "ช่วงเริ่มงาน" in timeline_text
    assert "ช่วงเลิกงาน" in timeline_text
    assert not page.timeline_table.isVisible()
    assert page.rules_table.rowCount() >= 10
    page.tabs.setCurrentIndex(1)
    page.refresh_live()
    assert page.live_table.rowCount() == 1
    assert page.live_table.item(0, 0).text().count(":") == 2
    assert page.live_table.item(0, 1).text() == "DMS Printer"
    assert page.live_table.item(0, 2).text() == "สำเร็จ"
    assert "C=81%" in page.live_table.item(0, 3).text()
    assert not page.live_table.alternatingRowColors()
    assert page.live_table.verticalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    assert page.live_table.verticalHeader().defaultSectionSize() == 34
    assert page.live_table.item(0, 0).textAlignment() & Qt.AlignmentFlag.AlignLeft
    first_item = page.live_table.item(0, 0)
    page.refresh_live()
    assert page.live_table.item(0, 0) is first_item
    page.close()
    app.processEvents()


def test_sync_log_status_explains_an_offline_printer_without_showing_raw_stage_first():
    app = QApplication.instance() or QApplication([])
    set_language(THAI)
    pipeline_log.clear()

    class OfflineRepository:
        def list(self, *, enabled_only: bool = False):
            return [
                DeviceConfig(
                    0,
                    "Sales Printer",
                    "192.0.2.11",
                    connection_status="offline",
                    last_error="TLS handshake timeout",
                )
            ]

    page = PagePipelineLog(repository=OfflineRepository(), cache=_Cache())

    assert "ต้องตรวจสอบ 1/1 เครื่อง" in page.status_banner.text()
    card = page.status_rows.itemAt(0).widget()
    texts = [label.text() for label in card.findChildren(type(page.status_banner))]
    assert "เชื่อมต่อไม่ได้" in texts
    assert any("เชื่อมต่อเครื่องไม่สำเร็จภายในเวลาที่กำหนด" in text for text in texts)
    page.close()
    app.processEvents()


def test_clearing_live_log_requires_confirmation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    pipeline_log.clear()
    pipeline_log.append(stage="SNMP", action="Probe completed", status="ok")
    page = PagePipelineLog(repository=_Repository(), cache=_Cache())

    monkeypatch.setattr(
        v5_pages.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    page._clear_live()

    assert len(pipeline_log) == 1
    page.close()
    app.processEvents()


def test_reading_status_dynamic_content_is_fully_english():
    app = QApplication.instance() or QApplication([])
    pipeline_log.clear()
    set_language(ENGLISH)
    try:
        page = PagePipelineLog(repository=_Repository(), cache=_Cache())
        page.refresh()
        apply_language(page)
        visible_copy = [
            widget.text()
            for widget in [
                *page.findChildren(QLabel),
                *page.findChildren(QAbstractButton),
            ]
            if widget.text()
        ]
        assert not [
            text for text in visible_copy
            if any("\u0e00" <= character <= "\u0e7f" for character in text)
        ]
        page.close()
        app.processEvents()
    finally:
        set_language(THAI)
