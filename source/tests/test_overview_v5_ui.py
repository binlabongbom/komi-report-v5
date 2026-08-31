import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QBoxLayout, QLabel, QWidget

import pages
from pages import PageOverview


def _summary(
    *,
    source: str = "billing_ledger",
    held: int = 0,
    incomplete: int = 0,
    provisional: int = 0,
) -> dict:
    return {
        "all_monthly": {
            "2026-07": {
                "total": 30,
                "cost": 98.0,
                "display_total": 30 + provisional,
                "display_cost": 98.0 + provisional * 2,
            }
        },
        "filtered_months": [],
        "current_billing_month": "2026-07",
        "metrics": {
            "total": 30,
            "total_color": 10,
            "total_bw": 20,
            "cost": 98.0,
            "provisional_total": provisional,
            "provisional_color": provisional,
            "provisional_bw": 0,
            "provisional_cost": provisional * 2,
            "display_total": 30 + provisional,
            "display_color": 10 + provisional,
            "display_bw": 20,
            "display_cost": 98.0 + provisional * 2,
            "machines": [30],
        },
        "machine_names": ["QA Printer"],
        "machine_values": [30],
        "type_values": [5, 10, 5, 10, 0, 0],
        "top_users": [],
        "devices": [
            {
                "slot": 0,
                "name": "QA Printer",
                "model": "KM bizhub C450i",
                "status": "online",
                "last_success_at": "2026-07-27T16:00:00+07:00",
                "confirmed_total": 30,
                "provisional_total": provisional,
                "display_total": 30 + provisional,
                "display_cost": 98.0 + provisional * 2,
                "provisional_cost_available": True,
                "held_days": held,
            }
        ],
        "source": source,
        "quality": {
            "held_days": held,
            "incomplete_days": incomplete,
            "provisional_days": int(provisional > 0),
            "provisional_cost_available": True,
            "last_sync_at": "2026-07-27T16:00:00+07:00",
            "status_counts": {"online": 1},
        },
    }


def test_overview_does_not_render_billing_quality_banner(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        pages,
        "build_overview_summary",
        lambda _filter: _summary(held=2, incomplete=1),
    )
    page = PageOverview(lambda: [None, None, None])
    page.show()
    app.processEvents()
    page.refresh()

    assert not hasattr(page, "overview_quality")
    assert "Online 1/1 เครื่อง" in page.overview_status.text()
    page.close()
    app.processEvents()


