from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import database
from ui.pages import device_overview
from services.device_config import DeviceConfig
from v5_pages import PageDeviceOverview


class _Repository:
    def list(self, *, enabled_only: bool = False):
        return [
            DeviceConfig(
                0,
                "Printer B",
                "192.0.2.20",
                serial="SER-B",
                connection_status="online",
            )
        ]


def test_device_overview_warns_when_cost_total_contains_old_slot_identity(tmp_path, monkeypatch):
    original = database.get_db_path()
    try:
        database.set_db_path(tmp_path / "device-overview-rollover.sqlite3")
        database.init_db()
        monkeypatch.setattr(
            device_overview,
            "billing_period",
            lambda: (date(2026, 7, 1), date(2026, 7, 31)),
        )
        monkeypatch.setattr(device_overview, "current_period_counters", lambda slot: {})
        monkeypatch.setattr(device_overview, "period_gross_cost", lambda slot: 20.0)
        monkeypatch.setattr(device_overview, "period_net_cost", lambda slots: (30.0, 0.0, 30.0))
        monkeypatch.setattr(device_overview, "current_device_identity", lambda slot: "serial:SER-B")
        monkeypatch.setattr(
            device_overview,
            "current_period_counters_by_identity",
            lambda slot: (
                SimpleNamespace(device_identity="serial:SER-A"),
                SimpleNamespace(device_identity="serial:SER-B"),
            ),
        )
        app = QApplication.instance() or QApplication([])
        page = PageDeviceOverview(repository=_Repository())

        page.refresh()

        assert "ยอดรวมรวมเครื่องเดิมใน slot" in page.cost_summary.text()
        assert "Printer B (Slot 1)" in page.cost_summary.text()
        assert "#FFF4E5" in page.cost_summary.styleSheet()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)
