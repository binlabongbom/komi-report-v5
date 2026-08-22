import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QAbstractAnimation
from PyQt6.QtWidgets import QApplication, QHeaderView, QLabel, QPushButton, QWidget

import v5_pages
from i18n import tr
from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue
from services.device_config import DeviceConfig
from services.runtime_snapshots import runtime_snapshots
from v5_pages import PageImportV5, _TonerLevelBar


class _Repository:
    def __init__(self, count: int, statuses: list[str] | None = None) -> None:
        statuses = statuses or ["pending"] * count
        self.devices = [
            DeviceConfig(
                slot=index,
                name=f"Printer {index + 1}",
                host=f"192.0.2.{index + 10}",
                model=f"Model {index + 1}",
                serial=f"SN-{index + 1}",
                last_total=1000 + index,
                connection_status=statuses[index],
                last_error="SNMP timeout" if statuses[index] not in {"online", "pending"} else "",
            )
            for index in range(count)
        ]

    def list(self, *, enabled_only: bool = False):
        return self.devices


class _Cache:
    def load(self, slot, day):
        return {"last_snmp_total": 1000 + slot, "latest": {"counter.total.total": 1000 + slot}}


class _LegacyImport(QWidget):
    def refresh(self):
        return None


@pytest.mark.parametrize("device_count", [1, 2, 3])
def test_import_layout_matches_configured_device_count(monkeypatch, device_count):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda slot: {"counter.total.total": 1000 + slot})

    page = PageImportV5(_LegacyImport(), repository=_Repository(device_count), cache=_Cache())
    page.resize(1300, 1200)
    page.show()
    app.processEvents()

    assert len(page._device_cards) == device_count
    assert page._grid_columns == device_count
    assert page.sync_button.text() == "อ่านข้อมูลตอนนี้"
    assert not hasattr(page, "mock_mode")
    assert not hasattr(page, "legacy_toggle")
    assert page._device_cards[0]._web_table.rowCount() == 1
    assert page._device_cards[0]._subject_table is None
    web_table = page._device_cards[0]._web_table
    assert web_table.verticalHeader().defaultSectionSize() == 34
    assert web_table.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Fixed
    assert web_table.columnWidth(1) == 84
    assert not web_table.alternatingRowColors()
    assert "ยังไม่มีคู่ Counter" in page._device_cards[0]._reconciliation_label.text()
    page.close()
    app.processEvents()


@pytest.mark.parametrize(
    ("page_width", "expected_columns"),
    [
        (794, 2),   # 1024 px window minus the desktop sidebar
        (1050, 3),  # 1280 px window
        (1210, 3),  # 1440 px window
    ],
)
def test_import_three_device_cards_reflow_without_overlap(monkeypatch, page_width, expected_columns):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda slot: {"counter.total.total": 1000 + slot})
    page = PageImportV5(_LegacyImport(), repository=_Repository(3), cache=_Cache())

    page.resize(page_width, 3600)
    page.show()
    app.processEvents()

    assert page._grid_columns == expected_columns
    geometries = [card.geometry() for card in page._device_cards]
    for index, first in enumerate(geometries):
        assert first.left() >= 22
        assert first.right() <= page.width() - 22
        for second in geometries[index + 1:]:
            assert not first.intersects(second)

    page.close()
    app.processEvents()


def test_import_single_device_uses_available_content_width(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda slot: {"counter.total.total": 1000 + slot})
    page = PageImportV5(_LegacyImport(), repository=_Repository(1), cache=_Cache())

    page.resize(1050, 1400)
    page.show()
    app.processEvents()

    assert page._grid_columns == 1
    assert page._device_cards[0].width() >= 990
    page.close()
    app.processEvents()


def test_import_refresh_can_clear_an_empty_device_grid(monkeypatch):
    """A fresh database has no device cards; refreshing it must not dereference None."""
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda _slot: {})
    page = PageImportV5(_LegacyImport(), repository=_Repository(0), cache=_Cache())

    page.refresh()

    assert page.device_grid.count() > 0
    page.close()
    app.processEvents()


