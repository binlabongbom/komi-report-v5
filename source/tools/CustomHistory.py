#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# tools/CustomHistory.py  —  เครื่องมือปรับแต่ง KM Meter Reader
# รัน standalone: python tools/CustomHistory.py
# ═══════════════════════════════════════════════════════════════════════════════
import sys
import os

# Add parent directory to path so we can import config/database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QListWidget, QListWidgetItem, QLineEdit,
    QGroupBox, QMessageBox, QAbstractItemView, QFrame, QGridLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config import (
    C_ACCENT, C_BG, C_CARD, C_BORDER, C_TEXT, C_TEXT2, C_RED, F_XS, F_SM, F_MD, F_LG, F_XL, F_2XL, APP_VER,
)
from database import get_cfg, set_cfg, set_settings_password, verify_settings_password

# ─── Helpers ──────────────────────────────────────────────────────────────────

def fnt(size: int, bold: bool = False) -> QFont:
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    return f


def _card() -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"QFrame {{ background:{C_CARD}; border-radius:10px; "
        f"border:1px solid {C_BORDER}; padding:4px; }}")
    return f


def _hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"color:{C_BORDER};")
    return ln


APP_SS = f"""
QWidget {{ background: {C_BG}; color: {C_TEXT}; font-family: 'Segoe UI'; }}
QTabWidget::pane {{ border: 1px solid {C_BORDER}; border-radius: 8px; }}
QTabBar::tab {{
    background: #F1F5F9; border: 1px solid {C_BORDER};
    padding: 7px 18px; border-radius: 6px 6px 0 0; margin-right: 3px;
    font-size: {F_MD}pt;
}}
QTabBar::tab:selected {{ background: {C_ACCENT}; color: white; }}
QPushButton {{
    background: {C_ACCENT}; color: white; border-radius: 7px;
    padding: 7px 18px; font-size: {F_MD}pt; font-weight: 600; border: none;
}}
QPushButton:hover {{ background: #1e40af; }}
QPushButton[variant="outline"] {{
    background: white; color: {C_ACCENT}; border: 1.5px solid {C_ACCENT};
}}
QPushButton[variant="outline"]:hover {{ background: {C_ACCENT}; color: white; }}
QPushButton[variant="danger"] {{
    background: {C_RED}; color: white;
}}
QPushButton[variant="danger"]:hover {{ background: #b91c1c; }}
QListWidget {{ border: 1px solid {C_BORDER}; border-radius: 6px;
               background: #F8FAFC; font-size: {F_MD}pt; }}
QListWidget::item {{ padding: 5px 8px; }}
QListWidget::item:selected {{ background: {C_ACCENT}; color: white; }}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
    border: 1px solid {C_BORDER}; border-radius: 5px;
    padding: 4px 8px; font-size: {F_MD}pt;
    background: white;
}}
QGroupBox {{
    border: 1px solid {C_BORDER}; border-radius: 8px;
    margin-top: 12px; font-size: {F_MD}pt; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
"""


def btn(label: str, variant: str = "primary", width: int = 0) -> QPushButton:
    b = QPushButton(label)
    b.setProperty("variant", variant)
    if variant == "primary":
        b.setStyleSheet(
            f"QPushButton {{ background:{C_ACCENT}; color:white; border-radius:7px;"
            f"padding:7px 18px; font-size:{F_MD}pt; font-weight:600; border:none; }}"
            f"QPushButton:hover {{ background:#1e40af; }}")
    elif variant == "outline":
        b.setStyleSheet(
            f"QPushButton {{ background:white; color:{C_ACCENT}; border:1.5px solid {C_ACCENT};"
            f"border-radius:7px; padding:7px 18px; font-size:{F_MD}pt; font-weight:600; }}"
            f"QPushButton:hover {{ background:{C_ACCENT}; color:white; }}")
    elif variant == "danger":
        b.setStyleSheet(
            f"QPushButton {{ background:{C_RED}; color:white; border-radius:7px;"
            f"padding:7px 18px; font-size:{F_MD}pt; font-weight:600; border:none; }}"
            f"QPushButton:hover {{ background:#b91c1c; }}")
    if width:
        b.setFixedWidth(width)
    return b


