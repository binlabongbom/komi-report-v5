from __future__ import annotations

from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles import reports as report_styles
from ui.styles.reports import (
    NAVY,
    BLUE,
    ORANGE,
    SLATE,
    GREEN,
    MUTED,
    DEVICE_COLORS,
)

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from html import escape

from PyQt6.QtCharts import (
    QBarCategoryAxis,
    QCategoryAxis,
    QBarSeries,
    QStackedBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QValueAxis,
)
from ui.chart_lifecycle import replace_chart
from PyQt6.QtCore import QDate, QEvent, QMargins, QPointF, QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import ENGLISH, apply_language, get_language, translate_text, tr
from ui.numeric_inputs import NumericDateEdit as QDateEdit
from ui.page_tabs import PageTabs as QTabWidget
from ui.page_tabs import PageHeading
from services.legacy_history_import import build_legacy_usage_intervals
from services.report_period_policy import (
    ReportPeriodLimitError, current_preview_period, validate_preview_period,
)
from services.report_models import (
    RawCell, build_legacy_raw_tables, build_user_rows, build_printer_rows,
    _combined, _record_total, _operation_available, _record_name,
)
from widgets import FrozenLeftTable, VisibleCheckBox
from ui.usage_table import UsageTable, PrinterUsageTable
from ui.flow_layout import FlowLayout, FlowLabel, FlowWidget

FIVE_CATEGORIES = ('Print Color', 'Print B&W', 'Copy Color', 'Copy B&W', 'Scan')

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


def _record_identity(record) -> str:
    identity = str(getattr(record, "device_identity", "") or "").strip()
    return identity or f"slot:{int(getattr(record, 'device_slot', 0))}"




class _CloudOverviewMetricCard(QFrame):
    """Overview summary card styled to match the operational Overview page."""

    def __init__(self, title: str, *, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cloud_overview_metric_card")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full_title = title
        self._full_value = "—"
        self._full_detail = ""
        self._compact = None
        self._accent = accent
        self._value_pixel_size = None
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(2)
        layout.setColumnStretch(0, 1)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("cloud_overview_metric_title")
        self.lbl_title.setWordWrap(False)
        self.lbl_val = QLabel("—")
        self.lbl_val.setObjectName("cloud_overview_metric_value")
        self.lbl_val.setStyleSheet(text_styles.label(accent, background='transparent', border='0'))
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_detail = QLabel("")
        self.lbl_detail.setObjectName("cloud_overview_metric_detail")
        for label in (self.lbl_title, self.lbl_val, self.lbl_detail):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.lbl_val.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.lbl_title, 0, 0)
        layout.addWidget(self.lbl_detail, 1, 0)
        layout.addWidget(self.lbl_val, 0, 1, 2, 1)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.lbl_title.setFixedHeight(self.lbl_title.fontMetrics().height())
        self.lbl_detail.setFixedHeight(max(14, self.lbl_detail.fontMetrics().height()))
        value_font = QFont(self.lbl_val.font())
        value_font.setPixelSize(24 if compact else 32)
        text_height = (
            self.lbl_title.height() + self.lbl_detail.height()
            + self.layout().verticalSpacing()
        )
        self.lbl_val.setFixedHeight(QFontMetrics(value_font).height())
        margins = self.layout().contentsMargins()
        self.setFixedHeight(
            max(text_height, self.lbl_val.height())
            + margins.top() + margins.bottom() + 2
        )
        self.refresh_elision()

    def set_metric(self, value: str, detail: str = "", *, available: bool = True) -> None:
        self._full_value = value if available else "—"
        self._full_detail = detail if available else "ไม่มี Counter แยกประเภท"
        self.lbl_val.setToolTip(self._full_value)
        self.lbl_val.setAccessibleName(self._full_value)
        self.lbl_detail.setToolTip(self._full_detail)
        self.refresh_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.refresh_elision()

    def refresh_elision(self) -> None:
        # Values are data: never replace digits with an ellipsis. The grid
        # reflows first, then the value font can fit a particularly long total.
        margins = self.layout().contentsMargins()
        available = max(1, self.contentsRect().width() - margins.left() - margins.right()
                        - self.layout().horizontalSpacing())
        value_limit = max(1, available - min(140, max(40, int(available * 0.45))))
        value_font = QFont(self.lbl_val.font())
        pixel_size = 24 if self._compact else 32
        minimum_size = 16 if self._compact else 20
        while True:
            value_font.setPixelSize(pixel_size)
            natural_width = QFontMetrics(value_font).horizontalAdvance(self._full_value) + 2
            if natural_width <= value_limit or pixel_size == minimum_size:
                break
            pixel_size -= 1
        if self._value_pixel_size != pixel_size:
            self._value_pixel_size = pixel_size
            self.lbl_val.setStyleSheet(
                text_styles.label(self._accent, background='transparent', border='0', font_size=f'{pixel_size}px')
            )
        self.lbl_val.setFixedWidth(min(available, natural_width + 2))
        self.layout().setColumnMinimumWidth(1, self.lbl_val.width())
        self.layout().activate()
        full_title = translate_text(self._full_title) if get_language() == ENGLISH else self._full_title
        self.lbl_title.setToolTip(full_title)
        self.lbl_title.setAccessibleName(full_title)
        self.lbl_title.setText(self.lbl_title.fontMetrics().elidedText(
            full_title, Qt.TextElideMode.ElideRight,
            max(1, self.lbl_title.contentsRect().width()),
        ))
        self.lbl_val.setText(self._full_value)
        full_detail = translate_text(self._full_detail) if get_language() == ENGLISH else self._full_detail
        self.lbl_detail.setToolTip(full_detail)
        detail = self.lbl_detail.fontMetrics().elidedText(
            full_detail, Qt.TextElideMode.ElideRight,
            max(1, self.lbl_detail.contentsRect().width()),
        )
        self._set_detail(detail)

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
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    heading_layout = QVBoxLayout()
    heading_layout.setContentsMargins(0, 0, 0, 0)
    heading_layout.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("cloud_panel_title")
    heading.setWordWrap(True)
    heading_layout.addWidget(heading)
    if subtitle:
        detail = QLabel(subtitle)
        detail.setObjectName("cloud_panel_subtitle")
        detail.setWordWrap(True)
        heading_layout.addWidget(detail)
    layout.addLayout(heading_layout)
    return frame, layout


