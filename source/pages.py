# ═══════════════════════════════════════════════════════════
# pages.py  —  แต่ละหน้าของโปรแกรม
# ═══════════════════════════════════════════════════════════

import json
import logging
import os
import platform
import stat
import traceback
from html import escape
from datetime import datetime
from collections import defaultdict
from pathlib import Path

from i18n import ENGLISH, apply_language, get_language, tr

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QLineEdit, QPushButton, QScrollArea,
    QComboBox, QGridLayout, QCheckBox,
    QDialog, QDialogButtonBox, QLayout, QSizePolicy,
    QBoxLayout
)
from PyQt6.QtCore  import Qt, pyqtSignal, pyqtSlot, QRect, QRectF, QPoint, QSize, QMargins, QUrl, QThread
from PyQt6.QtGui   import QColor, QBrush, QPainter, QPainterPath, QPen, QDesktopServices, QFont, QPixmap

from ui.numeric_inputs import NumericDoubleSpinBox as QDoubleSpinBox, NumericSpinBox as QSpinBox
from ui.page_tabs import PageTabs as QTabWidget

log = logging.getLogger(__name__)

from parser_profiles import PARSER_REGISTRY
from tools.check_parser import load_profiles


_parser_editor_windows = []   # เก็บ reference ป้องกัน GC

def _open_check_parser():
    """เปิดหน้าต่าง Check Parser (ทำงานได้ทั้ง .py และ .exe)"""
    try:
        from tools.check_parser import ParserEditorWindow
        win = ParserEditorWindow()
        win.setAttribute(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.WidgetAttribute.WA_DeleteOnClose)
        _parser_editor_windows.append(win)
        win.destroyed.connect(lambda: _parser_editor_windows.remove(win)
                              if win in _parser_editor_windows else None)
        win.show()
    except Exception as e:
        QMessageBox.critical(None, "เปิด Check Parser ไม่ได้", str(e))