# ─── CONFIG KEYS ──────────────────────────────────────────────────────────────
# Row order/visibility for Tab1 (ค่ามิเตอร์ปัจจุบัน)
# Stored as comma-separated keys, e.g. "total_counter,total_color,total_bw"
CURRENT_ROW_DEFAULT = "total_counter,total_color,total_bw,a4_color,a4_bw,a3_color,a3_bw"
CURRENT_ROW_LABELS = {
    "total_counter": "Grand Total",
    "total_color":   "Full Color",
    "total_bw":      "Black & White",
    "a4_color":      "A4 สี",
    "a4_bw":         "A4 ขาวดำ",
    "a3_color":      "A3 สี",
    "a3_bw":         "A3 ขาวดำ",
    "copy_color":    "Copy Color",
    "copy_bw":       "Copy B&W",
    "print_color":   "Print Color",
    "print_bw":      "Print B&W",
    "cost":          "ค่าใช้จ่าย (฿)",
}
ALL_CURRENT_KEYS = list(CURRENT_ROW_LABELS.keys())

# Column order/visibility for Tab2 (ย้อนหลังรายเดือน) per machine group
MONTHLY_COL_DEFAULT = "total_counter,total_color,total_bw,a4_color,a4_bw,a3_color,a3_bw,cost"
MONTHLY_COL_LABELS = {
    "total_counter": "Grand Total",
    "total_color":   "Color",
    "total_bw":      "B&W",
    "a4_color":      "A4 สี",
    "a4_bw":         "A4 ขาวดำ",
    "a3_color":      "A3 สี",
    "a3_bw":         "A3 ขาวดำ",
    "cost":          "ค่าใช้จ่าย(฿)",
}
ALL_MONTHLY_KEYS = list(MONTHLY_COL_LABELS.keys())


# ─── Page 1: ค่ามิเตอร์ปัจจุบัน — row order ────────────────────────────────