class CloudReportsWidget(QWidget):
    """Cloud-style presentation for truthful KOMI counter data.

    The widget only presents records supplied by PageHistoryV5. It never reads,
    writes, reconciles, or posts billing data by itself.
    """

    refresh_requested = pyqtSignal()
    export_requested = pyqtSignal()
    export_range_requested = pyqtSignal(object)
    period_changed = pyqtSignal(object)
    reading_status_requested = pyqtSignal()

    def __init__(self, parent=None, *, staged: bool = False) -> None:
        super().__init__(parent)
        self._staged = staged
        self._export_busy = False
        self._has_data = False
        self._data_tab: int | None = None
        self._prepared_models = {}
        self._rendered_tokens = {}
        self._snapshot_token = None
        self._loaded_tabs: set[int] = set()
        self._data_revision = 0
        self._render_generation = 0
        self._pending_render_tail = None
        self._render_tail_timer = QTimer(self)
        self._render_tail_timer.setSingleShot(True)
        self._render_tail_timer.timeout.connect(self._run_render_tail)
        self._row_revisions = {"users": -1, "printers": -1}
        self._loading = False
        self._tab_loading: set[int] = set()
        self._built_tabs: set[int] = set()
        self._tab_hosts: dict[int, QWidget] = {}
        self._tab_placeholders: dict[int, QLabel] = {}
        self._usage_meter_baselines: tuple = ()
        self.users_page = self.printers_page = self.usage_page = None
        self.legacy_raw_page = self.legacy_history_page = None
        self._records: tuple = ()
        self._daily_records: tuple = ()
        self._usage_daily_records: tuple = ()
        self._chart_daily_records: tuple = ()
        self._selected_chart_days: tuple = ()
        self._monthly_records: tuple = ()
        self._subjects: tuple = ()
        self._devices: tuple = ()
        self._legacy_history: tuple = ()
        self._legacy_usage_records: tuple = ()
        self._raw_counter_records: tuple = ()
        self._period: tuple[str, str] | None = None
        self._preview_blocked_period: tuple[str, str] | None = None
        self._last_sync_at: str | None = None
        self._selected_user: str | None = None
        self._user_rows: list[dict] = []
        self._printer_rows: list[dict] = []
        self._usage_selected_slots: set[int] = set()
        self.usage_device_filters: dict[int, VisibleCheckBox] = {}
        self._responsive_grids: list[tuple[QGridLayout, tuple[QWidget, ...], int, int]] = []
        self._period_toolbars: list[tuple[QGridLayout, tuple[QWidget, ...]]] = []
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._apply_responsive_layout)
        self._build()
        self._layout_timer.start(0)
        if self._staged:
            self.export_button.setEnabled(False)

    def _build(self) -> None:
        self.setObjectName("cloud_reports")
        self.setStyleSheet(
            report_styles.base_qss()
        )
        self._base_qss = self.styleSheet()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        self.header = QWidget()
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        heading = QGridLayout(self.header)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)
        self._header_grid = heading
        self._header_title = PageHeading("Reports", "ภาพรวมการใช้งานจากเครื่องพิมพ์ทั้งหมด")
        title = self._header_title.title
        title.setObjectName("cloud_title")
        subtitle = self._header_title.description
        self._header_subtitle = subtitle
        heading.addWidget(self._header_title, 0, 0)
        heading.setColumnStretch(0, 1)
        self.updated_label = QLabel("กำลังอ่านข้อมูลล่าสุด…")
        self.updated_label.setObjectName("cloud_subtitle")
        self.updated_label.setMinimumWidth(0)
        self.updated_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.updated_label.setWordWrap(False)
        self.updated_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.export_button = QPushButton("ส่งออก Excel")
        self.export_button.setObjectName("cloud_export")
        self.export_button.setAccessibleName("ส่งออกรายงานเป็นไฟล์ Excel")
        self.export_button.clicked.connect(self.export_requested.emit)
        heading.addWidget(self.export_button, 0, 2)
        self.refresh_button = QPushButton("รีเฟรช")
        self.refresh_button.setObjectName("cloud_primary")
        self.refresh_button.setAccessibleName("รีเฟรชข้อมูลรายงาน")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self.refresh_button, 0, 3)
        root.addWidget(self.header)

        self.error_label = QLabel("")
        self.error_label.setObjectName("cloud_error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        self.preview_limit_panel = QFrame()
        self.preview_limit_panel.setObjectName('cloud_report_toolbar')
        limit_layout = QHBoxLayout(self.preview_limit_panel)
        limit_layout.setContentsMargins(12, 8, 12, 8)
        self.preview_limit_label = QLabel()
        self.preview_limit_label.setWordWrap(True)
        self.preview_export_button = QPushButton(tr('Export ช่วงที่เลือก', 'Export selected period'))
        self.preview_export_button.setObjectName('cloud_export')
        self.preview_export_button.clicked.connect(
            lambda: self.export_range_requested.emit(self._preview_blocked_period)
            if self._preview_blocked_period is not None else None)
        limit_layout.addWidget(self.preview_limit_label, 1)
        limit_layout.addWidget(self.preview_export_button)
        self.preview_limit_panel.hide()
        root.addWidget(self.preview_limit_panel)

        self.loading_panel = QWidget()
        loading_layout = QHBoxLayout(self.loading_panel)
        loading_layout.setContentsMargins(0, 0, 0, 0)
        loading_layout.setSpacing(6)
        self.loading_indicator = QProgressBar()
        self.loading_indicator.setRange(0, 0)
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.setFixedSize(36, 8)
        self.loading_indicator.setAccessibleName(tr("กำลังโหลดรายงาน", "Loading reports"))
        self.loading_label = QLabel(tr("กำลังโหลดรายงาน…", "Loading reports…"))
        self.loading_label.setObjectName("cloud_subtitle")
        self.loading_label.setWordWrap(True)
        self.loading_label.setMinimumWidth(0)
        self.retry_button = QPushButton(tr("ลองอีกครั้ง", "Retry"))
        self.retry_button.setObjectName("cloud_retry")
        self.retry_button.setToolTip(tr("เริ่มโหลดรายงานอีกครั้ง", "Restart report loading"))
        self.retry_button.clicked.connect(self.refresh_requested.emit)
        loading_layout.addWidget(self.loading_indicator)
        loading_layout.addWidget(self.loading_label, 1)
        loading_layout.addWidget(self.retry_button)
        # Swap status inside a fixed header slot. Loading, long-running work
        # and Retry must never add a row or move the report's viewport.
        self.header_status = QStackedWidget()
        self.header_status.setFixedSize(280, 48)
        self.header_status.addWidget(self.updated_label)
        self.header_status.addWidget(self.loading_panel)
        self._empty_header_status = QWidget()
        self.header_status.addWidget(self._empty_header_status)
        self.header_status.setCurrentWidget(self.updated_label)
        heading.addWidget(self.header_status, 0, 1)
        self._slow_loading_timer = QTimer(self)
        self._slow_loading_timer.setSingleShot(True)
        self._slow_loading_timer.setInterval(5000)
        self._slow_loading_timer.timeout.connect(self._show_slow_loading)

        self.tabs = QTabWidget()
        self.tabs.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.tabs.setObjectName("cloud_report_tabs")
        self.tabs.setDocumentMode(False)
        self.tabs.tabBar().setObjectName("cloud_report_tabbar")
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.period_edit_pairs: list[tuple[QDateEdit, QDateEdit]] = []
        self.overview_page = self._build_overview()
        self.tab_scrolls: list[QScrollArea] = []
        self._built_tabs.add(0)
        if self._staged:
            for index, title in enumerate(("Overview", "Users", "Printers", "Usage", "Legacy")):
                host = QWidget()
                layout = QVBoxLayout(host)
                layout.setContentsMargins(0, 0, 0, 0)
                self._tab_hosts[index] = host
                if index == 0:
                    layout.addWidget(self._scrolling_tab(self.overview_page))
                else:
                    placeholder = QLabel("กำลังเตรียมรายงาน…")
                    placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    layout.addWidget(placeholder)
                    self._tab_placeholders[index] = placeholder
                self.tabs.addTab(host, title)
        else:
            self.users_page = self._build_users()
            self.printers_page = self._build_printers()
            self.usage_page = self._build_usage()
            self.legacy_raw_page = self._build_legacy_raw()
            self.legacy_history_page = self._build_legacy_history()
            for page, title in (
                (self.overview_page, "Overview"), (self.users_page, "Users"),
                (self.printers_page, "Printers"), (self.usage_page, "Usage"),
                (self.legacy_raw_page, "Legacy"),
            ):
                self.tabs.addTab(self._scrolling_tab(page), title)
            self._built_tabs.update(range(5))
        self.tabs.currentChanged.connect(self._render_selected_tab)
        root.addWidget(self.tabs, 1)

    @property
    def has_data(self) -> bool:
        return self._has_data and (self._data_tab is None or self.tabs.currentIndex() in self._loaded_tabs)

    def _can_render_tab(self, index: int) -> bool:
        return (self._preview_blocked_period is None and index in self._built_tabs and self._has_data
                and (self._data_tab is None or self._data_tab == index))

    @property
    def built_tabs(self) -> frozenset[int]:
        return frozenset(self._built_tabs)

    def ensure_tab(self, index: int) -> QWidget:
        """Construct one public tab once without changing the selected index."""
        if index not in range(5):
            raise ValueError("Report tab index must be between 0 and 4")
        if index not in self._built_tabs:
            attributes = ("overview_page", "users_page", "printers_page", "usage_page", "legacy_raw_page")
            builders = (self._build_overview, self._build_users, self._build_printers,
                        self._build_usage, self._build_legacy_raw)
            page = builders[index]()
            setattr(self, attributes[index], page)
            if index == 4:
                self.legacy_history_page = self._build_legacy_history()
            placeholder = self._tab_placeholders.pop(index)
            host = self._tab_hosts[index]
            host.layout().removeWidget(placeholder)
            placeholder.deleteLater()
            host.layout().addWidget(self._scrolling_tab(page))
            self._built_tabs.add(index)
            if self._period is not None:
                self.set_periods((), self._period)
            if index == 3 and self._can_render_tab(3):
                self._sync_usage_device_filters()
            # New children inherit the existing stylesheet. Invalidating the
            # density here restyled every already-built tab on each first visit.
            self._layout_timer.start(0)

        return self.tabs.widget(index)

    def prewarm_tab(self, index: int) -> QWidget:
        return self.ensure_tab(index)

    def set_loading(self, loading: bool) -> None:
        was_loading = self._loading
        self._loading = bool(loading)
        if loading:
            self._cancel_render_tail()
            self.error_label.hide()
            if not was_loading:
                self._slow_loading_timer.start()
                self.loading_label.setText(tr("กำลังอัปเดตรายงาน…", "Updating reports…") if self.has_data
                                           else tr("กำลังโหลดรายงาน…", "Loading reports…"))
        else:
            self._slow_loading_timer.stop()
        self._update_loading_visibility()

    def set_tab_loading(self, index: int, loading: bool) -> None:
        if index not in range(5):
            raise ValueError("Report tab index must be between 0 and 4")
        if loading:
            if index == self.tabs.currentIndex():
                self._cancel_render_tail()
            self._tab_loading.add(index)
        else:
            self._tab_loading.discard(index)
        self._update_loading_visibility()

    def _update_loading_visibility(self) -> None:
        tail_busy = self._pending_render_tail is not None and self._pending_render_tail[2] == self.tabs.currentIndex()
        busy = self._loading or self.tabs.currentIndex() in self._tab_loading or tail_busy
        self.header_status.setCurrentWidget(
            self.loading_panel if busy or not self.error_label.isHidden() else
            self._empty_header_status if self._preview_blocked_period is not None else self.updated_label)
        self.loading_indicator.setVisible(busy)
        if busy and not self._slow_loading_timer.isActive() and not self._loading:
            self.loading_label.setText(tr("กำลังโหลดรายงาน…", "Loading reports…"))
            self._slow_loading_timer.start()
        if not busy:
            self._slow_loading_timer.stop()
        self.retry_button.setVisible(not busy or not self._slow_loading_timer.isActive())
        self.export_button.setEnabled(not self._export_busy and (
            self.has_data or self._preview_blocked_period is not None or not self._staged))
        self.preview_export_button.setEnabled(not self._export_busy)

    def set_export_busy(self, busy: bool) -> None:
        self._export_busy = busy
        self.export_button.setText("กำลังส่งออก…" if busy else "ส่งออก Excel")
        self._update_loading_visibility()

    def _show_slow_loading(self) -> None:
        if self._loading or self.tabs.currentIndex() in self._tab_loading:
            self.loading_label.setText(tr("ใช้เวลานานกว่าปกติ · ยังโหลดอยู่", "Taking longer · Still loading"))
            self.retry_button.show()

    def _scrolling_tab(self, page: QWidget) -> QWidget:
        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(wrapper)
        # Hidden tabs must not retain a minimum width from an earlier toolbar arrangement.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        first = page.layout().itemAt(0)
        if first is not None and first.widget() is not None:
            toolbar = first.widget()
            if toolbar.objectName() == "cloud_report_toolbar":
                page.layout().removeWidget(toolbar)
                layout.addWidget(toolbar, 0, Qt.AlignmentFlag.AlignTop)
        page.layout().setContentsMargins(0, 0, 0, 0)
        if page in (self.overview_page, self.users_page, self.printers_page):
            page.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setObjectName("cloud_tab_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumSize(0, 0)
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        scroll.setWidget(page)
        scroll.viewport().installEventFilter(self)
        scroll.setVisible(self._preview_blocked_period is None)
        self.tab_scrolls.append(scroll)
        layout.addWidget(scroll, 1)
        return wrapper

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if hasattr(self, "_layout_timer"):
            self._layout_timer.start(0)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize:
            self._layout_timer.start(0)
        return super().eventFilter(watched, event)

    @staticmethod
    def _place_grid(grid: QGridLayout, widgets: tuple[QWidget, ...], columns: int) -> None:
        if getattr(grid, "_report_columns", None) == columns:
            return
        for widget in widgets:
            grid.removeWidget(widget)
        for column in range(max(grid.columnCount(), columns)):
            grid.setColumnStretch(column, 1 if column < columns else 0)
            grid.setColumnMinimumWidth(column, 0)
        for index, widget in enumerate(widgets):
            grid.addWidget(widget, index // columns, index % columns)
        grid._report_columns = columns

    def _set_density(self, compact: bool) -> None:
        if getattr(self, "_compact_density", None) == compact:
            return
        self._compact_density = compact
        self.tabs.set_compact(compact)
        density_qss = report_styles.density_qss(compact)
        self.setStyleSheet(self._base_qss + density_qss)
        self._header_subtitle.setVisible(True)
        for card in self.overview_kpis.values():
            card.set_compact(compact)

    def _apply_responsive_layout(self) -> None:
        if not hasattr(self, "tab_scrolls"):
            return
        margins = self.layout().contentsMargins()
        width = max(1, self.width() - margins.left() - margins.right())
        self._set_density(width < 1100 or self.height() < 760)
        compact_header = width < 520
        self.header_status.setFixedWidth(min(280, max(120, width - 216)))
        if getattr(self, "_compact_header", None) != compact_header:
            grid = self._header_grid
            widgets = (self._header_title, self.header_status, self.export_button, self.refresh_button)
            for widget in widgets:
                grid.removeWidget(widget)
            if compact_header:
                grid.addWidget(self._header_title, 0, 0, 1, 4)
                grid.addWidget(self.header_status, 1, 1)
                grid.addWidget(self.export_button, 1, 2)
                grid.addWidget(self.refresh_button, 1, 3)
            else:
                for column, widget in enumerate(widgets):
                    grid.addWidget(widget, 0, column)
            self._compact_header = compact_header
        for grid, widgets in self._period_toolbars:
            # The two calendar groups remain intact when moved to another row.
            margins = grid.contentsMargins()
            wide_minimum = (
                sum(max(w.minimumWidth(), w.minimumSizeHint().width()) for w in widgets[:5])
                + 5 * grid.horizontalSpacing() + margins.left() + margins.right()
            )
            mode = 0 if width >= max(740, wide_minimum) else (1 if width >= 540 else 2)
            if getattr(grid, "_report_mode", None) == mode:
                continue
            for widget in widgets:
                grid.removeWidget(widget)
            for column in range(7):
                grid.setColumnStretch(column, 0)
            title, start_label, start, end_label, end, note = widgets
            if mode == 0:
                for column, widget in enumerate(widgets[:5]):
                    grid.addWidget(widget, 0, column)
                grid.addWidget(note, 1, 0, 1, 7)
                grid.setColumnStretch(6, 1)
            elif mode == 1:
                grid.addWidget(title, 0, 0, 2, 1)
                grid.addWidget(start_label, 0, 1)
                grid.addWidget(start, 0, 2)
                grid.addWidget(end_label, 1, 1)
                grid.addWidget(end, 1, 2)
                grid.addWidget(note, 2, 0, 1, 4)
                grid.setColumnStretch(4, 1)
            else:
                grid.addWidget(title, 0, 0, 1, 2)
                grid.addWidget(start_label, 1, 0)
                grid.addWidget(start, 1, 1)
                grid.addWidget(end_label, 2, 0)
                grid.addWidget(end, 2, 1)
                grid.addWidget(note, 3, 0, 1, 2)
                grid.setColumnStretch(1, 1)
            grid._report_mode = mode
            grid.invalidate()
            grid.activate()
            toolbar = grid.parentWidget()
            toolbar.updateGeometry()
            wrapper = toolbar.parentWidget()
            if wrapper is not None and wrapper.layout() is not None:
                wrapper.layout().invalidate()
                wrapper.layout().activate()
                wrapper.updateGeometry()
        for grid, widgets, minimum, maximum in self._responsive_grids:
            parent = grid.parentWidget()
            available = max(1, parent.width() - grid.contentsMargins().left() - grid.contentsMargins().right())
            if widgets and isinstance(widgets[0], _CloudOverviewMetricCard):
                columns = 3 if available >= 900 else (2 if available >= 560 else 1)
                self._place_grid(grid, widgets, columns)
                for card in widgets:
                    card.refresh_elision()
                continue
            columns = max(1, min(maximum, (available + 12) // (minimum + 12)))
            self._place_grid(grid, widgets, columns)
            # Qt's grid can retain a one-line size hint while a flow legend
            # wraps. Reserve its height at the actual column width so that it
            # never overlaps the fixed-height chart or its axis labels.
            if widgets and all(widget.findChild(QChartView) is not None for widget in widgets):
                panel_width = max(1, (available - max(0, grid.horizontalSpacing()) * (columns - 1)) // columns)
                heights = [max(widget.minimumSizeHint().height(), widget.heightForWidth(panel_width))
                           for widget in widgets]
                for index, widget in enumerate(widgets):
                    widget.setMinimumHeight(max(heights) if columns > 1 else heights[index])
        if hasattr(self, "printers_table"):
            self._size_printers_table()
        for page in (self.overview_page, self.users_page, self.printers_page):
            # QScrollArea otherwise keeps the previous page height when a
            # nested flow layout changes its minimum after the initial show.
            if page is not None:
                page.layout().invalidate()
                page.setMinimumHeight(page.layout().minimumSize().height())
        self._layout_usage_device_filters()

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
        kpis.setHorizontalSpacing(8)
        kpis.setVerticalSpacing(8)
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
        cards = tuple(self.overview_kpis[key] for key in (
            "color_print", "bw_print", "total_usage", "color_copy", "bw_copy", "total_cost",
        ))
        for column, card in enumerate(cards):
            kpis.addWidget(card, 0, column)
            kpis.setColumnStretch(column, 1)
        self._responsive_grids.append((kpis, cards, 100, 6))
        layout.addWidget(self.overview_kpi_panel)
        grid = QGridLayout()
        grid.setSpacing(12)
        trend, trend_layout = _panel("Print / Copy timeline", "14 วันล่าสุดในช่วงรายงาน · Print และ Copy ซ้อนยอด A4/A3")
        self.overview_trend = self._chart_view()
        trend_layout.addWidget(self.overview_trend)
        self.overview_trend_legend = FlowWidget()
        trend_layout.addWidget(self.overview_trend_legend)
        grid.addWidget(trend, 0, 0)
        mix, mix_layout = _panel("Print / Copy / Scan", "A4 สีเข้ม · A3 สีอ่อน")
        self.overview_mix = self._chart_view()
        mix_layout.addWidget(self.overview_mix)
        self.overview_mix_legend = FlowWidget()
        mix_layout.addWidget(self.overview_mix_legend)
        for panel in (trend, mix):
            panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        trend_layout.addStretch(1)
        mix_layout.addStretch(1)
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
        self._responsive_grids.append((grid, (trend, mix, users, printers), 410, 2))
        layout.addLayout(grid)
        return page

    def _build_users(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
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
        charts = QGridLayout()
        top, top_layout = _panel("Top users", "เรียงตามยอดใช้งานในช่วงที่เลือก")
        self.users_top_chart = self._chart_view()
        self.users_top_chart.setFixedHeight(150)
        top_layout.addWidget(self.users_top_chart)
        charts.addWidget(top, 0, 0)
        printer, printer_layout = _panel("Printers used", "กดผู้ใช้เพื่อดูการกระจายตามเครื่อง")
        self.users_printer_chart = self._chart_view()
        self.users_printer_chart.setFixedHeight(150)
        printer_layout.addWidget(self.users_printer_chart)
        charts.addWidget(printer, 0, 1)
        self._responsive_grids.append((charts, (top, printer), 360, 2))
        layout.addLayout(charts)
        table_panel, table_layout = _panel(
            "Users",
            "ค่าใช้จ่ายจัดสรรจากยอดรายวันของแต่ละเครื่อง · — หมายถึงข้อมูลยังไม่ครบสำหรับคำนวณ",
        )
        heading = table_layout.itemAt(0).layout()
        title = heading.takeAt(0).widget()
        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addStretch()
        self.user_overview_button = QPushButton(tr('ภาพรวม', 'Overview'))
        self.user_printers_button = QPushButton(tr('รายเครื่อง', 'By printer'))
        self._user_table_mode = 'overview'
        for button, mode in ((self.user_overview_button, 'overview'), (self.user_printers_button, 'printers')):
            button.setCheckable(True)
            button.setObjectName('cloud_reset')
            button.setStyleSheet(report_styles.CLOUD_REPORTS_WIDGET_BUTTON)
            button.clicked.connect(lambda _checked, value=mode: self._set_user_table_mode(value))
            title_row.addWidget(button)
        self.user_overview_button.setChecked(True)
        heading.insertLayout(0, title_row)
        self._expanded_user_printers = {'all'}
        self.users_table = PrinterUsageTable()
        self.users_table._row_h = 34
        self.users_table._frozen_min_width = 180
        self.users_table._frozen_max_width = 240
        self.users_table._cloud_text_columns = frozenset((0,))
        for table in (self.users_table._left, self.users_table._right):
            table.verticalHeader().setDefaultSectionSize(34)
            table.setAlternatingRowColors(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.users_table.setMinimumHeight(340)
        self.users_table.setMaximumHeight(620)
        self.users_table._left.currentCellChanged.connect(
            lambda row, column, _previous_row, _previous_column: self._select_user_row(
                row, column, toggle=False
            )
        )
        self.users_table.printer_toggled.connect(self._toggle_user_printer)
        table_layout.addWidget(self.users_table)
        layout.addWidget(table_panel)
        return page

    def _set_user_table_mode(self, mode: str) -> None:
        self._user_table_mode = mode
        self.user_overview_button.setChecked(mode == 'overview')
        self.user_printers_button.setChecked(mode == 'printers')
        self._render_users_table()

    def _build_printers(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
        charts = QGridLayout()
        trend, trend_layout = _panel("Usage timeline", "14 วันล่าสุดในช่วงรายงาน · วันละหนึ่งแท่ง ซ้อน Color/B&W ของทุกเครื่อง")
        self.printer_trend = self._chart_view()
        trend_layout.addWidget(self.printer_trend)
        self.printer_trend_legend = FlowWidget()
        trend_layout.addWidget(self.printer_trend_legend)
        charts.addWidget(trend, 0, 0)
        mix, mix_layout = _panel(
            "Print / Copy / Scan", "A4 สีเข้ม · A3 สีอ่อน"
        )
        self.printer_mix = self._chart_view()
        mix_layout.addWidget(self.printer_mix)
        self.printer_mix_legend = FlowWidget()
        mix_layout.addWidget(self.printer_mix_legend)
        charts.addWidget(mix, 0, 1)
        # Fill the shared grid row even when the legends have different heights.
        # Keep each panel's contents top-aligned so both plots start together.
        for panel in (trend, mix):
            panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        trend_layout.addStretch(1)
        mix_layout.addStretch(1)
        self._responsive_grids.append((charts, (trend, mix), 410, 2))
        layout.addLayout(charts)
        bottom = QVBoxLayout()
        list_panel, list_layout = _panel("Printers", "ยอดรายเครื่องในช่วงที่เลือก")
        self.printers_table = _table(
            ("เครื่องพิมพ์", "สถานะ", "Print Color", "Print B&W", "Copy Color", "Copy B&W", "Scan", "รวม", "ค่าใช้จ่าย"),
            text_columns=(0, 1),
        )
        self.printers_table.setFixedHeight(240)
        self.printers_table.setWordWrap(True)
        self.printers_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.printers_table.horizontalHeader().setStretchLastSection(False)
        list_layout.addWidget(self.printers_table)
        bottom.addWidget(list_panel)
        layout.addLayout(bottom)
        return page

    def _build_usage(self) -> QWidget:
        """Show recorded usage at daily, monthly, or yearly level."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self._add_period_toolbar(layout)
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
        self.usage_waste_checkbox = VisibleCheckBox("หักส่วนลดกระดาษเสียจากค่าใช้จ่าย")
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
            button = QPushButton(tooltip)
            button.setObjectName("cloud_granularity")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setChecked(code == self.usage_granularity)
            button.clicked.connect(lambda checked, value=code: self._set_usage_granularity(value, checked))
            head.addWidget(button)
            self.usage_granularity_buttons[code] = button
        panel_layout.addLayout(head)
        self.usage_filter_title = QLabel(tr("เครื่องพิมพ์ที่แสดง", "Displayed printers"))
        self.usage_filter_title.setObjectName("cloud_panel_subtitle")
        self.usage_device_filter_container = QWidget()
        self.usage_device_filter_container.setMinimumWidth(0)
        self.usage_device_filter_container.installEventFilter(self)
        self.usage_device_filter_layout = FlowLayout(self.usage_device_filter_container, spacing=16)
        self.usage_device_filter_layout.addWidget(self.usage_filter_title)
        panel_layout.addWidget(self.usage_device_filter_container)
        self.usage_tabs = QTabWidget()
        self.usage_tabs.setObjectName("cloud_usage_tabs")
        self.usage_tabs.tabBar().setExpanding(False)

        all_devices_page = QWidget()
        all_devices_layout = QVBoxLayout(all_devices_page)
        all_devices_layout.setContentsMargins(0, 0, 0, 0)
        self.usage_monthly_table = UsageTable()
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
            self._compact_usage_labels(),
        )
        self.usage_monthly_table.setGroupSeparators(
            (5, 10, 11, 12),
            color="#CBD5E1",
            width=1,
        )
        all_devices_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        all_devices_layout.addWidget(self.usage_monthly_table)
        self.usage_tabs.addTab(all_devices_page, "ทุกเครื่อง")

        per_printer_page = QWidget()
        self.usage_printer_layout = QVBoxLayout(per_printer_page)
        self.usage_printer_layout.setContentsMargins(0, 0, 0, 0)
        self.usage_printer_layout.setSpacing(10)
        self.usage_printer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._expanded_usage_printers = set()
        self._usage_comparison_data = None
        self.usage_printer_table = PrinterUsageTable()
        self.usage_printer_table.printer_toggled.connect(self._toggle_usage_printer)
        self.usage_printer_layout.addWidget(self.usage_printer_table)
        self.usage_tabs.addTab(per_printer_page, "ตามเครื่อง")

        panel_layout.addWidget(self.usage_tabs)
        layout.addWidget(panel, 1)
        return page

    @staticmethod
    def _compact_usage_labels():
        paper = (tr('A3 สี', 'A3 Color'), tr('A3 ข/ด', 'A3 B&W'),
                 tr('A4 สี', 'A4 Color'), tr('A4 ข/ด', 'A4 B&W'), tr('อื่น ๆ', 'Other'))
        return paper * 2 + (tr('หน้า', 'Pages'), tr('หน้า', 'Pages'), tr('บาท', 'THB'))

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
            surfaces_styles.INFO_NOTICE
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
            surfaces_styles.INFO_NOTICE
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
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        title = QLabel(tr('ช่วงรายงาน · สูงสุด 12 เดือน', 'Report period · up to 12 months'))
        title.setStyleSheet(text_styles.label('#25364A', font_weight='750'))
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
        # The date range remains visible; the explanatory note is available on hover.
        toolbar.setToolTip(freshness.text())
        freshness.hide()
        toolbar_layout.addWidget(freshness, 1, 0, 1, 7)
        toolbar_layout.setColumnStretch(6, 1)

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
        self._period_toolbars.append((toolbar_layout, (title, start_label, start_control, end_label, end_control, freshness)))
        layout.addWidget(toolbar)

    @staticmethod
    def _calendar_control(editor: CalendarDateEdit) -> QWidget:
        host = QWidget()
        host.setObjectName("cloud_calendar_control")
        host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(editor)
        button = QPushButton("📅")
        button.setObjectName("cloud_calendar_button")
        button.setProperty("uiButtonRole", "compact-icon")
        button.setFixedSize(24, 24)
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
        control.setMaximumWidth(156)
        calendar = control.calendarWidget()
        calendar.setGridVisible(True)
        calendar.setStyleSheet(
            report_styles.PERIOD_CALENDAR
        )
        return control

    @staticmethod
    def _chart_view() -> QChartView:
        view = QChartView()
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setFixedHeight(240)
        view.setStyleSheet(report_styles.CLOUD_REPORTS_WIDGET_CHART_VIEW)
        return view


    def set_periods(
        self,
        periods: Iterable[tuple[str, str]],
        selected: tuple[str, str] | None,
    ) -> None:
        selected = selected or current_preview_period()

        # Available history must not disable historical calendar dates.
        # A selected range without records is an empty report.
        start_value = QDate.fromString(selected[0], "yyyy-MM-dd")
        end_value = QDate.fromString(selected[1], "yyyy-MM-dd")
        self._period = selected
        for start_edit, end_edit in self.period_edit_pairs:
            start_edit.blockSignals(True)
            end_edit.blockSignals(True)
            start_edit.setDate(start_value)
            end_edit.setDate(end_value)
            start_edit.blockSignals(False)
            end_edit.blockSignals(False)
        self.show_preview_period_limit(selected)

    def show_preview_period_limit(self, selected: tuple[str, str]) -> bool:
        """Keep both date editors usable, but never show old totals for a rejected range."""
        try:
            validate_preview_period(selected)
        except ReportPeriodLimitError:
            self._preview_blocked_period = selected
            self._cancel_render_tail()
            self._tab_loading.clear()
            self.error_label.hide()
            self.set_loading(False)
            start, end = map(date.fromisoformat, selected)
            self.preview_limit_label.setText(tr(
                'ช่วง {start}–{end} เกิน 12 เดือน จึงยังไม่โหลด Preview\n'
                'เลือกช่วงไม่เกิน 12 เดือนจากปีใดก็ได้ หรือ Export Excel ได้สูงสุด 5 ปีต่อไฟล์',
                'The selected period {start}–{end} exceeds 12 months. Preview has not been loaded.\n'
                'Choose up to 12 months from any year, or export up to 5 years per Excel file.'
            ).format(start=start.strftime('%d/%m/%Y'), end=end.strftime('%d/%m/%Y')))
        else:
            self._preview_blocked_period = None
        blocked = self._preview_blocked_period is not None
        self.preview_limit_panel.setVisible(blocked)
        for scroll in self.tab_scrolls:
            scroll.setVisible(not blocked)
        self._update_loading_visibility()
        return not blocked

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
        self.set_periods((), selected)
        self.period_changed.emit(selected)

    def show_error(self, message: str) -> None:
        self._cancel_render_tail()
        self._tab_loading.clear()
        self.set_loading(False)
        self.error_label.setText(message)
        self.error_label.show()
        self.loading_label.setText(tr("โหลดรายงานไม่สำเร็จ", "Report loading failed"))
        if self._staged and self.has_data:
            self.loading_label.setText(tr("โหลดไม่สำเร็จ · แสดงข้อมูลเดิม", "Load failed · Previous data shown"))
        self._update_loading_visibility()
        if self._staged:
            return
        for card in self.overview_kpis.values():
            card.set_metric("—", "")

    def set_data(
        self,
        *,
        records: Iterable,
        daily_records: Iterable,
        usage_daily_records: Iterable | None = None,
        chart_daily_records: Iterable | None = None,
        monthly_records: Iterable | None = None,
        subjects: Iterable,
        devices: Iterable,
        legacy_history: Iterable | None = None,
        raw_counter_records: Iterable | None = None,
        category_costs: Iterable = (),
        period: tuple[str, str] | None,
        last_sync_at: str | None,
        usage_meter_baselines: Iterable | None = None,
        tab_index: int | None = None,
        prepared_models=None,
        snapshot_token=None,
    ) -> bool:
        if period is not None:
            validate_preview_period(period)
            if self._period != period or self._preview_blocked_period is not None:
                self.set_periods((), period)
        if tab_index is not None and tab_index not in range(5):
            raise ValueError("Report tab index must be between 0 and 4")
        self._data_tab = tab_index
        self._prepared_models = prepared_models or {}
        self._snapshot_token = (snapshot_token, get_language(), self.include_waste_adjustment()) if snapshot_token is not None else None
        loaded_index = self.tabs.currentIndex() if tab_index is None else tab_index
        self._loaded_tabs.add(loaded_index)
        self._tab_loading.discard(loaded_index)
        self.error_label.hide()
        self._has_data = True
        self.set_loading(False)
        self._records = tuple(records)
        self._daily_records = tuple(daily_records)
        self._usage_daily_records = (
            tuple(usage_daily_records) if usage_daily_records is not None else self._daily_records
        )
        self._chart_daily_records = tuple(chart_daily_records) if chart_daily_records is not None else self._usage_daily_records
        self._selected_chart_days = tuple(r for r in self._chart_daily_records
            if period is None or (str(r.period_start) <= period[1] and str(r.period_end) >= period[0]))
        self._monthly_records = tuple(monthly_records) if monthly_records is not None else self._records
        self._subjects = tuple(subjects)
        self._devices = tuple(devices)
        self._legacy_history = tuple(legacy_history or ())
        self._raw_counter_records = tuple(raw_counter_records or ())
        self._category_costs = tuple(category_costs)
        self._usage_meter_baselines = tuple(usage_meter_baselines or ())
        self._legacy_usage_records = build_legacy_usage_intervals(self._legacy_history)
        self._period = period
        self._last_sync_at = last_sync_at
        self._sync_usage_device_filters()
        self.updated_label.setText(
            f"ข้อมูลล่าสุด {last_sync_at.replace('T', ' ')[:16]}" if last_sync_at else "ยังไม่มีเวลาซิงก์ล่าสุด"
        )
        self._data_revision += 1
        if self._snapshot_token is not None and self._rendered_tokens.get(loaded_index) == self._snapshot_token:
            if loaded_index in (0, 1):
                self._build_user_rows()
            if loaded_index in (0, 2):
                self._build_printer_rows()
            self._update_loading_visibility()
            return False
        if not self._staged:
            self._build_user_rows()
            self._build_printer_rows()
        self._render_selected_tab(self.tabs.currentIndex())
        return True

    def _render_selected_tab(self, index: int) -> None:
        self._cancel_render_tail()
        if not 0 <= index < 5:
            return
        self.ensure_tab(index)
        self._update_loading_visibility()
        if self._preview_blocked_period is not None:
            return
        if self._staged and not self._can_render_tab(index):
            return
        if self._staged:
            if index in (0, 1) and self._row_revisions["users"] != self._data_revision:
                self._build_user_rows()
                self._row_revisions["users"] = self._data_revision
            if index in (0, 2) and self._row_revisions["printers"] != self._data_revision:
                self._build_printer_rows()
                self._row_revisions["printers"] = self._data_revision
        renderers = (
            self._render_overview,
            self._render_users,
            self._render_printers,
            self._render_usage,
            lambda: (self._render_legacy_raw(), self._render_legacy_history()),
        )
        if 0 <= index < len(renderers):
            renderers[index]()
            if self._pending_render_tail is None and self._snapshot_token is not None:
                self._rendered_tokens[index] = self._snapshot_token
            self._layout_timer.start(0)

    def _cancel_render_tail(self) -> None:
        self._render_generation += 1
        self._pending_render_tail = None
        self._render_tail_timer.stop()

    def _schedule_render_tail(self, index: int, tables, charts) -> None:
        if not self._staged:
            tables()
            charts()
            return
        self._cancel_render_tail()
        self._pending_render_tail = (
            self._data_revision, self._render_generation, index, tables, charts,
        )
        self._update_loading_visibility()
        self.loading_label.setText(tr("กำลังเตรียมตาราง…", "Preparing tables…"))
        self._render_tail_timer.start(0)

    def _run_render_tail(self) -> None:
        pending = self._pending_render_tail
        self._pending_render_tail = None
        if pending is None:
            return
        revision, generation, index, tables, charts = pending
        if (revision != self._data_revision or generation != self._render_generation
                or index != self.tabs.currentIndex() or not self._can_render_tab(index)):
            return
        if tables is not None:
            tables()
            if revision != self._data_revision or generation != self._render_generation:
                return
            # Yield once more so completed tables can paint before chart construction.
            self._pending_render_tail = (revision, generation, index, None, charts)
            self.loading_label.setText(tr("กำลังวาดกราฟ…", "Drawing charts…"))
            self._render_tail_timer.start(0)
        else:
            charts()
            if self._snapshot_token is not None:
                self._rendered_tokens[index] = self._snapshot_token
            self._update_loading_visibility()
            self._layout_timer.start(0)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._cancel_render_tail()
        super().closeEvent(event)

    def _sync_usage_device_filters(self) -> None:
        if not hasattr(self, "usage_device_filter_layout") or (self._staged and not self._can_render_tab(3)):
            return
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
                checkbox.setParent(self.usage_device_filter_container)
                checkbox.show()
            else:
                checkbox.setText(label)
                checkbox.show()
        for slot, checkbox in self.usage_device_filters.items():
            if slot not in slots:
                checkbox.hide()
                self._usage_selected_slots.discard(slot)
        self._usage_filter_slots = slots
        self._layout_usage_device_filters()

    def _layout_usage_device_filters(self):
        if not hasattr(self, 'usage_device_filter_container'):
            return
        boxes = tuple(self.usage_device_filters[slot] for slot in getattr(self, '_usage_filter_slots', ()))
        flow = self.usage_device_filter_layout
        current = tuple(flow.itemAt(i).widget() for i in range(flow.count()))
        if current != (self.usage_filter_title, *boxes):
            while flow.count():
                flow.takeAt(0)
            for widget in (self.usage_filter_title, *boxes):
                flow.addWidget(widget)
        flow.invalidate()

    def _set_usage_slot_selected(self, slot: int, checked: bool) -> None:
        if checked:
            self._usage_selected_slots.add(slot)
        else:
            self._usage_selected_slots.discard(slot)
        self._render_usage()


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
        if self._staged and not self._can_render_tab(4):
            return
        models = self._prepared_models.get("legacy_raw")
        if models is None:
            models = build_legacy_raw_tables(self._raw_counter_records, self._devices)
        def display(value):
            if value is None:
                return "—"
            if isinstance(value, RawCell):
                suffix = " · " + tr("รอตรวจสอบยอดมิเตอร์", "Meter usage needs review") if value.needs_review else ""
                return _number(value.total) + suffix
            return value
        for table, model, empty, text_columns in zip(
            (self.legacy_machine_table, self.legacy_user_table, self.legacy_daily_table), models,
            ("ยังไม่มี Raw Counter ในช่วงวันที่เลือก", "ยังไม่มี Raw Counter แยกผู้ใช้ / Account ในช่วงวันที่เลือก", "ยังไม่มี Raw Counter รายวันในช่วงวันที่เลือก"),
            ((0, 1), (0,), (0,)),
        ):
            self._configure_raw_table(table, model.headers,
                tuple(tuple(display(value) for value in row) for row in model.rows),
                empty=empty, text_columns=text_columns)

    def _render_legacy_history(self) -> None:
        if self._staged and not self._can_render_tab(4):
            return
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
        prepared = self._prepared_models.get("users")
        self._user_rows = list(prepared if prepared is not None else build_user_rows(self._subjects, self._raw_counter_records, category_costs=getattr(self, "_category_costs", ())))
        if self._selected_user and not any(row["key"] == self._selected_user for row in self._user_rows):
            self._selected_user = None

    def _build_printer_rows(self) -> None:
        prepared = self._prepared_models.get("printers")
        if prepared is None:
            prepared = build_printer_rows(self._records, self._devices)
        field = self._cost_field()
        self._printer_rows = [dict(row, cost=row[field]) for row in prepared]

    def _report_cost_detail(self):
        provisional = any(int(getattr(record, "provisional_days", 0) or 0) for record in self._records)
        return tr("รวมยอดประมาณการ · ยังไม่ลงบัญชีครบ", "Includes estimates · Partly unposted") if provisional else tr("ยอดลงบัญชี · ช่วงวันที่เลือก", "Posted · Selected period")

    def _render_overview(self) -> None:
        if self._staged and not self._can_render_tab(0):
            return
        total_pages = sum(row["total"] for row in self._printer_rows)
        records = self._records
        print_available = any(bool(getattr(record, "print_available", False)) for record in records)
        copy_available = any(bool(getattr(record, "copy_available", False)) for record in records)
        cost_available = bool(records) and all(
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
            self._report_cost_detail(),
            available=cost_available,
        )
        if not records:
            for card in self.overview_kpis.values():
                card.set_metric("—", tr("ไม่มีข้อมูลในช่วงนี้ · ลองเปลี่ยนวันที่", "No data in this period. Try another date."))
        self._schedule_render_tail(0, self._render_overview_tables, self._render_overview_charts)

    def _render_overview_tables(self) -> None:
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

    def _render_overview_charts(self) -> None:
        replace_chart(self.overview_mix, self._paper_mix_chart())
        replace_chart(self.overview_trend, self._timeline_chart(None))
        self._set_legend(self.overview_trend_legend, self._paper_legend_entries())
        self._set_legend(self.overview_mix_legend, self._paper_legend_entries(scan=True))
        apply_language(self)

    @staticmethod
    def _set_legend(host, entries):
        flow = host.layout()
        while flow.count():
            item = flow.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for text in entries:
            label = FlowLabel(text)
            label.setProperty('i18n_data', True)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            flow.addWidget(label)
        host.updateGeometry()
        host.refresh_height()

    @staticmethod
    def _paper_legend_entries(*, scan=False):
        entries = [f'<span style="color:{color}">■</span><span style="color:{QColor(color).lighter(155).name()}">■</span> '
                   f'A4 | A3 {name}' for name, color in (('Print', BLUE), ('Copy', ORANGE))]
        if scan:
            entries.append(f'<span style="color:{GREEN}">■</span> Scan')
        return entries

    def _paper_mix_chart(self):
        series = []
        for operation, base, offset in (('print', BLUE, 0), ('copy', ORANGE, 2)):
            for paper, shade in (('a4', base), ('a3', QColor(base).lighter(155).name())):
                values = [0.0] * 5
                for index, color in enumerate(('color', 'bw')):
                    values[offset + index] = sum(_combined(record, f'{operation}_{paper}_{color}') for record in self._records)
                series.append((f'{operation.title()} {paper.upper()}', tuple(values), shade))
        series.append(('Scan', (0, 0, 0, 0, sum(_combined(record, 'scan') for record in self._records)), GREEN))
        return self._stacked_bar_chart(FIVE_CATEGORIES if self._records else (), tuple(series), show_legend=False)

    def _render_users(self) -> None:
        if self._staged and not self._can_render_tab(1):
            return
        self._schedule_render_tail(1, self._render_users_table, self._render_users_charts)

    def _render_users_table(self) -> None:
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
        table = self.users_table
        overview = self._user_table_mode == 'overview'
        groups = (("all", tr("ทุกเครื่อง", "All printers"), "all" in self._expanded_user_printers),) if overview else tuple(
            (f'slot:{slot}', self._slot_label(slot, devices_by_slot),
             f'slot:{slot}' in self._expanded_user_printers) for slot in slots)
        detail_fields = tuple(field for field, _, _ in USAGE_METRICS)
        detail_labels = self._compact_usage_labels()
        blockers = [QSignalBlocker(target) for target in (table, table._left, table._right)]
        table.set_printers('User / Account', groups, detail_labels, include_total=True)
        rows = []
        for row in self._user_rows:
            values = [row["name"]]
            if overview:
                members = tuple(row['by_slot'].values())
                combined = {field: sum(member.get(field, 0.0) for member in members) for field in detail_fields}
                for flag in ('print_available', 'copy_available', 'scan_available', 'cost_available'):
                    combined[flag] = bool(members) and all(member.get(flag, False) for member in members)
                combined['available_fields'] = set.intersection(*(set(member.get('available_fields', ())) for member in members)) if members else set()
                displayed = (combined,)
            else:
                displayed = tuple(row['by_slot'].get(slot, {}) for slot in slots)
            for (_, _, expanded), slot_row in zip(groups, displayed):
                fields = detail_fields if expanded else ('print', 'copy', 'scan', 'total', 'cost')
                for field in fields:
                    available = True
                    if field in ('print', 'copy', 'scan', 'cost'):
                        available = bool(slot_row.get(field + '_available'))
                    elif field.startswith(('print_', 'copy_')):
                        available = field in slot_row.get('available_fields', ())
                    if field in ('print', 'copy'):
                        count = sum(slot_row.get(f'{field}_{paper}_{color}', 0.0)
                                    for paper in ('a3', 'a4') for color in ('color', 'bw'))
                        count += slot_row.get(f'{field}_other', 0.0)
                    else:
                        count = slot_row.get(field, 0.0)
                    values.append(self._usage_value_text(field, float(count), available=available))
            rows.append(tuple(values))
        table.setRowCount(0)
        self._fill_table(table, rows, empty="ยังไม่มีข้อมูล User / Account ในช่วงนี้")
        for index, row in enumerate(self._user_rows):
            table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row["key"])
            table.item(index, 0).setToolTip(row['name'])
            for identity, _name, _expanded in groups:
                start, count = table.printer_columns[identity]
                cell = table.item(index, start + count - 1)
                cell.setToolTip(tr('ข้อมูลยอดแยกประเภทหรือค่าใช้จ่ายรายวันไม่ครบ จึงยังคำนวณค่าใช้จ่ายรวมของผู้ใช้นี้ไม่ได้',
                    'Incomplete category usage or daily cost evidence; a complete user cost cannot be calculated.') if cell.text() == '—' else
                    tr('ค่าใช้จ่ายจัดสรรจากสัดส่วนการใช้ A3/A4 สี/ขาวดำของแต่ละเครื่องในแต่ละวัน ไม่ใช่ใบแจ้งหนี้',
                       'Allocated from daily A3/A4 color and B&W usage per printer; not an invoice.'))
            if row['key'] == self._selected_user:
                table._left.setCurrentCell(index, 0)
                table._right.selectRow(index)
        table.fit_columns()
        del blockers

    def _toggle_user_printer(self, identity: str) -> None:
        if identity in self._expanded_user_printers:
            self._expanded_user_printers.remove(identity)
        else:
            self._expanded_user_printers.add(identity)
        self._render_users_table()
        button = self.users_table.toggle_buttons.get(identity)
        if button is not None:
            button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _render_users_charts(self) -> None:
        users = self._user_rows[:8]
        breakdown_available = any(
            slot_row.get('print_available') or slot_row.get('copy_available') or slot_row.get('scan_available')
            for row in self._user_rows for slot_row in row.get('by_slot', {}).values())
        colors = (BLUE, QColor(BLUE).lighter(155).name(), ORANGE,
                  QColor(ORANGE).lighter(155).name(), SLATE)
        if breakdown_available:
            top_series = []
            for index, label in enumerate(FIVE_CATEGORIES):
                values = tuple(sum(self._classified_user_slot(slot_row)[index]
                                   for slot_row in row.get('by_slot', {}).values()) for row in users)
                top_series.append((label, values, colors[index]))
            top_chart = self._stacked_bar_chart(tuple(row['name'] for row in users), tuple(top_series))
            top_chart.setTitle(tr('เฉพาะยอดที่แยกประเภทได้', 'Only classified usage'))
            compact_labels = (tr('P สี', 'P Col'), tr('P ข/ด', 'P BW'),
                              tr('C สี', 'C Col'), tr('C ข/ด', 'C BW'), tr('สแกน', 'Scan'))
            for marker, compact in zip(top_chart.legend().markers(), compact_labels):
                marker.setLabel(compact)
        else:
            top_chart = self._horizontal_like_chart(
                [row['name'] for row in users], [row['usage'] for row in users], ORANGE)
        replace_chart(self.users_top_chart, top_chart)
        # Users can load before Printers in staged mode; resolve labels from this snapshot.
        devices_by_slot = {int(device.slot): device for device in self._devices}
        devices_by_identity = {}
        for record in self._records:
            devices_by_identity.setdefault(_record_identity(record), _record_name(record, devices_by_slot))
        selected = next((row for row in self._user_rows if row["key"] == self._selected_user), None)
        chosen = (selected,) if selected else self._user_rows
        chosen_breakdown_available = any(
            slot_row.get('print_available') or slot_row.get('copy_available') or slot_row.get('scan_available')
            for row in chosen for slot_row in row.get('by_slot', {}).values())
        if chosen_breakdown_available:
            slots = sorted({int(slot) for row in chosen for slot in row.get('by_slot', {})})
            series = []
            for index, slot in enumerate(slots):
                values = [0.0] * 5
                for row in chosen:
                    parts = self._classified_user_slot(row.get('by_slot', {}).get(slot, {}))
                    values = [a + b for a, b in zip(values, parts)]
                series.append((self._slot_label(slot, devices_by_slot), tuple(values),
                               DEVICE_COLORS[index % len(DEVICE_COLORS)]))
            chart = self._bar_chart(FIVE_CATEGORIES, tuple(series))
            chart.setTitle(tr('P = Print · C = Copy · เฉพาะยอดที่แยกประเภทได้',
                              'P = Print · C = Copy · Only classified usage'))
        else:
            source = selected["printers"] if selected else defaultdict(float)
            if not selected:
                for row in self._user_rows:
                    for identity, usage in row["printers"].items():
                        source[identity] += usage
            labels = [devices_by_identity.get(key, key.replace("serial:", "")) for key in source]
            chart = self._horizontal_like_chart(labels, list(source.values()), BLUE)
        replace_chart(self.users_printer_chart, chart)
        self.user_filter_badge.setText(
            f"กำลังกรอง: {selected['name']}" if selected else "เลือกผู้ใช้จากตารางเพื่อกรองกราฟ"
        )
        self.user_recovery_button.setVisible(not self._user_rows)
        apply_language(self)

    @staticmethod
    def _classified_user_slot(slot_row):
        return tuple(sum(float(slot_row.get(f'{operation}_{paper}_{color}', 0.0))
                         for paper in ('a3', 'a4'))
                     for operation in ('print', 'copy') for color in ('color', 'bw')) + (
            float(slot_row.get('scan', 0.0)),)

    def _render_printers(self) -> None:
        if self._staged and not self._can_render_tab(2):
            return
        self._schedule_render_tail(2, self._render_printers_tables, self._render_printers_charts)

    def _render_printers_tables(self) -> None:
        rows = self._printer_rows
        classified = self._printer_classified_totals()
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
                    *(_number(classified[row['key']][index])
                      if row[f'{operation}_available'] else '—'
                      for index, operation in enumerate(('print', 'print', 'copy', 'copy'))),
                    _number(row["scan"]),
                    _number(row["total"]),
                    _money(row["cost"]) if row.get('cost_available', True) else '—',
                )
            )
        printers_signal_blocker = QSignalBlocker(self.printers_table)
        self._fill_table(self.printers_table, table_rows, empty="ยังไม่มีข้อมูลเครื่องพิมพ์ในช่วงนี้")
        for index, row in enumerate(rows):
            item = self.printers_table.item(index, 0)
            label = self._slot_label(row['slot'], {int(d.slot): d for d in self._devices})
            item.setText(label)
            item.setToolTip(label)
            item.setData(Qt.ItemDataRole.UserRole, row["key"])
        self._size_printers_table()
        del printers_signal_blocker

    def _size_printers_table(self):
        table = self.printers_table
        table.resizeRowsToContents()
        row_height = table.verticalHeader().defaultSectionSize()
        height = table.horizontalHeader().height() + table.frameWidth() * 2
        height += sum(table.rowHeight(row) if row < table.rowCount() else row_height for row in range(3))
        table.setFixedHeight(height)

    @staticmethod
    def _classified_record(record) -> tuple[float, float, float, float, float]:
        return tuple(
            sum(_combined(record, f'{operation}_{paper}_{color}') for paper in ('a3', 'a4'))
            for operation in ('print', 'copy') for color in ('color', 'bw')
        ) + (_combined(record, 'scan'),)

    def _printer_classified_totals(self) -> dict[str, list[float]]:
        classified = defaultdict(lambda: [0.0] * 5)
        for record in self._records:
            values = self._classified_record(record)
            target = classified[_record_identity(record)]
            for index, value in enumerate(values):
                target[index] += value
        return classified

    def _render_printers_charts(self) -> None:
        rows = self._printer_rows
        replace_chart(self.printer_mix, self._paper_mix_chart())
        replace_chart(self.printer_trend, self._printer_timeline_chart(rows))
        devices = {int(device.slot): device for device in self._devices}
        entries = []
        for index, slot in enumerate(sorted({row['slot'] for row in rows})):
            color = QColor(DEVICE_COLORS[index % len(DEVICE_COLORS)])
            entries.append(f'<span style="color:{color.name()}">■</span><span style="color:{color.lighter(155).name()}">■</span> '
                           f'C | BW {escape(self._slot_label(slot, devices))}')
        self._set_legend(self.printer_trend_legend, entries)
        self._set_legend(self.printer_mix_legend, self._paper_legend_entries(scan=True))
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

        return self.usage_waste_checkbox.isChecked() if hasattr(self, "usage_waste_checkbox") else True

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

    def _usage_baselines_by_slot(self) -> dict[int, tuple[date, dict]]:
        """Merge V4.6 and V5 absolute openings without creating usage rows."""

        candidates: dict[int, tuple[date, dict]] = {}

        def add(slot: int, observed_on: date, total: object, values=None) -> None:
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
                candidates[slot] = (observed_on, dict(values or {}, total=value))

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
                baseline.usage_values(),
            )
        for snapshot in self._legacy_history:
            try:
                observed = date.fromisoformat(str(snapshot.read_date)[:10])
            except ValueError:
                continue
            add(int(snapshot.slot), observed, snapshot.total)
        return candidates

    @staticmethod
    def _baseline_values(values: dict, fields: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_number(values[field]) if field != "cost" and values.get(field) is not None else "—"
                     for field in fields)

    @staticmethod
    def _baseline_label(baselines) -> str:
        days = sorted({day for day, _values in baselines})
        stamp = days[0].strftime("%d/%m/%Y") if len(days) == 1 else tr("หลายวันที่เริ่มต้น", "Multiple opening dates")
        return tr("Meter เริ่มต้น", "Opening meter") + "\n" + stamp

    @staticmethod
    def _style_baseline_row(table: FrozenLeftTable) -> None:
        row = table.rowCount() - 1
        if row < 0 or table.item(row, 0) is None:
            return
        table.setRowHeight(row, 52)
        for body in (table._left, table._right):
            body.setWordWrap(True)
        tooltip = (
            "ค่า Meter ครั้งแรกที่บันทึกไว้ ใช้เป็นข้อมูลอ้างอิงเท่านั้น "
            "ไม่รวมในยอดใช้งาน กราฟ หรือค่าใช้จ่าย"
        )
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is None:
                continue
            item.setBackground(QColor("#EEF6F9"))
            item.setForeground(QColor(NAVY))
            item.setToolTip(tooltip)

    def _render_usage(self) -> None:
        if self._staged and not self._can_render_tab(3):
            return
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
            openings = tuple(aggregate_baselines_by_slot.values())
            # Never turn a missing member/category into a zero in the aggregate.
            complete = len(openings) == len(self._usage_selected_slots)
            values = {field: sum(values[field] for _day, values in openings)
                      if complete and field != "cost" and all(values.get(field) is not None for _day, values in openings)
                      else None for field in usage_fields}
            aggregate_rows.append((self._baseline_label(openings), *self._baseline_values(values, usage_fields)))
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
        self._usage_comparison_data = (
            period_label, printer_groups, printers, period_labels,
            by_period_and_printer, all_baselines_by_slot,
        )
        self._render_usage_comparison()
        self.usage_monthly_table.setGroupedHeader(period_label, USAGE_GROUPS, self._compact_usage_labels())
        self.usage_monthly_table.fit_rows()
        apply_language(self)

    def _toggle_usage_printer(self, identity):
        if identity in self._expanded_usage_printers:
            self._expanded_usage_printers.remove(identity)
        else:
            self._expanded_usage_printers.add(identity)
        self._render_usage_comparison()
        button = self.usage_printer_table.toggle_buttons.get(identity)
        if button is not None:
            button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _render_usage_comparison(self):
        if self._usage_comparison_data is None:
            return
        period_label, printer_groups, printers, period_labels, data, baselines = self._usage_comparison_data
        groups = tuple((identity, name, identity in self._expanded_usage_printers)
                       for identity, name in printer_groups
                       if printers[identity][0] in self._usage_selected_slots)
        table = self.usage_printer_table
        vertical = table._vsb.value()
        horizontal = table._right.horizontalScrollBar().value()
        detail_fields = tuple(field for field, _, _ in USAGE_METRICS if field != 'total')
        detail_labels = self._compact_usage_labels()[:11] + (tr('บาท', 'THB'),)
        table.set_printers(period_label, groups, detail_labels)

        def fields(expanded):
            return detail_fields if expanded else ('print', 'copy', 'scan', 'cost')

        def value(row, field, *, opening=False):
            if row is None or (opening and field == 'cost'):
                return '—'
            if field in ('print', 'copy'):
                parts = [row.get(key) for key in detail_fields if key.startswith(field + '_')]
                known = all(part is not None for part in parts)
                amount = sum(part for part in parts if part is not None)
                known = known and (opening or bool(row.get(field + '_available')))
            else:
                amount = row.get(field)
                family = next((kind for kind in ('print', 'copy') if field.startswith(kind + '_')), None)
                known = amount is not None
                if not opening:
                    known = known and (bool(row.get(family + '_available')) if family else
                                       bool(row.get('cost_available', True)) if field == 'cost' else True)
            return self._usage_value_text(field, amount or 0, available=known)

        rows = []
        selected = {identity for identity, _, _ in groups}
        periods = {period for period, identity in data if identity in selected}
        for period in sorted(periods, reverse=True):
            rows.append((period_labels[period], *(value(data.get((period, identity)), field)
                         for identity, _, expanded in groups for field in fields(expanded))))
        openings = [baselines[printers[identity][0]] for identity, _, _ in groups
                    if printers[identity][0] in baselines]
        if openings:
            rows.append((self._baseline_label(openings),
                         *(value(baselines.get(printers[identity][0], (None, None))[1], field, opening=True)
                           for identity, _, expanded in groups for field in fields(expanded))))
        # Clear old cells as well as spans; empty filters must not leave stale values.
        table.setRowCount(0)
        self._fill_table(table, rows, empty=tr('ไม่มีข้อมูล', 'No data'))
        if openings:
            self._style_baseline_row(table)
            for identity, _, _ in groups:
                baseline = baselines.get(printers[identity][0])
                if baseline:
                    start, count = table.printer_columns[identity]
                    for col in range(start, start + count):
                        item = table.item(table.rowCount() - 1, col)
                        item.setToolTip(item.toolTip() + '\n' + self._baseline_label((baseline,)))
        table.fit_columns()
        table._refresh_viewport_alignment()
        table._vsb.setValue(vertical)
        table._right.horizontalScrollBar().setValue(horizontal)

    @staticmethod
    def _usage_value_text(field: str, value: float, *, available: bool = True) -> str:
        if not available:
            return "—"
        return _money(value) if field == "cost" else _number(value)

    def _usage_records(self, granularity: str, *, graph=False) -> tuple:
        daily = self._chart_daily_records if graph else self._usage_daily_records
        v5_records = daily if granularity == "D" else self._monthly_records
        if self._period is not None:
            start, end = map(date.fromisoformat, self._period)
            in_period = lambda record: start <= record.period_start <= record.period_end <= end
            v5_records = tuple(record for record in v5_records if in_period(record))
            if granularity != 'D':
                # Keep posted totals for complete billing periods. At the two
                # edges, use only selected daily rows, never a whole overlapping
                # month or a prorated amount. Match physical printer identities.
                covered = defaultdict(list)
                for record in v5_records:
                    covered[(record.device_slot, _record_identity(record))].append(
                        (record.period_start, record.period_end))
                v5_records += tuple(record for record in daily if in_period(record) and not any(
                    first <= record.period_start and record.period_end <= last
                    for first, last in covered[(record.device_slot, _record_identity(record))]))
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
            if (record.device_slot not in first_v5_by_slot
                or record.period_end < first_v5_by_slot[record.device_slot])
            and (self._period is None or in_period(record))
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
        cost_cards = [self.overview_kpis["total_cost"]]
        for card in cost_cards:
            card._full_title = caption
            card.refresh_elision()
        self._build_printer_rows()
        self._render_overview()
        self._render_printers()
        self._render_usage()

    def _timeline_chart(self, identity: str | None) -> QChart:
        grouped = defaultdict(lambda: [0.0] * 4)
        for record in self._selected_chart_days:
            if identity and _record_identity(record) != identity:
                continue
            day = str(record.period_start)[:10]
            for index, (operation, paper) in enumerate((('print', 'a4'), ('print', 'a3'),
                                                        ('copy', 'a4'), ('copy', 'a3'))):
                grouped[day][index] += sum(_combined(record, f'{operation}_{paper}_{color}')
                                           for color in ('color', 'bw'))
        days = sorted(grouped)[-14:]
        categories = tuple(f'{day[8:10]}/{day[5:7]} {operation}'
                           for day in days for operation in ('P', 'C'))
        series = []
        for index, (name, color) in enumerate((
            ('Print A4', BLUE), ('Print A3', QColor(BLUE).lighter(155).name()),
            ('Copy A4', ORANGE), ('Copy A3', QColor(ORANGE).lighter(155).name()),
        )):
            values = tuple(grouped[day][index] if position % 2 == index // 2 else 0.0
                           for day in days for position in range(2))
            series.append((name, values, color))
        chart = self._stacked_bar_chart(categories, tuple(series), show_legend=False)
        if days:
            # Two adjacent stacked bars per day, with one centered date label.
            old_axis = chart.axes(Qt.Orientation.Horizontal)[0]
            chart.removeAxis(old_axis)
            old_axis.deleteLater()
            axis = QCategoryAxis()
            axis.setStartValue(-0.5)
            for index, day in enumerate(days):
                axis.append(f'{day[8:10]}/{day[5:7]}', index * 2 + 1.5)
            axis.setRange(-0.5, len(days) * 2 - 0.5)
            axis.setLabelsAngle(-45 if len(days) > 7 else 0)
            chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
            chart.series()[0].attachAxis(axis)
        return chart

    def _printer_timeline_chart(self, rows: list[dict]) -> QChart:
        """One bar per day, stacking Color/B&W for every configured Slot."""
        daily = defaultdict(lambda: [0.0, 0.0])
        for record in self._selected_chart_days:
            day = str(record.period_start)[:10]
            slot = int(record.device_slot)
            for index, color in enumerate(('color', 'bw')):
                daily[(day, slot)][index] += sum(
                    _combined(record, f'{operation}_{paper}_{color}')
                    for operation in ('print', 'copy') for paper in ('a3', 'a4'))
        slots = sorted({int(row['slot']) for row in rows})
        dates = sorted({day for day, _slot in daily})[-14:]
        devices = {int(d.slot): d for d in self._devices}
        series = []
        for index, slot in enumerate(slots):
            name = self._slot_label(slot, devices)
            dark = DEVICE_COLORS[index % len(DEVICE_COLORS)]
            for shade, color in enumerate((dark, QColor(dark).lighter(155).name())):
                series.append((f'{name} · {"Color" if shade == 0 else "B&W"}',
                               tuple(daily[(day, slot)][shade] for day in dates), color))
        chart = self._stacked_bar_chart(tuple(f'{day[8:10]}/{day[5:7]}' for day in dates),
                                        tuple(series), show_legend=False)
        if any('ค่าเฉลี่ยประมาณการ' in note for record in self._selected_chart_days for note in getattr(record, 'remarks', ())):
            chart.setTitle(tr('วันที่ไม่มีข้อมูล Web แสดงค่าเฉลี่ยประมาณการ', 'Days without Web readings show estimated averages'))
        return chart

    @staticmethod
    def _stacked_bar_chart(categories, series_data, *, show_legend=True):
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(2, 2, 2, 2))
        if not categories or not series_data:
            chart.setTitle(tr('ยังไม่มีข้อมูลสำหรับสร้างกราฟ', 'No chart data'))
            chart.legend().hide()
            return chart
        series = QStackedBarSeries()
        series.setBarWidth(0.68)
        maxima = [0.0] * len(categories)
        for name, values, color in series_data:
            bar = QBarSet(name)
            bar.append([float(value) for value in values])
            bar.setColor(QColor(color))
            for index, value in enumerate(values):
                maxima[index] += float(value)
            from PyQt6.QtWidgets import QToolTip
            from PyQt6.QtGui import QCursor
            bar.hovered.connect(lambda entered, index, values=values, name=name:
                QToolTip.showText(QCursor.pos(), f'{categories[index]}\n{name}: {_number(values[index])}')
                if entered else QToolTip.hideText())
            series.append(bar)
        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append(list(categories))
        axis_x.setLabelsAngle(-45 if len(categories) > 7 else 0)
        axis_y = QValueAxis()
        axis_y.setTitleText(tr('หน้า', 'Pages'))
        axis_y.setRange(0, max(1.0, max(maxima) * 1.15))
        axis_y.setTickCount(4)
        axis_y.setLabelFormat('%.2f' if any(value != int(value) for _, values, _ in series_data for value in values) else '%.0f')
        axis_y.applyNiceNumbers()
        axis_font = QFont()
        axis_font.setPointSize(9)
        axis_x.setLabelsFont(axis_font)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(show_legend)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        return chart

    @staticmethod
    def _horizontal_like_chart(labels: list[str], values: list[float], color: str) -> QChart:
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtGui import QCursor
        short = [f"{index + 1}. {label if len(label) <= 15 else label[:10] + '…' + label[-4:]}"
                 for index, label in enumerate(labels)]
        chart = CloudReportsWidget._bar_chart(tuple(short), (("หน้า", tuple(values), color),))
        # Exact names and values remain available by mouse and accessibility;
        # the adjacent report tables expose the same data to keyboard users.
        for series in chart.series():
            for bar in series.barSets():
                bar.hovered.connect(lambda entered, index: QToolTip.showText(QCursor.pos(),
                    f"{labels[index]}: {_number(values[index])}") if entered else QToolTip.hideText())
        return chart

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
            from PyQt6.QtWidgets import QToolTip
            from PyQt6.QtGui import QCursor
            bar.hovered.connect(lambda entered, index, values=values, name=name: QToolTip.showText(QCursor.pos(),
                f'{categories[index]}\n{name}: {values[index]:,.2f}' if not float(values[index]).is_integer()
                else f'{categories[index]}\n{name}: {values[index]:,.0f}')
                if entered else QToolTip.hideText())
            maximum = max(maximum, *(float(value) for value in values), 0.0)
            series.append(bar)
        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append(list(categories))
        axis_x.setLabelsAngle(-45 if len(categories) > 7 else 0)
        axis_y = QValueAxis()
        axis_y.setRange(0, max(1.0, maximum * 1.18))
        axis_y.setLabelFormat('%.2f' if any(not float(v).is_integer() for _, values, _ in series_data for v in values) else '%.0f')
        axis_y.setTickCount(4)
        axis_y.applyNiceNumbers()
        axis_font = QFont()
        axis_font.setPointSize(9)
        axis_x.setLabelsFont(axis_font)
        axis_y.setLabelsFont(axis_font)
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
