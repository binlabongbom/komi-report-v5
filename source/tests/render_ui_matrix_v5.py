"""Render the V5 desktop UI matrix with synthetic local-only data.

This is an evidence helper, not a production launcher.  It blocks socket
connections, switches database.py to a temporary SQLite file, and replaces
report loaders with deterministic frozen-ledger fixtures.
"""

from __future__ import annotations

import json
import os
import re
import socket
import tempfile
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: I001
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTabWidget,
    QSpinBox,
    QWidget,
)

import database
from ui.pages import overview as overview_page
from ui.pages import devices as devices_page
from ui.settings import fleet as fleet_settings
from ui.reports import page as report_page
from app import MainWindow
from database import _open
from i18n import apply_language
from services.billing_ledger import post_daily_record, replace_entry
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.monthly_history import MonthlyUsage
from services.pricing import PriceList, PricingRepository
from services.runtime_snapshots import runtime_snapshots
from services import web_service
from qt_render_environment import configure_offscreen_fonts


VIEWPORTS = tuple(
    tuple(int(part) for part in value.lower().split("x", 1))
    for value in os.environ.get(
        "KOMI_UI_QA_VIEWPORTS", "1024x768,1280x800,1440x900"
    ).split(",")
    if value.strip()
)
DEVICE_COUNTS = tuple(
    int(value)
    for value in os.environ.get("KOMI_UI_QA_DEVICE_COUNTS", "1,2,3").split(",")
    if value.strip()
)
PAGE_NAMES = ("Overview", "Import", "Reports", "Settings")
OUTPUT_DIR = Path(
    os.environ.get(
        "KOMI_UI_QA_OUTPUT_DIR",
        Path(__file__).resolve().parents[2] / "docs" / "qa",
    )
)
QA_LANGUAGE = "en" if os.environ.get("KOMI_UI_QA_LANGUAGE", "th").lower().startswith("en") else "th"
THAI_LETTERS = re.compile(r"[ก-ฮะ-ูเ-์]")


def _overview_summary(device_count: int) -> dict:
    machines = [1_000] * device_count
    devices = [
        {
            "slot": index,
            "name": f"QA Printer {index + 1}",
            "host": f"192.0.2.{10 + index}",
            "serial": f"QA-SERIAL-{index + 1}",
            "status": "online",
            "toner": {"C": 81, "Y": 74, "M": 68, "K": 90},
        }
        for index in range(device_count)
    ]
    return {
        "all_monthly": {
            "2026-07": {
                "machines": machines,
                "provisional_machines": [0] * device_count,
            }
        },
        "filtered_months": ["2026-07"],
        "current_billing_month": "2026-07",
        "metrics": {
            "total": 3_000,
            "display_total": 3_000,
            "total_color": 1_200,
            "total_bw": 1_800,
            "cost": 289.50,
            "display_cost": 289.50,
            "provisional_total": 0,
            "print_available": True,
            "copy_available": True,
            "display_print_color": 750,
            "display_print_a3_color": 150,
            "display_print_a4_color": 600,
            "display_print_bw": 1_050,
            "display_print_a3_bw": 200,
            "display_print_a4_bw": 850,
            "display_copy_color": 450,
            "display_copy_a3_color": 90,
            "display_copy_a4_color": 360,
            "display_copy_bw": 750,
            "display_copy_a3_bw": 150,
            "display_copy_a4_bw": 600,
            "machines": machines,
        },
        "machine_names": [f"QA Printer {index + 1}" for index in range(device_count)],
        "machine_values": machines,
        "type_values": [300, 300, 600, 600, 0, 0],
        "top_users": [],
        "source": "billing_ledger",
        "quality": {
            "held_days": 2,
            "incomplete_days": 1,
            "status_counts": {"online": device_count},
            "last_sync_at": "2026-08-20T15:30:00+07:00",
            "provisional_cost_available": True,
        },
        "devices": devices,
    }


