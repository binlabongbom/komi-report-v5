"""Overview UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCharts import QBarCategoryAxis, QChart, QChartView, QLineSeries, QValueAxis
from PyQt6.QtCore import QMargins, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPen
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from i18n import ENGLISH, apply_language, get_language, tr
from services.summary_service import build_overview_summary
from ui.chart_lifecycle import replace_chart
from ui.components.metric_card import MetricCard
from ui.components.toner_bar import TonerBar
from ui.styles import devices as devices_styles
from ui.styles import text as text_styles
from ui.styles.overview import build_overview_qss
from ui.styles.tokens import (
    C_ACCENT,
    C_CARD,
    C_GREEN,
    C_ORANGE,
    C_STATUS_OFFLINE,
    C_STATUS_ONLINE,
    C_STATUS_PENDING,
    C_TABLE_BORDER,
    C_TEXT,
    C_TEXT2,
    C_TEXT3,
    C_TONER_C,
    C_TONER_K,
    C_TONER_M,
    C_TONER_Y,
    F_2XL,
    F_MD,
    F_SM,
    F_XL,
    F_XS,
    PAGE_OVERVIEW_MARGIN_B,
    PAGE_OVERVIEW_MARGIN_L,
    PAGE_OVERVIEW_MARGIN_R,
    PAGE_OVERVIEW_MARGIN_T,
    SLOT_COLORS,
)
from widgets import btn, fmt_baht, fn, fnt, sec_title, sub_title


class _OverviewMetricCard(MetricCard):
    """One compact cell in the Overview KPI matrix."""

    def __init__(self, title: str, *, accent: str = C_ACCENT, parent=None):
        super().__init__(title, object_prefix="overview_metric", accent=accent, parent=parent)
        # Preserve the existing public attribute used by overview refreshes.
        self.lbl_diff = self.lbl_detail
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        # Keep long currency values and their context fully visible at the
        # supported 1024 px minimum window size.
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(8)
        left = QWidget()
        left.setObjectName("overview_metric_content")
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left.setMinimumWidth(0)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(1)
        self.lbl_title.setFont(fnt(F_XL, True))
        self.lbl_val.setFont(fnt(F_2XL, True))
        self.lbl_diff.setFont(fnt(F_MD))
        self.lbl_diff.setWordWrap(False)
        self.lbl_diff.setStyleSheet(text_styles.label(C_TEXT2))
        left_layout.addWidget(self.lbl_title)
        left_layout.addWidget(self.lbl_diff)
        layout.addWidget(left, 1)
        layout.addWidget(self.lbl_val)


    def set_metric(self, value: object, detail: str = "", *, available: bool = True) -> None:
        self.lbl_val.setText(fn(value) if available else "—")
        self._set_detail(detail if available else "ไม่มี Counter แยกประเภท")


class _OverviewTonerBar(TonerBar):
    """Overview geometry and compatibility name for the shared toner track."""

    def __init__(self, key: str, value: object, color: str, parent=None):
        super().__init__(
            key, value, color, parent,
            object_name="overview_toner_bar", height=32,
            minimum_width=46, maximum_width=76, preferred_width=150,
            background=C_CARD,
        )


class PageOverviewV2(QWidget):
    reports_requested = pyqtSignal()
    sync_log_requested = pyqtSignal()
    sync_requested = pyqtSignal()

    PERIODS = (
        ("รายวัน", "day"),
        ("รายเดือน", "month"),
        ("รายปี", "year"),
        ("ทั้งหมด", "all"),
    )

    def __init__(self, get_data, parent=None):
        super().__init__(parent)
        self.get_data = get_data
        self._ov_filter = "month"
        self._all_monthly: dict = {}
        self._overview_compact = True
        from ui.background_read import LatestRead
        self.summary_reader = LatestRead(self)
        self.summary_reader.ready.connect(self._apply_summary)
        self.summary_reader.failed.connect(self._summary_failed)
        self.setStyleSheet(build_overview_qss())
        self.setAccessibleName("ภาพรวมการใช้งานและสถานะเครื่องพิมพ์")
        self._build()


    def _period_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setProperty("i18n_items", True)
        combo.setObjectName("overview_period_combo")
        combo.setAccessibleName("ตัวกรองช่วงเวลา")
        for label, key in self.PERIODS:
            combo.addItem(label, key)
        combo.setCurrentIndex(combo.findData(self._ov_filter))
        combo.setFixedSize(132, 36)
        combo.currentIndexChanged.connect(
            lambda _index: self._set_ov_filter(str(combo.currentData()))
        )
        return combo

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            PAGE_OVERVIEW_MARGIN_L, PAGE_OVERVIEW_MARGIN_T,
            PAGE_OVERVIEW_MARGIN_R, PAGE_OVERVIEW_MARGIN_B,
        )
        layout.setSpacing(10)

        header = QHBoxLayout()
        self._overview_title = sec_title("ภาพรวม")
        self._overview_title.setFont(fnt(F_2XL, True))
        header.addWidget(self._overview_title)
        header.addStretch()
        self._ov_filter_btns: dict[str, QPushButton] = {}
        self._chart_filter_btns: dict[str, QPushButton] = {}
        self.period_combo = self._period_combo()
        header.addWidget(self.period_combo)
        layout.addLayout(header)

        self.overview_status = QLabel("")
        self.overview_status.setObjectName("overview_status_line")
        self.overview_status.setWordWrap(True)
        layout.addWidget(self.overview_status)
        self.overview_retry = btn(tr("ลองโหลดอีกครั้ง", "Retry loading"), "outline")
        self.overview_retry.clicked.connect(self.refresh)
        self.overview_retry.hide()
        layout.addWidget(self.overview_retry, 0, Qt.AlignmentFlag.AlignLeft)

        recovery_actions = QHBoxLayout()
        recovery_actions.setSpacing(8)
        self.btn_sync_now = btn("อ่านข้อมูลล่าสุด", "primary", self)
        self.btn_sync_now.setAccessibleName("อ่านข้อมูลล่าสุดจากเครื่องพิมพ์ทุกเครื่อง")
        self.btn_open_sync_log = btn("ดูสถานะการอ่าน", "outline", self)
        self.btn_open_sync_log.setAccessibleName("ดูสถานะและประวัติการอ่านข้อมูล")
        self.btn_sync_now.clicked.connect(self._request_sync)
        self.btn_open_sync_log.clicked.connect(self.sync_log_requested.emit)
        recovery_actions.addWidget(self.btn_sync_now)
        recovery_actions.addWidget(self.btn_open_sync_log)
        recovery_actions.addStretch()
        layout.addLayout(recovery_actions)

        self.read_feedback = QLabel('')
        self.read_feedback.setWordWrap(True)
        self.read_feedback.setStyleSheet(text_styles.label('#245268', padding='4px 0'))
        self.read_feedback.hide()
        layout.addWidget(self.read_feedback)

        self.summary_strip = QFrame()
        self.summary_strip.setObjectName("overview_kpi_panel")
        kpi = QGridLayout(self.summary_strip)
        kpi.setContentsMargins(12, 12, 12, 12)
        kpi.setHorizontalSpacing(12)
        kpi.setVerticalSpacing(10)
        self.card_color_print = _OverviewMetricCard("พิมพ์สี", accent=C_ACCENT)
        self.card_bw_print = _OverviewMetricCard("พิมพ์ขาวดำ", accent=C_TEXT)
        self.card_color_copy = _OverviewMetricCard("สำเนาสี", accent=C_ORANGE)
        self.card_bw_copy = _OverviewMetricCard("สำเนาขาวดำ", accent=C_TEXT2)
        self.card_total_usage = _OverviewMetricCard("ยอดใช้งานรวม", accent=C_ACCENT)
        self.card_total_cost = _OverviewMetricCard("ค่าใช้จ่ายรวม", accent=C_GREEN)
        self._summary_grid = kpi
        self._summary_cards = (
            (0, 0, self.card_color_print),
            (0, 1, self.card_bw_print),
            (0, 2, self.card_total_usage),
            (0, 3, self.card_color_copy),
            (0, 4, self.card_bw_copy),
            (0, 5, self.card_total_cost),
        )
        for row, column, widget in self._summary_cards:
            kpi.addWidget(widget, row, column)
        for column in range(6):
            kpi.setColumnStretch(column, 1)
        self.stat_cards = [
            self.card_total_usage, self.card_color_print,
            self.card_bw_print, self.card_total_cost,
        ]
        layout.addWidget(self.summary_strip)

        section_header = QHBoxLayout()
        section_header.addWidget(sub_title("สถานะเครื่องพิมพ์"))
        section_header.addStretch()
        layout.addLayout(section_header)

        printer_card = QFrame()
        printer_card.setObjectName("overview_printer_panel")
        printer_outer = QVBoxLayout(printer_card)
        printer_outer.setContentsMargins(12, 12, 12, 12)
        printer_outer.setSpacing(10)
        self.printer_list = QWidget()
        self.printer_list.setObjectName("overview_printer_list")
        self.printer_list_layout = QVBoxLayout(self.printer_list)
        self.printer_list_layout.setContentsMargins(0, 0, 0, 0)
        self.printer_list_layout.setSpacing(10)
        printer_outer.addWidget(self.printer_list)
        layout.addWidget(printer_card)

        chart_header = QHBoxLayout()
        chart_header.addWidget(sub_title("แนวโน้มการใช้งาน"))
        chart_header.addStretch()

        self.trend_card = QFrame()
        self.trend_card.setObjectName("overview_chart_panel")
        trend_layout = QVBoxLayout(self.trend_card)
        trend_layout.setContentsMargins(12, 10, 12, 10)
        trend_layout.setSpacing(4)
        trend_layout.addLayout(chart_header)
        self.view_bar = QChartView()
        self.view_bar.setAccessibleName("กราฟแนวโน้มการใช้งานแยกตามเครื่อง")
        self.view_bar.setMinimumHeight(220)
        self.view_bar.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view_bar.setStyleSheet(devices_styles.overview_v2_view_bar())
        trend_layout.addWidget(self.view_bar)
        self._overview_bottom_row = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._overview_bottom_row.addWidget(self.trend_card)
        layout.addLayout(self._overview_bottom_row)

        self.overview_empty = QLabel("ยังไม่มีข้อมูลสำหรับแสดงใน Overview")
        self.overview_empty.setObjectName("overview_empty")
        self.overview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overview_empty.setWordWrap(True)
        self.overview_empty.hide()
        layout.addWidget(self.overview_empty)

        # Reports remains available as a programmatic shortcut used by cards
        # and automated checks. The two recovery actions above stay visible so
        # an empty or stale Overview never becomes a dead end.
        self.btn_open_reports = btn("ดูรายงานฉบับเต็ม", "outline", self)
        self.btn_open_reports.clicked.connect(self.reports_requested.emit)
        self.btn_open_reports.hide()
        self.lbl_time = QLabel("", self)
        self.lbl_time.hide()
        self.top_users_card = QFrame(self)
        self.top_users_card.hide()

    def _request_sync(self) -> None:
        self.btn_sync_now.setText("กำลังอ่านข้อมูล…")
        self.btn_sync_now.setEnabled(False)
        self.sync_requested.emit()

    def _set_ov_filter(self, key: str) -> None:
        self._ov_filter = key
        if hasattr(self, "period_combo") and self.period_combo.currentData() != key:
            self.period_combo.blockSignals(True)
            self.period_combo.setCurrentIndex(self.period_combo.findData(key))
            self.period_combo.blockSignals(False)
        self.refresh()

    def _reflow_overview(self, width: int) -> None:
        # Use the actual page width inside the scroll wrapper. The top-level
        # window also includes the persistent sidebar and overestimates the
        # horizontal space available to KPI cards.
        kpi_columns = 3 if width >= 900 else 2 if width >= 560 else 1
        compact = width < 980
        for index, (_row, _column, card) in enumerate(self._summary_cards):
            row, column = divmod(index, kpi_columns)
            self._summary_grid.addWidget(card, row, column)
            card.lbl_val.setFont(fnt(F_2XL, True))
        for column in range(6):
            self._summary_grid.setColumnStretch(column, 1 if column < kpi_columns else 0)
        self._overview_bottom_row.setDirection(
            QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        )
        self._overview_compact = compact

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_overview(event.size().width())

    def _redraw_bar(self) -> None:
        chart = QChart()
        chart.setBackgroundBrush(QColor(C_CARD))
        chart.setDropShadowEnabled(False)
        chart.setMargins(QMargins(6, 6, 6, 2))
        monthly = self._all_monthly
        if not monthly:
            chart.setTitle("ยังไม่มีข้อมูล")
            chart.legend().hide()
            replace_chart(self.view_bar, chart)
            return

        months = sorted(monthly)
        if self._ov_filter == "day":
            months = months[-1:]
        elif self._ov_filter == "month":
            months = months[-6:]
        elif self._ov_filter == "year":
            months = months[-12:]
        slot_count = max(
            (len(monthly[month].get("machines", [])) for month in months),
            default=0,
        )
        names = getattr(self, "_machine_names", [])
        colors = list(SLOT_COLORS)
        series_items = []
        maximum = 0.0
        for slot in range(slot_count):
            line = QLineSeries()
            line.setName(names[slot] if slot < len(names) else f"เครื่อง {slot + 1}")
            line.setColor(QColor(colors[slot % len(colors)]))
            pen = QPen(line.color(), 2.5)
            line.setPen(pen)
            line.setPointsVisible(True)
            for index, month in enumerate(months):
                item = monthly[month]
                confirmed = item.get("machines", [])
                provisional = item.get("provisional_machines", [])
                value = float(confirmed[slot] if slot < len(confirmed) else 0.0)
                value += float(provisional[slot] if slot < len(provisional) else 0.0)
                maximum = max(maximum, value)
                line.append(float(index), value)
            chart.addSeries(line)
            series_items.append(line)

        axis_x = QBarCategoryAxis()
        labels = []
        for month in months:
            try:
                labels.append(datetime.strptime(month, "%Y-%m").strftime("%b %y"))
            except ValueError:
                labels.append(month)
        axis_x.append(labels)
        axis_x.setLabelsColor(QColor(C_TEXT2))
        axis_x.setGridLineColor(QColor(C_TABLE_BORDER))
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        axis_y.setRange(0.0, max(1.0, maximum * 1.12))
        axis_y.setLabelsColor(QColor(C_TEXT2))
        axis_y.setGridLineColor(QColor(C_TABLE_BORDER))
        axis_y.setTitleText("Sheets" if get_language() == ENGLISH else "แผ่น")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for line in series_items:
            line.attachAxis(axis_x)
            line.attachAxis(axis_y)
        chart.legend().setVisible(bool(series_items))
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignTop)
        for line in series_items:
            for marker in chart.legend().markers(line):
                marker.setBrush(QBrush(line.color()))
                marker.setPen(QPen(line.color(), 1.0))
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        replace_chart(self.view_bar, chart)

    @staticmethod
    def _detail(a3: float, a4: float) -> str:
        return f"A3 {fn(a3)}  |  A4 {fn(a4)}"

    def refresh(self) -> None:
        self.overview_status.setText(tr("กำลังโหลดภาพรวม…", "Loading overview…"))
        self.overview_retry.hide()
        self.summary_reader.request(build_overview_summary, self._ov_filter)

    def _summary_failed(self, error) -> None:
        self.overview_status.setText(tr("โหลดภาพรวมไม่สำเร็จ · กดรีเฟรชเพื่อลองใหม่", "Overview could not be loaded. Refresh to retry."))
        self.overview_status.setToolTip(error)
        self.overview_retry.show()

    def closeEvent(self, event) -> None:
        self.summary_reader.cancel()
        super().closeEvent(event)

    def _apply_summary(self, summary) -> None:
        self.overview_status.setToolTip("")
        self._all_monthly = summary.get("all_monthly") or {}
        metrics = summary.get("metrics") or {}
        quality = summary.get("quality") or {}
        devices = summary.get("devices") or []
        self._machine_names = (
            [str(device.get("name") or f"เครื่อง {index + 1}") for index, device in enumerate(devices)]
            or summary.get("machine_names")
            or []
        )

        display_total = float(metrics.get("display_total", metrics.get("total", 0)) or 0)
        display_cost = float(metrics.get("display_cost", metrics.get("cost", 0)) or 0)
        provisional_total = float(metrics.get("provisional_total", 0) or 0)
        online = int((quality.get("status_counts") or {}).get("online") or 0)
        last_sync = str(quality.get("last_sync_at") or "")
        if last_sync:
            try:
                last_sync = datetime.fromisoformat(last_sync.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
            except ValueError:
                pass
        else:
            last_sync = "ยังไม่เคย Sync สำเร็จ"
        self.overview_status.setText(f"Online {online}/{len(devices)} เครื่อง  •  Sync ล่าสุด {last_sync}")

        print_available = bool(metrics.get("print_available"))
        copy_available = bool(metrics.get("copy_available"))
        self.card_color_print.set_metric(
            metrics.get("display_print_color", 0),
            self._detail(metrics.get("display_print_a3_color", 0), metrics.get("display_print_a4_color", 0)),
            available=print_available,
        )
        self.card_bw_print.set_metric(
            metrics.get("display_print_bw", 0),
            self._detail(metrics.get("display_print_a3_bw", 0), metrics.get("display_print_a4_bw", 0)),
            available=print_available,
        )
        self.card_color_copy.set_metric(
            metrics.get("display_copy_color", 0),
            self._detail(metrics.get("display_copy_a3_color", 0), metrics.get("display_copy_a4_color", 0)),
            available=copy_available,
        )
        self.card_bw_copy.set_metric(
            metrics.get("display_copy_bw", 0),
            self._detail(metrics.get("display_copy_a3_bw", 0), metrics.get("display_copy_a4_bw", 0)),
            available=copy_available,
        )
        self.card_total_usage.lbl_val.setText(fn(display_total))
        self.card_total_usage.lbl_diff.setText(
            f"ยืนยัน {fn(metrics.get('total', 0))} · วันนี้ +{fn(provisional_total)}"
        )
        if quality.get("provisional_cost_available", True):
            self.card_total_cost.lbl_val.setText(fmt_baht(display_cost))
        else:
            self.card_total_cost.lbl_val.setText("—")
        self.card_total_cost.lbl_diff.setText(
            tr('ประมาณการ · ยังไม่ลงบัญชี', 'Estimate · Not posted') if provisional_total
            else tr('ยืนยันแล้ว · THB', 'Posted · THB'))
        self.card_total_cost.setToolTip(
            tr('ยืนยันแล้ว {posted} · ประมาณการ {pending}', 'Posted {posted} · Estimated {pending}').format(
                posted=fmt_baht(metrics.get('cost', 0)), pending=fmt_baht(metrics.get('provisional_cost', 0))))

        while self.printer_list_layout.count():
            item = self.printer_list_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        toner_colors = {"C": C_TONER_C, "Y": C_TONER_Y, "M": C_TONER_M, "K": C_TONER_K}
        state_labels = {
            "online": ("Online", C_STATUS_ONLINE, "เชื่อมต่อและอ่านข้อมูลได้"),
            "offline": ("ไม่เชื่อมต่อ", C_STATUS_OFFLINE, "ตรวจสอบเครือข่ายหรือดูสถานะการอ่านใน Settings"),
            "stale": ("ข้อมูลล่าช้า", C_STATUS_PENDING, "รอการอ่านข้อมูลรอบถัดไป"),
            "syncing": ("กำลัง Sync", C_ACCENT, "กำลังอ่านข้อมูลจากเครื่องพิมพ์"),
            "pending": ("รอตรวจสอบ", C_STATUS_PENDING, "ยังไม่มีการอ่านข้อมูลที่สำเร็จ"),
        }
        for device in devices:
            row = QFrame()
            row.setObjectName("overview_printer_row_v2")
            grid = QGridLayout(row)
            grid.setContentsMargins(14, 10, 14, 10)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            raw_state = str(device.get("status") or "pending").casefold()
            state_text, state_color, fallback_detail = state_labels.get(
                raw_state, state_labels["pending"]
            )
            dot = QLabel("●")
            dot.setStyleSheet(text_styles.label(state_color, font_size='16px'))
            dot.setToolTip(state_text)
            name = QLabel(str(device.get("name") or f"เครื่อง {int(device.get('slot', 0)) + 1}"))
            name.setFont(fnt(F_XL, True))
            name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name.setWordWrap(True)
            name.setToolTip(name.text())
            serial = QLabel(f"Serial No: {device.get('serial') or '—'}")
            serial.setFont(fnt(F_XS))
            serial.setStyleSheet(text_styles.label(C_TEXT2))
            host_value = str(device.get("host") or "")
            host = QLabel()
            host.setObjectName("overview_ip_link")
            host.setFont(fnt(F_XS))
            host.setCursor(Qt.CursorShape.PointingHandCursor)
            if host_value:
                target_url = QUrl(f"https://{host_value}")
                host.setText(
                    f'<a href="{target_url.toString()}" '
                    f'style="color:{C_ACCENT};text-decoration:none;">'
                    f'IP: {host_value}</a>'
                )
                host.setTextFormat(Qt.TextFormat.RichText)
                host.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
                host.setOpenExternalLinks(False)
                host.setToolTip(f"เปิดหน้าตั้งค่าเครื่อง: {target_url.toString()}")
                host.linkActivated.connect(
                    lambda _link, url=target_url: QDesktopServices.openUrl(url)
                )
            else:
                host.setText("IP: —")
                host.setCursor(Qt.CursorShape.ArrowCursor)
            identity = QWidget()
            identity.setObjectName("overview_printer_identity")
            identity.setMinimumWidth(0)
            identity.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            identity_layout = QVBoxLayout(identity)
            identity_layout.setContentsMargins(0, 0, 0, 0)
            identity_layout.setSpacing(1)
            identity_layout.addWidget(name)
            metadata = QHBoxLayout()
            metadata.setContentsMargins(0, 0, 0, 0)
            metadata.setSpacing(8)
            metadata.addWidget(serial)
            metadata.addWidget(host)
            metadata.addStretch()
            identity_layout.addLayout(metadata)

            status = QLabel(f"● {state_text}")
            status.setFont(fnt(F_SM, True))
            status.setStyleSheet(
                text_styles.label(state_color, background='transparent', border='none')
            )
            status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status_detail = QLabel(fallback_detail)
            status_detail.setFont(fnt(F_XS))
            status_detail.setStyleSheet(text_styles.label(C_TEXT2, background='transparent', border='none'))
            status_detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status_detail.setWordWrap(True)

            toner = device.get("toner") if isinstance(device.get("toner"), dict) else {}
            toner_panel = QWidget()
            toner_panel.setObjectName("overview_toner_group")
            toner_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            toner_layout = QVBoxLayout(toner_panel)
            toner_layout.setContentsMargins(0, 0, 0, 0)
            toner_layout.setSpacing(2)
            toner_title = QLabel("หมึก")
            toner_title.setFont(fnt(F_XS, True))
            toner_title.setStyleSheet(text_styles.label(C_TEXT2, background='transparent', border='none'))
            toner_layout.addWidget(toner_title)
            toner_bars = QHBoxLayout()
            toner_bars.setContentsMargins(0, 0, 0, 0)
            toner_bars.setSpacing(4)
            for key in ("C", "Y", "M", "K"):
                toner_bars.addWidget(_OverviewTonerBar(key, toner.get(key), toner_colors[key]), 1)
            toner_layout.addLayout(toner_bars)

            grid.addWidget(dot, 0, 0, 2, 1)
            grid.addWidget(identity, 0, 1, 2, 1)
            grid.addWidget(status, 0, 2)
            grid.addWidget(status_detail, 1, 2)
            grid.addWidget(toner_panel, 0, 3, 2, 1)
            grid.setColumnStretch(1, 1)
            grid.setColumnMinimumWidth(3, 218)
            row.setAccessibleDescription(
                f"{name.text()}; {state_text}; {fallback_detail}; "
                f"Serial {device.get('serial') or '—'}; IP {host_value or '—'}"
            )
            self.printer_list_layout.addWidget(row)
        if not devices:
            no_device = QLabel("ยังไม่ได้ตั้งค่าเครื่องพิมพ์")
            no_device.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_device.setStyleSheet(text_styles.label(C_TEXT3, padding='18px'))
            self.printer_list_layout.addWidget(no_device)

        has_data = bool(self._all_monthly)
        self.trend_card.setVisible(has_data)
        self.overview_empty.setVisible(not has_data and not devices)
        if has_data:
            self._redraw_bar()
        self.btn_sync_now.setText("อ่านข้อมูลทันที")
        self.btn_sync_now.setEnabled(True)
        self.lbl_time.setText(datetime.now().strftime("%H:%M:%S"))
        apply_language(self)


PageOverview = PageOverviewV2
