"""Application stylesheet rules."""

from . import tokens
from .navigation import page_tabs_qss


def build_qss():
    return f"""
/* ── พื้นฐาน ── */
QMainWindow, QDialog {{
    background: {tokens.C_BG};
    color: {tokens.C_TEXT};
    font-family: {tokens.QSS_FONT_FAMILY};
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: #F5F5F5; width: 7px; border: none; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: #A6A6A6; border: none; border-radius: 4px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: #7A7A7A; }}
QScrollBar::handle:vertical:pressed {{ background: #5F5F5F; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: #F5F5F5; border: none;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0; background: transparent; border: none;
}}
QScrollBar:horizontal {{
    background: #F5F5F5; height: 7px; border: none; border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: #A6A6A6; border: none; border-radius: 4px; min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{ background: #7A7A7A; }}
QScrollBar::handle:horizontal:pressed {{ background: #5F5F5F; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: #F5F5F5; border: none;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0; background: transparent; border: none;
}}
QToolTip {{
    background: {tokens.C_SIDEBAR}; color: #ffffff;
    border: none; padding: 4px 8px; border-radius: 4px;
    font-size: {tokens.F_SM}pt;
}}

QWidget {{ color: {tokens.C_TEXT}; font-family: {tokens.QSS_FONT_FAMILY}; }}
QLabel {{ background: transparent; }}

/* ── Shared button geometry ── */
QPushButton {{
    background: #FFFFFF; color: {tokens.C_TEXT}; border: 1px solid {tokens.C_BORDER};
    border-radius: {tokens.BUTTON_RADIUS}px;
    padding: 7px 16px;
    font-size: {tokens.F_LG}pt;
    font-weight: 600;
}}

/* ── Sidebar ── */
QWidget#sidebar {{ background: {tokens.C_SIDEBAR}; }}
QComboBox#language_selector {{
    background: #183B5B;
    color: #FFFFFF;
    border: 1px solid #315A7C;
    padding: 7px 10px;
}}
QComboBox#language_selector QAbstractItemView {{
    background: #FFFFFF;
    color: {tokens.C_TEXT};
}}
QComboBox#wizard_language_selector {{
    min-width: 110px;
    background: #FFFFFF;
    border: 1px solid #B8C8D8;
}}

/* ── ปุ่ม nav ใน sidebar ── */
/* แก้สีปุ่ม nav ที่นี่: background / color / active */
QPushButton#nav {{
    background: transparent;
    color: #C5D5E4;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 14px;
    font-size: {tokens.F_XL}pt;
    font-weight: 500;
}}
QPushButton#nav:hover {{
    background: {tokens.C_SB_H};
    color: #ffffff;
}}
QPushButton#nav[active=true] {{
    background: #E9F3FA;   /* ← สีปุ่ม nav ที่เลือกอยู่ */
    color: #0B5E93;
    font-weight: 700;
}}

/* ── การ์ด ── */
QFrame#card {{
    background: {tokens.C_CARD};
    border: 1px solid {tokens.C_BORDER};
    border-radius: 12px;
}}
QFrame#stat_card {{
    background: {tokens.C_CARD};
    border: 1px solid {tokens.C_BORDER};
    border-radius: 12px;
}}
QFrame#preview_card {{
    background: #FFFBEB;
    border: 2px solid #FCD34D;
    border-radius: 10px;
}}
QFrame#warn_card {{
    background: #FEF2F2;
    border: 2px solid {tokens.C_RED};
    border-radius: 10px;
}}

/* ── ตาราง ── */
QTableWidget {{
    background: {tokens.C_CARD};
    border: 1px solid {tokens.C_TABLE_BORDER};
    border-radius: 8px;
    gridline-color: {tokens.C_TABLE_BORDER};
    font-size: {tokens.F_LG}pt;
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
}}
QTableWidget::item:selected {{
    background: {tokens.C_TABLE_SELECTED};
    color: {tokens.C_TEXT};
}}
QTableWidget::item:alternate {{
    background: {tokens.C_TABLE_ALT};
}}
QHeaderView::section {{
    background: {tokens.C_TABLE_HEADER};
    color: {tokens.C_TABLE_HEADER_TEXT};
    font-size: {tokens.F_MD}pt;
    font-weight: 600;
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid {tokens.C_TABLE_BORDER};
    border-right: 1px solid {tokens.C_TABLE_BORDER};
}}

/* ── Input / ComboBox ── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit {{
    background: white;
    border: 1.5px solid {tokens.C_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    font-size: {tokens.F_LG}pt;
    color: {tokens.C_TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QDateEdit:focus {{
    border-color: {tokens.C_ACCENT};
}}
QPushButton:focus {{
    border: 2px solid {tokens.C_ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {tokens.C_BORDER};
    selection-background-color: #e8f0f7; color: {tokens.C_TEXT};
}}

/* ── ปุ่มหลัก (Primary) — สีน้ำเงิน = เลือกอยู่ ── */
QPushButton#btn_primary {{
    background: {tokens.C_ACCENT};
    color: #FFFFFF;
    border: 1px solid {tokens.C_ACCENT};
    border-radius: 8px;
    padding: 7px 16px;
    font-size: {tokens.F_LG}pt;
    font-weight: 700;
}}
QPushButton#btn_primary:hover {{ background: #017DD0; color: #FFFFFF; border-color: #017DD0; }}
QPushButton#btn_primary:pressed {{ background: #074A76; color: #FFFFFF; border-color: #074A76; }}
QPushButton#btn_primary:disabled {{ background: #E8EEF4; color: #52677D; border-color: #C2CFDB; }}

/* ── ปุ่ม Outline ── */
QPushButton#btn_outline {{
    background: #FFFFFF; color: #24506E;
    border: 1px solid #B8C8D8; border-radius: 8px;
    padding: 7px 16px; font-size: {tokens.F_LG}pt; font-weight: 600;
}}
QPushButton#btn_outline:hover {{
    background: #dbeafe; color: #123262;
    border-color: #93c5fd;
}}
QPushButton#btn_outline:pressed {{
    background: #bfdbfe; color: #123262;
    border-color: #60a5fa;
}}

/* Semantic actions share geometry with the default button. */
QPushButton#btn_danger {{ background: #FFF1F2; color: #9F1239; border: 1px solid #FDA4AF; }}
QPushButton#btn_danger:hover {{ background: #FFE4E6; }}
QPushButton#btn_danger:pressed {{ background: #FECDD3; }}
QPushButton#btn_success {{ background: #ECFDF5; color: #065F46; border: 1px solid #6EE7B7; }}
QPushButton#btn_success:hover {{ background: #D1FAE5; }}
QPushButton#btn_success:pressed {{ background: #A7F3D0; }}
QPushButton#btn_warning {{ background: #FFFBEB; color: #92400E; border: 1px solid #FCD34D; }}
QPushButton#btn_warning:hover {{ background: #FEF3C7; }}
QPushButton#btn_warning:pressed {{ background: #FDE68A; }}
QPushButton:disabled, QPushButton#btn_primary:disabled,
QPushButton#btn_outline:disabled, QPushButton#btn_danger:disabled,
QPushButton#btn_success:disabled, QPushButton#btn_warning:disabled {{
    background: #EDF1F5; color: #66788A; border: 1px dashed #B8C8D8;
}}
QPushButton#nav:disabled {{ background: #203D56; color: #91A6B7; border: 1px dashed #56748D; }}
QPushButton#nav:focus, QPushButton#nav[active=true]:focus {{ border: 2px solid #69C7FF; }}
QPushButton#btn_primary:focus, QPushButton#btn_outline:focus,
QPushButton#btn_danger:focus, QPushButton#btn_success:focus,
QPushButton#btn_warning:focus {{ border: 2px solid #0284C7; }}

/* ── Checkbox ──
   Keep the native platform indicator so checked state always has a visible
   checkmark, including high-contrast and accessibility modes. */
QCheckBox {{ font-size: {tokens.F_LG}pt; spacing: 7px; }}

/* ── Tab Widget ── */
{page_tabs_qss()}

/* ── SpinBox arrows ── */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 18px; border: none;
}}
"""