def _usage_records(slots: list[int]) -> tuple[MonthlyUsage, ...]:
    period_start, period_end = report_page.history_period_range(
        date.today(),
        1,
        "monthly",
    )
    return tuple(
        MonthlyUsage(
            device_slot=slot,
            period_start=period_start,
            period_end=period_end,
            total=1_000,
            a3_color=100,
            a3_bw=200,
            a4_color=300,
            a4_bw=400,
            scan=50,
            gross_cost=100,
            net_cost=96.50,
            day_count=1,
            incomplete_days=1 if slot == 1 else 0,
            held_days=2 if slot == 0 else 0,
            device_identity=f"serial:QA-SERIAL-{slot + 1}",
            device_name_snapshot=f"QA Printer {slot + 1}",
            device_serial_snapshot=f"QA-SERIAL-{slot + 1}",
            print_color=300,
            print_bw=300,
            copy_color=200,
            copy_bw=200,
            provisional_total=50 if slot == 0 else 0,
            provisional_print_color=20 if slot == 0 else 0,
            provisional_print_bw=15 if slot == 0 else 0,
            provisional_copy_color=10 if slot == 0 else 0,
            provisional_copy_bw=5 if slot == 0 else 0,
            provisional_days=1 if slot == 0 else 0,
        )
        for slot in slots
    )


def _seed_billing_audit() -> None:
    """Create one correction chain and one Hold in the active temp database."""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    PricingRepository().set_prices(
        0,
        date(2026, 7, 1),
        PriceList(a4_color=1.0),
    )

    def daily_record(record_date: str, source: dict) -> int:
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

    posting_id = post_daily_record(
        daily_record("2026-07-16", {"reconciliation": {"billing_safe": True}})
    )
    replace_entry(
        posting_id,
        gross_cents=250,
        net_cents=245,
        reason="QA approved meter correction",
    )
    post_daily_record(daily_record("2026-07-17", {}))


def _visible_clips(window: MainWindow, *, root: QWidget | None = None) -> list[str]:
    clips: list[str] = []
    scope = root or window
    for widget in scope.findChildren((QLabel, QPushButton)):
        if not widget.isVisibleTo(window) or not widget.text().strip():
            continue
        if isinstance(widget, QLabel) and widget.wordWrap():
            continue
        # Manual step badges are fixed 30 px circles; their glyph fits, while
        # Qt's stylesheet sizeHint includes surrounding label padding.
        if isinstance(widget, QLabel) and widget.text().isdigit() and widget.width() == 30:
            continue
        if widget.sizeHint().width() > widget.width() + 4:
            clips.append(
                f"{widget.text().replace(chr(10), ' / ')[:80]} "
                f"(width={widget.width()}, hint={widget.sizeHint().width()})"
            )
    return clips


def _visible_thai(root: QWidget, window: MainWindow) -> list[str]:
    """Return untranslated Thai UI copy; business data and the baht sign are allowed."""
    found: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisibleTo(window):
            continue
        if isinstance(widget, (QLabel, QAbstractButton)) and THAI_LETTERS.search(widget.text()):
            found.append(widget.text().replace("\n", " / "))
        if isinstance(widget, QTabWidget):
            found.extend(
                widget.tabText(index)
                for index in range(widget.count())
                if THAI_LETTERS.search(widget.tabText(index))
            )
        if isinstance(widget, QComboBox):
            found.extend(
                widget.itemText(index)
                for index in range(widget.count())
                if THAI_LETTERS.search(widget.itemText(index))
            )
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)) and THAI_LETTERS.search(widget.suffix()):
            found.append(widget.suffix())
        if isinstance(widget, (QLineEdit, QPlainTextEdit)) and THAI_LETTERS.search(widget.placeholderText()):
            found.append(widget.placeholderText())
        if isinstance(widget, QTableWidget):
            for column in range(widget.columnCount()):
                header = widget.horizontalHeaderItem(column)
                if header is not None and THAI_LETTERS.search(header.text()):
                    found.append(header.text())
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    item = widget.item(row, column)
                    if item is not None and THAI_LETTERS.search(item.text()):
                        found.append(item.text())
    return list(dict.fromkeys(found))