class _NoParserMatchDialog(QDialog):
    """แสดงเมื่อนำเข้าไฟล์แล้วไม่พบ Parser ที่ตรงกัน"""
    RESULT_CANCEL      = 0
    RESULT_OPEN_PARSER = 1
    RESULT_CONFIRM     = 2

    def __init__(self, machine_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️  ไม่พบ Parser ที่ตรงกัน")
        self.setFixedWidth(460)
        self._result_code = self.RESULT_CANCEL

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)

        icon = QLabel("⚠️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size:36px; background:transparent; border:none;")
        lay.addWidget(icon)

        title = QLabel("ไม่พบ Parser ที่ตรงกับไฟล์นี้")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont(); f.setPointSize(13); f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        sub_msg = QLabel(
            f"ชื่อเครื่องในไฟล์:  <b>{machine_name}</b><br><br>"
            "โปรแกรมไม่พบ Parser Profile ที่ตรงกับเครื่องนี้<br>"
            "ข้อมูลที่นำเข้าอาจไม่ถูกต้อง"
        )
        sub_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_msg.setWordWrap(True)
        sub_msg.setStyleSheet("color:#64748B; font-size:10pt;")
        sub_msg.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(sub_msg)

        lay.addSpacing(4)

        btn_open = QPushButton("⚙️  เปิด Check Parser เพื่อตั้งค่า")
        btn_open.setFixedHeight(40)
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.setStyleSheet(
            "QPushButton { background:#2563EB; color:white; border:none;"
            " border-radius:8px; padding:8px 18px; font-weight:600; font-size:10pt; }"
            "QPushButton:hover { background:#1E3A8A; }"
        )
        btn_open.clicked.connect(self._on_open_parser)
        lay.addWidget(btn_open)

        btn_confirm = QPushButton("✅  ยืนยันบันทึกต่อไป (ไม่มี Parser)")
        btn_confirm.setFixedHeight(36)
        btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_confirm.setStyleSheet(
            "QPushButton { background:#F0FDF4; color:#16A34A; border:1.5px solid #16A34A;"
            " border-radius:8px; padding:6px 18px; font-weight:600; font-size:10pt; }"
            "QPushButton:hover { background:#16A34A; color:white; }"
        )
        btn_confirm.clicked.connect(self._on_confirm)
        lay.addWidget(btn_confirm)

        btn_cancel = QPushButton("ยกเลิก")
        btn_cancel.setFixedHeight(30)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(
            "QPushButton { background:transparent; color:#94A3B8; border:none; font-size:9pt; }"
            "QPushButton:hover { color:#0F172A; text-decoration:underline; }"
        )
        btn_cancel.clicked.connect(self.reject)
        lay.addWidget(btn_cancel, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_open_parser(self):
        self._result_code = self.RESULT_OPEN_PARSER
        self.done(self.RESULT_OPEN_PARSER)

    def _on_confirm(self):
        self._result_code = self.RESULT_CONFIRM
        self.done(self.RESULT_CONFIRM)

    def exec(self) -> int:
        super().exec()
        return self._result_code


class _FlowLayout(QLayout):
    """Simple flow layout: items wrap to next row when width exceeded."""
    def __init__(self, parent=None, margin=4, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        s += QSize(m.left() + m.right(), m.top() + m.bottom())
        return s

    def _do_layout(self, rect, test_only=False):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        row_h = 0
        for item in self._items:
            sz = item.sizeHint()
            if x + sz.width() > effective.right() + 1 and row_h > 0:
                x = effective.x()
                y += row_h + self._spacing
                row_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._spacing
            row_h = max(row_h, sz.height())
        return y + row_h - rect.y() + m.bottom()


class _ManualDocumentImage(QLabel):
    """Responsive screenshot shared by the in-app guide and Customer Guide."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._aspect_ratio = (
            pixmap.height() / pixmap.width() if pixmap.width() else 0.75
        )
        self.setPixmap(pixmap)
        self.setScaledContents(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.setMinimumWidth(0)
        self.setStyleSheet("background:#FFFFFF; border:0;")

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(120, round(max(1, width) * self._aspect_ratio))

    def sizeHint(self):
        width = min(900, max(640, self.pixmap().width()))
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(240, self.heightForWidth(240))


# ── PyQt6.QtCharts — native Qt charts (pie, bar)
from PyQt6.QtCharts import (
    QChart, QChartView, QPieSeries,
    QBarSeries, QBarSet, QBarCategoryAxis, QLineSeries, QValueAxis
)

from config import *
from database import (
    get_cfg, set_cfg, get_price, get_billing_day,
    get_last_two, get_all_readings, calc_cost, clear_slot, reset_db,
    PARSER_REGISTRY, check_duplicate, get_slot_serial, delete_reading,
    calc_billing_month, get_activity_log, get_price_snapshot, get_config_log,
    reset_settings_to_default,
    get_waste_paper_pct, set_waste_paper_pct, verify_settings_password,
    sanitize_filename, get_db_path,
    copy_database_for_first_run,
)
from runtime_config import RUNTIME_SETTINGS, load_runtime_settings, save_runtime_database_path
from tools.db_recovery import backup_database, inspect_database

# The legacy report graph is optional and only needed after Reports opens.
_PQG_OK = False
_pg_load_attempted = False
pg = None


def _load_pyqtgraph() -> None:
    global pg, _PQG_OK, _pg_load_attempted
    if _pg_load_attempted:
        return
    _pg_load_attempted = True
    try:
        import pyqtgraph
    except ImportError:
        return
    pg = pyqtgraph
    _PQG_OK = True


from widgets import (
    fnt, fn, fd, fmt_baht, hline, sec_title, sub_title,
    mk_card, mk_preview_card, mk_warn_card, StatCard,
    btn, tbl_item, make_table, FrozenColTable, FrozenLeftTable
)
from services.summary_service import build_overview_summary
from services.import_service import parse_import_file
from services.import_worker import ImportSaveWorker


class _OverviewMetricCard(QFrame):
    """One compact cell in the Overview KPI matrix."""

    def __init__(self, title: str, *, accent: str = C_ACCENT, parent=None):
        super().__init__(parent)
        self.setObjectName("overview_metric_card")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("overview_metric_title")
        self.lbl_title.setFont(fnt(F_XL, True))
        self.lbl_val = QLabel("—")
        self.lbl_val.setObjectName("overview_metric_value")
        self.lbl_val.setFont(fnt(F_2XL, True))
        self.lbl_val.setStyleSheet(f"color:{accent};")
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_diff = QLabel("")
        self.lbl_diff.setObjectName("overview_metric_detail")
        self.lbl_diff.setFont(fnt(F_MD))
        self.lbl_diff.setWordWrap(False)
        self.lbl_diff.setStyleSheet(f"color:{C_TEXT2};")
        left_layout.addWidget(self.lbl_title)
        left_layout.addWidget(self.lbl_diff)
        layout.addWidget(left, 1)
        layout.addWidget(self.lbl_val)

    def _set_detail(self, detail: str) -> None:
        """Style A3/A4 labels as metadata while keeping their numeric values black."""
        prefix, separator, suffix = detail.partition("  |  ")
        if prefix.startswith("A3 ") and separator and suffix.startswith("A4 "):
            a3_value = escape(prefix[3:])
            a4_value = escape(suffix[3:])
            self.lbl_diff.setTextFormat(Qt.TextFormat.RichText)
            self.lbl_diff.setText(
                "<span style='color:#64748B'>A3</span> "
                f"<span style='color:#111827'>{a3_value}</span>"
                "<span style='color:#94A3B8'>  |  </span>"
                "<span style='color:#64748B'>A4</span> "
                f"<span style='color:#111827'>{a4_value}</span>"
            )
            return
        self.lbl_diff.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_diff.setText(detail)

    def set_metric(self, value: object, detail: str = "", *, available: bool = True) -> None:
        self.lbl_val.setText(fn(value) if available else "—")
        self._set_detail(detail if available else "ไม่มี Counter แยกประเภท")


class _OverviewTonerBar(QWidget):
    """Dynamic toner fill used in compact Overview printer rows."""

    def __init__(self, key: str, value: object, color: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.color = QColor(color)
        try:
            self.value = max(0.0, min(100.0, float(value)))
            self.value_text = f"{self.value:,.0f}%"
        except (TypeError, ValueError):
            self.value = 0.0
            self.value_text = "—"
        self.setObjectName("overview_toner_bar")
        self.setProperty("tonerKey", key)
        self.setProperty("tonerPercent", self.value if self.value_text != "—" else None)
        # Overview shows four supplies per printer.  Keep each one compact so
        # the device identity and every toner colour remain visible together.
        self.setMinimumWidth(46)
        self.setMaximumWidth(76)
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background:transparent;border:none;")

    def sizeHint(self) -> QSize:
        return QSize(150, 32)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(C_CARD))
        rect = QRectF(0.5, 0.5, max(0.0, self.width() - 1.0), max(0.0, self.height() - 1.0))
        path = QPainterPath()
        path.addRoundedRect(rect, 6.0, 6.0)
        painter.fillPath(path, QColor(C_TONER_TRACK))
        if self.value > 0:
            painter.save()
            painter.setClipPath(path)
            fill = QColor(self.color)
            fill.setAlphaF(0.20)
            painter.fillRect(
                QRectF(rect.left(), rect.top(), rect.width() * self.value / 100.0, rect.height()),
                fill,
            )
            painter.restore()
        painter.setPen(QPen(QColor(C_TONER_BORDER), 1.0))
        painter.drawPath(path)
        painter.setPen(self.color)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.key}  {self.value_text}")

# ══════════════════════════════════════════════════════════
# PAGE: OVERVIEW  (ออกแบบใหม่)
# 1. Stat cards ยอดรวม 3 เครื่อง เดือนปัจจุบัน
# 2. PIE chart แต่ละเครื่อง + PIE chart ประเภทงาน
# 3. Bar chart ย้อนหลัง 12 เดือน (toggle: ปริมาณ / ค่าใช้จ่าย)
# 4. Top users เดือนปัจจุบัน
# ══════════════════════════════════════════════════════════
class PageOverview(QWidget):
    reports_requested = pyqtSignal()
    sync_log_requested = pyqtSignal()
    sync_requested = pyqtSignal()

    def __init__(self, get_data, parent=None):
        super().__init__(parent)
        self.get_data       = get_data
        self._bar_mode      = "volume"   # "volume" | "cost"
        self._all_monthly: dict = {}     # เก็บข้อมูลสำหรับ bar chart
        self._ov_filter     = "current"  # "current"|"3m"|"1y"|"all"
        self._build()

    def _build(self):
        self.setStyleSheet(build_overview_qss())   # ← QSS เฉพาะหน้า Overview
        self.setAccessibleName("ภาพรวมสถานะและยอดใช้งานวันนี้")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(PAGE_OVERVIEW_MARGIN_L, PAGE_OVERVIEW_MARGIN_T, PAGE_OVERVIEW_MARGIN_R, PAGE_OVERVIEW_MARGIN_B)
        lay.setSpacing(PAGE_OVERVIEW_SPACING)

        # ── Header: today's operational state ────────────────────
        self._overview_header = QGridLayout()
        self._overview_header.setContentsMargins(0, 0, 0, 0)
        self._overview_header.setHorizontalSpacing(12)
        self._overview_header.setVerticalSpacing(4)
        self._overview_title = sec_title("ภาพรวมวันนี้")
        self._overview_title.setWordWrap(True)
        self._overview_header.addWidget(self._overview_title, 0, 0)

        self._overview_filters = QWidget()
        tr = QHBoxLayout(self._overview_filters)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(8)
        tr.addStretch()
        self._ov_filter_btns = {}
        self.btn_sync_now = btn("อ่านข้อมูลทันที", "primary")
        self.btn_sync_now.setMinimumHeight(34)
        self.btn_sync_now.clicked.connect(self._request_sync)
        tr.addWidget(self.btn_sync_now)
        self.btn_open_reports = btn("ดูรายงานฉบับเต็ม", "outline")
        self.btn_open_reports.setMinimumHeight(34)
        self.btn_open_reports.clicked.connect(self.reports_requested.emit)
        tr.addWidget(self.btn_open_reports)
        self.lbl_time = QLabel("")
        self.lbl_time.setObjectName("lbl_ov_time")
        self.lbl_time.setFont(fnt(F_XS))
        self.lbl_time.setStyleSheet(f"color:{C_TEXT3}; margin-left:10px;")
        tr.addWidget(self.lbl_time)
        self._overview_header.addWidget(self._overview_filters, 1, 0)
        self._overview_compact = True
        lay.addLayout(self._overview_header)

        self.overview_status = QLabel("")
        self.overview_status.setObjectName("overview_status")
        self.overview_status.setAccessibleName("สถานะระบบและเวลาซิงก์ล่าสุด")
        self.overview_status.setWordWrap(True)
        lay.addWidget(self.overview_status)

        # ── Summary strip: confirmed Ledger + provisional Daily Cache ──
        summary_strip = QFrame()
        summary_strip.setObjectName("overview_summary_strip")
        sg = QGridLayout(summary_strip)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.setSpacing(0)
        specs = [
            ("ยอดใช้งาน",             C_ACCENT),
            ("งานสี",                  C_ORANGE),
            ("ขาวดำ",                  C_TEXT2),
            ("ค่าใช้จ่ายประมาณการ",    C_GREEN),
        ]
        self.stat_cards = []
        for col, (title, color) in enumerate(specs):
            sc = StatCard(title, color, compact=True)
            sc.setProperty("summaryColumn", col)
            sc.lbl_title.setFont(fnt(F_SM, True))
            sc.lbl_title.setStyleSheet(f"color:{C_TEXT2};")
            sc.lbl_diff.setStyleSheet(f"color:{C_TEXT2};")
            sg.addWidget(sc, 0, col)
            sg.setColumnStretch(col, 1)
            self.stat_cards.append(sc)
        lay.addWidget(summary_strip)

        self.overview_quality = QLabel("")
        self.overview_quality.setObjectName("overview_quality")
        self.overview_quality.setAccessibleName("สถานะยอดยืนยันและยอดระหว่างวัน")
        self.overview_quality.setWordWrap(True)
        lay.addWidget(self.overview_quality)

        # ── Printer status list ──────────────────────────────────
        printer_card = mk_card()
        printer_outer = QVBoxLayout(printer_card)
        printer_outer.setContentsMargins(
            CARD_MARGIN_L, CARD_MARGIN_T, CARD_MARGIN_R, CARD_MARGIN_B
        )
        printer_outer.setSpacing(8)
        printer_header = QHBoxLayout()
        printer_header.addWidget(sub_title("สถานะเครื่องพิมพ์"))
        printer_header.addStretch()
        self.btn_open_sync_log = btn("ตรวจสอบ Sync Log", "outline")
        self.btn_open_sync_log.setMinimumHeight(30)
        self.btn_open_sync_log.clicked.connect(self.sync_log_requested.emit)
        printer_header.addWidget(self.btn_open_sync_log)
        printer_outer.addLayout(printer_header)
        self.printer_list = QWidget()
        self.printer_list_layout = QVBoxLayout(self.printer_list)
        self.printer_list_layout.setContentsMargins(0, 0, 0, 0)
        self.printer_list_layout.setSpacing(0)
        printer_outer.addWidget(self.printer_list)
        lay.addWidget(printer_card)

        # ── Trend and optional User/Account summary ──────────────
        bar_card = mk_card(); bar_outer = QVBoxLayout(bar_card)
        bar_outer.setContentsMargins(CARD_MARGIN_L, CARD_MARGIN_T, CARD_MARGIN_R, CARD_MARGIN_B); bar_outer.setSpacing(BAR_SPACING)
        bar_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bar_card.setMaximumHeight(320)
        self.trend_card = bar_card

        bar_hdr = QHBoxLayout()
        bar_hdr.addWidget(sub_title("แนวโน้มย้อนหลัง 12 เดือน"))
        bar_hdr.addStretch()
        self.btn_vol    = btn("จำนวนหน้า", "primary")
        self.btn_cost_b = btn("ค่าใช้จ่าย", "outline")
        self.btn_vol.clicked.connect(lambda: self._switch_bar("volume"))
        self.btn_cost_b.clicked.connect(lambda: self._switch_bar("cost"))
        bar_hdr.addWidget(self.btn_vol)
        bar_hdr.addWidget(self.btn_cost_b)
        bar_outer.addLayout(bar_hdr)

        self.view_bar = QChartView()
        self.view_bar.setAccessibleName("กราฟแนวโน้มย้อนหลัง 12 เดือน")
        self.view_bar.setFixedHeight(220)
        self.view_bar.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view_bar.setStyleSheet(f"background: {C_CARD}; border: none;")
        bar_outer.addWidget(self.view_bar)

        self._overview_bottom_row = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._overview_bottom_row.setSpacing(12)
        self._overview_bottom_row.addWidget(bar_card, 1)

        top_card = mk_card()
        top_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_card.setMaximumHeight(320)
        self.top_users_card = top_card
        tl = QVBoxLayout(top_card)
        tl.setContentsMargins(CARD_MARGIN_L, CARD_MARGIN_T, CARD_MARGIN_R, CARD_MARGIN_B)
        tl.setSpacing(8)
        th = QHBoxLayout()
        th.setContentsMargins(0, 0, 0, 0)
        th.addWidget(sub_title("User / Account ที่ใช้งานสูงสุด"))
        th.addStretch()
        tl.addLayout(th)
        self.top_table = make_table(
            ["อันดับ", "ชื่อผู้ใช้", "สี (แผ่น)", "ขาวดำ (แผ่น)", "รวม (แผ่น)"],
            stretch_cols=[1],
            fixed_cols={0: 60, 2: 90, 3: 90, 4: 80},
            height=200
        )
        tl.addWidget(self.top_table)
        self._overview_bottom_row.addWidget(top_card, 1)

        lay.addLayout(self._overview_bottom_row)

        self.overview_empty = QLabel(
            "ยังไม่มีประวัติที่ยืนยันแล้ว กราฟจะเริ่มแสดงหลังมี Daily Record แรก "
            "ส่วนยอดระหว่างวันยังดูได้จากด้านบน"
        )
        self.overview_empty.setWordWrap(True)
        self.overview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overview_empty.setObjectName("overview_empty")
        self.overview_empty.hide()
        lay.addWidget(self.overview_empty)
        lay.addStretch(1)

    def _request_sync(self) -> None:
        self.btn_sync_now.setText("กำลังอ่านข้อมูล…")
        self.btn_sync_now.setEnabled(False)
        self.sync_requested.emit()

    def _reflow_overview(self, width: int) -> None:
        compact = width < 980
        if compact == self._overview_compact:
            return
        self._overview_header.removeWidget(self._overview_filters)
        if compact:
            self._overview_header.addWidget(self._overview_filters, 1, 0)
            self._overview_bottom_row.setDirection(QBoxLayout.Direction.TopToBottom)
        else:
            self._overview_header.addWidget(self._overview_filters, 0, 1)
            self._overview_header.setColumnStretch(0, 1)
            self._overview_bottom_row.setDirection(QBoxLayout.Direction.LeftToRight)
        self._overview_compact = compact
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_overview(event.size().width())

    # ────────────────────────────────────────────────────────────
    # HELPERS: charts
    # ────────────────────────────────────────────────────────────
    def _set_ov_filter(self, key: str):
        """เปลี่ยน filter ช่วงเวลา Overview"""
        self._ov_filter = key
        for k, b in self._ov_filter_btns.items():
            b.setObjectName("btn_primary" if k == key else "btn_outline")
            b.style().unpolish(b); b.style().polish(b)
        self.refresh()

    def _switch_bar(self, mode: str):
        """สลับ bar chart ระหว่างจำนวน / ค่าใช้จ่าย"""
        self._bar_mode = mode
        # เปลี่ยน style ปุ่ม
        for b, m in [(self.btn_vol, "volume"), (self.btn_cost_b, "cost")]:
            style = "primary" if mode == m else "outline"
            b.setObjectName(f"btn_{style}")
            b.style().unpolish(b); b.style().polish(b)
        self._redraw_bar()


    def _redraw_bar(self):
        """วาด bar chart ย้อนหลัง 12 เดือน"""
        monthly = self._all_monthly
        chart = QChart()
        chart.setBackgroundBrush(QColor(C_CARD))
        chart.setDropShadowEnabled(False)
        chart.legend().setVisible(False)

        if not monthly:
            chart.setTitle("ยังไม่มีข้อมูล")
            self.view_bar.setChart(chart)
            return

        months = sorted(monthly.keys())[-12:]
        if self._bar_mode == "volume":
            vals  = [monthly[m].get("display_total", monthly[m].get("total", 0)) for m in months]
            color = C_ACCENT
            lbl_y = "sheets" if get_language() == ENGLISH else "แผ่น"
        else:
            vals  = [monthly[m].get("display_cost", monthly[m].get("cost", 0.0)) for m in months]
            color = C_GREEN
            lbl_y = "THB" if get_language() == ENGLISH else "บาท"

        bar_set = QBarSet(lbl_y)
        bar_set.setColor(QColor(color))
        bar_set.setBorderColor(QColor(color))
        for v in vals:
            bar_set.append(float(v))

        series = QBarSeries()
        series.append(bar_set)
        chart.addSeries(series)

        xlabels = []
        for m in months:
            try:
                dt = datetime.strptime(m, "%Y-%m")
                xlabels.append(dt.strftime("%b %Y"))
            except Exception:
                xlabels.append(m)

        axis_x = QBarCategoryAxis()
        axis_x.append(xlabels)
        axis_x.setLabelsFont(fnt(F_MD))
        axis_x.setLabelsColor(QColor("#475569"))
        axis_x.setGridLineColor(QColor("#E2E8F0"))
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setTitleText(lbl_y)
        axis_y.setTitleFont(fnt(F_MD))
        axis_y.setLabelsFont(fnt(F_MD))
        axis_y.setLabelsColor(QColor("#475569"))
        axis_y.setGridLineColor(QColor("#E2E8F0"))
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        self.view_bar.setChart(chart)

    # ────────────────────────────────────────────────────────────
    # REFRESH
    # ────────────────────────────────────────────────────────────
    def refresh(self):
        """โหลดข้อมูลจาก database และอัปเดต UI ทั้งหน้า"""
        summary = build_overview_summary(self._ov_filter)
        self._all_monthly = summary["all_monthly"]
        cm = summary["metrics"]
        display_total = float(cm.get("display_total", cm.get("total", 0)) or 0)
        display_color = float(cm.get("display_color", cm.get("total_color", 0)) or 0)
        display_bw = float(cm.get("display_bw", cm.get("total_bw", 0)) or 0)
        display_cost = float(cm.get("display_cost", cm.get("cost", 0)) or 0)
        provisional_total = float(cm.get("provisional_total", 0) or 0)
        provisional_color = float(cm.get("provisional_color", 0) or 0)
        provisional_bw = float(cm.get("provisional_bw", 0) or 0)
        provisional_cost = float(cm.get("provisional_cost", 0) or 0)
        confirmed_total = float(cm.get("total", 0) or 0)
        confirmed_cost = float(cm.get("cost", 0) or 0)

        quality = summary.get("quality") or {}
        held_days = int(quality.get("held_days") or 0)
        incomplete_days = int(quality.get("incomplete_days") or 0)
        status_counts = quality.get("status_counts") or {}
        devices = summary.get("devices") or []
        online_count = int(status_counts.get("online") or 0)
        offline_count = int(status_counts.get("offline") or 0)
        stale_count = int(status_counts.get("stale") or 0)
        pending_count = int(status_counts.get("pending") or 0)
        last_sync_at = str(quality.get("last_sync_at") or "")
        last_sync_text = "ยังไม่เคย Sync สำเร็จ"
        if last_sync_at:
            try:
                last_sync_text = datetime.fromisoformat(
                    last_sync_at.replace("Z", "+00:00")
                ).astimezone().strftime("%d/%m/%Y %H:%M")
            except ValueError:
                last_sync_text = last_sync_at

        status_parts = [f"Online {online_count}/{len(devices)} เครื่อง"]
        if offline_count:
            status_parts.append(f"Offline {offline_count}")
        if stale_count:
            status_parts.append(f"ข้อมูลล่าช้า {stale_count}")
        if pending_count:
            status_parts.append(f"รอตรวจสอบ {pending_count}")
        status_parts.append(f"Sync ล่าสุด {last_sync_text}")
        self.overview_status.setText(" · ".join(status_parts))
        self.overview_status.setAccessibleDescription(self.overview_status.text())
        if offline_count:
            self.overview_status.setProperty("state", "error")
        elif stale_count or pending_count:
            self.overview_status.setProperty("state", "warning")
        else:
            self.overview_status.setProperty("state", "success")
        self.overview_status.style().unpolish(self.overview_status)
        self.overview_status.style().polish(self.overview_status)

        if summary.get("source") == "billing_ledger":
            parts = []
            if provisional_total or int(quality.get("provisional_days") or 0):
                cost_text = (
                    fmt_baht(provisional_cost)
                    if quality.get("provisional_cost_available", True)
                    else "—"
                )
                parts.append(
                    f"~ ยอดระหว่างวัน {fn(provisional_total)} หน้า · "
                    f"ค่าใช้จ่ายประมาณการ {cost_text} · ยังไม่บันทึกใน Billing Ledger"
                )
            else:
                parts.append(
                    f"ยอดยืนยันในรอบบิล {fn(confirmed_total)} หน้า · "
                    f"{fmt_baht(confirmed_cost)}"
                )
            if held_days:
                parts.append(f"Hold {held_days:,} วัน ไม่รวมในยอด")
            if incomplete_days:
                parts.append(f"ข้อมูลไม่สมบูรณ์ {incomplete_days:,} วัน")
            self.overview_quality.setText(" · ".join(parts))
            self.overview_quality.setAccessibleDescription(self.overview_quality.text())
            if held_days or incomplete_days:
                self.overview_quality.setProperty("state", "warning")
            elif provisional_total:
                self.overview_quality.setProperty("state", "info")
            else:
                self.overview_quality.setProperty("state", "success")
            self.overview_quality.style().unpolish(self.overview_quality)
            self.overview_quality.style().polish(self.overview_quality)
            self.overview_quality.show()
        else:
            self.overview_quality.hide()

        # ── Summary strip ────────────────────────────────────────
        if len(self.stat_cards) >= 4:
            prefix = "~" if provisional_total else ""
            self.stat_cards[0].lbl_val.setText(f"{prefix}{fn(display_total)}")
            self.stat_cards[0].lbl_diff.setText(
                f"ยืนยัน {fn(confirmed_total)} · วันนี้ +{fn(provisional_total)}"
            )
            self.stat_cards[1].lbl_val.setText(
                f"{'~' if provisional_color else ''}{fn(display_color)}"
            )
            self.stat_cards[1].lbl_diff.setText(f"วันนี้ +{fn(provisional_color)}")
            self.stat_cards[2].lbl_val.setText(
                f"{'~' if provisional_bw else ''}{fn(display_bw)}"
            )
            self.stat_cards[2].lbl_diff.setText(f"วันนี้ +{fn(provisional_bw)}")
            if quality.get("provisional_cost_available", True):
                self.stat_cards[3].lbl_val.setText(
                    f"{'~' if provisional_total else ''}{fmt_baht(display_cost)}"
                )
            else:
                self.stat_cards[3].lbl_val.setText("—")
            self.stat_cards[3].lbl_diff.setText(
                f"ยืนยัน {fmt_baht(confirmed_cost)} · วันนี้ ~{fmt_baht(provisional_cost)}"
                if provisional_total
                else f"ยืนยัน {fmt_baht(confirmed_cost)}"
            )

        # ── Printer rows ─────────────────────────────────────────
        while self.printer_list_layout.count():
            item = self.printer_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        state_labels = {
            "online": ("Online", "#087A55", "#EAF7EF"),
            "offline": ("Offline", "#B42318", "#FFF0F0"),
            "stale": ("ข้อมูลล่าช้า", "#8A4B08", "#FFF4E5"),
            "syncing": ("กำลัง Sync", "#155EEF", "#EFF6FF"),
            "pending": ("รอตรวจสอบ", "#475569", "#F1F5F9"),
        }
        for index, device in enumerate(devices):
            display_name = str(
                device.get("name") or f"เครื่อง {device.get('slot', 0) + 1}"
            )
            row = QFrame()
            row.setObjectName("overview_printer_row")
            row.setAccessibleName(f"สถานะ {display_name}")
            row.setProperty("lastRow", index == len(devices) - 1)
            row_layout = QGridLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setHorizontalSpacing(14)
            row_layout.setVerticalSpacing(3)
            name = QLabel(display_name)
            name.setFont(fnt(F_LG, True))
            model = QLabel(str(device.get("model") or device.get("host") or ""))
            model.setFont(fnt(F_XS))
            model.setStyleSheet(f"color:{C_TEXT3};")
            row_layout.addWidget(name, 0, 0)
            row_layout.addWidget(model, 1, 0)
            row_layout.setColumnStretch(0, 2)

            raw_state = str(device.get("status") or "pending")
            state_text, state_color, state_bg = state_labels.get(
                raw_state, state_labels["pending"]
            )
            state = QLabel(f"● {state_text}")
            state.setFont(fnt(F_MD, True))
            state.setStyleSheet(
                f"color:{state_color};background:{state_bg};"
                "border-radius:5px;padding:4px 8px;"
            )
            row_layout.addWidget(state, 0, 1, 2, 1)

            checked = device.get("last_success_at")
            checked_text = "ยังไม่มีข้อมูล"
            if checked:
                try:
                    checked_text = datetime.fromisoformat(
                        str(checked).replace("Z", "+00:00")
                    ).astimezone().strftime("%H:%M")
                except ValueError:
                    checked_text = str(checked)
            sync = QLabel(f"ข้อมูลล่าสุด\n{checked_text}")
            sync.setFont(fnt(F_SM))
            sync.setStyleSheet(f"color:{C_TEXT2};")
            row_layout.addWidget(sync, 0, 2, 2, 1)

            usage = QLabel(
                f"วันนี้ +{fn(device.get('provisional_total', 0))}\n"
                f"รวม {fn(device.get('display_total', 0))} หน้า"
            )
            usage.setFont(fnt(F_MD, True))
            usage.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(usage, 0, 3, 2, 1)

            if device.get("provisional_cost_available", True):
                cost_text = f"~{fmt_baht(device.get('display_cost', 0))}"
            else:
                cost_text = "—"
            cost = QLabel(f"ประมาณการ\n{cost_text}")
            cost.setFont(fnt(F_MD, True))
            cost.setStyleSheet(f"color:{C_GREEN};")
            cost.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(cost, 0, 4, 2, 1)

            held = int(device.get("held_days") or 0)
            if held:
                review = btn(f"ตรวจสอบ Hold {held}", "warning")
                review.clicked.connect(self.sync_log_requested.emit)
            elif raw_state in {"offline", "stale"}:
                review = btn("ตรวจสอบ", "outline")
                review.clicked.connect(self.sync_log_requested.emit)
            else:
                review = QLabel("ปกติ")
                review.setFont(fnt(F_SM, True))
                review.setStyleSheet(f"color:{C_GREEN};")
                review.setAlignment(Qt.AlignmentFlag.AlignCenter)
            review.setMinimumWidth(110)
            row_layout.addWidget(review, 0, 5, 2, 1)
            self.printer_list_layout.addWidget(row)
            row.setAccessibleDescription(
                f"{state_text}; ข้อมูลล่าสุด {checked_text}; "
                f"วันนี้เพิ่ม {fn(device.get('provisional_total', 0))} หน้า; "
                f"ค่าใช้จ่ายประมาณการ {cost_text}"
            )

        if not devices:
            no_device = QLabel("ยังไม่ได้ตั้งค่าเครื่องพิมพ์")
            no_device.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_device.setStyleSheet(f"color:{C_TEXT3};padding:18px;")
            self.printer_list_layout.addWidget(no_device)

        # ── Optional report details ──────────────────────────────
        has_trend = any(
            (item.get("display_total", item.get("total", 0)) or 0) > 0
            for item in self._all_monthly.values()
        )
        self.trend_card.setVisible(has_trend)
        if has_trend:
            self._redraw_bar()

        top_users = summary["top_users"]
        self.top_users_card.setVisible(bool(top_users))
        row_count = min(len(top_users), 5)
        self.top_table.setRowCount(row_count)
        medals = ["🥇", "🥈", "🥉", "  4", "  5"]
        for r, (name, cf, cb, t) in enumerate(top_users[:row_count]):
            medal = medals[r] if r < len(medals) else f"  {r + 1}"
            self.top_table.setItem(r, 0, tbl_item(medal))
            self.top_table.setItem(r, 1, tbl_item(
                name, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
            self.top_table.setItem(r, 2, tbl_item(fn(cf), color=C_ORANGE))
            self.top_table.setItem(r, 3, tbl_item(fn(cb), color=C_TEXT2))
            self.top_table.setItem(r, 4, tbl_item(fn(t), bold=True, mono=True, color=C_GREEN))
        self.overview_empty.setVisible(not has_trend and not top_users)

        self.btn_sync_now.setText("อ่านข้อมูลล่าสุด")
        self.btn_sync_now.setEnabled(True)
        self.lbl_time.setText(f"หน้าจออัปเดต {datetime.now().strftime('%H:%M:%S')}")

    def _months_ago(self, bm: str, n: int) -> str:
        """คำนวณ billing_month ที่ถอยหลัง n เดือน"""
        try:
            dt = datetime.strptime(bm, "%Y-%m")
            total = dt.month - 1 - n
            y = dt.year + total // 12
            m = total % 12 + 1
            return f"{y}-{m:02d}"
        except Exception:
            return bm


# ══════════════════════════════════════════════════════════
# OVERVIEW V2 — compact mock-up based dashboard
# ══════════════════════════════════════════════════════════
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
        self.setStyleSheet(build_overview_qss())
        self.setAccessibleName("ภาพรวมการใช้งานและสถานะเครื่องพิมพ์")
        self._build()


    def _period_combo(self) -> QComboBox:
        combo = QComboBox()
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
        self.view_bar.setStyleSheet(f"background:{C_CARD};border:none;")
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
            self.view_bar.setChart(chart)
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
        self.view_bar.setChart(chart)

    @staticmethod
    def _detail(a3: float, a4: float) -> str:
        return f"A3 {fn(a3)}  |  A4 {fn(a4)}"

    def refresh(self) -> None:
        summary = build_overview_summary(self._ov_filter)
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
        self.card_total_cost.lbl_diff.setText("THB")

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
            dot.setStyleSheet(f"color:{state_color};font-size:16px;")
            dot.setToolTip(state_text)
            name = QLabel(str(device.get("name") or f"เครื่อง {int(device.get('slot', 0)) + 1}"))
            name.setFont(fnt(F_XL, True))
            name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name.setWordWrap(True)
            name.setToolTip(name.text())
            serial = QLabel(f"Serial No: {device.get('serial') or '—'}")
            serial.setFont(fnt(F_XS))
            serial.setStyleSheet(f"color:{C_TEXT2};")
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
                f"color:{state_color};background:transparent;border:none;"
            )
            status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status_detail = QLabel(fallback_detail)
            status_detail.setFont(fnt(F_XS))
            status_detail.setStyleSheet(f"color:{C_TEXT2};background:transparent;border:none;")
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
            toner_title.setStyleSheet(f"color:{C_TEXT2};background:transparent;border:none;")
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
            no_device.setStyleSheet(f"color:{C_TEXT3};padding:18px;")
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


# New imports of PageOverview receive the redesigned dashboard while the old
# implementation remains above for a low-risk rollback during this UI pass.
PageOverview = PageOverviewV2


# ══════════════════════════════════════════════════════════
# PREVIEW DIALOG — แสดงข้อมูลก่อนบันทึก
# ══════════════════════════════════════════════════════════
class PreviewDialog(QDialog):
    """
    แสดง Preview ข้อมูลที่จะนำเข้า
    ตรวจสอบ: SN ตรงกับเครื่องที่เลือก, ไม่ซ้ำ
    ผู้ใช้ยืนยันก่อนบันทึก
    แสดงชื่อ parser ที่ตรวจพบ เพื่อให้ผู้ใช้รู้ว่าใช้ parser ตัวไหน
    """
    def __init__(self, slot: int, parsed: dict, filepath: str, parser_name: str = "", parent=None):
        super().__init__(parent)
        self.slot        = slot
        self.parsed      = parsed
        self.filepath    = filepath
        self.parser_name = parser_name
        self.setWindowTitle("Preview ข้อมูล — ยืนยันก่อนบันทึก")
        self.setMinimumWidth(620)
        self._warnings = []
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # ── หัวข้อ
        lay.addWidget(QLabel("📋  ตรวจสอบข้อมูลก่อนบันทึก",
                             font=fnt(F_XL, True)))

        # ── แบนเนอร์ parser ที่ตรวจพบ ──────────────────────────────
        if self.parser_name:
            # หาสีจาก registry
            p_color = "#6B7280"
            for entry in PARSER_REGISTRY:
                if entry["name"] == self.parser_name:
                    p_color = entry.get("color", "#6B7280")
                    break
            parser_banner = QFrame()
            parser_banner.setStyleSheet(
                f"QFrame {{ background: {p_color}18; border: 1.5px solid {p_color}60;"
                f" border-left: 5px solid {p_color}; border-radius: 8px; }}"
            )
            pb_lay = QHBoxLayout(parser_banner)
            pb_lay.setContentsMargins(14, 10, 14, 10)
            pb_icon = QLabel("🔍  ตรวจพบรูปแบบไฟล์:")
            pb_icon.setFont(fnt(F_MD))
            pb_icon.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
            pb_name = QLabel(self.parser_name)
            pb_name.setFont(fnt(F_LG, True))
            pb_name.setStyleSheet(f"color:{p_color}; background:transparent; border:none;")
            pb_lay.addWidget(pb_icon)
            pb_lay.addWidget(pb_name)

            # โหลด type badges จาก user profile JSON
            _TYPE_META = {
                "summary":    ("Summary",    "#16A34A"),
                "user":       ("User",       "#2563EB"),
                "production": ("Production", "#D97706"),
                "label":      ("Label",      "#8B5CF6"),
            }
            try:
                _pj = Path.home() / "konica_parser_user_profiles.json"
                if _pj.exists():
                    _data = json.loads(_pj.read_text(encoding="utf-8"))
                    _active_types = []
                    for _pr in _data.get("profiles", []):
                        if _pr.get("name", "") == self.parser_name:
                            _active_types = _pr.get("types", [])
                            break
                    for _tk in ("summary", "user", "production", "label"):
                        if _tk in _active_types:
                            _lbl, _clr = _TYPE_META[_tk]
                            _badge = QLabel(_lbl)
                            _badge.setFont(fnt(F_XS, True))
                            _badge.setStyleSheet(
                                f"background:{_clr}; color:white; padding:2px 8px;"
                                f" border-radius:4px; border:none;"
                            )
                            pb_lay.addWidget(_badge)
            except Exception:
                pass

            pb_lay.addStretch()
            lay.addWidget(parser_banner)

        # ── ข้อมูลไฟล์
        d = self.parsed
        info_card = mk_preview_card()
        il = QVBoxLayout(info_card); il.setContentsMargins(16,12,16,12); il.setSpacing(8)
        
        # Header: ชื่อ + Mode badge (Account/User)
        header_lay = QHBoxLayout()
        header_lbl = QLabel("ข้อมูลจากไฟล์"); header_lbl.setFont(fnt(F_LG, True))
        header_lay.addWidget(header_lbl)
        header_lay.addStretch()
        
        mode = d.get("mode")
        if mode == "account":
            mode_text = "User Mode"
            mode_color = "#2563EB"
        elif mode == "production":
            mode_text = "Production Mode"
            mode_color = "#D97706"
        elif mode == "label":
            mode_text = "Label Mode"
            mode_color = "#8B5CF6"
        else:  # "summary" or default
            mode_text = "Summary Mode"
            mode_color = "#16A34A"
        mode_badge = QLabel(mode_text)
        mode_badge.setFont(fnt(F_MD, True))
        mode_badge.setStyleSheet(f"background: {mode_color}; color: white; padding: 4px 10px; border-radius: 4px;")
        header_lay.addWidget(mode_badge)
        il.addLayout(header_lay)

        sm   = d.get("summary", {})
        curr, prev = get_last_two(self.slot)
        billing = calc_billing_month(d.get("date", ""))
        billing_day = get_billing_day()

        if mode == "label":
            # Label mode: แสดง Meter สี / ขาวดำ แทน A4/A3 breakdown
            prev_sm = prev.get("summary", {}) if prev else {}
            color_m = sm.get("total_color", 0)
            bw_m    = sm.get("total_bw",    0)
            total_m = sm.get("total",       0) or d.get("total_counter", 0)
            d_color = max(0, color_m - prev_sm.get("total_color", 0)) if prev else color_m
            d_bw    = max(0, bw_m    - prev_sm.get("total_bw",    0)) if prev else bw_m
            d_total = max(0, total_m - prev_sm.get("total",       0)) if prev else total_m
            cost    = (d_color * get_price("a4_color", self.slot) +
                       d_bw    * get_price("a4_bw",    self.slot))
            rows_info = [
                ("ชื่อรุ่น",           d.get("machine_name","—"),                   C_TEXT,   True),
                ("Serial No.",         d.get("serial","—"),                         C_ACCENT, True),
                ("วันที่อ่าน",         d.get("date","—"),                           C_TEXT,   False),
                ("เดือนบิล",           f"{billing}  (ตัดรอบวันที่ {billing_day})",  C_GREEN,  True),
                ("Mode",               "LABEL",                                     "#8B5CF6", False),
                ("Meter สี (Color)",   fn(d_color),                                C_ORANGE, False),
                ("Meter ขาวดำ (BW)",   fn(d_bw),                                   C_TEXT2,  False),
                ("รวม Meter ทั้งหมด",  fn(d_total),                                C_GREEN,  True),
                ("ค่าใช้จ่าย",         fmt_baht(cost),                             C_GREEN,  True),
            ]
        else:
            pc  = d.get("paper_color", {})
            pcp = prev.get("paper_color", {}) if prev else {}
            a4c  = max(0, pc.get("a4_color", 0) - pcp.get("a4_color", 0)) if prev else pc.get("a4_color", 0)
            a4bw = max(0, pc.get("a4_bw",    0) - pcp.get("a4_bw",    0)) if prev else pc.get("a4_bw",    0)
            a3c  = max(0, pc.get("a3_color", 0) - pcp.get("a3_color", 0)) if prev else pc.get("a3_color", 0)
            a3bw = max(0, pc.get("a3_bw",    0) - pcp.get("a3_bw",    0)) if prev else pc.get("a3_bw",    0)
            cost = calc_cost(a4c, a4bw, a3c, a3bw, self.slot)
            rows_info = [
                ("ชื่อรุ่น",     d.get("machine_name","—"),                          C_TEXT,   True),
                ("Serial No.",   d.get("serial","—"),                               C_ACCENT, True),
                ("วันที่อ่าน",   d.get("date","—"),                                 C_TEXT,   False),
                ("เดือนบิล",     f"{billing}  (ตัดรอบวันที่ {billing_day})",        C_GREEN,  True),
                ("Mode",         d.get("mode","—").upper(),                         C_TEXT,   False),
                ("A4 สี",        fn(a4c),                                           C_ACCENT, False),
                ("A4 ขาวดำ",     fn(a4bw),                                          C_TEXT2,  False),
                ("A3 สี",        fn(a3c),                                           C_ORANGE, False),
                ("A3 ขาวดำ",     fn(a3bw),                                          C_PURPLE, False),
                ("รวมทั้งหมด",   fn(sm.get("total",0)),                            C_GREEN,  True),
                ("ค่าใช้จ่าย",   fmt_baht(cost),                                    C_GREEN,  True),
            ]
        g = QGridLayout(); g.setSpacing(6)
        for r, (lbl, val, col, bold) in enumerate(rows_info):
            tl = QLabel(f"{lbl} :"); tl.setFont(fnt(F_MD)); tl.setStyleSheet(f"color:{C_TEXT3};")
            tl.setFixedWidth(110)
            vl = QLabel(val); vl.setFont(fnt(F_MD, bold)); vl.setStyleSheet(f"color:{col};")
            g.addWidget(tl, r, 0); g.addWidget(vl, r, 1)
        il.addLayout(g)
        lay.addWidget(info_card)

        # ── ตรวจสอบคำเตือน
        existing_sn = get_slot_serial(self.slot)
        mname = get_cfg(f"machine_name_{self.slot}", SLOT_NAMES[self.slot])
        new_sn = d.get("serial","")

        # ตรวจสอบ: ไฟล์นี้เป็นของเครื่องอื่นหรือไม่ (check SN ของเครื่องอื่น)
        for other_slot in range(3):
            if other_slot != self.slot:
                other_sn = get_slot_serial(other_slot)
                if new_sn and other_sn and new_sn == other_sn:
                    other_name = get_cfg(f"machine_name_{other_slot}", SLOT_NAMES[other_slot])
                    self._warnings.append(
                        f"⚠️  ไฟล์เป็นของเครื่องอื่น!\n"
                        f"   ไฟล์นี้มี SN: {new_sn}\n"
                        f"   เป็นของ: {other_name} (เครื่องที่ {other_slot+1})"
                    )

        if existing_sn and new_sn and existing_sn != new_sn:
            self._warnings.append(
                f"⚠️  Serial Number ไม่ตรง!\n"
                f"   เครื่องนี้เคยใช้: {existing_sn}\n"
                f"   ไฟล์ใหม่มี SN:  {new_sn}"
            )
        if check_duplicate(self.slot, new_sn, d.get("date","")):
            self._warnings.append(
                f"⚠️  ไฟล์ซ้ำ! มีข้อมูลวันที่ {d.get('date','')} SN {new_sn} อยู่แล้ว"
            )

        # แสดงคำเตือน
        for warn_text in self._warnings:
            wc = mk_warn_card()
            wl = QVBoxLayout(wc)
            wl.setContentsMargins(14, 12, 14, 12)
            wl.setSpacing(4)
            wlbl = QLabel(warn_text)
            wlbl.setFont(fnt(F_LG, True))
            wlbl.setStyleSheet("color: #DC2626; font-weight: bold;")
            wlbl.setWordWrap(True)
            wl.addWidget(wlbl)
            lay.addWidget(wc)

        # ── ปุ่ม
        btns = QDialogButtonBox()
        if self._warnings:
            save_btn = btns.addButton("บันทึกถึงกระนั้น", QDialogButtonBox.ButtonRole.AcceptRole)
            save_btn.setObjectName("btn_warning")
            save_btn.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; } QPushButton:pressed { background: #1E40AF !important; color: white !important; border-color: white !important; }")
        else:
            save_btn = btns.addButton("✅  บันทึกข้อมูล", QDialogButtonBox.ButtonRole.AcceptRole)
            save_btn.setObjectName("btn_success")
            save_btn.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; } QPushButton:pressed { background: #1E40AF !important; color: white !important; border-color: white !important; }")

        cancel_btn = btns.addButton("ยกเลิก", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.setObjectName("btn_outline")
        cancel_btn.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 7px 16px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; } QPushButton:pressed { background: #1E40AF !important; color: white !important; border-color: white !important; }")

        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


# ══════════════════════════════════════════════════════════
# PAGE: IMPORT REPORT
# นำเข้าไฟล์ + Preview + เปรียบเทียบ
# ══════════════════════════════════════════════════════════
class PageImport(QWidget):
    changed = pyqtSignal()   # ส่งสัญญาณเมื่อมีการเปลี่ยนแปลงข้อมูล

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slot_widgets = []   # list ของ dict widget แต่ละ slot
        self._drag_hint_labels = []  # ป้ายข้อความ hint สำหรับแต่ละการ์ด
        self._current_drag_card = None  # เทรคการ์ด drag ปัจจุบัน
        self._import_threads = []
        self._active_import_slot = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(18)
        lay.addWidget(sec_title("📥  นำเข้ารีพอร์ต"))

        # ── 3 Import Cards แถวบน
        cr = QHBoxLayout(); cr.setSpacing(14)
        for i in range(3):
            cr.addWidget(self._mk_import_card(i))
        lay.addLayout(cr)
        lay.addWidget(hline())

        # ── ประวัติการอัพโหลด (Activity Log)
        act_hdr = QHBoxLayout(); act_hdr.setContentsMargins(0, 0, 0, 4)
        act_hdr.addWidget(sub_title("📋  ประวัติการอัพโหลดไฟล์"))
        act_hdr.addStretch()
        self.btn_edit_mode = QPushButton("✏️  แก้ไข")
        self.btn_edit_mode.setFont(fnt(F_MD, True))
        self.btn_edit_mode.setFixedHeight(34)
        self.btn_edit_mode.setStyleSheet(
            "QPushButton { background: #EFF6FF; color: #2563EB; border: 1.5px solid #BFDBFE;"
            " border-radius: 7px; padding: 4px 16px; font-weight: 600; }"
            " QPushButton:hover { background: #2563EB; color: white; }"
        )
        self.btn_delete_sel = QPushButton("🗑  ลบที่เลือก")
        self.btn_delete_sel.setFont(fnt(F_MD, True))
        self.btn_delete_sel.setFixedHeight(34)
        self.btn_delete_sel.setStyleSheet(
            "QPushButton { background: #FEE2E2; color: #DC2626; border: 1.5px solid #FCA5A5;"
            " border-radius: 7px; padding: 4px 16px; font-weight: 600; }"
            " QPushButton:hover { background: #DC2626; color: white; }"
        )
        self.btn_delete_sel.setVisible(False)
        act_hdr.addWidget(self.btn_edit_mode)
        act_hdr.addWidget(self.btn_delete_sel)
        lay.addLayout(act_hdr)

        self._edit_mode = False
        self.btn_edit_mode.clicked.connect(self._toggle_edit_mode)
        self.btn_delete_sel.clicked.connect(self._delete_selected_activities)

        self.tbl_activity = make_table(
            ["วันที่/เวลา", "อัพไปเครื่อง", "ชื่อเครื่อง", "Serial", "ชื่อไฟล์", "วันที่อ่าน", "เดือนบิล", "Parser", "☑"],
            stretch_cols=[1, 4],
            height=240
        )
        self.tbl_activity.setAlternatingRowColors(True)
        self.tbl_activity.setColumnWidth(8, 50)
        self.tbl_activity.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.tbl_activity.setColumnHidden(8, True)
        self.tbl_activity.itemChanged.connect(self._on_activity_chk_changed)
        self.tbl_activity.cellClicked.connect(self._on_activity_row_clicked)
        self.tbl_activity.cellDoubleClicked.connect(self._on_activity_double_clicked)
        lay.addWidget(self.tbl_activity)
        lay.addStretch()

    def _mk_import_card(self, i: int) -> QFrame:
        """สร้าง card นำเข้าไฟล์ของแต่ละเครื่อง with drag & drop support"""
        color = SLOT_COLORS[i]
        # สร้าง card ด้วย mk_card แล้วเพิ่มความสามารถ drag & drop
        f = mk_card(top_color=color)
        f.setAcceptDrops(True)
        f._slot_index = i  # เก็บหมายเลข slot เพื่อใช้ในตัวจัดการ
        
        # เพิ่ม drag & drop handler ให้กับ card
        def dragEnterEvent_handler(event):
            if event.mimeData().hasUrls():
                urls = event.mimeData().urls()
                for url in urls:
                    if url.toLocalFile().lower().endswith(('.txt', '.csv')):
                        self._set_drag_highlight(f._slot_index)
                        event.acceptProposedAction()
                        return
            event.ignore()
        
        def dragMoveEvent_handler(event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()
        
        def dragLeaveEvent_handler(event):
            self._clear_drag_highlight()
            event.ignore()
        
        def dropEvent_handler(event):
            self._clear_drag_highlight()
            if event.mimeData().hasUrls():
                urls = event.mimeData().urls()
                for url in urls:
                    file_path = url.toLocalFile()
                    if file_path.lower().endswith(('.txt', '.csv')):
                        self._import_from_path(f._slot_index, file_path)
                        event.acceptProposedAction()
                        break
            else:
                event.ignore()
        
        # Bind the event handlers to the frame
        f.dragEnterEvent = dragEnterEvent_handler
        f.dragMoveEvent = dragMoveEvent_handler
        f.dragLeaveEvent = dragLeaveEvent_handler
        f.dropEvent = dropEvent_handler
        
        f.setMinimumHeight(200)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # Header
        hr = QHBoxLayout()
        dot = QLabel("●"); dot.setFont(fnt(F_LG, True))
        dot.setStyleSheet(f"color:{color};")
        name_l = QLabel(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))
        name_l.setFont(fnt(F_LG, True))
        mode_l = QLabel(""); mode_l.setFont(fnt(F_SM, True))
        mode_l.setStyleSheet(f"color:{color};")
        hr.addWidget(dot); hr.addWidget(name_l); hr.addStretch(); hr.addWidget(mode_l)
        lay.addLayout(hr)

        mach_l = QLabel("—"); mach_l.setFont(fnt(F_LG, True))
        mach_l.setStyleSheet(f"color:{C_TEXT};")
        sn_l = QLabel(""); sn_l.setFont(fnt(F_SM, True))
        sn_l.setStyleSheet(f"color:{C_TEXT};")
        date_l = QLabel(""); date_l.setFont(fnt(F_SM, True))
        date_l.setStyleSheet(f"color:{C_TEXT};")
        lay.addWidget(mach_l); lay.addWidget(sn_l); lay.addWidget(date_l)
        lay.addStretch()

        # ปุ่มนำเข้าและล้าง
        br = QHBoxLayout(); br.setSpacing(8)
        b_imp = btn("📥  นำเข้าไฟล์", "primary")
        b_imp.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        b_clr = btn("🗑", "danger"); b_clr.setFixedWidth(50); b_clr.setMinimumHeight(38)
        b_clr.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 12px; font-weight: 600; font-size: 16px; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        br.addWidget(b_imp); br.addWidget(b_clr)
        lay.addLayout(br)

        b_imp.clicked.connect(lambda _, s=i: self._import(s))
        b_clr.clicked.connect(lambda _, s=i: self._clear(s))

        f._w = {"mach":mach_l,"sn":sn_l,"date":date_l,
                "mode":mode_l,"name":name_l}
        f._import_button = b_imp
        f._clear_button = b_clr
        
        # สร้าง overlay widget สำหรับ drag & drop hint
        overlay = QLabel("", f)  # parent คือ card frame
        overlay.setStyleSheet(
            "QLabel { background-color: rgba(200, 200, 200, 200); border: 2px dashed #999999; "
            "border-radius: 8px; color: #333333; font-weight: 600; }"
        )
        overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay.setFont(fnt(F_MD, False))
        overlay.setGeometry(0, 0, f.width(), f.height())  # ตั้งค่า geometry เมื่อสร้าง
        overlay.setVisible(False)
        f._overlay = overlay
        f._overlay_text = f"วางไฟล์ที่ {get_cfg(f'machine_name_{i}', SLOT_NAMES[i])}"
        
        self._slot_widgets.append(f)
        return f

    def _import(self, slot: int):
        """เปิด file dialog → ใช้ _import_from_path"""
        mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
        path, _ = QFileDialog.getOpenFileName(
            self, f"เลือกไฟล์มิเตอร์ — {mname}",
            "", "Konica Minolta (*.txt *.csv);;All (*)"
        )
        if not path:
            return
        self._import_from_path(slot, path)
    
    def _import_from_path(self, slot: int, path: str):
        """ประมวลผลไฟล์นำเข้า (เรียกจาก _import หรือ drag & drop)"""
        try:
            import_result = parse_import_file(slot, path)
        except Exception as e:
            QMessageBox.critical(self, "เกิดข้อผิดพลาด", f"อ่านไฟล์ไม่ได้:\n{e}")
            return
        parser_name = import_result.parser_name
        parsed = import_result.parsed

        # ── ถ้าไม่พบ Parser ที่ตรงกัน ────────────────────────────────────────
        if import_result.is_unknown_parser:
            machine_name = import_result.unknown_machine_name(path)
            dlg = _NoParserMatchDialog(machine_name, parent=self)
            result = dlg.exec()
            if result == _NoParserMatchDialog.RESULT_OPEN_PARSER:
                _open_check_parser()
                return
            elif result != _NoParserMatchDialog.RESULT_CONFIRM:
                return  # ยกเลิก

        # แสดง Preview Dialog พร้อมชื่อ parser ที่ตรวจพบ
        dlg = PreviewDialog(slot, parsed, path, parser_name=parser_name, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return   # ผู้ใช้กดยกเลิก

        self._start_import_save(slot, parsed, path)

    def _start_import_save(self, slot: int, parsed: dict, path: str):
        self._set_import_busy(slot, True, "กำลังเริ่มบันทึก...")
        self._active_import_slot = slot

        thread = QThread(self)
        worker = ImportSaveWorker(slot, parsed, path)
        worker.moveToThread(thread)
        thread._worker = worker

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_import_progress)
        worker.success.connect(self._on_import_saved)
        worker.error.connect(self._on_import_save_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._forget_import_thread(t))

        self._import_threads.append(thread)
        thread.start()

    def _set_import_busy(self, slot: int | None, busy: bool, message: str = ""):
        for card in self._slot_widgets:
            card.setAcceptDrops(not busy)
            if hasattr(card, "_import_button"):
                card._import_button.setEnabled(not busy)
            if hasattr(card, "_clear_button"):
                card._clear_button.setEnabled(not busy)
        if self.btn_edit_mode:
            self.btn_edit_mode.setEnabled(not busy)
        if self.btn_delete_sel:
            self.btn_delete_sel.setEnabled(not busy)
        if slot is not None and 0 <= slot < len(self._slot_widgets):
            self._slot_widgets[slot]._w["mode"].setText(message)

    def _forget_import_thread(self, thread: QThread):
        if thread in self._import_threads:
            self._import_threads.remove(thread)
        if not self._import_threads:
            self._active_import_slot = None

    @pyqtSlot(str)
    def _on_import_progress(self, message: str):
        if self._active_import_slot is not None:
            self._slot_widgets[self._active_import_slot]._w["mode"].setText(message)

    @pyqtSlot(object)
    def _on_import_saved(self, _saved):
        slot = self._active_import_slot
        self._set_import_busy(slot, False)
        self.refresh()
        self.changed.emit()

    @pyqtSlot(str)
    def _on_import_save_error(self, message: str):
        slot = self._active_import_slot
        self._set_import_busy(slot, False)
        QMessageBox.critical(self, "บันทึกไม่สำเร็จ", message)

    def _clear(self, slot: int):
        """ล้างข้อมูลของ slot"""
        mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
        if QMessageBox.question(self, "ยืนยัน", f"ล้างข้อมูล {mname}?") \
                == QMessageBox.StandardButton.Yes:
            clear_slot(slot)
            self.refresh(); self.changed.emit()

    def _set_drag_highlight(self, slot_index: int):
        """Highlight นาง drag destination ด้วย overlay + shade อื่นๆ"""
        self._current_drag_card = slot_index
        
        for i, card_frame in enumerate(self._slot_widgets):
            if i == slot_index:
                # แสดง overlay widget ในการ์ด destination
                if hasattr(card_frame, '_overlay'):
                    card_frame._overlay.setText(card_frame._overlay_text)
                    card_frame._overlay.setGeometry(0, 0, card_frame.width(), card_frame.height())
                    card_frame._overlay.setVisible(True)
                    card_frame._overlay.raise_()
            else:
                # Shade items อื่นๆ ให้จาง
                card_frame.setStyleSheet(
                    "QFrame { border: 1px solid #E2E8F0 !important; border-radius: 8px; background: rgba(200, 200, 200, 0.15); }"
                )
                if hasattr(card_frame, '_overlay'):
                    card_frame._overlay.setVisible(False)
    
    def _clear_drag_highlight(self):
        """คืนค่าการ์ดเป็นสภาพปกติ"""
        if self._current_drag_card is None:
            return
        
        for i, card_frame in enumerate(self._slot_widgets):
            # รีเซ็ต stylesheet เป็นค่าปกติ
            card_frame.setStyleSheet("QFrame { background: transparent; }")
            if hasattr(card_frame, '_overlay'):
                card_frame._overlay.setVisible(False)
        
        self._current_drag_card = None

    def _on_activity_double_clicked(self, row, col):
        """ดับเบิ้ลคลิกแถว → เปิดไฟล์ที่สำรองไว้ใน imported folder"""
        if self._edit_mode:
            return
        file_item = self.tbl_activity.item(row, 4)
        if not file_item:
            return
        file_name = file_item.text()
        slot = file_item.data(Qt.ItemDataRole.UserRole)
        if slot is None:
            return
        card_name = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
        # [V4.5] กัน path traversal — ใช้ sanitize_filename + ตรวจว่า resolved path อยู่ใต้ base
        safe_name = sanitize_filename(card_name)
        safe_file = Path(file_name).name  # ตัด directory ทิ้งกรณี file_name เป็น path
        safe_file = sanitize_filename(safe_file)
        custom_base = get_cfg("imported_path", "")
        base = Path(custom_base) if custom_base else Path(get_db_path()).parent / "imported"
        archived = (base / safe_name / safe_file).resolve()
        base_resolved = base.resolve()
        if not str(archived).startswith(str(base_resolved)):
            log.warning("blocked path traversal: file_name=%r card=%r", file_name, card_name)
            QMessageBox.warning(self, "ไม่อนุญาต", "เส้นทางไฟล์ไม่ถูกต้อง")
            return
        if archived.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(archived)))
        else:
            QMessageBox.information(
                self, "ไม่พบไฟล์",
                f"ไม่พบไฟล์สำรองที่:\n{archived}\n\n"
                "(ไฟล์ที่ import ก่อนการเพิ่มฟีเจอร์นี้จะยังไม่มีสำรอง)"
            )

    def _on_activity_row_clicked(self, row, col):
        """คลิกแถวใดก็ได้ใน edit mode → toggle checkbox"""
        if not self._edit_mode:
            return
        chk = self.tbl_activity.item(row, 8)
        if chk:
            new_state = Qt.CheckState.Unchecked if chk.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            chk.setCheckState(new_state)

    def _on_activity_chk_changed(self, item):
        if item.column() != 8:
            return
        r = item.row()
        checked = item.checkState() == Qt.CheckState.Checked
        row_bg  = QColor("#EFF6FF") if checked else QColor(0, 0, 0, 0)
        chk_fg  = QColor("#2563EB") if checked else QColor("#94A3B8")
        for c in range(self.tbl_activity.columnCount() - 1):  # cols 0-7
            cell = self.tbl_activity.item(r, c)
            if cell:
                cell.setBackground(row_bg)
        item.setForeground(chk_fg)

    def _toggle_edit_mode(self):
        self._edit_mode = not self._edit_mode
        self.tbl_activity.setColumnHidden(8, not self._edit_mode)
        self.btn_delete_sel.setVisible(self._edit_mode)
        # เปลี่ยน cursor และ alternating เพื่อสื่อว่าคลิกได้
        if self._edit_mode:
            self.tbl_activity.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tbl_activity.setAlternatingRowColors(False)
            self.tbl_activity.setStyleSheet("QTableWidget { background: #F8FAFC; } QTableWidget::item:hover { background: #DBEAFE; }")
            self.btn_edit_mode.setText("✕  ยกเลิก")
            self.btn_edit_mode.setStyleSheet(
                "QPushButton { background: #F1F5F9; color: #64748B; border: 1.5px solid #CBD5E1;"
                " border-radius: 7px; padding: 4px 16px; font-weight: 600; }"
                " QPushButton:hover { background: #CBD5E1; color: #0F172A; }"
            )
        else:
            self.tbl_activity.setCursor(Qt.CursorShape.ArrowCursor)
            self.tbl_activity.setAlternatingRowColors(True)
            self.tbl_activity.setStyleSheet("")
            self.btn_edit_mode.setText("✏️  แก้ไข")
            self.btn_edit_mode.setStyleSheet(
                "QPushButton { background: #EFF6FF; color: #2563EB; border: 1.5px solid #BFDBFE;"
                " border-radius: 7px; padding: 4px 16px; font-weight: 600; }"
                " QPushButton:hover { background: #2563EB; color: white; }"
            )
            for r in range(self.tbl_activity.rowCount()):
                item = self.tbl_activity.item(r, 8)
                if item:
                    item.setCheckState(Qt.CheckState.Unchecked)

    def _delete_selected_activities(self):
        rec_ids = []
        for r in range(self.tbl_activity.rowCount()):
            item = self.tbl_activity.item(r, 8)
            if item and item.checkState() == Qt.CheckState.Checked:
                rec_ids.append(item.data(Qt.ItemDataRole.UserRole))

        if not rec_ids:
            QMessageBox.information(self, "ไม่มีรายการที่เลือก", "กรุณาติ๊กเลือกอย่างน้อย 1 รายการก่อน")
            return

        reply = QMessageBox.question(
            self, "ยืนยันการลบ",
            f"ลบ {len(rec_ids)} รายการที่เลือกใช่หรือไม่?\n\n"
            f"⚠️ ค่ามิเตอร์จะย้อนกลับไปยังรายการที่เหลือ",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            for rid in rec_ids:
                delete_reading(rid)
            self._edit_mode = False
            self.btn_edit_mode.setText("✏️  แก้ไข")
            self.btn_edit_mode.setStyleSheet(
                "QPushButton { background: #EFF6FF; color: #2563EB; border: 1.5px solid #BFDBFE;"
                " border-radius: 7px; padding: 4px 16px; font-weight: 600; }"
                " QPushButton:hover { background: #2563EB; color: white; }"
            )
            self.btn_delete_sel.setVisible(False)
            self.tbl_activity.setColumnHidden(8, True)  # [V4.5] fix: checkbox column is 8 (was incorrectly 7)
            self.refresh()
            self.changed.emit()

    def refresh(self):
        """โหลดข้อมูลล่าสุดและอัปเดตตาราง"""
        self.tbl_activity.setRowCount(0)

        for i in range(3):
            curr, prev = get_last_two(i)
            w = self._slot_widgets[i]._w
            mname = get_cfg(f"machine_name_{i}", SLOT_NAMES[i])
            w["name"].setText(mname)

            if not curr:
                w["mach"].setText("— ยังไม่มีข้อมูล —")
                w["sn"].setText(""); w["date"].setText(""); w["mode"].setText("")
                continue

            w["mach"].setText(curr.get("machine_name", mname))
            w["sn"].setText(f"SN: {curr.get('serial','—')}")
            w["date"].setText(f"📅 {curr.get('date','')}")
            mode = curr["mode"]
            if mode == "account":
                mode_text = "User Mode"
            elif mode == "production":
                mode_text = "Production Mode"
            else:  # "summary" or default
                mode_text = "Summary Mode"
            w["mode"].setText(mode_text)

        # โหลด Activity Log
        self.tbl_activity.blockSignals(True)
        activities = get_activity_log()
        for act in activities:
            r = self.tbl_activity.rowCount(); self.tbl_activity.insertRow(r)
            slot_name = get_cfg(f"machine_name_{act['slot']}", SLOT_NAMES[act["slot"]])
            vals = [
                act["imported_at"],
                slot_name,
                act["machine_name"],
                act["serial"],
                act["file_name"],
                act["read_date"],
                act["billing_month"],
                act.get("parser_name", ""),
            ]
            for c, v in enumerate(vals):
                it = tbl_item(v, mono=(c in [0,3,5,6]))
                if c == 4:  # ชื่อไฟล์ — เก็บ slot ไว้เพื่อใช้ใน double-click
                    it.setData(Qt.ItemDataRole.UserRole, act["slot"])
                self.tbl_activity.setItem(r, c, it)
            # Checkbox สำหรับ edit mode
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Unchecked)
            chk.setForeground(QColor("#94A3B8"))  # เริ่มต้นเทา
            chk.setData(Qt.ItemDataRole.UserRole, act["id"])
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_activity.setItem(r, 8, chk)
        self.tbl_activity.blockSignals(False)


# ══════════════════════════════════════════════════════════
# PAGE: MACHINE DETAIL
# แสดงค่ามิเตอร์รายเครื่อง คล้ายงบการเงิน
# ══════════════════════════════════════════════════════════
class PageHistory(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(12)
        lay.addWidget(sec_title("📈  Reports"))

        # ── เลือกอุปกรณ์ (ปุ่มแยก) - ซ่อนในแท็บผู้ใช้งาน
        self.machine_selector_container = QWidget()
        bar = QHBoxLayout(self.machine_selector_container); bar.setContentsMargins(0,0,0,0); bar.setSpacing(12)
        bar.addWidget(QLabel("อุปกรณ์ที่แสดง:", font=fnt(F_LG)))
        self.slot_btns = {}
        for i in range(3):
            mname = get_cfg(f"machine_name_{i}", SLOT_NAMES[i])
            btn_style = "primary" if i == 0 else "outline"
            b = btn(f"  {mname}", btn_style)
            b.setMinimumWidth(140)
            b.clicked.connect(lambda checked, idx=i: self._select_slot(idx))
            bar.addWidget(b)
            self.slot_btns[i] = b
        
        bar.addStretch()
        self.lbl_info = QLabel("")
        self.lbl_info.setFont(fnt(F_XS)); self.lbl_info.setStyleSheet(f"color:{C_TEXT3};")
        bar.addWidget(self.lbl_info)
        lay.addWidget(self.machine_selector_container)
        self._current_slot = 0

        # ── Tabs: มิเตอร์ปัจจุบัน | ย้อนหลังรายเดือน | เครื่อง | ผู้ใช้งาน
        self.tabs = QTabWidget()
        self.tabs.setFont(fnt(F_LG))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Tab 1: ค่ามิเตอร์ปัจจุบัน (ทุกเครื่อง รวมในหน้าเดียว)
        self.tab_current = QWidget()
        self._build_current_tab()
        self.tabs.addTab(self.tab_current, "📊  ค่ามิเตอร์ปัจจุบัน")

        # Tab 2: เปรียบเทียบรายเดือน (งบการเงิน)
        self.tab_monthly = QWidget()
        self._build_monthly_tab()
        self.tabs.addTab(self.tab_monthly, "📅  ย้อนหลังรายเดือน")

        # Tab 3: ผู้ใช้งาน
        self.tab_users = QWidget()
        self._build_users_tab()
        self.tabs.addTab(self.tab_users, "👤  ผู้ใช้งาน")

        # Tab 4: กราฟประวัติ
        self.tab_graph = QWidget()
        self._build_graph_tab()
        self.tabs.addTab(self.tab_graph, "📈  กราฟประวัติ")

        lay.addWidget(self.tabs, 1)
    
    def _select_slot(self, slot: int):
        """เลือกเครื่องจากปุ่ม (ใช้สำหรับแท็บที่ยังต้องการ)"""
        self._current_slot = slot
        for i, b in self.slot_btns.items():
            b.setObjectName("btn_primary" if i == slot else "btn_outline")
            b.style().unpolish(b)
            b.style().polish(b)
        self.refresh()

    def _on_tab_changed(self, index: int):
        """ซ่อน/แสดง machine selector bar — แท็บ 0, 1, 2, 3 ทั้งหมดซ่อนปุ่มเลือกเครื่อง"""
        # แท็บ 0 (ค่ามิเตอร์ปัจจุบัน) และ 1 (ย้อนหลัง) แสดง 3 เครื่องพร้อมกัน ไม่ต้องใช้ selector
        self.machine_selector_container.setVisible(False)

    def _build_current_tab(self):
        """Tab แสดงค่ามิเตอร์ปัจจุบัน — 3 เครื่องแสดงพร้อมกันในคอลัมน์แยก"""
        lay = QVBoxLayout(self.tab_current)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(10)

        # Header row: ชื่อ + stretch + checkbox ส่วนต่าง
        _hdr = QHBoxLayout()
        _hdr.setSpacing(12)  # เพิ่มระยะห่าง
        _hdr.addWidget(QLabel("ค่ามิเตอร์ปัจจุบัน เทียบกับครั้งก่อน — ทุกเครื่อง", font=fnt(F_LG, True)))
        _hdr.addStretch()
        self.chk_diff = QCheckBox("รวม ส่วนต่าง")
        self.chk_diff.setFont(fnt(F_MD))
        self.chk_diff.setChecked(True)    # default: แสดง (เปลี่ยนจาก False เป็น True)
        self.chk_diff.stateChanged.connect(self._refresh_current_all)
        _hdr.addWidget(self.chk_diff)
        _hdr.addSpacing(12)  # เพิ่มระยะห่างทีขวา
        lay.addLayout(_hdr)

        # ROW LABELS — รายการแสดงใน Tab ค่ามิเตอร์ปัจจุบัน
        # (label, key_curr, key_prev, key_diff, is_header, color)
        self._current_tab_rows = [
            ("── SUMMARY ──",          None, None, None, True, C_TEXT),
            ("Grand Total (P)",        "grand_total",   "grand_total",  "grand_total",  False, C_TEXT),
            ("Full Color Total (P)",   "total_color",   "total_color",  "total_color",  False, C_ORANGE),
            ("B&W Total (P)",          "total_bw",      "total_bw",     "total_bw",     False, C_TEXT2),
            ("── Paper Size ──",       None, None, None, True, C_TEXT),
            ("A4 - Full Color (P)",    "a4_color",   "a4_color",   "a4_color",   False, C_ACCENT),
            ("A4 - B&W (P)",           "a4_bw",      "a4_bw",      "a4_bw",      False, C_TEXT2),
            ("A3 - Full Color (P)",    "a3_color",   "a3_color",   "a3_color",   False, C_ORANGE),
            ("A3 - B&W (P)",           "a3_bw",      "a3_bw",      "a3_bw",      False, C_PURPLE),
            ("Meter - Full Color (M)", "color_meter", "color_meter", "color_meter", False, C_ORANGE),
            ("Meter - B&W (M)",        "bw_meter",    "bw_meter",    "bw_meter",    False, C_TEXT2),
        ]

        # สร้างตาราง 1 ตาราง ร่วมกัน: ซ้าย = รายการ (ค้างไว้), 3 กลุ่ม = แต่ละเครื่อง
        self.tbl_current_all = FrozenLeftTable()
        lay.addWidget(self.tbl_current_all, 1)

        # หมายเหตุขนาดกระดาษ
        _note_curr = QLabel("ℹ️  หมายเหตุ: ขนาดกระดาษที่เล็กกว่า A4 จะถูกนับรวมเป็น A4")
        _note_curr.setFont(fnt(F_XS))
        _note_curr.setStyleSheet(f"color:{C_TEXT3}; padding:3px 2px;")
        lay.addWidget(_note_curr)

    def _build_monthly_tab(self):
        """Tab ย้อนหลังรายเดือน — ทุกเครื่องในคอลัมน์พร้อมกัน"""
        lay = QVBoxLayout(self.tab_monthly)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(10)

        # แสดงวันตัดรอบ
        self.lbl_billing_day = QLabel()
        self.lbl_billing_day.setFont(fnt(F_MD))
        self.lbl_billing_day.setStyleSheet(
            f"color:{C_ACCENT}; background:{SLOT_LIGHT[0]}; "
            f"padding:4px 14px; border-radius:5px;")
        lay.addWidget(self.lbl_billing_day)

        # Header row: ชื่อตาราง (แถวบน)
        _m_hdr = QHBoxLayout()
        _m_hdr.addWidget(QLabel("ยอดการใช้งานแยกตามเดือนบิล", font=fnt(F_LG, True)))
        _m_hdr.addStretch()
        lay.addLayout(_m_hdr)

        # Control row: detail checkbox + waste% checkbox + export (แถวล่าง)
        _m_ctrl = QHBoxLayout()
        _m_ctrl.setSpacing(14)
        _m_ctrl.addStretch()
        self.chk_detail_monthly = QCheckBox("รายละเอียด")
        self.chk_detail_monthly.setFont(fnt(F_MD))
        self.chk_detail_monthly.setChecked(False)   # default: ซ่อนรายละเอียด
        self.chk_detail_monthly.stateChanged.connect(lambda: self._refresh_monthly(self._current_slot))
        _m_ctrl.addWidget(self.chk_detail_monthly)
        self.chk_waste_monthly = QCheckBox()
        self.chk_waste_monthly.setFont(fnt(F_MD))
        self.chk_waste_monthly.setChecked(True)
        self.chk_waste_monthly.stateChanged.connect(lambda: self._refresh_monthly(self._current_slot))
        self._set_waste_checkbox_text()
        _m_ctrl.addWidget(self.chk_waste_monthly)
        self.btn_export_monthly = btn("📥  Export to Excel", "outline")
        self.btn_export_monthly.clicked.connect(
            lambda: self._export_to_excel(self.tbl_monthly, "Monthly_Report_All"))
        _m_ctrl.addWidget(self.btn_export_monthly)
        lay.addLayout(_m_ctrl)

        self.tbl_monthly = FrozenLeftTable()
        lay.addWidget(self.tbl_monthly, 1)

        # หมายเหตุขนาดกระดาษ
        _note_monthly = QLabel("ℹ️  หมายเหตุ: ขนาดกระดาษที่เล็กกว่า A4 จะถูกนับรวมเป็น A4")
        _note_monthly.setFont(fnt(F_XS))
        _note_monthly.setStyleSheet(f"color:{C_TEXT3}; padding:3px 2px;")
        lay.addWidget(_note_monthly)

        # ── Summary stat cards — 2×4 ──────────────────────────────
        sc_grid = QGridLayout(); sc_grid.setSpacing(8)

        # Col 0–1: Color/BW + Cost (compact, 2 rows)
        self.sc_m_total_color = StatCard("Color",    C_ORANGE, compact=True)
        self.sc_m_cost_color  = StatCard("Cost Color(฿)", C_ORANGE, compact=True)
        self.sc_m_total_bw    = StatCard("B&W",      C_TEXT2, compact=True)
        self.sc_m_cost_bw     = StatCard("Cost B&W(฿)", C_TEXT2, compact=True)
        # Col 2–3: Grand Total + Total Cost — ใหญ่ขึ้น span 2 แถว
        self.sc_m_grand       = StatCard("Grand Total",   C_ACCENT, compact=False)
        self.sc_m_grand_cost  = StatCard("Total Cost(฿)", C_GREEN,  compact=False)

        sc_grid.addWidget(self.sc_m_total_color, 0, 0)
        sc_grid.addWidget(self.sc_m_cost_color,  0, 1)
        sc_grid.addWidget(self.sc_m_total_bw,    1, 0)
        sc_grid.addWidget(self.sc_m_cost_bw,     1, 1)
        sc_grid.addWidget(self.sc_m_grand,       0, 2, 2, 1)   # span 2 rows
        sc_grid.addWidget(self.sc_m_grand_cost,  0, 3, 2, 1)   # span 2 rows
        for c in range(4):
            sc_grid.setColumnStretch(c, 1)

        # ── Filter ปุ่มขวาล่าง ────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.addStretch()
        self._monthly_filter = "all"
        self._monthly_filter_btns = {}
        for key, lbl in [("current","ปัจจุบัน"),("3m","3 เดือน"),("1y","12 เดือน"),("current_year","ปีปัจจุบัน"),("all","ทั้งหมด")]:
            b = btn(lbl, "outline" if key != "all" else "primary")
            b.setFont(fnt(F_XS))
            b.setContentsMargins(4, 2, 4, 2)
            b.clicked.connect(lambda _c, k=key: self._set_monthly_card_filter(k))
            filter_row.addWidget(b)
            self._monthly_filter_btns[key] = b

        lay.addLayout(sc_grid)
        lay.addLayout(filter_row)

    def _set_monthly_card_filter(self, key: str):
        """เปลี่ยน filter สำหรับการ์ดสรุป (ย้อนหลัง)"""
        self._monthly_filter = key
        for k, b in self._monthly_filter_btns.items():
            b.setObjectName("btn_primary" if k == key else "btn_outline")
            b.style().unpolish(b); b.style().polish(b)
        self._refresh_monthly(self._current_slot)

    def _set_waste_checkbox_text(self):
        """อัปเดตข้อความ checkbox กระดาษเสียให้แสดงค่า x% ปัจจุบัน"""
        try:
            pct = get_waste_paper_pct()
        except Exception:
            pct = DEFAULT_WASTE_PCT
        self.chk_waste_monthly.setText(f"รวมกระดาษเสีย {pct:.1f}%")

    def refresh(self):
        """โหลดข้อมูลของทุก slot และอัปเดตทุกแท็บ"""
        slot = self._current_slot
        curr, prev = get_last_two(slot)
        mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
        
        # อัปเดต button text
        for i in range(3):
            n = get_cfg(f"machine_name_{i}", SLOT_NAMES[i])
            self.slot_btns[i].setText(f"  {n}")

        # อัปเดต label (ไม่มีผลเมื่อ machine_selector_container ซ่อน)
        if curr:
            self.lbl_info.setText(
                f"{curr.get('machine_name','—')}  ·  SN: {curr.get('serial','—')}  ·  {curr.get('date','')}")
        else:
            self.lbl_info.setText("ยังไม่มีข้อมูล")

        self._refresh_current_all()
        self._refresh_monthly(slot)
        self._populate_month_dropdown_users(slot)
        if _PQG_OK:
            self._reset_graph_date_defaults()
            self._refresh_graph()

    def _populate_month_dropdown_users(self, slot: int):
        """เติมรายการเดือนลง dropdown ของ Users tab - รวม Account + Summary + Production data"""
        self.cmb_month_users.blockSignals(True)
        old_month = self.cmb_month_users.currentData() if self.cmb_month_users.count() > 0 else None
        self.cmb_month_users.clear()
        
        # ดึง billing_month ที่มีข้อมูล (Account mode หรือ Summary/Production) จากทั้ง 3 เครื่อง
        months_with_data = set()
        for i in range(3):
            all_readings = get_all_readings(i)
            for data_json, _, billing_month, _ in all_readings:
                # ตรวจสอบว่ามีข้อมูลใน record นี้หรือไม่
                if isinstance(data_json, str):
                    try:
                        data = json.loads(data_json)
                    except:
                        continue
                else:
                    data = data_json
                
                if not data or not billing_month:
                    continue
                
                # Check for Account mode with named accounts
                has_named_account = False
                if data.get("accounts"):
                    for acc in data.get("accounts", []):
                        if acc.get("name"):
                            has_named_account = True
                            break
                
                # Check for Summary/Production mode with data
                has_summary_data = data.get("summary") and data["summary"].get("total", 0) > 0
                
                # Add month if has either named accounts OR summary data
                if has_named_account or has_summary_data:
                    months_with_data.add(billing_month)
        
        # เรียง months ตามลำดับ ที่ใหม่ก่อน
        months_list = sorted(list(months_with_data), reverse=True)
        
        if not months_list:
            # ถ้าไม่มีข้อมูล เลย ให้แสดงข้อความ
            self.cmb_month_users.addItem("ไม่มีข้อมูล", None)
        else:
            for month in months_list:
                self.cmb_month_users.addItem(month, month)
        
        self.cmb_month_users.blockSignals(False)
        # เลือก item แรก (ล่าสุด) เสมอ ตาม requirement
        if self.cmb_month_users.count() > 0:
            self.cmb_month_users.setCurrentIndex(0)
            # เรียก refresh หลังจาก dropdown เติมเสร็จ
            self._refresh_users(self._current_slot)

    def _reset_graph_date_defaults(self):
        """ตั้งค่าเริ่มต้นช่วงเดือนกราฟ: แสดงทั้งหมด (มุมมองเครื่อง)"""
        self._graph_date_from = ""  # ไม่จำกัดเดือนเริ่มต้น → ทั้งหมด
        self._graph_date_to = ""    # ไม่จำกัดเดือนสุดท้าย → ทั้งหมด

    def _refresh_current_all(self):
        """อัปเดต Tab ค่ามิเตอร์ปัจจุบัน — แสดงทั้ง 3 เครื่องในตารางเดียว"""
        tbl = self.tbl_current_all
        rows_spec = self._current_tab_rows
        n_rows = len(rows_spec)

        # สร้าง header: รายการ | เครื่อง1: ปัจจุบัน | ครั้งก่อน | ส่วนต่าง | เครื่อง2: ... | เครื่อง3: ...
        headers = ["รายการ"]
        for slot in range(3):
            mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
            curr, _ = get_last_two(slot)
            d_curr = curr.get("date", "—") if curr else "—"
            # billing month มาจากแถวล่าสุดของ readings (อาจไม่มีอยู่ใน data_json โดยตรง)
            _rows = get_all_readings(slot)
            bm = _rows[-1][2] if _rows else "—"
            headers += [
                f"{mname}\nปัจจุบัน\n({d_curr})\nรอบบิล {bm}",
                f"ครั้งก่อน",
                f"ส่วนต่าง",
            ]

        tbl.setColumnCount(len(headers))
        tbl.setRowCount(n_rows)
        tbl.setHorizontalHeaderLabels(headers)
        tbl.setColumnWidth(0, 150)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        tbl.verticalHeader().setVisible(False)

        # รวบรวมข้อมูลทั้ง 3 เครื่อง
        slot_data = []
        for slot in range(3):
            curr, prev = get_last_two(slot)
            slot_data.append((curr, prev))

        def _get_val(data, key):
            if data is None: return None
            pc = data.get("paper_color", {})
            sm = data.get("summary", {})
            if key == "grand_total":    return data.get("total_counter", 0)
            if key == "total_color":    return sm.get("total_color", 0)
            if key == "total_bw":       return sm.get("total_bw", 0)
            if key == "a4_color":       return pc.get("a4_color", 0)
            if key == "a4_bw":          return pc.get("a4_bw", 0)
            if key == "a3_color":       return pc.get("a3_color", 0)
            if key == "a3_bw":          return pc.get("a3_bw", 0)
            mt = data.get("meters", {})
            if key == "color_meter":    return mt.get("color_meter", 0)
            if key == "bw_meter":       return mt.get("bw_meter", 0)
            return 0

        for r, (label, ck, pk, dk, is_header, col) in enumerate(rows_spec):
            lbl_item = QTableWidgetItem(label)
            lbl_item.setFont(fnt(F_MD, is_header))
            lbl_item.setForeground(QColor("#000000" if is_header else col))
            lbl_item.setBackground(QColor("#F8FAFC") if is_header else QColor(C_CARD))
            lbl_item.setFlags(lbl_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r, 0, lbl_item)

            for si, (curr, prev) in enumerate(slot_data):
                base_col = 1 + si * 3
                if is_header:
                    for c in range(3):
                        it = QTableWidgetItem("")
                        it.setBackground(QColor("#F8FAFC"))
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        tbl.setItem(r, base_col + c, it)
                else:
                    cv = _get_val(curr, ck)
                    pv = _get_val(prev, pk)
                    dv = max(0, cv - pv) if cv is not None and pv is not None else None

                    c_item = QTableWidgetItem(fn(cv) if cv is not None else "—")
                    c_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    c_item.setFont(fnt(F_MD, True, True))
                    c_item.setForeground(QColor(SLOT_COLORS[si]))
                    c_item.setFlags(c_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    tbl.setItem(r, base_col, c_item)

                    p_item = QTableWidgetItem(fn(pv) if pv is not None else "—")
                    p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    p_item.setFont(fnt(F_MD, False, True))
                    p_item.setForeground(QColor(C_TEXT3))
                    p_item.setFlags(p_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    tbl.setItem(r, base_col + 1, p_item)

                    d_item = QTableWidgetItem(fd(dv) if dv is not None else "—")
                    d_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    d_item.setFont(fnt(F_MD, True, True))
                    d_item.setForeground(QColor(C_GREEN if dv and dv > 0 else C_TEXT2))
                    d_item.setFlags(d_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    tbl.setItem(r, base_col + 2, d_item)

        # แสดง/ซ่อนคอลัมน์ ครั้งก่อน + ส่วนต่าง ตาม checkbox
        show_diff = hasattr(self, 'chk_diff') and self.chk_diff.isChecked()
        for si in range(3):
            base = 1 + si * 3
            tbl.setColumnHidden(base + 1, not show_diff)   # ครั้งก่อน
            tbl.setColumnHidden(base + 2, not show_diff)   # ส่วนต่าง

    def _refresh_current(self, curr: dict, prev: dict, slot: int):
        """(เดิม) ใช้ได้เมื่อ tbl_current ยังอยู่ — keep for backward compat"""
        pass  # ถูกแทนที่ด้วย _refresh_current_all แล้ว

    def _refresh_monthly(self, slot: int):
        """อัปเดต Tab ย้อนหลังรายเดือน — แสดงทุกเครื่องในคอลัมน์"""
        # slot param kept for backward-compat but all 3 slots are shown

        # ─── Column specs ───────────────────────────────────────────────
        STD_SPEC = [
            ("Grand Total (P)",   "total_counter"),
            ("Color (P)",         "total_color"),
            ("B&W (P)",           "total_bw"),
            ("A4 สี (P)",         "a4_color"),
            ("A4 ขาวดำ (P)",      "a4_bw"),
            ("A3 สี (P)",         "a3_color"),
            ("A3 ขาวดำ (P)",      "a3_bw"),
            ("ค่าใช้จ่าย (฿)",    "cost"),
        ]
        LBL_SPEC = [
            ("Grand Total (P)",   "total_counter"),
            ("Meter - สี (M)",    "color_meter"),
            ("Meter - ขาวดำ (M)", "bw_meter"),
            ("ค่าใช้จ่าย (฿)",   "cost"),
        ]
        TOT_SPEC = [
            ("Grand Total (P)",   "total_counter"),
            ("Color (P)",         "total_color"),
            ("B&W (P)",           "total_bw"),
            ("A4 สี (P)",         "a4_color"),
            ("A4 ขาวดำ (P)",      "a4_bw"),
            ("A3 สี (P)",         "a3_color"),
            ("A3 ขาวดำ (P)",      "a3_bw"),
            ("Meter - สี (M)",    "color_meter"),
            ("Meter - ขาวดำ (M)", "bw_meter"),
            ("ค่าใช้จ่าย (฿)",    "cost"),
        ]
        # detail cols (index range to hide when detail OFF): STD=1..6, LBL=1..2, TOT=1..9
        STD_DETAIL_RANGE = range(1, 7)
        LBL_DETAIL_RANGE = range(1, 3)
        TOT_DETAIL_RANGE = range(1, 9)

        # ─── Detect Label mode per slot ─────────────────────────────────
        # ตรวจสอบจาก (1) การตั้งค่า Parser ใน Settings ก่อน
        # หากไม่มีการตั้งค่า จึง fallback ไปดู mode ของ reading ล่าสุด
        def _is_label_slot(s):
            parser_id_str = get_cfg(f"parser_{s}", "")
            if parser_id_str:
                try:
                    profile_slot = int(parser_id_str)
                    all_profiles = load_profiles()
                    for prof in all_profiles:
                        if prof.get("slot") == profile_slot:
                            if "label" in prof.get("types", []):
                                return True
                            break
                except (ValueError, TypeError):
                    pass
            curr, _ = get_last_two(s)
            return curr is not None and curr.get("mode") == "label"
        is_label = [_is_label_slot(s) for s in range(3)]
        slot_specs = [LBL_SPEC if is_label[s] else STD_SPEC for s in range(3)]

        # --- helper: compute monthly data for a single slot ---
        def _compute_monthly_for_slot(s):
            md_slot = {}
            all_readings = get_all_readings(s)
            prev = None
            for data_json, imp_at, billing_month, rec_id in all_readings:
                if isinstance(data_json, str):
                    try:
                        data = json.loads(data_json)
                    except Exception:
                        continue
                else:
                    data = data_json
                if billing_month not in md_slot:
                    md_slot[billing_month] = {
                        "total_counter": 0, "a4_color": 0, "a4_bw": 0,
                        "a3_color": 0, "a3_bw": 0, "total_color": 0,
                        "total_bw": 0, "color_meter": 0, "bw_meter": 0,
                        "reading_ids": []
                    }
                md_slot[billing_month]["reading_ids"].append(rec_id)
                pc = data.get("paper_color", {})
                sm = data.get("summary", {})
                mt = data.get("meters", {})
                if prev:
                    pcp = prev.get("paper_color", {})
                    psm = prev.get("summary", {})
                    pmt = prev.get("meters", {})
                    md_slot[billing_month]["total_counter"] += max(0, data.get("total_counter", 0) - prev.get("total_counter", 0))
                    md_slot[billing_month]["a4_color"]  += max(0, pc.get("a4_color", 0)  - pcp.get("a4_color", 0))
                    md_slot[billing_month]["a4_bw"]     += max(0, pc.get("a4_bw", 0)     - pcp.get("a4_bw", 0))
                    md_slot[billing_month]["a3_color"]  += max(0, pc.get("a3_color", 0)  - pcp.get("a3_color", 0))
                    md_slot[billing_month]["a3_bw"]     += max(0, pc.get("a3_bw", 0)     - pcp.get("a3_bw", 0))
                    md_slot[billing_month]["total_color"] += max(0, sm.get("total_color", 0) - psm.get("total_color", 0))
                    md_slot[billing_month]["total_bw"]   += max(0, sm.get("total_bw", 0)    - psm.get("total_bw", 0))
                    md_slot[billing_month]["color_meter"] += max(0, mt.get("color_meter", 0) - pmt.get("color_meter", 0))
                    md_slot[billing_month]["bw_meter"]    += max(0, mt.get("bw_meter", 0)    - pmt.get("bw_meter", 0))
                else:
                    md_slot[billing_month]["total_counter"] += data.get("total_counter", 0)
                    md_slot[billing_month]["a4_color"]   += pc.get("a4_color", 0)
                    md_slot[billing_month]["a4_bw"]      += pc.get("a4_bw", 0)
                    md_slot[billing_month]["a3_color"]   += pc.get("a3_color", 0)
                    md_slot[billing_month]["a3_bw"]      += pc.get("a3_bw", 0)
                    md_slot[billing_month]["total_color"] += sm.get("total_color", 0)
                    md_slot[billing_month]["total_bw"]   += sm.get("total_bw", 0)
                    md_slot[billing_month]["color_meter"] += mt.get("color_meter", 0)
                    md_slot[billing_month]["bw_meter"]    += mt.get("bw_meter", 0)
                prev = data
            # Compute costs per month
            for month, mdat in md_slot.items():
                _a4c_p = _a4bw_p = _a3c_p = _a3bw_p = 0.0
                # [V4.5] ใช้ snapshot ของ reading สุดท้ายของเดือน (ราคาที่ใช้จริงตอนสิ้นเดือน)
                # — เดิมใช้ reading แรกซึ่งไม่สะท้อนราคาปัจจุบัน
                rids = mdat.get("reading_ids", [])
                for rid in reversed(rids):
                    snap = get_price_snapshot(rid)
                    if snap:
                        _a4c_p  = float(snap.get(f"{s}_a4_color", 0))
                        _a4bw_p = float(snap.get(f"{s}_a4_bw",    0))
                        _a3c_p  = float(snap.get(f"{s}_a3_color", 0))
                        _a3bw_p = float(snap.get(f"{s}_a3_bw",    0))
                        break
                if (_a4c_p + _a4bw_p + _a3c_p + _a3bw_p) <= 0:
                    _a4c_p  = get_price("a4_color", s)
                    _a4bw_p = get_price("a4_bw",    s)
                    _a3c_p  = get_price("a3_color", s)
                    _a3bw_p = get_price("a3_bw",    s)
                if is_label[s]:
                    # Label mode: ราคา meter สี/ขาวดำ
                    _cm = mdat.get("color_meter", 0)
                    _bm = mdat.get("bw_meter",    0)
                    if _cm > 0 or _bm > 0:
                        # มี label meter data → ใช้ label formula
                        mdat["cost"]       = _cm * _a4c_p + _bm * _a4bw_p
                        mdat["cost_color"] = _cm * _a4c_p
                        mdat["cost_bw"]    = _bm * _a4bw_p
                    else:
                        # ไม่มี meter data (reading เก่าที่บันทึกไว้ก่อนเปลี่ยนเป็น label)
                        # → fallback ใช้ standard formula
                        mdat["cost"]       = (mdat.get("a4_color", 0) * _a4c_p + mdat.get("a4_bw", 0) * _a4bw_p +
                                              mdat.get("a3_color", 0) * _a3c_p + mdat.get("a3_bw", 0) * _a3bw_p)
                        mdat["cost_color"] = mdat.get("a4_color", 0) * _a4c_p + mdat.get("a3_color", 0) * _a3c_p
                        mdat["cost_bw"]    = mdat.get("a4_bw",    0) * _a4bw_p + mdat.get("a3_bw",    0) * _a3bw_p
                else:
                    mdat["cost"]       = (mdat.get("a4_color", 0) * _a4c_p + mdat.get("a4_bw", 0) * _a4bw_p +
                                          mdat.get("a3_color", 0) * _a3c_p + mdat.get("a3_bw", 0) * _a3bw_p)
                    mdat["cost_color"] = mdat.get("a4_color", 0) * _a4c_p + mdat.get("a3_color", 0) * _a3c_p
                    mdat["cost_bw"]    = mdat.get("a4_bw",    0) * _a4bw_p + mdat.get("a3_bw",    0) * _a3bw_p
            return md_slot

        # Collect data for all 3 slots
        all_slot_data = [_compute_monthly_for_slot(s) for s in range(3)]

        # Union of all months, newest first — fill gaps between earliest and latest
        all_months_set = set()
        for sd in all_slot_data:
            all_months_set.update(sd.keys())
        if all_months_set:
            # Generate continuous range from min to max month
            _min = min(all_months_set)
            _max = max(all_months_set)
            _cur = datetime.strptime(_min, "%Y-%m")
            _end = datetime.strptime(_max, "%Y-%m")
            while _cur <= _end:
                all_months_set.add(_cur.strftime("%Y-%m"))
                if _cur.month == 12:
                    _cur = _cur.replace(year=_cur.year + 1, month=1)
                else:
                    _cur = _cur.replace(month=_cur.month + 1)
        months = sorted(all_months_set, reverse=True)

        # อัปเดต label ของ checkbox ให้ตรงกับค่าปัจจุบันใน settings
        if hasattr(self, 'chk_waste_monthly'):
            self._set_waste_checkbox_text()

        # Waste % factor
        waste_factor = 1.0
        if self.chk_waste_monthly.isChecked():
            waste_factor = 1.0 - get_waste_paper_pct() / 100.0

        # --- Update billing day label ---
        billing_day = get_billing_day()
        _thai_mo = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        self.lbl_billing_day.setText(
            f"📅  วันตัดรอบบิล: วันที่ {billing_day} ของทุกเดือน  "
            f"  (เช่น วันที่ {billing_day} ม.ค. ถึง วันที่ {billing_day} ก.พ. = รอบเดือน ก.พ.)")

        def _fmt_billing_col(bm_str):
            try:
                dt = datetime.strptime(bm_str, "%Y-%m")
                mo_name = _thai_mo[dt.month - 1]
                year_be = dt.year + 543
                if dt.month == 1:
                    prev_mo = datetime(dt.year - 1, 12, 1)
                else:
                    prev_mo = datetime(dt.year, dt.month - 1, 1)
                start_lbl = f"{billing_day + 1} {_thai_mo[prev_mo.month - 1]}"
                end_lbl   = f"{billing_day} {mo_name}"
                return f"{mo_name} {year_be}\n({start_lbl} – {end_lbl})"
            except Exception:
                return bm_str

        # ─── Build dynamic headers with per-slot COL_SPEC ───────────────
        tbl = self.tbl_monthly
        tbl.blockSignals(True)

        hdrs = ["เดือน"]
        slot_bases = []          # absolute col index where each slot group starts
        for si in range(3):
            slot_bases.append(len(hdrs))
            mname = get_cfg(f"machine_name_{si}", SLOT_NAMES[si])
            for col_lbl, _ in slot_specs[si]:
                hdrs.append(f"{mname}\n{col_lbl}")
        tot_base = len(hdrs)     # absolute col index where รวมทั้งหมด group starts
        for col_lbl, _ in TOT_SPEC:
            hdrs.append(f"รวมทั้งหมด\n{col_lbl}")

        tbl.setRowCount(len(months))
        tbl.setColumnCount(len(hdrs))
        tbl.setHorizontalHeaderLabels(hdrs)
        tbl.setColumnWidth(0, 120)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setVisible(False)

        for r, month in enumerate(months):
            mo_item = QTableWidgetItem(_fmt_billing_col(month))
            mo_item.setFont(fnt(F_MD, True))
            mo_item.setForeground(QColor(C_ACCENT))
            mo_item.setBackground(QColor("#F8FAFC"))
            mo_item.setFlags(mo_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            mo_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 0, mo_item)

            col_idx = 1
            total_md = {
                "total_counter": 0,
                "total_color": 0,
                "total_bw": 0,
                "a4_color": 0,
                "a4_bw": 0,
                "a3_color": 0,
                "a3_bw": 0,
                "color_meter": 0,
                "bw_meter": 0,
                "cost": 0.0,
            }
            # กลุ่มข้อมูลรายเครื่อง (เครื่อง 1, 2, 3)
            for si in range(3):
                slot_color = QColor(SLOT_COLORS[si])
                md = all_slot_data[si].get(month, {})
                total_md["total_counter"] += md.get("total_counter", 0)
                total_md["total_color"]   += md.get("total_color", 0)
                total_md["total_bw"]      += md.get("total_bw", 0)
                total_md["a4_color"]      += md.get("a4_color", 0)
                total_md["a4_bw"]         += md.get("a4_bw", 0)
                total_md["a3_color"]      += md.get("a3_color", 0)
                total_md["a3_bw"]         += md.get("a3_bw", 0)
                total_md["color_meter"]   += md.get("color_meter", 0)
                total_md["bw_meter"]      += md.get("bw_meter", 0)
                total_md["cost"]          += md.get("cost", 0.0)
                for col_lbl, key in slot_specs[si]:
                    val = md.get(key, 0)
                    if key == "cost":
                        val = val * waste_factor
                        text = fmt_baht(val) if val != 0 else "–"
                        bold = True
                    else:
                        text = fn(int(val)) if val != 0 else "–"
                        bold = (key == "total_counter")
                    cell = QTableWidgetItem(text)
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setFont(fnt(F_MD, bold))
                    cell.setForeground(slot_color)
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    tbl.setItem(r, col_idx, cell)
                    col_idx += 1

            # กลุ่มข้อมูล "รวมทั้งหมด" (1+2+3) ขวาสุด
            total_fg = QColor(C_ACCENT)
            for col_lbl, key in TOT_SPEC:
                val = total_md.get(key, 0)
                if key == "cost":
                    val = val * waste_factor
                    text = fmt_baht(val) if val != 0 else "–"
                    bold = True
                else:
                    text = fn(int(val)) if val != 0 else "–"
                    bold = (key == "total_counter")
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFont(fnt(F_MD, bold))
                cell.setForeground(total_fg)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r, col_idx, cell)
                col_idx += 1

        tbl.blockSignals(False)

        # --- Update stat cards filtered by self._monthly_filter ---
        if self._monthly_filter == "all" or not months:
            relevant = set(months)
        elif self._monthly_filter == "current_year":
            # ตั้งแต่มกรา ของปีที่มีค่า ถึงเดือนสุดท้ายที่มีค่า
            if months:
                latest_month = months[0]  # newest first
                latest_year = int(latest_month.split("-")[0])
                relevant = set([m for m in months if int(m.split("-")[0]) == latest_year])
            else:
                relevant = set()
        else:
            n_back = {"current": 1, "3m": 3, "1y": 12}.get(self._monthly_filter, len(months))
            relevant = set(months[:n_back])

        agg_grand = agg_grand_cost = agg_color = agg_color_cost = agg_bw = agg_bw_cost = 0.0
        for month in relevant:
            for si in range(3):
                md = all_slot_data[si].get(month, {})
                agg_grand      += md.get("total_counter", 0)
                agg_color      += md.get("total_color", 0)
                agg_bw         += md.get("total_bw", 0)
                agg_grand_cost += md.get("cost", 0) * waste_factor
                agg_color_cost += md.get("cost_color", 0) * waste_factor
                agg_bw_cost    += md.get("cost_bw", 0) * waste_factor

        self.sc_m_grand.set_value(int(agg_grand))
        self.sc_m_grand_cost.set_baht(agg_grand_cost)
        self.sc_m_total_color.set_value(int(agg_color))
        self.sc_m_cost_color.set_baht(agg_color_cost)
        self.sc_m_total_bw.set_value(int(agg_bw))
        self.sc_m_cost_bw.set_baht(agg_bw_cost)

        # แสดง/ซ่อนคอลัมน์รายละเอียด ตาม checkbox และ per-slot COL_SPEC
        show_detail = hasattr(self, 'chk_detail_monthly') and self.chk_detail_monthly.isChecked()
        for si in range(3):
            base = slot_bases[si]
            detail_range = LBL_DETAIL_RANGE if is_label[si] else STD_DETAIL_RANGE
            for ci in detail_range:
                tbl.setColumnHidden(base + ci, not show_detail)
        # รวมทั้งหมด group: ใช้ TOT_DETAIL_RANGE
        for ci in TOT_DETAIL_RANGE:
            tbl.setColumnHidden(tot_base + ci, not show_detail)

    def _build_users_tab(self):
        """Tab แสดงผู้ใช้งาน (History tab) — 2 มุมมอง: ภาพรวม / แบ่งตามเครื่อง"""
        lay = QVBoxLayout(self.tab_users)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(10)

        tr = QHBoxLayout()
        # Dropdown สำหรับเลือกเดือน
        tr.addWidget(QLabel("เดือนที่แสดง:", font=fnt(F_LG)))
        self.cmb_month_users = QComboBox()
        self.cmb_month_users.setFixedWidth(140)
        self.cmb_month_users.currentIndexChanged.connect(self._on_month_users_changed)
        tr.addWidget(self.cmb_month_users)

        # ── ปุ่มเลือกมุมมอง ──
        tr.addSpacing(20)
        tr.addWidget(QLabel("มุมมอง:", font=fnt(F_LG)))
        self._users_view_btns = {}
        for key, label in [("overview", "📋  ภาพรวม"), ("by_machine", "🖨  แบ่งตามเครื่อง")]:
            b = btn(label, "primary" if key == "overview" else "outline")
            b.setFixedWidth(150)
            b.clicked.connect(lambda checked, k=key: self._set_users_view(k))
            tr.addWidget(b)
            self._users_view_btns[key] = b

        tr.addStretch()
        self.search_users = QLineEdit()
        self.search_users.setPlaceholderText("🔍  ค้นหาชื่อ...")
        self.search_users.setFixedWidth(220)
        self.search_users.textChanged.connect(self._filter_users)
        tr.addWidget(self.search_users)

        self.btn_export_users = btn("📥  Export to Excel", "outline")
        self.btn_export_users.clicked.connect(lambda: self._export_to_excel(self.tbl_users, "Users_Report"))
        tr.addWidget(self.btn_export_users)

        lay.addLayout(tr)

        self.lbl_count_users = QLabel("")
        self.lbl_count_users.setFont(fnt(F_MD))
        self.lbl_count_users.setStyleSheet(f"color:{C_TEXT2};")
        lay.addWidget(self.lbl_count_users)

        # เริ่มต้นเป็น overview mode — 17 คอลัมน์ (frozen ชื่อผู้ใช้ + ค่าใช้จ่าย)
        cols = ["ชื่อผู้ใช้",
                "Total\nCounter (P)", "Total\nColor (P)", "Total\nB&W (P)",
                "Meter\nสี (M)", "Meter\nขาวดำ (M)",
                "Total\nPrint (P)", "Total\nCopy (P)",
                "Print\nA4 สี (P)", "Print\nA4 ขาวดำ (P)", "Print\nA3 สี (P)", "Print\nA3 ขาวดำ (P)",
                "Copy\nA4 สี (P)", "Copy\nA4 ขาวดำ (P)", "Copy\nA3 สี (P)", "Copy\nA3 ขาวดำ (P)",
                "ค่าใช้จ่าย (฿)"]
        self.tbl_users = FrozenColTable()
        self.tbl_users.configure(cols, left_width=160, right_width=115, mid_col_width=88)
        # ซ่อน Meter สี / Meter ขาวดำ ใน overview (global col 4,5 → mid local 3,4)
        self.tbl_users._mid.setColumnHidden(3, True)
        self.tbl_users._mid.setColumnHidden(4, True)
        self.tbl_users.setAlternatingRowColors(True)
        lay.addWidget(self.tbl_users, 1)

        self._users_rows_overview = []   # 15-element row list
        self._users_rows_machine = []    # 14-element row list
        self._users_view_mode = "overview"

    def _set_users_view(self, mode: str):
        """เปลี่ยนมุมมอง Users tab (overview / by_machine)"""
        self._users_view_mode = mode
        for k, b in self._users_view_btns.items():
            b.setObjectName("btn_primary" if k == mode else "btn_outline")
            b.style().unpolish(b)
            b.style().polish(b)
        self._rebuild_users_columns()
        self._repopulate_users()

    def _rebuild_users_columns(self):
        """ปรับ column headers ของ tbl_users ตาม view mode (FrozenColTable)"""
        if self._users_view_mode == "overview":
            cols = ["ชื่อผู้ใช้",
                    "Total\nCounter (P)", "Total\nColor (P)", "Total\nB&W (P)",
                    "Meter\nสี (M)", "Meter\nขาวดำ (M)",
                    "Total\nPrint (P)", "Total\nCopy (P)",
                    "Print\nA4 สี (P)", "Print\nA4 ขาวดำ (P)", "Print\nA3 สี (P)", "Print\nA3 ขาวดำ (P)",
                    "Copy\nA4 สี (P)", "Copy\nA4 ขาวดำ (P)", "Copy\nA3 สี (P)", "Copy\nA3 ขาวดำ (P)",
                    "ค่าใช้จ่าย (฿)"]
            self.tbl_users.configure(cols, left_width=160, right_width=115, mid_col_width=88)
            # ซ่อน Meter สี / Meter ขาวดำ (global col 4,5 → mid local 3,4)
            self.tbl_users._mid.setColumnHidden(3, True)
            self.tbl_users._mid.setColumnHidden(4, True)
        else:
            m_names = [get_cfg(f"machine_name_{i}", SLOT_NAMES[i]) for i in range(3)]
            cols = ["ชื่อผู้ใช้",
                    f"{m_names[0]}\nสี (P)", f"{m_names[0]}\nขาวดำ (P)", f"{m_names[0]}\nรวม (P)",
                    f"{m_names[1]}\nสี (P)", f"{m_names[1]}\nขาวดำ (P)", f"{m_names[1]}\nรวม (P)",
                    f"{m_names[2]}\nสี (P)", f"{m_names[2]}\nขาวดำ (P)", f"{m_names[2]}\nรวม (P)",
                    "รวมสี (P)", "รวมขาวดำ (P)", "รวมทั้งหมด (P)", "ค่าใช้จ่าย (฿)"]
            self.tbl_users.configure(cols, left_width=160, right_width=115, mid_col_width=88)
            # ยืนยันว่าทุกคอลัมน์ mid แสดงครบ (ล้างสถานะ hidden จาก overview)
            for _c in range(self.tbl_users._mid.columnCount()):
                self.tbl_users._mid.setColumnHidden(_c, False)

    def _repopulate_users(self):
        """เติมข้อมูลลงตาราง Users ตาม view mode ปัจจุบัน (แถวรวมแสดงเสมอ)"""
        text = self.search_users.text().lower()
        if self._users_view_mode == "overview":
            rows = [(t, rv) for t, rv in self._users_rows_overview
                    if rv[0] == "รวมทั้งหมด" or text in rv[0].lower()]
            self._populate_users_overview(rows)
        else:
            rows = [(t, rv) for t, rv in self._users_rows_machine
                    if rv[0] == "รวมทั้งหมด" or text in rv[0].lower()]
            self._populate_users_machine(rows)

    def _build_graph_tab(self):
        _load_pyqtgraph()
        """Tab แสดงกราฟประวัติการใช้งาน — Clustered Bar Chart"""
        lay = QVBoxLayout(self.tab_graph)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(10)

        # ── ส่วนควบคุม: ปุ่มมุมมอง + ปุ่ม action ──
        ctrl_frame = QFrame()
        ctrl_frame.setMinimumHeight(42)
        ctrl_lay = QHBoxLayout(ctrl_frame)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ctrl_lay.setSpacing(6)

        ctrl_lay.addWidget(QLabel("มุมมอง:", font=fnt(F_LG)))
        self._graph_view_btns = {}
        for key, label in [("by_machine", "เครื่อง"), ("by_type", "ประเภทงาน"), ("by_user", "ผู้ใช้งาน")]:
            b = btn(label, "primary" if key == "by_machine" else "outline")
            b.setMinimumWidth(92)
            b.clicked.connect(lambda checked, k=key: self._set_graph_view(k))
            ctrl_lay.addWidget(b)
            self._graph_view_btns[key] = b

        ctrl_lay.addStretch()

        # Checkbox แสดงค่าในกราฟ
        self.chk_show_values = QCheckBox("แสดงตัวเลข")
        self.chk_show_values.setFont(fnt(F_MD))
        self.chk_show_values.setChecked(False)
        self.chk_show_values.stateChanged.connect(self._refresh_graph)
        ctrl_lay.addWidget(self.chk_show_values)

        ctrl_lay.addSpacing(8)

        # Checkbox Public User (สำหรับ by_user mode)
        self.chk_public_user = QCheckBox("รวม Public User")
        self.chk_public_user.setFont(fnt(F_MD))
        self.chk_public_user.setChecked(True)
        self.chk_public_user.stateChanged.connect(self._refresh_graph)
        self.chk_public_user.setVisible(False)
        ctrl_lay.addWidget(self.chk_public_user)

        # เพิ่มระยะหว่าง 12px
        ctrl_lay.addSpacing(12)

        # ปุ่ม Reset View
        self.btn_reset_view = btn("Reset", "outline")
        self.btn_reset_view.setMinimumWidth(78)
        self.btn_reset_view.clicked.connect(self._reset_graph_view)
        ctrl_lay.addWidget(self.btn_reset_view)

        # ปุ่ม Save to PNG
        self.btn_save_png = btn("Save PNG", "outline")
        self.btn_save_png.setMinimumWidth(88)
        self.btn_save_png.clicked.connect(self._save_graph_png)
        ctrl_lay.addWidget(self.btn_save_png)

        lay.addWidget(ctrl_frame)

        # ─── Date Range Filter Bar (บรรทัดที่ 2) ───
        # ค่าเริ่มต้น: 3 เดือนก่อนหน้า → เดือนปัจจุบัน
        today = datetime.now()
        self._current_month = today.strftime("%Y-%m")
        _y, _mo = today.year, today.month - 3
        if _mo <= 0:
            _mo += 12
            _y -= 1
        self._graph_date_from = f"{_y}-{_mo:02d}"
        self._graph_date_to = self._current_month
        self._available_months_for_filter = []  # จะเติมหลัง _prepare_graph_data()

        date_frame = QFrame()
        date_frame.setMinimumHeight(42)
        date_lay = QHBoxLayout(date_frame)
        date_lay.setContentsMargins(0, 0, 0, 0)
        date_lay.setSpacing(6)

        date_lay.addWidget(QLabel("ช่วงรอบบิล:", font=fnt(F_LG)))

        self.cmb_date_from = QComboBox()
        self.cmb_date_from.setMinimumWidth(130)
        self.cmb_date_from.setFont(fnt(F_MD))
        self.cmb_date_from.currentTextChanged.connect(self._on_date_from_changed)
        date_lay.addWidget(self.cmb_date_from)

        date_lay.addWidget(QLabel("ถึง", font=fnt(F_LG)))

        self.cmb_date_to = QComboBox()
        self.cmb_date_to.setMinimumWidth(130)
        self.cmb_date_to.setFont(fnt(F_MD))
        self.cmb_date_to.currentTextChanged.connect(self._on_date_to_changed)
        date_lay.addWidget(self.cmb_date_to)

        self.btn_date_reset = btn("ปีปัจจุบัน", "outline")
        self.btn_date_reset.setMinimumWidth(110)
        self.btn_date_reset.clicked.connect(self._on_date_reset_all)
        date_lay.addWidget(self.btn_date_reset)

        self.btn_date_all = btn("ทั้งหมด", "outline")
        self.btn_date_all.setMinimumWidth(100)
        self.btn_date_all.clicked.connect(self._on_date_show_all)
        date_lay.addWidget(self.btn_date_all)

        date_lay.addStretch()

        lay.addWidget(date_frame)

        # ── Machine filter row (ใต้ช่วงเดือน — สำหรับ by_user mode) ─────────
        mach_frame = QFrame()
        mach_frame.setMinimumHeight(42)
        mach_lay = QHBoxLayout(mach_frame)
        mach_lay.setContentsMargins(0, 0, 0, 0)
        mach_lay.setSpacing(6)
        mach_lay.addWidget(QLabel("เครื่อง (ผู้ใช้งาน):", font=fnt(F_LG)))
        self._graph_user_machine_filter = {0, 1, 2}
        self._graph_mach_filter_btns = {}
        for _si in range(3):
            _b = btn(SLOT_NAMES[_si], "primary")
            _b.setMinimumWidth(100)
            _b.clicked.connect(lambda _c, s=_si: self._toggle_graph_machine_filter(s))
            mach_lay.addWidget(_b)
            self._graph_mach_filter_btns[_si] = _b
        mach_lay.addStretch()
        self.graph_machine_filter_frame = mach_frame
        mach_frame.setVisible(False)
        lay.addWidget(mach_frame)

        # ── PlotWidget สำหรับแสดงกราฟ
        if _PQG_OK:
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground(GRAPH_BG_COLOR)
            
            # ปรับขนาด font ของ axis labels
            left_axis = self.plot_widget.getAxis('left')
            left_axis.setLabel('จำนวน (แผ่น)', units='', size=GRAPH_AXIS_LABEL_SIZE)
            
            bottom_axis = self.plot_widget.getAxis('bottom')
            bottom_axis.setLabel('รอบบิล', units='', size=GRAPH_AXIS_LABEL_SIZE)
            
            # ปรับขนาด font ของ title โดยตั้ง TitleLabel
            self.plot_widget.setTitle('ประวัติการใช้งาน')
            pi = self.plot_widget.getPlotItem()
            if pi.titleLabel is not None:
                pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
            
            self.plot_widget.showGrid(x=True, y=True, alpha=GRAPH_GRID_ALPHA)
            self.plot_widget.setMinimumHeight(200)
            lay.addWidget(self.plot_widget, 1)
            self._graph_data_cache = {}
            self._mouse_proxy = pg.SignalProxy(
                self.plot_widget.scene().sigMouseMoved,
                rateLimit=60, slot=self._on_mouse_moved)

        # ── Pie chart container สำหรับ by_type / by_user ──────
        # Layout: Pie ใหญ่รวม (บน) + Row 3 Pie เล็กแยกเครื่อง (ล่าง)
        self.pie_container = QWidget()
        self.pie_container.setStyleSheet(f"background: {C_BG};")
        self.pie_container.setVisible(False)
        pie_vlay = QVBoxLayout(self.pie_container)
        pie_vlay.setContentsMargins(0, 0, 0, 0)
        pie_vlay.setSpacing(6)

        # Pie ใหญ่รวมทุกเครื่อง
        self.pie_view_all = QChartView()
        self.pie_view_all.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.pie_view_all.setStyleSheet(f"background: {C_CARD}; border-radius: 8px; border: none;")
        self.pie_view_all.setMinimumHeight(300)
        pie_vlay.addWidget(self.pie_view_all, 5)

        # Row 3 Pie เล็กแยกเครื่อง
        pie_small_row = QHBoxLayout()
        pie_small_row.setSpacing(6)
        self.pie_views_slot = []
        for _i in range(3):
            _v = QChartView()
            _v.setRenderHint(QPainter.RenderHint.Antialiasing)
            _v.setStyleSheet(f"background: {C_CARD}; border-radius: 8px; border: none;")
            _v.setMinimumHeight(220)
            pie_small_row.addWidget(_v, 1)
            self.pie_views_slot.append(_v)
        pie_vlay.addLayout(pie_small_row, 3)

        lay.addWidget(self.pie_container, 1)

        # ── Legend checkbox สำหรับ by_user (วางใต้แกน X) ──
        self._ext_legend_widget = QWidget()
        self._ext_legend_layout = _FlowLayout(self._ext_legend_widget, margin=6, spacing=20)
        self._ext_legend_widget.setVisible(False)
        lay.addWidget(self._ext_legend_widget)

        self._graph_view_mode = "by_machine"
        self._graph_initialized = True

    # ── Graph view button callback ──────────────────────────────────────
    def _toggle_graph_machine_filter(self, si: int):
        """Toggle เครื่องที่แสดงใน by_user mode"""
        if si in self._graph_user_machine_filter:
            if len(self._graph_user_machine_filter) > 1:
                self._graph_user_machine_filter.discard(si)
        else:
            self._graph_user_machine_filter.add(si)
        for s, b in self._graph_mach_filter_btns.items():
            b.setObjectName("btn_primary" if s in self._graph_user_machine_filter else "btn_outline")
            b.style().unpolish(b)
            b.style().polish(b)
        self._refresh_graph()

    def _set_graph_view(self, key: str):
        """เปลี่ยนมุมมองกราฟ (by_machine / by_type / by_user)"""
        self._graph_view_mode = key
        for k, b in self._graph_view_btns.items():
            b.setObjectName("btn_primary" if k == key else "btn_outline")
            b.style().unpolish(b)
            b.style().polish(b)
        if hasattr(self, "chk_public_user"):
            self.chk_public_user.setVisible(key == "by_user")
        if hasattr(self, "graph_machine_filter_frame"):
            self.graph_machine_filter_frame.setVisible(key == "by_user")
        self._refresh_graph()

    def _reset_graph_view(self):
        """รีเซ็ตมุมมองกราฟให้กลับมาที่ตำแหน่ง auto-range"""
        if _PQG_OK and hasattr(self, 'plot_widget'):
            self.plot_widget.enableAutoRange()

    def _save_graph_png(self):
        """บันทึกภาพกราฟปัจจุบันเป็น PNG"""
        if not _PQG_OK or not hasattr(self, 'plot_widget'):
            QMessageBox.warning(self, "ข้อผิดพลาด", "ไม่สามารถบันทึกกราฟได้")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "บันทึกกราฟเป็น PNG",
            f"chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
            "PNG Files (*.png);;All Files (*)")
        if not path:
            return
        try:
            # pie chart mode: grab ทั้ง container (เฉพาะ by_type)
            if self._graph_view_mode == "by_type" and hasattr(self, 'pie_container'):
                pixmap = self.pie_container.grab()
                pixmap.save(path, "PNG")
                QMessageBox.information(self, "สำเร็จ", f"บันทึกภาพกราฟเรียบร้อยแล้ว\n{path}")
            else:
                import pyqtgraph.exporters as exporters
                exporter = exporters.ImageExporter(self.plot_widget.getPlotItem())
                exporter.parameters()['width'] = 1600
                exporter.export(path)
                QMessageBox.information(self, "สำเร็จ", f"บันทึกภาพกราฟเรียบร้อยแล้ว\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "ข้อผิดพลาด", f"ไม่สามารถบันทึกไฟล์ได้:\n{e}")

    # ── Prepare graph data ────────────────────────────────────────────
    def _prepare_graph_data(self) -> dict:
        """เตรียมข้อมูลรายเดือนสำหรับวาดกราฟแท่ง (ทุก mode: summary/production/account)"""
        thai_months = {1:"ม.ค.", 2:"ก.พ.", 3:"มี.ค.", 4:"เม.ย.", 5:"พ.ค.", 6:"มิ.ย.",
                       7:"ก.ค.", 8:"ส.ค.", 9:"ก.ย.", 10:"ต.ค.", 11:"พ.ย.", 12:"ธ.ค."}

        # เก็บข้อมูลแต่ละเครื่อง แยกตามเดือน
        # slot_monthly[slot][billing_month] = {a4_color, a4_bw, a3_color, a3_bw, total, total_color, total_bw, users:{name:{color,bw,total}}}
        slot_monthly = [{} for _ in range(3)]
        m_names = [get_cfg(f"machine_name_{i}", SLOT_NAMES[i]) for i in range(3)]

        for slot in range(3):
            all_readings = get_all_readings(slot)
            prev = None
            for data_json, _, billing_month, rec_id in all_readings:
                if isinstance(data_json, str):
                    try:
                        data = json.loads(data_json)
                    except:
                        continue
                else:
                    data = data_json
                if not data or not billing_month:
                    prev = data
                    continue

                sm  = data.get("summary", {})
                pc  = data.get("paper_color", {})
                det = data.get("detail", {})

                # คำนวณ delta
                if prev:
                    psm  = prev.get("summary", {})
                    ppc  = prev.get("paper_color", {})
                    pdet = prev.get("detail", {})
                    a4c  = max(0, pc.get("a4_color",0) - ppc.get("a4_color",0))
                    a4bw = max(0, pc.get("a4_bw",0)    - ppc.get("a4_bw",0))
                    a3c  = max(0, pc.get("a3_color",0)  - ppc.get("a3_color",0))
                    a3bw = max(0, pc.get("a3_bw",0)     - ppc.get("a3_bw",0))
                    total = max(0, sm.get("total",0) - psm.get("total",0))
                    tc   = max(0, sm.get("total_color",0) - psm.get("total_color",0))
                    tb   = max(0, sm.get("total_bw",0)    - psm.get("total_bw",0))
                    copy_c  = max(0, det.get("copy",{}).get("color",0)  - pdet.get("copy",{}).get("color",0))
                    copy_bw = max(0, det.get("copy",{}).get("bw",0)     - pdet.get("copy",{}).get("bw",0))
                    prt_c   = max(0, det.get("print",{}).get("color",0) - pdet.get("print",{}).get("color",0))
                    prt_bw  = max(0, det.get("print",{}).get("bw",0)    - pdet.get("print",{}).get("bw",0))
                    pmt  = prev.get("meters", {})
                    mt_c = max(0, data.get("meters",{}).get("color_meter",0) - pmt.get("color_meter",0))
                    mt_b = max(0, data.get("meters",{}).get("bw_meter",0)    - pmt.get("bw_meter",0))
                else:
                    a4c  = pc.get("a4_color",0)
                    a4bw = pc.get("a4_bw",0)
                    a3c  = pc.get("a3_color",0)
                    a3bw = pc.get("a3_bw",0)
                    total = sm.get("total",0)
                    tc   = sm.get("total_color",0)
                    tb   = sm.get("total_bw",0)
                    copy_c  = det.get("copy",{}).get("color",0)
                    copy_bw = det.get("copy",{}).get("bw",0)
                    prt_c   = det.get("print",{}).get("color",0)
                    prt_bw  = det.get("print",{}).get("bw",0)
                    mt_c = data.get("meters",{}).get("color_meter",0)
                    mt_b = data.get("meters",{}).get("bw_meter",0)

                if billing_month not in slot_monthly[slot]:
                    slot_monthly[slot][billing_month] = {
                        "a4_color": 0, "a4_bw": 0, "a3_color": 0, "a3_bw": 0,
                        "total": 0, "total_color": 0, "total_bw": 0,
                        "copy_color": 0, "copy_bw": 0, "print_color": 0, "print_bw": 0,
                        "meter_color": 0, "meter_bw": 0,
                        "users": {},
                    }
                md = slot_monthly[slot][billing_month]
                md["a4_color"]    += a4c
                md["a4_bw"]       += a4bw
                md["a3_color"]    += a3c
                md["a3_bw"]       += a3bw
                md["total"]       += total
                md["total_color"] += tc
                md["total_bw"]    += tb
                md["copy_color"]  += copy_c
                md["copy_bw"]     += copy_bw
                md["print_color"] += prt_c
                md["print_bw"]    += prt_bw
                md["meter_color"] += mt_c
                md["meter_bw"]    += mt_b

                # ดึง user data (Account mode)
                if data.get("accounts"):
                    for a in data["accounts"]:
                        name = a.get("name", "")
                        if not name:
                            continue
                        c = a.get("color_a4",0) + a.get("color_a3",0)
                        b = a.get("bw_a4",0) + a.get("bw_a3",0)
                        t = a.get("total", c+b)
                        if name not in md["users"]:
                            md["users"][name] = {"color": 0, "bw": 0, "total": 0}
                        md["users"][name]["color"] += c
                        md["users"][name]["bw"]    += b
                        md["users"][name]["total"] += t
                else:
                    # Summary/Production → Public
                    if "Public" not in md["users"]:
                        md["users"]["Public"] = {"color": 0, "bw": 0, "total": 0}
                    md["users"]["Public"]["color"] += tc
                    md["users"]["Public"]["bw"]    += tb
                    md["users"]["Public"]["total"] += total

                prev = data

        # รวม billing months จากทุก slot
        all_months_set = set()
        for slot in range(3):
            all_months_set.update(slot_monthly[slot].keys())
        all_months_full = sorted(all_months_set)

        # อัปเดตรายการเดือนที่ใช้ใน dropdown ทุกครั้ง (รองรับข้อมูลใหม่ทันที)
        self._available_months_for_filter = all_months_full

        # ตรวจสอบและปรับช่วงเดือนที่เลือกให้ยัง valid กับข้อมูลล่าสุด
        if all_months_full:
            # ถ้าเป็น "" → แสดงทั้งหมด (ใช้ first/last)
            if self._graph_date_from == "" or self._graph_date_to == "":
                self._graph_date_from = all_months_full[0]
                self._graph_date_to = all_months_full[-1]
            elif (self._graph_date_from not in all_months_full
                    or self._graph_date_to not in all_months_full):
                self._graph_date_from = all_months_full[0]
                self._graph_date_to = all_months_full[-1]
            else:
                if self._graph_date_from > self._graph_date_to:
                    self._graph_date_from, self._graph_date_to = self._graph_date_to, self._graph_date_from

        # Filter months ตามช่วง _graph_date_from ถึง _graph_date_to
        all_months = [m for m in all_months_full
                      if self._graph_date_from <= m <= self._graph_date_to]
        if not all_months and all_months_full:
            all_months = [all_months_full[-1]]  # Fallback

        # สร้าง x_labels (ชื่อเดือนไทย)
        x_labels = []
        for m in all_months:
            try:
                dt = datetime.strptime(m, "%Y-%m")
                x_labels.append(f"{thai_months.get(dt.month, '')} {dt.year + 543}")
            except Exception:
                x_labels.append(m)

        return {
            "slot_monthly": slot_monthly,
            "m_names": m_names,
            "all_months": all_months,
            "x_labels": x_labels,
            "view_mode": self._graph_view_mode,
        }

    # ── Draw bar chart ────────────────────────────────────────────────
    def _draw_graph(self, data: dict):
        """วาด Clustered Bar Chart บน pyqtgraph"""
        if not _PQG_OK or not hasattr(self, 'plot_widget'):
            return
        try:
            self.plot_widget.clear()

            slot_monthly = data["slot_monthly"]
            m_names      = data["m_names"]
            all_months   = data["all_months"]
            x_labels     = data["x_labels"]
            view_mode    = data["view_mode"]

            n_months = len(all_months)
            if n_months == 0:
                self.plot_widget.setTitle("ยังไม่มีข้อมูล")
                return

            # ── ล้าง legend เก่า ──
            pi = self.plot_widget.getPlotItem()
            if pi.legend is not None:
                try:
                    pi.legend.scene().removeItem(pi.legend)
                except Exception:
                    pass
                pi.legend = None
            legend = self.plot_widget.addLegend(offset=(10, 10))
            self._current_legend = legend
            
            # ซ่อน legend checkbox widget โดยค่าเริ่มต้น (จะแสดงเมื่อจำเป็น)
            if hasattr(self, '_ext_legend_widget'):
                self._ext_legend_widget.setVisible(False)

            # ── สี RGB สำหรับแต่ละ series (อ่านจาก config) ──
            def _h(hx):
                h = hx.lstrip('#')
                return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))
            
            def _get_text_color(rgb):
                """คืน (255,255,255) ถ้าพื้นม่วง เข้ม หรือ (0,0,0) สำหรับพื้นอ่อน"""
                r, g, b = rgb
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                return (255, 255, 255) if luminance < 128 else (0, 0, 0)
            
            colors_machine = [_h(c) for c in GRAPH_COLORS_MACHINE]
            colors_type    = {k: _h(v) for k, v in GRAPH_COLORS_TYPE.items()}
            colors_user_pool = [
                (37,99,235),(220,38,38),(22,163,74),(234,88,12),(124,58,237),
                (6,182,212),(236,72,153),(168,85,247),(251,146,60),(20,184,166),
            ]

            self._hover_bars = []  # [(label, x_center, value, month_label, color_rgb)]

            # ── ตรวจสอบว่าเครื่องไหนมีข้อมูล (ซ่อนเครื่องที่ไม่มี) ──
            active_slots = []
            for si in range(3):
                has_data = any(
                    (
                        slot_monthly[si].get(m, {}).get("total", 0) > 0
                        or slot_monthly[si]
                        .get(m, {})
                        .get("provisional_total", 0)
                        > 0
                    )
                    for m in all_months
                )
                if has_data:
                    active_slots.append(si)
            if not active_slots:
                active_slots = [0]  # fallback แสดงอย่างน้อย 1 เครื่อง

            # ═══════════════════════════════════════════════════════════
            if view_mode == "by_machine":
                # กราฟแท่ง: เฉพาะเครื่องที่มีข้อมูล — Clustered
                # กรองเครื่องตามสถานะ checkbox
                hidden_machines = getattr(self, '_hidden_machines', set())
                visible_slots = [si for si in active_slots if si not in hidden_machines]
                # ห้ามแสดงเครื่องทั้งหมด ถ้าผู้ใช้ปิด filter ทั้งหมด
                
                # ถ้าทั้งหมดถูกซ่อน แสดงข้อความให้ผู้ใช้เห็น แต่ยังให้ checkbox ทำงานได้
                if not visible_slots:
                    self.plot_widget.setTitle("โปรดเลือกเครื่องอย่างน้อย 1 เครื่อง")
                    pi = self.plot_widget.getPlotItem()
                    if pi.titleLabel is not None:
                        pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
                    # ยังคงรีเซ็ต checkbox layout และให้เปิดได้
                    if hasattr(self, '_ext_legend_layout'):
                        while self._ext_legend_layout.count():
                            item = self._ext_legend_layout.takeAt(0)
                            if item.widget():
                                item.widget().deleteLater()
                        for si in active_slots:
                            rgb = colors_machine[si]
                            hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                            cb = QCheckBox(m_names[si])
                            cb.setChecked(False)  # ทั้งหมดเป็น unchecked
                            cb.setFont(fnt(F_SM))
                            cb.setStyleSheet(
                                f"QCheckBox {{ spacing: 3px; color: #999999; }}"
                                f"QCheckBox::indicator {{ width: 13px; height: 13px; }}"
                                f"QCheckBox::indicator:checked {{ background: {hex_c}; border: 1px solid {hex_c}; border-radius: 2px; }}"
                                f"QCheckBox::indicator:unchecked {{ background: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 2px; }}")
                            cb.toggled.connect(lambda checked, s=si: self._toggle_machine_legend(s, checked))
                            self._ext_legend_layout.addWidget(cb)
                        self._ext_legend_widget.setVisible(True)
                    return

                n_series = len(visible_slots)
                bar_w = GRAPH_BAR_WIDTH
                group_w = n_series * bar_w + 0.15

                for idx, si in enumerate(visible_slots):
                    xs, ys = [], []
                    rgb = colors_machine[si]
                    for mi, month in enumerate(all_months):
                        md = slot_monthly[si].get(month, {})
                        val = md.get("total", 0)
                        x = mi * group_w + idx * bar_w
                        xs.append(x)
                        ys.append(val)
                        self._hover_bars.append((m_names[si], x, val, x_labels[mi] if mi < len(x_labels) else "", rgb))
                    bar_item = pg.BarGraphItem(
                        x=xs, height=ys, width=bar_w * 0.9,
                        brush=pg.mkBrush(*rgb, 200),
                        pen=pg.mkPen(*rgb, width=1),
                    )
                    self.plot_widget.addItem(bar_item)
                    
                    # เพิ่มค่าบน bar ถ้า checkbox ถูกเลือก
                    if hasattr(self, 'chk_show_values') and self.chk_show_values.isChecked():
                        for x, y in zip(xs, ys):
                            if y > 0:
                                label_text = f"[{m_names[si]}] : {int(y):,} แผ่น"
                                text = pg.TextItem(label_text, anchor=(0.5, 1.0))
                                text.setFont(fnt(GRAPH_VALUE_SIZE))
                                text.setColor(pg.mkColor(0, 0, 0))
                                text.setPos(x, y)
                                self.plot_widget.addItem(text)

                # แกน X: label ตรงกลางกลุ่ม
                x_ticks = []
                for mi in range(n_months):
                    center = mi * group_w + (n_series - 1) * bar_w / 2
                    x_ticks.append((center, x_labels[mi] if mi < len(x_labels) else ""))

                self.plot_widget.setTitle("ประวัติการใช้งาน — แยกตามเครื่อง")
                pi = self.plot_widget.getPlotItem()
                if pi.titleLabel is not None:
                    pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
                self.plot_widget.getAxis('left').setLabel('จำนวน (แผ่น)', size=GRAPH_AXIS_LABEL_SIZE)

                # ซ่อน legend ในกราฟ + แสดง legend checkbox ภายนอกใต้แกน X
                if hasattr(self, '_current_legend') and self._current_legend is not None:
                    try:
                        self._current_legend.scene().removeItem(self._current_legend)
                    except Exception:
                        pass
                    pi.legend = None

                # สร้าง checkbox legend ด้านล่าง
                if hasattr(self, '_ext_legend_layout'):
                    # ล้าง checkbox เก่า
                    while self._ext_legend_layout.count():
                        item = self._ext_legend_layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    for si in active_slots:
                        rgb = colors_machine[si]
                        hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                        cb = QCheckBox(m_names[si])
                        cb.setChecked(si not in hidden_machines)
                        cb.setFont(fnt(F_SM))
                        cb.setStyleSheet(
                            f"QCheckBox {{ spacing: 3px; }}"
                            f"QCheckBox::indicator {{ width: 13px; height: 13px; }}"
                            f"QCheckBox::indicator:checked {{ background: {hex_c}; border: 1px solid {hex_c}; border-radius: 2px; }}"
                            f"QCheckBox::indicator:unchecked {{ background: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 2px; }}")
                        cb.toggled.connect(lambda checked, s=si: self._toggle_machine_legend(s, checked))
                        self._ext_legend_layout.addWidget(cb)
                    self._ext_legend_widget.setVisible(True)

            # ═══════════════════════════════════════════════════════════
            elif view_mode == "by_type":
                # Stacked bar: แต่ละเดือน แต่ละเครื่อง มีชุด 4 ประเภท (copy_color, copy_bw, print_color, print_bw)
                # = Clustered (3 เครื่อง) x Stacked (4 ประเภท)
                configured_type_keys = [
                    "copy_color",
                    "copy_bw",
                    "print_color",
                    "print_bw",
                    "meter_color",
                    "meter_bw",
                ]
                type_keys = [
                    type_key
                    for type_key in configured_type_keys
                    if any(
                        slot_monthly[slot].get(month, {}).get(type_key, 0) > 0
                        for slot in active_slots
                        for month in all_months
                    )
                ] or configured_type_keys[:4]
                type_labels = {"copy_color":"Copy สี", "copy_bw":"Copy ขาวดำ", "print_color":"Print สี", "print_bw":"Print ขาวดำ", "meter_color":"Meter สี", "meter_bw":"Meter ขาวดำ"}
                
                # กรองประเภทตามสถานะ checkbox
                hidden_types = getattr(self, '_hidden_types', set())
                visible_type_keys = [tk for tk in type_keys if tk not in hidden_types]
                
                # ถ้าทั้งหมดถูกซ่อน แสดงข้อความให้ผู้ใช้เห็น แต่ยังให้ checkbox ทำงานได้
                if not visible_type_keys:
                    self.plot_widget.setTitle("โปรดเลือกประเภทงานอย่างน้อย 1 ประเภท")
                    pi = self.plot_widget.getPlotItem()
                    if pi.titleLabel is not None:
                        pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
                    # ยังคงรีเซ็ต checkbox layout และให้เปิดได้
                    if hasattr(self, '_ext_legend_layout'):
                        while self._ext_legend_layout.count():
                            item = self._ext_legend_layout.takeAt(0)
                            if item.widget():
                                item.widget().deleteLater()
                        for tk in type_keys:
                            hex_c = GRAPH_COLORS_TYPE.get(tk, "#000000")
                            cb = QCheckBox(type_labels[tk])
                            cb.setChecked(False)  # ทั้งหมดเป็น unchecked
                            cb.setFont(fnt(F_SM))
                            cb.setStyleSheet(
                                f"QCheckBox {{ spacing: 3px; color: #999999; }}"
                                f"QCheckBox::indicator {{ width: 13px; height: 13px; }}"
                                f"QCheckBox::indicator:checked {{ background: {hex_c}; border: 1px solid {hex_c}; border-radius: 2px; }}"
                                f"QCheckBox::indicator:unchecked {{ background: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 2px; }}")
                            cb.toggled.connect(lambda checked, t=tk: self._toggle_type_legend(t, checked))
                            self._ext_legend_layout.addWidget(cb)
                        self._ext_legend_widget.setVisible(True)
                    return
                
                n_machines = len(active_slots)
                bar_w = GRAPH_BAR_WIDTH
                group_w = n_machines * bar_w + 0.15

                # สร้าง stacked bars
                added_legend = set()
                # [V4.5] เก็บ bottoms ต่อ slot เพื่อให้ label "ค่ารวมบนสุด" วางตำแหน่งถูก
                bottoms_per_slot = {}
                for idx, si in enumerate(active_slots):
                    bottoms = [0.0] * n_months
                    bottoms_per_slot[si] = bottoms
                    segment_heights = {mi: {} for mi in range(n_months)}  # เก็บความสูงแต่ละส่วน
                    for tk in visible_type_keys:
                        xs, ys = [], []
                        for mi, month in enumerate(all_months):
                            md = slot_monthly[si].get(month, {})
                            val = md.get(tk, 0)
                            x = mi * group_w + idx * bar_w
                            xs.append(x)
                            ys.append(val)
                            segment_heights[mi][tk] = val  # เก็บค่าแต่ละประเภท
                            self._hover_bars.append((f"{m_names[si]} - {type_labels[tk]}", x, val, x_labels[mi] if mi < len(x_labels) else "", colors_type[tk]))
                        bar_item = pg.BarGraphItem(
                            x=xs, height=ys, width=bar_w * 0.9,
                            y0=bottoms[:n_months],
                            brush=pg.mkBrush(*colors_type[tk], 180),
                            pen=pg.mkPen(*colors_type[tk], width=1),
                        )
                        self.plot_widget.addItem(bar_item)
                        # อัปเดต bottoms
                        for mi in range(n_months):
                            md = slot_monthly[si].get(all_months[mi], {})
                            bottoms[mi] += md.get(tk, 0)

                    # เพิ่มค่าแต่ละประเภท ลงในแต่ละส่วนของ stacked bar
                    if hasattr(self, 'chk_show_values') and self.chk_show_values.isChecked():
                        for mi in range(n_months):
                            y_bottom = 0.0
                            x = mi * group_w + idx * bar_w
                            for tk in visible_type_keys:
                                val = segment_heights[mi].get(tk, 0)
                                if val > 0:
                                    # ตรงกลางส่วน (segment) ของแต่ละ type
                                    y_pos = y_bottom + val / 2
                                    label_text = f"{tk}, {int(val)} แผ่น"
                                    text = pg.TextItem(label_text, anchor=(0.5, 0.5))
                                    text.setFont(fnt(F_SM))
                                    text_color = _get_text_color(colors_type[tk])
                                    text.setColor(pg.mkColor(*text_color))
                                    text.setPos(x, y_pos)
                                    self.plot_widget.addItem(text)
                                    y_bottom += val

                # แกน X
                x_ticks = []
                for mi in range(n_months):
                    center = mi * group_w + (n_machines - 1) * bar_w / 2
                    x_ticks.append((center, x_labels[mi] if mi < len(x_labels) else ""))

                # เพิ่มค่ารวมบนสุด stacked bars ถ้า checkbox ถูกเลือก
                # [V4.5] fix: ใช้ bottoms_per_slot[si] แทน bottoms ที่ถูก reassign ใน outer loop
                if hasattr(self, 'chk_show_values') and self.chk_show_values.isChecked():
                    for idx, si in enumerate(active_slots):
                        slot_bottoms = bottoms_per_slot.get(si, [0.0] * n_months)
                        for mi in range(n_months):
                            md = slot_monthly[si].get(all_months[mi], {})
                            total = md.get("total", 0)
                            if total > 0:
                                x = mi * group_w + idx * bar_w
                                y = slot_bottoms[mi] if mi < len(slot_bottoms) else 0
                                label_text = f"[{m_names[si]}] : {int(total):,} แผ่น"
                                text = pg.TextItem(label_text, anchor=(0.5, 1.0))
                                text.setFont(fnt(GRAPH_VALUE_SIZE))
                                text.setColor(pg.mkColor(0, 0, 0))
                                text.setPos(x, y)
                                self.plot_widget.addItem(text)

                self.plot_widget.setTitle("ประวัติการใช้งาน — แยกตามประเภทงาน")
                pi = self.plot_widget.getPlotItem()
                if pi.titleLabel is not None:
                    pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
                self.plot_widget.getAxis('left').setLabel('จำนวน (แผ่น)', size=GRAPH_AXIS_LABEL_SIZE)

                # ซ่อน legend ในกราฟ + แสดง legend checkbox ภายนอกใต้แกน X
                if hasattr(self, '_current_legend') and self._current_legend is not None:
                    try:
                        self._current_legend.scene().removeItem(self._current_legend)
                    except Exception:
                        pass
                    pi.legend = None

                # สร้าง checkbox legend ด้านล่าง
                if hasattr(self, '_ext_legend_layout'):
                    # ล้าง checkbox เก่า
                    while self._ext_legend_layout.count():
                        item = self._ext_legend_layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    for tk in type_keys:
                        rgb = colors_type[tk]
                        hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                        cb = QCheckBox(type_labels[tk])
                        cb.setChecked(tk not in hidden_types)
                        cb.setFont(fnt(F_SM))
                        cb.setStyleSheet(
                            f"QCheckBox {{ spacing: 3px; }}"
                            f"QCheckBox::indicator {{ width: 13px; height: 13px; }}"
                            f"QCheckBox::indicator:checked {{ background: {hex_c}; border: 1px solid {hex_c}; border-radius: 2px; }}"
                            f"QCheckBox::indicator:unchecked {{ background: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 2px; }}")
                        cb.toggled.connect(lambda checked, t=tk: self._toggle_type_legend(t, checked))
                        self._ext_legend_layout.addWidget(cb)
                    self._ext_legend_widget.setVisible(True)

            # ═══════════════════════════════════════════════════════════
            elif view_mode == "by_user":
                # X = ผู้ใช้งาน, Y = ปริมาณรวมทุกเดือน, stack = เครื่อง (M1 blue, M2 red, M3 green)
                user_machine_filter = getattr(self, '_graph_user_machine_filter', {0, 1, 2})
                include_public = (not hasattr(self, 'chk_public_user')
                                  or self.chk_public_user.isChecked())
                slot_rgb = [_h(c) for c in SLOT_COLORS]
                public_patterns = {"public", "public user", "public (label)", "สาธารณะ", "guest", ""}

                # Aggregate per user per machine across all selected months
                user_machine_totals = {}  # {uname: {si: total}}
                for si in range(3):
                    if si not in user_machine_filter:
                        continue
                    for month in all_months:
                        md = slot_monthly[si].get(month, {})
                        for uname, ud in md.get("users", {}).items():
                            if not include_public and uname.strip().lower() in public_patterns:
                                continue
                            if uname not in user_machine_totals:
                                user_machine_totals[uname] = {}
                            user_machine_totals[uname][si] = (
                                user_machine_totals[uname].get(si, 0) + ud.get("total", 0)
                            )

                user_grand = {u: sum(v.values()) for u, v in user_machine_totals.items()}
                user_grand = {u: v for u, v in user_grand.items() if v > 0}

                if not user_grand:
                    self.plot_widget.setTitle("ยังไม่มีข้อมูลผู้ใช้งาน")
                    pi = self.plot_widget.getPlotItem()
                    if pi.titleLabel is not None:
                        pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
                    x_ticks = []
                else:
                    all_user_names = sorted(user_grand.keys(), key=lambda u: -user_grand[u])
                    n_users = len(all_user_names)
                    bar_w = min(0.8, 8.0 / max(n_users, 1))

                    for ui, uname in enumerate(all_user_names):
                        y_bottom = 0.0
                        for si in sorted(user_machine_filter):
                            val = user_machine_totals[uname].get(si, 0)
                            if val <= 0:
                                continue
                            rgb = slot_rgb[si]
                            bar_item = pg.BarGraphItem(
                                x=[ui], height=[val], width=bar_w * 0.9,
                                y0=[y_bottom],
                                brush=pg.mkBrush(*rgb, 200),
                                pen=pg.mkPen(*rgb, width=1),
                            )
                            self.plot_widget.addItem(bar_item)
                            self._hover_bars.append((
                                f"{m_names[si]} — {uname}", ui, val, uname, rgb))
                            if (hasattr(self, 'chk_show_values')
                                    and self.chk_show_values.isChecked() and val > 0):
                                seg_text = pg.TextItem(
                                    f"{m_names[si]}: {fn(int(val))}", anchor=(0.5, 0.5))
                                seg_text.setFont(fnt(F_SM))
                                seg_text.setColor(pg.mkColor(*_get_text_color(rgb)))
                                seg_text.setPos(ui, y_bottom + val / 2)
                                self.plot_widget.addItem(seg_text)
                            y_bottom += val
                        # Grand total label on top
                        if (hasattr(self, 'chk_show_values')
                                and self.chk_show_values.isChecked()):
                            total = user_grand.get(uname, 0)
                            if total > 0:
                                top_text = pg.TextItem(fn(int(total)), anchor=(0.5, 1.0))
                                top_text.setFont(fnt(GRAPH_VALUE_SIZE, bold=True))
                                top_text.setColor(pg.mkColor(0, 0, 0))
                                top_text.setPos(ui, y_bottom)
                                self.plot_widget.addItem(top_text)

                    x_ticks = [(ui, uname) for ui, uname in enumerate(all_user_names)]

                self.plot_widget.setTitle("ประวัติการใช้งาน — แยกตามผู้ใช้งาน")
                pi = self.plot_widget.getPlotItem()
                if pi.titleLabel is not None:
                    pi.titleLabel.setFont(fnt(GRAPH_TITLE_SIZE, bold=True))
                self.plot_widget.getAxis('left').setLabel(
                    'จำนวน (แผ่น)', size=GRAPH_AXIS_LABEL_SIZE)
                self.plot_widget.getAxis('bottom').setLabel(
                    'ผู้ใช้งาน', units='', size=GRAPH_AXIS_LABEL_SIZE)

                # ซ่อน legend ปกติ + ซ่อน user checkbox legend
                if hasattr(self, '_current_legend') and self._current_legend is not None:
                    try:
                        self._current_legend.scene().removeItem(self._current_legend)
                    except Exception:
                        pass
                    pi.legend = None
                if hasattr(self, '_ext_legend_widget'):
                    self._ext_legend_widget.setVisible(False)

            # ── แสดง external legend สำหรับโหมด by_machine, by_type, by_user ──
            if view_mode not in ["by_machine", "by_type", "by_user"] and hasattr(self, '_ext_legend_widget'):
                self._ext_legend_widget.setVisible(False)

            # ── ตั้งค่าแกน X ──
            axis = self.plot_widget.getAxis('bottom')
            axis.setTicks([x_ticks])

            # ── Crosshair + Tooltip ──
            self._vline = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen('#94a3b8', width=1, style=Qt.PenStyle.DashLine))
            _ttbg_h = GRAPH_TOOLTIP_BG.lstrip('#')
            _ttfg_h = GRAPH_TOOLTIP_COLOR.lstrip('#')
            _ttbg = pg.mkBrush(int(_ttbg_h[0:2],16), int(_ttbg_h[2:4],16), int(_ttbg_h[4:6],16), 220)
            _ttfg = (int(_ttfg_h[0:2],16), int(_ttfg_h[2:4],16), int(_ttfg_h[4:6],16))
            self._tooltip = pg.TextItem(
                text='', anchor=(0.0, 0.0),
                border=pg.mkPen('#94a3b8'),
                fill=_ttbg,
                color=_ttfg)
            self._tooltip.setFont(fnt(GRAPH_TOOLTIP_SIZE))
            self._tooltip.setZValue(100)
            self.plot_widget.addItem(self._vline, ignoreBounds=True)
            self.plot_widget.addItem(self._tooltip, ignoreBounds=True)
            self._vline.setVisible(False)
            self._tooltip.setVisible(False)

            # เก็บ x_ticks สำหรับ hover
            self._hover_x_ticks = x_ticks

            # ── ซูมออกให้มองเห็นรอบๆ กราฟ ──
            vb = self.plot_widget.getViewBox()
            vb.setDefaultPadding(0.08)
            self.plot_widget.enableAutoRange()

        except Exception as e:
            traceback.print_exc()

    def _on_mouse_moved(self, evt):
        """แสดง crosshair + tooltip เมื่อเม้าชี้บนกราฟแท่ง — แสดงทุก series ที่ x ใกล้เคียง"""
        if not _PQG_OK or not hasattr(self, 'plot_widget'):
            return
        if not hasattr(self, '_vline') or not hasattr(self, '_tooltip'):
            return
        try:
            pos = evt[0]
            if not self.plot_widget.sceneBoundingRect().contains(pos):
                self._vline.setVisible(False)
                self._tooltip.setVisible(False)
                return

            mouse_pt = self.plot_widget.getViewBox().mapSceneToView(pos)
            mx = mouse_pt.x()

            hover_bars = getattr(self, '_hover_bars', [])
            if not hover_bars:
                self._vline.setVisible(False)
                self._tooltip.setVisible(False)
                return

            # หา bar ที่ x ใกล้เม้าที่สุด
            best_dist = 999
            best_x = None
            for entry in hover_bars:
                bx = entry[1]
                dist = abs(bx - mx)
                if dist < best_dist:
                    best_dist = dist
                    best_x = bx

            if best_dist > 0.3 or best_x is None:
                self._vline.setVisible(False)
                self._tooltip.setVisible(False)
                return

            # รวบรวมทุก bar ที่ x ใกล้เคียงกับ best_x (ภายใน tolerance)
            tol = 0.05
            matched = []
            for entry in hover_bars:
                bx = entry[1]
                if abs(bx - best_x) < tol:
                    matched.append(entry)

            if not matched:
                self._vline.setVisible(False)
                self._tooltip.setVisible(False)
                return

            month_label = matched[0][3]
            lines = [month_label]
            for entry in matched:
                label, bx, val, ml = entry[0], entry[1], entry[2], entry[3]
                rgb = entry[4] if len(entry) > 4 else (100, 100, 100)
                fmt_val = f"{val:,.0f}" if isinstance(val, (int, float)) else str(val)
                # ใช้ colored square (Unicode) เพื่อแสดงสี
                hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                lines.append(f'<span style="color:{hex_c};">■</span> {label}: {fmt_val}')

            vb = self.plot_widget.getViewBox()
            vr = vb.viewRange()
            x_min, x_max = vr[0]
            y_min, y_max = vr[1]
            my = mouse_pt.y()

            # anchor แบบ dynamic: พลิกทิศเมื่อเม้าอยู่ใกล้ขอบ
            ax = 0.0 if mx < (x_min + x_max) / 2 else 1.0
            ay = 1.0 if my > (y_min + y_max) / 2 else 0.0
            self._tooltip.setAnchor((ax, ay))

            self._vline.setPos(best_x)
            self._tooltip.setHtml("<br>".join(lines))
            self._tooltip.setPos(mx, my)
            self._vline.setVisible(True)
            self._tooltip.setVisible(True)
        except Exception:
            pass

    def _toggle_machine_legend(self, si: int, checked: bool):
        """เปิด/ปิด เครื่อง ใน legend checkbox แล้ว redraw กราฟ"""
        if not hasattr(self, '_hidden_machines'):
            self._hidden_machines = set()
        if checked:
            self._hidden_machines.discard(si)
        else:
            self._hidden_machines.add(si)
        self._refresh_graph()

    def _toggle_type_legend(self, tk: str, checked: bool):
        """เปิด/ปิด ประเภทงาน ใน legend checkbox แล้ว redraw กราฟ"""
        if not hasattr(self, '_hidden_types'):
            self._hidden_types = set()
        if checked:
            self._hidden_types.discard(tk)
        else:
            self._hidden_types.add(tk)
        self._refresh_graph()

    def _toggle_user_legend(self, uname: str, checked: bool):
        """เปิด/ปิด user ใน legend checkbox แล้ว redraw กราฟ"""
        if not hasattr(self, '_hidden_users'):
            self._hidden_users = set()
        if checked:
            self._hidden_users.discard(uname)
        else:
            self._hidden_users.add(uname)
        self._refresh_graph()

    def _on_date_from_changed(self, text: str):
        """เมื่อเปลี่ยน 'From' date"""
        if not text or not self._available_months_for_filter:
            return
        # ดึง month string จาก combobox data
        idx = self.cmb_date_from.currentIndex()
        month_str = self.cmb_date_from.itemData(idx)
        if month_str is None or month_str not in self._available_months_for_filter:
            return
        # อัปเดต _graph_date_from
        self._graph_date_from = month_str
        # ถ้า from > to ให้อัปเดต to ด้วย
        if self._graph_date_from > self._graph_date_to:
            self._graph_date_to = self._graph_date_from
            # อัปเดต combobox to โดยไม่ activate signal ใหม่
            idx_to = self.cmb_date_to.findData(self._graph_date_to)
            if idx_to >= 0:
                self.cmb_date_to.blockSignals(True)
                self.cmb_date_to.setCurrentIndex(idx_to)
                self.cmb_date_to.blockSignals(False)
        # Refresh กราฟ
        self._refresh_graph()

    def _on_date_to_changed(self, text: str):
        """เมื่อเปลี่ยน 'To' date"""
        if not text or not self._available_months_for_filter:
            return
        # ดึง month string จาก combobox data
        idx = self.cmb_date_to.currentIndex()
        month_str = self.cmb_date_to.itemData(idx)
        if month_str is None or month_str not in self._available_months_for_filter:
            return
        # อัปเดต _graph_date_to
        self._graph_date_to = month_str
        # ถ้า to < from ให้อัปเดต from ด้วย
        if self._graph_date_to < self._graph_date_from:
            self._graph_date_from = self._graph_date_to
            # อัปเดต combobox from โดยไม่ activate signal ใหม่
            idx_from = self.cmb_date_from.findData(self._graph_date_from)
            if idx_from >= 0:
                self.cmb_date_from.blockSignals(True)
                self.cmb_date_from.setCurrentIndex(idx_from)
                self.cmb_date_from.blockSignals(False)
        # Refresh กราฟ
        self._refresh_graph()

    def _on_date_reset_all(self):
        """ตั้ง range เป็น ปีปัจจุบัน (ม.ค. ปีนี้ → เดือนปัจจุบัน)"""
        if not self._available_months_for_filter:
            return
        today_dt = datetime.now()
        first_of_year = f"{today_dt.year}-01"
        current_month = today_dt.strftime("%Y-%m")
        date_from = first_of_year if first_of_year >= self._available_months_for_filter[0] else self._available_months_for_filter[0]
        date_to = current_month if current_month <= self._available_months_for_filter[-1] else self._available_months_for_filter[-1]
        self._graph_date_from = date_from
        self._graph_date_to = date_to
        # อัปเดต combobox
        idx_from = self.cmb_date_from.findData(self._graph_date_from)
        idx_to = self.cmb_date_to.findData(self._graph_date_to)
        self.cmb_date_from.blockSignals(True)
        self.cmb_date_to.blockSignals(True)
        if idx_from >= 0:
            self.cmb_date_from.setCurrentIndex(idx_from)
        if idx_to >= 0:
            self.cmb_date_to.setCurrentIndex(idx_to)
        self.cmb_date_from.blockSignals(False)
        self.cmb_date_to.blockSignals(False)
        # Refresh กราฟ
        self._refresh_graph()

    def _on_date_show_all(self):
        """แสดงข้อมูลทั้งหมดตั้งแต่แรกจนถึงปัจจุบัน"""
        if not self._available_months_for_filter:
            return
        self._graph_date_from = self._available_months_for_filter[0]
        self._graph_date_to = self._available_months_for_filter[-1]
        # อัปเดต combobox
        idx_from = self.cmb_date_from.findData(self._graph_date_from)
        idx_to = self.cmb_date_to.findData(self._graph_date_to)
        self.cmb_date_from.blockSignals(True)
        self.cmb_date_to.blockSignals(True)
        if idx_from >= 0:
            self.cmb_date_from.setCurrentIndex(idx_from)
        if idx_to >= 0:
            self.cmb_date_to.setCurrentIndex(idx_to)
        self.cmb_date_from.blockSignals(False)
        self.cmb_date_to.blockSignals(False)
        # Refresh กราฟ
        self._refresh_graph()

    def _populate_date_filter_dropdowns(self):
        """เติมข้อมูลลงใน combobox from/to เมื่อครั้งแรก"""
        if not self._available_months_for_filter:
            return
        # เปลี่ยนชื่อเดือนให้เป็นภาษาไทย
        thai_months = {1:"ม.ค.", 2:"ก.พ.", 3:"มี.ค.", 4:"เม.ย.", 5:"พ.ค.", 6:"มิ.ย.",
                       7:"ก.ค.", 8:"ส.ค.", 9:"ก.ย.", 10:"ต.ค.", 11:"พ.ย.", 12:"ธ.ค."}
        thai_items = []
        for m in self._available_months_for_filter:
            try:
                dt = datetime.strptime(m, "%Y-%m")
                label = f"{thai_months.get(dt.month, '')} {dt.year + 543}  ({m})"
            except Exception:
                label = m
            thai_items.append((m, label))
        
        # เติม cmb_date_from และ cmb_date_to
        self.cmb_date_from.blockSignals(True)
        self.cmb_date_to.blockSignals(True)
        self.cmb_date_from.clear()
        self.cmb_date_to.clear()
        for m, label in thai_items:
            self.cmb_date_from.addItem(label, m)
            self.cmb_date_to.addItem(label, m)
        # ตั้งค่าเริ่มต้น
        idx_from = next((i for i, (m, _) in enumerate(thai_items) if m == self._graph_date_from), 0)
        idx_to = next((i for i, (m, _) in enumerate(thai_items) if m == self._graph_date_to), len(thai_items) - 1)
        self.cmb_date_from.setCurrentIndex(idx_from)
        self.cmb_date_to.setCurrentIndex(idx_to)
        self.cmb_date_from.blockSignals(False)
        self.cmb_date_to.blockSignals(False)

    def _refresh_graph(self):
        """อัปเดตกราฟ"""
        if not _PQG_OK or not hasattr(self, 'plot_widget'):
            return
        
        try:
            data = self._prepare_graph_data()
            # Populate date filter dropdowns ทุกครั้งเพื่อให้เดือนใหม่ขึ้นทันทีหลัง import
            if self._available_months_for_filter:
                self._populate_date_filter_dropdowns()
            self._graph_data_cache = data
            if data.get("view_mode") == "by_type":
                # ซ่อน bar chart, แสดง pie container (เฉพาะ by_type)
                self.plot_widget.setVisible(False)
                if hasattr(self, 'pie_container'):
                    self.pie_container.setVisible(True)
                self._draw_pie_graph(data)
            else:
                # แสดง bar chart, ซ่อน pie container (by_machine, by_user)
                self.plot_widget.setVisible(True)
                if hasattr(self, 'pie_container'):
                    self.pie_container.setVisible(False)
                self._draw_graph(data)
        except Exception as e:
            traceback.print_exc()

    def _draw_pie_graph(self, data: dict):
        """วาด Pie Chart: 1 อันใหญ่รวมทุกเครื่อง + 3 อันเล็กแยกรายเครื่อง"""
        if not hasattr(self, 'pie_view_all') or not hasattr(self, 'pie_views_slot'):
            return

        view_mode    = data["view_mode"]
        slot_monthly = data["slot_monthly"]
        all_months   = data["all_months"]
        m_names      = data["m_names"]

        if hasattr(self, '_ext_legend_widget'):
            self._ext_legend_widget.setVisible(False)

        active_slots = [
            si for si in range(3)
            if any(slot_monthly[si].get(m, {}).get("total", 0) > 0 for m in all_months)
        ] or [0]

        colors_user_pool = [
            "#2563EB", "#DC2626", "#16A34A", "#EA580C", "#7C3AED",
            "#06B6D4", "#EC4899", "#A855F7", "#FB923C", "#14B8A6",
        ]

        show_values = (hasattr(self, 'chk_show_values')
                       and self.chk_show_values.isChecked())

        def _apply_slice_label(sl, is_large, pct):
            """เปิด/ปิด label outside slice ตาม show_values และขนาด slice"""
            from PyQt6.QtCharts import QPieSlice
            if is_large:
                # Pie ใหญ่: ซ่อน label เมื่อ slice < 5% (ดูใน legend แทน)
                if show_values and pct >= 5.0:
                    sl.setLabelVisible(True)
                    sl.setLabelPosition(QPieSlice.LabelPosition.LabelOutside)
                    sl.setLabelFont(fnt(F_SM))
                    sl.setLabelColor(QColor("#1E293B"))
                    arm = 0.15 + max(0.0, (10.0 - pct) * 0.01)
                    sl.setLabelArmLengthFactor(arm)
                else:
                    sl.setLabelVisible(False)
            else:
                # Pie เล็ก: ไม่มี legend → แสดง label เฉพาะ slices ที่ >= 5%
                # slices เล็ก (<5%) ซ่อน label เพื่อหลีกเลี่ยงการซ้อนทับ
                if pct >= 5.0:
                    sl.setLabelVisible(True)
                    sl.setLabelPosition(QPieSlice.LabelPosition.LabelOutside)
                    sl.setLabelFont(fnt(6))
                    sl.setLabelColor(QColor("#1E293B"))
                    # Longer arm for smaller slices to reduce overlap
                    arm = 0.15 + max(0.0, (8.0 - pct) * 0.01)
                    sl.setLabelArmLengthFactor(arm)
                else:
                    sl.setLabelVisible(False)

        def _make_chart(series, title, is_large=False):
            series.setPieSize(0.65 if is_large else 0.70)
            chart = QChart()
            chart.addSeries(series)
            chart.setTitle(title)
            chart.setTitleFont(fnt(F_LG if is_large else F_MD, bold=True))
            chart.setBackgroundBrush(QColor(C_CARD))
            chart.setDropShadowEnabled(False)
            if is_large:
                chart.legend().setVisible(True)
                chart.legend().setAlignment(Qt.AlignmentFlag.AlignRight)
                chart.legend().setFont(fnt(F_MD))
            else:
                # Pie เล็ก: ซ่อน legend (พื้นที่น้อย ข้อความถูกตัดเป็น ...)
                # ดูรายละเอียดได้จาก Pie ใหญ่ด้านบน + label บน slice
                chart.legend().setVisible(False)
            # Keep data refreshes immediate; motion is reserved for controls
            # and uses the same timing throughout the application.
            chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
            return chart

        def _fill_type(series, slot_list, is_large=False):
            type_keys   = ["a4_color", "a4_bw", "a3_color", "a3_bw", "meter_color", "meter_bw"]
            type_labels = {"a4_color": "A4 สี", "a4_bw": "A4 ขาวดำ",
                           "a3_color": "A3 สี", "a3_bw": "A3 ขาวดำ",
                           "meter_color": "Meter สี", "meter_bw": "Meter ขาวดำ"}
            type_colors = {"a4_color": "#2563EB", "a4_bw": "#787670",
                           "a3_color": "#EA580C", "a3_bw": "#7C3AED",
                           "meter_color": "#DB2777", "meter_bw": "#475569"}
            totals = {tk: 0 for tk in type_keys}
            for si in slot_list:
                for month in all_months:
                    md = slot_monthly[si].get(month, {})
                    for tk in type_keys:
                        totals[tk] += md.get(tk, 0)
            grand = sum(totals.values())
            if grand == 0:
                sl = series.append("ยังไม่มีข้อมูล", 1)
                sl.setBrush(QColor("#E2E8F0"))
            else:
                for tk in type_keys:
                    v = totals[tk]
                    if v > 0:
                        pct = v / grand * 100
                        if is_large:
                            if show_values:
                                lbl = f"{type_labels[tk]}  {int(v):,}  ({pct:.1f}%)"
                            else:
                                lbl = f"{type_labels[tk]}  {pct:.1f}%"
                        else:
                            # Small pie: no legend — keep label short to avoid overlap
                            lbl = f"{type_labels[tk]}  {pct:.1f}%"
                        sl = series.append(lbl, v)
                        sl.setBrush(QColor(type_colors.get(tk, "#888888")))
                        sl.setBorderColor(QColor("white"))
                        sl.setBorderWidth(2)
                        _apply_slice_label(sl, is_large, pct)

        def _fill_user(series, slot_list, color_map, is_large=False):
            user_totals: dict = {}
            for si in slot_list:
                for month in all_months:
                    md = slot_monthly[si].get(month, {})
                    for uname, ud in md.get("users", {}).items():
                        user_totals[uname] = user_totals.get(uname, 0) + ud.get("total", 0)
            grand = sum(user_totals.values())
            if grand == 0:
                sl = series.append("ยังไม่มีข้อมูล", 1)
                sl.setBrush(QColor("#E2E8F0"))
            else:
                for ui, (uname, v) in enumerate(
                        sorted(user_totals.items(), key=lambda x: -x[1])):
                    if v > 0:
                        pct = v / grand * 100
                        if is_large:
                            if show_values:
                                lbl = f"{uname}  {int(v):,}  ({pct:.1f}%)"
                            else:
                                lbl = f"{uname}  {pct:.1f}%"
                        else:
                            # Small pie: no legend — keep label short to avoid overlap
                            lbl = f"{uname}  {pct:.1f}%"
                        sl = series.append(lbl, v)
                        sl.setBrush(QColor(color_map.get(uname,
                            colors_user_pool[ui % len(colors_user_pool)])))
                        sl.setBorderColor(QColor("white"))
                        sl.setBorderWidth(2)
                        _apply_slice_label(sl, is_large, pct)

        if view_mode == "by_type":
            # ── Pie ใหญ่ รวมทุกเครื่อง ──
            s_all = QPieSeries()
            _fill_type(s_all, active_slots, is_large=True)
            self.pie_view_all.setChart(
                _make_chart(s_all, "📊  ประเภทงาน — รวมทุกเครื่อง", is_large=True))

            # ── Pie เล็ก แยก 3 เครื่อง ──
            for i, view in enumerate(self.pie_views_slot):
                s = QPieSeries()
                _fill_type(s, [i], is_large=False)
                view.setChart(_make_chart(s, f"🖨  {m_names[i]}"))

        else:  # by_user
            # สร้าง color map ร่วม (สีเดียวกันทุก chart)
            all_users = sorted({
                uname
                for si in active_slots
                for month in all_months
                for uname in slot_monthly[si].get(month, {}).get("users", {})
            })
            color_map = {u: colors_user_pool[i % len(colors_user_pool)]
                         for i, u in enumerate(all_users)}

            # ── Pie ใหญ่ รวมทุกเครื่อง ──
            s_all = QPieSeries()
            _fill_user(s_all, active_slots, color_map, is_large=True)
            self.pie_view_all.setChart(
                _make_chart(s_all, "👤  ผู้ใช้งาน — รวมทุกเครื่อง", is_large=True))

            # ── Pie เล็ก แยก 3 เครื่อง ──
            for i, view in enumerate(self.pie_views_slot):
                s = QPieSeries()
                _fill_user(s, [i], color_map, is_large=False)
                view.setChart(_make_chart(s, f"🖨  {m_names[i]}"))


    def _populate_users_overview(self, rows):
        """เติมข้อมูลลงตาราง Users — มุมมองภาพรวม (17 คอลัมน์)"""
        self.tbl_users.setRowCount(0)
        n_cols = 17
        for _, rv in rows:
            r = self.tbl_users.rowCount(); self.tbl_users.insertRow(r)
            is_total = (rv[0] == "รวมทั้งหมด")
            item0 = tbl_item(rv[0], Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            if is_total:
                item0.setFont(fnt(F_MD, True))
                item0.setBackground(QColor("#F1F5F9"))
            self.tbl_users.setItem(r, 0, item0)
            for c in range(1, n_cols):
                v = rv[c]
                color = None
                bold = False
                if c in (1, 2, 3, 6, 7): color = "#000000"; bold = True   # Total Counter/Color/BW/Print/Copy
                elif c == 4:              color = "#7C3AED"; bold = True   # Meter สี → ม่วง
                elif c == 5:              color = "#6B7280"; bold = True   # Meter ขาวดำ → เทา
                elif 8 <= c <= 15:        color = "#6B7280"               # Print/Copy A4/A3 → เทา
                elif c == 16:             color = "#6B7280"; bold = True  # ค่าใช้จ่าย → เทา
                item = tbl_item(v, color=color, bold=(bold or is_total))
                if is_total:
                    item.setBackground(QColor("#F1F5F9"))
                self.tbl_users.setItem(r, c, item)

    def _populate_users_machine(self, rows):
        """เติมข้อมูลลงตาราง Users — มุมมองแบ่งตามเครื่อง (14 คอลัมน์)"""
        self.tbl_users.setRowCount(0)
        for _, rv in rows:
            r = self.tbl_users.rowCount(); self.tbl_users.insertRow(r)
            is_total = (rv[0] == "รวมทั้งหมด")
            item0 = tbl_item(rv[0], Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            if is_total:
                item0.setFont(fnt(F_MD, True))
                item0.setBackground(QColor("#F1F5F9"))
            self.tbl_users.setItem(r, 0, item0)
            for c in range(1, 14):
                v = rv[c]
                mi = (c - 1) // 3
                color = SLOT_COLORS[mi] if v != "—" and c <= 9 else None
                if c in (10, 11, 12): color = "#000000"  # รวมสี, รวมขาวดำ, รวมทั้งหมด → ดำ
                if c == 13:           color = "#6B7280"  # ค่าใช้จ่าย → เทา
                item = tbl_item(v, color=color, bold=(c >= 10 or is_total), mono=(c == 13))
                if is_total:
                    item.setBackground(QColor("#F1F5F9"))
                self.tbl_users.setItem(r, c, item)

    def _filter_users(self, text):
        """กรองข้อมูลผู้ใช้ตามข้อความค้นหา"""
        self._repopulate_users()

    def _on_month_users_changed(self):
        """เมื่อเลือกเดือนในหน้า Users"""
        self._refresh_users(self._current_slot)

    def _refresh_users(self, slot: int):
        """อัปเดต tab ผู้ใช้งาน ตามเดือนที่เลือก — 2 มุมมอง: ภาพรวม + แบ่งตามเครื่อง"""
        month = self.cmb_month_users.currentData() if self.cmb_month_users.count() > 0 else None
        if month is None:
            self._users_rows_overview = []
            self._users_rows_machine = []
            self._repopulate_users()
            self.lbl_count_users.setText("ไม่มีข้อมูล")
            return

        def _get_any(d: dict, keys, default=0):
            for k in keys:
                if k in d:
                    return d.get(k, default)
            return default

        def _split_by_size(total_val: int, a4_base: int, a3_base: int):
            total_val = max(0, int(total_val or 0))
            a4_base = max(0, int(a4_base or 0))
            a3_base = max(0, int(a3_base or 0))
            base = a4_base + a3_base
            if total_val <= 0:
                return 0, 0
            if base <= 0:
                return total_val, 0
            a4_val = round(total_val * (a4_base / base))
            a4_val = max(0, min(total_val, int(a4_val)))
            return a4_val, total_val - a4_val

        # ── ดึงข้อมูลจากทั้ง 3 เครื่อง ──
        user_map = defaultdict(lambda: [None] * 3)
        public_data = [{"color": 0, "bw": 0, "total": 0,
                        "copy_color": 0, "copy_bw": 0, "print_color": 0, "print_bw": 0,
                        "print_a4c": 0, "print_a4bw": 0, "print_a3c": 0, "print_a3bw": 0,
                        "copy_a4c": 0, "copy_a4bw": 0, "copy_a3c": 0, "copy_a3bw": 0,
                        "a4c": 0, "a4bw": 0, "a3c": 0, "a3bw": 0,
                        "meter_color": 0, "meter_bw": 0} for _ in range(3)]
        label_public_data = [{"color": 0, "bw": 0, "total": 0,
                              "copy_color": 0, "copy_bw": 0, "print_color": 0, "print_bw": 0,
                              "print_a4c": 0, "print_a4bw": 0, "print_a3c": 0, "print_a3bw": 0,
                              "copy_a4c": 0, "copy_a4bw": 0, "copy_a3c": 0, "copy_a3bw": 0,
                              "a4c": 0, "a4bw": 0, "a3c": 0, "a3bw": 0,
                              "meter_color": 0, "meter_bw": 0} for _ in range(3)]

        for i in range(3):
            all_readings = get_all_readings(i)
            prev_data = None
            for data_json, _, billing_month, _ in all_readings:
                if isinstance(data_json, str):
                    try:
                        curr = json.loads(data_json)
                    except:
                        continue
                else:
                    curr = data_json
                if not curr:
                    continue
                if billing_month != month:
                    prev_data = curr
                    continue

                # [V4.5] Account mode — คำนวณ diff จาก prev_data เพื่อแสดงการใช้ในเดือน
                # (เดิมใช้ snapshot ค่าทั้งหมด = overstate)
                if curr.get("accounts"):
                    prev_accs = {p.get("name"): p for p in (prev_data.get("accounts") or [])} if prev_data else {}
                    for a in curr["accounts"]:
                        name = a.get("name")
                        if not name:
                            continue
                        p = prev_accs.get(name)
                        if p:
                            diff_acc = {
                                "name":     name,
                                "total":    max(0, a.get("total", 0) - p.get("total", 0)),
                                "color_a4": max(0, a.get("color_a4", 0) - p.get("color_a4", 0)),
                                "color_a3": max(0, a.get("color_a3", 0) - p.get("color_a3", 0)),
                                "bw_a4":    max(0, a.get("bw_a4", 0)    - p.get("bw_a4", 0)),
                                "bw_a3":    max(0, a.get("bw_a3", 0)    - p.get("bw_a3", 0)),
                            }
                            for k in ("print_color","print_bw","print_a3_color","print_a3_bw",
                                      "copy_color","copy_bw","copy_a3_color","copy_a3_bw",
                                      "print_total","copy_total"):
                                diff_acc[k] = max(0, a.get(k, 0) - p.get(k, 0))
                            user_map[name][i] = diff_acc
                        else:
                            # ไม่มี baseline → ใช้ค่าเต็ม (user ใหม่ในเดือนนี้)
                            user_map[name][i] = a
                    prev_data = curr
                    continue
                # Summary/Production mode → Public
                else:
                    sm = curr.get("summary", {})
                    pc = curr.get("paper_color", {})
                    det = curr.get("detail", {})
                    dc = det.get("copy", {})
                    dp = det.get("print", {})
                    if prev_data:
                        psm = prev_data.get("summary", {})
                        ppc = prev_data.get("paper_color", {})
                        pdet = prev_data.get("detail", {})
                        pdc = pdet.get("copy", {})
                        pdp = pdet.get("print", {})
                        color = max(0, (pc.get("a4_color",0)+pc.get("a3_color",0))
                                     - (ppc.get("a4_color",0)+ppc.get("a3_color",0)))
                        bw    = max(0, (pc.get("a4_bw",0)+pc.get("a3_bw",0))
                                     - (ppc.get("a4_bw",0)+ppc.get("a3_bw",0)))
                        total = max(0, sm.get("total",0) - psm.get("total",0))
                        copy_c = max(0, dc.get("color",0) - pdc.get("color",0))
                        copy_b = max(0, dc.get("bw",0) - pdc.get("bw",0))
                        prt_c  = max(0, dp.get("color",0) - pdp.get("color",0))
                        prt_b  = max(0, dp.get("bw",0) - pdp.get("bw",0))
                        a4c  = max(0, pc.get("a4_color",0) - ppc.get("a4_color",0))
                        a4bw = max(0, pc.get("a4_bw",0) - ppc.get("a4_bw",0))
                        a3c  = max(0, pc.get("a3_color",0) - ppc.get("a3_color",0))
                        a3bw = max(0, pc.get("a3_bw",0) - ppc.get("a3_bw",0))
                        # copy/print per A4/A3
                        cp_a4c  = max(0, _get_any(dc, ("a4_color", "copy_a4_color", "copy_a4c"), 0)
                                     - _get_any(pdc, ("a4_color", "copy_a4_color", "copy_a4c"), 0))
                        cp_a4bw = max(0, _get_any(dc, ("a4_bw", "copy_a4_bw", "copy_a4bw"), 0)
                                     - _get_any(pdc, ("a4_bw", "copy_a4_bw", "copy_a4bw"), 0))
                        cp_a3c  = max(0, _get_any(dc, ("a3_color", "copy_a3_color", "copy_a3c"), 0)
                                     - _get_any(pdc, ("a3_color", "copy_a3_color", "copy_a3c"), 0))
                        cp_a3bw = max(0, _get_any(dc, ("a3_bw", "copy_a3_bw", "copy_a3bw"), 0)
                                     - _get_any(pdc, ("a3_bw", "copy_a3_bw", "copy_a3bw"), 0))
                        pr_a4c  = max(0, _get_any(dp, ("a4_color", "print_a4_color", "print_a4c"), 0)
                                     - _get_any(pdp, ("a4_color", "print_a4_color", "print_a4c"), 0))
                        pr_a4bw = max(0, _get_any(dp, ("a4_bw", "print_a4_bw", "print_a4bw"), 0)
                                     - _get_any(pdp, ("a4_bw", "print_a4_bw", "print_a4bw"), 0))
                        pr_a3c  = max(0, _get_any(dp, ("a3_color", "print_a3_color", "print_a3c"), 0)
                                     - _get_any(pdp, ("a3_color", "print_a3_color", "print_a3c"), 0))
                        pr_a3bw = max(0, _get_any(dp, ("a3_bw", "print_a3_bw", "print_a3bw"), 0)
                                     - _get_any(pdp, ("a3_bw", "print_a3_bw", "print_a3bw"), 0))

                        # บางไฟล์เก็บเฉพาะยอดรวม copy/print ไม่มีแยก A4/A3 → แบ่งตามสัดส่วน paper_color
                        if cp_a4c + cp_a3c == 0 and copy_c > 0:
                            cp_a4c, cp_a3c = _split_by_size(copy_c, a4c, a3c)
                        if cp_a4bw + cp_a3bw == 0 and copy_b > 0:
                            cp_a4bw, cp_a3bw = _split_by_size(copy_b, a4bw, a3bw)
                        if pr_a4c + pr_a3c == 0 and prt_c > 0:
                            pr_a4c, pr_a3c = _split_by_size(prt_c, a4c, a3c)
                        if pr_a4bw + pr_a3bw == 0 and prt_b > 0:
                            pr_a4bw, pr_a3bw = _split_by_size(prt_b, a4bw, a3bw)
                    else:
                        color = pc.get("a4_color",0) + pc.get("a3_color",0)
                        bw    = pc.get("a4_bw",0) + pc.get("a3_bw",0)
                        total = sm.get("total",0)
                        copy_c = dc.get("color",0)
                        copy_b = dc.get("bw",0)
                        prt_c  = dp.get("color",0)
                        prt_b  = dp.get("bw",0)
                        a4c  = pc.get("a4_color",0)
                        a4bw = pc.get("a4_bw",0)
                        a3c  = pc.get("a3_color",0)
                        a3bw = pc.get("a3_bw",0)
                        cp_a4c  = _get_any(dc, ("a4_color", "copy_a4_color", "copy_a4c"), 0)
                        cp_a4bw = _get_any(dc, ("a4_bw", "copy_a4_bw", "copy_a4bw"), 0)
                        cp_a3c  = _get_any(dc, ("a3_color", "copy_a3_color", "copy_a3c"), 0)
                        cp_a3bw = _get_any(dc, ("a3_bw", "copy_a3_bw", "copy_a3bw"), 0)
                        pr_a4c  = _get_any(dp, ("a4_color", "print_a4_color", "print_a4c"), 0)
                        pr_a4bw = _get_any(dp, ("a4_bw", "print_a4_bw", "print_a4bw"), 0)
                        pr_a3c  = _get_any(dp, ("a3_color", "print_a3_color", "print_a3c"), 0)
                        pr_a3bw = _get_any(dp, ("a3_bw", "print_a3_bw", "print_a3bw"), 0)

                        if cp_a4c + cp_a3c == 0 and copy_c > 0:
                            cp_a4c, cp_a3c = _split_by_size(copy_c, a4c, a3c)
                        if cp_a4bw + cp_a3bw == 0 and copy_b > 0:
                            cp_a4bw, cp_a3bw = _split_by_size(copy_b, a4bw, a3bw)
                        if pr_a4c + pr_a3c == 0 and prt_c > 0:
                            pr_a4c, pr_a3c = _split_by_size(prt_c, a4c, a3c)
                        if pr_a4bw + pr_a3bw == 0 and prt_b > 0:
                            pr_a4bw, pr_a3bw = _split_by_size(prt_b, a4bw, a3bw)
                    # ตรวจว่าเป็น Label mode → แยกไปที่ label_public_data
                    _pd = label_public_data[i] if curr.get("mode") == "label" else public_data[i]
                    _pd["color"] += color
                    _pd["bw"]    += bw
                    _pd["total"] += total
                    _pd["copy_color"]  += copy_c
                    _pd["copy_bw"]     += copy_b
                    _pd["print_color"] += prt_c
                    _pd["print_bw"]    += prt_b
                    _pd["a4c"]  += a4c
                    _pd["a4bw"] += a4bw
                    _pd["a3c"]  += a3c
                    _pd["a3bw"] += a3bw
                    _pd["print_a4c"]  += pr_a4c
                    _pd["print_a4bw"] += pr_a4bw
                    _pd["print_a3c"]  += pr_a3c
                    _pd["print_a3bw"] += pr_a3bw
                    _pd["copy_a4c"]   += cp_a4c
                    _pd["copy_a4bw"]  += cp_a4bw
                    _pd["copy_a3c"]   += cp_a3c
                    _pd["copy_a3bw"]  += cp_a3bw
                    # meter data (Label mode)
                    mt  = curr.get("meters", {})
                    pmt = prev_data.get("meters", {}) if prev_data else {}
                    if prev_data:
                        _pd["meter_color"] += max(0, mt.get("color_meter", 0) - pmt.get("color_meter", 0))
                        _pd["meter_bw"]    += max(0, mt.get("bw_meter",    0) - pmt.get("bw_meter",    0))
                    else:
                        _pd["meter_color"] += mt.get("color_meter", 0)
                        _pd["meter_bw"]    += mt.get("bw_meter",    0)

                prev_data = curr

        has_public       = any(m["total"] > 0 for m in public_data)
        has_label_public = any(m["total"] > 0 for m in label_public_data)

        # ══════════════════════════════════════════════════════════
        # มุมมอง 1: ภาพรวม (Overview) — รวมทุกเครื่อง 15 คอลัมน์
        # [name, total, total_color, total_bw, total_print, total_copy,
        #  prt_a4c, prt_a4bw, prt_a3c, prt_a3bw,
        #  cop_a4c, cop_a4bw, cop_a3c, cop_a3bw, cost]
        # ══════════════════════════════════════════════════════════
        self._users_rows_overview = []
        g = [0]*15  # grand totals for 15 numeric cols (incl meter_color, meter_bw)
        g_cost = 0.0

        for name, slots in sorted(user_map.items()):
            v_total = v_tc = v_tb = v_tp = v_tco = 0
            v_meter_c = v_meter_b = 0
            v_pa4c = v_pa4b = v_pa3c = v_pa3b = 0
            v_ca4c = v_ca4b = v_ca3c = v_ca3b = 0
            cost = 0.0
            for i in range(3):
                a = slots[i]
                if isinstance(a, dict) and a:
                    v_total += a.get("total", 0)
                    v_tc    += a.get("color_a4",0) + a.get("color_a3",0)
                    v_tb    += a.get("bw_a4",0) + a.get("bw_a3",0)
                    v_tp    += a.get("print_total", a.get("print_color",0) + a.get("print_bw",0)
                                     + a.get("print_a3_color",0) + a.get("print_a3_bw",0))
                    v_tco   += a.get("copy_total", a.get("copy_color",0) + a.get("copy_bw",0)
                                     + a.get("copy_a3_color",0) + a.get("copy_a3_bw",0))
                    v_pa4c  += _get_any(a, ("print_color", "print_a4_color", "print_a4c"), 0)
                    v_pa4b  += _get_any(a, ("print_bw", "print_a4_bw", "print_a4bw"), 0)
                    v_pa3c  += _get_any(a, ("print_a3_color", "print_a3c"), 0)
                    v_pa3b  += _get_any(a, ("print_a3_bw", "print_a3bw"), 0)
                    v_ca4c  += _get_any(a, ("copy_color", "copy_a4_color", "copy_a4c"), 0)
                    v_ca4b  += _get_any(a, ("copy_bw", "copy_a4_bw", "copy_a4bw"), 0)
                    v_ca3c  += _get_any(a, ("copy_a3_color", "copy_a3c"), 0)
                    v_ca3b  += _get_any(a, ("copy_a3_bw", "copy_a3bw"), 0)
                    cost  += calc_cost(a.get("color_a4",0), a.get("bw_a4",0),
                                       a.get("color_a3",0), a.get("bw_a3",0), i)
            vals = [v_total, v_tc, v_tb, v_meter_c, v_meter_b, v_tp, v_tco,
                    v_pa4c, v_pa4b, v_pa3c, v_pa3b,
                    v_ca4c, v_ca4b, v_ca3c, v_ca3b]
            rv = [name] + [fn(x) for x in vals] + [fmt_baht(cost)]
            self._users_rows_overview.append((v_total, rv))
            for j, x in enumerate(vals): g[j] += x
            g_cost += cost

        if has_public:
            v_total = v_tc = v_tb = v_tp = v_tco = 0
            v_meter_c = v_meter_b = 0
            v_pa4c = v_pa4b = v_pa3c = v_pa3b = 0
            v_ca4c = v_ca4b = v_ca3c = v_ca3b = 0
            cost = 0.0
            for i in range(3):
                m = public_data[i]
                if m["total"] > 0:
                    v_total += m["total"]
                    v_tc    += m["color"]
                    v_tb    += m["bw"]
                    v_meter_c += m["meter_color"]
                    v_meter_b += m["meter_bw"]
                    v_tp    += m["print_color"] + m["print_bw"]
                    v_tco   += m["copy_color"] + m["copy_bw"]
                    v_pa4c  += m["print_a4c"]
                    v_pa4b  += m["print_a4bw"]
                    v_pa3c  += m["print_a3c"]
                    v_pa3b  += m["print_a3bw"]
                    v_ca4c  += m["copy_a4c"]
                    v_ca4b  += m["copy_a4bw"]
                    v_ca3c  += m["copy_a3c"]
                    v_ca3b  += m["copy_a3bw"]
                    if m["meter_color"] > 0 or m["meter_bw"] > 0:
                        cost += (m["meter_color"] * get_price("a4_color", i) +
                                 m["meter_bw"]    * get_price("a4_bw",    i))
                    else:
                        cost += calc_cost(m["a4c"], m["a4bw"], m["a3c"], m["a3bw"], i)
            vals = [v_total, v_tc, v_tb, v_meter_c, v_meter_b, v_tp, v_tco,
                    v_pa4c, v_pa4b, v_pa3c, v_pa3b,
                    v_ca4c, v_ca4b, v_ca3c, v_ca3b]
            rv = ["Public"] + [fn(x) for x in vals] + [fmt_baht(cost)]
            self._users_rows_overview.append((v_total, rv))
            for j, x in enumerate(vals): g[j] += x
            g_cost += cost

        if has_label_public:
            v_total = v_tc = v_tb = v_tp = v_tco = 0
            v_meter_c = v_meter_b = 0
            v_pa4c = v_pa4b = v_pa3c = v_pa3b = 0
            v_ca4c = v_ca4b = v_ca3c = v_ca3b = 0
            cost = 0.0
            for i in range(3):
                m = label_public_data[i]
                if m["total"] > 0:
                    v_total   += m["total"]
                    v_meter_c += m["meter_color"]
                    v_meter_b += m["meter_bw"]
                    v_tc      += m["meter_color"]
                    v_tb      += m["meter_bw"]
                    cost      += (m["meter_color"] * get_price("a4_color", i) +
                                  m["meter_bw"]    * get_price("a4_bw",    i))
            vals = [v_total, v_tc, v_tb, v_meter_c, v_meter_b, v_tp, v_tco,
                    v_pa4c, v_pa4b, v_pa3c, v_pa3b,
                    v_ca4c, v_ca4b, v_ca3c, v_ca3b]
            rv = ["Public (Label)"] + [fn(x) for x in vals] + [fmt_baht(cost)]
            self._users_rows_overview.append((v_total, rv))
            for j, x in enumerate(vals): g[j] += x
            g_cost += cost

        self._users_rows_overview.sort(key=lambda x: x[0], reverse=True)
        # แถว Total
        self._users_rows_overview.append((0,
            ["รวมทั้งหมด"] + [fn(x) for x in g[:15]] + [fmt_baht(g_cost)]))

        # ══════════════════════════════════════════════════════════
        # มุมมอง 2: แบ่งตามเครื่อง (By Machine)
        # ══════════════════════════════════════════════════════════
        self._users_rows_machine = []
        gt_tc = gt_tb = gt_tt = 0; gt_cost = 0.0
        gt_slot = [[0, 0, 0] for _ in range(3)]

        for name, slots in sorted(user_map.items()):
            rv = [name]; tc = tb = tt = 0; total_cost = 0.0
            for i in range(3):
                a = slots[i]
                if isinstance(a, dict) and a:
                    c = a.get("color_a4",0) + a.get("color_a3",0)
                    b = a.get("bw_a4",0)    + a.get("bw_a3",0)
                    t = a.get("total", c + b)
                    cost = calc_cost(a.get("color_a4",0), a.get("bw_a4",0),
                                     a.get("color_a3",0), a.get("bw_a3",0), i)
                    total_cost += cost
                    rv += [fn(c), fn(b), fn(t)]; tc += c; tb += b; tt += t
                    gt_slot[i][0] += c; gt_slot[i][1] += b; gt_slot[i][2] += t
                else:
                    rv += ["—", "—", "—"]
            rv += [fn(tc), fn(tb), fn(tt), fmt_baht(total_cost)]
            self._users_rows_machine.append((tt, rv))
            gt_tc += tc; gt_tb += tb; gt_tt += tt; gt_cost += total_cost

        if has_public:
            rv = ["Public"]; tc = tb = tt = 0; total_cost = 0.0
            for i in range(3):
                m = public_data[i]
                if m["total"] > 0:
                    c = m["color"] + m["meter_color"]
                    b = m["bw"]   + m["meter_bw"]
                    t = m["total"]
                    if m["meter_color"] > 0 or m["meter_bw"] > 0:
                        cost = (m["meter_color"] * get_price("a4_color", i) +
                                m["meter_bw"]    * get_price("a4_bw",    i))
                    else:
                        cost = calc_cost(m["a4c"], m["a4bw"], m["a3c"], m["a3bw"], i)
                    total_cost += cost
                    rv += [fn(c), fn(b), fn(t)]; tc += c; tb += b; tt += t
                    gt_slot[i][0] += c; gt_slot[i][1] += b; gt_slot[i][2] += t
                else:
                    rv += ["—", "—", "—"]
            rv += [fn(tc), fn(tb), fn(tt), fmt_baht(total_cost)]
            self._users_rows_machine.append((tt, rv))
            gt_tc += tc; gt_tb += tb; gt_tt += tt; gt_cost += total_cost

        if has_label_public:
            rv = ["Public (Label)"]; tc = tb = tt = 0; total_cost = 0.0
            for i in range(3):
                m = label_public_data[i]
                if m["total"] > 0:
                    c = m["meter_color"]
                    b = m["meter_bw"]
                    t = m["total"]
                    cost = (m["meter_color"] * get_price("a4_color", i) +
                            m["meter_bw"]    * get_price("a4_bw",    i))
                    total_cost += cost
                    rv += [fn(c), fn(b), fn(t)]; tc += c; tb += b; tt += t
                    gt_slot[i][0] += c; gt_slot[i][1] += b; gt_slot[i][2] += t
                else:
                    rv += ["—", "—", "—"]
            rv += [fn(tc), fn(tb), fn(tt), fmt_baht(total_cost)]
            self._users_rows_machine.append((tt, rv))
            gt_tc += tc; gt_tb += tb; gt_tt += tt; gt_cost += total_cost

        self._users_rows_machine.sort(key=lambda x: x[0], reverse=True)
        # แถว Total
        total_rv = ["รวมทั้งหมด"]
        for i in range(3):
            total_rv += [fn(gt_slot[i][0]), fn(gt_slot[i][1]), fn(gt_slot[i][2])]
        total_rv += [fn(gt_tc), fn(gt_tb), fn(gt_tt), fmt_baht(gt_cost)]
        self._users_rows_machine.append((0, total_rv))

        n_users = len(self._users_rows_overview) - 1  # ลบแถว Total
        self.lbl_count_users.setText(f"พบ {n_users} บัญชี ({month})")
        self._rebuild_users_columns()
        self._repopulate_users()

    def _export_to_excel(self, table: QTableWidget, default_name: str):
        """ส่งออกข้อมูลใน QTableWidget ปัจจุบันเป็นไฟล์ Excel"""
        if table.rowCount() == 0:
            QMessageBox.warning(self, "ไม่มีข้อมูล", "ตารางไม่มีข้อมูลสำหรับส่งออก")
            return
            
        path, _ = QFileDialog.getSaveFileName(
            self, "บันทึกเป็นไฟล์ Excel", f"{default_name}.xlsx", "Excel Files (*.xlsx);;All Files (*)"
        )
        if not path: return
        
        try:
            # Keep the large Excel dependency off the interactive startup path.
            import openpyxl
            from openpyxl.styles import Alignment, Font

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Report"
            
            # Header
            headers = []
            for c in range(table.columnCount()):
                it = table.horizontalHeaderItem(c)
                headers.append(it.text().replace('\n', ' ') if it else "")
            ws.append(headers)
            
            for col in range(1, len(headers)+1):
                cell = ws.cell(row=1, column=col)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center', vertical='center')
                
            # Data
            for r in range(table.rowCount()):
                row_data = []
                for c in range(table.columnCount()):
                    it = table.item(r, c)
                    val = it.text() if it else ""
                    # [V4.5] แปลง string ที่เป็นตัวเลขเป็น number — รองรับ +, -, ทศนิยม, comma
                    clean_val = val.replace(',', '').replace('฿', '').strip()
                    # ตัด leading +/- สำหรับเช็ค isdigit, แต่ keep ค่าเดิมตอน float()
                    test_val = clean_val.lstrip('+-').replace('.', '', 1)
                    if clean_val and test_val.isdigit() and val != "—":
                        try:
                            val = float(clean_val)
                            if val.is_integer(): val = int(val)
                        except: pass
                    row_data.append(val)
                ws.append(row_data)
                
            wb.save(path)
            QMessageBox.information(self, "สำเร็จ", "ส่งออกไฟล์ Excel เรียบร้อยแล้ว")
        except Exception as e:
            QMessageBox.critical(self, "ข้อผิดพลาด", f"ไม่สามารถบันทึกไฟล์ได้:\n{e}")


# ══════════════════════════════════════════════════════════
# PAGE: INDIVIDUAL — การใช้งานรายบุคคล
# ══════════════════════════════════════════════════════════
class PageIndividual(QWidget):
    def __init__(self, get_data, parent=None):
        super().__init__(parent)
        self.get_data = get_data
        self._rows = []
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        tr = QHBoxLayout()
        tr.addWidget(sec_title("👤  การใช้งานรายบุคคล"))
        
        # ── ปุ่มเลือกมุมมอง
        tr.addSpacing(20)
        tr.addWidget(QLabel("มุมมอง:", font=fnt(F_LG)))
        self.view_btns_users = {}
        view_buttons = [
            ("รายวัน", "day"),
            ("รายสัปดาห์", "week"),
            ("รายเดือน", "month"),
            ("รายปี", "year"),
        ]
        for lbl, mode in view_buttons:
            b = btn(lbl, "outline" if mode != "month" else "primary")
            b.setFixedWidth(110)
            b.clicked.connect(lambda checked, m=mode: self._set_view_users(m))
            tr.addWidget(b)
            self.view_btns_users[mode] = b
        
        tr.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  ค้นหาชื่อ...")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._filter)
        tr.addWidget(self.search)
        lay.addLayout(tr)

        self.lbl_count = QLabel("")
        self.lbl_count.setFont(fnt(F_MD))
        self.lbl_count.setStyleSheet(f"color:{C_TEXT2};")
        lay.addWidget(self.lbl_count)

        cols = ["ชื่อผู้ใช้",
                "เครื่อง 1\nสี","เครื่อง 1\nขาวดำ","เครื่อง 1\nรวม",
                "เครื่อง 2\nสี","เครื่อง 2\nขาวดำ","เครื่อง 2\nรวม",
                "เครื่อง 3\nสี","เครื่อง 3\nขาวดำ","เครื่อง 3\nรวม",
                "รวมสี","รวมขาวดำ","รวมทั้งหมด"]
        self.tbl = make_table(cols, stretch_cols=[0],
                              fixed_cols={i:88 for i in range(1,13)})
        self.tbl.setAlternatingRowColors(True)
        lay.addWidget(self.tbl)

    def refresh(self):
        slot_data = self.get_data()
        user_map = defaultdict(lambda: [None]*3)
        for i, (curr,_,__) in enumerate(slot_data):
            if not curr or not curr.get("accounts"): continue
            for a in curr["accounts"]:
                user_map[a["name"]][i] = a

        self._rows = []
        for name, slots in sorted(user_map.items()):
            rv = [name]; tc=tb=tt=0
            for i in range(3):
                a = slots[i]
                if isinstance(a,dict) and a:
                    c = a.get("color_a4",0) + a.get("color_a3",0)
                    b = a.get("bw_a4",0)    + a.get("bw_a3",0)
                    t = a.get("total", c+b)
                    rv += [fn(c), fn(b), fn(t)]; tc+=c; tb+=b; tt+=t
                else:
                    rv += ["—","—","—"]
            rv += [fn(tc), fn(tb), fn(tt)]
            self._rows.append((tt, rv))
        self._rows.sort(key=lambda x: x[0], reverse=True)
        self.lbl_count.setText(f"พบ {len(self._rows)} ผู้ใช้งาน")
        self._populate(self._rows)

    def _populate(self, rows):
        self.tbl.setRowCount(0)
        for _, rv in rows:
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, tbl_item(rv[0], Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft))
            for c in range(1, 13):
                v = rv[c]
                mi = (c-1)//3
                color = SLOT_COLORS[mi] if v != "—" and c <= 9 else None
                if c == 12: color = C_GREEN
                self.tbl.setItem(r, c, tbl_item(v, color=color, bold=(c==12), mono=(c==12)))

    def _filter(self, text):
        self._populate([(t,rv) for t,rv in self._rows if text.lower() in rv[0].lower()])

    def _set_view_users(self, mode: str):
        """เปลี่ยนมุมมอง Users"""
        for m, btn in self.view_btns_users.items():
            btn.setObjectName("primary" if m == mode else "outline")
            btn.style().unpolish(btn)
            btn.style().polish(btn)


# ══════════════════════════════════════════════════════════
# PAGE: SETTINGS — ตั้งค่าทั้งหมด
# ══════════════════════════════════════════════════════════
class PageSettings(QWidget):
    changed = pyqtSignal()   # ส่งสัญญาณเมื่อตั้งค่าเปลี่ยน
    parser_read_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._authenticated = False
        self._build()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_parser_dropdowns()

    @staticmethod
    def _fill_parser_combo(combo, profiles):
        """เติม items ลง parser combo: เฉพาะ user profiles ที่ตั้งค่าแล้ว"""
        has_any = False
        for prof in profiles:
            if not prof.get("column_map"):  # ข้ามถ้ายังไม่ตั้งค่า column_map
                continue
            name = prof.get("name", f"Parser {prof.get('slot', '?')}")
            combo.addItem(name, prof.get("slot", 1))
            has_any = True
        if not has_any:
            combo.addItem("(ยังไม่มี Parser)", None)

    def _refresh_parser_dropdowns(self):
        """โหลด parser profiles ใหม่จากไฟล์ทุกครั้งที่เปิดหน้า Settings"""
        if not hasattr(self, "parser_dropdowns"):
            return
        profiles = load_profiles()
        for slot_idx, combo in self.parser_dropdowns.items():
            combo.blockSignals(True)
            combo.clear()
            self._fill_parser_combo(combo, profiles)
            # ตั้งค่าตาม config ที่บันทึกไว้ (ไม่ใช้ prev_data เพื่อป้องกัน mismatch)
            try:
                saved = get_cfg(f"parser_{slot_idx}", "")
                if saved:
                    idx = combo.findData(int(saved))
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            except (ValueError, TypeError):
                pass
            combo.blockSignals(False)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(20)
        lay.addWidget(sec_title("⚙️  ตั้งค่า"))

        # ── 1. ชื่อเครื่องพิมพ์
        c1 = mk_card(); c1.setMaximumWidth(900)
        l1 = QVBoxLayout(c1); l1.setContentsMargins(20,16,20,16); l1.setSpacing(12)
        l1.addWidget(sub_title("🖨  ชื่อเครื่องพิมพ์"))
        self.name_inp = []
        self.parser_dropdowns = {}
        parser_profiles = load_profiles()
        for i in range(3):
            hr = QHBoxLayout(); hr.setSpacing(8)
            dot = QLabel("●"); dot.setFont(fnt(F_LG, True))
            dot.setStyleSheet(f"color:{SLOT_COLORS[i]};")
            lb = QLabel(f"เครื่อง {i+1} :"); lb.setFont(fnt(F_LG)); lb.setFixedWidth(88)
            inp = QLineEdit(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))
            inp.setFont(fnt(F_LG)); inp.setFixedWidth(160)
            sep = QLabel("|"); sep.setFont(fnt(F_LG)); sep.setStyleSheet(f"color:{C_TEXT3}; padding: 0 4px;")
            parser_lbl = QLabel("Parser :"); parser_lbl.setFont(fnt(F_MD))
            parser_combo = QComboBox(); parser_combo.setFont(fnt(F_MD)); parser_combo.setFixedWidth(300)
            self._fill_parser_combo(parser_combo, parser_profiles)
            current_parser = get_cfg(f"parser_{i}", "")
            if current_parser:
                try:
                    parser_slot_val = int(current_parser)
                    idx_p = parser_combo.findData(parser_slot_val)
                    if idx_p >= 0:
                        parser_combo.setCurrentIndex(idx_p)
                except (ValueError, TypeError):
                    pass
            parser_combo.currentIndexChanged.connect(self._update_price_label_modes)
            hr.addWidget(dot); hr.addWidget(lb); hr.addWidget(inp)
            hr.addWidget(sep); hr.addWidget(parser_lbl); hr.addWidget(parser_combo)
            l1.addLayout(hr)
            self.name_inp.append(inp)
            self.parser_dropdowns[i] = parser_combo
        btn_row = QHBoxLayout(); btn_row.setSpacing(10); btn_row.setContentsMargins(0,4,0,0)
        b_save = btn("💾  บันทึกชื่อเครื่อง", "primary"); b_save.setFixedWidth(200)
        b_save.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        b_save.clicked.connect(self._save_names)
        b_import_parser = btn("📥  นำเข้า Parser", "outline"); b_import_parser.setFixedWidth(180)
        b_import_parser.setStyleSheet("QPushButton { background: #EFF6FF !important; color: #2563EB !important; border: 1.5px solid #BFDBFE !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #2563EB !important; }")
        b_import_parser.clicked.connect(self._import_parser_profile)
        btn_row.addWidget(b_save)
        btn_row.addWidget(b_import_parser)
        btn_row.addStretch()
        l1.addLayout(btn_row)
        lay.addWidget(c1)
        self._btn_save_names = b_save

        # ── 2. Price List (แยกแต่ละเครื่อง)
        c2 = mk_card(); c2.setMaximumWidth(700)
        l2 = QVBoxLayout(c2); l2.setContentsMargins(20,16,20,16); l2.setSpacing(16)
        l2.addWidget(sub_title("💰  ราคาต่อแผ่น (บาท) — แยกแต่ละเครื่อง"))

        price_specs = [
            ("a4_color", "A4 สี",    C_ACCENT),
            ("a4_bw",    "A4 ขาวดำ", C_TEXT2),
            ("a3_color", "A3 สี",    C_ORANGE),
            ("a3_bw",    "A3 ขาวดำ", C_PURPLE),
        ]
        
        # สร้าง price_spins dict โครงสร้าง: {slot: {key: spin}}
        self.price_spins = {0: {}, 1: {}, 2: {}}
        self.price_labels = {0: {}, 1: {}, 2: {}}
        
        # 3 subsections สำหรับแต่ละเครื่อง
        for slot in range(3):
            mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
            dot = QLabel("●"); dot.setFont(fnt(F_LG, True))
            dot.setStyleSheet(f"color:{SLOT_COLORS[slot]};")
            mk_lbl = QLabel(f"เครื่อง {slot+1}: {mname}"); mk_lbl.setFont(fnt(F_MD, True))
            mk_lbl.setStyleSheet(f"color:{SLOT_COLORS[slot]};")
            mk_row = QHBoxLayout(); mk_row.setSpacing(6)
            mk_row.addWidget(dot); mk_row.addWidget(mk_lbl); mk_row.addStretch()
            l2.addLayout(mk_row)
            
            pg = QGridLayout(); pg.setSpacing(10)
            for r, (key, label, color) in enumerate(price_specs):
                lbl = QLabel(f"  {label} :"); lbl.setFont(fnt(F_LG))
                lbl.setStyleSheet(f"color:{color};"); lbl.setFixedWidth(100)
                spin = QDoubleSpinBox()
                spin.setRange(0, 9999); spin.setDecimals(2); spin.setSuffix(" บาท/แผ่น")
                spin.setValue(get_price(key, slot)); spin.setFont(fnt(F_LG)); spin.setFixedWidth(180)
                pg.addWidget(lbl, r//2, (r%2)*2); pg.addWidget(spin, r//2, (r%2)*2+1)
                self.price_spins[slot][key] = spin
                self.price_labels[slot][key] = lbl
            l2.addLayout(pg)
            if slot < 2:
                l2.addWidget(hline())

        b_price = btn("💾  บันทึก Price List", "primary"); b_price.setFixedWidth(200)
        b_price.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        b_price.clicked.connect(self._save_prices)
        l2.addWidget(b_price)
        lay.addWidget(c2)
        self._btn_save_prices = b_price

        self._update_price_label_modes()  # ปรับ label ตาม parser mode ปัจจุบัน

        # ── 2b. % กระดาษเสีย
        c_waste = mk_card(); c_waste.setMaximumWidth(700)
        l_waste = QVBoxLayout(c_waste); l_waste.setContentsMargins(20,16,20,16); l_waste.setSpacing(12)
        l_waste.addWidget(sub_title("📄  % กระดาษเสีย (Waste Paper)"))
        wr = QHBoxLayout()
        lb_waste = QLabel("% กระดาษเสีย :"); lb_waste.setFont(fnt(F_LG)); lb_waste.setFixedWidth(140)
        self.spin_waste = QDoubleSpinBox()
        self.spin_waste.setRange(0, 100); self.spin_waste.setDecimals(1)
        self.spin_waste.setSuffix(" %"); self.spin_waste.setValue(get_waste_paper_pct())
        self.spin_waste.setFont(fnt(F_LG)); self.spin_waste.setFixedWidth(160)
        wr.addWidget(lb_waste); wr.addWidget(self.spin_waste); wr.addStretch()
        l_waste.addLayout(wr)
        waste_hint = QLabel("ใช้สำหรับหักค่าใช้จ่ายกระดาษเสียในรายงานรายเดือน")
        waste_hint.setFont(fnt(F_XS)); waste_hint.setStyleSheet(f"color:{C_TEXT3};")
        l_waste.addWidget(waste_hint)
        b_waste = btn("💾  บันทึก % กระดาษเสีย", "primary"); b_waste.setFixedWidth(220)
        b_waste.clicked.connect(self._save_waste_pct)
        l_waste.addWidget(b_waste)
        lay.addWidget(c_waste)
        self._btn_save_waste = b_waste

        # ── 3. วันตัดรอบ
        c_day = mk_card(); c_day.setMaximumWidth(700)
        l_day = QVBoxLayout(c_day); l_day.setContentsMargins(20,16,20,16); l_day.setSpacing(12)
        l_day.addWidget(sub_title("📅  วันตัดรอบบิล"))
        
        dr = QHBoxLayout()
        lb_day = QLabel("วันตัดรอบบิล :"); lb_day.setFont(fnt(F_LG)); lb_day.setFixedWidth(130)
        self.spin_day = QSpinBox()
        self.spin_day.setRange(1, 31); self.spin_day.setValue(get_billing_day())
        self.spin_day.setSuffix(" ของเดือน"); self.spin_day.setFont(fnt(F_LG)); self.spin_day.setFixedWidth(180)
        dr.addWidget(lb_day); dr.addWidget(self.spin_day); dr.addStretch()
        l_day.addLayout(dr)
        
        day_hint = QLabel("เช่น ถ้าตั้งวัน 25 → ไฟล์ที่อ่านวันที่ 1-25 นับเป็นเดือนนั้น, หลังวันที่ 25 นับเป็นเดือนถัดไป")
        day_hint.setFont(fnt(F_XS)); day_hint.setStyleSheet(f"color:{C_TEXT3};")
        l_day.addWidget(day_hint)

        b_day = btn("💾  บันทึกวันตัดรอบ", "primary"); b_day.setFixedWidth(200)
        b_day.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        b_day.clicked.connect(self._save_billing_day)
        l_day.addWidget(b_day)
        lay.addWidget(c_day)
        self._btn_save_billing_day = b_day

        # ── 4. Log การเปลี่ยนแปลง Pricelist
        c_log = mk_card(); c_log.setMaximumWidth(700)
        l_log = QVBoxLayout(c_log); l_log.setContentsMargins(20,16,20,16); l_log.setSpacing(12)
        l_log.addWidget(sub_title("📋  ประวัติการเปลี่ยนแปลงการตั้งค่า"))
        
        self.log_table = make_table(
            ["ลำดับที่", "รายการ", "ค่าเก่า", "ค่าใหม่", "วัน/เวลา"],
            stretch_cols=[1],
            fixed_cols={0:80, 2:100, 3:100, 4:160},
            height=220
        )
        l_log.addWidget(self.log_table)
        lay.addWidget(c_log)

        # ── 5. Database path
        c3 = mk_card(); c3.setMaximumWidth(700)
        l3 = QVBoxLayout(c3); l3.setContentsMargins(20,16,20,16); l3.setSpacing(10)
        l3.addWidget(sub_title("🗄  Database"))
        self.db_lbl = QLabel()
        self.db_lbl.setFont(fnt(F_XS))
        self.db_lbl.setWordWrap(True)
        self.db_lbl.setMinimumWidth(0)
        self.db_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.db_lbl.setStyleSheet(f"color:{C_TEXT2}; background:#F1F5F9; padding:8px; border-radius:6px;")
        b_ch = btn("เปลี่ยน Path", "outline"); b_ch.setFixedWidth(130)
        b_ch.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 7px 16px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        b_ch.clicked.connect(self._change_db)
        self._btn_change_db_path = b_ch
        l3.addWidget(self.db_lbl)
        l3.addWidget(b_ch, 0, Qt.AlignmentFlag.AlignLeft)
        self._v5_db_migration_note = QLabel(
            "การเปลี่ยน Path หรือนำ Backup กลับมาใช้ จะสร้างสำเนาที่ตรวจสอบแล้ว "
            "และมีผลเมื่อเปิดโปรแกรมครั้งถัดไป ฐานข้อมูลที่กำลังใช้จะไม่ถูกทับ"
        )
        self._v5_db_migration_note.setWordWrap(True)
        self._v5_db_migration_note.setStyleSheet(
            "background:#FFF4E5;color:#8A4B08;border:1px solid #F4C98B;"
            "border-radius:6px;padding:8px 10px;"
        )
        self._v5_db_migration_note.hide()
        l3.addWidget(self._v5_db_migration_note)
        db_actions = QHBoxLayout(); db_actions.setSpacing(8)
        self._btn_check_db = btn("ตรวจสอบ Database", "outline")
        self._btn_check_db.clicked.connect(self._inspect_database)
        self._btn_backup_db = btn("สำรอง Database", "outline")
        self._btn_backup_db.clicked.connect(self._backup_database)
        self._btn_restore_db = btn("นำ Backup กลับมาใช้", "outline")
        self._btn_restore_db.clicked.connect(self._stage_database_restore)
        db_actions.addWidget(self._btn_check_db)
        db_actions.addWidget(self._btn_backup_db)
        db_actions.addWidget(self._btn_restore_db)
        db_actions.addStretch()
        l3.addLayout(db_actions)
        self._refresh_db_path_label()

        # ── Imported folder path
        l3.addWidget(QLabel("โฟลเดอร์เก็บไฟล์สำรอง (Imported):", font=fnt(F_SM)))
        default_imported = str(Path(get_cfg("db_path", str(DB_PATH))).parent / "imported")
        self.imported_lbl = QLabel(get_cfg("imported_path", default_imported))
        self.imported_lbl.setFont(fnt(F_XS))
        self.imported_lbl.setWordWrap(True)
        self.imported_lbl.setMinimumWidth(0)
        self.imported_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.imported_lbl.setStyleSheet(f"color:{C_TEXT2}; background:#F1F5F9; padding:8px; border-radius:6px;")
        b_ch2 = btn("เปลี่ยนโฟลเดอร์สำรอง", "outline"); b_ch2.setFixedWidth(180)
        b_ch2.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 7px 16px; font-weight: 600; } QPushButton:hover { background: #2563EB !important; color: white !important; border-color: #E2E8F0 !important; }")
        b_ch2.clicked.connect(self._change_imported_path)
        b_open_imported = btn("📂  เปิดโฟลเดอร์", "outline"); b_open_imported.setMinimumWidth(150)
        b_open_imported.setStyleSheet("QPushButton { background: white !important; color: #0F172A !important; border: 1.5px solid #E2E8F0 !important; border-radius: 8px; padding: 7px 16px; font-weight: 600; } QPushButton:hover { background: #16A34A !important; color: white !important; border-color: #16A34A !important; }")
        b_open_imported.clicked.connect(self._open_imported_folder)
        l3.addWidget(self.imported_lbl)
        imported_actions = QHBoxLayout(); imported_actions.setSpacing(8)
        imported_actions.addWidget(b_ch2)
        imported_actions.addWidget(b_open_imported)
        imported_actions.addStretch()
        l3.addLayout(imported_actions)

        lay.addWidget(c3)

        # ── 6. Parser tuning
        c_parser = mk_card(); c_parser.setMaximumWidth(700)
        l_parser = QVBoxLayout(c_parser); l_parser.setContentsMargins(20,16,20,16); l_parser.setSpacing(10)
        l_parser.addWidget(sub_title("🧩  ตรวจสอบ Parser Mapping"))
        p_hint = QLabel(
            "ดูข้อมูล Raw จากเครื่องแต่ละ Slot เทียบกับช่องที่จะบันทึกใน Database "
            "และแก้ Mapping เฉพาะ Serial Number ได้"
        )
        p_hint.setFont(fnt(F_MD)); p_hint.setStyleSheet(f"color:{C_TEXT2};")
        p_hint.setWordWrap(True)
        l_parser.addWidget(p_hint)
        b_parser = btn("🔎  ตรวจสอบ Parser Mapping", "outline"); b_parser.setFixedWidth(260)
        b_parser.clicked.connect(self._open_parser_settings)
        l_parser.addWidget(b_parser)
        lay.addWidget(c_parser)

        # ── 7. Program behaviour, logs and maintenance
        c_runtime = mk_card(); c_runtime.setMaximumWidth(900)
        l_runtime = QVBoxLayout(c_runtime)
        l_runtime.setContentsMargins(20, 16, 20, 16)
        l_runtime.setSpacing(12)
        l_runtime.addWidget(sub_title("⚙️  โปรแกรม Log และการบำรุงรักษา"))

        self.runtime_info = QLabel()
        self.runtime_info.setWordWrap(True)
        self.runtime_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.runtime_info.setStyleSheet(
            f"color:{C_TEXT2};background:#F1F5F9;border:1px solid #D6E0EA;"
            "border-radius:6px;padding:9px 11px;"
        )
        l_runtime.addWidget(self.runtime_info)

        self.close_to_tray = QCheckBox(
            "เมื่อกดปิดหน้าต่าง ให้โปรแกรมทำงานต่อใน System Tray"
        )
        self.close_to_tray.setChecked(get_cfg("close_to_tray", "1") != "0")
        self.close_to_tray.setToolTip(
            "ยกเลิกตัวเลือกนี้ หากต้องการให้ปุ่มปิดหน้าต่างหยุดโปรแกรมจริง"
        )
        l_runtime.addWidget(self.close_to_tray)

        preference_row = QHBoxLayout(); preference_row.setSpacing(8)
        retention_label = QLabel("เก็บ Log ย้อนหลัง")
        retention_label.setFont(fnt(F_MD, True))
        self.log_retention_days = QSpinBox()
        self.log_retention_days.setRange(1, 365)
        self.log_retention_days.setSuffix(" วัน")
        try:
            retention_days = int(get_cfg("log_retention_days", "30") or "30")
        except ValueError:
            retention_days = 30
        self.log_retention_days.setValue(max(1, min(365, retention_days)))
        save_program = btn("บันทึกการทำงานของโปรแกรม", "primary")
        save_program.clicked.connect(self._save_program_preferences)
        preference_row.addWidget(retention_label)
        preference_row.addWidget(self.log_retention_days)
        preference_row.addSpacing(10)
        preference_row.addWidget(save_program)
        preference_row.addStretch()
        l_runtime.addLayout(preference_row)

        # Two rows keep the English labels readable at the supported
        # 1024 px desktop width without forcing horizontal scrolling.
        log_actions = QGridLayout(); log_actions.setSpacing(8)
        open_logs = btn("เปิดโฟลเดอร์ Log", "outline")
        open_logs.clicked.connect(self._open_log_folder)
        export_logs = btn("ส่งออก Log สำหรับ Support", "outline")
        export_logs.clicked.connect(self._open_issue_log)
        clear_logs = btn("ล้าง Log เก่า", "outline")
        clear_logs.clicked.connect(self._clear_old_logs)
        clear_cache = btn("ล้างไฟล์ชั่วคราว", "outline")
        clear_cache.clicked.connect(self._clear_runtime_cache)
        log_actions.addWidget(open_logs, 0, 0)
        log_actions.addWidget(export_logs, 0, 1)
        log_actions.addWidget(clear_logs, 1, 0)
        log_actions.addWidget(clear_cache, 1, 1)
        log_actions.setColumnStretch(2, 1)
        l_runtime.addLayout(log_actions)
        lay.addWidget(c_runtime)

        # ── 8. Data and reset actions.  Keep all destructive choices in one
        # clearly-scannable system instead of two similar warning cards.
        c4 = mk_card()
        l4 = QVBoxLayout(c4); l4.setContentsMargins(20,16,20,16); l4.setSpacing(8)
        l4.addWidget(sub_title("⚠️  จัดการข้อมูลและคืนค่าโปรแกรม"))
        warn = QLabel("ระบบสำรอง Database ก่อนเปลี่ยนหรือลบข้อมูลทุกครั้ง กรุณาเลือกตามผลกระทบที่ต้องการ")
        warn.setFont(fnt(F_MD)); warn.setStyleSheet(f"color:{C_ORANGE};")
        warn.setWordWrap(True)
        l4.addWidget(warn)

        def maintenance_row(title: str, detail: str, action: str, callback, *, danger: bool = False):
            row = QFrame()
            row.setObjectName("maintenance_action_row")
            row.setStyleSheet(
                "QFrame#maintenance_action_row{background:#F8FAFC;border:1px solid #D6E0EA;"
                "border-radius:7px;} QLabel{background:transparent;border:none;}"
            )
            body = QHBoxLayout(row); body.setContentsMargins(12,9,12,9); body.setSpacing(12)
            copy = QVBoxLayout(); copy.setSpacing(2)
            heading = QLabel(title); heading.setFont(fnt(F_MD, True))
            explanation = QLabel(detail); explanation.setWordWrap(True)
            explanation.setStyleSheet(f"color:{C_TEXT2};")
            copy.addWidget(heading); copy.addWidget(explanation)
            body.addLayout(copy, 1)
            button = btn(action, "danger" if danger else "outline")
            button.setMinimumWidth(180)
            button.clicked.connect(callback)
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            l4.addWidget(row)
            return button

        b_rst = maintenance_row(
            "ล้างเฉพาะประวัติการใช้งาน",
            "ลบ Reading, Billing และ Log ใน Database · เก็บเครื่องพิมพ์ ราคา Parser และ Registration",
            "ล้างประวัติ",
            self._reset,
            danger=True,
        )
        b_rst_cfg = maintenance_row(
            "คืนค่าการตั้งค่าทั่วไป",
            "คืนชื่อเครื่อง ราคา และวันตัดรอบเป็นค่าเริ่มต้น · ไม่ลบประวัติการใช้งาน",
            "คืนค่า Settings",
            self._reset_settings,
        )
        b_rst_parser = maintenance_row(
            "คืนค่า Parser Mapping",
            "สำรองและลบ Parser Profile ที่ปรับแต่งไว้ · ไม่ลบ Database",
            "คืนค่า Parser",
            self._reset_parser,
        )
        b_factory = maintenance_row(
            "เริ่มติดตั้งและตั้งค่าใหม่ทั้งหมด",
            "ลบเครื่องพิมพ์ ราคา ประวัติ Parser override และสถานะ Registration แล้วกลับไป Setup Wizard",
            "เริ่มตั้งค่าใหม่",
            self._factory_reset,
            danger=True,
        )
        lay.addWidget(c4)
        self._btn_reset_db = b_rst
        self._btn_reset_settings = b_rst_cfg
        lay.addStretch()

        # [V4.5] เปิดใช้ระบบรหัสผ่าน — เนื้อหาถูกซ่อนจนกว่าจะ unlock ผ่าน ensure_unlocked()
        self._protected_widgets = [
            c1, c2, c_waste, c_day, c_log, c3, c_parser, c_runtime, c4
        ]
        # V5 owns devices, PricingRepository, billing day and waste discount in
        # its main Settings page.  Keep the legacy cards for V4 compatibility,
        # but hide every duplicate editor when this page is embedded in V5.
        # Parser tuning remains available through the separate protected card.
        self._v5_duplicate_cards = [c1, c2, c_waste, c_day]
        self._authenticated = False
        self._set_protected_visible(False)

        # โหลด log ครั้งแรก (จะถูก refresh อีกครั้งหลัง unlock)
        self._refresh_log()

    def _on_machine_type_changed(self, slot: int):
        pass  # machine type selection removed — parser is now inline with machine name

    def _save_machine_types(self):
        pass  # removed — parser saving is now in _save_names()

    def _set_protected_visible(self, visible: bool):
        """Show/hide protected settings widgets based on authentication"""
        for w in getattr(self, '_protected_widgets', []):
            w.setVisible(visible)

    def set_v5_embed_mode(self) -> None:
        """Prepare legacy support tools for the simplified V5 Settings page."""
        self._v5_embed_mode = True
        duplicates = set(getattr(self, "_v5_duplicate_cards", []))
        self._protected_widgets = [
            widget for widget in getattr(self, "_protected_widgets", [])
            if widget not in duplicates
        ]
        for widget in duplicates:
            widget.setVisible(False)
        if hasattr(self, "_btn_change_db_path"):
            self._btn_change_db_path.setVisible(True)
        if hasattr(self, "_v5_db_migration_note"):
            self._v5_db_migration_note.setVisible(True)
        # V5.1 no longer asks general users for a Settings password.  Risky
        # operations retain their explicit warning and confirmation dialogs.
        self._authenticated = True
        self._set_protected_visible(True)
        for widget in self._protected_widgets:
            widget.setMaximumWidth(16777215)
        title_item = self.layout().itemAt(0) if self.layout() is not None else None
        if title_item is not None and title_item.widget() is not None:
            title_item.widget().hide()
        self._refresh_db_path_label()

    def ensure_unlocked(self) -> bool:
        """เรียกก่อนเข้าแท็บ Settings: ตรวจสอบรหัสผ่านก่อนเข้าหน้า"""
        if getattr(self, "_v5_embed_mode", False):
            self._authenticated = True
            self._set_protected_visible(True)
            return True
        if getattr(self, "_authenticated", False):
            return True
        if self._ask_password():
            self._authenticated = True
            self._set_protected_visible(True)
            self._refresh_ui()
            self._refresh_log()
            return True
        return False

    def _ask_password(self) -> bool:
        """แสดง dialog ขอรหัสผ่าน"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        from config import C_ACCENT, C_TEXT, C_TEXT2, C_BORDER, F_MD, F_SM
        from widgets import fnt

        dlg = QDialog(self)
        dlg.setWindowTitle("ยืนยันรหัสผ่าน")
        dlg.setFixedWidth(320)
        dlg.setWindowFlags(
            dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)

        lbl = QLabel("🔒  ใส่รหัสผ่านเพื่อเข้าหน้า Settings")
        lbl.setFont(fnt(F_SM, bold=True))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color:{C_TEXT};")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        pwd_edit = QLineEdit()
        pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_edit.setPlaceholderText("รหัสผ่าน...")
        pwd_edit.setFont(fnt(F_MD))
        pwd_edit.setFixedHeight(34)
        pwd_edit.setStyleSheet(
            f"QLineEdit {{ border:1px solid {C_BORDER}; border-radius:6px;"
            f" padding:4px 10px; color:{C_TEXT}; }}"
        )
        lay.addWidget(pwd_edit)

        err_lbl = QLabel("")
        err_lbl.setFont(fnt(F_SM))
        err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_lbl.setStyleSheet("color:#DC2626;")
        lay.addWidget(err_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_cancel = QPushButton("ยกเลิก")
        btn_cancel.setFont(fnt(F_SM))
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(
            f"QPushButton {{ background:{C_BORDER}; color:{C_TEXT2}; border:none;"
            f" border-radius:6px; padding:4px 14px; }}"
        )
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("ยืนยัน")
        btn_ok.setFont(fnt(F_SM, bold=True))
        btn_ok.setFixedHeight(32)
        btn_ok.setStyleSheet(
            f"QPushButton {{ background:{C_ACCENT}; color:white; border:none;"
            f" border-radius:6px; padding:4px 14px; }}"
            f"QPushButton:hover {{ background:#1E3A8A; }}"
        )
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        _result = [False]
        # [V4.5] password lockout — เก็บใน instance attribute
        if not hasattr(self, "_pwd_attempts"):
            self._pwd_attempts = 0
        if not hasattr(self, "_pwd_lock_until"):
            self._pwd_lock_until = None

        from datetime import datetime as _dt, timedelta as _td

        def _check_lock():
            if self._pwd_lock_until and _dt.now() < self._pwd_lock_until:
                remain = int((self._pwd_lock_until - _dt.now()).total_seconds())
                err_lbl.setText(f"ใส่ผิดเกินกำหนด — โปรดรอ {remain} วินาที")
                pwd_edit.setEnabled(False)
                btn_ok.setEnabled(False)
                return True
            pwd_edit.setEnabled(True)
            btn_ok.setEnabled(True)
            return False

        def _confirm():
            if _check_lock():
                return
            if verify_settings_password(pwd_edit.text()):
                _result[0] = True
                self._pwd_attempts = 0
                self._pwd_lock_until = None
                dlg.accept()
            else:
                self._pwd_attempts += 1
                remaining = max(0, 3 - self._pwd_attempts)
                if self._pwd_attempts >= 3:
                    self._pwd_lock_until = _dt.now() + _td(seconds=30)
                    err_lbl.setText("ใส่ผิด 3 ครั้ง — ล็อก 30 วินาที")
                    pwd_edit.setEnabled(False)
                    btn_ok.setEnabled(False)
                    log.warning("settings password locked for 30s after 3 failed attempts")
                else:
                    err_lbl.setText(f"รหัสผ่านไม่ถูกต้อง (เหลืออีก {remaining} ครั้ง)")
                    pwd_edit.clear()
                    pwd_edit.setFocus()

        _check_lock()
        btn_ok.clicked.connect(_confirm)
        pwd_edit.returnPressed.connect(_confirm)

        dlg.exec()
        return _result[0]

    def _import_parser_profile(self):
        """[V4.5] นำเข้า Parser Profile (.json) — validate schema/ขนาด ก่อน save"""
        from tools.check_parser import load_profiles, save_profiles, _empty_profile

        path, _ = QFileDialog.getOpenFileName(
            self, "เลือกไฟล์ Parser Profile (.json)",
            "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            from app import validate_parser_json
            new_profiles = validate_parser_json(path)
        except Exception as e:
            QMessageBox.critical(self, "โหลดไฟล์ไม่ได้", str(e))
            return

        try:
            existing = load_profiles()
        except Exception:
            existing = []

        # ต่อท้าย profile ใหม่ (ไม่ทับของเดิม)
        next_slot = (max((p.get("slot", 0) for p in existing), default=0)) + 1
        added = 0
        for np_ in new_profiles:
            profile = {**_empty_profile(next_slot), **np_, "slot": next_slot}
            existing.append(profile)
            next_slot += 1
            added += 1

        save_profiles(existing)
        self._refresh_parser_dropdowns()
        QMessageBox.information(
            self, "นำเข้าสำเร็จ",
            f"นำเข้า Parser Profile {added} รายการแล้ว"
        )

    def _save_names(self):
        for i, inp in enumerate(self.name_inp):
            set_cfg(f"machine_name_{i}", inp.text())
        for slot, parser_combo in self.parser_dropdowns.items():
            parser_slot_val = parser_combo.currentData()
            if parser_slot_val:
                set_cfg(f"parser_{slot}", str(parser_slot_val))
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว", "บันทึกชื่อเครื่องและ Parser เรียบร้อย")

    def _update_price_label_modes(self, *_):
        """ปรับ label ราคา — Label mode: แสดง Meter สี/ขาวดำ, ซ่อน A3"""
        lbl_renames = {
            "a4_color": ("Meter - สี",    "บาท/เมตร"),
            "a4_bw":    ("Meter - ขาวดำ", "บาท/เมตร"),
        }
        std_names = {
            "a4_color": ("A4 สี",    "บาท/แผ่น"),
            "a4_bw":    ("A4 ขาวดำ", "บาท/แผ่น"),
            "a3_color": ("A3 สี",    "บาท/แผ่น"),
            "a3_bw":    ("A3 ขาวดำ", "บาท/แผ่น"),
        }
        all_profiles = load_profiles()
        profiles_by_slot = {p["slot"]: p for p in all_profiles}
        for slot in range(3):
            combo = self.parser_dropdowns.get(slot)
            is_lbl = False
            if combo is not None:
                profile_slot = combo.currentData()
                prof = profiles_by_slot.get(profile_slot, {})
                is_lbl = "label" in prof.get("types", [])
            for key in ["a4_color", "a4_bw", "a3_color", "a3_bw"]:
                lbl_w = self.price_labels.get(slot, {}).get(key)
                spin  = self.price_spins.get(slot, {}).get(key)
                if not lbl_w or not spin:
                    continue
                if is_lbl:
                    if key in lbl_renames:
                        new_name, new_suffix = lbl_renames[key]
                        lbl_w.setText(f"  {new_name} :")
                        spin.setSuffix(f" {new_suffix}")
                        lbl_w.show(); spin.show()
                    else:  # a3_color, a3_bw — ซ่อน
                        lbl_w.hide(); spin.hide()
                else:
                    n, s = std_names[key]
                    lbl_w.setText(f"  {n} :")
                    spin.setSuffix(f" {s}")
                    lbl_w.show(); spin.show()

    def _save_prices(self):
        for slot in range(3):
            for key, spin in self.price_spins[slot].items():
                set_cfg(f"price_{slot}_{key}", str(spin.value()))
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว", "บันทึก Price List เรียบร้อย")

    def _save_waste_pct(self):
        set_waste_paper_pct(self.spin_waste.value())
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว",
            f"บันทึก % กระดาษเสีย ({self.spin_waste.value():.1f}%) เรียบร้อย")

    def _save_billing_day(self):
        set_cfg("billing_day", str(self.spin_day.value()))
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว",
            f"บันทึกวันตัดรอบบิล (วันที่ {self.spin_day.value()}) เรียบร้อย")

    def _refresh_log(self):
        """โหลดและแสดง Pricelist change log"""
        self.log_table.setRowCount(0)
        logs = get_config_log(50)  # แสดง 50 รายการล่าสุด
        
        for idx, log in enumerate(logs):
            self.log_table.insertRow(idx)
            # ลำดับที่
            self.log_table.setItem(idx, 0, tbl_item(str(idx + 1), Qt.AlignmentFlag.AlignCenter))
            
            # รายการ (config_key) — แปลงเป็นชื่อไทยสำหรับอ่านง่าย
            config_key = log["config_key"]
            if config_key.startswith("price_"):
                # แปลง price_0_a4_color → เครื่อง 1 - A4 สี
                parts = config_key.split("_")
                if len(parts) >= 3:
                    slot = int(parts[1])
                    price_type = "_".join(parts[2:])
                    mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
                    # แปลง a4_color → A4 สี
                    price_labels = {
                        "a4_color": "A4 สี",
                        "a4_bw": "A4 ขาวดำ",
                        "a3_color": "A3 สี",
                        "a3_bw": "A3 ขาวดำ",
                    }
                    price_label = price_labels.get(price_type, price_type)
                    display_key = f"เครื่อง {slot+1}: {mname} → {price_label}"
                else:
                    display_key = config_key
            elif config_key == "billing_day":
                display_key = "วันตัดรอบบิล"
            else:
                display_key = config_key
            
            self.log_table.setItem(idx, 1, tbl_item(display_key))
            
            # ค่าเก่า
            old_val = log["old_value"] or "-"
            self.log_table.setItem(idx, 2, tbl_item(str(old_val)))
            
            # ค่าใหม่
            new_val = log["new_value"] or "-"
            self.log_table.setItem(idx, 3, tbl_item(str(new_val)))
            
            # วัน/เวลา
            time_str = log["changed_at"] or "-"
            self.log_table.setItem(idx, 4, tbl_item(str(time_str)))

    @staticmethod
    def _runtime_config_path() -> Path:
        return Path(os.environ.get("KOMI_RUNTIME_CONFIG", RUNTIME_SETTINGS.config_path))

    def _next_start_database_path(self) -> Path:
        config_path = self._runtime_config_path()
        if not config_path.is_file():
            return Path(get_db_path()).expanduser().resolve(strict=False)
        return load_runtime_settings({}, config_path=config_path).db_path.resolve(strict=False)

    @staticmethod
    def _database_filename(path: str | Path) -> Path:
        destination = Path(path).expanduser()
        if destination.suffix.casefold() != ".db":
            destination = destination.with_suffix(".db")
        return destination.resolve(strict=False)

    def _persist_next_database(self, destination: Path) -> None:
        save_runtime_database_path(destination, config_path=self._runtime_config_path())
        self._refresh_db_path_label()

    def _change_db(self):
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        p, _ = QFileDialog.getSaveFileName(
            self,
            "เลือกตำแหน่ง Database ใหม่",
            str(active.with_name(f"{active.stem}-copy.db")),
            "SQLite (*.db)",
        )
        if not p:
            return
        destination = self._database_filename(p)
        try:
            copy_database_for_first_run(destination)
            self._persist_next_database(destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "เปลี่ยน Path ไม่สำเร็จ",
                f"{error}\n\nDatabase ที่กำลังใช้ไม่ถูกแก้ไข",
            )
            return
        QMessageBox.information(
            self,
            "เตรียม Database ใหม่แล้ว",
            f"สร้างสำเนาที่ตรวจสอบแล้ว:\n{destination}\n\n"
            "จะเริ่มใช้เมื่อปิดและเปิดโปรแกรมครั้งถัดไป",
        )

    def _inspect_database(self) -> None:
        active = Path(get_db_path())
        try:
            result = inspect_database(active)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Database ไม่ผ่าน", str(error))
            return
        counts = result.get("critical_counts", {})
        total_rows = sum(int(value) for value in counts.values()) if isinstance(counts, dict) else 0
        QMessageBox.information(
            self,
            "Database พร้อมใช้งาน",
            f"Integrity: OK\nSchema: {result.get('user_version', '—')}\n"
            f"ตรวจพบข้อมูลสำคัญ {total_rows:,} รายการ\n\n{active}",
        )

    def _backup_database(self) -> None:
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = active.parent / "backups" / f"{active.stem}-{stamp}.db"
        p, _ = QFileDialog.getSaveFileName(
            self,
            "สำรอง Database",
            str(default),
            "SQLite (*.db)",
        )
        if not p:
            return
        destination = self._database_filename(p)
        try:
            result = backup_database(active, destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "สำรองไม่สำเร็จ", str(error))
            return
        QMessageBox.information(
            self,
            "สำรอง Database แล้ว",
            f"Integrity: {str(result.get('integrity', '')).upper()}\n{destination}\n"
            f"Archive: {result.get('archive_files', 0):,} ไฟล์\n"
            "เก็บโฟลเดอร์ archives ข้างไฟล์สำรองไว้ด้วยเมื่อต้องย้ายหรือกู้คืน",
        )

    def _stage_database_restore(self) -> None:
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        source, _ = QFileDialog.getOpenFileName(
            self,
            "เลือก Backup Database",
            str(active.parent),
            "SQLite (*.db)",
        )
        if not source:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = active.with_name(f"{active.stem}-restored-{stamp}.db")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "บันทึกฐานข้อมูลที่จะใช้ครั้งถัดไป",
            str(default),
            "SQLite (*.db)",
        )
        if not target:
            return
        destination = self._database_filename(target)
        try:
            inspect_database(Path(source))
            backup_database(Path(source), destination)
            self._persist_next_database(destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "นำ Backup กลับมาใช้ไม่สำเร็จ",
                f"{error}\n\nDatabase ที่กำลังใช้ไม่ถูกแก้ไข",
            )
            return
        QMessageBox.information(
            self,
            "เตรียม Backup แล้ว",
            f"ตรวจสอบและสร้างสำเนาแล้ว:\n{destination}\n\n"
            "จะเริ่มใช้เมื่อปิดและเปิดโปรแกรมครั้งถัดไป",
        )

    def _refresh_db_path_label(self):
        """Show the database used now and a different next-start path explicitly."""
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        configured = (
            self._next_start_database_path()
            if getattr(self, "_v5_embed_mode", False)
            else Path(get_cfg("db_path", str(active)) or active)
        )
        if configured == active:
            text = f"กำลังใช้งาน: {active}"
        else:
            text = f"กำลังใช้งาน: {active}\nหลังเปิดโปรแกรมครั้งถัดไป: {configured}"
        self.db_lbl.setText(text)
        self.db_lbl.setToolTip(text)

    def _change_imported_path(self):
        current = get_cfg("imported_path", "")
        start = current if current else str(Path(get_cfg("db_path", str(DB_PATH))).parent)
        p = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์เก็บไฟล์สำรอง", start)
        if p:
            self.imported_lbl.setText(p)
            set_cfg("imported_path", p)
            QMessageBox.information(self, "บันทึกแล้ว",
                f"โฟลเดอร์ Imported:\n{p}\n\nมีผลทันทีกับการ import ครั้งถัดไป")

    def _open_imported_folder(self):
        """เปิดโฟลเดอร์ imported ใน File Manager"""
        custom = get_cfg("imported_path", "")
        default = str(Path(get_cfg("db_path", str(DB_PATH))).parent / "imported")
        folder = Path(custom) if custom else Path(default)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_parser_settings(self):
        """Open the V5.2 Raw → Mapping → Database inspector."""
        from ui.parser_mapping_inspector import ParserMappingInspector

        window = ParserMappingInspector(
            self,
            read_requested=self.parser_read_requested.emit,
        )
        _parser_editor_windows.append(window)
        window.destroyed.connect(
            lambda: _parser_editor_windows.remove(window)
            if window in _parser_editor_windows
            else None
        )
        window.show()
        window.raise_()
        window.activateWindow()

    def _refresh_runtime_info(self) -> None:
        log_dir = RUNTIME_SETTINGS.log_dir.expanduser().resolve(strict=False)
        close_behavior = (
            tr(
                "ปิดหน้าต่างแล้วทำงานต่อใน System Tray",
                "Closing the window keeps the app running in the System Tray",
            )
            if self.close_to_tray.isChecked()
            else tr(
                "ปิดหน้าต่างแล้วหยุดโปรแกรม",
                "Closing the window exits the application",
            )
        )
        self.runtime_info.setText(
            f"Version {APP_VER} · {platform.system()} / {platform.machine()}\n"
            f"{close_behavior}\nLog: {log_dir}"
        )

    def _save_program_preferences(self) -> None:
        set_cfg("close_to_tray", "1" if self.close_to_tray.isChecked() else "0")
        set_cfg("log_retention_days", str(self.log_retention_days.value()))
        self._refresh_runtime_info()
        self.changed.emit()
        QMessageBox.information(
            self,
            "บันทึกแล้ว",
            "บันทึกพฤติกรรมการปิดโปรแกรมและระยะเวลาเก็บ Log แล้ว",
        )

    @staticmethod
    def _active_log_paths() -> set[Path]:
        active: set[Path] = set()
        for handler in logging.getLogger().handlers:
            base_filename = getattr(handler, "baseFilename", None)
            if base_filename:
                active.add(Path(base_filename).resolve(strict=False))
        return active

    def _open_log_folder(self) -> None:
        log_dir = RUNTIME_SETTINGS.log_dir.expanduser().resolve(strict=False)
        log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _clear_old_logs(self) -> None:
        days = self.log_retention_days.value()
        if QMessageBox.question(
            self,
            "ล้าง Log เก่า",
            f"ลบเฉพาะไฟล์ Log ที่เก่ากว่า {days} วันหรือไม่?\n\n"
            "ไฟล์ Log ที่โปรแกรมกำลังเขียนจะไม่ถูกลบ",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        root = RUNTIME_SETTINGS.log_dir.expanduser().resolve(strict=False)
        cutoff = datetime.now().timestamp() - (days * 86_400)
        active = self._active_log_paths()
        deleted = 0
        if root.is_dir():
            for candidate in root.iterdir():
                name = candidate.name.casefold()
                if (
                    not candidate.is_file()
                    or candidate.resolve(strict=False) in active
                    or (".log" not in name and ".jsonl" not in name)
                ):
                    continue
                try:
                    if candidate.stat().st_mtime < cutoff:
                        candidate.unlink()
                        deleted += 1
                except OSError:
                    log.warning("could not delete old log %s", candidate)
        QMessageBox.information(self, "ล้าง Log แล้ว", f"ลบ Log เก่า {deleted} ไฟล์")

    def _clear_runtime_cache(self) -> None:
        if QMessageBox.question(
            self,
            "ล้างไฟล์ชั่วคราว",
            "ลบเฉพาะไฟล์ .tmp, .cache และ .part ในโฟลเดอร์ runtime-cache หรือไม่?\n\n"
            "Database, ประวัติ, Billing, Excel และ Log จะไม่ถูกลบ",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        roots = {
            (RUNTIME_SETTINGS.app_home / "runtime-cache").expanduser().resolve(strict=False),
            Path(get_db_path()).expanduser().resolve(strict=False).parent / "runtime-cache",
        }
        deleted = 0
        for root in roots:
            if not root.is_dir():
                continue
            for candidate in root.rglob("*"):
                if not candidate.is_file() or candidate.suffix.casefold() not in {
                    ".tmp", ".cache", ".part"
                }:
                    continue
                try:
                    candidate.unlink()
                    deleted += 1
                except OSError:
                    log.warning("could not delete runtime cache %s", candidate)
        QMessageBox.information(
            self,
            "ล้างไฟล์ชั่วคราวแล้ว",
            f"ลบไฟล์ชั่วคราว {deleted} ไฟล์",
        )

    def _operation_access_granted(self) -> bool:
        """V5 uses explicit confirmations instead of a Settings password."""
        if getattr(self, "_v5_embed_mode", False):
            return True
        return self._ask_password()

    def _confirm_destructive(self, title: str, message: str) -> bool:
        first = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if first != QMessageBox.StandardButton.Yes:
            return False
        if not getattr(self, "_v5_embed_mode", False):
            return True
        second = QMessageBox.question(
            self,
            "ยืนยันครั้งสุดท้าย",
            "ระบบจะสำรองข้อมูลก่อนดำเนินการ\n\nยืนยันว่าต้องการทำรายการนี้จริงหรือไม่?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return second == QMessageBox.StandardButton.Yes

    def _automatic_database_backup(self, action_slug: str) -> Path | None:
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = active.parent / "backups" / f"{active.stem}-before-{action_slug}-{stamp}.db"
        try:
            backup_database(active, destination)
        except Exception as error:
            log.exception("automatic database backup failed before %s", action_slug)
            QMessageBox.warning(
                self,
                "หยุดรายการเพื่อป้องกันข้อมูล",
                f"สำรอง Database ไม่สำเร็จ จึงยังไม่ได้เปลี่ยนหรือลบข้อมูล\n\n{error}",
            )
            return None
        return destination

    def _reset(self):
        if not self._operation_access_granted():
            return
        if not self._confirm_destructive(
            "ยืนยันล้างข้อมูลการใช้งาน",
            "ลบประวัติการใช้งาน รายงาน Billing และ Log การตั้งค่าใน Database "
            "ทั้งหมดถาวร?\n\n"
            "การตั้งค่าเครื่องพิมพ์ ราคา Parser Registration และหน้า Wizard "
            "จะยังคงอยู่",
        ):
            return
        backup_path = self._automatic_database_backup("reset-usage")
        if backup_path is None:
            return
        reset_db()
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(
            self,
            "ล้างข้อมูลแล้ว",
            "ลบประวัติการใช้งาน รายงาน Billing และ Log การตั้งค่าใน Database "
            "เรียบร้อย\n"
            "การตั้งค่าเครื่องพิมพ์ ราคา Parser Registration และหน้า Wizard "
            "ยังคงอยู่\n\n"
            f"ไฟล์สำรอง: {backup_path}",
        )

    def _factory_reset(self):
        """Clear all V5 state so the next application launch opens Setup Wizard."""
        if not self._operation_access_granted():
            return
        message = (
            "ลบเครื่องพิมพ์ ราคา รอบบิล ประวัติการใช้งาน และ Billing Audit ทั้งหมดถาวร?\n\n"
            "เมื่อเปิดโปรแกรมใหม่ ระบบจะแสดง Setup Wizard อีกครั้ง"
        )
        if not self._confirm_destructive("ยืนยันเริ่มตั้งค่าใหม่", message):
            return
        backup_path = self._automatic_database_backup("factory-reset")
        if backup_path is None:
            return
        from database import factory_reset_v5

        factory_reset_v5()
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(
            self,
            "เริ่มตั้งค่าใหม่แล้ว",
            "ล้างข้อมูลและการตั้งค่าเรียบร้อย\n"
            "กรุณาปิดแล้วเปิดโปรแกรมใหม่เพื่อเข้าสู่ Setup Wizard\n\n"
            f"ไฟล์สำรอง: {backup_path}",
        )

    def _reset_parser(self):
        """ลบไฟล์ Parser Profile ทั้งหมด — เหมือนเปิดโปรแกรมครั้งแรก"""
        if not self._operation_access_granted():
            return
        if not self._confirm_destructive(
            "ยืนยันรีเซท Parser",
            "ลบ Parser Profile ทั้งหมดหรือไม่?\n\nระบบจะสำรอง Profile เดิมก่อนลบ",
        ):
            return
        from tools.check_parser import PROFILES_DIR
        parser_files = list(PROFILES_DIR.glob("profile_*.json"))
        backup_dir: Path | None = None
        if parser_files:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_dir = PROFILES_DIR.parent / "backups" / f"parser-{stamp}"
            try:
                backup_dir.mkdir(parents=True, exist_ok=False)
                for parser_file in parser_files:
                    destination = backup_dir / parser_file.name
                    destination.write_bytes(parser_file.read_bytes())
            except OSError as error:
                log.exception("parser profile backup failed")
                QMessageBox.warning(
                    self,
                    "หยุดรายการเพื่อป้องกันข้อมูล",
                    f"สำรอง Parser Profile ไม่สำเร็จ จึงยังไม่ได้ลบข้อมูล\n\n{error}",
                )
                return
        deleted = 0
        for pf in parser_files:
            try:
                pf.unlink()
                deleted += 1
            except OSError:
                pass
        self._refresh_parser_dropdowns()
        QMessageBox.information(
            self, "รีเซทแล้ว",
            f"ลบ Parser Profile {deleted} รายการเรียบร้อย"
            + (f"\n\nไฟล์สำรอง: {backup_dir}" if backup_dir else "")
        )

    def _reset_settings(self):
        """รีเซทการตั้งค่า (ชื่อเครื่อง, ราคา, วันตัดรอบ) เป็นค่าเริ่มต้น"""
        if not self._operation_access_granted():
            return
        if not self._confirm_destructive(
            "ยืนยันรีเซทการตั้งค่า",
            "รีเซทชื่อเครื่อง ราคา และวันตัดรอบเป็นค่าเริ่มต้นหรือไม่?\n\n"
            "ข้อมูลที่บันทึกไว้จะถูกอัปเดตเป็นค่าเริ่มต้น",
        ):
            return
        backup_path = self._automatic_database_backup("reset-settings")
        if backup_path is None:
            return
        reset_settings_to_default()
        self.changed.emit()
        self._refresh_log()
        self._refresh_ui()
        QMessageBox.information(
            self,
            "รีเซทแล้ว",
            f"รีเซทการตั้งค่าเรียบร้อย\n\nไฟล์สำรอง: {backup_path}",
        )

    def _open_issue_log(self):
        """รวบรวม settings + 4 ไฟล์ .txt ล่าสุด + parsers + screenshots ทุกหน้า → ZIP ลง Downloads"""
        import sys, shutil, tempfile, zipfile, sqlite3
        from PyQt6.QtWidgets import QApplication

        if QMessageBox.question(
            self, "สร้าง Issue Log",
            "โปรแกรมจะรวบรวมข้อมูลต่อไปนี้เป็นไฟล์ ZIP เก็บใน Downloads:\n\n"
            "• การตั้งค่าและเวอร์ชันโปรแกรม\n"
            "• ไฟล์ .txt 4 ไฟล์ล่าสุดที่นำเข้า\n"
            "• Parser ที่ใช้ทุกตัว\n"
            "• Snapshot ของทุกหน้าจอ\n\n"
            "ดำเนินการต่อ?"
        ) != QMessageBox.StandardButton.Yes:
            return

        main_win = self.window()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        zip_name = f"Issue log -Komi report v{APP_VER} {ts}.zip"
        downloads = Path.home() / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        zip_path = downloads / zip_name

        try:
            with tempfile.TemporaryDirectory() as tmp_str:
                tmp = Path(tmp_str)

                # 1) info.txt — version + settings (mask password)
                lines = [
                    f"App        : {APP_TITLE}",
                    f"Version    : v{APP_VER}",
                    f"Generated  : {datetime.now().isoformat(timespec='seconds')}",
                    f"Platform   : {sys.platform}",
                    f"Python     : {sys.version.split()[0]}",
                    "",
                    "=== Settings ===",
                ]
                try:
                    with sqlite3.connect(get_db_path()) as conn:
                        rows = conn.execute(
                            "SELECT key, value FROM settings ORDER BY key"
                        ).fetchall()
                    for k, v in rows:
                        if "password" in k.lower():
                            v = "***REDACTED***"
                        lines.append(f"{k} = {v}")
                except Exception as e:
                    lines.append(f"(read settings failed: {e})")
                (tmp / "info.txt").write_text("\n".join(lines), encoding="utf-8")

                # 2) recent_txt/ — 4 ไฟล์ .txt ล่าสุดจาก imported folder
                recent_dir = tmp / "recent_txt"
                recent_dir.mkdir()
                try:
                    from database import get_activity_log
                    acts = get_activity_log(4)
                    custom_base = get_cfg("imported_path", "")
                    base = Path(custom_base) if custom_base else Path(get_db_path()).parent / "imported"
                    for act in acts:
                        slot = act.get("slot", 0)
                        fname = sanitize_filename(Path(act.get("file_name", "")).name)
                        card_name = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
                        src = base / sanitize_filename(card_name) / fname
                        if src.exists():
                            shutil.copy2(src, recent_dir / fname)
                        else:
                            (recent_dir / f"_missing_{fname}.txt").write_text(
                                f"original path: {src}\n(ไฟล์สำรองหาย)", encoding="utf-8"
                            )
                except Exception as e:
                    (recent_dir / "_error.txt").write_text(f"error: {e}", encoding="utf-8")

                # 3) parsers/ — รวมทุก parser profile
                parsers_dir = tmp / "parsers"
                parsers_dir.mkdir()
                try:
                    profiles = load_profiles()
                    (parsers_dir / "all_profiles.json").write_text(
                        json.dumps(profiles, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    from tools.check_parser import PROFILES_DIR as _PROF_DIR
                    if _PROF_DIR.exists():
                        for f in _PROF_DIR.glob("profile_*.json"):
                            shutil.copy2(f, parsers_dir / f.name)
                except Exception as e:
                    (parsers_dir / "_error.txt").write_text(f"error: {e}", encoding="utf-8")

                # 4) screenshots/ — grab ทุกหน้าใน stack (ไม่ต้องเปลี่ยนหน้าที่กำลังแสดง)
                ss_dir = tmp / "screenshots"
                ss_dir.mkdir()
                try:
                    stack = getattr(main_win, "stack", None)
                    page_names = ["overview", "import", "history", "settings", "manual"]
                    if stack is not None and stack.count() > 0:
                        for i in range(stack.count()):
                            w = stack.widget(i)
                            # ถ้าหน้านี้ห่อด้วย QScrollArea → grab widget ข้างใน (เห็นเต็มหน้า)
                            inner = w.widget() if isinstance(w, QScrollArea) else w
                            inner.adjustSize()
                            QApplication.processEvents()
                            pix = inner.grab()
                            name = page_names[i] if i < len(page_names) else f"page_{i}"
                            pix.save(str(ss_dir / f"{i+1}_{name}.png"), "PNG")
                    else:
                        main_win.grab().save(str(ss_dir / "1_main.png"), "PNG")
                except Exception as e:
                    (ss_dir / "_error.txt").write_text(f"error: {e}", encoding="utf-8")

                # 5) zip ทั้งหมด
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root_dir, _, files in os.walk(tmp):
                        for f in files:
                            full = Path(root_dir) / f
                            zf.write(full, arcname=str(full.relative_to(tmp)))

            QMessageBox.information(
                self, "สร้าง Issue Log สำเร็จ",
                f"บันทึกไว้ที่:\n{zip_path}"
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(downloads)))
        except Exception as e:
            log.exception("issue log failed")
            QMessageBox.critical(
                self, "สร้าง Issue Log ไม่ได้",
                f"{type(e).__name__}: {e}"
            )

    def _refresh_ui(self):
        """[V4.5] รีเฟรช UI fields — ลบ dead branches (type_dropdowns/multiplier_spins ว่างเสมอ)"""
        for i, inp in enumerate(self.name_inp):
            inp.setText(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))

        for slot in range(3):
            if slot in self.parser_dropdowns:
                parser_combo = self.parser_dropdowns[slot]
                current_parser = get_cfg(f"parser_{slot}", "")
                if current_parser:
                    try:
                        idx_p = parser_combo.findData(int(current_parser))
                    except (ValueError, TypeError):
                        idx_p = -1
                    if idx_p >= 0:
                        parser_combo.setCurrentIndex(idx_p)
        
        # รีเฟรช Price List
        for slot in range(3):
            for key, spin in self.price_spins[slot].items():
                spin.setValue(get_price(key, slot))
        
        # รีเฟรช วันตัดรอบบิล
        self.spin_day.setValue(get_billing_day())
        # รีเฟรช % กระดาษเสีย
        if hasattr(self, 'spin_waste'):
            self.spin_waste.setValue(get_waste_paper_pct())
        # รีเฟรช imported path
        if hasattr(self, 'imported_lbl'):
            default_imported = str(Path(get_cfg("db_path", str(DB_PATH))).parent / "imported")
            self.imported_lbl.setText(get_cfg("imported_path", default_imported))
        if hasattr(self, 'db_lbl'):
            self._refresh_db_path_label()
        if hasattr(self, 'close_to_tray'):
            self.close_to_tray.setChecked(get_cfg("close_to_tray", "1") != "0")
        if hasattr(self, 'log_retention_days'):
            try:
                days = int(get_cfg("log_retention_days", "30") or "30")
            except ValueError:
                days = 30
            self.log_retention_days.setValue(max(1, min(365, days)))
        if hasattr(self, 'runtime_info'):
            self._refresh_runtime_info()


# ══════════════════════════════════════════════════════════
# PAGE: MANUAL  —  คู่มือการใช้งาน
# ══════════════════════════════════════════════════════════
class PageManual(QWidget):
    """
    คู่มือใช้งาน KOMI Report V5.2 สำหรับผู้ใช้ทั่วไปและเจ้าหน้าที่ดูแลระบบ
    โดยยึดพฤติกรรมของหน้าจอจริงเป็นหลัก
    """
    FONT_SCALE = 0.80

    @classmethod
    def _manual_point_size(cls, size: int) -> int:
        """ลด typography เฉพาะหน้าคู่มือ โดยไม่กระทบหน้าอื่นของโปรแกรม"""
        return max(8, round(size * cls.FONT_SCALE))

    @classmethod
    def _manual_font(cls, size: int, bold: bool = False) -> QFont:
        return fnt(cls._manual_point_size(size), bold=bold)

    def __init__(self, parent=None):
        super().__init__(parent)
        # องค์ประกอบที่ไม่ได้กำหนดฟอนต์เฉพาะ จะ inherit ขนาดคู่มือที่ลดแล้ว
        self.setFont(self._manual_font(F_LG))
        self._build()

    # ── helper: สร้าง section header ────────────────────────
    def _sec(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(self._manual_font(F_2XL))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color:{C_ACCENT}; font-weight:bold; padding-bottom:4px;"
            f"border-bottom: 2px solid {C_ACCENT}; margin-top:18px; margin-bottom:6px;"
        )
        return lbl

    # ── helper: สร้าง step badge + ข้อความ ──────────────────
    def _step(self, num: int, text: str) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background:transparent; border:0;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(10)

        badge = QLabel(str(num))
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:{C_ACCENT}; color:white; border-radius:15px;"
            f"font-weight:bold; font-size:{self._manual_point_size(F_LG)}pt;"
        )

        desc = QLabel(text)
        desc.setFont(self._manual_font(F_XL))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:0;")

        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(desc, 1)
        return row

    # ── helper: สร้าง card พื้นขาว ────────────────────────
    def _card(self, title: str, body_widgets: list) -> QFrame:
        card = QFrame()
        card.setObjectName("manual_document_block")
        card.setStyleSheet(
            "QFrame#manual_document_block { background:#FFFFFF; border:0; "
            "border-radius:0; padding:0; }"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 8, 8, 12)
        vl.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setFont(self._manual_font(F_2XL))
            t.setWordWrap(True)
            t.setStyleSheet(
                f"color:{C_TEXT}; font-weight:bold; background:transparent; "
                f"border:0; border-bottom:1px solid {C_ACCENT}; padding:2px 0 8px 0;"
            )
            vl.addWidget(t)
        for w in body_widgets:
            vl.addWidget(w)
        return card

    # ── helper: ข้อความธรรมดา ────────────────────────────
    def _txt(self, text: str, bold=False, color=None) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(self._manual_font(F_XL))
        lbl.setWordWrap(True)
        c = color or C_TEXT
        lbl.setStyleSheet(
            f"color:{c}; background:transparent; border:0; "
            f"{'font-weight:bold;' if bold else ''}"
        )
        return lbl

    # ── helper: ข้อความหมายเหตุ/tip (สีรอง) ─────────────
    def _tip(self, text: str) -> QLabel:
        lbl = QLabel(f"💡  {text}")
        lbl.setFont(self._manual_font(F_LG))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color:{C_TEXT2}; background:#EEF6FF; border:0; "
            f"border-left:4px solid {C_ACCENT}; padding:8px 12px;"
        )
        return lbl

    def _guide_screenshot(self, index: int, caption: str, *, english=False) -> QWidget:
        filename = f"customer-guide/assets-v5.2/{index:02d}-"
        names = {
            1: "setup-company.png",
            2: "setup-printers.png",
            3: "setup-pricing.png",
            4: "setup-review.png",
            5: "overview.png",
            6: "devices.png",
            7: "reports-overview.png",
            8: "reports-usage.png",
            9: "reports-legacy.png",
            10: "settings.png",
            11: "advanced-lan.png",
            12: "advanced-tools.png",
            13: "manual.png",
        }
        image_path = self._manual_asset(filename + names[index])
        if index == 11:
            image_path = self._manual_asset('customer-guide/assets-v5.2.12-source/network-activity.png')
        pixmap = (
            QPixmap(str(image_path))
            if self._manual_asset_available(image_path)
            else QPixmap()
        )

        block = QWidget()
        block.setStyleSheet("background:#FFFFFF; border:0;")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(8, 6, 8, 16)
        layout.setSpacing(5)
        image = _ManualDocumentImage(pixmap)
        image.setObjectName(
            f"manual_doc_image_{'en_' if english else ''}{index:02d}"
        )
        if pixmap.isNull():
            image.setText(
                "Screenshot is not available" if english else "ไม่พบภาพประกอบคู่มือ"
            )
        layout.addWidget(image)
        label = QLabel(caption)
        label.setFont(self._manual_font(F_SM))
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"color:{C_TEXT2}; background:transparent; border:0; "
            "font-style:italic; padding:2px 8px;"
        )
        layout.addWidget(label)
        return block

    def _insert_customer_guide_screenshots(self) -> None:
        groups = (
            ((1, 2, 3, 4), ("ตั้งค่าบริษัทและฐานข้อมูล", "ค้นหาและเลือกเครื่องพิมพ์", "ตั้งราคาและรอบบิล", "ตรวจสอบก่อนเริ่มใช้งาน")),
            ((5, 6), ("ภาพรวมการใช้งาน", "ข้อมูลรายเครื่อง")),
            ((7, 8, 9), ("รายงานภาพรวม", "รายงาน Usage", "รายงาน Legacy")),
            ((10, 11, 12), ("การตั้งค่าหลัก", "สถานะการตั้งค่าเครือข่าย · ข้อมูลจำลอง", "เครื่องมือขั้นสูงและ Parser Mapping")),
            ((13,), ("คู่มือฉบับย่อในโปรแกรม",)),
        )
        english_captions = (
            ("Company and Database setup", "Discover and select printers", "Prices and billing cycle", "Review before first use"),
            ("Operational overview", "Per-device information"),
            ("Report overview", "Usage report", "Legacy report"),
            ("Main Settings", "Network activity · synthetic example", "Advanced tools and Parser Mapping"),
            ("In-app quick guide",),
        )
        for sections, captions, english in (
            (self._thai_manual_sections, tuple(group[1] for group in groups), False),
            (self._english_manual_sections, english_captions, True),
        ):
            for section, (indexes, _thai_captions), section_captions in zip(
                sections,
                groups,
                captions,
                strict=True,
            ):
                layout = section.layout()
                insert_at = max(1, layout.count() - 1)
                for index, caption in zip(indexes, section_captions, strict=True):
                    layout.insertWidget(
                        insert_at,
                        self._guide_screenshot(index, caption, english=english),
                    )
                    insert_at += 1

    @staticmethod
    def _manual_asset(filename: str) -> Path:
        candidates = (
            Path(__file__).resolve().parent / "docs" / filename,
            Path(__file__).resolve().parent.parent / "docs" / filename,
        )
        return next((path for path in candidates if path.exists()), candidates[-1])

    @staticmethod
    def _manual_asset_available(path: Path) -> bool:
        """Reject unresolved OneDrive placeholders before Qt blocks on them."""
        try:
            flags = getattr(path.stat(), "st_flags", 0)
        except OSError:
            return False
        return path.is_file() and not (flags & getattr(stat, "SF_DATALESS", 0))

    def _diagram_card(self, title: str, summary: str, image_name: str, html_name: str) -> QFrame:
        image_path = self._manual_asset(image_name)
        html_path = self._manual_asset(html_name)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumWidth(0)
        preview.setMinimumHeight(280)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview.setStyleSheet(f"background:#F7F8FA;border:1px solid {C_BORDER};padding:8px;")
        pixmap = QPixmap(str(image_path)) if self._manual_asset_available(image_path) else QPixmap()
        if pixmap.isNull():
            preview.setText("ไม่พบภาพคู่มือ")
        else:
            preview.setPixmap(
                pixmap.scaled(
                    560,
                    390,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        open_path = html_path if self._manual_asset_available(html_path) else image_path
        open_button = QPushButton("เปิด Diagram แบบเต็ม")
        open_button.setEnabled(self._manual_asset_available(open_path))
        open_button.setStyleSheet(
            f"QPushButton {{ background:{C_ACCENT};color:white;border:0;border-radius:6px;padding:9px 14px;"
            "font-weight:bold; } QPushButton:disabled { background:#AAB4BF; }"
        )
        open_button.clicked.connect(
            lambda _checked=False, path=open_path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        )
        if html_name == "sync-rule-flowchart.html":
            self.manual_sync_button = open_button
        else:
            self.manual_storage_button = open_button
        return self._card(title, [self._txt(summary), preview, open_button])

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(10)

        # ── Header ──────────────────────────────────────────
        header = QHBoxLayout()
        self.manual_title = QLabel("📖  คู่มือการใช้งาน")
        self.manual_title.setFont(self._manual_font(F_2XL))
        self.manual_title.setStyleSheet(f"color:{C_TEXT}; font-weight:bold;")
        self.manual_subtitle = QLabel("KOMI Report V5.2 — ติดตั้ง อ่านมิเตอร์ และออกรายงาน")
        self.manual_subtitle.setFont(self._manual_font(F_LG))
        self.manual_subtitle.setStyleSheet(f"color:{C_TEXT2};")
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(self.manual_title)
        title_col.addWidget(self.manual_subtitle)
        header.addLayout(title_col)
        header.addStretch()
        self.manual_toc_combo = QComboBox()
        self.manual_toc_combo.setObjectName("manual_toc_combo")
        self.manual_toc_combo.setMinimumWidth(210)
        self.manual_toc_combo.setFont(self._manual_font(F_LG))
        self.manual_toc_combo.setAccessibleName("สารบัญหน้านี้")
        self.manual_toc_combo.currentIndexChanged.connect(
            self._scroll_to_manual_section
        )
        header.addWidget(self.manual_toc_combo)
        outer.addLayout(header)
        outer.addSpacing(2)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(18)

        self.manual_scroll = QScrollArea()
        self.manual_scroll.setObjectName("manual_single_page_scroll")
        self.manual_scroll.setWidgetResizable(True)
        self.manual_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.manual_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.manual_scroll.setStyleSheet(
            "QScrollArea#manual_single_page_scroll { background:transparent; border:0; }"
        )

        self.manual_content = QWidget()
        self.manual_content.setObjectName("manual_word_content")
        self.manual_content.setStyleSheet(
            "QWidget#manual_word_content { background:#FFFFFF; }"
        )
        content_layout = QVBoxLayout(self.manual_content)
        content_layout.setContentsMargins(12, 0, 12, 32)
        content_layout.setSpacing(30)

        self._thai_manual_sections = [
            self._tab_firstrun(),
            self._tab_workflow(),
            self._tab_history(),
            self._tab_settings(),
            self._tab_v5_system(),
        ]
        self._english_manual_sections = self._build_english_manual_sections()
        self._insert_customer_guide_screenshots()
        self._insert_updated_guide()
        for section in (*self._thai_manual_sections, *self._english_manual_sections):
            section.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Maximum,
            )
            content_layout.addWidget(section)
        content_layout.addStretch()
        self.manual_scroll.setWidget(self.manual_content)
        self.manual_scroll.verticalScrollBar().valueChanged.connect(
            self._update_manual_toc_highlight
        )
        body.addWidget(self.manual_scroll, 1)

        self.manual_toc_frame = QFrame()
        self.manual_toc_frame.setObjectName("manual_toc_frame")
        self.manual_toc_frame.setFixedWidth(224)
        self.manual_toc_frame.setStyleSheet(
            f"QFrame#manual_toc_frame {{ background-color:{C_CARD}; "
            f"border:1px solid {C_BORDER}; border-radius:10px; }}"
        )
        toc_layout = QVBoxLayout(self.manual_toc_frame)
        toc_layout.setContentsMargins(12, 14, 12, 14)
        toc_layout.setSpacing(5)
        self.manual_toc_title = QLabel("สารบัญหน้านี้")
        self.manual_toc_title.setFont(self._manual_font(F_LG, bold=True))
        self.manual_toc_title.setStyleSheet(f"color:{C_TEXT};padding:4px 6px 8px 6px;")
        toc_layout.addWidget(self.manual_toc_title)
        self.manual_toc_buttons: list[QPushButton] = []
        for index in range(5):
            button = QPushButton()
            button.setFont(self._manual_font(F_LG))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(self._manual_toc_button_style(active=False))
            button.clicked.connect(
                lambda _checked=False, section_index=index: self._scroll_to_manual_section(
                    section_index
                )
            )
            self.manual_toc_buttons.append(button)
            toc_layout.addWidget(button)
        toc_layout.addStretch()
        body.addWidget(self.manual_toc_frame, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(body, 1)

        self._apply_i18n_visibility(get_language())
        self._update_manual_responsive_layout(self.width())

    def _insert_updated_guide(self):
        for sections, english in ((self._thai_manual_sections, False), (self._english_manual_sections, True)):
            guide = self._manual_asset('customer-guide/KOMI_Report_5.2.12_Source_Guide.pdf')
            button = QPushButton('Open updated illustrated guide (Thai PDF)' if english else 'เปิดคู่มือฉบับปรับปรุงพร้อมภาพ (PDF)')
            button.setEnabled(self._manual_asset_available(guide))
            button.clicked.connect(lambda _=False, path=guide: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            sections[0].layout().insertWidget(1, self._card('Updated guide' if english else 'คู่มือหน้าจอที่ปรับปรุง', [
                self._txt('Network settings, shared Slot baselines, revised reports and Archive. The guide identifies features awaiting verified member connections.' if english else
                    'รวมการตั้งค่าเครือข่าย ฐาน Slot รายงานฉบับแก้ไข และ Archive คู่มือระบุส่วนที่ยังรอเชื่อมต่อสมาชิกที่ยืนยันสิทธิ์ไว้ด้วย'), button]))
            sections[3].layout().insertWidget(1, self._card('Network settings and shared changes' if english else 'การตั้งค่าเครือข่ายและค่าร่วมกัน', [
                self._txt('Settings > Advanced > Network settings shows actual work and durable receipt queues. A completed send is not proof that the peer saved it.' if english else
                    'ตั้งค่า > ขั้นสูง > การตั้งค่าเครือข่าย แสดงงานที่กำลังทำและคิวรอยืนยันรับ การส่งข้อความสำเร็จยังไม่ใช่หลักฐานว่าปลายทางบันทึกแล้ว'),
                self._txt('Verified descendants apply after active reads finish. Conflicting edits remain available in shared settings history for review. Discovery alone does not enroll a computer.' if english else
                    'ค่าที่รับมาและต่อจากประวัติเดิมจะใช้เมื่ออ่านมิเตอร์เสร็จ หากแก้ชนกันให้ตรวจเลือกในประวัติการตั้งค่าร่วม การค้นพบใน LAN อย่างเดียวยังไม่ถือว่าเข้าร่วมระบบ'),
                self._txt('Each computer keeps its own identity and shares the same three printer Slots. Replacing a used printer starts from its reviewed meter baseline.' if english else
                    'แต่ละคอมมีตัวตนของตนเองและใช้ Slot เครื่องพิมพ์สามช่องชุดเดียวกัน เมื่อเปลี่ยนเป็นเครื่องมือสอง ยอดจะนับต่อจากฐานที่ตรวจยืนยันแล้ว')]))
            sections[2].layout().insertWidget(1, self._card('Missing history and revised reports' if english else 'ช่วงขาดข้อมูลและรายงานฉบับแก้ไข', [
                self._txt('A 301-page gap over two entirely missing days is shown as an estimated 150.5 pages per day. The graph never determines invoice amounts.' if english else
                    'ช่วงขาด 301 หน้าในสองวันที่ไม่มีข้อมูลทั้งวัน กราฟแสดงเฉลี่ยประมาณการวันละ 150.5 หน้า ไม่ใช้ค่าเฉลี่ยกราฟคิดเงิน'),
                self._txt('Review Web evidence before confirming revised allocation. Originals remain intact and delivery awaits verified receipts. Old user/Raw details are not rewritten by this action.' if english else
                    'ตรวจหลักฐาน Web ก่อนยืนยันฉบับแก้ไขการแบ่งยอด ระบบเก็บต้นฉบับและคิวรอรับไว้ การยืนยันนี้ไม่เขียนทับรายละเอียดผู้ใช้หรือ Raw เก่า'),
                self._txt('Details older than twelve months can be archived. Monthly summaries remain available; older files open only when requested.' if english else
                    'รายละเอียดเกิน 12 เดือนเก็บเป็น Archive ได้ สรุปรายเดือนยังเรียกดูได้ และเปิดไฟล์เก่าเฉพาะเมื่อขอดูรายละเอียด')]))

    def _apply_i18n_visibility(self, language: str) -> None:
        self._manual_language = language
        english = language == "en"
        for section in self._thai_manual_sections:
            section.setVisible(not english)
        for section in self._english_manual_sections:
            section.setVisible(english)
        self.manual_title.setText("📖  User manual" if english else "📖  คู่มือการใช้งาน")
        self.manual_subtitle.setText(
            "KOMI Report V5.2 — setup, meters and reports"
            if english
            else "KOMI Report V5.2 — ติดตั้ง อ่านมิเตอร์ และออกรายงาน"
        )
        self.manual_toc_title.setText("On this page" if english else "สารบัญหน้านี้")
        self.manual_toc_combo.setAccessibleName(
            "On this page" if english else "สารบัญหน้านี้"
        )
        labels = (
            ("Getting started", "Daily workflow", "Reports", "Settings", "System V5.2")
            if english
            else ("เริ่มต้นใช้งาน", "วิธีทำงาน", "รายงาน", "ตั้งค่า", "ระบบ V5.2")
        )
        self.manual_toc_combo.blockSignals(True)
        self.manual_toc_combo.clear()
        self.manual_toc_combo.addItems(labels)
        self.manual_toc_combo.blockSignals(False)
        for button, label in zip(self.manual_toc_buttons, labels, strict=True):
            button.setText(label)
            button.setAccessibleName(label)
        self.manual_scroll.verticalScrollBar().setValue(0)
        self._set_manual_toc_active(0)

    def _active_manual_sections(self) -> list[QWidget]:
        return (
            self._english_manual_sections
            if self._manual_language == ENGLISH
            else self._thai_manual_sections
        )

    def _scroll_to_manual_section(self, index: int) -> None:
        sections = self._active_manual_sections()
        if not (0 <= index < len(sections)):
            return
        section = sections[index]
        top = section.mapTo(self.manual_content, QPoint(0, 0)).y()
        self.manual_scroll.verticalScrollBar().setValue(max(0, top - 8))
        self._set_manual_toc_active(index)

    def _set_manual_toc_active(self, index: int) -> None:
        for button_index, button in enumerate(self.manual_toc_buttons):
            active = button_index == index
            button.setChecked(active)
            button.setStyleSheet(self._manual_toc_button_style(active=active))
        self.manual_toc_combo.blockSignals(True)
        self.manual_toc_combo.setCurrentIndex(index)
        self.manual_toc_combo.blockSignals(False)

    @staticmethod
    def _manual_toc_button_style(*, active: bool) -> str:
        if active:
            return (
                f"text-align:left; color:{C_ACCENT}; background-color:#EAF3FB; "
                f"border:1px solid {C_ACCENT}; border-radius:6px; padding:9px 8px; "
                "font-weight:bold;"
            )
        return (
            f"text-align:left; color:{C_TEXT2}; background-color:transparent; "
            "border:1px solid transparent; border-radius:6px; padding:9px 8px;"
        )

    def _update_manual_toc_highlight(self, value: int) -> None:
        sections = self._active_manual_sections()
        if not sections:
            return
        probe = value + 72
        active = 0
        for index, section in enumerate(sections):
            if section.mapTo(self.manual_content, QPoint(0, 0)).y() <= probe:
                active = index
            else:
                break
        self._set_manual_toc_active(active)

    def _update_manual_responsive_layout(self, width: int) -> None:
        show_right_toc = width >= 980
        self.manual_toc_frame.setVisible(show_right_toc)
        self.manual_toc_combo.setVisible(not show_right_toc)

    def _english_manual_section(
        self,
        title: str,
        cards: list[tuple[str, list[QWidget]]],
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(14)
        layout.addWidget(self._sec(title))
        for card_title, widgets in cards:
            layout.addWidget(self._card(card_title, widgets))
        layout.addStretch()
        return page

    def _build_english_manual_sections(self) -> list[QWidget]:
        return [
            self._english_manual_section("Getting started", [
                ("First computer setup", [
                    self._step(1, "Enter the company name. Start date and Version are filled automatically."),
                    self._step(2, "Keep the Database path, select Browse, or use Import for an existing database."),
                    self._step(3, "Discover or add printers manually, then select and verify up to three devices."),
                    self._step(4, "Set A4/A3 Color and B&W prices, billing-cycle end day and waste-paper discount."),
                    self._step(5, "Review and save. Online Registration completes before the main window opens."),
                    self._tip("If Online Registration cannot connect, the Wizard offers the Offline License flow."),
                ]),
                ("Additional computer setup", [
                    self._txt("An additional desktop can review the company configuration offered by an authorized computer on the same LAN.", bold=True),
                    self._txt("The initial setup copy is separate from continuous shared work. Each computer retains its own registration identity."),
                ]),
            ]),
            self._english_manual_section("Daily workflow", [
                ("Reading printer data", [
                    self._step(1, "Read SNMP identity and Total Meter first."),
                    self._step(2, "Select the compatible Web Connection method automatically and request an Administrator password only when required."),
                    self._step(3, "Store daily Print and Copy data together with the original Legacy counter labels."),
                    self._step(4, "Close the daily record and calculate confirmed usage and cost."),
                    self._tip("A dash means the printer did not provide the value; it does not mean zero."),
                ]),
                ("Device information", [
                    self._txt("Each device card shows model, serial number, Total Meter, available toner, paper-tray status and raw counters."),
                    self._txt("Closing the window may keep KOMI Report running in System Tray. Choose Exit to stop the application completely."),
                ]),
            ]),
            self._english_manual_section("Reports", [
                ("Normalized reports", [
                    self._txt("Overview, Users, Printers and Usage keep Print and Copy separate.", bold=True),
                    self._txt("The opening Meter row is a reference baseline only and is never included in usage or cost."),
                    self._txt("The waste-paper checkbox switches net/gross cost without changing page counts."),
                ]),
                ("Legacy and Excel", [
                    self._txt("Legacy preserves exact printer counter labels such as A5, Large Size or FAX instead of forcing them into A3/A4."),
                    self._txt("Excel exports six sheets: three normalized views and three Legacy views for printer, user and daily data."),
                ]),
            ]),
            self._english_manual_section("Settings", [
                ("Everyday settings", [
                    self._txt("Manage printers and prices, billing, automatic readings and Registration status from the main Settings page."),
                ]),
                ("Advanced Settings", [
                    self._txt("Advanced Settings expands on the same page. It includes Database path, backup/restore/integrity, Auto-start, logs, maintenance, LAN Web Report and Parser Mapping.", bold=True),
                    self._tip("Back up the Database before Restore, changing its path or starting a new Database."),
                ]),
                ("LAN Web Report", [
                    self._txt("LAN Web Report starts automatically. Read-only access may be allowed without a password; staff and edit functions remain protected."),
                ]),
            ]),
            self._english_manual_section("System V5.2", [
                ("Registration and background operation", [
                    self._step(1, "Online Registration is the normal first-run mode."),
                    self._step(2, "Status and aggregate Total Meter are scheduled approximately every six hours."),
                    self._step(3, "The Host marks a missing Desktop connection only after three days; this is not a printer-failure claim."),
                    self._step(4, "Offline License stops Registration, Status and Meter telemetry without deleting local reports."),
                ]),
                ("Computers and recovery", [
                    self._txt("Primary and Secondary desktops can run together and continue serving the same read-only Web Report on the LAN."),
                    self._txt("Back up the Database before restore, reset or moving the data path."),
                ]),
            ]),
        ]

    def _tab_v5_system(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(14)
        layout.addWidget(self._sec("การทำงานเบื้องหลังของ KOMI Report V5.2"))
        layout.addWidget(
            self._txt(
                "โปรแกรมเก็บฐานข้อมูลและรายงานไว้ในเครือข่ายลูกค้า ส่วนการลงทะเบียนส่งเฉพาะข้อมูลที่ระบุในประกาศ "
                "หัวข้อนี้อธิบายการอ่านเครื่อง การทำงานร่วมกัน และการลงทะเบียน Online/Offline"
            )
        )
        layout.addWidget(self._card("คอมพิวเตอร์ร่วมกันและ Web Report", [
            self._step(1, "คอมเครื่องแรกตั้งค่าเครื่องพิมพ์ ราคา รอบบิล และฐานข้อมูล"),
            self._step(2, "คอมเพิ่มเติมตรวจและรับชุดค่าบริษัทที่ได้รับสิทธิ์มาใช้ โดยคงตัวตนการลงทะเบียนของตนเอง"),
            self._step(3, "คอมทุกเครื่องใช้ Slot ชุดเดียวกัน Web Report แบบอ่านอย่างเดียวเปิดผ่าน LAN ได้เมื่อเครื่องที่ให้บริการยังออนไลน์"),
            self._step(4, "เมื่อปิดหน้าต่าง Agent ทำงานต่อที่ System Tray; ใช้เมนูออกจาก Agent เมื่อต้องการหยุดจริง"),
            self._tip("ก่อน Sync ให้ตรวจชื่อบริษัท รายการเครื่อง ราคา และรอบบิลบนหน้าสรุปทุกครั้ง"),
        ]))
        layout.addWidget(self._card("การลงทะเบียนและสถานะ", [
            self._step(1, "Online Registration เป็นวิธีปกติ และทำงานก่อนเปิดหน้าหลักครั้งแรก"),
            self._step(2, "เมื่อลงทะเบียนแล้ว โปรแกรมส่งสถานะโดยประมาณทุก 6 ชั่วโมง พร้อม Total Meter รวมของเครื่องที่เลือก"),
            self._step(3, "Host จะแจ้งการขาดการเชื่อมต่อเมื่อไม่ได้รับข้อมูลเกิน 3 วัน โดยไม่สรุปว่าเครื่องพิมพ์เสีย"),
            self._step(4, "กรณีไม่มี Internet ให้ส่งออก .komirequest และนำเข้า .komilicense ที่ได้รับจากผู้ดูแล"),
            self._tip("Offline License ปิดการส่ง Registration, Status และ Meter แต่ไม่ลบฐานข้อมูลหรือรายงานในเครื่อง"),
        ]))
        self._manual_diagram_cards = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._manual_diagram_cards.setSpacing(14)
        self._manual_diagram_cards.addWidget(
            self._diagram_card(
                "1. กฎการอ่านข้อมูลอัตโนมัติ",
                "ดูเส้นทาง Scheduler และการอ่านข้อมูล ตั้งแต่ SNMP, Web throttle, RAM ไปจนถึง Daily Record",
                "sync-rule-flowchart.png",
                "sync-rule-flowchart.html",
            )
        )
        self._manual_diagram_cards.addWidget(
            self._diagram_card(
                "2. การเก็บข้อมูล",
                "ดูความต่างระหว่าง RAM ชั่วคราว, JSON Daily Cache, SQLite และข้อมูลที่ History/Billing ใช้",
                "data-storage-overview.png",
                "data-storage-overview.html",
            )
        )
        layout.addLayout(self._manual_diagram_cards)
        layout.addWidget(
            self._tip(
                "Diagram เป็นไฟล์ Local ภายในโปรแกรม เปิดดูได้โดยไม่ต้องเชื่อมต่อ Internet "
                "และไม่ส่งข้อมูลเครื่องพิมพ์ออกภายนอก"
            )
        )
        layout.addStretch()
        return page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "manual_toc_frame"):
            self._update_manual_responsive_layout(event.size().width())
        if not hasattr(self, "_manual_diagram_cards"):
            return
        direction = (
            QBoxLayout.Direction.LeftToRight
            if event.size().width() >= 1160
            else QBoxLayout.Direction.TopToBottom
        )
        if self._manual_diagram_cards.direction() != direction:
            self._manual_diagram_cards.setDirection(direction)
            self.updateGeometry()

    # ══════════════════════════════════════════════════════
    # TAB 0 — ภาพรวมการทำงานของโปรแกรม
    # ══════════════════════════════════════════════════════
    def _tab_workflow(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("การใช้งานประจำวัน"))

        # ─ วงจรการทำงานหลัก ──────────────────────────────
        lay.addWidget(self._card("วงจรการอ่านข้อมูล", [
            self._txt(
                "KOMI Report V5.2 อ่านข้อมูลจากเครื่อง Konica Minolta ที่เลือกไว้สูงสุด 3 เครื่อง "
                "ตามตารางเวลา หรือสั่งอ่านทันทีจากหน้าอุปกรณ์"
            ),
            self._step(1, "ตรวจสถานะและ Total Meter ผ่าน SNMP ก่อน"),
            self._step(2, "อ่าน Web Connection ด้วยวิธีที่รุ่นนั้นรองรับโดยอัตโนมัติ และขอรหัส Administrator เฉพาะเมื่อจำเป็น"),
            self._step(3, "เก็บข้อมูลรายวัน แยก Print และ Copy พร้อมชื่อ Counter ต้นทางสำหรับ Legacy"),
            self._step(4, "ปิด Daily Record แล้วสร้างยอดใช้งานและค่าใช้จ่ายของวันนั้น"),
            self._step(5, "แสดงผลในภาพรวม รายงาน และ Excel โดยใช้ช่วงวันที่เดียวกัน"),
        ]))

        # ─ โครงสร้างข้อมูล ───────────────────────────────
        lay.addWidget(self._card("ข้อมูลที่เห็นในหน้าอุปกรณ์", [
            self._txt("• Model, Serial Number และ Total Meter ล่าสุด"),
            self._txt("• ระดับหมึก C / M / Y / K เมื่อรุ่นนั้นส่งค่า"),
            self._txt("• ถาดกระดาษ ขนาด/ชนิดกระดาษ และสถานะ Ready, Near Empty หรือ Empty"),
            self._txt("• Counter รายละเอียดจากเครื่อง และ User Authentication / Account Track เมื่อเปิดใช้งาน"),
            self._tip("เครื่องแต่ละรุ่นอาจส่งข้อมูลไม่เท่ากัน เครื่องหมาย — หมายถึงรุ่นนั้นไม่ส่งค่าหรือยังอ่านไม่ได้ ไม่ใช่ค่า 0"),
        ]))

        # ─ การคำนวณค่าใช้จ่าย ────────────────────────────
        lay.addWidget(self._card("การคำนวณรายงาน", [
            self._txt("ยอดใช้งาน = Meter ปลายงวด − Meter ต้นงวด โดยแยก Print/Copy และประเภทกระดาษ", bold=True),
            self._txt("แถว Meter เริ่มต้นมีไว้เป็นหลักฐานฐานเริ่มต้น ไม่รวมเป็นยอดใช้งานและไม่คิดค่าใช้จ่าย"),
            self._txt("ค่าใช้จ่ายก่อนส่วนลด = จำนวนหน้า × ราคาต่อหน้า"),
            self._txt("ค่าใช้จ่ายสุทธิ = ค่าใช้จ่ายก่อนส่วนลด × (1 − % กระดาษเสีย / 100)"),
            self._tip("เปิดหรือปิด checkbox คิดรวม % กระดาษเสียในหน้า Reports ได้ โดยจำนวนหน้าไม่เปลี่ยน"),
        ]))

        # ─ ความสัมพันธ์ระหว่าง Parser กับการนำเข้า ──────
        lay.addWidget(self._card("Legacy และ Parser Mapping", [
            self._txt(
                "Legacy แสดงชื่อ Counter ตรงตามที่เครื่องส่ง เช่น A5, Large Size หรือ FAX โดยไม่บังคับแปลงเป็น A3/A4",
                bold=True,
            ),
            self._step(1, "เปิด Settings → การตั้งค่าขั้นสูง → ตรวจสอบ Parser Mapping"),
            self._step(2, "เลือก Slot แล้วตรวจ Raw Data เทียบกับช่อง Database"),
            self._step(3, "แก้ Mapping เฉพาะรายการที่ผิด แล้วบันทึกกลับ"),
            self._tip("ถ้าไม่แน่ใจให้เก็บเป็น No Mapping เพื่อไม่ให้ยอดถูกรวมผิดประเภท"),
        ]))

        # ─ วันตัดรอบบิล ──────────────────────────────────
        lay.addWidget(self._card("ปิดโปรแกรมให้ถูกวิธี", [
            self._txt("ค่าเริ่มต้นเมื่อกดปิดหน้าต่าง โปรแกรมยังทำงานต่อใน System Tray เพื่ออ่านข้อมูลตามเวลา", bold=True),
            self._step(1, "ต้องการเปิดหน้าต่างอีกครั้ง ให้คลิกไอคอน KOMI Report ใน System Tray"),
            self._step(2, "ต้องการหยุดโปรแกรมจริง ให้เลือก Exit / ออกจากโปรแกรมจากเมนู System Tray"),
            self._step(3, "ปรับพฤติกรรมนี้ได้ใน Settings → การตั้งค่าขั้นสูง → โปรแกรม Log และการบำรุงรักษา"),
            self._tip("ก่อน Backup, Restore หรือลบ Database ควร Exit โปรแกรมให้หยุดสนิท"),
        ]))

        lay.addStretch()
        return page

    # ══════════════════════════════════════════════════════
    # TAB 1 — เริ่มต้นใช้งาน / Parser Setup
    # ══════════════════════════════════════════════════════
    def _tab_firstrun(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("เริ่มต้นใช้งาน KOMI Report V5.2"))

        lay.addWidget(self._card("คอมเครื่องแรก — ตั้งค่าครั้งแรก", [
            self._step(1, "กรอกชื่อบริษัท วันที่เริ่มใช้งานและ Version จะแสดงให้อัตโนมัติ"),
            self._step(2, "ตรวจ Database Path ใช้ [Browse] เมื่อต้องการเปลี่ยนตำแหน่ง หรือ [Import] เมื่อต้องการนำฐานข้อมูลเดิมมาใช้"),
            self._step(3, "อ่านประกาศข้อมูลการลงทะเบียน แล้วกดค้นหาเครื่องพิมพ์ใน LAN หรือกำหนดช่วง IP/เพิ่ม IP ด้วยตนเอง"),
            self._step(4, "เลือกไม่เกิน 3 เครื่อง ตรวจ Model, Serial และการเชื่อมต่อให้ผ่าน จากนั้นกำหนด Slot และชื่อจุดติดตั้ง"),
            self._step(5, "ตั้งราคา A4/A3 สีและขาวดำ วันตัดรอบบิล และเปอร์เซ็นต์กระดาษเสีย แล้วตรวจสอบก่อนบันทึก"),
            self._tip("ระหว่างสแกนจะแสดงความคืบหน้า กด Enter ในหน้ากำหนดช่วง IP เพื่อเริ่มสแกนได้"),
        ]))

        lay.addWidget(self._card("คอมเพิ่มเติม — รับค่าบริษัท", [
            self._step(1, "เมื่อพบคอมที่ตอบกลับใน LAN โปรแกรมแสดงข้อเสนอให้นำการตั้งค่ามาตรวจ"),
            self._step(2, "ตรวจชื่อบริษัท Slot เครื่องพิมพ์ ราคา รอบบิล และสิทธิ์เข้าร่วมก่อนรับค่า"),
            self._step(3, "ถ้าไม่พบคอมที่ต้องการ ให้กดค้นหาอีกครั้ง หรือกรอก IP ของคอมที่ให้บริการ"),
            self._tip("การรับค่าเริ่มต้นไม่คัดลอกตัวตนของอีกคอม การ Sync ต่อเนื่องเริ่มเมื่อมีสมาชิกที่ยืนยันสิทธิ์แล้ว"),
        ]))

        lay.addWidget(self._card("ลงทะเบียนก่อนเปิดโปรแกรม", [
            self._step(1, "หลังคลิก [บันทึกและเปิดโปรแกรม] ระบบจะลงทะเบียน Online และแสดงสถานะรอผล"),
            self._step(2, "เมื่อลงทะเบียนสำเร็จจะแสดงเครื่องหมายถูก แล้วเปิดหน้าหลักอัตโนมัติ"),
            self._step(3, "ถ้าเชื่อมต่อ Host ไม่ได้ ให้เลือก [ลงทะเบียน Offline] เพื่อส่งออก Request และนำเข้า License ที่ได้รับ"),
            self._tip("Offline License จะหยุดการส่ง Registration, Status และ Meter แต่ข้อมูลรายงานในเครื่องยังทำงานตามปกติ"),
        ]))

        lay.addWidget(self._card("ตรวจผลครั้งแรก", [
            self._step(1, "เปิดเมนูอุปกรณ์ แล้วกด [อ่านข้อมูลตอนนี้]"),
            self._step(2, "ตรวจชื่อรุ่น, Serial, Total Meter, หมึก, ถาดกระดาษ และ Counter จากเครื่องจริง"),
            self._step(3, "ถ้าข้อมูลไม่อัปเดต ให้เปิด Settings → สถานะและประวัติ"),
            self._tip("สถานะ Online เพียงอย่างเดียวไม่ยืนยันว่าข้อมูล Meter ครบ ต้องตรวจ Total Meter และเวลาอ่านล่าสุดด้วย"),
        ]))

        lay.addStretch()
        return page

    # ══════════════════════════════════════════════════════
    # TAB 1 — วิธีดาวน์โหลดไฟล์ TXT จากเครื่อง Konica Minolta
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # TAB 2 — วิธีนำเข้าไฟล์ (Import)
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # TAB 3 — หน้า Overview
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # TAB 4 — หน้า History
    # ══════════════════════════════════════════════════════
    def _tab_history(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("หน้า Reports — การใช้งานและค่าใช้จ่าย"))

        lay.addWidget(self._card("เลือกช่วงรายงาน", [
            self._txt("เลือกวันที่เริ่มต้นและวันที่สิ้นสุดจากคนละช่อง แล้วใช้ช่วงเดียวกันกับทุกแท็บ", bold=True),
            self._step(1, "Overview สรุป Print สี/ขาวดำ, Copy สี/ขาวดำ, ยอดรวม และค่าใช้จ่าย"),
            self._step(2, "Users แสดงผู้ใช้หรือ Account แยกตามเครื่องและประเภทงานที่เครื่องส่งมา"),
            self._step(3, "Printers แสดงกราฟทุกเครื่องพร้อมกัน; การเลือกแถวเปลี่ยนเฉพาะรายละเอียด Meter"),
            self._step(4, "Usage และ Legacy ใช้มุมมอง D / M / Y และดูรวมทุกเครื่องหรือแยกตามเครื่อง"),
        ]))

        lay.addWidget(self._card("Usage — รายงานมาตรฐาน", [
            self._txt("หัวตารางแบ่ง Print และ Copy อย่างชัดเจน แล้วแยก A3/A4 สี ขาวดำ และ Other", bold=True),
            self._step(1, "แถวแรกสุดเป็น Meter เริ่มต้น ใช้เป็นฐานอ้างอิงเท่านั้น"),
            self._step(2, "Meter เริ่มต้นไม่รวมในยอดใช้งาน ยอดรวม หรือค่าใช้จ่าย"),
            self._step(3, "checkbox [คิดรวม % กระดาษเสีย] เปิดไว้เป็นค่าเริ่มต้น ปิดได้เพื่อดูค่าใช้จ่ายก่อนส่วนลด"),
            self._tip("ตารางกว้างและเลื่อนซ้าย–ขวาได้เพื่อรักษาชื่อคอลัมน์ Print/Copy ให้ครบ"),
        ]))

        lay.addWidget(self._card("Legacy — ข้อมูลตรงจากเครื่อง", [
            self._txt("แสดงชื่อ Counter ตามที่เครื่องส่งจริง เช่น A5, Large Size, FAX หรือชื่อเฉพาะรุ่น โดยไม่บังคับ Map เป็น A3/A4", bold=True),
            self._step(1, "เลือกทุกเครื่องเพื่อเปรียบเทียบ Counter ต้นทางของ Slot 1–3"),
            self._step(2, "เลือกตามเครื่องหรือผู้ใช้เพื่อดูว่ารายการนั้นเกิดจากเครื่องใด"),
            self._step(3, "ถ้าชื่อหรือ Mapping ผิด ให้เปิด Settings → การตั้งค่าขั้นสูง → Parser Mapping"),
            self._tip("No Mapping หมายถึงเก็บข้อมูลต้นทางไว้ แต่ไม่รวมเข้าหมวดมาตรฐานที่อาจทำให้ยอดผิด"),
        ]))

        lay.addWidget(self._card("ส่งออก Excel", [
            self._step(1, "กด [ส่งออก Excel] แล้วเลือกช่วงวันที่ใน Popup"),
            self._step(2, "ไฟล์มี 6 ชีท: รายเครื่อง, ผู้ใช้, รายวัน และ Legacy ของทั้งสามมุมมอง"),
            self._step(3, "ชีทมาตรฐานแยก Print/Copy; ชีท Legacy คงชื่อประเภทจากเครื่องไว้ตรงๆ"),
            self._tip("ตรวจชื่อบริษัท ช่วงวันที่ และวันเวลาส่งออกที่หัวเอกสารก่อนนำไปใช้งาน"),
        ]))

        lay.addStretch()
        return page

    # ══════════════════════════════════════════════════════
    # TAB 5 — หน้า Settings
    # ══════════════════════════════════════════════════════
    def _tab_settings(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("หน้า Settings — ตั้งค่าโปรแกรม"))

        lay.addWidget(self._card("การตั้งค่าที่ใช้ประจำ", [
            self._step(1, "เครื่องพิมพ์และราคา — เพิ่มหรือเปลี่ยนเครื่อง 1–3 เครื่อง และแก้ราคาต่อหน้า"),
            self._step(2, "รอบบิล — วันสิ้นสุดรอบบิลและเปอร์เซ็นต์กระดาษเสีย"),
            self._step(3, "การอ่านข้อมูลอัตโนมัติ — เปิดพร้อมระบบและตารางเวลาที่แนะนำ"),
            self._step(4, "การลงทะเบียน — ดูสถานะล่าสุด ลองส่งอีกครั้ง หรือใช้ Offline License"),
            self._tip("หน้า Settings ไม่มีรหัสผ่าน แต่คำสั่งที่ลบหรือเขียนทับข้อมูลยังต้องยืนยัน"),
        ]))

        lay.addWidget(self._card("การตั้งค่าขั้นสูง — แสดงในหน้าเดิม", [
            self._txt("กด [เปิดการตั้งค่าขั้นสูง] แล้วข้อมูลทั้งหมดจะขยายในหน้า Settings เดิม ไม่เปิดหน้าต่างใหม่", bold=True),
            self._step(1, "ฐานข้อมูล: ดู/เปลี่ยน Path, Backup, Restore, ตรวจความสมบูรณ์ และเริ่มฐานข้อมูลใหม่"),
            self._step(2, "โปรแกรม: Auto-start, ทำงานใน System Tray และพฤติกรรมเมื่อปิดหน้าต่าง"),
            self._step(3, "Log: เปิดโฟลเดอร์ ส่งออกชุด Support และกำหนดระยะเวลาเก็บ"),
            self._step(4, "บำรุงรักษา: ล้าง Cache/ไฟล์ชั่วคราว หรือคืนค่าการตั้งค่าโดยไม่ลบฐานข้อมูล"),
            self._tip("Backup ก่อน Restore เปลี่ยน Path หรือลบ Database ทุกครั้ง"),
        ]))

        lay.addWidget(self._card("รายงานผ่าน LAN", [
            self._step(1, "Web Report บน LAN เปิดให้อัตโนมัติและแสดง URL สำหรับเครื่องอื่น"),
            self._step(2, "เลือกอนุญาตให้เปิดรายงานแบบอ่านอย่างเดียวโดยไม่ใช้รหัสได้"),
            self._step(3, "กดเปิดหน้า Web หรือคัดลอกที่อยู่ LAN แล้วทดสอบจากเครื่องอื่นในเครือข่ายเดียวกัน"),
            self._tip("สิทธิ์เจ้าหน้าที่และการแก้ไขยังคงต้องยืนยันตัวตน แม้เปิดรายงานทั่วไปโดยไม่ใช้รหัส"),
        ]))

        lay.addWidget(self._card("Parser Mapping", [
            self._step(1, "เปิดหน้าต่าง Parser Mapping จากการตั้งค่าขั้นสูง"),
            self._step(2, "เลือก Slot แล้วเปรียบเทียบ Raw Data กับหมวด Database"),
            self._step(3, "แก้เฉพาะรายการที่ Map ผิด แล้วบันทึกแยกตาม Serial Number"),
            self._tip("รายการที่ไม่แน่ใจควรเป็น No Mapping เพื่อป้องกันการรวมยอดผิด"),
        ]))

        lay.addStretch()
        return page

    def refresh(self):
        """ไม่ต้องโหลดข้อมูลเพิ่มเติม — เนื้อหาคงที่"""
        pass

    def minimumSizeHint(self) -> QSize:
        """Allow the manual to reflow inside the desktop minimum viewport."""
        hint = super().minimumSizeHint()
        return QSize(min(760, hint.width()), hint.height())
