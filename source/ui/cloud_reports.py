from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from html import escape

from PyQt6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PyQt6.QtCore import QDate, QEvent, QMargins, QPointF, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from i18n import apply_language
from services.legacy_history_import import build_legacy_usage_intervals
from services.report_operation_breakdown import (
    breakdown_from_raw_records,
    raw_operation_label,
)
from widgets import FrozenLeftTable, VisibleCheckBox

NAVY = "#123262"
BLUE = "#1677C8"
ORANGE = "#E58A18"
CYAN = "#16A6C7"
SLATE = "#56677A"
GREEN = "#16805A"
LINE = "#D9E2EA"
MUTED = "#66788A"
PANEL = "#FFFFFF"
DEVICE_COLORS = (BLUE, ORANGE, "#D65364")
COPY_COLORS = (ORANGE, "#7C3AED", "#64748B")

USAGE_METRICS = (
    ("print_a3_color", "Print A3 Color", "print"),
    ("print_a3_bw", "Print A3 B&W", "print"),
    ("print_a4_color", "Print A4 Color", "print"),
    ("print_a4_bw", "Print A4 B&W", "print"),
    ("print_other", "Print Other", "print"),
    ("copy_a3_color", "Copy A3 Color", "copy"),
    ("copy_a3_bw", "Copy A3 B&W", "copy"),
    ("copy_a4_color", "Copy A4 Color", "copy"),
    ("copy_a4_bw", "Copy A4 B&W", "copy"),
    ("copy_other", "Copy Other", "copy"),
    ("scan", "Scan", "always"),
    ("total", "รวม", "always"),
    ("cost", "ค่าใช้จ่ายโดยประมาณ", "cost"),
)

USAGE_GROUPS = (
    ("Print", 5, "#DDF4E4"),
    ("Copy", 5, "#DCEFF8"),
    ("Scan", 1, "#DDEAF8"),
    ("รวม", 1, "#FBE8DC"),
    ("ค่าใช้จ่าย", 1, "#F3DDF3"),
)

USAGE_SUBLABELS = (
    "A3 Color",
    "A3 B&W",
    "A4 Color",
    "A4 B&W",
    "Other",
    "A3 Color",
    "A3 B&W",
    "A4 Color",
    "A4 B&W",
    "Other",
    "หน้า",
    "หน้า",
    "บาท",
)


