"""Legacy UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import json
import traceback
from collections import defaultdict
from datetime import datetime

from PyQt6.QtCharts import QChart, QChartView, QPieSeries
from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_WASTE_PCT, SLOT_NAMES
from database import (
    calc_cost,
    get_all_readings,
    get_billing_day,
    get_cfg,
    get_last_two,
    get_price,
    get_price_snapshot,
    get_waste_paper_pct,
)
from services.support_diagnostics import with_diagnostic
from tools.check_parser import load_profiles
from ui.chart_lifecycle import replace_chart
from ui.page_tabs import PageTabs as QTabWidget
from ui.styles import inputs as inputs_styles
from ui.styles import reports as reports_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles.tokens import (
    C_ACCENT,
    C_CARD,
    C_GREEN,
    C_ORANGE,
    C_PURPLE,
    C_TEXT,
    C_TEXT2,
    C_TEXT3,
    F_LG,
    F_MD,
    F_SM,
    F_XS,
    GRAPH_AXIS_LABEL_SIZE,
    GRAPH_BAR_WIDTH,
    GRAPH_BG_COLOR,
    GRAPH_COLORS_MACHINE,
    GRAPH_COLORS_TYPE,
    GRAPH_GRID_ALPHA,
    GRAPH_TITLE_SIZE,
    GRAPH_TOOLTIP_BG,
    GRAPH_TOOLTIP_COLOR,
    GRAPH_TOOLTIP_SIZE,
    GRAPH_VALUE_SIZE,
    SLOT_COLORS,
    SLOT_LIGHT,
)
from widgets import FrozenColTable, FrozenLeftTable, StatCard, btn, fd, fmt_baht, fn, fnt, sec_title, tbl_item


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
        self.lbl_info.setFont(fnt(F_XS)); self.lbl_info.setStyleSheet(text_styles.label(C_TEXT3))
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
        _note_curr.setStyleSheet(text_styles.label(C_TEXT3, padding='3px 2px'))
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
            reports_styles.billing_day_badge(SLOT_LIGHT[0]))
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
        _note_monthly.setStyleSheet(text_styles.label(C_TEXT3, padding='3px 2px'))
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
        get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])

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
        self.cmb_month_users.currentData() if self.cmb_month_users.count() > 0 else None
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
        self.cmb_month_users.setProperty("i18n_items", True)
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
        self.lbl_count_users.setStyleSheet(text_styles.label(C_TEXT2))
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
        self.cmb_date_from.setProperty("i18n_items", True)
        self.cmb_date_from.setMinimumWidth(130)
        self.cmb_date_from.setFont(fnt(F_MD))
        self.cmb_date_from.currentTextChanged.connect(self._on_date_from_changed)
        date_lay.addWidget(self.cmb_date_from)

        date_lay.addWidget(QLabel("ถึง", font=fnt(F_LG)))

        self.cmb_date_to = QComboBox()
        self.cmb_date_to.setProperty("i18n_items", True)
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
        self.pie_container.setStyleSheet(reports_styles.history_pie_container())
        self.pie_container.setVisible(False)
        pie_vlay = QVBoxLayout(self.pie_container)
        pie_vlay.setContentsMargins(0, 0, 0, 0)
        pie_vlay.setSpacing(6)

        # Pie ใหญ่รวมทุกเครื่อง
        self.pie_view_all = QChartView()
        self.pie_view_all.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.pie_view_all.setStyleSheet(surfaces_styles.card())
        self.pie_view_all.setMinimumHeight(300)
        pie_vlay.addWidget(self.pie_view_all, 5)

        # Row 3 Pie เล็กแยกเครื่อง
        pie_small_row = QHBoxLayout()
        pie_small_row.setSpacing(6)
        self.pie_views_slot = []
        for _i in range(3):
            _v = QChartView()
            _v.setRenderHint(QPainter.RenderHint.Antialiasing)
            _v.setStyleSheet(surfaces_styles.card())
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
            QMessageBox.critical(self, "ข้อผิดพลาด", with_diagnostic(f"ไม่สามารถบันทึกไฟล์ได้:\n{e}", e, "ข้อผิดพลาด"))

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
                                inputs_styles.legend_checkbox(hex_c, muted=True))
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
                            inputs_styles.legend_checkbox(hex_c))
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
                                inputs_styles.legend_checkbox(hex_c, muted=True))
                            cb.toggled.connect(lambda checked, t=tk: self._toggle_type_legend(t, checked))
                            self._ext_legend_layout.addWidget(cb)
                        self._ext_legend_widget.setVisible(True)
                    return

                n_machines = len(active_slots)
                bar_w = GRAPH_BAR_WIDTH
                group_w = n_machines * bar_w + 0.15

                # สร้าง stacked bars
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
                            inputs_styles.legend_checkbox(hex_c))
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

        except Exception:
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
                label, bx, val, _ml = entry[0], entry[1], entry[2], entry[3]
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
        except Exception:
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
            replace_chart(self.pie_view_all,
                _make_chart(s_all, "📊  ประเภทงาน — รวมทุกเครื่อง", is_large=True))

            # ── Pie เล็ก แยก 3 เครื่อง ──
            for i, view in enumerate(self.pie_views_slot):
                s = QPieSeries()
                _fill_type(s, [i], is_large=False)
                replace_chart(view, _make_chart(s, f"🖨  {m_names[i]}"))

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
            replace_chart(self.pie_view_all,
                _make_chart(s_all, "👤  ผู้ใช้งาน — รวมทุกเครื่อง", is_large=True))

            # ── Pie เล็ก แยก 3 เครื่อง ──
            for i, view in enumerate(self.pie_views_slot):
                s = QPieSeries()
                _fill_user(s, [i], color_map, is_large=False)
                replace_chart(view, _make_chart(s, f"🖨  {m_names[i]}"))


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
            QMessageBox.critical(self, "ข้อผิดพลาด", with_diagnostic(f"ไม่สามารถบันทึกไฟล์ได้:\n{e}", e, "ข้อผิดพลาด"))
