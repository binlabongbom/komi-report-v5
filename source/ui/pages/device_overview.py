"""Device overview UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from database import get_cfg
from services.billing_v5 import period_gross_cost, period_net_cost
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfigRepository
from services.usage import (
    DEFAULT_USAGE_LABELS,
    billing_period,
    current_device_identity,
    current_period_counters,
    current_period_counters_by_identity,
    default_usage_groups,
    latest_counters,
)
from ui.common_dialogs import AllCountersDialog
from ui.styles import devices as devices_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_GREEN, C_RED, C_TEXT2, F_2XL, F_MD, F_SM, SLOT_COLORS
from widgets import btn, fnt


class PageDeviceOverview(QWidget):
    def __init__(self, repository: DeviceConfigRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self.cache = DailyCacheStore()
        self.mode = "usage"
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        header = QHBoxLayout()
        self.title = QLabel("Usage รอบบิลปัจจุบัน")
        self.title.setFont(fnt(F_2XL, True))
        header.addWidget(self.title)
        header.addStretch()
        self.mode_combo = QComboBox()
        self.mode_combo.setProperty("i18n_items", True)
        self.mode_combo.addItem("Usage รอบนี้", "usage")
        self.mode_combo.addItem("Counter สะสมล่าสุด", "latest")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        header.addWidget(self.mode_combo)
        self.refresh_button = btn("อ่านค่าทันที", "outline")
        header.addWidget(self.refresh_button)
        root.addLayout(header)
        self.period_label = QLabel("")
        self.period_label.setStyleSheet(text_styles.label(C_TEXT2))
        root.addWidget(self.period_label)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        root.addLayout(self.grid)
        self.cost_summary = QLabel("")
        self.cost_summary.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='12px', font_weight='700'))
        root.addWidget(self.cost_summary)
        root.addStretch()

    def _mode_changed(self) -> None:
        self.mode = self.mode_combo.currentData()
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        devices = self.repository.list(enabled_only=True)
        start, end = billing_period()
        self.period_label.setText(f"รอบบิล {start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')} · SNMP ทุก 5 นาที")
        columns = max(1, min(3, len(devices)))
        try:
            pinned = json.loads(get_cfg("pinned_counters_json", "[]") or "[]")
        except json.JSONDecodeError:
            pinned = []
        for index, device in enumerate(devices):
            counters = current_period_counters(device.slot) if self.mode == "usage" else latest_counters(device.slot)
            groups = default_usage_groups(counters)
            card = QFrame()
            card.setObjectName("card")
            card.setStyleSheet(devices_styles.device_overview_card(SLOT_COLORS[device.slot]))
            layout = QVBoxLayout(card)
            cap = QHBoxLayout()
            name = QLabel(device.name)
            name.setProperty("i18n_data", True)
            name.setFont(fnt(F_MD, True))
            cap.addWidget(name)
            cap.addStretch()
            status = QLabel("● Online" if device.connection_status == "online" else "● Offline")
            status.setStyleSheet(text_styles.label(C_GREEN if device.connection_status == 'online' else C_RED))
            cap.addWidget(status)
            layout.addLayout(cap)
            identity = QLabel(f"{device.model or 'Model —'} · {device.serial or 'Serial —'}")
            identity.setStyleSheet(text_styles.label(C_TEXT2))
            layout.addWidget(identity)
            latest = device.last_success_at or device.last_checked_at or "ยังไม่มีข้อมูล"
            last_label = QLabel(f"ข้อมูลล่าสุด: {latest}")
            last_label.setStyleSheet(text_styles.label(C_TEXT2, font_size='11px'))
            layout.addWidget(last_label)
            if self.mode == "usage":
                cache_state = self.cache.load(device.slot, end)
                if cache_state and cache_state.get("first_success"):
                    first_success = str(cache_state["first_success"])
                    try:
                        first_success = first_success[11:16]
                    except (IndexError, TypeError):
                        pass
                    baseline = QLabel(
                        f"เริ่มนับ Usage วันนี้ {first_success} น. · รอบแรกเป็น baseline\n"
                        "เลือก ‘Counter สะสมล่าสุด’ เพื่อดูยอดที่อยู่ในเครื่อง"
                    )
                    baseline.setWordWrap(True)
                    baseline.setStyleSheet(devices_styles.DEVICE_OVERVIEW_BASELINE)
                    layout.addWidget(baseline)
            meter_grid = QGridLayout()
            for row, label in enumerate(DEFAULT_USAGE_LABELS):
                meter_grid.addWidget(QLabel(label), row, 0)
                value = groups.get(label)
                number = QLabel("—" if value is None else f"{value:,.0f}")
                number.setAlignment(Qt.AlignmentFlag.AlignRight)
                number.setFont(fnt(F_SM, True))
                meter_grid.addWidget(number, row, 1)
            offset = len(DEFAULT_USAGE_LABELS)
            for extra_row, key in enumerate(pinned, start=offset):
                meter_grid.addWidget(QLabel(key), extra_row, 0)
                number = QLabel(f"{counters.get(key, 0):,.0f}" if key in counters else "—")
                number.setAlignment(Qt.AlignmentFlag.AlignRight)
                number.setFont(fnt(F_SM, True))
                meter_grid.addWidget(number, extra_row, 1)
            layout.addLayout(meter_grid)
            gross = period_gross_cost(device.slot)
            cost = QLabel(f"ค่าใช้จ่ายก่อนส่วนลด: {gross:,.2f} บาท")
            cost.setStyleSheet(text_styles.label('#18875D', font_weight='700'))
            layout.addWidget(cost)
            more = QPushButton("ดูค่าทั้งหมด")
            more.clicked.connect(lambda _checked=False, d=device, c=counters: AllCountersDialog(f"{d.name} — Counter ทั้งหมด", c, self).exec())
            layout.addWidget(more)
            self.grid.addWidget(card, index // columns, index % columns)
        gross, waste_pct, net = period_net_cost([device.slot for device in devices])
        historical_slots: list[str] = []
        for device in devices:
            configured_identity = current_device_identity(device.slot)
            identities = current_period_counters_by_identity(device.slot)
            if any(
                item.device_identity != configured_identity
                for item in identities
            ):
                historical_slots.append(f"{device.name} (Slot {device.slot + 1})")
        summary = (
            f"รวมก่อนส่วนลด {gross:,.2f} บาท · ส่วนลดกระดาษเสีย {waste_pct:g}% · "
            f"ยอดสุทธิ {net:,.2f} บาท"
        )
        if historical_slots:
            summary += (
                " · ⚠ ยอดรวมรวมเครื่องเดิมใน slot: "
                + ", ".join(historical_slots)
            )
            self.cost_summary.setStyleSheet(
                text_styles.label('#8A4B08', background='#FFF4E5', padding='12px', font_weight='700')
            )
        else:
            self.cost_summary.setStyleSheet(
                text_styles.label('#245268', background='#EEF6F9', padding='12px', font_weight='700')
            )
        self.cost_summary.setText(summary)
        self.title.setText("Usage รอบบิลปัจจุบัน" if self.mode == "usage" else "Counter สะสมล่าสุด")