class CalendarDateEdit(QDateEdit):
    """A date field whose full surface opens the calendar popup.

    Native QDateEdit only opens its calendar from the narrow drop-down arrow;
    customers understandably click the date text itself.  Forwarding a left
    click to the native drop-down sub-control keeps the platform calendar and
    all built-in date validation while removing the typing-first behaviour.
    """

    def _popup_event(self, event: QMouseEvent) -> QMouseEvent:
        local = QPointF(max(1, self.width() - 6), self.height() / 2)
        global_position = QPointF(self.mapToGlobal(local.toPoint()))
        return QMouseEvent(
            event.type(),
            local,
            global_position,
            event.button(),
            event.buttons(),
            event.modifiers(),
            event.pointingDevice(),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.calendarPopup():
            super().mousePressEvent(self._popup_event(event))
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.calendarPopup():
            super().mouseReleaseEvent(self._popup_event(event))
            return
        super().mouseReleaseEvent(event)

    def open_calendar(self) -> None:
        """Open the native popup from the adjacent visible calendar button."""
        local = QPointF(self.rect().center())
        global_position = QPointF(self.mapToGlobal(local.toPoint()))
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            local,
            global_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            local,
            global_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.mousePressEvent(press)
        self.mouseReleaseEvent(release)


def _number(value: float | int) -> str:
    return f"{value:,.0f}"


def _money(value: float | int) -> str:
    return f"{value:,.2f}"


def _combined(record, name: str) -> float:
    return float(getattr(record, name, 0) or 0) + float(
        getattr(record, f"provisional_{name}", 0) or 0
    )


def _record_total(record) -> float:
    explicit = _combined(record, "total")
    if explicit:
        return explicit
    return sum(
        _combined(record, name)
        for name in ("a3_color", "a4_color", "a3_bw", "a4_bw")
    )


def _operation_total(record, operation: str) -> float:
    return sum(
        _combined(record, f"{operation}_{suffix}")
        for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
    )


def _operation_available(record, operation: str) -> bool:
    return bool(getattr(record, f"{operation}_available", False)) or any(
        _combined(record, f"{operation}_{suffix}")
        for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
    )


def _record_identity(record) -> str:
    identity = str(getattr(record, "device_identity", "") or "").strip()
    return identity or f"slot:{int(getattr(record, 'device_slot', 0))}"


def _record_name(record, devices_by_slot: dict[int, object]) -> str:
    snapshot = str(getattr(record, "device_name_snapshot", "") or "").strip()
    slot = int(getattr(record, "device_slot", 0))
    device = devices_by_slot.get(slot)
    return snapshot or str(getattr(device, "name", "") or f"MFP {slot + 1}")


def _chart_printer_name(value: str) -> str:
    """Keep chart legends compact while the table retains the full device name."""
    name = str(value).strip()
    for prefix in ("KONICA MINOLTA bizhub ", "KM bizhub ", "bizhub "):
        if name.casefold().startswith(prefix.casefold()):
            name = name[len(prefix) :].strip()
            break
    return name if len(name) <= 20 else f"{name[:19]}…"


class _CloudOverviewMetricCard(QFrame):
    """Overview summary card styled to match the operational Overview page."""

    def __init__(self, title: str, *, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cloud_overview_metric_card")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(8)

        content = QWidget()
        content.setObjectName("cloud_overview_metric_content")
        content.setMinimumWidth(0)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(1)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("cloud_overview_metric_title")
        self.lbl_detail = QLabel("")
        self.lbl_detail.setObjectName("cloud_overview_metric_detail")
        self.lbl_detail.setWordWrap(False)
        content_layout.addWidget(self.lbl_title)
        content_layout.addWidget(self.lbl_detail)

        self.lbl_val = QLabel("—")
        self.lbl_val.setObjectName("cloud_overview_metric_value")
        self.lbl_val.setStyleSheet(f"color:{accent};background:transparent;border:0;")
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(content, 1)
        layout.addWidget(self.lbl_val)

    def set_metric(self, value: str, detail: str = "", *, available: bool = True) -> None:
        self.lbl_val.setText(value if available else "—")
        self._set_detail(detail if available else "ไม่มี Counter แยกประเภท")

    def _set_detail(self, detail: str) -> None:
        """Keep A3/A4 labels muted while preserving their values as readable data."""
        prefix, separator, suffix = detail.partition("  |  ")
        if prefix.startswith("A3 ") and separator and suffix.startswith("A4 "):
            a3_value = escape(prefix[3:])
            a4_value = escape(suffix[3:])
            self.lbl_detail.setTextFormat(Qt.TextFormat.RichText)
            self.lbl_detail.setText(
                "<span style='color:#64748B'>A3</span> "
                f"<span style='color:#111827'>{a3_value}</span>"
                "<span style='color:#94A3B8'>  |  </span>"
                "<span style='color:#64748B'>A4</span> "
                f"<span style='color:#111827'>{a4_value}</span>"
            )
            return
        self.lbl_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_detail.setText(detail)


def _table(
    headers: tuple[str, ...],
    *,
    text_columns: tuple[int, ...] = (0,),
) -> QTableWidget:
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    # The global application QSS applies a different paint path to alternate
    # rows, which adds an unwanted left inset on macOS. Reports prioritises
    # stable column edges over zebra striping.
    table.setAlternatingRowColors(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    table.horizontalHeader().setMinimumSectionSize(58)
    table._cloud_text_columns = frozenset(text_columns)
    for column in range(len(headers)):
        table.horizontalHeader().setSectionResizeMode(
            column,
            QHeaderView.ResizeMode.Stretch
            if column == 0
            else QHeaderView.ResizeMode.ResizeToContents,
        )
        header = table.horizontalHeaderItem(column)
        if header is not None:
            alignment = (
                Qt.AlignmentFlag.AlignLeft
                if column in table._cloud_text_columns
                else Qt.AlignmentFlag.AlignRight
            )
            header.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
    return table


def _panel(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("cloud_report_panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    head = QHBoxLayout()
    text = QVBoxLayout()
    heading = QLabel(title)
    heading.setObjectName("cloud_panel_title")
    text.addWidget(heading)
    if subtitle:
        detail = QLabel(subtitle)
        detail.setObjectName("cloud_panel_subtitle")
        detail.setWordWrap(True)
        text.addWidget(detail)
    head.addLayout(text)
    head.addStretch()
    layout.addLayout(head)
    return frame, layout


class CloudReportsWidget(QWidget):
    """Cloud-style presentation for truthful KOMI counter data.

    The widget only presents records supplied by PageHistoryV5. It never reads,
    writes, reconciles, or posts billing data by itself.
    """

    refresh_requested = pyqtSignal()
    export_requested = pyqtSignal()
    period_changed = pyqtSignal(object)
    reading_status_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: tuple = ()
        self._daily_records: tuple = ()
        self._usage_daily_records: tuple = ()
        self._monthly_records: tuple = ()
        self._subjects: tuple = ()
        self._devices: tuple = ()
        self._legacy_history: tuple = ()
        self._legacy_usage_records: tuple = ()
        self._raw_counter_records: tuple = ()
        self._period: tuple[str, str] | None = None
        self._last_sync_at: str | None = None
        self._selected_user: str | None = None
        self._selected_printer: str | None = None
        self._user_rows: list[dict] = []
        self._printer_rows: list[dict] = []
        self._usage_selected_slots: set[int] = set()
        self.usage_device_filters: dict[int, VisibleCheckBox] = {}
        self._build()

    def _build(self) -> None:
        self.setObjectName("cloud_reports")
        self.setStyleSheet(
            f"QWidget#cloud_reports{{background:#F3F6F8;color:#243244;}}"
            "QWidget#cloud_reports QLabel{background:transparent;border:none;}"
            f"QFrame#cloud_report_toolbar,QFrame#cloud_report_panel,QFrame#cloud_kpi{{"
            f"background:{PANEL};border:1px solid {LINE};border-radius:7px;}}"
            "QLabel#cloud_title{font-size:25px;font-weight:800;color:#25364A;}"
            f"QLabel#cloud_subtitle,QLabel#cloud_panel_subtitle{{color:{MUTED};font-size:12px;}}"
            "QLabel#cloud_panel_title{font-size:15px;font-weight:750;color:#25364A;}"
            f"QLabel#cloud_kpi_caption{{color:{MUTED};font-size:12px;}}"
            "QLabel#cloud_kpi_value{font-size:24px;font-weight:800;}"
            f"QLabel#cloud_kpi_note{{color:{MUTED};font-size:10px;}}"
            f"QFrame#cloud_overview_kpi_panel{{background:{PANEL};border:1px solid {LINE};border-radius:12px;}}"
            "QFrame#cloud_overview_metric_card{background:#FFFFFF;border:1px solid #D7E0EA;border-radius:9px;}"
            "QWidget#cloud_overview_metric_content{background:transparent;border:none;}"
            "QLabel#cloud_overview_metric_title{color:#25364A;font-size:15px;font-weight:750;}"
            f"QLabel#cloud_overview_metric_detail{{color:{MUTED};font-size:11px;}}"
            "QLabel#cloud_overview_metric_value{font-size:24px;font-weight:800;}"
            "QTabWidget#cloud_report_tabs::pane{border:0;background:transparent;}"
            f"QTabBar::tab{{background:transparent;color:{MUTED};padding:10px 24px;"
            f"border-bottom:3px solid transparent;font-weight:700;}}"
            f"QTabBar::tab:selected{{color:{NAVY};border-bottom:3px solid {ORANGE};}}"
            f"QTableWidget{{background:white;border:1px solid {LINE};gridline-color:#E8EDF2;"
            "alternate-background-color:#F7F9FB;selection-background-color:#E8F2FB;"
            "selection-color:#203247;}"
            "QTableWidget::item{padding:8px 10px;}"
            "QHeaderView::section{background:#F1F4F7;color:#526476;border:0;"
            "border-bottom:1px solid #D9E2EA;padding:8px 10px 8px 1px;font-weight:700;}"
            "QLabel#cloud_period_label{color:#526476;font-size:11px;font-weight:700;}"
            "QDateEdit#cloud_period_date{background:white;color:#243244;border:1px solid #B9CBDD;"
            "border-radius:6px;padding:8px 10px;min-width:132px;font-weight:700;}"
            f"QDateEdit#cloud_period_date:hover,QDateEdit#cloud_period_date:focus{{border-color:{BLUE};}}"
            "QDateEdit#cloud_period_date::drop-down{border:0;width:24px;}"
            f"QPushButton#cloud_primary{{background:{BLUE};color:white;border:0;border-radius:5px;"
            "padding:9px 14px;font-weight:700;}"
            f"QPushButton#cloud_export{{background:white;color:{NAVY};border:1px solid #B9CBDD;"
            "border-radius:5px;padding:9px 14px;font-weight:700;}"
            f"QPushButton#cloud_export:hover{{background:#EEF5FB;border-color:{BLUE};}}"
            f"QPushButton#cloud_reset{{background:#EEF3F7;color:{NAVY};border:1px solid {LINE};"
            "border-radius:5px;padding:7px 11px;font-weight:700;}"
            f"QPushButton#cloud_calendar_button{{background:#EEF5FB;color:{NAVY};"
            f"border:1px solid #B9CBDD;border-radius:6px;min-width:34px;"
            "padding:7px 5px;font-size:16px;}"
            f"QPushButton#cloud_granularity{{background:#EEF3F7;color:{NAVY};border:1px solid {LINE};"
            "border-radius:5px;min-width:30px;padding:6px 8px;font-weight:800;}"
            f"QPushButton#cloud_granularity:checked{{background:{NAVY};color:white;border-color:{NAVY};}}"
            f"QLabel#cloud_filter_badge{{background:#FFF2DE;color:#95570A;border:1px solid #F2D09B;"
            "border-radius:11px;padding:5px 9px;font-weight:700;}"
            "QLabel#cloud_error{background:#FFF0F1;color:#A61D2D;border:1px solid #F1BBC1;"
            "border-radius:5px;padding:9px 12px;font-weight:700;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 18)
        root.setSpacing(12)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Reports")
        title.setObjectName("cloud_title")
        title_box.addWidget(title)
        subtitle = QLabel("ภาพรวมการใช้งานจากเครื่องพิมพ์ทั้งหมด")
        subtitle.setObjectName("cloud_subtitle")
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch()
        self.updated_label = QLabel("กำลังอ่านข้อมูลล่าสุด…")
        self.updated_label.setObjectName("cloud_subtitle")
        self.updated_label.setMinimumWidth(100)
        self.updated_label.setMaximumWidth(170)
        self.updated_label.setWordWrap(True)
        self.updated_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.updated_label)
        self.export_button = QPushButton("ส่งออก Excel")
        self.export_button.setObjectName("cloud_export")
        self.export_button.setAccessibleName("ส่งออกรายงานเป็นไฟล์ Excel")
        self.export_button.clicked.connect(self.export_requested.emit)
        heading.addWidget(self.export_button)
        self.refresh_button = QPushButton("รีเฟรช")
        self.refresh_button.setObjectName("cloud_primary")
        self.refresh_button.setAccessibleName("รีเฟรชข้อมูลรายงาน")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self.refresh_button)
        root.addLayout(heading)

        self.error_label = QLabel("")
        self.error_label.setObjectName("cloud_error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("cloud_report_tabs")
        self.period_edit_pairs: list[tuple[QDateEdit, QDateEdit]] = []
        self.overview_page = self._build_overview()
        self.users_page = self._build_users()
        self.printers_page = self._build_printers()
        self.usage_page = self._build_usage()
        self.legacy_raw_page = self._build_legacy_raw()
        self.legacy_history_page = self._build_legacy_history()
        self.tabs.addTab(self.overview_page, "Overview")
        self.tabs.addTab(self.users_page, "Users")
        self.tabs.addTab(self.printers_page, "Printers")
        self.tabs.addTab(self.usage_page, "Usage")
        self.tabs.addTab(self.legacy_raw_page, "Legacy")
        self.tabs.currentChanged.connect(self._render_selected_tab)
        root.addWidget(self.tabs, 1)

    def _build_overview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
        self.overview_kpi_panel = QFrame()
        self.overview_kpi_panel.setObjectName("cloud_overview_kpi_panel")
        kpis = QGridLayout(self.overview_kpi_panel)
        kpis.setContentsMargins(12, 12, 12, 12)
        kpis.setHorizontalSpacing(12)
        kpis.setVerticalSpacing(10)
        self.overview_kpis = {
            "color_print": _CloudOverviewMetricCard("พิมพ์สี", accent=BLUE),
            "bw_print": _CloudOverviewMetricCard("พิมพ์ขาวดำ", accent="#18202C"),
            "total_usage": _CloudOverviewMetricCard("ยอดใช้งานรวม", accent=BLUE),
            "color_copy": _CloudOverviewMetricCard("สำเนาสี", accent="#F25C05"),
            "bw_copy": _CloudOverviewMetricCard("สำเนาขาวดำ", accent="#56677A"),
            "total_cost": _CloudOverviewMetricCard(
                "ค่าใช้จ่ายสุทธิ", accent="#00A651"
            ),
        }
        for index, key in enumerate(
            ("color_print", "bw_print", "total_usage", "color_copy", "bw_copy", "total_cost")
        ):
            row, column = divmod(index, 3)
            kpis.addWidget(self.overview_kpis[key], row, column)
        for column in range(3):
            kpis.setColumnStretch(column, 1)
        layout.addWidget(self.overview_kpi_panel)
        grid = QGridLayout()
        grid.setSpacing(12)
        trend, trend_layout = _panel("Print / Copy timeline", "แสดงรายวันเมื่อมี Daily record")
        self.overview_trend = self._chart_view()
        trend_layout.addWidget(self.overview_trend)
        grid.addWidget(trend, 0, 0)
        mix, mix_layout = _panel("Color, B&W และ Scan", "สัดส่วนยอดในช่วงที่เลือก")
        self.overview_mix = self._chart_view()
        mix_layout.addWidget(self.overview_mix)
        grid.addWidget(mix, 0, 1)
        users, users_layout = _panel("Top users", "ยอดจาก User Authentication / Account Track")
        self.overview_users = _table(
            ("User / Account", "ประเภท", "หน้า"), text_columns=(0, 1)
        )
        self.overview_users.setFixedHeight(190)
        users_layout.addWidget(self.overview_users)
        grid.addWidget(users, 1, 0)
        printers, printers_layout = _panel("Top printers", "ยอดตาม Physical identity ของเครื่อง")
        self.overview_printers = _table(
            ("เครื่องพิมพ์", "Print", "Copy", "Scan", "รวม")
        )
        self.overview_printers.setFixedHeight(190)
        printers_layout.addWidget(self.overview_printers)
        grid.addWidget(printers, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return page

    def _build_users(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
        self.user_kpis, kpis = self._kpi_row(
            (
                ("count", "ผู้ใช้ที่มีข้อมูล", "คน", NAVY),
                ("print", "Print", "หน้า", BLUE),
                ("copy", "Copy", "หน้า", ORANGE),
                ("usage", "ยอดใช้งานรวม", "หน้า", SLATE),
                ("highest", "ผู้ใช้สูงสุด", "หน้า", GREEN),
            )
        )
        layout.addLayout(kpis)
        filter_row = QHBoxLayout()
        self.user_filter_badge = QLabel("เลือกผู้ใช้จากตารางเพื่อกรองกราฟ")
        self.user_filter_badge.setObjectName("cloud_filter_badge")
        filter_row.addWidget(self.user_filter_badge)
        filter_row.addStretch()
        reset = QPushButton("ล้างตัวกรอง")
        reset.setObjectName("cloud_reset")
        reset.clicked.connect(self._clear_user_filter)
        filter_row.addWidget(reset)
        self.user_recovery_button = QPushButton("ดูสถานะการอ่าน")
        self.user_recovery_button.setObjectName("cloud_reset")
        self.user_recovery_button.clicked.connect(self.reading_status_requested)
        filter_row.addWidget(self.user_recovery_button)
        layout.addLayout(filter_row)
        charts = QHBoxLayout()
        top, top_layout = _panel("Top users", "เรียงตามยอดใช้งานในช่วงที่เลือก")
        self.users_top_chart = self._chart_view()
        top_layout.addWidget(self.users_top_chart)
        charts.addWidget(top, 1)
        printer, printer_layout = _panel("Printers used", "กดผู้ใช้เพื่อดูการกระจายตามเครื่อง")
        self.users_printer_chart = self._chart_view()
        printer_layout.addWidget(self.users_printer_chart)
        charts.addWidget(printer, 1)
        layout.addLayout(charts)
        table_panel, table_layout = _panel(
            "Users",
            "ข้อมูล RAM ใช้เพื่อวิเคราะห์การกระจาย ไม่ใช้คำนวณค่าใช้จ่าย",
        )
        self.users_table = FrozenLeftTable()
        self.users_table._row_h = 34
        self.users_table._cloud_text_columns = frozenset((0,))
        for table in (self.users_table._left, self.users_table._right):
            table.verticalHeader().setDefaultSectionSize(34)
            table.setAlternatingRowColors(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.users_table.setMinimumHeight(220)
        self.users_table.setMaximumHeight(360)
        self.users_table._left.currentCellChanged.connect(
            lambda row, column, _previous_row, _previous_column: self._select_user_row(
                row, column, toggle=False
            )
        )
        table_layout.addWidget(self.users_table)
        layout.addWidget(table_panel)
        return page

    def _build_printers(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
        self.printer_kpis, kpis = self._kpi_row(
            (
                ("count", "เครื่องที่มีการใช้งาน", "เครื่อง", NAVY),
                ("print", "Print", "หน้า", BLUE),
                ("copy", "Copy", "หน้า", ORANGE),
                ("scan", "Scan", "หน้า", SLATE),
                ("cost", "ค่าใช้จ่ายสุทธิ", "บาท", GREEN),
            )
        )
        layout.addLayout(kpis)
        self.printer_compare_note = QLabel(
            "กราฟเปรียบเทียบเครื่องพิมพ์ทุกเครื่องพร้อมกัน · คลิกแถวด้านล่างเพื่อดู Meter detail"
        )
        self.printer_compare_note.setObjectName("cloud_subtitle")
        layout.addWidget(self.printer_compare_note)
        charts = QHBoxLayout()
        trend, trend_layout = _panel("Usage timeline", "เปรียบเทียบยอดรายวันของทุกเครื่อง")
        self.printer_trend = self._chart_view()
        trend_layout.addWidget(self.printer_trend)
        charts.addWidget(trend, 3)
        mix, mix_layout = _panel(
            "Print / Copy / Scan", "แยกประเภทงานรายเครื่องตาม Counter ที่เครื่องส่ง"
        )
        self.printer_mix = self._chart_view()
        mix_layout.addWidget(self.printer_mix)
        charts.addWidget(mix, 2)
        layout.addLayout(charts)
        bottom = QHBoxLayout()
        list_panel, list_layout = _panel("Printers", "คลิกชื่อเครื่องเพื่อดูรายละเอียด โดยกราฟยังแสดงทุกเครื่อง")
        self.printers_table = _table(
            ("เครื่องพิมพ์", "สถานะ", "Print", "Copy", "Scan", "รวม", "ค่าใช้จ่าย"),
            text_columns=(0, 1),
        )
        self.printers_table.setMinimumHeight(210)
        self.printers_table.setMaximumHeight(340)
        self.printers_table.currentCellChanged.connect(
            lambda row, column, _previous_row, _previous_column: self._select_printer_row(
                row, column
            )
        )
        list_layout.addWidget(self.printers_table)
        bottom.addWidget(list_panel, 3)
        detail_panel, detail_layout = _panel("Meter detail", "ค่าล่าสุดสำหรับเครื่องที่เลือก")
        self.printer_detail = _table(("รายการ", "ค่า"), text_columns=(0,))
        self.printer_detail.setMinimumHeight(210)
        self.printer_detail.setMaximumHeight(340)
        self.printer_detail.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        detail_layout.addWidget(self.printer_detail)
        bottom.addWidget(detail_panel, 2)
        layout.addLayout(bottom)
        return page

    def _build_usage(self) -> QWidget:
        """Show recorded usage at daily, monthly, or yearly level."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        panel = QFrame()
        panel.setObjectName("cloud_report_panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        heading = QLabel("Usage")
        heading.setObjectName("cloud_panel_title")
        head.addWidget(heading)
        head.addStretch()
        self.usage_waste_checkbox = VisibleCheckBox("คิดรวม % กระดาษเสีย")
        self.usage_waste_checkbox.setChecked(True)
        self.usage_waste_checkbox.setAccessibleName(
            "คิดค่าใช้จ่ายหลังรวมเปอร์เซ็นต์กระดาษเสีย"
        )
        self.usage_waste_checkbox.setToolTip(
            "เปิด: ใช้ยอดสุทธิหลังคิด % กระดาษเสียจาก Billing Ledger\n"
            "ปิด: ใช้ยอดก่อนคิด % กระดาษเสีย โดยจำนวนหน้าไม่เปลี่ยน"
        )
        self.usage_waste_checkbox.toggled.connect(self._set_waste_adjustment)
        head.addWidget(self.usage_waste_checkbox)
        view_label = QLabel("มุมมอง")
        view_label.setObjectName("cloud_panel_subtitle")
        head.addWidget(view_label)
        self.usage_granularity = "M"
        self.usage_granularity_buttons: dict[str, QPushButton] = {}
        for code, tooltip in (("D", "รายวัน"), ("M", "รายเดือน"), ("Y", "รายปี")):
            button = QPushButton(code)
            button.setObjectName("cloud_granularity")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setChecked(code == self.usage_granularity)
            button.clicked.connect(lambda checked, value=code: self._set_usage_granularity(value, checked))
            head.addWidget(button)
            self.usage_granularity_buttons[code] = button
        panel_layout.addLayout(head)
        self.usage_timeline_chart = self._chart_view()
        panel_layout.addWidget(self.usage_timeline_chart)
        self.usage_tabs = QTabWidget()
        self.usage_tabs.setObjectName("cloud_usage_tabs")
        self.usage_tabs.tabBar().setExpanding(False)

        all_devices_page = QWidget()
        all_devices_layout = QVBoxLayout(all_devices_page)
        all_devices_layout.setContentsMargins(0, 0, 0, 0)
        self.usage_device_filter_layout = QHBoxLayout()
        self.usage_device_filter_layout.addStretch()
        all_devices_layout.addLayout(self.usage_device_filter_layout)
        self.usage_monthly_table = FrozenLeftTable()
        self.usage_monthly_table._row_h = 34
        self.usage_monthly_table.setColumnCount(1 + len(USAGE_METRICS))
        self.usage_monthly_table.setHorizontalHeaderLabels(
            ("เดือน", *(label for _field, label, _availability in USAGE_METRICS))
        )
        self.usage_monthly_table._cloud_text_columns = frozenset((0,))
        for table in (
            self.usage_monthly_table._left,
            self.usage_monthly_table._right,
        ):
            table.setAlternatingRowColors(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.usage_monthly_table.setColumnWidth(0, 108)
        for column, (_field, _label, availability) in enumerate(USAGE_METRICS, start=1):
            self.usage_monthly_table.setColumnWidth(
                column, 190 if availability == "cost" else 128
            )
        self.usage_monthly_table.setGroupedHeader(
            "เดือน",
            USAGE_GROUPS,
            USAGE_SUBLABELS,
        )
        self.usage_monthly_table.setGroupSeparators(
            (5, 10, 11, 12),
            color="#CBD5E1",
            width=1,
        )
        all_devices_layout.addWidget(self.usage_monthly_table, 1)
        self.usage_tabs.addTab(all_devices_page, "ทุกเครื่อง")

        per_printer_page = QWidget()
        per_printer_layout = QVBoxLayout(per_printer_page)
        per_printer_layout.setContentsMargins(0, 0, 0, 0)
        self.usage_by_printer_table = FrozenLeftTable()
        self.usage_by_printer_table._row_h = 34
        for table in (
            self.usage_by_printer_table._left,
            self.usage_by_printer_table._right,
        ):
            table.setAlternatingRowColors(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        per_printer_layout.addWidget(self.usage_by_printer_table, 1)
        self.usage_tabs.addTab(per_printer_page, "ตามเครื่อง")

        panel_layout.addWidget(self.usage_tabs)
        layout.addWidget(panel, 1)
        return page

    def _build_legacy_raw(self) -> QWidget:
        """Exact source counters with no paper/category mapping."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
        note = QLabel(
            "แสดงชื่อ Counter และค่าตามที่เครื่องส่งมาโดยตรง · ไม่ Map กระดาษ "
            "ไม่เปลี่ยนชื่อ และไม่เดาค่าที่เครื่องไม่ได้ส่ง"
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;"
            "border-radius:6px;padding:9px 11px;"
        )
        layout.addWidget(note)
        self.legacy_raw_tabs = QTabWidget()
        self.legacy_raw_tabs.setObjectName("cloud_usage_tabs")
        self.legacy_machine_table = self._raw_table()
        self.legacy_user_table = self._raw_table()
        self.legacy_daily_table = self._raw_table()
        for title, table in (
            ("รายเครื่อง", self.legacy_machine_table),
            ("ผู้ใช้", self.legacy_user_table),
            ("รายวัน", self.legacy_daily_table),
        ):
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.addWidget(table)
            self.legacy_raw_tabs.addTab(host, title)
        layout.addWidget(self.legacy_raw_tabs, 1)
        return page

    @staticmethod
    def _raw_table() -> QTableWidget:
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setAlternatingRowColors(False)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setMinimumSectionSize(110)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        return table

    def _build_legacy_history(self) -> QWidget:
        """Show imported V4.6 snapshots without applying current V5 prices."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        panel, panel_layout = _panel(
            "ประวัติการใช้งานจาก V4.6",
            "ข้อมูลย้อนหลังจาก Database ที่นำเข้า · แสดง Meter snapshot เท่านั้นและไม่คำนวณค่าใช้จ่าย",
        )
        notice = QLabel(
            "ประวัติเชื่อมด้วย Slot ซึ่งแทนจุดติดตั้ง/แผนก · ชื่อเครื่องและ Serial เป็นหลักฐานของเครื่อง "
            "ในช่วงเวลานั้น และระบบไม่คำนวณ Meter ข้ามจุดเปลี่ยนเครื่อง"
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(
            "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;"
            "border-radius:6px;padding:9px 11px;"
        )
        panel_layout.addWidget(notice)
        self.legacy_history_table = _table(
            (
                "วันที่",
                "Slot / จุดติดตั้ง",
                "เครื่องเดิม",
                "Serial Number",
                "Total Meter",
                "Color",
                "B/W",
                "แหล่งข้อมูล",
            ),
            text_columns=(0, 1, 2, 3, 7),
        )
        panel_layout.addWidget(self.legacy_history_table, 1)
        layout.addWidget(panel, 1)
        return page

    def _add_period_toolbar(self, layout: QVBoxLayout) -> None:
        """Add synchronized start/end date fields inside a period-based tab."""
        toolbar = QFrame()
        toolbar.setObjectName("cloud_report_toolbar")
        toolbar_layout = QGridLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 9, 14, 9)
        toolbar_layout.setSpacing(10)

        title = QLabel("ช่วงรายงาน")
        title.setStyleSheet("font-weight:750;color:#25364A;")
        toolbar_layout.addWidget(title, 0, 0)

        start_label = QLabel("วันที่เริ่มต้น")
        start_label.setObjectName("cloud_period_label")
        start_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toolbar_layout.addWidget(start_label, 0, 1)
        start_edit = self._period_date_edit("วันที่เริ่มต้นของรายงาน")
        start_label.setBuddy(start_edit)
        start_control = self._calendar_control(start_edit)
        toolbar_layout.addWidget(start_control, 0, 2)

        end_label = QLabel("วันที่สิ้นสุด")
        end_label.setObjectName("cloud_period_label")
        end_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toolbar_layout.addWidget(end_label, 0, 3)
        end_edit = self._period_date_edit("วันที่สิ้นสุดของรายงาน")
        end_label.setBuddy(end_edit)
        end_control = self._calendar_control(end_edit)
        toolbar_layout.addWidget(end_control, 0, 4)
        freshness = QLabel("ตัวเลขทั้งหมดในแท็บนี้ใช้ช่วงเวลาเดียวกัน")
        freshness.setObjectName("cloud_subtitle")
        freshness.setWordWrap(True)
        toolbar_layout.addWidget(freshness, 1, 0, 1, 6)
        toolbar_layout.setColumnStretch(5, 1)

        start_edit.dateChanged.connect(
            lambda _value, start=start_edit, end=end_edit: self._period_dates_changed(
                start, end, changed="start"
            )
        )
        end_edit.dateChanged.connect(
            lambda _value, start=start_edit, end=end_edit: self._period_dates_changed(
                start, end, changed="end"
            )
        )
        self.period_edit_pairs.append((start_edit, end_edit))
        if len(self.period_edit_pairs) == 1:
            self.period_start_edit = start_edit
            self.period_end_edit = end_edit
        layout.addWidget(toolbar)

    @staticmethod
    def _calendar_control(editor: CalendarDateEdit) -> QWidget:
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.addWidget(editor)
        button = QPushButton("📅")
        button.setObjectName("cloud_calendar_button")
        button.setAccessibleName(f"เปิดปฏิทิน {editor.accessibleName()}")
        button.setToolTip("คลิกเพื่อเลือกวันที่จากปฏิทิน")
        button.clicked.connect(editor.open_calendar)
        row.addWidget(button)
        return host

    @staticmethod
    def _period_date_edit(accessible_name: str) -> QDateEdit:
        control = CalendarDateEdit()
        control.setObjectName("cloud_period_date")
        control.setAccessibleName(accessible_name)
        control.setCalendarPopup(True)
        control.setDisplayFormat("dd/MM/yyyy")
        control.lineEdit().setReadOnly(True)
        control.setMinimumWidth(142)
        control.setMaximumWidth(170)
        calendar = control.calendarWidget()
        calendar.setGridVisible(True)
        calendar.setStyleSheet(
            "QCalendarWidget QWidget{background:#FFFFFF;color:#243244;}"
            "QCalendarWidget QToolButton{background:#EEF4F8;color:#25364A;border:0;"
            "padding:6px;font-weight:700;}"
            "QCalendarWidget QAbstractItemView{background:#FFFFFF;color:#243244;"
            "selection-background-color:#1677C8;selection-color:#FFFFFF;outline:0;}"
            "QCalendarWidget QSpinBox{background:#FFFFFF;color:#243244;border:1px solid #B9CBDD;}"
        )
        return control

    @staticmethod
    def _chart_view() -> QChartView:
        view = QChartView()
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setFixedHeight(190)
        view.setStyleSheet("background:white;border:0;")
        return view

    @staticmethod
    def _kpi_row(specs: tuple[tuple[str, str, str, str], ...]):
        values: dict[str, QLabel] = {}
        row = QGridLayout()
        row.setSpacing(10)
        for column, (key, caption, unit, color) in enumerate(specs):
            card = QFrame()
            card.setObjectName("cloud_kpi")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 11, 14, 11)
            card_layout.setSpacing(2)
            label = QLabel(caption)
            label.setObjectName("cloud_kpi_caption")
            value = QLabel("—")
            value.setObjectName("cloud_kpi_value")
            value.setStyleSheet(f"color:{color};background:transparent;border:0;")
            note = QLabel(unit)
            note.setObjectName("cloud_kpi_note")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            card_layout.addWidget(note)
            row.addWidget(card, 0, column)
            row.setColumnStretch(column, 1)
            value._cloud_caption = label
            values[key] = value
        return values, row

    def set_periods(
        self,
        periods: Iterable[tuple[str, str]],
        selected: tuple[str, str] | None,
    ) -> None:
        normalized_periods = tuple(periods)
        if selected is None and normalized_periods:
            selected = normalized_periods[0]
        if selected is None:
            return

        available_dates = [value for period in normalized_periods for value in period]
        available_dates.extend(selected)
        minimum = QDate.fromString(min(available_dates), "yyyy-MM-dd")
        maximum = QDate.fromString(max(available_dates), "yyyy-MM-dd")
        start_value = QDate.fromString(selected[0], "yyyy-MM-dd")
        end_value = QDate.fromString(selected[1], "yyyy-MM-dd")
        self._period = selected
        for start_edit, end_edit in self.period_edit_pairs:
            start_edit.blockSignals(True)
            end_edit.blockSignals(True)
            start_edit.setDateRange(minimum, maximum)
            end_edit.setDateRange(minimum, maximum)
            start_edit.setDate(start_value)
            end_edit.setDate(end_value)
            start_edit.blockSignals(False)
            end_edit.blockSignals(False)

    def current_period(self) -> tuple[str, str] | None:
        if self._period is None or not self.period_edit_pairs:
            return self._period
        start_edit, end_edit = self.period_edit_pairs[0]
        return (
            start_edit.date().toString("yyyy-MM-dd"),
            end_edit.date().toString("yyyy-MM-dd"),
        )

    def _period_dates_changed(
        self,
        start_edit: QDateEdit,
        end_edit: QDateEdit,
        *,
        changed: str,
    ) -> None:
        start_value = start_edit.date()
        end_value = end_edit.date()
        if start_value > end_value:
            if changed == "start":
                end_value = start_value
            else:
                start_value = end_value

        selected = (
            start_value.toString("yyyy-MM-dd"),
            end_value.toString("yyyy-MM-dd"),
        )
        self._period = selected
        for other_start, other_end in self.period_edit_pairs:
            other_start.blockSignals(True)
            other_end.blockSignals(True)
            other_start.setDate(start_value)
            other_end.setDate(end_value)
            other_start.blockSignals(False)
            other_end.blockSignals(False)
        self.period_changed.emit(selected)

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
        for card in self.overview_kpis.values():
            card.set_metric("—", "")
        for group in (self.user_kpis, self.printer_kpis):
            for value in group.values():
                value.setText("—")

    def set_data(
        self,
        *,
        records: Iterable,
        daily_records: Iterable,
        usage_daily_records: Iterable | None = None,
        monthly_records: Iterable | None = None,
        subjects: Iterable,
        devices: Iterable,
        legacy_history: Iterable | None = None,
        raw_counter_records: Iterable | None = None,
        period: tuple[str, str] | None,
        last_sync_at: str | None,
        usage_meter_baselines: Iterable | None = None,
    ) -> None:
        self.error_label.hide()
        self._records = tuple(records)
        self._daily_records = tuple(daily_records)
        self._usage_daily_records = (
            tuple(usage_daily_records) if usage_daily_records is not None else self._daily_records
        )
        self._monthly_records = tuple(monthly_records) if monthly_records is not None else self._records
        self._subjects = tuple(subjects)
        self._devices = tuple(devices)
        self._legacy_history = tuple(legacy_history or ())
        self._raw_counter_records = tuple(raw_counter_records or ())
        self._usage_meter_baselines = tuple(usage_meter_baselines or ())
        self._legacy_usage_records = build_legacy_usage_intervals(self._legacy_history)
        self._period = period
        self._last_sync_at = last_sync_at
        self._sync_usage_device_filters()
        self.updated_label.setText(
            f"ข้อมูลล่าสุด {last_sync_at.replace('T', ' ')[:16]}" if last_sync_at else "ยังไม่มีเวลาซิงก์ล่าสุด"
        )
        self._build_user_rows()
        self._build_printer_rows()
        self._render_selected_tab(self.tabs.currentIndex())

    def _render_selected_tab(self, index: int) -> None:
        renderers = (
            self._render_overview,
            self._render_users,
            self._render_printers,
            self._render_usage,
            lambda: (self._render_legacy_raw(), self._render_legacy_history()),
        )
        if 0 <= index < len(renderers):
            renderers[index]()

    def _sync_usage_device_filters(self) -> None:
        devices_by_slot = {int(device.slot): device for device in self._devices}
        records_by_slot = {
            int(getattr(record, "device_slot", 0)): record
            for record in (
                *self._monthly_records,
                *self._usage_daily_records,
                *self._legacy_usage_records,
            )
        }
        slots = tuple(
            sorted(
                set(devices_by_slot)
                | {int(getattr(record, "device_slot", 0)) for record in self._monthly_records}
                | {int(getattr(record, "device_slot", 0)) for record in self._usage_daily_records}
                | {int(getattr(record, "device_slot", 0)) for record in self._legacy_usage_records}
                | {int(getattr(record, "device_slot", 0)) for record in self._usage_meter_baselines}
            )
        )
        for slot in slots:
            label = self._slot_label(slot, devices_by_slot, records_by_slot.get(slot))
            checkbox = self.usage_device_filters.get(slot)
            if checkbox is None:
                checkbox = VisibleCheckBox(label)
                checkbox.setAccessibleName(f"แสดงข้อมูล {label}")
                checkbox.setChecked(True)
                checkbox.toggled.connect(
                    lambda checked, selected_slot=slot: self._set_usage_slot_selected(
                        selected_slot, checked
                    )
                )
                self.usage_device_filters[slot] = checkbox
                self._usage_selected_slots.add(slot)
                self.usage_device_filter_layout.addWidget(checkbox)
            else:
                checkbox.setText(label)
                checkbox.show()
        for slot, checkbox in self.usage_device_filters.items():
            if slot not in slots:
                checkbox.hide()
                self._usage_selected_slots.discard(slot)

    def _set_usage_slot_selected(self, slot: int, checked: bool) -> None:
        if checked:
            self._usage_selected_slots.add(slot)
        else:
            self._usage_selected_slots.discard(slot)
        self._render_usage()

    @staticmethod
    def _raw_type_key(record) -> tuple[str, str, str]:
        """Return the exact source identity without merging model counters."""

        return (
            str(getattr(record, "canonical_field", "")),
            str(getattr(record, "label", "")),
            str(getattr(record, "source_path", "")),
        )

    @staticmethod
    def _raw_display_label(
        raw_type: tuple[str, str, str],
        all_types: Iterable[tuple[str, str, str]],
    ) -> str:
        field, label, source_path = raw_type
        base = label or field or "Unknown"
        duplicate = sum(
            1 for other in all_types if (other[1] or other[0] or "Unknown") == base
        ) > 1
        return f"{base} [{source_path}]" if duplicate and source_path else base

    @staticmethod
    def _raw_value(records: Iterable) -> str:
        values = tuple(records)
        if not values:
            return "—"
        return _number(sum(float(getattr(item, "delta_value", 0.0)) for item in values))

    @staticmethod
    def _raw_device_label(slot: int, records: Iterable, devices_by_slot: dict[int, object]) -> str:
        snapshot = next(
            (
                str(getattr(item, "device_name_snapshot", "") or "").strip()
                for item in records
                if int(getattr(item, "device_slot", -1)) == slot
                and str(getattr(item, "device_name_snapshot", "") or "").strip()
            ),
            "",
        )
        device = devices_by_slot.get(slot)
        return f"Slot {slot + 1} · {snapshot or getattr(device, 'name', '') or f'MFP {slot + 1}'}"

    @staticmethod
    def _configure_raw_table(
        table: QTableWidget,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
        *,
        empty: str,
        text_columns: tuple[int, ...] = (0,),
    ) -> None:
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(max(1, len(rows)))
        header = table.horizontalHeader()
        if headers:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for column in range(1, len(headers)):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
                table.setColumnWidth(column, 170)
        if not rows:
            if headers:
                table.setSpan(0, 0, 1, len(headers))
                item = QTableWidgetItem(empty)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(0, 0, item)
            return
        for row_no, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    (
                        Qt.AlignmentFlag.AlignLeft
                        if column in text_columns
                        else Qt.AlignmentFlag.AlignRight
                    )
                    | Qt.AlignmentFlag.AlignVCenter
                )
                table.setItem(row_no, column, item)

    def _render_legacy_raw(self) -> None:
        records = tuple(self._raw_counter_records)
        devices_by_slot = {int(device.slot): device for device in self._devices}
        slots = tuple(
            sorted(
                {int(getattr(item, "device_slot", 0)) for item in records}
                | set(devices_by_slot)
            )
        )
        device_labels = {
            slot: self._raw_device_label(slot, records, devices_by_slot) for slot in slots
        }
        device_rows = tuple(item for item in records if not getattr(item, "subject_type", ""))
        raw_types = tuple(
            sorted(
                {self._raw_type_key(item) for item in device_rows},
                key=lambda item: (item[1].casefold(), item[0], item[2]),
            )
        )
        machine_rows: list[tuple[str, ...]] = []
        for raw_type in raw_types:
            values = tuple(
                self._raw_value(
                    item
                    for item in device_rows
                    if int(item.device_slot) == slot
                    and self._raw_type_key(item) == raw_type
                )
                for slot in slots
            )
            machine_rows.append(
                (
                    (
                        "—"
                        if raw_operation_label(raw_type[0], raw_type[1])
                        == "ไม่พบข้อมูลแยกประเภท"
                        else raw_operation_label(raw_type[0], raw_type[1])
                    ),
                    self._raw_display_label(raw_type, raw_types),
                    *values,
                )
            )
        self._configure_raw_table(
            self.legacy_machine_table,
            (
                "กลุ่มงาน",
                "ประเภท Counter (ชื่อจากเครื่อง)",
                *(device_labels[slot] for slot in slots),
            ),
            tuple(machine_rows),
            empty="ยังไม่มี Raw Counter ในช่วงวันที่เลือก",
            text_columns=(0, 1),
        )

        subject_rows = tuple(item for item in records if getattr(item, "subject_type", ""))
        subject_columns = tuple(
            sorted(
                {
                    (int(item.device_slot), *self._raw_type_key(item))
                    for item in subject_rows
                },
                key=lambda item: (item[0], item[2].casefold(), item[1]),
            )
        )
        subjects = tuple(
            sorted(
                {
                    (
                        str(item.subject_type),
                        str(item.subject_id),
                        str(item.subject_name or item.subject_id),
                    )
                    for item in subject_rows
                },
                key=lambda item: (item[2].casefold(), item[0], item[1]),
            )
        )
        user_rows: list[tuple[str, ...]] = []
        for subject_type, subject_id, subject_name in subjects:
            values = tuple(
                self._raw_value(
                    item
                    for item in subject_rows
                    if str(item.subject_type) == subject_type
                    and str(item.subject_id) == subject_id
                    and int(item.device_slot) == slot
                    and self._raw_type_key(item) == (field, label, source_path)
                )
                for slot, field, label, source_path in subject_columns
            )
            user_rows.append((f"{subject_name} ({subject_type})", *values))
        self._configure_raw_table(
            self.legacy_user_table,
            (
                "ผู้ใช้ / Account",
                *(
                    f"{device_labels.get(slot, f'Slot {slot + 1}')} · "
                    f"{raw_operation_label(field, label)} · "
                    f"{self._raw_display_label((field, label, source_path), tuple((item[1], item[2], item[3]) for item in subject_columns))}"
                    for slot, field, label, source_path in subject_columns
                ),
            ),
            tuple(user_rows),
            empty="ยังไม่มี Raw Counter แยกผู้ใช้ / Account ในช่วงวันที่เลือก",
        )

        days = tuple(sorted({item.record_date for item in device_rows}))
        daily_columns = tuple(
            sorted(
                {(int(item.device_slot), *self._raw_type_key(item)) for item in device_rows},
                key=lambda item: (item[0], item[2].casefold(), item[1]),
            )
        )
        daily_rows = tuple(
            (
                day.strftime("%d/%m/%Y"),
                *(
                    self._raw_value(
                        item
                        for item in device_rows
                        if item.record_date == day
                        and int(item.device_slot) == slot
                        and self._raw_type_key(item) == (field, label, source_path)
                    )
                    for slot, field, label, source_path in daily_columns
                ),
            )
            for day in days
        )
        self._configure_raw_table(
            self.legacy_daily_table,
            (
                "วันที่",
                *(
                    f"{device_labels.get(slot, f'Slot {slot + 1}')} · "
                    f"{raw_operation_label(field, label)} · "
                    f"{self._raw_display_label((field, label, source_path), tuple((item[1], item[2], item[3]) for item in daily_columns))}"
                    for slot, field, label, source_path in daily_columns
                ),
            ),
            daily_rows,
            empty="ยังไม่มี Raw Counter รายวันในช่วงวันที่เลือก",
        )

    def _render_legacy_history(self) -> None:
        rows = tuple(
            sorted(
                self._legacy_history,
                key=lambda item: (
                    int(getattr(item, "slot", 0)),
                    str(getattr(item, "read_date", "")),
                ),
                reverse=True,
            )
        )
        event_by_id: dict[int, str] = {}
        previous_by_slot: dict[int, object] = {}
        for record in sorted(
            rows,
            key=lambda item: (
                int(getattr(item, "slot", 0)),
                str(getattr(item, "read_date", "")),
            ),
        ):
            slot = int(getattr(record, "slot", 0))
            previous = previous_by_slot.get(slot)
            previous_by_slot[slot] = record
            if previous is None:
                event_by_id[id(record)] = "V4.6 · จุดเริ่มประวัติ"
                continue
            old_serial = str(getattr(previous, "serial", "") or "").strip()
            new_serial = str(getattr(record, "serial", "") or "").strip()
            meter_dropped = float(getattr(record, "total", 0) or 0) < float(
                getattr(previous, "total", 0) or 0
            )
            if (old_serial and new_serial and old_serial != new_serial) or meter_dropped:
                event_by_id[id(record)] = "V4.6 · เปลี่ยนเครื่อง / Baseline ใหม่"
            else:
                event_by_id[id(record)] = "V4.6 Historical"
        self.legacy_history_table.clearSpans()
        self.legacy_history_table.clearContents()
        self.legacy_history_table.setRowCount(max(1, len(rows)))
        if not rows:
            self.legacy_history_table.setSpan(0, 0, 1, 8)
            empty = QTableWidgetItem("ยังไม่มีประวัติ V4.6 · นำเข้าได้จาก Setup Wizard")
            empty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.legacy_history_table.setItem(0, 0, empty)
            return
        for row_index, record in enumerate(rows):
            values = (
                str(getattr(record, "read_date", "") or "—"),
                self._slot_label(
                    int(getattr(record, "slot", 0)),
                    {int(device.slot): device for device in self._devices},
                    record,
                ),
                str(getattr(record, "machine_name", "") or f"MFP {int(getattr(record, 'slot', 0)) + 1}"),
                str(getattr(record, "serial", "") or "—"),
                _number(float(getattr(record, "total", 0) or 0)),
                _number(float(getattr(record, "color", 0) or 0)),
                _number(float(getattr(record, "bw", 0) or 0)),
                event_by_id[id(record)],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                alignment = (
                    Qt.AlignmentFlag.AlignLeft
                    if column in (0, 1, 2, 3, 7)
                    else Qt.AlignmentFlag.AlignRight
                )
                item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
                self.legacy_history_table.setItem(row_index, column, item)

    def _build_user_rows(self) -> None:
        grouped: dict[str, dict] = {}
        subject_group_keys: dict[tuple[str, str, int], str] = {}
        for item in self._subjects:
            subject_name = str(item.subject_name or "").strip()
            slot = int(item.device_slot)
            key = (
                f"{item.subject_type}:name:{subject_name.casefold()}"
                if subject_name and subject_name != str(item.subject_id)
                else f"{item.subject_type}:slot:{slot}:id:{item.subject_id}"
            )
            subject_group_keys[(str(item.subject_type), str(item.subject_id), slot)] = key
            row = grouped.setdefault(
                key,
                {
                    "key": key,
                    "name": subject_name or str(item.subject_id),
                    "type": item.subject_type,
                    "usage": 0.0,
                    "print": 0.0,
                    "copy": 0.0,
                    "print_available": False,
                    "copy_available": False,
                    "latest": 0.0,
                    "printers": defaultdict(float),
                    "by_slot": defaultdict(
                        lambda: {
                            "print_a3_color": 0.0,
                            "print_a3_bw": 0.0,
                            "print_a4_color": 0.0,
                            "print_a4_bw": 0.0,
                            "print_other": 0.0,
                            "copy_a3_color": 0.0,
                            "copy_a3_bw": 0.0,
                            "copy_a4_color": 0.0,
                            "copy_a4_bw": 0.0,
                            "copy_other": 0.0,
                            "scan": 0.0,
                            "total": 0.0,
                            "cost": 0.0,
                            "print_available": False,
                            "copy_available": False,
                            "scan_available": False,
                            "cost_available": False,
                        }
                    ),
                    "review": False,
                },
            )
            identity = _record_identity(item)
            row["usage"] += float(item.period_usage)
            row["latest"] = max(row["latest"], float(item.latest_total))
            row["printers"][identity] += float(item.period_usage)
            row["by_slot"][slot]["total"] += float(item.period_usage)
            row["review"] = row["review"] or bool(item.needs_review)

        raw_groups: dict[tuple[str, str, int, str], list[object]] = defaultdict(list)
        for item in self._raw_counter_records:
            subject_type = str(getattr(item, "subject_type", "") or "")
            subject_id = str(getattr(item, "subject_id", "") or "")
            if not subject_type or not subject_id:
                continue
            serial = str(getattr(item, "device_serial_snapshot", "") or "").strip()
            slot = int(item.device_slot)
            identity = f"serial:{serial}" if serial else f"slot:{slot}"
            raw_groups[(subject_type, subject_id, slot, identity)].append(item)
        for (subject_type, subject_id, slot, identity), raw_records in raw_groups.items():
            key = subject_group_keys.get((subject_type, subject_id, slot))
            if key is None:
                raw_name = str(getattr(raw_records[0], "subject_name", "") or "").strip()
                key = (
                    f"{subject_type}:name:{raw_name.casefold()}"
                    if raw_name and raw_name != subject_id
                    else f"{subject_type}:slot:{slot}:id:{subject_id}"
                )
            row = grouped.get(key)
            if row is None:
                continue
            breakdown = breakdown_from_raw_records(raw_records)
            slot_row = row["by_slot"][slot]
            for field in (
                "print_a3_color",
                "print_a3_bw",
                "print_a4_color",
                "print_a4_bw",
                "print_other",
                "copy_a3_color",
                "copy_a3_bw",
                "copy_a4_color",
                "copy_a4_bw",
                "copy_other",
                "scan",
            ):
                slot_row[field] += float(getattr(breakdown, field))
            slot_row["print_available"] = (
                slot_row["print_available"] or breakdown.print_available
            )
            slot_row["copy_available"] = (
                slot_row["copy_available"] or breakdown.copy_available
            )
            slot_row["scan_available"] = (
                slot_row["scan_available"] or breakdown.scan_available
            )
            row["print"] += breakdown.print_total
            row["copy"] += breakdown.copy_total
            row["print_available"] = row["print_available"] or breakdown.print_available
            row["copy_available"] = row["copy_available"] or breakdown.copy_available
            if breakdown.print_available or breakdown.copy_available:
                row["printers"][identity] = max(
                    row["printers"].get(identity, 0.0),
                    breakdown.print_total + breakdown.copy_total,
                )
        self._user_rows = sorted(grouped.values(), key=lambda item: item["usage"], reverse=True)
        if self._selected_user and not any(row["key"] == self._selected_user for row in self._user_rows):
            self._selected_user = None

    def _build_printer_rows(self) -> None:
        devices_by_slot = {int(device.slot): device for device in self._devices}
        grouped: dict[str, dict] = {}
        for record in self._records:
            key = _record_identity(record)
            slot = int(record.device_slot)
            device = devices_by_slot.get(slot)
            row = grouped.setdefault(
                key,
                {
                    "key": key,
                    "slot": slot,
                    "name": _record_name(record, devices_by_slot),
                    "device": device,
                    "color": 0.0,
                    "bw": 0.0,
                    "print": 0.0,
                    "copy": 0.0,
                    "print_available": False,
                    "copy_available": False,
                    "scan": 0.0,
                    "total": 0.0,
                    "cost": 0.0,
                    "review": False,
                },
            )
            row["color"] += sum(_combined(record, name) for name in ("a3_color", "a4_color"))
            row["bw"] += sum(_combined(record, name) for name in ("a3_bw", "a4_bw"))
            row["print"] += _operation_total(record, "print")
            row["copy"] += _operation_total(record, "copy")
            row["print_available"] = row["print_available"] or _operation_available(
                record, "print"
            )
            row["copy_available"] = row["copy_available"] or _operation_available(
                record, "copy"
            )
            row["scan"] += _combined(record, "scan")
            row["total"] += _record_total(record)
            row["cost"] += self._record_cost(record)
            row["review"] = row["review"] or bool(record.held_days or record.incomplete_days)
        self._printer_rows = sorted(grouped.values(), key=lambda item: item["total"], reverse=True)
        if self._selected_printer and not any(row["key"] == self._selected_printer for row in self._printer_rows):
            self._selected_printer = None

    def _render_overview(self) -> None:
        total_pages = sum(row["total"] for row in self._printer_rows)
        total_scan = sum(row["scan"] for row in self._printer_rows)
        records = self._records
        print_available = any(bool(getattr(record, "print_available", False)) for record in records)
        copy_available = any(bool(getattr(record, "copy_available", False)) for record in records)
        cost_available = all(
            bool(getattr(record, "provisional_cost_available", True))
            for record in records
            if int(getattr(record, "provisional_days", 0) or 0)
        )

        def counter_total(name: str) -> float:
            return sum(_combined(record, name) for record in records)

        def a3_a4_detail(a3_name: str, a4_name: str) -> str:
            return f"A3 {_number(counter_total(a3_name))}  |  A4 {_number(counter_total(a4_name))}"

        self.overview_kpis["color_print"].set_metric(
            _number(counter_total("print_color")),
            a3_a4_detail("print_a3_color", "print_a4_color"),
            available=print_available,
        )
        self.overview_kpis["bw_print"].set_metric(
            _number(counter_total("print_bw")),
            a3_a4_detail("print_a3_bw", "print_a4_bw"),
            available=print_available,
        )
        self.overview_kpis["color_copy"].set_metric(
            _number(counter_total("copy_color")),
            a3_a4_detail("copy_a3_color", "copy_a4_color"),
            available=copy_available,
        )
        self.overview_kpis["bw_copy"].set_metric(
            _number(counter_total("copy_bw")),
            a3_a4_detail("copy_a3_bw", "copy_a4_bw"),
            available=copy_available,
        )
        self.overview_kpis["total_usage"].set_metric(
            _number(total_pages), "ช่วงรายงานที่เลือก"
        )
        self.overview_kpis["total_cost"].set_metric(
            f"฿{_money(sum(row['cost'] for row in self._printer_rows))}",
            "THB",
            available=cost_available,
        )
        self._fill_table(
            self.overview_users,
            [
                (row["name"], "User" if row["type"] == "user" else "Account Track", _number(row["usage"]))
                for row in self._user_rows[:10]
            ],
            empty="ยังไม่มีข้อมูล User / Account ในช่วงนี้",
        )
        self._fill_table(
            self.overview_printers,
            [
                (
                    row["name"],
                    _number(row["print"]) if row["print_available"] else "—",
                    _number(row["copy"]) if row["copy_available"] else "—",
                    _number(row["scan"]),
                    _number(row["total"]),
                )
                for row in self._printer_rows[:10]
            ],
            empty="ยังไม่มีข้อมูลเครื่องพิมพ์ในช่วงนี้",
        )
        self.overview_mix.setChart(
            self._bar_chart(
                ("Print", "Copy", "Scan"),
                (
                    (
                        "หน้า",
                        (
                            sum(row["print"] for row in self._printer_rows),
                            sum(row["copy"] for row in self._printer_rows),
                            total_scan,
                        ),
                        BLUE,
                    ),
                ),
            )
        )
        self.overview_trend.setChart(self._timeline_chart(None))
        apply_language(self)

    def _render_users(self) -> None:
        total = sum(row["usage"] for row in self._user_rows)
        highest = self._user_rows[0]["usage"] if self._user_rows else 0
        print_available = any(row["print_available"] for row in self._user_rows)
        copy_available = any(row["copy_available"] for row in self._user_rows)
        self.user_kpis["count"].setText(_number(len(self._user_rows)))
        self.user_kpis["print"].setText(
            _number(sum(row["print"] for row in self._user_rows))
            if print_available
            else "—"
        )
        self.user_kpis["copy"].setText(
            _number(sum(row["copy"] for row in self._user_rows))
            if copy_available
            else "—"
        )
        self.user_kpis["usage"].setText(_number(total))
        self.user_kpis["highest"].setText(_number(highest))
        self.users_top_chart.setChart(
            self._horizontal_like_chart(
                [row["name"] for row in self._user_rows[:8]],
                [row["usage"] for row in self._user_rows[:8]],
                ORANGE,
            )
        )
        devices_by_identity = {row["key"]: row["name"] for row in self._printer_rows}
        selected = next((row for row in self._user_rows if row["key"] == self._selected_user), None)
        source = selected["printers"] if selected else defaultdict(float)
        if not selected:
            for row in self._user_rows:
                for identity, usage in row["printers"].items():
                    source[identity] += usage
        labels = [devices_by_identity.get(key, key.replace("serial:", "")) for key in source]
        self.users_printer_chart.setChart(self._horizontal_like_chart(labels, list(source.values()), BLUE))
        self.user_filter_badge.setText(
            f"กำลังกรอง: {selected['name']}" if selected else "เลือกผู้ใช้จากตารางเพื่อกรองกราฟ"
        )
        self.user_recovery_button.setVisible(not self._user_rows)
        slots = tuple(
            sorted(
                {int(device.slot) for device in self._devices}
                | {
                    int(slot)
                    for row in self._user_rows
                    for slot in row["by_slot"]
                }
            )
        )
        devices_by_slot = {int(device.slot): device for device in self._devices}
        usage_fields = tuple(field for field, _label, _availability in USAGE_METRICS)
        self._configure_users_matrix(slots, devices_by_slot, usage_fields)
        rows = []
        for row in self._user_rows:
            values = [row["name"]]
            for slot in slots:
                slot_row = row["by_slot"].get(slot, {})
                for field in usage_fields:
                    available = True
                    if field.startswith("print_"):
                        available = bool(slot_row.get("print_available"))
                    elif field.startswith("copy_"):
                        available = bool(slot_row.get("copy_available"))
                    elif field == "scan":
                        available = bool(slot_row.get("scan_available"))
                    elif field == "cost":
                        available = False
                    values.append(
                        self._usage_value_text(
                            field,
                            float(slot_row.get(field, 0.0)),
                            available=available,
                        )
                    )
            rows.append(tuple(values))
        users_signal_blocker = QSignalBlocker(self.users_table)
        self._fill_table(self.users_table, rows, empty="ยังไม่มีข้อมูล User / Account ในช่วงนี้")
        for index, row in enumerate(self._user_rows):
            self.users_table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row["key"])
        del users_signal_blocker
        apply_language(self)

    def _configure_users_matrix(
        self,
        slots: tuple[int, ...],
        devices_by_slot: dict[int, object],
        usage_fields: tuple[str, ...],
    ) -> None:
        table = self.users_table
        metric_labels = tuple(label for _field, label, _availability in USAGE_METRICS)
        table.setRowCount(0)
        table.setColumnCount(1 + len(slots) * len(usage_fields))
        table.setHorizontalHeaderLabels(("User / Account",) + metric_labels * len(slots))
        for column in range(table.columnCount()):
            header = table.horizontalHeaderItem(column)
            if header is not None:
                header.setTextAlignment(
                    (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    if column == 0
                    else (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
        table.setColumnWidth(0, 210)
        for group_index in range(len(slots)):
            for metric_index, field in enumerate(usage_fields):
                column = 1 + group_index * len(usage_fields) + metric_index
                table.setColumnWidth(column, 190 if field == "cost" else 128)
        outer_groups = tuple(
            (
                self._slot_label(slot, devices_by_slot),
                len(usage_fields),
            )
            for slot in slots
        )
        middle_groups = tuple(
            group
            for _slot in slots
            for group in USAGE_GROUPS
        )
        table.setThreeLevelGroupedHeader(
            "User / Account",
            outer_groups,
            middle_groups,
            USAGE_SUBLABELS * len(slots),
        )
        table.setGroupSeparators(
            tuple(len(usage_fields) * (index + 1) for index in range(len(slots) - 1)),
            color="#CBD5E1",
            width=1,
        )

    def _render_printers(self) -> None:
        rows = self._printer_rows
        total_cost = sum(row["cost"] for row in rows)
        self.printer_kpis["count"].setText(_number(len([row for row in rows if row["total"] > 0])))
        self.printer_kpis["print"].setText(
            _number(sum(row["print"] for row in rows))
            if any(row["print_available"] for row in rows)
            else "—"
        )
        self.printer_kpis["copy"].setText(
            _number(sum(row["copy"] for row in rows))
            if any(row["copy_available"] for row in rows)
            else "—"
        )
        self.printer_kpis["scan"].setText(_number(sum(row["scan"] for row in rows)))
        self.printer_kpis["cost"].setText(_money(total_cost))
        selected = next((row for row in rows if row["key"] == self._selected_printer), None)
        self.printer_mix.setChart(
            self._bar_chart(
                ("Print", "Copy", "Scan"),
                tuple(
                    (
                        _chart_printer_name(row["name"]),
                        (row["print"], row["copy"], row["scan"]),
                        DEVICE_COLORS[index % len(DEVICE_COLORS)],
                    )
                    for index, row in enumerate(rows)
                ),
            )
        )
        self.printer_trend.setChart(self._printer_timeline_chart(rows))
        table_rows = []
        for row in rows:
            device = row["device"]
            status = "ควรตรวจสอบ" if row["review"] else (
                "Online" if str(getattr(device, "connection_status", "")).casefold() == "online" else "ค่าล่าสุด"
            )
            table_rows.append(
                (
                    row["name"],
                    status,
                    _number(row["print"]) if row["print_available"] else "—",
                    _number(row["copy"]) if row["copy_available"] else "—",
                    _number(row["scan"]),
                    _number(row["total"]),
                    _money(row["cost"]),
                )
            )
        printers_signal_blocker = QSignalBlocker(self.printers_table)
        self._fill_table(self.printers_table, table_rows, empty="ยังไม่มีข้อมูลเครื่องพิมพ์ในช่วงนี้")
        for index, row in enumerate(rows):
            self.printers_table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row["key"])
        del printers_signal_blocker
        detail = selected or (rows[0] if rows else None)
        if detail:
            device = detail["device"]
            detail_rows = (
                ("เครื่องพิมพ์", detail["name"]),
                ("IP address", str(getattr(device, "host", "") or "—")),
                ("Serial", str(getattr(device, "serial", "") or detail["key"].replace("serial:", ""))),
                ("Total Meter ล่าสุด", _number(getattr(device, "last_total", 0) or 0)),
                ("สำเร็จล่าสุด", str(getattr(device, "last_success_at", "") or "ยังไม่มีข้อมูล")),
                (
                    "Print ในช่วงนี้",
                    _number(detail["print"]) if detail["print_available"] else "ไม่พบข้อมูลแยกประเภท",
                ),
                (
                    "Copy ในช่วงนี้",
                    _number(detail["copy"]) if detail["copy_available"] else "ไม่พบข้อมูลแยกประเภท",
                ),
                ("ยอดในช่วงนี้", f"{_number(detail['total'])} หน้า"),
            )
            self._fill_table(self.printer_detail, detail_rows)
        else:
            self._fill_table(self.printer_detail, [], empty="เลือกเครื่องเพื่อดู Meter detail")
        apply_language(self)

    @staticmethod
    def _usage_period(record, granularity: str) -> tuple[str, str]:
        period_start = str(getattr(record, "period_start", "") or "")
        try:
            parsed = date.fromisoformat(period_start[:10])
        except ValueError:
            return period_start or "—", period_start
        if granularity == "D":
            return parsed.strftime("%d/%m/%Y"), parsed.isoformat()
        if granularity == "Y":
            return str(parsed.year), str(parsed.year)
        billing_month = str(getattr(record, "billing_month", "") or "")
        if len(billing_month) == 7:
            return f"{billing_month[5:7]}/{billing_month[:4]}", billing_month
        return parsed.strftime("%m/%Y"), parsed.strftime("%Y-%m")

    def include_waste_adjustment(self) -> bool:
        """Return the report-wide cost view selected by the user."""

        return self.usage_waste_checkbox.isChecked()

    def _cost_field(self) -> str:
        return "net_cost" if self.include_waste_adjustment() else "gross_cost"

    def _record_cost(self, record) -> float:
        return _combined(record, self._cost_field())

    def _usage_values(self, record) -> dict[str, float]:
        return {
            "print_a3_color": _combined(record, "print_a3_color"),
            "print_a3_bw": _combined(record, "print_a3_bw"),
            "print_a4_color": _combined(record, "print_a4_color"),
            "print_a4_bw": _combined(record, "print_a4_bw"),
            "print_other": _combined(record, "print_other"),
            "copy_a3_color": _combined(record, "copy_a3_color"),
            "copy_a3_bw": _combined(record, "copy_a3_bw"),
            "copy_a4_color": _combined(record, "copy_a4_color"),
            "copy_a4_bw": _combined(record, "copy_a4_bw"),
            "copy_other": _combined(record, "copy_other"),
            "scan": _combined(record, "scan"),
            "total": _record_total(record),
            "cost": self._record_cost(record),
        }

    def _usage_baselines_by_slot(self) -> dict[int, tuple[date, float]]:
        """Merge V4.6 and V5 absolute openings without creating usage rows."""

        candidates: dict[int, tuple[date, float]] = {}

        def add(slot: int, observed_on: date, total: object) -> None:
            if isinstance(total, bool):
                return
            try:
                value = float(total)
            except (TypeError, ValueError):
                return
            if value < 0:
                return
            current = candidates.get(slot)
            if current is None or observed_on < current[0]:
                candidates[slot] = (observed_on, value)

        for baseline in self._usage_meter_baselines:
            observed = getattr(baseline, "observed_on", None)
            if not isinstance(observed, date):
                try:
                    observed = date.fromisoformat(str(observed)[:10])
                except ValueError:
                    continue
            add(
                int(getattr(baseline, "device_slot", 0)),
                observed,
                getattr(baseline, "total_meter", None),
            )
        for snapshot in self._legacy_history:
            try:
                observed = date.fromisoformat(str(snapshot.read_date)[:10])
            except ValueError:
                continue
            add(int(snapshot.slot), observed, snapshot.total)
        return candidates

    @staticmethod
    def _baseline_values(total: float | None, fields: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            _number(total) if field == "total" and total is not None else "—"
            for field in fields
        )

    @staticmethod
    def _style_baseline_row(table: FrozenLeftTable) -> None:
        if not table.rowCount() or table.item(0, 0) is None:
            return
        tooltip = (
            "ค่า Meter ครั้งแรกที่บันทึกไว้ ใช้เป็นข้อมูลอ้างอิงเท่านั้น "
            "ไม่รวมในยอดใช้งาน กราฟ หรือค่าใช้จ่าย"
        )
        for column in range(table.columnCount()):
            item = table.item(0, column)
            if item is None:
                continue
            item.setBackground(QColor("#EEF6F9"))
            item.setForeground(QColor(NAVY))
            item.setToolTip(tooltip)

    def _render_usage(self) -> None:
        granularity = self.usage_granularity
        period_label = {"D": "วัน", "M": "เดือน", "Y": "ปี"}[granularity]
        period_description = {"D": "รายวัน", "M": "รายเดือน", "Y": "รายปี"}[granularity]
        source_records = self._usage_records(granularity)
        devices_by_slot = {int(device.slot): device for device in self._devices}
        totals_by_period: dict[str, dict] = {}
        period_labels: dict[str, str] = {}
        by_period_and_printer: dict[tuple[str, str], dict] = {}
        printers: dict[str, tuple[int, str]] = {}
        all_baselines_by_slot = self._usage_baselines_by_slot()
        aggregate_baselines_by_slot = {
            slot: value
            for slot, value in all_baselines_by_slot.items()
            if slot in self._usage_selected_slots
        }
        for record in source_records:
            value_label, period_key = self._usage_period(record, granularity)
            period_labels[period_key] = value_label
            values = self._usage_values(record)
            slot = int(getattr(record, "device_slot", 0))
            if slot in self._usage_selected_slots:
                total_row = totals_by_period.setdefault(
                    period_key,
                    {
                        "period": value_label,
                        "cost_available": True,
                        "print_available": False,
                        "copy_available": False,
                        **{name: 0.0 for name in values},
                    },
                )
                for name, value in values.items():
                    total_row[name] += value
                total_row["cost_available"] = (
                    total_row["cost_available"] and self._cost_available(record)
                )
                total_row["print_available"] = (
                    total_row["print_available"] or _operation_available(record, "print")
                )
                total_row["copy_available"] = (
                    total_row["copy_available"] or _operation_available(record, "copy")
                )
            identity = f"slot:{slot}"
            printers.setdefault(
                identity,
                (slot, self._slot_label(slot, devices_by_slot, record)),
            )
            printer_row = by_period_and_printer.setdefault(
                (period_key, identity),
                {
                    "cost_available": True,
                    "print_available": False,
                    "copy_available": False,
                    **{name: 0.0 for name in values},
                },
            )
            for name, value in values.items():
                printer_row[name] += value
            printer_row["cost_available"] = (
                printer_row["cost_available"] and self._cost_available(record)
            )
            printer_row["print_available"] = (
                printer_row["print_available"] or _operation_available(record, "print")
            )
            printer_row["copy_available"] = (
                printer_row["copy_available"] or _operation_available(record, "copy")
            )

        for device in self._devices:
            slot = int(device.slot)
            identity = f"slot:{slot}"
            printers.setdefault(identity, (slot, self._slot_label(slot, devices_by_slot)))

        for slot in all_baselines_by_slot:
            identity = f"slot:{slot}"
            printers.setdefault(identity, (slot, self._slot_label(slot, devices_by_slot)))

        usage_fields = tuple(field for field, _label, _availability in USAGE_METRICS)

        def available(field: str, row: dict) -> bool:
            availability = next(
                requirement
                for metric, _label, requirement in USAGE_METRICS
                if metric == field
            )
            if availability == "print":
                return bool(row.get("print_available"))
            if availability == "copy":
                return bool(row.get("copy_available"))
            if availability == "cost":
                return bool(row.get("cost_available", True))
            return True

        aggregate_rows = [
            (
                row["period"],
                *(
                    self._usage_value_text(
                        name,
                        row[name],
                        available=available(name, row),
                    )
                    for name in usage_fields
                ),
            )
            for _period, row in sorted(totals_by_period.items(), reverse=True)
        ]
        if aggregate_baselines_by_slot:
            aggregate_rows.insert(
                0,
                (
                    "Meter เริ่มต้น",
                    *self._baseline_values(
                        sum(total for _day, total in aggregate_baselines_by_slot.values()),
                        usage_fields,
                    ),
                ),
            )
        self.usage_monthly_table.horizontalHeaderItem(0).setText(period_label)
        self.usage_monthly_table.groupedHeaderItem(0, 0).setText(period_label)
        self._fill_table(
            self.usage_monthly_table,
            aggregate_rows,
            empty=f"ยังไม่มีข้อมูลการใช้งาน{period_description}",
        )
        if aggregate_baselines_by_slot:
            self._style_baseline_row(self.usage_monthly_table)
        printer_groups = tuple(
            (identity, name)
            for identity, (_slot, name) in sorted(
                printers.items(), key=lambda item: (item[1][0], item[1][1].casefold())
            )
        )
        self._configure_usage_matrix_table(period_label, printer_groups, usage_fields)
        printer_rows = []
        if all_baselines_by_slot:
            baseline_values = ["Meter เริ่มต้น"]
            for _identity, (slot, _name) in sorted(
                printers.items(), key=lambda item: (item[1][0], item[1][1].casefold())
            ):
                baseline = all_baselines_by_slot.get(slot)
                baseline_values.extend(
                    self._baseline_values(
                        baseline[1] if baseline is not None else None,
                        usage_fields,
                    )
                )
            printer_rows.append(tuple(baseline_values))
        for period_key, period_text in sorted(period_labels.items(), reverse=True):
            values = [period_text]
            for identity, _name in printer_groups:
                printer_row = by_period_and_printer.get((period_key, identity), {})
                values.extend(
                    self._usage_value_text(
                        name,
                        printer_row.get(name, 0.0),
                        available=available(name, printer_row),
                    )
                    for name in usage_fields
                )
            printer_rows.append(tuple(values))
        self._fill_table(
            self.usage_by_printer_table,
            printer_rows,
            empty=f"ยังไม่มีข้อมูลการใช้งาน{period_description}ของเครื่องพิมพ์",
        )
        if all_baselines_by_slot:
            self._style_baseline_row(self.usage_by_printer_table)
        chronological = [row for _period, row in sorted(totals_by_period.items())]
        self.usage_timeline_chart.setChart(
            self._multi_line_chart(
                tuple(row["period"] for row in chronological),
                (
                    (
                        "Print",
                        tuple(
                            sum(float(row[field]) for field in usage_fields if field.startswith("print_"))
                            for row in chronological
                        ),
                        BLUE,
                    ),
                    (
                        "Copy",
                        tuple(
                            sum(float(row[field]) for field in usage_fields if field.startswith("copy_"))
                            for row in chronological
                        ),
                        ORANGE,
                    ),
                ),
            )
        )
        apply_language(self)

    @staticmethod
    def _usage_value_text(field: str, value: float, *, available: bool = True) -> str:
        if not available:
            return "—"
        return _money(value) if field == "cost" else _number(value)

    def _usage_records(self, granularity: str) -> tuple:
        v5_records = self._usage_daily_records if granularity == "D" else self._monthly_records
        cutoff_records = self._usage_daily_records or self._monthly_records
        first_v5_by_slot: dict[int, date] = {}
        for record in cutoff_records:
            try:
                start = date.fromisoformat(str(getattr(record, "period_start", ""))[:10])
            except ValueError:
                continue
            slot = int(getattr(record, "device_slot", 0))
            first_v5_by_slot[slot] = min(start, first_v5_by_slot.get(slot, start))
        legacy_records = tuple(
            record
            for record in self._legacy_usage_records
            if record.device_slot not in first_v5_by_slot
            or record.period_end < first_v5_by_slot[record.device_slot]
        )
        return legacy_records + tuple(v5_records)

    @staticmethod
    def _cost_available(record) -> bool:
        return bool(
            getattr(
                record,
                "cost_available",
                getattr(record, "provisional_cost_available", True),
            )
        )

    @staticmethod
    def _slot_label(slot: int, devices_by_slot: dict[int, object], record=None) -> str:
        device = devices_by_slot.get(slot)
        name = str(getattr(device, "name", "") or "").strip()
        if not name and record is not None:
            name = str(
                getattr(record, "device_name_snapshot", "")
                or getattr(record, "machine_name", "")
                or ""
            ).strip()
        return f"Slot {slot + 1} · {name or 'ยังไม่ได้ตั้งชื่อ'}"

    def _configure_usage_matrix_table(
        self,
        period_label: str,
        printer_groups: tuple[tuple[str, str], ...],
        usage_fields: tuple[str, ...],
    ) -> None:
        metric_labels = tuple(label for _field, label, _availability in USAGE_METRICS)
        table = self.usage_by_printer_table
        table.setRowCount(0)
        table.setColumnCount(1 + len(printer_groups) * len(usage_fields))
        table.setHorizontalHeaderLabels(
            (period_label,) + metric_labels * len(printer_groups)
        )
        table.setColumnWidth(0, 118)
        for group_index in range(len(printer_groups)):
            for metric_index, field in enumerate(usage_fields):
                column = 1 + group_index * len(usage_fields) + metric_index
                table.setColumnWidth(column, 190 if field == "cost" else 128)
        table.setThreeLevelGroupedHeader(
            period_label,
            tuple((name, len(usage_fields)) for _identity, name in printer_groups),
            tuple(group for _identity, _name in printer_groups for group in USAGE_GROUPS),
            USAGE_SUBLABELS * len(printer_groups),
        )
        table.setGroupSeparators(
            tuple(len(usage_fields) * (index + 1) for index in range(len(printer_groups) - 1)),
            color="#CBD5E1",
            width=1,
        )
        table._cloud_text_columns = frozenset((0,))

    def _set_usage_granularity(self, granularity: str, checked: bool) -> None:
        if not checked:
            self.usage_granularity_buttons[granularity].setChecked(True)
            return
        self.usage_granularity = granularity
        for code, button in self.usage_granularity_buttons.items():
            button.blockSignals(True)
            button.setChecked(code == granularity)
            button.blockSignals(False)
        self._render_usage()

    def _set_waste_adjustment(self, _checked: bool) -> None:
        """Refresh cost presentation without recalculating stored ledger history."""

        if not hasattr(self, "overview_kpis"):
            return
        caption = (
            "ค่าใช้จ่ายสุทธิ"
            if self.include_waste_adjustment()
            else "ค่าใช้จ่ายก่อนส่วนลด"
        )
        self.overview_kpis["total_cost"].lbl_title.setText(caption)
        printer_caption = getattr(self.printer_kpis["cost"], "_cloud_caption", None)
        if printer_caption is not None:
            printer_caption.setText(caption)
        self._build_printer_rows()
        self._render_overview()
        self._render_printers()
        self._render_usage()

    def _timeline_chart(self, identity: str | None) -> QChart:
        grouped: dict[str, dict[str, float]] = defaultdict(
            lambda: {"print": 0.0, "copy": 0.0}
        )
        for record in self._daily_records:
            if identity and _record_identity(record) != identity:
                continue
            start = str(record.period_start)
            key = start[5:] if len(start) >= 10 else start
            grouped[key]["print"] += _operation_total(record, "print")
            grouped[key]["copy"] += _operation_total(record, "copy")
        labels = list(grouped)[-14:]
        return self._bar_chart(
            tuple(labels),
            (
                ("Print", tuple(grouped[label]["print"] for label in labels), BLUE),
                ("Copy", tuple(grouped[label]["copy"] for label in labels), ORANGE),
            ),
        )

    def _printer_timeline_chart(self, rows: list[dict]) -> QChart:
        """Compare every printer over the same dates; selection changes detail only."""
        by_identity: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: {"print": 0.0, "copy": 0.0})
        )
        all_dates: set[str] = set()
        for record in self._daily_records:
            start = str(record.period_start)
            label = start[5:] if len(start) >= 10 else start
            all_dates.add(label)
            bucket = by_identity[_record_identity(record)][label]
            bucket["print"] += _operation_total(record, "print")
            bucket["copy"] += _operation_total(record, "copy")
        labels = sorted(all_dates)[-14:]
        series_data = tuple(
            series
            for index, row in enumerate(rows)
            for series in (
                (
                    f"{_chart_printer_name(row['name'])} · Print",
                    tuple(
                        by_identity[row["key"]][label]["print"] for label in labels
                    ),
                    DEVICE_COLORS[index % len(DEVICE_COLORS)],
                ),
                (
                    f"{_chart_printer_name(row['name'])} · Copy",
                    tuple(
                        by_identity[row["key"]][label]["copy"] for label in labels
                    ),
                    COPY_COLORS[index % len(COPY_COLORS)],
                ),
            )
        )
        return self._bar_chart(tuple(labels), series_data)

    @staticmethod
    def _multi_line_chart(
        labels: tuple[str, ...],
        series_data: tuple[tuple[str, tuple[float, ...], str], ...],
    ) -> QChart:
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(2, 2, 2, 2))
        if not labels:
            chart.setTitle("ยังไม่มีข้อมูล V4.6 หรือ V5 สำหรับสร้าง Timeline")
            chart.legend().hide()
            return chart
        line_series: list[QLineSeries] = []
        maximum = 0.0
        for name, values, color in series_data:
            series = QLineSeries()
            series.setName(name)
            series.setColor(QColor(color))
            series.setPointsVisible(True)
            for index, value in enumerate(values):
                series.append(float(index), float(value))
                maximum = max(maximum, float(value))
            chart.addSeries(series)
            line_series.append(series)
        axis_x = QBarCategoryAxis()
        axis_x.append(list(labels))
        axis_x.setLabelsAngle(-45)
        axis_y = QValueAxis()
        axis_y.setRange(0, max(1.0, maximum * 1.18))
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for series in line_series:
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)
        chart.legend().setVisible(True)
        return chart

    @staticmethod
    def _horizontal_like_chart(labels: list[str], values: list[float], color: str) -> QChart:
        short = [label if len(label) <= 15 else f"{label[:14]}…" for label in labels]
        return CloudReportsWidget._bar_chart(tuple(short), (("หน้า", tuple(values), color),))

    @staticmethod
    def _bar_chart(categories: tuple[str, ...], series_data: tuple[tuple[str, tuple[float, ...], str], ...]) -> QChart:
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(2, 2, 2, 2))
        if not categories:
            chart.setTitle("ยังไม่มีข้อมูลสำหรับสร้างกราฟ")
            chart.legend().hide()
            return chart
        series = QBarSeries()
        maximum = 0.0
        for name, values, color in series_data:
            bar = QBarSet(name)
            bar.append([float(value) for value in values])
            bar.setColor(QColor(color))
            maximum = max(maximum, *(float(value) for value in values), 0.0)
            series.append(bar)
        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append(list(categories))
        axis_y = QValueAxis()
        axis_y.setRange(0, max(1.0, maximum * 1.18))
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(len(series_data) > 1)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        return chart

    @staticmethod
    def _fill_table(table: QTableWidget, rows: Iterable[Iterable[str]], empty: str = "") -> None:
        materialized = [tuple(str(value).strip() for value in row) for row in rows]
        if hasattr(table, "clearSpans"):
            table.clearSpans()
        if not materialized and empty:
            table.setRowCount(1)
            item = QTableWidgetItem(empty)
            item.setForeground(QColor(MUTED))
            table.setItem(0, 0, item)
            if not isinstance(table, FrozenLeftTable):
                table.setSpan(0, 0, 1, table.columnCount())
            return
        table.setRowCount(len(materialized))
        for row_index, row in enumerate(materialized):
            for column, value in enumerate(row):
                item = QTableWidgetItem(value)
                if column not in table._cloud_text_columns:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column, item)

    def _select_user_row(self, row: int, _column: int, *, toggle: bool = True) -> None:
        if row < 0:
            return
        item = self.users_table.item(row, 0)
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key is None or (not toggle and key == self._selected_user):
            return
        self._selected_user = (
            None if toggle and key == self._selected_user else key
        )
        self._render_users()

    def _clear_user_filter(self) -> None:
        self._selected_user = None
        self.users_table.clearSelection()
        self._render_users()

    def _select_printer_row(self, row: int, _column: int) -> None:
        if row < 0:
            return
        item = self.printers_table.item(row, 0)
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key is None or key == self._selected_printer:
            return
        self._selected_printer = key
        self._render_printers()

    def _clear_printer_filter(self) -> None:
        self._selected_printer = None
        self.printers_table.clearSelection()
        self._render_printers()
