#!/usr/bin/env python3
"""
preview_colors.py — ดูตัวอย่างสี, ฟอนต์, ปุ่ม และ card ของโปรแกรมแบบ Live

แก้ค่าใน config.py แล้วรันโปรแกรมนี้ใหม่ → เห็นผลทันที
ไม่ต้องเปิดโปรแกรมหลักเพื่อเช็คว่าสีออกมาถูกต้องไหม

ใช้งาน:  python tools/preview_colors.py
"""

import sys
import re
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QFrame, QGridLayout, QTabWidget,
    QColorDialog, QMessageBox, QSpinBox, QPushButton, QFontComboBox, QLineEdit, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui  import QFont, QColor, QFontDatabase

import config
from widgets import fnt, btn, StatCard, badge

CONFIG_PATH = Path(__file__).parent.parent / "config.py"


def _text_color_for(hex_bg: str) -> tuple[str, str, str]:
    """คืน (fg_main, fg_sub, fg_hint) ที่อ่านง่ายที่สุดบนพื้น hex_bg"""
    c = QColor(hex_bg)
    # relative luminance (sRGB)
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    if lum > 0.45:   # พื้นสว่าง → ตัวอักษรดำ
        return ("rgba(0,0,0,0.85)", "rgba(0,0,0,0.60)", "rgba(0,0,0,0.38)")
    else:             # พื้นเข้ม → ตัวอักษรขาว
        return ("rgba(255,255,255,0.95)", "rgba(255,255,255,0.75)", "rgba(255,255,255,0.50)")


# ════════════════════════════════════════════════════════════
# HELPER WIDGETS
# ════════════════════════════════════════════════════════════

class Swatch(QFrame):
    """กล่องแสดงสี — คลิกเพื่อเปลี่ยนสีและบันทึกลง config.py"""
    need_refresh = pyqtSignal()  # emit หลังบันทึกสำเร็จ

    def __init__(self, name: str, color: str):
        super().__init__()
        self._name  = name
        self._hex   = color
        self.setFixedSize(170, 95)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"คลิกเพื่อเปลี่ยนสี {name}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        fg_main, fg_sub, fg_hint = _text_color_for(color)

        # ชื่อตัวแปร เช่น C_ACCENT
        lbl_name = QLabel(name)
        lbl_name.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        lbl_name.setStyleSheet(f"color: {fg_main}; background: transparent; border: none;")
        lbl_name.setWordWrap(True)

        # ค่า hex เช่น #123262
        self._lbl_val = QLabel(color)
        self._lbl_val.setFont(QFont("Courier New", 9))
        self._lbl_val.setStyleSheet(f"color: {fg_sub}; background: transparent; border: none;")

        # hint คลิกได้
        self._lbl_hint = QLabel("✏️ คลิกเพื่อแก้")
        self._lbl_hint.setFont(QFont("Courier New", 8))
        self._lbl_hint.setStyleSheet(f"color: {fg_hint}; background: transparent; border: none;")

        lay.addWidget(lbl_name)
        lay.addWidget(self._lbl_val)
        lay.addWidget(self._lbl_hint)

        self._lbl_name = lbl_name
        self._apply_style()

    def _apply_style(self):
        fg_main, fg_sub, fg_hint = _text_color_for(self._hex)
        # อัปเดตสีตัวอักษรทุกครั้งที่สีพื้นเปลี่ยน
        if hasattr(self, "_lbl_name"):
            self._lbl_name.setStyleSheet(f"color: {fg_main}; background: transparent; border: none;")
            self._lbl_val.setStyleSheet(f"color: {fg_sub}; background: transparent; border: none;")
            self._lbl_hint.setStyleSheet(f"color: {fg_hint}; background: transparent; border: none;")
        c = QColor(self._hex)
        lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        hover_border = "rgba(0,0,0,0.4)" if lum > 0.45 else "rgba(255,255,255,0.6)"
        self.setStyleSheet(f"""
            QFrame {{
                background: {self._hex};
                border-radius: 8px;
                border: 1px solid rgba(0,0,0,0.15);
            }}
            QFrame:hover {{
                border: 2px solid {hover_border};
            }}
        """)

    def mousePressEvent(self, event):
        dlg = QColorDialog(QColor(self._hex), self)
        dlg.setWindowTitle(f"เลือกสีสำหรับ  {self._name}")
        if dlg.exec():
            new_hex = dlg.currentColor().name().upper()
            self._write_to_config(new_hex)

    def _write_to_config(self, new_hex: str):
        try:
            text = CONFIG_PATH.read_text(encoding="utf-8")
            
            # Handle Machine_i pattern
            if self._name.startswith("Machine_"):
                idx = int(self._name.split("_")[1])
                pattern = rf'(GRAPH_COLORS_MACHINE\s*=\s*\[\s*(?:["\']#[0-9A-Fa-f]{{6}}["\'],\s*)*?)("[#][0-9A-Fa-f]{{6}}")(\s*(?:,\s*["\']#[0-9A-Fa-f]{{6}}["\'])*)'
                # Better: just replace the specific index
                lines = text.split('\n')
                new_lines = []
                in_machine_colors = False
                machine_idx = 0
                for line in lines:
                    if 'GRAPH_COLORS_MACHINE' in line and '=' in line and '[' in line:
                        in_machine_colors = True
                    if in_machine_colors and '"#' in line:
                        if machine_idx == idx:
                            line = re.sub(r'"#[0-9A-Fa-f]{6}"', f'"{new_hex}"', line)
                        machine_idx += 1
                    if in_machine_colors and ']' in line:
                        in_machine_colors = False
                    new_lines.append(line)
                text = '\n'.join(new_lines)
            
            # Handle Type_* pattern
            elif self._name.startswith("Type_"):
                type_key = self._name.replace("Type_", "")
                pattern = rf'(\"{type_key}\"\s*:\s*)"#[0-9A-Fa-f]{{6}}"'
                text, n = re.subn(pattern, rf'\g<1>"{new_hex}"', text)
                if n == 0:
                    QMessageBox.warning(self, "ไม่พบตัวแปร",
                        f"ไม่พบ {type_key} ใน GRAPH_COLORS_TYPE")
                    return
            
            # Handle regular C_* or other variables
            else:
                new_text, n = re.subn(
                    rf'({re.escape(self._name)}\s*=\s*")[^"]*"',
                    rf'\g<1>{new_hex}"',
                    text,
                )
                if n == 0:
                    QMessageBox.warning(self, "ไม่พบตัวแปร",
                        f"ไม่พบ  {self._name}  ใน config.py")
                    return
                text = new_text
            
            CONFIG_PATH.write_text(text, encoding="utf-8")
            self._hex = new_hex
            self._lbl_val.setText(new_hex)
            self._apply_style()
            self.need_refresh.emit()
        except Exception as ex:
            QMessageBox.critical(self, "เกิดข้อผิดพลาด", str(ex))


