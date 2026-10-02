"""Imports UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import SLOT_NAMES
from database import (
    calc_billing_month,
    calc_cost,
    check_duplicate,
    clear_slot,
    delete_reading,
    get_activity_log,
    get_billing_day,
    get_cfg,
    get_db_path,
    get_last_two,
    get_price,
    get_slot_serial,
    sanitize_filename,
)
from parser_profiles import PARSER_REGISTRY
from services.import_service import parse_import_file
from services.import_worker import ImportSaveWorker
from services.support_diagnostics import with_diagnostic
from ui.parser_editor import _open_check_parser
from ui.styles import buttons as buttons_styles
from ui.styles import devices as devices_styles
from ui.styles import legacy as legacy_styles
from ui.styles import text as text_styles
from ui.styles.tokens import (
    C_ACCENT,
    C_GREEN,
    C_ORANGE,
    C_PURPLE,
    C_TEXT,
    C_TEXT2,
    C_TEXT3,
    F_LG,
    F_MD,
    F_SM,
    F_XL,
    F_XS,
    SLOT_COLORS,
)
from widgets import (
    btn,
    fmt_baht,
    fn,
    fnt,
    hline,
    make_table,
    mk_card,
    mk_preview_card,
    mk_warn_card,
    sec_title,
    sub_title,
    tbl_item,
)

log = logging.getLogger(__name__)


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
        icon.setStyleSheet(legacy_styles.NO_PARSER_MATCH_DIALOG_ICON)
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
        sub_msg.setStyleSheet(text_styles.label('#64748B', font_size='10pt'))
        sub_msg.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(sub_msg)

        lay.addSpacing(4)

        btn_open = QPushButton("⚙️  เปิด Check Parser เพื่อตั้งค่า")
        btn_open.setFixedHeight(40)
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.setStyleSheet(
            legacy_styles.NO_PARSER_MATCH_DIALOG_BTN_OPEN
        )
        btn_open.clicked.connect(self._on_open_parser)
        lay.addWidget(btn_open)

        btn_confirm = QPushButton("✅  ยืนยันบันทึกต่อไป (ไม่มี Parser)")
        btn_confirm.setFixedHeight(36)
        btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_confirm.setStyleSheet(
            legacy_styles.NO_PARSER_MATCH_DIALOG_BTN_CONFIRM
        )
        btn_confirm.clicked.connect(self._on_confirm)
        lay.addWidget(btn_confirm)

        btn_cancel = QPushButton("ยกเลิก")
        btn_cancel.setFixedHeight(30)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(
            legacy_styles.NO_PARSER_MATCH_DIALOG_BTN_CANCEL
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
                legacy_styles.preview_dialog_parser_banner(p_color)
            )
            pb_lay = QHBoxLayout(parser_banner)
            pb_lay.setContentsMargins(14, 10, 14, 10)
            pb_icon = QLabel("🔍  ตรวจพบรูปแบบไฟล์:")
            pb_icon.setFont(fnt(F_MD))
            pb_icon.setStyleSheet(text_styles.label(C_TEXT2, background='transparent', border='none'))
            pb_name = QLabel(self.parser_name)
            pb_name.setProperty("i18n_data", True)
            pb_name.setFont(fnt(F_LG, True))
            pb_name.setStyleSheet(text_styles.label(p_color, background='transparent', border='none'))
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
                                legacy_styles.preview_dialog_badge(_clr)
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
        mode_badge.setStyleSheet(legacy_styles.preview_dialog_mode_badge(mode_color))
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
            tl = QLabel(f"{lbl} :"); tl.setFont(fnt(F_MD)); tl.setStyleSheet(text_styles.label(C_TEXT3))
            tl.setFixedWidth(110)
            vl = QLabel(val); vl.setFont(fnt(F_MD, bold)); vl.setStyleSheet(text_styles.label(col))
            g.addWidget(tl, r, 0); g.addWidget(vl, r, 1)
        il.addLayout(g)
        lay.addWidget(info_card)

        # ── ตรวจสอบคำเตือน
        existing_sn = get_slot_serial(self.slot)
        get_cfg(f"machine_name_{self.slot}", SLOT_NAMES[self.slot])
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
            wlbl.setStyleSheet(text_styles.label('#DC2626', font_weight='bold'))
            wlbl.setWordWrap(True)
            wl.addWidget(wlbl)
            lay.addWidget(wc)

        # ── ปุ่ม
        btns = QDialogButtonBox()
        if self._warnings:
            save_btn = btns.addButton("บันทึกถึงกระนั้น", QDialogButtonBox.ButtonRole.AcceptRole)
            save_btn.setObjectName("btn_warning")
            save_btn.setStyleSheet(buttons_styles.dialog_action(pressed=True))
        else:
            save_btn = btns.addButton("✅  บันทึกข้อมูล", QDialogButtonBox.ButtonRole.AcceptRole)
            save_btn.setObjectName("btn_success")
            save_btn.setStyleSheet(buttons_styles.dialog_action(pressed=True))

        cancel_btn = btns.addButton("ยกเลิก", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.setObjectName("btn_outline")
        cancel_btn.setStyleSheet(legacy_styles.PREVIEW_DIALOG_CANCEL_BTN)

        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


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
            buttons_styles.EDIT
        )
        self.btn_delete_sel = QPushButton("🗑  ลบที่เลือก")
        self.btn_delete_sel.setFont(fnt(F_MD, True))
        self.btn_delete_sel.setFixedHeight(34)
        self.btn_delete_sel.setStyleSheet(
            devices_styles.IMPORT_BTN_DELETE_SEL
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
        dot.setStyleSheet(text_styles.label(color))
        name_l = QLabel(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))
        name_l.setFont(fnt(F_LG, True))
        mode_l = QLabel(""); mode_l.setFont(fnt(F_SM, True))
        mode_l.setStyleSheet(text_styles.label(color))
        hr.addWidget(dot); hr.addWidget(name_l); hr.addStretch(); hr.addWidget(mode_l)
        lay.addLayout(hr)

        mach_l = QLabel("—"); mach_l.setFont(fnt(F_LG, True))
        mach_l.setStyleSheet(text_styles.label(C_TEXT))
        sn_l = QLabel(""); sn_l.setFont(fnt(F_SM, True))
        sn_l.setStyleSheet(text_styles.label(C_TEXT))
        date_l = QLabel(""); date_l.setFont(fnt(F_SM, True))
        date_l.setStyleSheet(text_styles.label(C_TEXT))
        lay.addWidget(mach_l); lay.addWidget(sn_l); lay.addWidget(date_l)
        lay.addStretch()

        # ปุ่มนำเข้าและล้าง
        br = QHBoxLayout(); br.setSpacing(8)
        b_imp = btn("📥  นำเข้าไฟล์", "primary")
        b_imp.setStyleSheet(buttons_styles.dialog_action())
        b_clr = btn("🗑", "danger"); b_clr.setFixedWidth(50); b_clr.setMinimumHeight(38)
        b_clr.setStyleSheet(devices_styles.IMPORT_B_CLR)
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
            devices_styles.IMPORT_OVERLAY
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
            QMessageBox.critical(self, "เกิดข้อผิดพลาด", with_diagnostic(f"อ่านไฟล์ไม่ได้:\n{e}", e, "เกิดข้อผิดพลาด"))
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
                    devices_styles.IMPORT_CARD_FRAME_SET_DRAG_HIGHLIGHT
                )
                if hasattr(card_frame, '_overlay'):
                    card_frame._overlay.setVisible(False)

    def _clear_drag_highlight(self):
        """คืนค่าการ์ดเป็นสภาพปกติ"""
        if self._current_drag_card is None:
            return

        for i, card_frame in enumerate(self._slot_widgets):
            # รีเซ็ต stylesheet เป็นค่าปกติ
            card_frame.setStyleSheet(devices_styles.IMPORT_CARD_FRAME)
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
            self.tbl_activity.setStyleSheet(devices_styles.IMPORT_TBL_ACTIVITY)
            self.btn_edit_mode.setText("✕  ยกเลิก")
            self.btn_edit_mode.setStyleSheet(
                devices_styles.IMPORT_BTN_EDIT_MODE
            )
        else:
            self.tbl_activity.setCursor(Qt.CursorShape.ArrowCursor)
            self.tbl_activity.setAlternatingRowColors(True)
            self.tbl_activity.setStyleSheet("")
            self.btn_edit_mode.setText("✏️  แก้ไข")
            self.btn_edit_mode.setStyleSheet(
                buttons_styles.EDIT
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
                buttons_styles.EDIT
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
