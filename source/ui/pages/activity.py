"""Activity UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import _open, get_cfg, get_db_path
from i18n import apply_language, tr
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pipeline_log import PipelineEvent, pipeline_log
from services.polling import PollingPolicy
from services.runtime_snapshots import runtime_snapshots
from services.sync_schedule import DailyTimelineEntry, build_daily_timeline, load_schedule_windows, schedule_mode_at
from ui.page_tabs import PageTabs as QTabWidget
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_GREEN, C_RED, C_TEXT2, F_2XL, F_MD, F_SM
from widgets import btn, fnt


class PagePipelineLog(QWidget):
    """Live observability for SNMP → Web → RAM cache → daily database."""

    sync_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    STAGES = (
        ("ทุกขั้นตอน", None),
        ("ตรวจสถานะ (SNMP)", "SNMP"),
        ("อ่าน Meter (Web)", "WEB"),
        ("เก็บข้อมูล (RAM / DB)", "RAM_DB"),
        ("ผลอ่านร่วม (Sync)", "SYNC"),
        ("กฎระบบ", "POLICY"),
    )

    def __init__(
        self,
        repository: DeviceConfigRepository | None = None,
        cache: DailyCacheStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self.cache = cache or DailyCacheStore()
        self._last_live_signature: tuple[object, ...] | None = None
        self._visible_events: list[PipelineEvent] = []
        self._build()
        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self._refresh_if_visible)
        self.timer.start()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        self.page_title = QLabel("สถานะและประวัติการอ่าน")
        self.page_title.setFont(fnt(F_2XL, True))
        root.addWidget(self.page_title)
        self.page_note = QLabel(
            "เช็กว่าเครื่องใดอ่าน Meter สำเร็จ มีอะไรต้องทำหรือไม่ แล้วค่อยเปิดรายละเอียดเมื่อจำเป็น "
            "· Live Log เก็บเฉพาะรอบที่เปิดโปรแกรมนี้ สูงสุด 5,000 เหตุการณ์"
        )
        self.page_note.setWordWrap(True)
        self.page_note.setStyleSheet(text_styles.label(C_TEXT2))
        root.addWidget(self.page_note)

        self.tabs = QTabWidget()
        def scrollable(content):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(content)
            return scroll
        self.tabs.addTab(scrollable(self._status_tab()), "สถานะการอ่าน")
        self.tabs.addTab(scrollable(self._live_tab()), "ประวัติการอ่าน")
        self.tabs.addTab(scrollable(self._cache_tab()), "ข้อมูลวันนี้")
        self.timeline_scroll = self._timeline_tab()
        self.tabs.addTab(self.timeline_scroll, "การทำงานอัตโนมัติ")
        from ui.counter_review import CounterReviewPanel
        self.counter_reviews = CounterReviewPanel(self.repository, self.cache)
        self.counter_review_page = scrollable(self.counter_reviews)
        self.tabs.addTab(self.counter_review_page, tr("ตรวจสอบมิเตอร์", "Meter review"))
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        root.addWidget(self.tabs, 1)

    def _status_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        top.addWidget(self.status_banner, 1)
        self.sync_button = btn("อ่านข้อมูลตอนนี้", "primary")
        self.sync_button.clicked.connect(self.sync_requested.emit)
        top.addWidget(self.sync_button)
        refresh_button = btn("รีเฟรช", "outline")
        refresh_button.clicked.connect(self.refresh_status)
        top.addWidget(refresh_button)
        layout.addLayout(top)

        schedule_row = QHBoxLayout()
        self.status_schedule = QLabel()
        self.status_schedule.setWordWrap(True)
        self.status_schedule.setStyleSheet(text_styles.label(C_TEXT2, padding='2px 4px'))
        schedule_row.addWidget(self.status_schedule, 1)
        settings_button = btn("ตั้งเวลาอ่านข้อมูล", "outline")
        settings_button.clicked.connect(self.settings_requested.emit)
        schedule_row.addWidget(settings_button)
        layout.addLayout(schedule_row)

        self.status_rows = QVBoxLayout()
        self.status_rows.setSpacing(10)
        layout.addLayout(self.status_rows)
        layout.addStretch()
        return page

    def _timeline_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        self.timeline_page = page
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.timeline_status = QLabel("")
        self.timeline_status.setWordWrap(True)
        self.timeline_status.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='10px', font_weight='700'))
        top.addWidget(self.timeline_status, 1)
        refresh_button = btn(tr("รีเฟรช", "Refresh"), "outline")
        refresh_button.clicked.connect(self.refresh_timeline)
        top.addWidget(refresh_button)
        layout.addLayout(top)

        schedule_card = QFrame()
        schedule_card.setStyleSheet(
            settings_styles.PIPELINE_LOG_SCHEDULE_CARD
        )
        schedule_card.setObjectName("schedule_timeline_card")
        schedule_layout = QVBoxLayout(schedule_card)
        schedule_layout.setContentsMargins(14, 12, 14, 12)
        schedule_layout.setSpacing(8)
        schedule_heading = QLabel("แผนการอ่านข้อมูลวันนี้")
        schedule_heading.setFont(fnt(F_MD, True))
        schedule_layout.addWidget(schedule_heading)
        self.schedule_summary = QLabel()
        self.schedule_summary.setWordWrap(True)
        self.schedule_summary.setStyleSheet(text_styles.label('#475569'))
        schedule_layout.addWidget(self.schedule_summary)
        self.schedule_band = QFrame()
        self.schedule_band.setObjectName("schedule_timeline_band")
        self.schedule_band.setStyleSheet(settings_styles.PIPELINE_LOG_SCHEDULE_BAND)
        self.schedule_band_layout = QHBoxLayout(self.schedule_band)
        self.schedule_band_layout.setContentsMargins(0, 0, 0, 0)
        self.schedule_band_layout.setSpacing(3)
        schedule_layout.addWidget(self.schedule_band)
        self.schedule_notice = QLabel("เป็นแผนที่ตั้งไว้ · ผลการอ่านจริงดูได้จากแท็บ ประวัติการอ่าน")
        self.schedule_notice.setWordWrap(True)
        self.schedule_notice.setStyleSheet(text_styles.label('#64748B', font_size='12px'))
        schedule_layout.addWidget(self.schedule_notice)
        schedule_actions = QHBoxLayout()
        schedule_actions.addStretch()
        schedule_settings_button = btn("ตั้งเวลาอ่านข้อมูล", "outline")
        schedule_settings_button.clicked.connect(self.settings_requested.emit)
        schedule_actions.addWidget(schedule_settings_button)
        schedule_layout.addLayout(schedule_actions)
        layout.addWidget(schedule_card)

        self.next_poll_label = QLabel("")
        self.next_poll_label.setWordWrap(True)
        self.next_poll_label.setStyleSheet(text_styles.label(C_TEXT2, padding='2px 4px 8px'))
        layout.addWidget(self.next_poll_label)

        self.timeline_detail_toggle = QCheckBox("แสดงตารางรายละเอียดตามช่วงเวลา")
        self.timeline_detail_toggle.toggled.connect(self._toggle_timeline_detail)
        layout.addWidget(self.timeline_detail_toggle)
        self.timeline_table = QTableWidget(0, 7)
        self.timeline_table.setHorizontalHeaderLabels(
            ["เวลา", "โหมด", "SNMP", "Web Connection", "RAM / Daily Cache", "Database", "หมายเหตุ"]
        )
        self.timeline_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.timeline_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.timeline_table.verticalHeader().setVisible(False)
        self.timeline_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.timeline_table)
        for column, width in enumerate((125, 110, 210, 230, 330, 260, 260)):
            self.timeline_table.setColumnWidth(column, width)
        layout.addWidget(self.timeline_table)
        self.timeline_table.setVisible(False)
        self.timeline_technical = self._technical_rules_section()
        layout.addWidget(self.timeline_technical)
        self.timeline_technical.hide()
        layout.addStretch()
        return scroll

    def _live_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.device_filter = QComboBox()
        self.device_filter.addItem("ทุกเครื่อง", None)
        for device in self.repository.list(enabled_only=True):
            self.device_filter.addItem(f"{device.name} ({device.host})", device.slot)
        self.device_filter.currentIndexChanged.connect(self.refresh_live)
        controls.addWidget(self.device_filter)
        self.stage_filter = QComboBox()
        self.stage_filter.setProperty("i18n_items", True)
        for label, stage in self.STAGES:
            self.stage_filter.addItem(label, stage)
        self.stage_filter.currentIndexChanged.connect(self.refresh_live)
        controls.addWidget(self.stage_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("ค้นหาเหตุผล, counter หรือข้อความในเหตุการณ์...")
        self.search.textChanged.connect(self.refresh_live)
        controls.addWidget(self.search, 1)
        refresh_button = btn("รีเฟรช", "outline")
        refresh_button.clicked.connect(self.refresh_live)
        controls.addWidget(refresh_button)
        copy_button = btn("คัดลอก", "outline")
        copy_button.clicked.connect(self._copy_live)
        controls.addWidget(copy_button)
        clear_button = btn("ล้าง Live Log", "outline")
        clear_button.clicked.connect(self._clear_live)
        controls.addWidget(clear_button)
        layout.addLayout(controls)

        self.live_count = QLabel("")
        self.live_count.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(self.live_count)
        self.live_table = QTableWidget(0, 5)
        self.live_table.setHorizontalHeaderLabels(
            [tr("เวลา", "Time"), tr("เครื่องพิมพ์", "Printer"),
             tr("อ่านโดย", "Read by"), tr("ผลลัพธ์", "Result"), tr("รายละเอียด", "Details")]
        )
        self.live_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.live_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.live_table.verticalHeader().setVisible(False)
        self.live_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.live_table)
        for column, width in enumerate((145, 200, 180, 110, 430)):
            self.live_table.setColumnWidth(column, width)
        layout.addWidget(self.live_table, 1)
        self.live_detail = QPlainTextEdit()
        self.live_detail.setReadOnly(True)
        self.live_detail.setPlaceholderText("คลิกเหตุการณ์เพื่อดู Stage, endpoint และรายละเอียดเชิงเทคนิค")
        self.live_detail.setMinimumHeight(92)
        self.live_detail.setMaximumHeight(132)
        self.live_detail.setStyleSheet(
            settings_styles.PIPELINE_LOG_LIVE_DETAIL
        )
        self.live_table.cellClicked.connect(self._show_live_detail)
        self.live_table.itemActivated.connect(
            lambda item: self._show_live_detail(item.row(), item.column())
        )
        layout.addWidget(self.live_detail)
        return page

    def _cache_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        hint = QLabel(
            "ข้อมูลที่อ่านวันนี้พักอยู่ใน Cache ก่อนปิดเป็น Daily Record เมื่อเปลี่ยนวัน "
            "· รายละเอียด raw อยู่ในคอลัมน์ด้านขวาเพื่อใช้ตรวจสอบ"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='10px'))
        layout.addWidget(hint)
        refresh_button = btn("รีเฟรชข้อมูลวันนี้", "outline")
        refresh_button.clicked.connect(self.refresh_cache)
        layout.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignRight)
        self.cache_table = QTableWidget(0, 13)
        self.cache_table.setHorizontalHeaderLabels(
            [
                "เครื่อง / IP",
                "วันที่",
                "SNMP reads",
                "Web saves",
                "Opening Total",
                "Latest Total",
                "Daily Delta",
                "SNMP Total OID",
                "Errors",
                "First / Last success",
                "Cache status",
                "DB ล่าสุด",
                "Rollup status",
            ]
        )
        self.cache_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cache_table.verticalHeader().setVisible(False)
        self.cache_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.cache_table)
        for column, width in enumerate((190, 100, 90, 90, 110, 110, 100, 290, 70, 230, 130, 120, 190)):
            self.cache_table.setColumnWidth(column, width)
        layout.addWidget(self.cache_table, 1)
        return page

    def _technical_rules_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("sync_technical_section")
        section.setStyleSheet(
            settings_styles.PIPELINE_LOG_SECTION
        )
        layout = QVBoxLayout(section)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        title = QLabel("รายละเอียดทางเทคนิค")
        title.setFont(fnt(F_MD, True))
        layout.addWidget(title)
        note = QLabel("กฎที่ใช้อยู่จริงสำหรับ Scheduler, Web Meter, Cache และการปิดข้อมูลรายวัน")
        note.setWordWrap(True)
        note.setStyleSheet(text_styles.label('#64748B'))
        layout.addWidget(note)
        self.rules_table = QTableWidget(0, 3)
        self.rules_table.setHorizontalHeaderLabels(["ขั้นตอน", "ค่าปัจจุบัน", "เงื่อนไข / ผลลัพธ์"])
        self.rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.rules_table)
        self.rules_table.setColumnWidth(0, 220)
        self.rules_table.setColumnWidth(1, 260)
        layout.addWidget(self.rules_table)
        return section

    @staticmethod
    def _stabilize_table(table: QTableWidget) -> None:
        """Keep every row on the same text origin and avoid Qt alternate-state jitter."""
        table.setAlternatingRowColors(False)
        table.setWordWrap(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setFixedHeight(40)

    @staticmethod
    def _align_log_item(item: QTableWidgetItem, row: int, *, centered: bool = False) -> None:
        alignment = Qt.AlignmentFlag.AlignCenter if centered else Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        if row % 2:
            item.setBackground(QColor("#F7F8FA"))

    def _refresh_if_visible(self) -> None:
        if self.isVisible():
            self.refresh()
        elif self.timeline_page.isVisible():
            self.refresh_timeline()

    def refresh(self) -> None:
        if self.tabs.currentWidget() is self.counter_reviews:
            self.counter_reviews.refresh()
        elif self.tabs.currentIndex() == 0:
            self.refresh_status()
        elif self.tabs.currentIndex() == 1:
            self.refresh_live()
        elif self.tabs.currentIndex() == 2:
            self.refresh_cache()
        else:
            self.refresh_timeline()

    @staticmethod
    def _display_time(value: str | None) -> str:
        if not value:
            return "ยังไม่มีข้อมูล"
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%d/%m %H:%M") + " น."
        except ValueError:
            return value.replace("T", " ")

    def _next_poll_for_device(self, device: DeviceConfig, now: datetime, snmp_minutes: int) -> str:
        start_actions = {"เริ่มรอบตาม Schedule", "เริ่มรอบอ่านทันที"}
        latest = next(
            (
                event
                for event in pipeline_log.snapshot(limit=2_000)
                if event.device_slot == device.slot and event.action in start_actions
            ),
            None,
        )
        if latest is None:
            if device.last_checked_at or device.last_success_at:
                return "ระบบจะตรวจ SNMP ตามรอบที่กำหนด"
            return "รอ Scheduler เริ่มรอบแรก หรือกดอ่านข้อมูลตอนนี้"
        try:
            due = datetime.fromisoformat(latest.at) + timedelta(minutes=snmp_minutes)
        except ValueError:
            return "รอ Scheduler รอบถัดไป"
        if due <= now:
            return "ถึงเวลาตรวจแล้ว · กำลังรอ Timer/คิว"
        return f"SNMP รอบถัดไปประมาณ {due.strftime('%H:%M')} น."

    @staticmethod
    def _plain_error(value: str) -> str:
        from services.support_diagnostics import diagnose, safe_text
        diagnostic = diagnose(value)
        if diagnostic.code == 'operation_failed':
            return safe_text(value) or diagnostic.summary
        return f'{diagnostic.summary} [{diagnostic.error_code} / {diagnostic.code}]'

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _open_device_events(self, slot: int) -> None:
        self.tabs.setCurrentIndex(1)
        index = self.device_filter.findData(slot)
        if index >= 0:
            self.device_filter.setCurrentIndex(index)
        self.refresh_live()

    def _status_for_device(
        self,
        device: DeviceConfig,
        state: dict | None,
        events: list[PipelineEvent],
        now: datetime,
        snmp_minutes: int,
    ) -> tuple[str, str, str, str, str]:
        latest_success = device.last_success_at or (state or {}).get("last_success")
        error_event = next(
            (event for event in events if event.device_slot == device.slot and event.status == "error"),
            None,
        )
        review_event = next(
            (
                event
                for event in events
                if event.device_slot == device.slot
                and event.status == "warning"
                and ("review" in event.action.lower() or "reconciliation" in event.action.lower())
            ),
            None,
        )
        status = (device.connection_status or "pending").lower()
        if status == "offline" or device.last_error or error_event:
            raw_reason = device.last_error or (error_event.value if error_event else "")
            from services.support_diagnostics import diagnose
            diagnostic = diagnose(raw_reason)
            web_failure = diagnostic.code in {'auth_rejected', 'password_rejected', 'admin_required', 'factory_credentials_rejected', 'session_busy', 'tls_handshake', 'tls_protocol', 'tls_certificate', 'certificate_expired', 'certificate_name', 'certificate_trust', 'certificate_pin', 'endpoint_missing'}
            return (
                "อ่าน Web ไม่สำเร็จ" if web_failure else "เชื่อมต่อไม่ได้",
                self._plain_error(raw_reason),
                "#B42318",
                diagnostic.action,
                latest_success or "",
            )
        if review_event:
            return (
                "ต้องตรวจสอบ",
                "ข้อมูล Meter ต้องตรวจสอบก่อนนำไปใช้คิดค่าใช้จ่าย",
                "#B54708",
                "เปิดประวัติการอ่านและข้อมูลวันนี้เพื่อตรวจรายละเอียด",
                latest_success or "",
            )
        if status == "syncing":
            return ("กำลังอ่านข้อมูล", "ระบบกำลังอ่าน Meter ของเครื่องนี้", "#1769AA", "รอผลการอ่าน", latest_success or "")
        if not latest_success:
            return (
                "รอรอบแรก",
                "ยังไม่มีการอ่าน Web Meter ที่สำเร็จในรอบนี้",
                "#64748B",
                self._next_poll_for_device(device, now, snmp_minutes),
                "",
            )
        return (
            "ปกติ",
            f"Web Meter ล่าสุด {self._display_time(latest_success)}",
            C_GREEN,
            self._next_poll_for_device(device, now, snmp_minutes),
            latest_success,
        )

    def refresh_status(self) -> None:
        now = datetime.now().astimezone()
        snmp_minutes = max(1, int(get_cfg("snmp_interval_minutes", "5") or 5))
        policy = self._policy()
        mode = schedule_mode_at(now.timetz().replace(tzinfo=None), policy)
        devices = self.repository.list(enabled_only=True)
        events = pipeline_log.snapshot(limit=2_000)
        rows: list[tuple[DeviceConfig, tuple[str, str, str, str, str]]] = []
        for device in devices:
            rows.append((device, self._status_for_device(device, self.cache.load(device.slot, date.today()), events, now, snmp_minutes)))
        issues = sum(
            status in {"เชื่อมต่อไม่ได้", "ต้องตรวจสอบ"}
            for _device, (status, *_rest) in rows
        )
        waiting = sum(
            status in {"รอรอบแรก", "กำลังอ่านข้อมูล"}
            for _device, (status, *_rest) in rows
        )
        if not devices:
            headline = "ยังไม่มีเครื่องที่เปิดใช้งาน · ไปที่ตั้งค่าเพื่อเพิ่มเครื่องพิมพ์"
            style = settings_styles.REFRESH_STATUS_STYLE
        elif issues:
            headline = f"ต้องตรวจสอบ {issues}/{len(devices)} เครื่อง · ดูคำแนะนำในแต่ละรายการด้านล่าง"
            style = settings_styles.REFRESH_STATUS_STYLE
        elif waiting:
            headline = f"กำลังเริ่มต้นการอ่าน · {waiting}/{len(devices)} เครื่องรอ Scheduler หรือกำลังอ่าน Meter"
            style = settings_styles.REFRESH_STATUS_STYLE_INACTIVE
        else:
            headline = f"ทุกเครื่องปกติ · {len(devices)} เครื่อง · Web Meter ล่าสุดตามรายการด้านล่าง"
            style = settings_styles.REFRESH_STATUS_STYLE_SUCCESS
        self.status_banner.setText(headline)
        self.status_banner.setStyleSheet(style)
        self.status_schedule.setText(
            f"ตอนนี้อยู่ในช่วง {mode} · SNMP ทุก {snmp_minutes} นาที · "
            "รายละเอียดแผนงานอยู่ที่แท็บ การทำงานอัตโนมัติ"
        )
        self._clear_layout(self.status_rows)
        from services.computer_names import snapshot_readers
        readers = snapshot_readers(get_db_path(), {d.slot: snapshot for d in devices
            if (snapshot := runtime_snapshots.get(d.slot)) is not None and snapshot.serial == d.serial})
        for device, (status, description, colour, next_action, _latest_success) in rows:
            card = QFrame()
            card.setStyleSheet(
                settings_styles.PIPELINE_LOG_REFRESH_STATUS
            )
            body = QHBoxLayout(card)
            body.setContentsMargins(15, 12, 14, 12)
            body.setSpacing(12)
            copy = QVBoxLayout()
            name = QLabel(f"{device.name}  ·  {device.host}")
            name.setFont(fnt(F_MD, True))
            copy.addWidget(name)
            detail = QLabel(description)
            detail.setWordWrap(True)
            detail.setStyleSheet(text_styles.label('#475569'))
            copy.addWidget(detail)
            provenance = readers.get(device.slot)
            text = (tr("ผล Web ที่แสดง อ่านโดย {name} · {at}", "Displayed Web reading by {name} · {at}").format(
                name=provenance['name'], at=self._display_time(provenance['at'])) if provenance else
                tr("ผู้อ่าน: ยังไม่มีหลักฐานระบุคอมต้นทาง", "Reader: source computer is not yet available"))
            reader_label = QLabel(text)
            reader_label.setTextFormat(Qt.TextFormat.PlainText)
            reader_label.setProperty('i18n_data', True)
            reader_label.setWordWrap(True)
            reader_label.setStyleSheet(text_styles.label('#475569'))
            if provenance:
                reader_label.setToolTip(provenance['origin'])
            copy.addWidget(reader_label)
            action = QLabel(next_action)
            action.setWordWrap(True)
            action.setStyleSheet(text_styles.label('#64748B'))
            copy.addWidget(action)
            body.addLayout(copy, 1)
            marker = QLabel(status)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setMinimumWidth(106)
            marker.setStyleSheet(text_styles.label(colour, font_weight='700', padding='7px 8px'))
            body.addWidget(marker)
            details_button = btn("ดูรายละเอียด", "outline")
            details_button.clicked.connect(lambda _checked=False, slot=device.slot: self._open_device_events(slot))
            body.addWidget(details_button)
            self.status_rows.addWidget(card)
        apply_language(self)

    @staticmethod
    def _clock(value: str, fallback: time) -> time:
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
            return time(hour, minute)
        except (TypeError, ValueError):
            return fallback

    def _policy(self) -> PollingPolicy:
        return PollingPolicy(
            web_interval=timedelta(minutes=max(1, int(get_cfg("web_interval_minutes", "15") or 15))),
            peak_web_interval=timedelta(
                minutes=max(1, int(get_cfg("peak_web_interval_minutes", "5") or 5))
            ),
            work_start=self._clock(get_cfg("work_start", "08:00") or "08:00", time(8, 0)),
            work_end=self._clock(get_cfg("work_end", "17:00") or "17:00", time(17, 0)),
            schedule_windows=load_schedule_windows(get_cfg("sync_schedule_windows", "")),
        )

    def _next_poll_text(self, now: datetime, snmp_minutes: int) -> str:
        events = pipeline_log.snapshot(limit=2_000)
        start_actions = {"เริ่มรอบตาม Schedule", "เริ่มรอบอ่านทันที"}
        lines: list[str] = []
        for device in self.repository.list(enabled_only=True):
            latest = next(
                (
                    event
                    for event in events
                    if event.device_slot == device.slot and event.action in start_actions
                ),
                None,
            )
            if latest is None:
                lines.append(f"{device.name}: รอ Scheduler เริ่มรอบแรก")
                continue
            due = datetime.fromisoformat(latest.at) + timedelta(minutes=snmp_minutes)
            if due <= now:
                lines.append(f"{device.name}: ถึงเวลาตรวจแล้ว กำลังรอ Timer/คิว")
            else:
                lines.append(f"{device.name}: SNMP รอบถัดไปประมาณ {due.strftime('%H:%M:%S')} น.")
        return " · ".join(lines) or "ยังไม่มีเครื่องที่เปิดใช้งาน"

    def refresh_timeline(self) -> None:
        now = datetime.now().astimezone()
        policy = self._policy()
        snmp_minutes = max(1, int(get_cfg("snmp_interval_minutes", "5") or 5))
        rows = build_daily_timeline(policy, snmp_minutes=snmp_minutes)
        mode = schedule_mode_at(now.timetz().replace(tzinfo=None), policy)
        self.timeline_status.setText(
            f"วันนี้ {now.strftime('%d/%m/%Y')} · ตอนนี้ {now.strftime('%H:%M:%S')} น. · โหมด {mode} · "
            f"SNMP ทุก {snmp_minutes} นาที"
        )
        self._render_schedule_band(rows, policy, now, snmp_minutes)
        self.next_poll_label.setText(self._next_poll_text(now, snmp_minutes))
        self.timeline_table.setRowCount(len(rows))
        current_clock = now.hour * 60 + now.minute
        for row, entry in enumerate(rows):
            values = (
                entry.time_range,
                entry.mode,
                entry.snmp,
                entry.web,
                entry.ram,
                entry.database,
                entry.note,
            )
            active = self._range_contains(entry.time_range, current_clock)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if active:
                    item.setBackground(QColor("#E8F7F0"))
                    if column in (0, 1):
                        item.setForeground(QColor(C_GREEN))
                elif row % 2:
                    item.setBackground(QColor("#F7F8FA"))
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignCenter if column in (0, 1) else Qt.AlignmentFlag.AlignLeft)
                    | Qt.AlignmentFlag.AlignVCenter
                )
                self.timeline_table.setItem(row, column, item)
        self.refresh_rules()
        apply_language(self)

    def _toggle_timeline_detail(self, visible: bool) -> None:
        self.timeline_table.setVisible(visible)
        self.timeline_technical.setVisible(visible)

    @staticmethod
    def _timeline_duration(label: str) -> int:
        if "–" not in label:
            return 1
        try:
            start_text, end_text = label.split("–", 1)
            start_hour, start_minute = (int(value) for value in start_text.split(":", 1))
            end_hour, end_minute = (int(value) for value in end_text.split(":", 1))
            return max(1, (end_hour * 60 + end_minute) - (start_hour * 60 + start_minute) + 1)
        except ValueError:
            return 1

    def _render_schedule_band(
        self,
        rows: tuple[DailyTimelineEntry, ...],
        policy: PollingPolicy,
        now: datetime,
        snmp_minutes: int,
    ) -> None:
        while self.schedule_band_layout.count():
            item = self.schedule_band_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        current_clock = now.hour * 60 + now.minute
        self.schedule_summary.setText(
            f"00:00 — 24:00 · SNMP ทุก {snmp_minutes} นาที · "
            f"Web ช่วงปกติทุก {int(policy.web_interval.total_seconds() // 60)} นาที"
        )
        peak_index = 0
        for entry in rows[1:]:
            active = self._range_contains(entry.time_range, current_clock)
            if entry.mode == "Normal":
                background, border, title = "#F1F5F9", "#CBD5E1", "Normal"
            elif entry.mode == "Peak":
                peak_index += 1
                title = "ช่วงเริ่มงาน" if peak_index == 1 else "ช่วงเลิกงาน"
                background, border = "#E8F0FE", "#B7CAE8"
            else:
                background, border, title = "#E8F7F0", "#A9D8BC", entry.mode
            if active:
                border = C_GREEN
            segment = QFrame()
            segment.setStyleSheet(
                settings_styles.pipeline_log_segment(background, border)
            )
            segment_layout = QVBoxLayout(segment)
            segment_layout.setContentsMargins(6, 6, 6, 6)
            segment_layout.setSpacing(2)
            span = QLabel(entry.time_range)
            span.setAlignment(Qt.AlignmentFlag.AlignCenter)
            span.setStyleSheet(text_styles.label('#475569', font_size='11px'))
            segment_layout.addWidget(span)
            name = QLabel(title)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setWordWrap(True)
            name.setFont(fnt(F_SM, True))
            segment_layout.addWidget(name)
            web = QLabel(entry.web.replace("เมื่อ Total เพิ่ม · ", "Web "))
            web.setAlignment(Qt.AlignmentFlag.AlignCenter)
            web.setWordWrap(True)
            web.setStyleSheet(text_styles.label('#475569', font_size='11px'))
            segment_layout.addWidget(web)
            self.schedule_band_layout.addWidget(segment, self._timeline_duration(entry.time_range))

    @staticmethod
    def _range_contains(label: str, minute: int) -> bool:
        if "–" not in label:
            return False
        start_text, end_text = label.split("–", 1)

        def parse(value: str) -> int:
            hour, minute_value = (int(part) for part in value.split(":", 1))
            return hour * 60 + minute_value

        try:
            return parse(start_text) <= minute <= parse(end_text)
        except ValueError:
            return False

    @staticmethod
    def _event_text(event: PipelineEvent) -> str:
        return " ".join(
            (event.device_name, event.host, event.stage, event.action, event.target, event.value, event.detail, event.status,
             event.computer_name, event.reader_name)
        ).lower()

    def refresh_live(self) -> None:
        selected_slot = self.device_filter.currentData()
        selected_stage = self.stage_filter.currentData()
        search = self.search.text().strip().lower()
        events = pipeline_log.snapshot(limit=2_000)
        signature = (
            len(events),
            events[0].sequence if events else 0,
            selected_slot,
            selected_stage,
            search,
        )
        if signature == self._last_live_signature:
            return
        self._last_live_signature = signature
        filtered = [
            event
            for event in events
            if (selected_slot is None or event.device_slot == selected_slot)
            and (
                selected_stage is None
                or (selected_stage == "RAM_DB" and event.stage in {"RAM", "DB"})
                or event.stage == selected_stage
            )
            and (not search or search in self._event_text(event))
        ][:750]
        self._visible_events = filtered
        self.live_table.setRowCount(len(filtered))
        for row, event in enumerate(filtered):
            try:
                display_time = datetime.fromisoformat(event.at).strftime("%d/%m %H:%M:%S")
            except ValueError:
                display_time = event.at.replace("T", " ")
            values = (
                display_time,
                event.device_name or "ระบบ",
                event.reader_name or '—',
                self._event_result(event),
                self._event_summary(event),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 3:
                    item.setForeground(QColor(self._event_colour(event)))
                self._align_log_item(item, row, centered=column == 3)
                self.live_table.setItem(row, column, item)
        self.live_count.setText(
            f"แสดง {len(filtered):,} / {len(events):,} เหตุการณ์ล่าสุด · แถวใหม่อยู่ด้านบน · "
            "คลิกแถวเพื่อดูรายละเอียดเทคนิค"
        )
        if not filtered:
            self.live_detail.clear()
        apply_language(self)

    @staticmethod
    def _event_result(event: PipelineEvent) -> str:
        labels = {
            "ok": "สำเร็จ",
            "error": "ไม่สำเร็จ",
            "warning": "ต้องตรวจสอบ",
            "request": "กำลังอ่าน",
            "skip": "ข้ามรอบ",
        }
        return labels.get(event.status, "ข้อมูลระบบ")

    @staticmethod
    def _event_colour(event: PipelineEvent) -> str:
        return {
            "ok": C_GREEN,
            "error": C_RED,
            "warning": "#B54708",
            "request": "#1769AA",
            "skip": C_TEXT2,
        }.get(event.status, C_TEXT2)

    @staticmethod
    def _event_summary(event: PipelineEvent) -> str:
        if event.diagnostic:
            from services.support_diagnostics import diagnose
            diagnostic = diagnose(event.diagnostic)
            return f'{event.action} · {diagnostic.summary} [{diagnostic.error_code} / {diagnostic.code}]'
        summary = event.action
        if event.value and event.value not in {"—", "None"}:
            summary += f" · {event.value}"
        elif event.detail:
            summary += f" · {event.detail}"
        return summary

    def _show_live_detail(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self._visible_events):
            return
        event = self._visible_events[row]
        self.live_detail.setPlainText(
            "\n".join(
                (
                    f"เวลา: {event.at}",
                    f"เครื่อง: {event.device_name or 'ระบบ'} {event.host}".strip(),
                    f"คอมที่ทำรายการ: {event.computer_name or '—'}",
                    f"อ่านโดย: {event.reader_name or '—'}",
                    f"Stage: {event.stage}",
                    f"Action: {event.action}",
                    f"Target: {event.target or '—'}",
                    f"Value: {event.value or '—'}",
                    f"Detail: {event.detail or '—'}",
                    event.diagnostic,
                )
            )
        )

    def _copy_live(self) -> None:
        # A copied failure includes the same full evidence as its detail pane.
        from services.support_diagnostics import safe_text
        rows = ["เวลา\tเครื่องพิมพ์\tคอมที่ทำรายการ\tอ่านโดย\tผลลัพธ์\tรายละเอียด"]
        for event in self._visible_events:
            try:
                stamp = datetime.fromisoformat(event.at).strftime("%d/%m %H:%M:%S")
            except ValueError:
                stamp = event.at.replace("T", " ")
            rows.append(
                "\t".join((stamp, event.device_name or "ระบบ", event.computer_name or '—', event.reader_name or '—',
                           self._event_result(event), self._event_summary(event)))
            )
            rows.append(safe_text(f'Stage: {event.stage}\nTarget: {event.target}\nValue: {event.value}\nDetail: {event.detail}'))
            if event.diagnostic:
                rows.append(event.diagnostic)
        QApplication.clipboard().setText("\n".join(rows))

    def _clear_live(self) -> None:
        choice = QMessageBox.question(
            self,
            "ล้าง Live Log",
            "ล้างเฉพาะเหตุการณ์ของรอบที่เปิดโปรแกรมนี้\nไม่กระทบ Meter, Cache หรือ Billing",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        pipeline_log.clear()
        pipeline_log.append(stage="POLICY", action="ล้าง Live Log", target="RAM ring buffer", status="info")
        self._last_live_signature = None
        self.refresh_live()

    @staticmethod
    def _total(payload: dict | None, section: str) -> object:
        values = (payload or {}).get(section, {})
        return values.get("counter.total.total", values.get("counter.total.print_page_total", "—"))

    def refresh_cache(self) -> None:
        devices = self.repository.list(enabled_only=True)
        today = date.today()
        self.cache_table.setRowCount(len(devices))
        with _open(commit=False) as conn:
            latest_rows = {
                device.slot: conn.execute(
                    """SELECT record_date,sample_count,error_count,incomplete,last_success
                       FROM daily_meter_records WHERE device_slot=?
                       ORDER BY record_date DESC LIMIT 1""",
                    (device.slot,),
                ).fetchone()
                for device in devices
            }
        for row, device in enumerate(devices):
            state = self.cache.load(device.slot, today)
            db_row = latest_rows.get(device.slot)
            if state:
                first_last = f"{state.get('first_success') or '—'}\n{state.get('last_success') or '—'}"
                cache_status = f"{state.get('last_status', 'pending')} · RAM+disk"
                record_date = state.get("record_date", today.isoformat())
                heartbeat_count = state.get("heartbeat_count", 0)
                sample_count = state.get("sample_count", 0)
                error_count = state.get("error_count", 0)
            else:
                first_last = "—"
                cache_status = "ยังไม่มี Cache วันนี้"
                record_date = today.isoformat()
                heartbeat_count = sample_count = error_count = 0
            if db_row:
                db_last = f"{db_row[0]} · {db_row[1]} Web"
                db_state = "Packed วันนี้" if db_row[0] == today.isoformat() else (
                    "วันนี้ยังพักใน Cache (ปกติ)" if state else "รอข้อมูลวันนี้"
                )
                if db_row[3]:
                    db_state += " · incomplete"
            else:
                db_last = "ยังไม่มี Daily Record"
                db_state = "วันนี้ยังพักใน Cache" if state else "รอการอ่านสำเร็จ"
            values = (
                f"{device.name}\n{device.host}",
                str(record_date),
                str(heartbeat_count),
                str(sample_count),
                str(self._total(state, "opening")),
                str(self._total(state, "latest")),
                str(self._total(state, "delta")),
                get_cfg(f"snmp_total_oid_{device.slot}", "ยังไม่ Calibrate") or "ยังไม่ Calibrate",
                str(error_count),
                first_last,
                cache_status,
                db_last,
                db_state,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._align_log_item(item, row, centered=column in (1, 2, 3, 8))
                self.cache_table.setItem(row, column, item)
        apply_language(self)

    def refresh_rules(self) -> None:
        work_start = get_cfg("work_start", "08:00") or "08:00"
        work_end = get_cfg("work_end", "17:00") or "17:00"
        rules = (
            ("SNMP heartbeat", f"ทุก {get_cfg('snmp_interval_minutes', '5')} นาที", "อ่าน Total/Model/Serial และเพิ่ม heartbeat_count"),
            ("SNMP Total OID", "Auto-calibrate แยกรุ่น/เครื่อง", "เทียบ SNMP candidates กับ Web counter.total.total; ตรงกันแล้วจึงจำ OID"),
            ("Total ไม่เพิ่ม", "ไม่เรียก Web", "เก็บสถานะ Online และค่าล่าสุดไว้"),
            ("Total เพิ่ม", f"Web throttle {get_cfg('web_interval_minutes', '15')} นาที", "อ่าน Full Counter แล้วเพิ่ม sample_count"),
            ("Peak window", f"{work_start} / {work_end} ±30 นาที", f"ลด Web throttle เหลือ {get_cfg('peak_web_interval_minutes', '5')} นาที"),
            ("SNMP ไม่ตอบ", "Web fallback 5 ครั้ง", "ห่างครั้งละ 5 นาที แล้วเป็น Offline"),
            ("Offline", "ยัง probe SNMP ทุก 5 นาที", "จำกัด Web probe ซ้ำประมาณ 1 ชั่วโมง"),
            ("RAM / Daily Cache", "atomic JSON แยกเครื่อง/วัน", "เก็บ opening, latest, delta, counts และ errors"),
            ("เปลี่ยนวัน", "1 Daily Record / เครื่อง / วัน", "commit DB สำเร็จแล้วจึงลบ Cache วันเก่า"),
            ("ปิดโปรแกรม/เครื่องก่อนจบวัน", "ใช้ค่าล่าสุด", "Daily Record ระบุ incomplete; ไม่ประมาณค่าที่หาย"),
        )
        self.rules_table.setRowCount(len(rules))
        for row, values in enumerate(rules):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._align_log_item(item, row)
                self.rules_table.setItem(row, column, item)