def test_import_sync_button_emits_request_and_waits_for_completion(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda _slot: {"counter.total.total": 1000})
    page = PageImportV5(_LegacyImport(), repository=_Repository(1), cache=_Cache())
    requests: list[bool] = []
    page.sync_requested.connect(lambda: requests.append(True))

    page.sync_button.click()

    assert requests == [True]
    assert not page.sync_button.isEnabled()
    assert page.sync_button.text() == tr("กำลัง Sync…", "Syncing…")
    assert page.sync_message.isHidden()
    page.sync_completed()
    assert page.sync_button.isEnabled()
    assert page.sync_button.text() == tr("อ่านข้อมูลตอนนี้", "Read now")
    assert not page.sync_message.isHidden()
    assert page.sync_message.text() == "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้ โปรดตรวจสอบเครือข่าย"
    page.close()
    app.processEvents()


def test_import_sync_status_uses_per_device_dots_and_hides_error_when_all_online(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda slot: {"counter.total.total": 1000 + slot})
    repository = _Repository(2, statuses=["online", "offline"])
    page = PageImportV5(_LegacyImport(), repository=repository, cache=_Cache())

    indicators = [card._connection_indicator for card in page._device_cards]
    assert indicators[0].property("connectionStatus") == "online"
    assert "#00A651" in indicators[0].styleSheet()
    assert indicators[0].width() == 30
    assert indicators[0]._animation.state() == QAbstractAnimation.State.Running
    assert indicators[1].property("connectionStatus") == "offline"
    assert "#D71920" in indicators[1].styleSheet()

    page.sync_completed()
    assert not page.sync_message.isHidden()
    assert "Printer 2: SNMP timeout" in page.sync_message.toolTip()

    repository.devices = [
        DeviceConfig(**{**device.__dict__, "connection_status": "online", "last_error": ""})
        for device in repository.devices
    ]
    page.sync_completed()
    assert page.sync_message.isHidden()
    assert page.sync_message.text() == ""
    page.close()
    app.processEvents()


def test_import_card_uses_clean_labels_and_dynamic_toner_bars(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda _slot: {"counter.total.total": 1000})

    class _TonerCache(_Cache):
        def load(self, slot, day):
            return {
                "last_snmp_total": 1000,
                "snmp_toner": {"C": 31, "Y": 67, "M": 41, "K": 59},
                "snmp_paper": [
                    {"name": "Tray 2", "level": 0, "capacity": 500, "status": 6, "input_index": 2},
                    {"name": "Bypass Tray", "level": -3, "capacity": 100, "status": 4, "input_index": 5},
                    {"name": "Tray 1", "level": 120, "capacity": 500, "status": 4, "input_index": 1},
                ],
            }

    page = PageImportV5(_LegacyImport(), repository=_Repository(1, ["online"]), cache=_TonerCache())
    page.resize(1050, 1200)
    page.show()
    app.processEvents()
    card = page._device_cards[0]
    visible_labels = [label.text() for label in card.findChildren(QLabel) if not label.isHidden()]
    bars = card.findChildren(_TonerLevelBar)
    toner_row = card.findChild(QWidget, "toner_level_row")
    tray_tiles = card.findChildren(QWidget, "paper_tray_tile")

    assert not any(button.text() == "⚙" for button in card.findChildren(QPushButton))
    assert all(source not in " ".join(visible_labels) for source in ("(SNMP)", "(status)", "Billing source", "RAM ·"))
    assert card._zero_checkbox.isHidden()
    assert card._reconciliation_label.isHidden()
    assert [bar.property("tonerPercent") for bar in bars] == [31.0, 67.0, 41.0, 59.0]
    assert all(bar.height() == 20 for bar in bars)
    assert [tile.property("trayName") for tile in tray_tiles] == ["Tray1", "Tray2", "Bypass Tray"]
    assert [tile.property("paperState") for tile in tray_tiles] == ["available", "empty", "available"]
    assert all(tile.height() == 20 for tile in tray_tiles)
    assert "#F59E0B" in tray_tiles[1].styleSheet()
    assert "#E5E7EB" in tray_tiles[0].styleSheet()
    assert "กระดาษหมด" not in visible_labels
    assert "กระดาษหมด" in tray_tiles[1].toolTip()
    assert toner_row is not None
    assert toner_row.grab().toImage().pixelColor(0, 0).name() == "#ffffff"
    page.close()
    app.processEvents()


