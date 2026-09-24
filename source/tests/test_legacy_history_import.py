from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date

import pytest
from PyQt6.QtWidgets import QApplication

import database
from services.device_config import DeviceConfig
from services.legacy_history_import import (
    LegacyHistoryImportError,
    LegacyUsageSnapshot,
    build_legacy_usage_intervals,
    detect_legacy_history_sources,
    import_legacy_history,
    load_imported_legacy_history,
    preview_legacy_history,
)
from services.monthly_history import MonthlyUsage
from ui.cloud_reports import CloudReportsWidget
from v5_pages import LegacyHistoryImportDialog, SetupWizardV5


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_v46_database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 46")
        connection.execute(
            """CREATE TABLE readings(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   slot INTEGER NOT NULL,
                   machine_name TEXT,
                   serial TEXT,
                   read_date TEXT,
                   read_date_iso TEXT,
                   billing_month TEXT,
                   mode TEXT,
                   data_json TEXT,
                   imported_at TEXT,
                   file_name TEXT,
                   parser_name TEXT
               )"""
        )
        payloads = (
            {
                "date": "2025/01/10",
                "machine_name": "Old DMS",
                "serial": "OLD-001",
                "mode": "summary",
                "summary": {"total_color": 100, "total_bw": 200, "total": 300},
                "paper_color": {"a4_color": 80, "a4_bw": 190, "a3_color": 20, "a3_bw": 10},
                "meters": {"color_meter": 100, "bw_meter": 200},
                "accounts": [{"name": "must-not-import", "password": "secret"}],
                "ip_address": "192.0.2.55",
            },
            {
                "date": "2025/02/10",
                "machine_name": "Old DMS",
                "serial": "OLD-001",
                "mode": "summary",
                "summary": {"total_color": 130, "total_bw": 260, "total": 390},
                "paper_color": {"a4_color": 100, "a4_bw": 240, "a3_color": 30, "a3_bw": 20},
                "meters": {"color_meter": 130, "bw_meter": 260},
            },
        )
        for payload in payloads:
            connection.execute(
                """INSERT INTO readings(
                       slot,machine_name,serial,read_date,read_date_iso,billing_month,
                       mode,data_json,imported_at,file_name,parser_name
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "Old DMS",
                    "OLD-001",
                    payload["date"],
                    payload["date"].replace("/", "-"),
                    payload["date"][:7].replace("/", "-"),
                    "summary",
                    json.dumps(payload),
                    "2025-02-10 10:00:00",
                    "old-report.txt",
                    "V4.6 Summary",
                ),
            )
        connection.execute(
            """INSERT INTO readings(slot,read_date,data_json)
               VALUES(0,'not-a-date','not-json')"""
        )
        connection.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO settings VALUES('password','must-not-import')")


def test_preview_is_read_only_and_reports_only_importable_usage(tmp_path):
    source = tmp_path / "KOMI_Report_V46.db"
    _create_v46_database(source)
    before = _sha256(source)

    preview = preview_legacy_history(source)

    assert preview.source_schema_version == 46
    assert preview.total_rows == 3
    assert preview.valid_rows == 2
    assert preview.new_rows == 2
    assert preview.duplicate_rows == 0
    assert preview.rejected_rows == 1
    assert preview.date_min == "2025-01-10"
    assert preview.date_max == "2025-02-10"
    assert preview.devices[0].machine_name == "Old DMS"
    assert preview.devices[0].reading_count == 2
    assert _sha256(source) == before


def test_preview_hash_and_rows_include_committed_wal_content(tmp_path):
    source = tmp_path / "KOMI_Report_V46_WAL.db"
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("PRAGMA user_version = 46")
        connection.execute(
            """CREATE TABLE readings(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   slot INTEGER NOT NULL,
                   read_date TEXT,
                   data_json TEXT
               )"""
        )
        connection.commit()
        connection.execute(
            "INSERT INTO readings(slot,read_date,data_json) VALUES(?,?,?)",
            (
                0,
                "2025-03-10",
                json.dumps({"summary": {"total": 10}, "date": "2025-03-10"}),
            ),
        )
        connection.commit()

        preview = preview_legacy_history(source)
        assert preview.valid_rows == 1
        assert preview.date_min == "2025-03-10"

        connection.execute(
            "INSERT INTO readings(slot,read_date,data_json) VALUES(?,?,?)",
            (
                0,
                "2025-03-11",
                json.dumps({"summary": {"total": 20}, "date": "2025-03-11"}),
            ),
        )
        connection.commit()
        with pytest.raises(LegacyHistoryImportError, match="เปลี่ยนระหว่างตรวจสอบ"):
            import_legacy_history(preview)
    finally:
        connection.close()


def test_import_backs_up_v5_sanitizes_payload_and_is_idempotent(tmp_path):
    source = tmp_path / "KOMI_Report_V46.db"
    _create_v46_database(source)
    before = _sha256(source)
    preview = preview_legacy_history(source)

    result = import_legacy_history(preview)

    assert result.imported_rows == 2
    assert result.rejected_rows == 1
    assert result.backup_path.is_file()
    assert _sha256(source) == before
    with sqlite3.connect(database.get_db_path()) as connection:
        rows = connection.execute(
            "SELECT data_json,parser_name FROM readings ORDER BY read_date_iso"
        ).fetchall()
        assert len(rows) == 2
        assert all(parser_name == "legacy_v4.6_database" for _, parser_name in rows)
        imported_payload = json.loads(rows[0][0])
        assert imported_payload["summary"]["total"] == 300
        assert "accounts" not in imported_payload
        assert "ip_address" not in imported_payload
        assert connection.execute("SELECT COUNT(*) FROM price_snapshot").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM legacy_history_imports").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM legacy_history_items").fetchone()[0] == 2

    second_preview = preview_legacy_history(source)
    assert second_preview.new_rows == 0
    assert second_preview.duplicate_rows == 2

    snapshots = load_imported_legacy_history()
    assert [row.read_date for row in snapshots] == ["2025-02-10", "2025-01-10"]
    assert snapshots[0].total == 390
    assert snapshots[0].color == 130
    assert snapshots[0].bw == 260


def test_setup_wizard_exposes_history_import_once_on_company_step(tmp_path):
    source = tmp_path / "KOMI_Report_V46.db"
    _create_v46_database(source)
    app = QApplication.instance() or QApplication([])

    wizard = SetupWizardV5(edit_mode=True, legacy_source_paths=[str(source)])
    assert wizard.stack.count() == 4
    assert wizard.stack.currentIndex() == 0
    assert not wizard.legacy_import_button.isHidden()
    assert wizard.legacy_import_button.text() == "Import"
    assert wizard.legacy_import_button.parent() is wizard.database_path_container
    assert wizard.database_path_status.isHidden()
    assert not hasattr(wizard, "legacy_card")

    dialog = LegacyHistoryImportDialog(wizard)
    preview = dialog.load_source(str(source))
    assert preview is not None
    assert dialog.import_button.isEnabled()
    assert "2 รายการ" in dialog.import_button.text()
    assert dialog.device_table.rowCount() == 1
    assert dialog.minimumWidth() <= 720
    assert dialog.minimumHeight() <= 520
    dialog.close()
    wizard.close()
    app.processEvents()


def test_legacy_detection_only_returns_confirmed_v46_database(tmp_path):
    source = tmp_path / "KOMI_Report_V46.db"
    _create_v46_database(source)
    unrelated = tmp_path / "unrelated.db"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE notes(value TEXT)")

    assert detect_legacy_history_sources(
        [source, unrelated], include_known_locations=False
    ) == (source.resolve(),)


def test_cloud_reports_exposes_imported_v46_history_without_cost(tmp_path):
    source = tmp_path / "KOMI_Report_V46.db"
    _create_v46_database(source)
    import_legacy_history(preview_legacy_history(source))
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    widget.set_data(
        records=(),
        daily_records=(),
        subjects=(),
        devices=(),
        legacy_history=load_imported_legacy_history(),
        period=None,
        last_sync_at=None,
    )
    widget.tabs.setCurrentIndex(4)

    assert widget.tabs.indexOf(widget.legacy_history_page) == -1
    assert widget.legacy_history_table.rowCount() == 2
    assert widget.legacy_history_table.item(0, 4).text() == "390"
    assert widget.legacy_history_table.columnCount() == 8
    assert all(
        "Cost" not in widget.legacy_history_table.horizontalHeaderItem(column).text()
        and "ค่าใช้จ่าย" not in widget.legacy_history_table.horizontalHeaderItem(column).text()
        for column in range(widget.legacy_history_table.columnCount())
    )
    widget.tabs.setCurrentIndex(3)
    assert widget.usage_monthly_table.rowCount() == 2
    assert widget.usage_monthly_table.item(1, 0).text().startswith("Meter เริ่มต้น\n")
    headers = [
        widget.usage_monthly_table.horizontalHeaderItem(column).text()
        for column in range(widget.usage_monthly_table.columnCount())
    ]
    assert widget.usage_monthly_table.item(1, headers.index("รวม")).text() == "300"
    assert widget.usage_monthly_table.item(1, headers.index("Scan")).text() == "—"
    assert (
        widget.usage_monthly_table.item(
            1, headers.index("ค่าใช้จ่ายโดยประมาณ")
        ).text()
        == "—"
    )
    assert all(
        widget.usage_monthly_table.item(1, headers.index(label)).text() == "—"
        for label in headers
        if label.startswith(("Print ", "Copy "))
    )
    assert widget.usage_monthly_table.item(0, 0).text() == "02/2025"
    assert widget.usage_monthly_table.item(0, headers.index("รวม")).text() == "90"
    assert widget.usage_monthly_table.item(0, headers.index("Scan")).text() == "0"
    assert (
        widget.usage_monthly_table.item(
            0, headers.index("ค่าใช้จ่ายโดยประมาณ")
        ).text()
        == "—"
    )
    widget.close()
    app.processEvents()


def test_legacy_usage_follows_slot_but_never_calculates_across_replacement():
    snapshots = (
        LegacyUsageSnapshot(
            read_date="2025-01-10",
            billing_month="2025-01",
            slot=0,
            machine_name="Old Accounting",
            serial="OLD-001",
            total=300,
            color=100,
            bw=200,
            a3_color=20,
            a3_bw=10,
            a4_color=80,
            a4_bw=190,
        ),
        LegacyUsageSnapshot(
            read_date="2025-02-10",
            billing_month="2025-02",
            slot=0,
            machine_name="Old Accounting",
            serial="OLD-001",
            total=390,
            color=130,
            bw=260,
            a3_color=30,
            a3_bw=20,
            a4_color=100,
            a4_bw=240,
        ),
        LegacyUsageSnapshot(
            read_date="2025-03-10",
            billing_month="2025-03",
            slot=0,
            machine_name="Replacement Accounting",
            serial="NEW-002",
            total=50,
            color=10,
            bw=40,
            a3_color=0,
            a3_bw=5,
            a4_color=10,
            a4_bw=35,
        ),
        LegacyUsageSnapshot(
            read_date="2025-04-10",
            billing_month="2025-04",
            slot=0,
            machine_name="Replacement Accounting",
            serial="NEW-002",
            total=90,
            color=25,
            bw=65,
            a3_color=5,
            a3_bw=10,
            a4_color=20,
            a4_bw=55,
        ),
    )

    records = build_legacy_usage_intervals(snapshots)

    assert [record.billing_month for record in records] == ["2025-02", "2025-04"]
    assert [record.total for record in records] == [90, 40]
    assert {record.device_identity for record in records} == {"slot:0"}
    assert all(record.cost_available is False for record in records)


def test_usage_timeline_keeps_one_slot_across_v46_and_v5_serials():
    app = QApplication.instance() or QApplication([])
    widget = CloudReportsWidget()
    legacy = (
        LegacyUsageSnapshot(
            read_date="2025-01-10",
            billing_month="2025-01",
            slot=0,
            machine_name="Old Accounting",
            serial="OLD-001",
            total=300,
            color=100,
            bw=200,
            a3_color=20,
            a3_bw=10,
            a4_color=80,
            a4_bw=190,
        ),
    )
    v5 = MonthlyUsage(
        device_slot=0,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        total=40,
        a3_color=5,
        a3_bw=5,
        a4_color=10,
        a4_bw=20,
        scan=0,
        gross_cost=20,
        net_cost=20,
        day_count=1,
        incomplete_days=0,
        device_identity="serial:V5-999",
        device_name_snapshot="New Accounting Printer",
        device_serial_snapshot="V5-999",
    )
    widget.set_data(
        records=(v5,),
        daily_records=(v5,),
        usage_daily_records=(v5,),
        monthly_records=(v5,),
        subjects=(),
        devices=(DeviceConfig(0, "แผนกบัญชี", "192.0.2.10", serial="V5-999"),),
        legacy_history=legacy,
        period=("2026-08-01", "2026-08-31"),
        last_sync_at=None,
    )
    widget.tabs.setCurrentIndex(3)

    matrix = widget.usage_printer_table
    assert matrix.columnCount() == 5
    assert matrix.groupedHeaderItem(1, 1).text() == "Print"
    assert widget.usage_monthly_table.rowCount() == 2
    assert widget.usage_monthly_table.item(1, 0).text().startswith("Meter เริ่มต้น\n")
    assert widget.usage_monthly_table.item(1, 12).text() == "300"
    assert widget.usage_monthly_table.item(1, 13).text() == "—"
    assert widget.usage_monthly_table.item(0, 12).text() == "40"
    assert not hasattr(widget, 'usage_timeline_chart')
    widget.close()
    app.processEvents()
