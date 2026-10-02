"""Devices UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import re
from datetime import date

from PyQt6.QtCore import Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import tr, translate_text
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.reconciliation import ReconciliationReport, reconcile_web_counters
from services.runtime_snapshots import RuntimeCounterRow, runtime_snapshots
from services.snmp_probe import PaperTrayStatus, SnmpTotalProbe
from services.usage import latest_counters
from ui.components.toner_bar import TonerBar
from ui.styles import devices as devices_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_BORDER, C_MUTED_TEXT, C_TABLE_ALT, C_TEXT2, F_2XL, F_MD, SLOT_COLORS
from widgets import btn, fnt


class _TonerLevelBar(TonerBar):
    """Device-card geometry and compatibility name for the shared toner track."""

    def __init__(self, key: str, value: object, color: str, parent=None) -> None:
        super().__init__(key, value, color, parent)


class _PulsingStatusIndicator(QWidget):
    """Large connection light that pulses while a printer is online."""

    def __init__(self, status: str, color: str, tooltip: str, parent=None) -> None:
        super().__init__(parent)
        self.status = status
        self.color = QColor(color)
        self._pulse = 0.35
        self.setObjectName("device_connection_indicator")
        self.setProperty("connectionStatus", status or "unknown")
        self.setFixedSize(30, 30)
        self.setToolTip(tooltip)
        # Keep the semantic color discoverable to styles, accessibility tools,
        # and lightweight UI regression tests. Painting remains custom.
        self.setStyleSheet(text_styles.label(color))
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(1_200)
        self._animation.setStartValue(0.35)
        self._animation.setKeyValueAt(0.5, 1.0)
        self._animation.setEndValue(0.35)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._set_pulse)
        if status == "online":
            self._animation.start()

    def _set_pulse(self, value: object) -> None:
        self._pulse = float(value)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        pulse = self._pulse if self.status == "online" else 0.55
        halo = QColor(self.color)
        halo.setAlphaF(0.18 + (0.22 * pulse))
        halo_radius = 9.0 + (3.0 * pulse)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, int(halo_radius), int(halo_radius))
        core = QColor(self.color)
        core.setAlphaF(0.75 + (0.25 * pulse))
        painter.setBrush(core)
        painter.drawEllipse(center, 6, 6)


class PageImportV5(QWidget):
    """Device-first live intake view for SNMP, Web and RAM counters."""

    changed = pyqtSignal()
    settings_requested = pyqtSignal(int)
    sync_requested = pyqtSignal()
    sync_log_requested = pyqtSignal()

    def __init__(
        self,
        legacy_import: QWidget,
        repository: DeviceConfigRepository | None = None,
        cache: DailyCacheStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.legacy = legacy_import
        self.repository = repository or DeviceConfigRepository()
        self.cache = cache or DailyCacheStore()
        self._device_cards: list[QWidget] = []
        self._grid_columns = 0
        self._empty_device_state: QWidget | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("รับข้อมูลรายเครื่อง")
        title.setFont(fnt(F_2XL, True))
        header.addWidget(title)
        header.addStretch()

        sync_controls = QVBoxLayout()
        sync_controls.setContentsMargins(0, 0, 0, 0)
        sync_controls.setSpacing(3)
        sync_actions = QHBoxLayout()
        sync_actions.setContentsMargins(0, 0, 0, 0)
        sync_actions.setSpacing(10)
        self.sync_log_button = btn("สถานะการอ่าน", "outline")
        self.sync_log_button.clicked.connect(self.sync_log_requested.emit)
        sync_actions.addWidget(self.sync_log_button)
        self.sync_button = btn("อ่านข้อมูลตอนนี้", "primary")
        self.sync_button.clicked.connect(self._request_sync)
        sync_actions.addWidget(self.sync_button)
        sync_controls.addLayout(sync_actions)
        self.sync_message = QLabel("")
        self.sync_message.setObjectName("import_sync_message")
        self.sync_message.setWordWrap(True)
        self.sync_message.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sync_message.setStyleSheet(text_styles.label('#C62828', font_size='10px', font_weight='600'))
        self.sync_message.setMaximumWidth(310)
        self.sync_message.hide()
        sync_controls.addWidget(self.sync_message, 0, Qt.AlignmentFlag.AlignRight)
        header.addLayout(sync_controls)
        root.addLayout(header)

        self.device_grid = QGridLayout()
        self.device_grid.setContentsMargins(0, 4, 0, 4)
        self.device_grid.setHorizontalSpacing(16)
        self.device_grid.setVerticalSpacing(18)
        self.device_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        root.addLayout(self.device_grid)

        self.legacy.setParent(self)
        self.legacy.setVisible(False)
        if hasattr(self.legacy, "changed"):
            self.legacy.changed.connect(self.changed)
        root.addStretch()
        self.refresh()

    def _request_sync(self) -> None:
        self.sync_message.clear()
        self.sync_message.hide()
        self.sync_button.setEnabled(False)
        self.sync_button.setText(tr("กำลัง Sync…", "Syncing…"))
        self.sync_requested.emit()

    def sync_completed(self) -> None:
        self.sync_button.setText(tr("อ่านข้อมูลตอนนี้", "Read now"))
        self.sync_button.setEnabled(True)
        devices = self.repository.list(enabled_only=True)
        failed = [device for device in devices if device.connection_status != "online"]
        if failed:
            self.sync_message.setText(
                tr(
                    "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้ โปรดตรวจสอบเครือข่าย",
                    "Could not connect to the printer. Check the network connection.",
                )
            )
            self.sync_message.setToolTip(
                "\n".join(
                    f"{device.name}: {device.last_error or device.connection_status}"
                    for device in failed
                )
            )
            self.sync_message.show()
        else:
            self.sync_message.clear()
            self.sync_message.hide()

    @staticmethod
    def _format_number(value: object) -> str:
        if value in (None, ""):
            return "—"
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _section_title(text: str, source: str = "") -> QLabel:
        label = QLabel(text if not source else f"{text}   {source}")
        label.setFont(fnt(F_MD, True))
        label.setStyleSheet(devices_styles.import_section_title())
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(text_styles.label(C_BORDER))
        return line

    @staticmethod
    def _value_row(label: str, value: str, source: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)
        name = QLabel(label)
        name.setStyleSheet(text_styles.label(C_TEXT2, background='transparent'))
        name.setFixedWidth(100)
        row.addWidget(name)
        number = QLabel(value)
        number.setFont(fnt(F_MD, True))
        number.setAlignment(Qt.AlignmentFlag.AlignRight)
        number.setWordWrap(True)
        number.setMinimumWidth(0)
        number.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(number, 1)
        if source:
            badge = QLabel(source)
            badge.setStyleSheet(text_styles.label('#64748B', font_size='10px'))
            badge.setFixedWidth(45)
            badge.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(badge)
        return row

    def _snapshot(self, device: DeviceConfig) -> dict:
        state = self.cache.load(device.slot, date.today()) or {}
        counters = latest_counters(device.slot)
        ram_snapshot = runtime_snapshots.get(device.slot)
        snmp_total = state.get("last_snmp_total", device.last_total)
        web_total = counters.get("counter.total.total", device.last_total)
        toner = state.get("snmp_toner") or {}
        paper = state.get("snmp_paper") or []
        paper_alerts = state.get("snmp_paper_alerts") or []
        web_rows = (
            ram_snapshot.web_rows
            if ram_snapshot is not None
            else tuple(
                RuntimeCounterRow(key, key, value, "Daily Cache")
                for key, value in sorted(counters.items())
            )
        )
        subject_rows = ram_snapshot.subject_rows if ram_snapshot is not None else ()
        return {
            "snmp_total": snmp_total,
            "web_total": web_total,
            "toner": toner,
            "paper": paper,
            "paper_alerts": paper_alerts,
            "web_rows": web_rows,
            "subject_rows": subject_rows,
            "counter_count": len(web_rows),
            "last_success": state.get("last_success") or device.last_success_at,
            "reconciliation": reconcile_web_counters(
                {row.canonical_field: row.count for row in web_rows}
            ),
        }

    def _web_table(self, rows: tuple[RuntimeCounterRow, ...]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("import_web_table")
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Counter", tr("ค่า", "Value")])
        table.setRowCount(len(rows))
        table.setMinimumWidth(0)
        table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        table.setFixedHeight(202)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Qt applies the global ``item`` padding again to ``item:alternate``.
        # Paint zebra rows explicitly so every row keeps the same text origin.
        table.setAlternatingRowColors(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setStyleSheet(
            devices_styles.IMPORT_TABLE
        )
        vertical_header = table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical_header.setDefaultSectionSize(34)
        vertical_header.setMinimumSectionSize(34)
        horizontal_header = table.horizontalHeader()
        horizontal_header.setFixedHeight(38)
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(1, 84)
        for index, row in enumerate(rows):
            field = QTableWidgetItem(row.canonical_field)
            field.setToolTip(f"{row.label}\n{row.source_path}")
            field.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value = QTableWidgetItem(self._format_number(row.count))
            value.setData(Qt.ItemDataRole.UserRole, row.count)
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if index % 2:
                field.setBackground(QColor(C_TABLE_ALT))
                value.setBackground(QColor(C_TABLE_ALT))
            table.setItem(index, 0, field)
            table.setItem(index, 1, value)
        return table

    @staticmethod
    def _set_zero_rows_hidden(table: QTableWidget, hidden: bool) -> None:
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            try:
                is_zero = not isinstance(raw, bool) and float(raw) == 0.0
            except (TypeError, ValueError):
                is_zero = False
            table.setRowHidden(row, hidden and is_zero)

    @staticmethod
    def _subject_total_rows(rows: tuple[RuntimeCounterRow, ...]) -> tuple[RuntimeCounterRow, ...]:
        """Return one explicit Total counter per User/Account without guessing a sum."""
        totals: dict[tuple[str, str], RuntimeCounterRow] = {}
        for row in rows:
            canonical = row.canonical_field.casefold()
            label = row.label.strip().casefold()
            if not (canonical.endswith(".total.total") or label in {"total", "total counter"}):
                continue
            identity = row.subject_id or row.subject_name or "unknown"
            key = (row.subject_type or "subject", identity)
            totals.setdefault(key, row)
        return tuple(totals.values())

    def _subject_table(self, rows: tuple[RuntimeCounterRow, ...]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("import_subject_table")
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["User / Account", "Total Counter"])
        table.setRowCount(len(rows))
        table.setMinimumWidth(0)
        table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        table.setFixedHeight(222)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setStyleSheet(
            devices_styles.IMPORT_TABLE_SUBJECT_TABLE
        )
        vertical_header = table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical_header.setDefaultSectionSize(34)
        vertical_header.setMinimumSectionSize(34)
        horizontal_header = table.horizontalHeader()
        horizontal_header.setFixedHeight(38)
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(1, 120)
        for index, row in enumerate(rows):
            subject = QTableWidgetItem(row.subject_name or row.subject_id or "Unknown")
            subject.setToolTip(
                f"type={row.subject_type or 'unknown'} · id={row.subject_id or '—'}\n{row.source_path}"
            )
            subject.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value = QTableWidgetItem(self._format_number(row.count))
            value.setToolTip(row.canonical_field)
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if index % 2:
                for item in (subject, value):
                    item.setBackground(QColor(C_TABLE_ALT))
            table.setItem(index, 0, subject)
            table.setItem(index, 1, value)
        return table

    def _toner_row(self, toner: dict) -> QWidget:
        panel = QWidget()
        panel.setObjectName("toner_level_row")
        # Override the application-wide QWidget page background. This wrapper
        # sits inside a white device card, so any exposed gaps around/between
        # the four custom bars must match that card instead of page gray.
        panel.setStyleSheet(devices_styles.IMPORT_PANEL)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        colors = {"C": "#009DC4", "Y": "#B28700", "M": "#D81B60", "K": "#1F2937"}
        for key in ("C", "Y", "M", "K"):
            layout.addWidget(_TonerLevelBar(key, toner.get(key), colors[key]), 1)
        return panel

    @staticmethod
    def _cached_paper_trays(paper: object) -> tuple[PaperTrayStatus, ...]:
        """Read only identifiable physical input trays from the SNMP cache."""
        trays: list[PaperTrayStatus] = []
        if isinstance(paper, list):
            for item in paper:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "Tray")
                level = SnmpTotalProbe._integer(item.get("level"))
                capacity = SnmpTotalProbe._integer(item.get("capacity"))
                status = SnmpTotalProbe._integer(item.get("status"))
                input_index = SnmpTotalProbe._integer(item.get("input_index"))
                trays.append(PaperTrayStatus(name, level, capacity, status, input_index))
        return tuple(trays)

    @staticmethod
    def _tray_display_name(tray: PaperTrayStatus) -> str | None:
        """Map vendor labels to the configured operator-facing tray slots."""
        normalized = tray.name.casefold()
        if "bypass" in normalized:
            return "Bypass Tray"
        patterns = (
            r"(?:tray|cassette|drawer)\s*(?:no\.?\s*)?([1-5])\b",
            r"\b([1-5])(?:st|nd|rd|th)\s*(?:tray|cassette|drawer)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return f"Tray{match.group(1)}"
        if tray.input_index in {1, 2, 3, 4, 5}:
            return f"Tray{tray.input_index}"
        return None

    @classmethod
    def _ordered_paper_trays(cls, paper: object) -> tuple[tuple[str, PaperTrayStatus], ...]:
        discovered: dict[str, PaperTrayStatus] = {}
        for tray in cls._cached_paper_trays(paper):
            label = cls._tray_display_name(tray)
            if label is not None:
                discovered.setdefault(label, tray)
        # The two-row order mirrors the physical tray arrangement requested
        # by the operator: odd trays on top, even trays then Bypass below.
        order = ("Tray1", "Tray3", "Tray5", "Tray2", "Tray4", "Bypass Tray")
        return tuple((label, discovered[label]) for label in order if label in discovered)

    @staticmethod
    def _paper_tray_rows(
        ordered_trays: tuple[tuple[str, PaperTrayStatus], ...],
    ) -> tuple[tuple[tuple[str, PaperTrayStatus], ...], ...]:
        """Keep the physical tray matrix, with Bypass on its own row."""
        by_name = dict(ordered_trays)
        top = tuple((name, by_name[name]) for name in ("Tray1", "Tray3", "Tray5") if name in by_name)
        bottom = tuple((name, by_name[name]) for name in ("Tray2", "Tray4") if name in by_name)
        bypass = (("Bypass Tray", by_name["Bypass Tray"]),) if "Bypass Tray" in by_name else ()
        return tuple(row for row in (top, bottom, bypass) if row)

    @staticmethod
    def _paper_tray_columns(ordered_trays: tuple[tuple[str, PaperTrayStatus], ...]) -> int:
        return 3 if any(name == "Tray5" for name, _tray in ordered_trays) else 2

    @staticmethod
    def _paper_tile_state(tray: PaperTrayStatus, alerts: tuple[str, ...]) -> tuple[str, str, str, str]:
        """Render only confirmed-empty trays in orange; all other states stay neutral grey."""
        normalized_names = (tray.name.casefold(), (PageImportV5._tray_display_name(tray) or "").casefold())
        scoped_alerts = tuple(
            alert
            for alert in alerts
            if any(name and name in alert.casefold() for name in normalized_names)
        )
        summary = SnmpTotalProbe.summarize_paper((tray,), scoped_alerts)
        labels = {
            "empty": ("empty", "#F59E0B", "#FFFFFF", "#D97706"),
            "attention": ("unknown", "#E5E7EB", "#475569", "#CBD5E1"),
            "available": ("available", "#E5E7EB", "#334155", "#CBD5E1"),
            "unknown": ("unknown", "#E5E7EB", "#475569", "#CBD5E1"),
        }
        return labels[summary.state]

    def _paper_tray_tiles(self, paper: object, alerts: object) -> QWidget | None:
        ordered_trays = self._ordered_paper_trays(paper)
        if not ordered_trays:
            return None
        known_alerts = tuple(str(alert) for alert in alerts if str(alert).strip()) if isinstance(alerts, list) else ()
        panel = QWidget()
        panel.setObjectName("paper_tray_tiles")
        panel.setStyleSheet(devices_styles.IMPORT_PANEL_PAPER_TRAY_TILES)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title = QLabel("สถานะถาดกระดาษ")
        title.setStyleSheet(text_styles.label(C_TEXT2, background='transparent'))
        layout.addWidget(title)
        columns = self._paper_tray_columns(ordered_trays)
        for row_trays in self._paper_tray_rows(ordered_trays):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            is_bypass_row = row_trays[0][0] == "Bypass Tray"
            for tray_name, tray in row_trays:
                state, background, foreground, border = self._paper_tile_state(tray, known_alerts)
                tooltip_state = "กระดาษหมด" if state == "empty" else "สถานะกระดาษปกติ" if state == "available" else "อ่านสถานะกระดาษไม่ได้"
                tile = QFrame()
                tile.setObjectName("paper_tray_tile")
                tile.setProperty("trayName", tray_name)
                tile.setProperty("paperState", state)
                tile.setFixedHeight(20)
                tile_layout = QVBoxLayout(tile)
                tile_layout.setContentsMargins(4, 1, 4, 1)
                name = QLabel(tray_name)
                name.setAlignment(Qt.AlignmentFlag.AlignCenter)
                name.setStyleSheet(devices_styles.IMPORT_NAME)
                tile.setStyleSheet(
                    devices_styles.import_tile(background, foreground, border)
                )
                tile.setToolTip(f"{tray_name} · {tooltip_state}")
                tile_layout.addWidget(name)
                row.addWidget(tile, columns if is_bypass_row else 1)
            if not is_bypass_row:
                for _blank in range(columns - len(row_trays)):
                    row.addStretch(1)
            layout.addLayout(row)
        return panel

    @staticmethod
    def _connection_indicator(device: DeviceConfig) -> _PulsingStatusIndicator:
        status = device.connection_status.casefold()
        if status == "online":
            color = "#00A651"
            text = "เชื่อมต่อแล้ว"
        elif status in {"pending", "unknown", ""}:
            color = "#F5C000"
            text = "ยังไม่ได้ตรวจสอบ"
        else:
            color = "#D71920"
            text = "ไม่สามารถเชื่อมต่อได้"
        detail = device.last_error or text
        checked = f"\nตรวจล่าสุด: {device.last_checked_at}" if device.last_checked_at else ""
        return _PulsingStatusIndicator(status or "unknown", color, f"{text}\n{detail}{checked}")

    def _device_card(self, device: DeviceConfig) -> QFrame:
        snapshot = self._snapshot(device)
        card = QFrame()
        card.setObjectName("import_device_card")
        card.setStyleSheet(
            devices_styles.import_device_card(SLOT_COLORS[device.slot])
        )
        # The page changes between one, two and three columns.  A hard minimum
        # width makes QGridLayout overlap cards at 1024 px, so the responsive
        # reflow owns the column count and cards are allowed to shrink cleanly.
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(9)

        top = QHBoxLayout()
        name = QLabel(device.name)
        name.setProperty("i18n_data", True)
        name.setFont(fnt(F_MD, True))
        name.setWordWrap(True)
        name.setMinimumWidth(0)
        top.addWidget(name, 1)
        top.addStretch()
        connection_indicator = self._connection_indicator(device)
        top.addWidget(connection_indicator)
        layout.addLayout(top)
        card._connection_indicator = connection_indicator

        layout.addLayout(self._value_row("ชื่อรุ่น", device.model or "—"))
        layout.addLayout(self._value_row("Serial number", device.serial or "—"))
        layout.addLayout(self._value_row("Total Meter", self._format_number(snapshot["snmp_total"])))
        toner_title = QLabel("ปริมาณหมึก")
        toner_title.setStyleSheet(text_styles.label(C_TEXT2, background='transparent'))
        layout.addWidget(toner_title)
        layout.addWidget(self._toner_row(snapshot["toner"]))
        paper_tiles = self._paper_tray_tiles(snapshot["paper"], snapshot["paper_alerts"])
        if paper_tiles is not None:
            layout.addWidget(paper_tiles)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_title(tr("ปริมาณการใช้งาน", "Usage")))
        layout.addLayout(self._value_row("ยอดรวม Meter", self._format_number(snapshot["web_total"])))
        detail = QLabel(
            tr(
                f"อ่านได้ {snapshot['counter_count']:,} Counter"
                + (f" · ล่าสุด {str(snapshot['last_success'])[11:16]} น." if snapshot["last_success"] else ""),
                f"Read {snapshot['counter_count']:,} counters"
                + (f" · latest {str(snapshot['last_success'])[11:16]}" if snapshot["last_success"] else ""),
            )
        )
        detail.setStyleSheet(text_styles.label(C_MUTED_TEXT, font_size='10px', background='transparent'))
        layout.addWidget(detail)
        web_table = self._web_table(snapshot["web_rows"])
        zero_count = sum(
            1
            for row in snapshot["web_rows"]
            if not isinstance(row.count, bool) and isinstance(row.count, (int, float)) and float(row.count) == 0.0
        )
        zero_checkbox = QCheckBox(
            tr(
                f"ซ่อน Counter ที่มีค่าเป็น 0 ({zero_count:,} รายการ)",
                f"Hide zero-value counters ({zero_count:,} items)",
            )
        )
        zero_checkbox.toggled.connect(
            lambda checked, table=web_table: self._set_zero_rows_hidden(table, checked)
        )
        zero_checkbox.setParent(card)
        zero_checkbox.hide()
        card._zero_checkbox = zero_checkbox
        reconciliation: ReconciliationReport = snapshot["reconciliation"]
        reconciliation_label = QLabel(translate_text(reconciliation.summary(limit=3)))
        reconciliation_label.setWordWrap(True)
        if reconciliation.needs_review:
            reconciliation_label.setStyleSheet(
                text_styles.label('#A62B2B', background='#FFF1F0', border='1px solid #F2B8B5', padding='8px', font_size='10px', font_weight='700')
            )
        elif reconciliation.checked_count:
            reconciliation_label.setStyleSheet(
                text_styles.label('#176B49', background='#EDF8F2', border='1px solid #B8DFC9', padding='8px', font_size='10px', font_weight='700')
            )
        else:
            reconciliation_label.setStyleSheet(text_styles.label('#64748B', background='#F8FAFC', padding='8px', font_size='10px'))
        reconciliation_label.setToolTip(reconciliation.audit_summary(limit=max(1, len(reconciliation.issues))))
        reconciliation_label.setParent(card)
        reconciliation_label.hide()
        card._reconciliation_label = reconciliation_label
        card._web_table = web_table
        layout.addWidget(web_table)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_title("User Authentication / Account Track"))
        subject_rows = snapshot["subject_rows"]
        subject_total_rows = self._subject_total_rows(subject_rows)
        if subject_total_rows:
            subject_detail = QLabel(
                tr(
                    f"RAM snapshot · {len(subject_total_rows):,} User/Account · แสดง Total Counter",
                    f"RAM snapshot · {len(subject_total_rows):,} users/accounts · Total Counter",
                )
            )
            subject_detail.setStyleSheet(text_styles.label(C_MUTED_TEXT, font_size='10px', background='transparent'))
            layout.addWidget(subject_detail)
            subject_table = self._subject_table(subject_total_rows)
            card._subject_table = subject_table
            layout.addWidget(subject_table)
        else:
            empty = QLabel(
                tr(
                    "ไม่พบ User Authentication / Account Track ที่เปิดใช้งาน",
                    "No enabled User Authentication / Account Track data",
                )
            )
            empty.setWordWrap(True)
            empty.setMinimumWidth(0)
            empty.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            empty.setStyleSheet(
                devices_styles.import_empty()
            )
            layout.addWidget(empty)
            card._subject_table = None
        layout.addStretch()
        return card

    @staticmethod
    def _responsive_columns(width: int, device_count: int) -> int:
        """Keep counter labels readable while using the available width."""
        readable_columns = max(1, min(3, width // 300))
        return max(1, min(readable_columns, device_count))

    def _clear_grid_positions(self) -> None:
        while self.device_grid.count():
            self.device_grid.takeAt(0)
        for column in range(3):
            self.device_grid.setColumnStretch(column, 0)
            self.device_grid.setColumnMinimumWidth(column, 0)

    def _reflow_device_cards(self, *, force: bool = False) -> None:
        if not self._device_cards:
            return
        available_width = max(0, self.width() - 44)
        columns = self._responsive_columns(available_width, len(self._device_cards))
        if not force and columns == self._grid_columns:
            return
        self._clear_grid_positions()
        self._grid_columns = columns
        for index, card in enumerate(self._device_cards):
            self.device_grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.device_grid.setColumnStretch(column, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_device_cards()

    def refresh(self) -> None:
        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._device_cards.clear()
        self._empty_device_state = None
        self._grid_columns = 0
        devices = self.repository.list(enabled_only=True)
        for device in devices:
            card = self._device_card(device)
            self._device_cards.append(card)
        if self._device_cards:
            self._reflow_device_cards(force=True)
        if not devices:
            empty = QLabel("ยังไม่ได้ตั้งค่าเครื่องพิมพ์ · ไปที่ Settings เพื่อเพิ่ม 1–3 เครื่อง")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(text_styles.label('#64748B', background='white', border='1px solid #CBD5E1', padding='28px'))
            self._empty_device_state = empty
            self.device_grid.addWidget(empty, 0, 0)
            self.device_grid.setColumnStretch(0, 1)