def test_overview_reflows_bottom_cards_at_desktop_minimum_width(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(pages, "build_overview_summary", lambda _filter: _summary())
    page = PageOverview(lambda: [None, None, None])
    page.resize(794, 1400)
    page.show()
    app.processEvents()

    assert page.width() == 794
    assert page.minimumSizeHint().width() <= 794
    assert page._overview_bottom_row.direction() == QBoxLayout.Direction.TopToBottom
    assert page._summary_grid.itemAtPosition(0, 0).widget() is page.card_color_print
    assert page._summary_grid.itemAtPosition(0, 1).widget() is page.card_bw_print
    assert page._summary_grid.itemAtPosition(1, 0).widget() is page.card_total_usage
    assert page._summary_grid.itemAtPosition(1, 1).widget() is page.card_color_copy
    assert page._summary_grid.itemAtPosition(2, 0).widget() is page.card_bw_copy
    assert page._summary_grid.itemAtPosition(2, 1).widget() is page.card_total_cost
    for card in page.stat_cards:
        assert card.lbl_title.width() + 4 >= card.lbl_title.sizeHint().width()
        assert card.lbl_diff.width() + 4 >= card.lbl_diff.sizeHint().width()

    page.resize(1210, 1400)
    app.processEvents()
    assert page._overview_bottom_row.direction() == QBoxLayout.Direction.LeftToRight
    assert page._summary_grid.itemAtPosition(0, 0).widget() is page.card_color_print
    assert page._summary_grid.itemAtPosition(0, 1).widget() is page.card_bw_print
    assert page._summary_grid.itemAtPosition(0, 2).widget() is page.card_total_usage
    assert page._summary_grid.itemAtPosition(1, 0).widget() is page.card_color_copy
    assert page._summary_grid.itemAtPosition(1, 1).widget() is page.card_bw_copy
    assert page._summary_grid.itemAtPosition(1, 2).widget() is page.card_total_cost
    page.close()
    app.processEvents()


def test_overview_metric_cards_are_compact_and_style_a3_a4_details(monkeypatch):
    app = QApplication.instance() or QApplication([])
    summary = _summary()
    summary["metrics"].update(
        {
            "print_available": True,
            "display_print_color": 48,
            "display_print_a3_color": 1,
            "display_print_a4_color": 47,
        }
    )
    monkeypatch.setattr(pages, "build_overview_summary", lambda _filter: summary)
    page = PageOverview(lambda: [None, None, None])
    page.resize(1210, 1400)
    page.show()
    app.processEvents()
    page.refresh()

    card = page.card_color_print
    margins = card.layout().contentsMargins()
    assert card.height() == 56
    # The compact 14 px horizontal inset keeps long metric values visible at
    # the supported 1024 px minimum window width.
    assert margins.left() == 14
    assert margins.top() == 5
    assert margins.right() == 14
    assert margins.bottom() == 5
    assert card.findChild(QLabel, "overview_metric_title") is card.lbl_title
    assert card.findChild(QLabel, "overview_metric_detail") is card.lbl_diff
    assert card.lbl_title.parentWidget().objectName() == "overview_metric_content"
    assert card.lbl_val.font().pointSize() == pages.F_2XL
    assert card.lbl_val.alignment() & Qt.AlignmentFlag.AlignVCenter
    card_image = card.grab().toImage()
    assert card_image.pixelColor(card.width() // 2, card.height() // 2).name().lower() == pages.C_CARD.lower()
    assert card.lbl_diff.textFormat() == Qt.TextFormat.RichText
    assert "color:#64748B'>A3" in card.lbl_diff.text()
    assert "color:#111827'>1" in card.lbl_diff.text()
    assert "color:#64748B'>A4" in card.lbl_diff.text()
    assert "color:#111827'>47" in card.lbl_diff.text()
    page.close()
    app.processEvents()


def test_overview_marks_current_cache_as_provisional_and_exposes_actions(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        pages,
        "build_overview_summary",
        lambda _filter: _summary(provisional=12),
    )
    page = PageOverview(lambda: [None, None, None])
    page.show()
    app.processEvents()
    page.refresh()

    assert not hasattr(page, "overview_quality")
    assert page.stat_cards[0].lbl_val.text() == "42"
    assert "วันนี้ +12" in page.stat_cards[0].lbl_diff.text()
    assert page.printer_list_layout.count() == 1

    emitted = {"reports": 0, "log": 0, "sync": 0}
    page.reports_requested.connect(
        lambda: emitted.__setitem__("reports", emitted["reports"] + 1)
    )
    page.sync_log_requested.connect(
        lambda: emitted.__setitem__("log", emitted["log"] + 1)
    )
    page.sync_requested.connect(
        lambda: emitted.__setitem__("sync", emitted["sync"] + 1)
    )
    page.btn_open_reports.click()
    page.btn_open_sync_log.click()
    page.btn_sync_now.click()
    assert page.btn_sync_now.isVisibleTo(page)
    assert page.btn_open_sync_log.isVisibleTo(page)
    assert emitted == {"reports": 1, "log": 1, "sync": 1}
    assert not page.btn_sync_now.isEnabled()
    page.close()
    app.processEvents()


def test_overview_printer_rows_keep_status_and_all_toner_colours_visible(monkeypatch):
    app = QApplication.instance() or QApplication([])
    summary = _summary()
    device = summary["devices"][0]
    device.update(
        {
            "name": "KM bizhub C450i พร้อมชื่อที่ยาวขึ้น",
            "serial": "AA7R041002004",
            "host": "10.244.116.6",
            "status": "pending",
            "toner": {"C": 31, "Y": 67, "M": 41, "K": 59},
        }
    )
    monkeypatch.setattr(pages, "build_overview_summary", lambda _filter: summary)
    page = PageOverview(lambda: [None, None, None])
    page.resize(794, 1400)
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()

    row = page.printer_list_layout.itemAt(0).widget()
    bars = row.findChildren(pages._OverviewTonerBar)
    labels = [label.text() for label in row.findChildren(QLabel)]
    toner_group = row.findChild(QWidget, "overview_toner_group")

    assert [bar.property("tonerKey") for bar in bars] == ["C", "Y", "M", "K"]
    assert all(bar.width() >= 46 for bar in bars)
    assert toner_group is not None
    toner_point = toner_group.mapTo(row, QPoint(toner_group.width() - 5, 3))
    row_image = row.grab().toImage()
    assert row_image.pixelColor(toner_point).name().lower() == pages.C_CARD.lower()
    assert "● รอตรวจสอบ" in labels
    assert "ยังไม่มีการอ่านข้อมูลที่สำเร็จ" in labels
    assert "รอตรวจสอบ" in row.accessibleDescription()
    page.close()
    app.processEvents()