def test_import_card_paper_rows_follow_fixed_order_and_hide_missing_trays():
    paper = [
        {"name": "Bypass Tray", "level": -3, "capacity": 100, "status": 4, "input_index": 5},
        {"name": "Tray 5", "level": -3, "capacity": 500, "status": 4, "input_index": 5},
        {"name": "Tray 4", "level": 0, "capacity": 500, "status": 6, "input_index": 4},
        {"name": "Tray 3", "level": 120, "capacity": 500, "status": 4, "input_index": 3},
        {"name": "Tray 2", "level": 120, "capacity": 500, "status": 4, "input_index": 2},
        {"name": "Tray 1", "level": 120, "capacity": 500, "status": 4, "input_index": 1},
    ]

    ordered = PageImportV5._ordered_paper_trays(paper)
    rows = PageImportV5._paper_tray_rows(ordered)
    empty = PageImportV5._paper_tile_state(ordered[4][1], ())
    available = PageImportV5._paper_tile_state(ordered[0][1], ())

    assert [label for label, _tray in ordered] == ["Tray1", "Tray3", "Tray5", "Tray2", "Tray4", "Bypass Tray"]
    assert [[label for label, _tray in row] for row in rows] == [
        ["Tray1", "Tray3", "Tray5"],
        ["Tray2", "Tray4"],
        ["Bypass Tray"],
    ]
    assert PageImportV5._paper_tray_columns(ordered) == 3
    assert empty[:2] == ("empty", "#F59E0B")
    assert available[:2] == ("available", "#E5E7EB")


def test_import_card_paper_rows_keep_physical_layout_with_four_or_two_trays_and_bypass():
    four_plus_bypass = PageImportV5._ordered_paper_trays(
        [
            {"name": "Tray 1", "level": 1, "capacity": 500, "status": 4, "input_index": 1},
            {"name": "Tray 2", "level": 1, "capacity": 500, "status": 4, "input_index": 2},
            {"name": "Tray 3", "level": 1, "capacity": 500, "status": 4, "input_index": 3},
            {"name": "Tray 4", "level": 1, "capacity": 500, "status": 4, "input_index": 4},
            {"name": "Bypass Tray", "level": 1, "capacity": 100, "status": 4, "input_index": 5},
        ]
    )
    two_plus_bypass = PageImportV5._ordered_paper_trays(
        [
            {"name": "Tray 1", "level": 1, "capacity": 500, "status": 4, "input_index": 1},
            {"name": "Tray 2", "level": 1, "capacity": 500, "status": 4, "input_index": 2},
            {"name": "Bypass Tray", "level": 1, "capacity": 100, "status": 4, "input_index": 5},
        ]
    )

    assert [[label for label, _tray in row] for row in PageImportV5._paper_tray_rows(four_plus_bypass)] == [
        ["Tray1", "Tray3"],
        ["Tray2", "Tray4"],
        ["Bypass Tray"],
    ]
    assert [[label for label, _tray in row] for row in PageImportV5._paper_tray_rows(two_plus_bypass)] == [
        ["Tray1"],
        ["Tray2"],
        ["Bypass Tray"],
    ]
    assert PageImportV5._paper_tray_columns(four_plus_bypass) == 2
    assert PageImportV5._paper_tray_columns(two_plus_bypass) == 2