def _visible_thai_metadata(root: QWidget, window: MainWindow) -> list[str]:
    """Audit nonvisual accessibility copy as part of the English matrix."""
    found: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisibleTo(window):
            continue
        for value in (
            widget.accessibleName(),
            widget.accessibleDescription(),
            widget.toolTip(),
        ):
            if value and THAI_LETTERS.search(value):
                found.append(value.replace("\n", " / "))
    return list(dict.fromkeys(found))


def _visible_in_scroll(scroll: QScrollArea, widget) -> bool:
    top_left = widget.mapTo(scroll.viewport(), QPoint(0, 0))
    return scroll.viewport().rect().intersects(QRect(top_left, widget.size()))


def _contact_sheet(images: list[tuple[str, QImage]], title: str, target: Path) -> None:
    sheet = QImage(1600, 940, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("white"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    title_font = QFont("Helvetica Neue", 18)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor("#123262"))
    painter.drawText(QRect(24, 10, 1552, 34), Qt.AlignmentFlag.AlignLeft, title)
    label_font = QFont("Helvetica Neue", 12)
    label_font.setBold(True)
    painter.setFont(label_font)
    for index, (label, source) in enumerate(images):
        column = index % 3
        row = index // 3
        panel = QRect(20 + column * 526, 54 + row * 438, 506, 418)
        painter.setPen(QColor("#D6E0EA"))
        painter.drawRect(panel)
        painter.setPen(QColor("#123262"))
        painter.drawText(
            QRect(panel.left() + 10, panel.top() + 6, panel.width() - 20, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        image_rect = QRect(panel.left() + 8, panel.top() + 34, panel.width() - 16, panel.height() - 42)
        scaled = source.scaled(
            image_rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        point = QPoint(
            image_rect.left() + (image_rect.width() - scaled.width()) // 2,
            image_rect.top() + (image_rect.height() - scaled.height()) // 2,
        )
        painter.drawImage(point, scaled)
    painter.end()
    if not sheet.save(str(target), "PNG"):
        raise RuntimeError(f"could not save {target}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    configure_offscreen_fonts(app)
    original_db = database.get_db_path()
    network_attempts: list[str] = []
    current_count = {"value": 1}

    def block_connect(_socket, address) -> None:
        network_attempts.append(repr(address))
        raise RuntimeError("network is blocked by UI QA")

    socket.socket.connect = block_connect
    # Status labels must remain deterministic and offline in visual QA.
    web_service._port_open = lambda _port: False
    web_service._lan_ip = lambda: "127.0.0.1"
    overview_page.build_overview_summary = lambda _filter: _overview_summary(current_count["value"])
    devices_page.latest_counters = lambda slot: {
        "counter.total.total": 10_000 + slot,
        "counter.print.full_color_total": 1_000,
        "counter.print.black_total": 4_000,
    }
    report_page.load_usage_history = lambda slots, **_kwargs: _usage_records(slots)
    report_page.load_monthly_usage = lambda slots, **_kwargs: _usage_records(slots)
    report_page.load_subject_history = lambda slots, **_kwargs: ()

    temp_root = Path(tempfile.mkdtemp(prefix="komi-ui-matrix-"))
    fleet_settings.configure_autostart = (
        lambda _enabled, *, apply=True: temp_root / "synthetic-autostart-registration"
    )
    results: list[tuple[int, str, str]] = []
    try:
        for device_count in DEVICE_COUNTS:
            current_count["value"] = device_count
            db_path = temp_root / f"devices-{device_count}.sqlite3"
            database.set_db_path(db_path)
            database.init_db()
            database.set_cfg("ui_language", QA_LANGUAGE)
            database.set_cfg("db_path", str(db_path))
            database.set_cfg("billing_day", "1")
            database.set_cfg("waste_paper_pct", "47")
            DeviceConfigRepository().replace_all(
                [
                    DeviceConfig(
                        slot=index,
                        name=f"QA Printer {index + 1}",
                        host=f"192.0.2.{10 + index}",
                        model="bizhub C450i",
                        serial=f"QA-SERIAL-{index + 1}",
                        connection_status="online",
                        last_total=10_000 + index,
                    )
                    for index in range(device_count)
                ]
            )
            _seed_billing_audit()
            runtime_snapshots.clear()
            window = MainWindow()
            window._quitting = True
            for width, height in VIEWPORTS:
                window.resize(width, height)
                window.show()
                app.processEvents()
                app.processEvents()
                captures: list[tuple[str, QImage]] = []
                for page_index, page_name in enumerate(PAGE_NAMES):
                    window._nav(window.nav_btns[page_index])
                    app.processEvents()
                    app.processEvents()
                    wrapper = window.stack.currentWidget()
                    if isinstance(wrapper, QScrollArea):
                        assert wrapper.horizontalScrollBar().maximum() == 0, (
                            f"horizontal overflow: {page_name} · {device_count} device(s) · "
                            f"{width}x{height} · max={wrapper.horizontalScrollBar().maximum()}"
                        )
                    assert not _visible_clips(window), _visible_clips(window)
                    if QA_LANGUAGE == "en":
                        assert not _visible_thai(window._page_widgets[page_index], window), (
                            page_name,
                            _visible_thai(window._page_widgets[page_index], window),
                        )
                        assert not _visible_thai_metadata(window._page_widgets[page_index], window), (
                            page_name,
                            _visible_thai_metadata(window._page_widgets[page_index], window),
                        )
                    if page_name == "Import":
                        cards = window.pg_import._device_cards
                        assert not any(
                            cards[first].geometry().intersects(cards[second].geometry())
                            for first in range(len(cards))
                            for second in range(first + 1, len(cards))
                        )
                    elif page_name == "Reports":
                        if QA_LANGUAGE == "th":
                            assert (
                                "มีข้อมูลรอตรวจสอบ"
                                in window.pg_history.report_overview_warning.text()
                            )
                            assert (
                                "Hold 2 device-day"
                                in window.pg_history._report_overview_review_detail
                            )
                            assert "47" not in window.pg_history.report_period_note.text()
                            assert window.pg_history.report_period_note.isHidden()
                        if device_count == 3 and width in (1024, 1440):
                            for tab_index, slug in enumerate(
                                ("overview", "users", "printers", "usage", "legacy")
                            ):
                                window.pg_history.report_center_tabs.setCurrentIndex(tab_index)
                                app.processEvents()
                                if QA_LANGUAGE == "en":
                                    assert not _visible_thai(
                                        window.pg_history.report_center, window
                                    ), (slug, _visible_thai(window.pg_history.report_center, window))
                                    assert not _visible_thai_metadata(
                                        window.pg_history.report_center, window
                                    ), (
                                        slug,
                                        _visible_thai_metadata(window.pg_history.report_center, window),
                                    )
                                window.grab().save(
                                    str(OUTPUT_DIR / f"v5-{width}-3dev-reports-{slug}.png"),
                                    "PNG",
                                )
                            window.pg_history.report_center_tabs.setCurrentIndex(0)
                            app.processEvents()
                    elif page_name == "Settings":
                        assert window.pg_settings.fleet.horizontalScrollBar().maximum() == 0
                        assert str(db_path) in window.pg_settings.fleet_content.active_database_path.text()
                    capture = window.grab().toImage()
                    captures.append((page_name, capture))
                    if device_count == 3 and (width, height) == (1024, 768):
                        capture.save(
                            str(OUTPUT_DIR / f"v5-1024-3dev-{page_name.lower().replace(' ', '-')}.png"),
                            "PNG",
                        )
                        if page_name == "Settings":
                            settings_scroll = window.pg_settings.fleet
                            settings_bar = settings_scroll.verticalScrollBar()
                            settings_content = window.pg_settings.fleet_content
                            for task_key in ("billing", "schedule", "support"):
                                window.pg_settings._select_section(
                                    {"billing": 0, "schedule": 1, "support": 3}[task_key]
                                )
                                settings_scroll = {
                                    "billing": window.pg_settings.fleet,
                                    "schedule": window.pg_settings.schedule_page,
                                    "support": window.pg_settings.advanced_page,
                                }[task_key]
                                assert settings_content._set_active_editor(task_key)
                                settings_scroll.ensureWidgetVisible(
                                    settings_content._task_editors[task_key],
                                    12,
                                    12,
                                )
                                app.processEvents()
                                assert settings_content._active_editor == task_key
                                visibility = {
                                    key: editor.isVisibleTo(window)
                                    for key, editor in settings_content._task_editors.items()
                                }
                                assert all(
                                    editor.isVisibleTo(window) == (key == task_key)
                                    for key, editor in settings_content._task_editors.items()
                                ), (task_key, visibility)
                                assert settings_scroll.horizontalScrollBar().maximum() == 0, (
                                    task_key,
                                    settings_scroll.horizontalScrollBar().maximum(),
                                    settings_content.sizeHint().width(),
                                    settings_scroll.viewport().width(),
                                )
                                assert not _visible_clips(
                                    window,
                                    root=settings_content,
                                ), _visible_clips(window, root=settings_content)
                                if QA_LANGUAGE == "en":
                                    assert not _visible_thai(settings_content, window), (
                                        f"Settings {task_key} editor",
                                        _visible_thai(settings_content, window),
                                    )
                                    assert not _visible_thai_metadata(settings_content, window), (
                                        f"Settings {task_key} metadata",
                                        _visible_thai_metadata(settings_content, window),
                                    )
                                window.grab().save(
                                    str(
                                        OUTPUT_DIR
                                        / f"v5-1024-3dev-settings-{task_key}.png"
                                    ),
                                    "PNG",
                                )
                                if task_key == "schedule":
                                    settings_content.advanced_schedule_button.setChecked(True)
                                    settings_scroll.ensureWidgetVisible(
                                        settings_content.schedule_editor,
                                        12,
                                        12,
                                    )
                                    app.processEvents()
                                    assert settings_scroll.horizontalScrollBar().maximum() == 0
                                    assert not _visible_clips(
                                        window,
                                        root=settings_content,
                                    ), _visible_clips(window, root=settings_content)
                                    if QA_LANGUAGE == "en":
                                        assert not _visible_thai(settings_content, window), (
                                            "Settings advanced schedule",
                                            _visible_thai(settings_content, window),
                                        )
                                    window.grab().save(
                                        str(
                                            OUTPUT_DIR
                                            / "v5-1024-3dev-settings-schedule-advanced.png"
                                        ),
                                        "PNG",
                                    )
                                    settings_content.advanced_schedule_button.setChecked(False)
                                if task_key == "support":
                                    assert settings_content._set_active_editor("web")
                                    settings_scroll.ensureWidgetVisible(
                                        settings_content.web_task_editor,
                                        12,
                                        12,
                                    )
                                    app.processEvents()
                                    assert settings_content.support_task_editor.isVisibleTo(window)
                                    assert settings_content.web_task_editor.isVisibleTo(window)
                                    assert not settings_content.billing_editor.isVisibleTo(window)
                                    assert not settings_content.schedule_editor.isVisibleTo(window)
                                    assert settings_scroll.horizontalScrollBar().maximum() == 0
                                    assert not _visible_clips(
                                        window,
                                        root=settings_content,
                                    ), _visible_clips(window, root=settings_content)
                                    window.grab().save(
                                        str(
                                            OUTPUT_DIR
                                            / "v5-1024-3dev-settings-advanced-lan.png"
                                        ),
                                        "PNG",
                                    )
                                    assert settings_content._set_active_editor("support")
                                    app.processEvents()
                            window.pg_settings.show_main()
                            settings_scroll = window.pg_settings.fleet
                            settings_bar = settings_scroll.verticalScrollBar()
                            settings_bar.setValue(0)
                            app.processEvents()
                            assert settings_content.billing_editor.isVisibleTo(window)
                            assert window.pg_settings.section_tabs.currentIndex() == 0
                            window.grab().save(
                                str(OUTPUT_DIR / "v5-1024-3dev-settings-bottom.png"),
                                "PNG",
                            )
                            settings_bar.setValue(0)
                            app.processEvents()
                            window.pg_settings.setCurrentWidget(window.pg_settings.audit)
                            window.pg_settings.audit.refresh()
                            apply_language(window.pg_settings._audit_host)
                            app.processEvents()
                            if QA_LANGUAGE == "en":
                                assert not _visible_thai(window.pg_settings._audit_host, window), (
                                    "Settings billing audit",
                                    _visible_thai(window.pg_settings._audit_host, window),
                                )
                                assert not _visible_thai_metadata(
                                    window.pg_settings._audit_host, window
                                )
                            window.grab().save(
                                str(OUTPUT_DIR / "v5-1024-3dev-billing-audit.png"),
                                "PNG",
                            )
                            window.pg_settings.show_activity()
                            app.processEvents()
                            if QA_LANGUAGE == "en":
                                assert not _visible_thai(window.pg_settings._activity_host, window), (
                                    "Settings reading status",
                                    _visible_thai(window.pg_settings._activity_host, window),
                                )
                                assert not _visible_thai_metadata(
                                    window.pg_settings._activity_host, window
                                )
                            window.grab().save(
                                str(OUTPUT_DIR / "v5-1024-3dev-reading-status.png"),
                                "PNG",
                            )
                            window.pg_settings.show_advanced()
                            app.processEvents()
                            if QA_LANGUAGE == "en":
                                assert not _visible_thai(window.pg_settings._legacy_host, window), (
                                    "Settings advanced tools",
                                    _visible_thai(window.pg_settings._legacy_host, window),
                                )
                                assert not _visible_thai_metadata(
                                    window.pg_settings._legacy_host, window
                                )
                            window.grab().save(
                                str(OUTPUT_DIR / "v5-1024-3dev-settings-tools.png"),
                                "PNG",
                            )
                            window.pg_settings.setCurrentWidget(window.pg_settings.fleet)
                            app.processEvents()

                expected_columns = window.pg_import._responsive_columns(
                    max(0, window.pg_import.width() - 44), device_count
                )
                assert window.pg_import._grid_columns == expected_columns
                _contact_sheet(
                    captures,
                    f"KOMI Report V5 UI QA · {device_count} device(s) · {width}×{height} · synthetic temp DB",
                    OUTPUT_DIR / f"v5-matrix-{device_count}dev-{width}x{height}.png",
                )
                results.append((device_count, f"{width}x{height}", "PASS"))

            window._nav(window.nav_btns[3])
            legacy = window.pg_settings.legacy_content
            window.pg_settings.show_advanced()
            app.processEvents()
            assert all(card.isHidden() for card in legacy._v5_duplicate_cards)
            window.resize(1024, 768)
            app.processEvents()
            window.grab().save(str(OUTPUT_DIR / "v5-1024-3dev-settings-tools-unlocked.png"), "PNG")
            window.polling.stop()
            window.close()
            app.processEvents()
    finally:
        database.set_db_path(original_db)

    if network_attempts:
        raise AssertionError(f"unexpected network attempts: {network_attempts}")
    print(f"rendered {len(results)} viewport/device matrices; network attempts: 0")
    for device_count, viewport, status in results:
        print(f"{device_count} device(s) · {viewport}: {status}")


if __name__ == "__main__":
    main()
