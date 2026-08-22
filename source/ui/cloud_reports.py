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
from PyQt6.QtCore import QDate, QMargins, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
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
from widgets import FrozenLeftTable

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
        self._period: tuple[str, str] | None = None
        self._last_sync_at: str | None = None
        self._selected_user: str | None = None
        self._selected_printer: str | None = None
        self._user_rows: list[dict] = []
        self._printer_rows: list[dict] = []
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
        self.legacy_history_page = self._build_legacy_history()
        self.tabs.addTab(self.overview_page, "Overview")
        self.tabs.addTab(self.users_page, "Users")
        self.tabs.addTab(self.printers_page, "Printers")
        self.tabs.addTab(self.usage_page, "Usage")
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
            "total_cost": _CloudOverviewMetricCard("ค่าใช้จ่ายรวม", accent="#00A651"),
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
        self.overview_printers = _table(("เครื่องพิมพ์", "Color", "B&W", "รวม"))
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
                ("usage", "ยอดใช้งานรวม", "หน้า", BLUE),
                ("average", "เฉลี่ยต่อผู้ใช้", "หน้า", ORANGE),
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
        self.users_table = _table(
            ("User / Account", "ประเภท", "ยอดช่วงนี้", "Total Counter ล่าสุด", "เครื่องที่ใช้", "สถานะ"),
            text_columns=(0, 1, 4, 5),
        )
        self.users_table.setMinimumHeight(220)
        self.users_table.setMaximumHeight(360)
        self.users_table.currentCellChanged.connect(
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
                ("pages", "พิมพ์ / ถ่ายเอกสาร", "หน้า", BLUE),
                ("color", "Color", "หน้า", ORANGE),
                ("bw", "B&W", "หน้า", SLATE),
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
        mix, mix_layout = _panel("Color vs B&W", "แยก Color/B&W รายเครื่อง · ไม่รวม Scan")
        self.printer_mix = self._chart_view()
        mix_layout.addWidget(self.printer_mix)
        charts.addWidget(mix, 2)
        layout.addLayout(charts)
        bottom = QHBoxLayout()
        list_panel, list_layout = _panel("Printers", "คลิกชื่อเครื่องเพื่อดูรายละเอียด โดยกราฟยังแสดงทุกเครื่อง")
        self.printers_table = _table(
            ("เครื่องพิมพ์", "สถานะ", "Color", "B&W", "Scan", "รวม", "ค่าใช้จ่าย"),
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
        continuity_note = QLabel(
            "Timeline รวมตาม Slot · ประวัติ V4.6 ต่อกับ V5 โดยไม่คำนวณ Meter ข้ามการเปลี่ยนเครื่อง "
            "และไม่คิดค่าใช้จ่ายย้อนหลัง"
        )
        continuity_note.setWordWrap(True)
        continuity_note.setStyleSheet(
            "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;"
            "border-radius:6px;padding:9px 11px;"
        )
        panel_layout.addWidget(continuity_note)
        self.usage_timeline_chart = self._chart_view()
        panel_layout.addWidget(self.usage_timeline_chart)
        self.usage_tabs = QTabWidget()
        self.usage_tabs.setObjectName("cloud_usage_tabs")
        self.usage_tabs.tabBar().setExpanding(False)

        all_devices_page = QWidget()
        all_devices_layout = QVBoxLayout(all_devices_page)
        all_devices_layout.setContentsMargins(0, 0, 0, 0)
        self.usage_monthly_table = _table(
            (
                "เดือน",
                "A3 Color",
                "A3 B&W",
                "A4 Color",
                "A4 B&W",
                "Scan",
                "รวม",
                "ค่าใช้จ่ายโดยประมาณ",
            ),
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
            table.setTextElideMode(Qt.TextElideMode.ElideRight)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        per_printer_layout.addWidget(self.usage_by_printer_table, 1)
        self.usage_tabs.addTab(per_printer_page, "ตามเครื่อง")

        panel_layout.addWidget(self.usage_tabs)
        layout.addWidget(panel, 1)
        return page

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
        toolbar_layout.addWidget(start_edit, 0, 2)

        end_label = QLabel("วันที่สิ้นสุด")
        end_label.setObjectName("cloud_period_label")
        end_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toolbar_layout.addWidget(end_label, 0, 3)
        end_edit = self._period_date_edit("วันที่สิ้นสุดของรายงาน")
        end_label.setBuddy(end_edit)
        toolbar_layout.addWidget(end_edit, 0, 4)
        freshness = QLabel("ตัวเลขทั้งหมดในแท็บนี้ใช้ช่วงเวลาเดียวกัน")
        freshness.setObjectName("cloud_subtitle")
        freshness.setWordWrap(True)
        toolbar_layout.addWidget(freshness, 1, 0, 1, 5)
        toolbar_layout.setColumnStretch(4, 1)

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
    def _period_date_edit(accessible_name: str) -> QDateEdit:
        control = QDateEdit()
        control.setObjectName("cloud_period_date")
        control.setAccessibleName(accessible_name)
        control.setCalendarPopup(True)
        control.setDisplayFormat("dd/MM/yyyy")
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
        period: tuple[str, str] | None,
        last_sync_at: str | None,
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
        self._legacy_usage_records = build_legacy_usage_intervals(self._legacy_history)
        self._period = period
        self._last_sync_at = last_sync_at
        self.updated_label.setText(
            f"ข้อมูลล่าสุด {last_sync_at.replace('T', ' ')[:16]}" if last_sync_at else "ยังไม่มีเวลาซิงก์ล่าสุด"
        )
        self._build_user_rows()
        self._build_printer_rows()
        self._render_overview()
        self._render_users()
        self._render_printers()
        self._render_usage()
        self._render_legacy_history()

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
        for item in self._subjects:
            key = f"{item.subject_type}:{item.subject_id}"
            row = grouped.setdefault(
                key,
                {
                    "key": key,
                    "name": item.subject_name,
                    "type": item.subject_type,
                    "usage": 0.0,
                    "latest": 0.0,
                    "printers": defaultdict(float),
                    "review": False,
                },
            )
            identity = _record_identity(item)
            row["usage"] += float(item.period_usage)
            row["latest"] = max(row["latest"], float(item.latest_total))
            row["printers"][identity] += float(item.period_usage)
            row["review"] = row["review"] or bool(item.needs_review)
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
                    "scan": 0.0,
                    "total": 0.0,
                    "cost": 0.0,
                    "review": False,
                },
            )
            row["color"] += sum(_combined(record, name) for name in ("a3_color", "a4_color"))
            row["bw"] += sum(_combined(record, name) for name in ("a3_bw", "a4_bw"))
            row["scan"] += _combined(record, "scan")
            row["total"] += _record_total(record)
            row["cost"] += _combined(record, "net_cost")
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
            [(row["name"], _number(row["color"]), _number(row["bw"]), _number(row["total"])) for row in self._printer_rows[:10]],
            empty="ยังไม่มีข้อมูลเครื่องพิมพ์ในช่วงนี้",
        )
        self.overview_mix.setChart(
            self._bar_chart(
                ("Color", "B&W", "Scan"),
                (("หน้า", (sum(row["color"] for row in self._printer_rows), sum(row["bw"] for row in self._printer_rows), total_scan), BLUE),),
            )
        )
        self.overview_trend.setChart(self._timeline_chart(None))
        apply_language(self)

    def _render_users(self) -> None:
        total = sum(row["usage"] for row in self._user_rows)
        highest = self._user_rows[0]["usage"] if self._user_rows else 0
        self.user_kpis["count"].setText(_number(len(self._user_rows)))
        self.user_kpis["usage"].setText(_number(total))
        self.user_kpis["average"].setText(_number(total / len(self._user_rows) if self._user_rows else 0))
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
        rows = []
        for row in self._user_rows:
            printer_names = [devices_by_identity.get(key, key.replace("serial:", "")) for key in row["printers"]]
            rows.append(
                (
                    row["name"],
                    "User" if row["type"] == "user" else "Account Track",
                    _number(row["usage"]),
                    _number(row["latest"]),
                    ", ".join(printer_names) or "—",
                    "ควรตรวจสอบ" if row["review"] else "พร้อมใช้",
                )
            )
        users_signal_blocker = QSignalBlocker(self.users_table)
        self._fill_table(self.users_table, rows, empty="ยังไม่มีข้อมูล User / Account ในช่วงนี้")
        for index, row in enumerate(self._user_rows):
            self.users_table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row["key"])
        del users_signal_blocker
        apply_language(self)

    def _render_printers(self) -> None:
        rows = self._printer_rows
        total_pages = sum(row["total"] for row in rows)
        total_color = sum(row["color"] for row in rows)
        total_bw = sum(row["bw"] for row in rows)
        total_cost = sum(row["cost"] for row in rows)
        self.printer_kpis["count"].setText(_number(len([row for row in rows if row["total"] > 0])))
        self.printer_kpis["pages"].setText(_number(total_pages))
        self.printer_kpis["color"].setText(_number(total_color))
        self.printer_kpis["bw"].setText(_number(total_bw))
        self.printer_kpis["cost"].setText(_money(total_cost))
        selected = next((row for row in rows if row["key"] == self._selected_printer), None)
        self.printer_mix.setChart(
            self._bar_chart(
                ("Color", "B&W"),
                tuple(
                    (
                        _chart_printer_name(row["name"]),
                        (row["color"], row["bw"]),
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
                (row["name"], status, _number(row["color"]), _number(row["bw"]), _number(row["scan"]), _number(row["total"]), _money(row["cost"]))
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

    @staticmethod
    def _usage_values(record) -> dict[str, float]:
        return {
            "a3_color": _combined(record, "a3_color"),
            "a3_bw": _combined(record, "a3_bw"),
            "a4_color": _combined(record, "a4_color"),
            "a4_bw": _combined(record, "a4_bw"),
            "scan": _combined(record, "scan"),
            "total": _record_total(record),
            "cost": _combined(record, "net_cost"),
        }

    def _render_usage(self) -> None:
        granularity = self.usage_granularity
        period_label = {"D": "วัน", "M": "เดือน", "Y": "ปี"}[granularity]
        period_description = {"D": "รายวัน", "M": "รายเดือน", "Y": "รายปี"}[granularity]
        source_records = self._usage_records(granularity)
        devices_by_slot = {int(device.slot): device for device in self._devices}
        totals_by_period: dict[str, dict] = {}
        by_period_and_printer: dict[tuple[str, str], dict] = {}
        printers: dict[str, tuple[int, str]] = {}
        for record in source_records:
            value_label, period_key = self._usage_period(record, granularity)
            values = self._usage_values(record)
            total_row = totals_by_period.setdefault(
                period_key,
                {"period": value_label, "cost_available": True, **{name: 0.0 for name in values}},
            )
            for name, value in values.items():
                total_row[name] += value
            total_row["cost_available"] = total_row["cost_available"] and self._cost_available(record)

            slot = int(getattr(record, "device_slot", 0))
            identity = f"slot:{slot}"
            printers.setdefault(
                identity,
                (slot, self._slot_label(slot, devices_by_slot, record)),
            )
            printer_row = by_period_and_printer.setdefault(
                (period_key, identity),
                {
                    "cost_available": True,
                    **{name: 0.0 for name in values},
                },
            )
            for name, value in values.items():
                printer_row[name] += value
            printer_row["cost_available"] = (
                printer_row["cost_available"] and self._cost_available(record)
            )

        for device in self._devices:
            slot = int(device.slot)
            identity = f"slot:{slot}"
            printers.setdefault(identity, (slot, self._slot_label(slot, devices_by_slot)))

        usage_fields = ("a3_color", "a3_bw", "a4_color", "a4_bw", "scan", "total", "cost")
        aggregate_rows = [
            (
                row["period"],
                *(
                    self._usage_value_text(
                        name,
                        row[name],
                        available=row["cost_available"] if name == "cost" else True,
                    )
                    for name in usage_fields
                ),
            )
            for _period, row in sorted(totals_by_period.items(), reverse=True)
        ]
        self.usage_monthly_table.horizontalHeaderItem(0).setText(period_label)
        self._fill_table(
            self.usage_monthly_table,
            aggregate_rows,
            empty=f"ยังไม่มีข้อมูลการใช้งาน{period_description}",
        )
        printer_groups = tuple(
            (identity, name)
            for identity, (_slot, name) in sorted(
                printers.items(), key=lambda item: (item[1][0], item[1][1].casefold())
            )
        )
        self._configure_usage_matrix_table(period_label, printer_groups, usage_fields)
        printer_rows = []
        for period_key, row in sorted(totals_by_period.items(), reverse=True):
            values = [row["period"]]
            for identity, _name in printer_groups:
                printer_row = by_period_and_printer.get((period_key, identity), {})
                values.extend(
                    self._usage_value_text(
                        name,
                        printer_row.get(name, 0.0),
                        available=(
                            bool(printer_row.get("cost_available", True))
                            if name == "cost"
                            else True
                        ),
                    )
                    for name in usage_fields
                )
            printer_rows.append(tuple(values))
        self._fill_table(
            self.usage_by_printer_table,
            printer_rows,
            empty=f"ยังไม่มีข้อมูลการใช้งาน{period_description}ของเครื่องพิมพ์",
        )
        chronological = [row for _period, row in sorted(totals_by_period.items())]
        self.usage_timeline_chart.setChart(
            self._line_chart(
                tuple(row["period"] for row in chronological),
                tuple(float(row["total"]) for row in chronological),
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
        metric_labels = (
            "A3 Color",
            "A3 B&W",
            "A4 Color",
            "A4 B&W",
            "Scan",
            "รวม",
            "ค่าใช้จ่ายโดยประมาณ",
        )
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
                table.setColumnWidth(column, 132 if field == "cost" else 82)
        table.setGroupedHeader(
            period_label,
            tuple((name, len(usage_fields)) for _identity, name in printer_groups),
            metric_labels * len(printer_groups),
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

    def _timeline_chart(self, identity: str | None) -> QChart:
        grouped: dict[str, float] = defaultdict(float)
        for record in self._daily_records:
            if identity and _record_identity(record) != identity:
                continue
            start = str(record.period_start)
            grouped[start[5:] if len(start) >= 10 else start] += _record_total(record)
        labels = list(grouped)[-14:]
        values = [grouped[label] for label in labels]
        return self._bar_chart(tuple(labels), (("Print / Copy", tuple(values), BLUE),))

    def _printer_timeline_chart(self, rows: list[dict]) -> QChart:
        """Compare every printer over the same dates; selection changes detail only."""
        by_identity: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        all_dates: set[str] = set()
        for record in self._daily_records:
            start = str(record.period_start)
            label = start[5:] if len(start) >= 10 else start
            all_dates.add(label)
            by_identity[_record_identity(record)][label] += _record_total(record)
        labels = sorted(all_dates)[-14:]
        series_data = tuple(
            (
                _chart_printer_name(row["name"]),
                tuple(by_identity[row["key"]].get(label, 0.0) for label in labels),
                DEVICE_COLORS[index % len(DEVICE_COLORS)],
            )
            for index, row in enumerate(rows)
        )
        return self._bar_chart(tuple(labels), series_data)

    @staticmethod
    def _line_chart(labels: tuple[str, ...], values: tuple[float, ...]) -> QChart:
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(2, 2, 2, 2))
        if not labels:
            chart.setTitle("ยังไม่มีข้อมูล V4.6 หรือ V5 สำหรับสร้าง Timeline")
            chart.legend().hide()
            return chart
        series = QLineSeries()
        series.setName("Usage ตาม Slot")
        series.setColor(QColor(BLUE))
        series.setPointsVisible(True)
        for index, value in enumerate(values):
            series.append(float(index), float(value))
        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append(list(labels))
        axis_x.setLabelsAngle(-45)
        axis_y = QValueAxis()
        maximum = max(values, default=0.0)
        axis_y.setRange(0, max(1.0, maximum * 1.18))
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().hide()
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