def test_import_card_hides_paper_section_when_no_identifiable_tray_is_reported():
    ordered = PageImportV5._ordered_paper_trays(
        [{"name": "Unknown feeder", "level": -2, "capacity": 0, "status": 2}],
    )

    assert ordered == ()


def test_toner_bar_rounded_corners_match_white_device_card():
    from config import build_qss

    app = QApplication.instance() or QApplication([])
    previous_style = app.styleSheet()
    app.setStyleSheet(build_qss())
    bar = _TonerLevelBar("C", 31, "#009DC4")
    bar.resize(120, 38)
    bar.show()
    app.processEvents()

    image = bar.grab().toImage()
    assert image.pixelColor(0, 0).name() == "#ffffff"
    assert image.pixelColor(image.width() - 1, 0).name() == "#ffffff"

    bar.close()
    app.setStyleSheet(previous_style)
    app.processEvents()


def test_import_sync_log_button_opens_observability_page(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda _slot: {"counter.total.total": 1000})
    page = PageImportV5(_LegacyImport(), repository=_Repository(1), cache=_Cache())
    requests: list[bool] = []
    page.sync_log_requested.connect(lambda: requests.append(True))

    page.sync_log_button.click()

    assert requests == [True]
    page.close()
    app.processEvents()


def test_import_can_hide_zero_web_counters_without_removing_data(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(
        v5_pages,
        "latest_counters",
        lambda _slot: {
            "counter.total.total": 1000,
            "counter.copy.bw_total": 0,
            "counter.copy.full_color_total": 5,
        },
    )
    page = PageImportV5(_LegacyImport(), repository=_Repository(1), cache=_Cache())
    card = page._device_cards[0]
    table = card._web_table

    assert table.rowCount() == 3
    assert not any(table.isRowHidden(row) for row in range(table.rowCount()))
    card._zero_checkbox.setChecked(True)
    assert table.isRowHidden(0)
    assert not table.isRowHidden(1)
    assert not table.isRowHidden(2)
    assert table.rowCount() == 3
    page.close()
    app.processEvents()


def test_import_uses_real_subject_name_from_runtime_snapshot(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(v5_pages, "latest_counters", lambda _slot: {"counter.total.total": 2341})
    reading = MeterReading.create(
        "192.0.2.10",
        [
            WebCounterValue("counter.total.total", "Total", 2341, "Total", "MFP.Total"),
            WebCounterValue(
                "counter.user.total.total",
                "Total: Total",
                2,
                "Total",
                "MFP.AuthCounter[1]",
                subject_type="user",
                subject_id="1",
                subject_name="DMS",
            ),
        ],
        "web_connection_admin_read_only",
        WebAuthState.ADMIN,
    )
    runtime_snapshots.update(0, reading)

    page = PageImportV5(_LegacyImport(), repository=_Repository(1), cache=_Cache())
    subject_table = page._device_cards[0]._subject_table

    assert subject_table is not None
    assert subject_table.item(0, 0).text() == "DMS"
    assert subject_table.item(0, 1).text() == "2"
    page.close()
    app.processEvents()


def test_import_shows_needs_review_when_web_totals_do_not_reconcile(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime_snapshots.clear()
    monkeypatch.setattr(
        v5_pages,
        "latest_counters",
        lambda _slot: {
            "counter.total.total": 100,
            "counter.print.total": 80,
            "counter.print.full_color_total": 50,
            "counter.print.bw_total": 20,
            "counter.copy.total": 20,
            "counter.copy.full_color_total": 5,
            "counter.copy.bw_total": 15,
        },
    )

    page = PageImportV5(_LegacyImport(), repository=_Repository(1), cache=_Cache())

    warning = page._device_cards[0]._reconciliation_label
    assert "Needs Review" in warning.text()
    assert "Print Total" in warning.text()
    page.close()
    app.processEvents()