def section_label(text: str) -> QLabel:
    """หัวข้อย่อยใน tab"""
    lbl = QLabel(text)
    lbl.setFont(fnt(config.F_LG, bold=True))
    lbl.setStyleSheet(f"color: {config.C_TEXT2}; padding: 4px 0;")
    return lbl


def divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {config.C_BORDER}; max-height: 1px;")
    return f


# ════════════════════════════════════════════════════════════
# TABS
# ════════════════════════════════════════════════════════════

def make_scrollable(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidget(inner)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    return scroll


def tab_colors(on_refresh=None) -> QWidget:
    """Tab 1: แสดง swatch ของทุก C_* constant — คลิก swatch เพื่อแก้สี"""
    container = QWidget()
    grid = QGridLayout(container)
    grid.setSpacing(12)
    grid.setContentsMargins(20, 20, 20, 20)

    # ดึงเฉพาะ C_* ที่เป็นสีเท่านั้น
    color_vars = sorted(
        [(k, v) for k, v in vars(config).items()
         if k.startswith("C_") and isinstance(v, str) and v.startswith("#")],
        key=lambda x: x[0]
    )

    COLS = 5
    for i, (name, val) in enumerate(color_vars):
        sw = Swatch(name, val)
        if on_refresh:
            sw.need_refresh.connect(on_refresh)
        grid.addWidget(sw, i // COLS, i % COLS)

    # padding ด้านล่าง
    grid.setRowStretch(len(color_vars) // COLS + 1, 1)
    return make_scrollable(container)


def tab_fonts(on_refresh=None) -> QWidget:
    """Tab 2: เลือกฟอนต์หลัก + ปรับขนาด F_* — live preview + บันทึก"""
    container = QWidget()
    outer = QVBoxLayout(container)
    outer.setContentsMargins(20, 20, 20, 20)
    outer.setSpacing(10)

    # ── เลือกฟอนต์หลัก (DEFAULT_FONT_NAME) ──────────────────────────
    outer.addWidget(section_label("เลือกฟอนต์หลักโปรแกรม (DEFAULT_FONT_NAME)"))
    outer.addWidget(divider())

    font_sel_row = QHBoxLayout()
    font_sel_row.setSpacing(12)

    lbl_fn = QLabel("DEFAULT_FONT_NAME")
    lbl_fn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
    lbl_fn.setStyleSheet(f"color:{config.C_TEXT3};")
    lbl_fn.setFixedWidth(190)

    font_combo = QFontComboBox()
    font_combo.setFixedWidth(280)
    font_combo.setCurrentFont(QFont(config.DEFAULT_FONT_NAME))
    font_combo.setEditable(True)
    font_combo.setToolTip("เลือกฟอนต์ หรือพิมพ์ชื่อฟอนต์ที่ต้องการ")

    lbl_font_preview = QLabel("สวัสดี  AaBbCc 0123  คุณภาพดี")
    lbl_font_preview.setFont(QFont(config.DEFAULT_FONT_NAME, config.F_LG))
    lbl_font_preview.setStyleSheet(f"color:{config.C_TEXT};")

    def _font_live():
        name = font_combo.currentFont().family()
        lbl_font_preview.setFont(QFont(name, config.F_LG))
        lbl_fn.setStyleSheet(f"color:{config.C_ORANGE}; font-weight:bold;")
    font_combo.currentFontChanged.connect(lambda _: _font_live())

    font_sel_row.addWidget(lbl_fn)
    font_sel_row.addWidget(font_combo)
    font_sel_row.addWidget(lbl_font_preview)
    font_sel_row.addStretch()
    outer.addLayout(font_sel_row)

    # ── chip ฟอนต์แนะนำที่มีในระบบ (Mac + Windows) ─────────────────
    sys_fonts = set(QFontDatabase.families())
    suggested = [f for f in [
        # macOS
        "SF Pro", "SF Pro Display", "SF Pro Text", "Helvetica Neue",
        "Helvetica", "Thonburi", "Ayuthaya", "Krungthep",
        # Windows
        "Segoe UI", "Segoe UI Variable", "Tahoma", "Verdana",
        "Calibri", "Trebuchet MS", "Leelawadee UI", "Leelawadee",
        # Cross-platform
        "Arial", "IBM Plex Sans Thai", "Noto Sans Thai",
    ] if f in sys_fonts]

    if suggested:
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        chip_row.addWidget(QLabel("💡 แนะนำ:"))
        chip_row.itemAt(0).widget().setStyleSheet(
            f"color:{config.C_TEXT2}; font-size:{config.F_SM}pt;")
        for fname in suggested[:9]:
            chip = QPushButton(fname)
            chip.setFixedHeight(26)
            chip.setStyleSheet(
                f"QPushButton {{border:1px solid {config.C_BORDER}; border-radius:13px;"
                f" padding:0 10px; background:white; color:{config.C_TEXT};"
                f" font-size:{config.F_SM}pt;}}"
                f"QPushButton:hover {{background:{config.C_ACCENT}; color:white;"
                f" border-color:{config.C_ACCENT};}}"
            )
            chip.clicked.connect(lambda _, f=fname: (
                font_combo.setCurrentFont(QFont(f)),
                _font_live(),
            ))
            chip_row.addWidget(chip)
        chip_row.addStretch()
        outer.addLayout(chip_row)

    outer.addSpacing(12)
    outer.addWidget(divider())

    # ── ขนาดฟอนต์ (F_*) ─────────────────────────────────────────────
    outer.addWidget(section_label("ขนาดฟอนต์ (F_*) — ปรับตัวเลข แล้วกด 💾 บันทึก"))
    outer.addWidget(divider())

    font_vars = sorted(
        [(k, v) for k, v in vars(config).items()
         if k.startswith("F_") and isinstance(v, int)],
        key=lambda x: x[1]
    )
    spinboxes: dict[str, QSpinBox] = {}

    for name, size in font_vars:
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setSpacing(14)
        row.setContentsMargins(0, 0, 0, 0)

        lbl_key = QLabel(name)
        lbl_key.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl_key.setFixedWidth(90)
        lbl_key.setStyleSheet(f"color: {config.C_TEXT3};")

        sb = QSpinBox()
        sb.setRange(6, 72)
        sb.setValue(size)
        sb.setFixedWidth(64)
        sb.setToolTip(f"ขนาดปัจจุบัน: {size}  (range 6–72)")
        spinboxes[name] = sb

        lbl_sample = QLabel("สวัสดี AaBbCc 0123")
        lbl_sample.setFont(QFont(config.DEFAULT_FONT_NAME, size))
        lbl_sample.setStyleSheet(f"color: {config.C_TEXT};")
        lbl_sample.setFixedWidth(260)

        lbl_bold = QLabel("Bold — ตัวหนา")
        lbl_bold.setFont(QFont(config.DEFAULT_FONT_NAME, size, QFont.Weight.Bold))
        lbl_bold.setStyleSheet(f"color: {config.C_ACCENT};")

        def _live(val, ls=lbl_sample, lb=lbl_bold, lk=lbl_key):
            f = font_combo.currentFont().family()
            ls.setFont(QFont(f, val))
            lb.setFont(QFont(f, val, QFont.Weight.Bold))
            lk.setStyleSheet(f"color: {config.C_ORANGE}; font-weight: bold;")
        sb.valueChanged.connect(_live)
        font_combo.currentFontChanged.connect(
            lambda _, sb=sb, ls=lbl_sample, lb=lbl_bold: _live(sb.value(), ls, lb))

        row.addWidget(lbl_key)
        row.addWidget(sb)
        row.addWidget(lbl_sample)
        row.addWidget(lbl_bold)
        row.addStretch()
        outer.addWidget(row_w)

    outer.addSpacing(12)
    outer.addWidget(divider())

    # ── ปุ่มบันทึก ───────────────────────────────────────────────────
    def _save_fonts():
        try:
            text = CONFIG_PATH.read_text(encoding="utf-8")
            new_font_name = font_combo.currentFont().family()
            text, _ = re.subn(
                r'(DEFAULT_FONT_NAME\s*=\s*")[^"]*"',
                rf'\g<1>{new_font_name}"',
                text,
            )
            for var_name, sb in spinboxes.items():
                text, _ = re.subn(
                    rf'({re.escape(var_name)}\s*=\s*)\d+',
                    lambda m, v=sb.value(): m.group(1) + str(v),
                    text,
                )
            CONFIG_PATH.write_text(text, encoding="utf-8")
            if on_refresh:
                importlib.reload(config)
                on_refresh()
        except Exception as ex:
            QMessageBox.critical(None, "เกิดข้อผิดพลาด", str(ex))

    btn_save = QPushButton("💾  บันทึกลง config.py")
    btn_save.setObjectName("btn_primary")
    btn_save.setFixedWidth(220)
    btn_save.clicked.connect(_save_fonts)

    btn_reset = QPushButton("↩  รีเซ็ต")
    btn_reset.setObjectName("btn_outline")
    btn_reset.setFixedWidth(100)
    def _reset_fonts():
        if on_refresh:
            importlib.reload(config)
            on_refresh()
    btn_reset.clicked.connect(_reset_fonts)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_row.addWidget(btn_reset)
    btn_row.addWidget(btn_save)
    outer.addLayout(btn_row)
    outer.addStretch()
    return make_scrollable(container)


def tab_buttons(on_refresh=None) -> QWidget:
    """Tab 3: แสดงปุ่มทุก style — แก้สีได้ผ่าน swatch ด้านล่าง"""
    container = QWidget()
    lay = QVBoxLayout(container)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(20)

    lay.addWidget(section_label("ปุ่มทุก style  —  btn('ข้อความ', style)"))
    lay.addWidget(divider())

    styles = ["primary", "outline", "danger", "success", "warning"]
    for style in styles:
        row = QHBoxLayout()
        row.setSpacing(20)

        b = btn(f"  {style}  ", style)
        b.setFixedWidth(140)

        lbl = QLabel(f'btn("ข้อความ", "{style}")')
        lbl.setFont(QFont("Courier New", 11))
        lbl.setStyleSheet(f"color: {config.C_TEXT2};")

        row.addWidget(b)
        row.addWidget(lbl)
        row.addStretch()
        lay.addLayout(row)

    lay.addSpacing(12)
    lay.addWidget(divider())
    lay.addWidget(section_label("สีที่ใช้ในปุ่ม — คลิก swatch เพื่อแก้"))
    lay.addWidget(divider())

    btn_color_keys = ["C_ACCENT", "C_RED", "C_GREEN", "C_ORANGE", "C_YELLOW"]
    swatch_row = QHBoxLayout()
    swatch_row.setSpacing(12)
    for key in btn_color_keys:
        val = getattr(config, key, None)
        if val:
            sw = Swatch(key, val)
            if on_refresh:
                sw.need_refresh.connect(on_refresh)
            swatch_row.addWidget(sw)
    swatch_row.addStretch()
    lay.addLayout(swatch_row)

    lay.addStretch()
    return make_scrollable(container)


def tab_cards(on_refresh=None) -> QWidget:
    """Tab 4: StatCard, Badge — แก้สีได้ผ่าน swatch ด้านล่าง"""
    container = QWidget()
    lay = QVBoxLayout(container)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.setSpacing(16)

    # ── StatCard ──────────────────────────────────────────
    lay.addWidget(section_label("StatCard — ใช้ใน PageOverview / PageHistory"))
    lay.addWidget(divider())

    card_row = QHBoxLayout()
    card_row.setSpacing(12)
    cards_data = [
        ("ยอดพิมพ์รวม", config.C_ACCENT,  42300, 1250),
        ("A4 สี",       config.C_ORANGE,  18500,  870),
        ("A4 ขาวดำ",    config.C_TEXT2,   23800,  380),
        ("ค่าใช้จ่าย",  config.C_GREEN,   None,   None),
    ]
    for title, color, val, diff in cards_data:
        sc = StatCard(title, color)
        if val is not None:
            sc.set_value(val, diff)
        else:
            sc.set_baht(1234.50)
        card_row.addWidget(sc)
    card_row.addStretch()
    lay.addLayout(card_row)

    # ── Badge ─────────────────────────────────────────────
    lay.addSpacing(8)
    lay.addWidget(section_label("badge() — ป้ายแสดงสถานะ"))
    lay.addWidget(divider())

    badge_row = QHBoxLayout()
    badge_row.setSpacing(8)
    badge_data = [
        ("USER",   config.C_ACCENT),
        ("SUM",    config.C_GREEN),
        ("PROD",   config.C_ORANGE),
        ("ซ้ำ",    config.C_RED),
        ("คำเตือน", config.C_YELLOW),
        ("ปกติ",   config.C_PURPLE),
    ]
    for text, color in badge_data:
        badge_row.addWidget(badge(text, color))
    badge_row.addStretch()
    lay.addLayout(badge_row)

    # ── สีที่ใช้ใน card/badge แก้ได้ที่นี่ ────────────────
    lay.addSpacing(12)
    lay.addWidget(divider())
    lay.addWidget(section_label("สีที่ใช้ใน Card และ Badge — คลิก swatch เพื่อแก้"))
    lay.addWidget(divider())

    card_color_keys = ["C_ACCENT", "C_ORANGE", "C_TEXT2", "C_GREEN",
                       "C_RED", "C_YELLOW", "C_PURPLE"]
    sw_row = QHBoxLayout()
    sw_row.setSpacing(12)
    for key in card_color_keys:
        val = getattr(config, key, None)
        if val:
            sw = Swatch(key, val)
            if on_refresh:
                sw.need_refresh.connect(on_refresh)
            sw_row.addWidget(sw)
    sw_row.addStretch()
    lay.addLayout(sw_row)

    lay.addStretch()
    return make_scrollable(container)


def tab_graph(on_refresh=None) -> QWidget:
    """Tab 5: Graph Customization — ปรับขนาด font, สี bar, และ settings อื่นๆ"""
    container = QWidget()
    lay = QVBoxLayout(container)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.setSpacing(14)

    # ── Font Sizes ─────────────────────────────────────────
    lay.addWidget(section_label("📐 ขนาด Font ในกราฟ"))
    lay.addWidget(divider())

    graph_font_vars = [
        ("GRAPH_TITLE_SIZE", "ขนาด title"),
        ("GRAPH_AXIS_LABEL_SIZE", "ขนาด axis labels"),
        ("GRAPH_TOOLTIP_SIZE", "ขนาด tooltip"),
        ("GRAPH_VALUE_SIZE", "ขนาด ค่าบน bar"),
    ]
    font_spinboxes = {}

    for var_name, label in graph_font_vars:
        val = getattr(config, var_name, 12)
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setSpacing(12)
        row.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setFont(QFont("Courier New", 10))
        lbl.setFixedWidth(160)
        lbl.setStyleSheet(f"color: {config.C_TEXT2};")

        sb = QSpinBox()
        sb.setRange(8, 48)
        sb.setValue(val)
        sb.setFixedWidth(70)
        sb.setSuffix(" pt")
        font_spinboxes[var_name] = sb

        lbl_preview = QLabel(f"ตัวอย่าง font {val}pt")
        lbl_preview.setFont(QFont(config.DEFAULT_FONT_NAME, val))
        lbl_preview.setStyleSheet(f"color:{config.C_TEXT};")

        def _live(v, preview=lbl_preview, size_var=var_name):
            preview.setFont(QFont(config.DEFAULT_FONT_NAME, v))
        sb.valueChanged.connect(_live)

        row.addWidget(lbl)
        row.addWidget(sb)
        row.addWidget(lbl_preview)
        row.addStretch()
        lay.addWidget(row_w)

    lay.addSpacing(8)
    lay.addWidget(divider())

    # ── Bar Settings ──────────────────────────────────────
    lay.addWidget(section_label("📊 ตั้งค่า Bar Chart"))
    lay.addWidget(divider())

    bar_settings = [
        ("GRAPH_BAR_WIDTH", "ความกว้าง bar (0-1)", 0, 1, 0.01),
        ("GRAPH_GRID_ALPHA", "ความโปร่งใส grid (0-1)", 0, 1, 0.05),
    ]
    bar_spinboxes = {}

    for var_name, label, min_v, max_v, step in bar_settings:
        val = getattr(config, var_name, 0.5)
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setSpacing(12)
        row.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setFont(QFont("Courier New", 10))
        lbl.setFixedWidth(160)
        lbl.setStyleSheet(f"color: {config.C_TEXT2};")

        sb = QDoubleSpinBox()
        sb.setRange(min_v, max_v)
        sb.setValue(val)
        sb.setDecimals(2)
        sb.setSingleStep(step)
        sb.setFixedWidth(90)
        bar_spinboxes[var_name] = sb

        lbl_val = QLabel(f"{val:.2f}")
        lbl_val.setFixedWidth(60)

        def _live_bar(v, lv=lbl_val):
            lv.setText(f"{v:.2f}")
        sb.valueChanged.connect(_live_bar)

        row.addWidget(lbl)
        row.addWidget(sb)
        row.addWidget(lbl_val)
        row.addStretch()
        lay.addWidget(row_w)

    lay.addSpacing(8)
    lay.addWidget(divider())

    # ── สี Bar ─────────────────────────────────────────────
    lay.addWidget(section_label("🎨 สีที่ใช้ใน Bar Chart"))
    lay.addWidget(divider())

    # Machine colors
    lay.addWidget(QLabel("สี Machine (by_machine view)"))
    machine_colors = getattr(config, "GRAPH_COLORS_MACHINE", ["#2563EB", "#DC2626", "#16A34A"])
    machine_row = QHBoxLayout()
    machine_row.setSpacing(8)
    for i, color in enumerate(machine_colors):
        sw = Swatch(f"Machine_{i}", color)
        if on_refresh:
            sw.need_refresh.connect(on_refresh)
        machine_row.addWidget(sw)
    machine_row.addStretch()
    lay.addLayout(machine_row)

    # Type colors
    lay.addSpacing(8)
    lay.addWidget(QLabel("สี Type (by_type view)"))
    type_colors_dict = getattr(config, "GRAPH_COLORS_TYPE", {})
    type_row = QHBoxLayout()
    type_row.setSpacing(8)
    type_keys = ["copy_color", "copy_bw", "print_color", "print_bw"]
    type_labels = {"copy_color": "Copy สี", "copy_bw": "Copy ขาวดำ", 
                   "print_color":"Print สี", "print_bw":"Print ขาวดำ"}
    for key in type_keys:
        color = type_colors_dict.get(key, "#000000")
        sw = Swatch(f"Type_{key}", color)
        if on_refresh:
            sw.need_refresh.connect(on_refresh)
        type_row.addWidget(sw)
    type_row.addStretch()
    lay.addLayout(type_row)

    # Tooltip colors
    lay.addSpacing(8)
    lay.addWidget(QLabel("สี Tooltip"))
    tooltip_row = QHBoxLayout()
    tooltip_row.setSpacing(8)
    for key in ["GRAPH_TOOLTIP_COLOR", "GRAPH_TOOLTIP_BG"]:
        val = getattr(config, key, "#000000")
        sw = Swatch(key, val)
        if on_refresh:
            sw.need_refresh.connect(on_refresh)
        tooltip_row.addWidget(sw)
    tooltip_row.addStretch()
    lay.addLayout(tooltip_row)

    lay.addSpacing(12)
    lay.addWidget(divider())

    # ── ปุ่มบันทึก ────────────────────────────────────────
    def _save_graph_settings():
        try:
            text = CONFIG_PATH.read_text(encoding="utf-8")
            # Update font sizes
            for var_name, sb in font_spinboxes.items():
                text, _ = re.subn(
                    rf'({re.escape(var_name)}\s*=\s*)\d+',
                    lambda m, v=sb.value(): m.group(1) + str(v),
                    text,
                )
            # Update bar settings
            for var_name, sb in bar_spinboxes.items():
                text, _ = re.subn(
                    rf'({re.escape(var_name)}\s*=\s*)[\d.]+',
                    lambda m, v=sb.value(): m.group(1) + f"{v:.2f}",
                    text,
                )
            CONFIG_PATH.write_text(text, encoding="utf-8")
            if on_refresh:
                importlib.reload(config)
                on_refresh()
            QMessageBox.information(None, "สำเร็จ", "บันทึกการตั้งค่ากราฟเรียบร้อยแล้ว")
        except Exception as ex:
            QMessageBox.critical(None, "เกิดข้อผิดพลาด", str(ex))

    btn_save = QPushButton("💾  บันทึกลง config.py")
    btn_save.setObjectName("btn_primary")
    btn_save.setFixedWidth(220)
    btn_save.clicked.connect(_save_graph_settings)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_row.addWidget(btn_save)
    lay.addLayout(btn_row)
    lay.addStretch()
    return make_scrollable(container)


# ════════════════════════════════════════════════════════════
# MAIN WINDOW
# ════════════════════════════════════════════════════════════

class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Config Preview — preview_colors.py")
        self.setMinimumSize(960, 680)
        self.resize(1100, 750)

        self._tabs = QTabWidget()
        self._tabs.setFont(fnt(config.F_LG))
        self.setCentralWidget(self._tabs)
        self._rebuild_tabs()

    def _rebuild_tabs(self):
        """สร้าง (หรือสร้างใหม่) ทุก tab — เรียกหลัง reload config"""
        current = self._tabs.currentIndex()
        self._tabs.clear()
        self.setStyleSheet(config.build_qss())
        self._tabs.setFont(fnt(config.F_LG))
        cb = self._on_color_changed
        self._tabs.addTab(tab_colors(on_refresh=cb),  "🎨  สี (C_*)")
        self._tabs.addTab(tab_fonts(on_refresh=cb),   "🔤  ฟอนต์ (F_*)")
        self._tabs.addTab(tab_buttons(on_refresh=cb), "🔘  ปุ่ม (btn)")
        self._tabs.addTab(tab_cards(on_refresh=cb),   "📊  Cards & Badges")
        self._tabs.addTab(tab_graph(on_refresh=cb),   "📈  Graph Settings")
        if current >= 0:
            self._tabs.setCurrentIndex(current)

    def _on_color_changed(self):
        """Swatch บันทึกแล้ว → reload config → rebuild ทุก tab"""
        importlib.reload(config)
        self._rebuild_tabs()
        self.statusBar().showMessage("✅  บันทึกและอัปเดต config.py เรียบร้อยแล้ว", 3000)


# ════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(fnt(config.F_MD))
    win = PreviewWindow()
    win.statusBar().showMessage("คลิกที่ swatch สีใดก็ได้เพื่อแก้ไขและบันทึกลง config.py")
    win.show()
    sys.exit(app.exec())