class PageCurrentRows(QWidget):
    """ปรับแต่งแถวที่แสดงใน Tab 'ค่ามิเตอร์ปัจจุบัน' (Tab 1 ของ History)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lbl = QLabel("📋  ค่ามิเตอร์ปัจจุบัน — จัดลำดับแถว")
        lbl.setFont(fnt(F_XL, True)); lbl.setStyleSheet(f"color:{C_ACCENT};")
        lay.addWidget(lbl)

        hint = QLabel(
            "ลากเพื่อเรียงลำดับ ✓ = แสดง    ✗ = ซ่อน\n"
            "รายการที่ถูกเลือก (check) จะแสดงในตาราง ค่ามิเตอร์ปัจจุบัน")
        hint.setFont(fnt(F_SM)); hint.setStyleSheet(f"color:{C_TEXT2};")
        lay.addWidget(hint)

        body = QHBoxLayout()

        # List: แถวที่เปิดใช้งาน (สามารถลากเรียงลำดับ)
        left = QGroupBox("แถวที่แสดง (ลากเรียงลำดับ)")
        left.setFont(fnt(F_MD, True))
        ll = QVBoxLayout(left); ll.setSpacing(6)
        self.lst_active = QListWidget()
        self.lst_active.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst_active.setFont(fnt(F_MD))
        ll.addWidget(self.lst_active)
        body.addWidget(left, 2)

        # Buttons
        mid = QVBoxLayout(); mid.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        mid.setSpacing(8)
        self.btn_add    = btn("◀  เพิ่ม",    "primary", 110)
        self.btn_remove = btn("ลบ  ▶",    "outline", 110)
        mid.addWidget(self.btn_add)
        mid.addWidget(self.btn_remove)
        body.addLayout(mid)

        # List: รายการที่ซ่อน
        right = QGroupBox("แถวที่ซ่อน")
        right.setFont(fnt(F_MD, True))
        rl = QVBoxLayout(right); rl.setSpacing(6)
        self.lst_hidden = QListWidget()
        self.lst_hidden.setFont(fnt(F_MD))
        rl.addWidget(self.lst_hidden)
        body.addWidget(right, 1)

        lay.addLayout(body, 1)

        # Save / Reset
        bot = QHBoxLayout()
        b_save  = btn("💾  บันทึก",    "primary", 140)
        b_reset = btn("🔄  รีเซท Default", "outline", 180)
        b_save.clicked.connect(self._save)
        b_reset.clicked.connect(self._reset)
        bot.addStretch()
        bot.addWidget(b_save)
        bot.addWidget(b_reset)
        lay.addLayout(bot)

        self.btn_add.clicked.connect(self._add_row)
        self.btn_remove.clicked.connect(self._remove_row)

    def _load(self):
        active_keys = get_cfg("custom_current_rows", CURRENT_ROW_DEFAULT).split(",")
        active_keys = [k.strip() for k in active_keys if k.strip() in ALL_CURRENT_KEYS]
        hidden_keys = [k for k in ALL_CURRENT_KEYS if k not in active_keys]

        self.lst_active.clear()
        for k in active_keys:
            it = QListWidgetItem(CURRENT_ROW_LABELS.get(k, k))
            it.setData(Qt.ItemDataRole.UserRole, k)
            self.lst_active.addItem(it)

        self.lst_hidden.clear()
        for k in hidden_keys:
            it = QListWidgetItem(CURRENT_ROW_LABELS.get(k, k))
            it.setData(Qt.ItemDataRole.UserRole, k)
            self.lst_hidden.addItem(it)

    def _add_row(self):
        sel = self.lst_hidden.currentItem()
        if sel:
            self.lst_hidden.takeItem(self.lst_hidden.row(sel))
            self.lst_active.addItem(sel)

    def _remove_row(self):
        sel = self.lst_active.currentItem()
        if sel:
            self.lst_active.takeItem(self.lst_active.row(sel))
            self.lst_hidden.addItem(sel)

    def _save(self):
        keys = []
        for i in range(self.lst_active.count()):
            keys.append(self.lst_active.item(i).data(Qt.ItemDataRole.UserRole))
        set_cfg("custom_current_rows", ",".join(keys))
        QMessageBox.information(self, "บันทึกแล้ว",
            "บันทึกการตั้งค่าแถว ค่ามิเตอร์ปัจจุบัน เรียบร้อย\n"
            "(จะมีผลเมื่อรีเฟรชหน้า History)")

    def _reset(self):
        set_cfg("custom_current_rows", CURRENT_ROW_DEFAULT)
        self._load()
        QMessageBox.information(self, "รีเซทแล้ว", "รีเซทเป็นค่าเริ่มต้นเรียบร้อย")


# ─── Page 2: ย้อนหลังรายเดือน — column order ────────────────────────────────

class PageMonthlyColumns(QWidget):
    """ปรับแต่งคอลัมน์ที่แสดงใน Tab 'ย้อนหลังรายเดือน' (Tab 2 ของ History)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lbl = QLabel("📅  ย้อนหลังรายเดือน — จัดลำดับคอลัมน์")
        lbl.setFont(fnt(F_XL, True)); lbl.setStyleSheet(f"color:{C_ACCENT};")
        lay.addWidget(lbl)

        hint = QLabel(
            "เลือกคอลัมน์ที่แสดงในตาราง ย้อนหลังรายเดือน (เหมือนกันสำหรับทุกเครื่อง)\n"
            "ลากใน 'คอลัมน์ที่แสดง' เพื่อเรียงลำดับ")
        hint.setFont(fnt(F_SM)); hint.setStyleSheet(f"color:{C_TEXT2};")
        lay.addWidget(hint)

        body = QHBoxLayout()

        left = QGroupBox("คอลัมน์ที่แสดง (ลากเรียงลำดับ)")
        left.setFont(fnt(F_MD, True))
        ll = QVBoxLayout(left); ll.setSpacing(6)
        self.lst_active = QListWidget()
        self.lst_active.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst_active.setFont(fnt(F_MD))
        ll.addWidget(self.lst_active)
        body.addWidget(left, 2)

        mid = QVBoxLayout(); mid.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        mid.setSpacing(8)
        self.btn_add    = btn("◀  เพิ่ม", "primary", 110)
        self.btn_remove = btn("ลบ  ▶",   "outline", 110)
        mid.addWidget(self.btn_add)
        mid.addWidget(self.btn_remove)
        body.addLayout(mid)

        right = QGroupBox("คอลัมน์ที่ซ่อน")
        right.setFont(fnt(F_MD, True))
        rl = QVBoxLayout(right); rl.setSpacing(6)
        self.lst_hidden = QListWidget()
        self.lst_hidden.setFont(fnt(F_MD))
        rl.addWidget(self.lst_hidden)
        body.addWidget(right, 1)

        lay.addLayout(body, 1)

        bot = QHBoxLayout()
        b_save  = btn("💾  บันทึก",    "primary", 140)
        b_reset = btn("🔄  รีเซท Default", "outline", 180)
        b_save.clicked.connect(self._save)
        b_reset.clicked.connect(self._reset)
        bot.addStretch()
        bot.addWidget(b_save)
        bot.addWidget(b_reset)
        lay.addLayout(bot)

        self.btn_add.clicked.connect(self._add_col)
        self.btn_remove.clicked.connect(self._remove_col)

    def _load(self):
        active_keys = get_cfg("custom_monthly_cols", MONTHLY_COL_DEFAULT).split(",")
        active_keys = [k.strip() for k in active_keys if k.strip() in ALL_MONTHLY_KEYS]
        hidden_keys = [k for k in ALL_MONTHLY_KEYS if k not in active_keys]

        self.lst_active.clear()
        for k in active_keys:
            it = QListWidgetItem(MONTHLY_COL_LABELS.get(k, k))
            it.setData(Qt.ItemDataRole.UserRole, k)
            self.lst_active.addItem(it)

        self.lst_hidden.clear()
        for k in hidden_keys:
            it = QListWidgetItem(MONTHLY_COL_LABELS.get(k, k))
            it.setData(Qt.ItemDataRole.UserRole, k)
            self.lst_hidden.addItem(it)

    def _add_col(self):
        sel = self.lst_hidden.currentItem()
        if sel:
            self.lst_hidden.takeItem(self.lst_hidden.row(sel))
            self.lst_active.addItem(sel)

    def _remove_col(self):
        sel = self.lst_active.currentItem()
        if sel:
            self.lst_active.takeItem(self.lst_active.row(sel))
            self.lst_hidden.addItem(sel)

    def _save(self):
        keys = []
        for i in range(self.lst_active.count()):
            keys.append(self.lst_active.item(i).data(Qt.ItemDataRole.UserRole))
        set_cfg("custom_monthly_cols", ",".join(keys))
        QMessageBox.information(self, "บันทึกแล้ว",
            "บันทึกการตั้งค่าคอลัมน์ ย้อนหลังรายเดือน เรียบร้อย\n"
            "(จะมีผลเมื่อรีเฟรชหน้า History)")

    def _reset(self):
        set_cfg("custom_monthly_cols", MONTHLY_COL_DEFAULT)
        self._load()
        QMessageBox.information(self, "รีเซทแล้ว", "รีเซทเป็นค่าเริ่มต้นเรียบร้อย")


# ─── Page 3: Stat Cards ──────────────────────────────────────────────────────

class PageStatCards(QWidget):
    """ปรับแต่ง Stat Cards — สี, ขนาดตัวเลข, ชื่อการ์ด"""

    CARD_DEFS = [
        # (cfg_key_prefix, default_label, default_color)
        ("sc_color",      "Full Color",    "#EA580C"),
        ("sc_bw",         "B&W",           "#5a5a5d"),
        ("sc_a4c",        "A4 สี",         "#123262"),
        ("sc_a4bw",       "A4 ขาวดำ",      "#5a5a5d"),
        ("sc_a3c",        "A3 สี",         "#EA580C"),
        ("sc_a3bw",       "A3 ขาวดำ",      "#7C3AED"),
        ("sc_grand",      "Grand Total",   "#123262"),
        ("sc_cost",       "ค่าใช้จ่าย",    "#16A34A"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lbl = QLabel("🃏  Stat Cards — ปรับแต่งชื่อและสี")
        lbl.setFont(fnt(F_XL, True)); lbl.setStyleSheet(f"color:{C_ACCENT};")
        lay.addWidget(lbl)

        hint = QLabel("ปรับชื่อและสีในแต่ละ Stat Card ของหน้า Overview และ History")
        hint.setFont(fnt(F_SM)); hint.setStyleSheet(f"color:{C_TEXT2};")
        lay.addWidget(hint)

        grid = QGridLayout(); grid.setSpacing(10)
        grid.addWidget(QLabel("การ์ด",     font=fnt(F_MD, True)), 0, 0)
        grid.addWidget(QLabel("ชื่อที่แสดง", font=fnt(F_MD, True)), 0, 1)
        grid.addWidget(QLabel("สี (Hex)",    font=fnt(F_MD, True)), 0, 2)

        self._card_widgets = {}  # {key: (name_inp, color_inp)}
        for row, (key, default_label, default_color) in enumerate(self.CARD_DEFS, start=1):
            disp_key = QLabel(default_label); disp_key.setFont(fnt(F_MD))
            name_inp = QLineEdit()
            name_inp.setFont(fnt(F_MD)); name_inp.setFixedWidth(180)
            color_inp = QLineEdit()
            color_inp.setFont(fnt(F_MD)); color_inp.setFixedWidth(120)
            grid.addWidget(disp_key,   row, 0)
            grid.addWidget(name_inp,   row, 1)
            grid.addWidget(color_inp,  row, 2)
            self._card_widgets[key] = (name_inp, color_inp)

        lay.addLayout(grid)
        lay.addStretch()

        bot = QHBoxLayout()
        b_save  = btn("💾  บันทึก",    "primary", 140)
        b_reset = btn("🔄  รีเซท Default", "outline", 180)
        b_save.clicked.connect(self._save)
        b_reset.clicked.connect(self._reset)
        bot.addStretch()
        bot.addWidget(b_save)
        bot.addWidget(b_reset)
        lay.addLayout(bot)

    def _load(self):
        for key, default_label, default_color in self.CARD_DEFS:
            name_inp, color_inp = self._card_widgets[key]
            name_inp.setText(get_cfg(f"{key}_label", default_label))
            color_inp.setText(get_cfg(f"{key}_color", default_color))

    def _save(self):
        for key, default_label, default_color in self.CARD_DEFS:
            name_inp, color_inp = self._card_widgets[key]
            set_cfg(f"{key}_label", name_inp.text() or default_label)
            set_cfg(f"{key}_color", color_inp.text() or default_color)
        QMessageBox.information(self, "บันทึกแล้ว",
            "บันทึกการตั้งค่า Stat Cards เรียบร้อย\n"
            "(จะมีผลเมื่อรีสตาร์ทโปรแกรม)")

    def _reset(self):
        for key, default_label, default_color in self.CARD_DEFS:
            set_cfg(f"{key}_label", default_label)
            set_cfg(f"{key}_color", default_color)
        self._load()
        QMessageBox.information(self, "รีเซทแล้ว", "รีเซทเป็นค่าเริ่มต้นเรียบร้อย")


# ─── Page 4: Password Settings ───────────────────────────────────────────────

class PagePassword(QWidget):
    """เปลี่ยนรหัสผ่านสำหรับบันทึกการตั้งค่า"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(20)

        lbl = QLabel("🔒  เปลี่ยนรหัสผ่าน")
        lbl.setFont(fnt(F_XL, True)); lbl.setStyleSheet(f"color:{C_ACCENT};")
        lay.addWidget(lbl)

        card = _card()
        cl = QVBoxLayout(card); cl.setContentsMargins(20, 16, 20, 16); cl.setSpacing(14)

        def _row(label: str) -> QLineEdit:
            r = QHBoxLayout()
            lb = QLabel(label); lb.setFont(fnt(F_LG)); lb.setFixedWidth(220)
            inp = QLineEdit()
            inp.setFont(fnt(F_LG))
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setFixedWidth(240)
            r.addWidget(lb); r.addWidget(inp); r.addStretch()
            cl.addLayout(r)
            return inp

        self.inp_old  = _row("รหัสผ่านปัจจุบัน :")
        self.inp_new  = _row("รหัสผ่านใหม่ :")
        self.inp_conf = _row("ยืนยันรหัสใหม่ :")

        b_chg = btn("🔑  เปลี่ยนรหัสผ่าน", "primary", 200)
        b_chg.clicked.connect(self._change_password)
        cl.addWidget(b_chg)

        hint = QLabel("รหัสผ่านนี้ใช้ยืนยันก่อนบันทึกการตั้งค่าในโปรแกรมหลัก")
        hint.setFont(fnt(F_XS)); hint.setStyleSheet(f"color:{C_TEXT2};")
        cl.addWidget(hint)

        lay.addWidget(card)
        lay.addStretch()

    def _change_password(self):
        old = self.inp_old.text()
        new = self.inp_new.text()
        conf = self.inp_conf.text()

        # [V4.5] ใช้ verify_settings_password เพื่อ hash + timing-safe compare
        if not verify_settings_password(old):
            QMessageBox.warning(self, "ผิดพลาด", "รหัสผ่านปัจจุบันไม่ถูกต้อง")
            return
        if not new or len(new) < 4:
            QMessageBox.warning(self, "ผิดพลาด", "รหัสผ่านใหม่ต้องยาวอย่างน้อย 4 ตัวอักษร")
            return
        if new != conf:
            QMessageBox.warning(self, "ผิดพลาด", "รหัสผ่านใหม่ไม่ตรงกัน")
            return

        # [V4.5] hash ก่อนเก็บเสมอ (เดิม plaintext)
        set_settings_password(new)
        self.inp_old.clear(); self.inp_new.clear(); self.inp_conf.clear()
        QMessageBox.information(self, "สำเร็จ", "เปลี่ยนรหัสผ่านเรียบร้อย")


# ─── Main Window ─────────────────────────────────────────────────────────────

class CustomHistoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"CustomHistory — KM Meter Tools  v{APP_VER}")
        self.resize(820, 600)
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(16, 12, 16, 12)
        main_lay.setSpacing(10)

        # Header
        hdr = QLabel(f"🛠  CustomHistory  —  ปรับแต่งการแสดงผล KM Meter Reader")
        hdr.setFont(fnt(F_2XL, True))
        hdr.setStyleSheet(f"color:{C_ACCENT}; padding-bottom:4px;")
        main_lay.addWidget(hdr)
        main_lay.addWidget(_hline())

        tabs = QTabWidget()
        tabs.setFont(fnt(F_LG))

        tabs.addTab(PageCurrentRows(),    "📋  ค่ามิเตอร์ปัจจุบัน")
        tabs.addTab(PageMonthlyColumns(), "📅  ย้อนหลังรายเดือน")
        tabs.addTab(PageStatCards(),      "🃏  Stat Cards")
        tabs.addTab(PagePassword(),       "🔒  รหัสผ่าน")

        main_lay.addWidget(tabs, 1)

        # Footer
        footer = QLabel(f"KM Meter Reader  |  version {APP_VER}  |  CustomHistory Tool")
        footer.setFont(fnt(F_XS))
        footer.setStyleSheet(f"color:{C_TEXT2};")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        main_lay.addWidget(footer)


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_SS)
    win = CustomHistoryWindow()
    win.show()
    sys.exit(app.exec())
