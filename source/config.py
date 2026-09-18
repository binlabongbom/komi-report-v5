# ═══════════════════════════════════════════════════════════
# config.py  —  ค่าคงที่ / สี / ฟอนต์ / สไตล์ทั้งหมด
# แก้ไขที่นี่ที่เดียวเพื่อเปลี่ยนหน้าตาโปรแกรม
# ═══════════════════════════════════════════════════════════

import sys

from komi_version import APP_VERSION
from runtime_config import RUNTIME_SETTINGS


IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")


def _platform_value(default, *, windows=None, macos=None, linux=None):
    if IS_WINDOWS and windows is not None:
        return windows
    if IS_MACOS and macos is not None:
        return macos
    if linux is not None:
        return linux
    return default

# ─── ข้อมูลโปรแกรม ────────────────────────────────────────
APP_TITLE = "KOMI Report"              # ชื่อโปรแกรม (แสดงใน title bar)
APP_VER   = APP_VERSION                  # เวอร์ชันที่แสดงใน Desktop UI
PACKAGE_VERSION = APP_VERSION            # เวอร์ชัน build/API (ตรงกับ authority)
LOGO_TEXT = "🖨  KOMI Report"                  # ข้อความโลโก้ใน sidebar
LOGO_SUB  = "Konica Minolta"               # ข้อความใต้โลโก้

# ─── Database ─────────────────────────────────────────────
DB_PATH  = RUNTIME_SETTINGS.db_path  # environment > runtime.toml > local default
MAX_HIST = 120                                     # จำนวนเรคอร์ดสูงสุดต่อเครื่อง

# ─── ชื่อและสีแต่ละเครื่อง ────────────────────────────────
# SLOT_COLORS = สีหลัก (ปุ่ม, ขอบการ์ด, จุดสี)
# SLOT_LIGHT  = สีพื้นอ่อน (badge, highlight)
# SLOT_NAMES  = ชื่อตั้งต้น (ผู้ใช้เปลี่ยนได้ในหน้า ตั้งค่า)
SLOT_COLORS = ["#2563EB", "#DC2626", "#16A34A"]   # น้ำเงิน / แดง / เขียว
SLOT_LIGHT  = ["#DBEAFE", "#FEE2E2", "#DCFCE7"]
SLOT_NAMES  = ["เครื่อง 1", "เครื่อง 2", "เครื่อง 3"]

# ─── Palette โทนสว่าง ─────────────────────────────────────
# เปลี่ยนสีพื้นหลัง หรือสีข้อความได้ที่นี่
C_BG      = "#F0F0F0"   # พื้นหลังหลัก
C_SIDEBAR = "#102A43"   # sidebar (โทนสีเข้ม)
C_SB_H    = "#183B5B"   # sidebar hover
C_CARD    = "#ffffff"   # พื้นหลังการ์ด
C_BORDER  = "#919191"   # เส้นขอบการ์ดและพื้นผิวหลัก
C_TABLE_BORDER = "#E3E3E3"
C_TABLE_HEADER = "#00284D"
C_TABLE_HEADER_TEXT = "#FFFFFF"
C_TABLE_ALT = "#FAFAFA"
C_TABLE_SELECTED = "#D5E6FB"
C_TONER_TRACK = "#F8FAFC"
C_TONER_BORDER = "#D1D1D1"
C_TONER_C = "#009DC4"
C_TONER_Y = "#B28700"
C_TONER_M = "#D81B60"
C_TONER_K = "#1F2937"
C_STATUS_ONLINE = "#00A651"
C_STATUS_PENDING = "#F5C000"
C_STATUS_OFFLINE = "#D71920"
C_EMPTY_BG = "#F8FAFC"
C_TEXT    = "#191919"   # ข้อความหลัก
C_TEXT2   = "#505050"   # ข้อความรอง
C_TEXT3   = "#B4B4B4"   # ข้อความจาง
C_ACCENT  = "#0065A3"   # สีหลัก — ปุ่ม primary, nav active
C_SECTION_TEXT = "#283C50"
C_MUTED_TEXT = "#B4B4B4"
C_GREEN   = "#16A34A"   # สีบวก / สำเร็จ
C_RED     = "#DC2626"   # สีลบ / อันตราย
C_ORANGE  = "#EA580C"   # สี (color print)
C_PURPLE  = "#7C3AED"   # A3 ขาวดำ
C_YELLOW  = "#CA8A04"   # เตือน

# ─── ฟอนต์ขนาดต่างๆ ──────────────────────────────────────
# ปรับขนาดตัวอักษรได้ที่นี่
F_XS   = _platform_value(11, windows=9)    # เล็กมาก (เช่น timestamp)
F_SM   = _platform_value(11, windows=10)   # เล็ก (label รอง)
F_MD   = _platform_value(12, windows=11)   # กลาง (ข้อความทั่วไป)
F_LG   = _platform_value(13, windows=12)   # ใหญ่ (ตาราง, ฟอร์ม)
F_XL   = _platform_value(16, windows=13)   # ใหญ่ขึ้น (ปุ่ม, nav)
F_2XL  = _platform_value(28, windows=24)   # หัวข้อหน้า
F_NUM  = _platform_value(40, windows=34)   # ตัวเลขหลัก stat card
F_NMSM = _platform_value(14, windows=13)   # ตัวเลขรอง

# ─── Default Font ──────────────────────────────────────────
UI_FONT_FAMILY = _platform_value(
    "Thonburi",
    windows="Segoe UI",
    macos=".AppleSystemUIFont",
    linux="Ubuntu",
)
MONO_FONT_FAMILY = _platform_value("Menlo", windows="Consolas", linux="DejaVu Sans Mono")
QSS_FONT_FAMILY = _platform_value(
    "'Thonburi'",
    windows="'Segoe UI', 'Leelawadee UI', 'Noto Sans Thai', sans-serif",
    macos="'.AppleSystemUIFont'",
    linux="'Ubuntu', 'Noto Sans Thai', sans-serif",
)
DEFAULT_FONT_NAME = UI_FONT_FAMILY  # ฟอนต์เริ่มต้นทั้งโปรแกรม
DEFAULT_FONT_SIZE = _platform_value(11, windows=11)  # ขนาดฟอนต์เริ่มต้น

# ─── % กระดาษเสีย default ───────────────────────────────
# ค่าเริ่มต้น 2% — ผู้ใช้เปลี่ยนได้ในหน้าตั้งค่า
DEFAULT_WASTE_PCT = 2.0

# ─── V5 background meter defaults ────────────────────────
DEFAULT_ADMIN_USERNAME = "administrator"
DEFAULT_ADMIN_PASSWORD = ""
DEFAULT_SNMP_COMMUNITY = "public"
DEFAULT_SNMP_INTERVAL_MINUTES = 5
DEFAULT_WEB_INTERVAL_MINUTES = 15
DEFAULT_PEAK_WEB_INTERVAL_MINUTES = 5
DEFAULT_WORK_START = "08:00"
DEFAULT_WORK_END = "17:00"
DEFAULT_PEAK_BEFORE_MINUTES = 30
DEFAULT_PEAK_AFTER_MINUTES = 30
# วันสิ้นสุดรอบบิล: ถ้าเดือนนั้นไม่มีวันที่ระบุ ให้ใช้วันสุดท้ายของเดือน
DEFAULT_BILLING_DAY = 31

# ─── รหัสผ่านสำหรับเปลี่ยนการตั้งค่า ─────────────────────
DEFAULT_SETTINGS_PASSWORD = ""

# ─── ราคาต่อแผ่น (ค่า default — ผู้ใช้เปลี่ยนได้ในหน้า ตั้งค่า) ──
# หน่วย: บาท/แผ่น
DEFAULT_PRICE = {
    "a4_color": 0.00,
    "a4_bw":    0.00,
    "a3_color": 0.00,
    "a3_bw":    0.00,
}

# ─── Window & Layout Dimensions ────────────────────────────
WINDOW_MIN_WIDTH = 1024         # ความกว้างขั้นต่ำของหน้าต่าง
WINDOW_MIN_HEIGHT = 768         # ความสูงขั้นต่ำของหน้าต่าง
WINDOW_DEFAULT_WIDTH = _platform_value(1280, windows=1240)   # ความกว้างดีฟอลต์
WINDOW_DEFAULT_HEIGHT = _platform_value(800, windows=780)    # ความสูงดีฟอลต์
SIDEBAR_WIDTH = _platform_value(230, windows=228)            # ความกว้าง sidebar
NAV_BUTTON_HEIGHT = _platform_value(46, windows=44)          # ความสูงปุ่ม navigation
BUTTON_HEIGHT = _platform_value(40, windows=38)              # standard action
BUTTON_LARGE_HEIGHT = _platform_value(48, windows=48)        # wizard/mode choice
BUTTON_LINK_HEIGHT = _platform_value(32, windows=32)         # text/link action
BUTTON_ICON_SIZE = _platform_value(38, windows=38)           # icon-only action
BUTTON_RADIUS = 8                                             # shared corner radius
BUTTON_MOTION_MS = 120                                        # hover/press transition
LOGO_SCALED_WIDTH = _platform_value(54, windows=50)          # icon เล็กในหัว sidebar แนวนอน
LOGO_FILENAME = "logo.png"      # ชื่อไฟล์โลโก้
LOGO_MARGIN_BOTTOM = _platform_value(14, windows=12)  # ระยะห่างด้านล่างของโลโก้

# ─── Layout Margins & Spacing ──────────────────────────────
SIDEBAR_MARGIN_LEFT = _platform_value(12, windows=10)      # sidebar padding ซ้าย
SIDEBAR_MARGIN_TOP = _platform_value(20, windows=16)       # sidebar padding บน
SIDEBAR_MARGIN_RIGHT = _platform_value(12, windows=10)     # sidebar padding ขวา
SIDEBAR_MARGIN_BOTTOM = _platform_value(16, windows=14)    # sidebar padding ล่าง
SIDEBAR_SPACING = _platform_value(4, windows=3)            # ระยะ spacing ที่ sidebar

PAGE_OVERVIEW_MARGIN_L = 16     # balanced outer breathing room
PAGE_OVERVIEW_MARGIN_T = 14
PAGE_OVERVIEW_MARGIN_R = 16
PAGE_OVERVIEW_MARGIN_B = 14
PAGE_OVERVIEW_SPACING = 8

PAGE_SETTINGS_MARGIN_L = _platform_value(24, windows=20)   # margin ซ้าย Page Settings
PAGE_SETTINGS_MARGIN_T = _platform_value(20, windows=16)   # margin บน Page Settings
PAGE_SETTINGS_MARGIN_R = _platform_value(24, windows=20)   # margin ขวา Page Settings
PAGE_SETTINGS_MARGIN_B = _platform_value(20, windows=16)   # margin ล่าง Page Settings

CARD_MARGIN_L = 12              # shared card inner padding
CARD_MARGIN_T = 10
CARD_MARGIN_R = 12
CARD_MARGIN_B = 10
CARD_SPACING = 8

GRID_SPACING = 12               # spacing between grid items
PIE_ROW_SPACING = 10            # spacing between chart cards
BAR_SPACING = 8                 # spacing inside trend cards

# ─── Chart Heights ────────────────────────────────────────
PIE_CHART_MIN_HEIGHT = _platform_value(150, windows=140)   # ความสูงขั้นต่ำของ pie chart (ลดลง)
BAR_CHART_MIN_HEIGHT = _platform_value(250, windows=230)   # ความสูงขั้นต่ำของ bar chart (ลดลง)

# ─── Status Bar ────────────────────────────────────────────
STATUS_TEXT_COLOR = "#64748B"   # สีข้อความ status bar
STATUS_PADDING = "4px 8px"      # padding status bar

# ─── Graph Customization ────────────────────────────────────
GRAPH_TITLE_SIZE = _platform_value(24, windows=20)         # ขนาด font ของ title กราฟ (pt)
GRAPH_AXIS_LABEL_SIZE = _platform_value(14, windows=12)    # ขนาด font ของ axis labels (pt)
GRAPH_TOOLTIP_SIZE = _platform_value(13, windows=11)       # ขนาด font ของ tooltip (pt)
GRAPH_VALUE_SIZE = _platform_value(11, windows=10)         # ขนาด font ของค่าบน bar (pt)
GRAPH_BG_COLOR = "#FFFFFF"      # สีพื้นหลังกราฟ
GRAPH_BAR_WIDTH = 0.25          # ความกว้างของ bar (ratio)
GRAPH_GRID_ALPHA = 0.30          # ความโปร่งใส grid (0-1)
GRAPH_TOOLTIP_COLOR = "#555555" # สีข้อความ tooltip (hex)
GRAPH_TOOLTIP_BG = "#FFFFFF"    # สีพื้นหลังของ tooltip (hex)

# ─── Graph Bar Colors ───────────────────────────────────────
GRAPH_COLORS_MACHINE = [        # สี bar สำหรับแต่ละเครื่อง
    "#2563EB",  # Machine 0 (น้ำเงิน)
    "#DC2626",  # Machine 1 (แดง)
    "#16A34A",  # Machine 2 (เขียว)
]
GRAPH_COLORS_TYPE = {           # สี bar สำหรับประเภทงาน
    "copy_color":   "#EA580C",   # Copy สี (ส้ม)
    "copy_bw":      "#787670",   # Copy ขาวดำ (เทา)
    "print_color":  "#2563EB",   # Print สี (น้ำเงิน)
    "print_bw":     "#7C3AED",   # Print ขาวดำ (ม่วง)
    "meter_color":  "#DB2777",   # Meter สี / Label (ชมพู-แดง)
    "meter_bw":     "#475569",   # Meter ขาวดำ / Label (สเลต)
}

# ─── QSS หลัก (stylesheet ทั้งโปรแกรม) ───────────────────
# แก้ตรงนี้เพื่อเปลี่ยน style ปุ่ม/ตาราง/input ทั้งหมด
def page_tabs_qss():
    """One left-aligned tab pattern for all desktop page containers."""
    return f"""
QTabWidget::pane {{
    border: 1px solid {C_BORDER}; border-radius: 0;
    background: {C_CARD};
}}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar::tab {{
    background: #E5ECF2; color: {C_TEXT2};
    border: 1px solid {C_BORDER};
    padding: 7px 18px; font-size: {F_LG}px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {C_CARD}; color: {C_ACCENT};
    font-weight: 700; border-bottom: 2px solid {C_ACCENT};
}}
QTabBar::tab:hover {{ background: #DCE7EF; color: {C_TEXT}; }}
"""


def build_qss():
    return f"""
/* ── พื้นฐาน ── */
QMainWindow, QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: {QSS_FONT_FAMILY};
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
    background: {C_SIDEBAR}; color: #ffffff;
    border: none; padding: 4px 8px; border-radius: 4px;
    font-size: {F_SM}pt;
}}

/* ── Shared button geometry ── */
QPushButton {{
    border-radius: {BUTTON_RADIUS}px;
    padding: 7px 16px;
    font-size: {F_MD}pt;
    font-weight: 600;
}}

/* ── Sidebar ── */
QWidget#sidebar {{ background: {C_SIDEBAR}; }}
QComboBox#language_selector {{
    background: #183B5B;
    color: #FFFFFF;
    border: 1px solid #315A7C;
    padding: 7px 10px;
}}
QComboBox#language_selector QAbstractItemView {{
    background: #FFFFFF;
    color: {C_TEXT};
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
    font-size: {F_XL}pt;
    font-weight: 500;
}}
QPushButton#nav:hover {{
    background: {C_SB_H};
    color: #ffffff;
}}
QPushButton#nav[active=true] {{
    background: #E9F3FA;   /* ← สีปุ่ม nav ที่เลือกอยู่ */
    color: #0B5E93;
    font-weight: 700;
}}

/* ── การ์ด ── */
QFrame#card {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 12px;
}}
QFrame#stat_card {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 12px;
}}
QFrame#preview_card {{
    background: #FFFBEB;
    border: 2px solid #FCD34D;
    border-radius: 10px;
}}
QFrame#warn_card {{
    background: #FEF2F2;
    border: 2px solid {C_RED};
    border-radius: 10px;
}}

/* ── ตาราง ── */
QTableWidget {{
    background: {C_CARD};
    border: 1px solid {C_TABLE_BORDER};
    border-radius: 8px;
    gridline-color: {C_TABLE_BORDER};
    font-size: {F_LG}pt;
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
}}
QTableWidget::item:selected {{
    background: {C_TABLE_SELECTED};
    color: {C_TEXT};
}}
QTableWidget::item:alternate {{
    background: {C_TABLE_ALT};
}}
QHeaderView::section {{
    background: {C_TABLE_HEADER};
    color: {C_TABLE_HEADER_TEXT};
    font-size: {F_MD}pt;
    font-weight: 600;
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid {C_TABLE_BORDER};
    border-right: 1px solid {C_TABLE_BORDER};
}}

/* ── Input / ComboBox ── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background: white;
    border: 1.5px solid {C_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    font-size: {F_LG}pt;
    color: {C_TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
    border-color: {C_ACCENT};
}}
QPushButton:focus {{
    border: 2px solid {C_ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {C_BORDER};
    selection-background-color: #e8f0f7; color: {C_TEXT};
}}

/* ── ปุ่มหลัก (Primary) — สีน้ำเงิน = เลือกอยู่ ── */
QPushButton#btn_primary {{
    background: {C_ACCENT} !important;
    color: #FFFFFF !important;
    border: 1px solid {C_ACCENT} !important;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: {F_LG}pt;
    font-weight: 700;
}}
QPushButton#btn_primary:hover {{ background: #017DD0 !important; color: #FFFFFF !important; border-color: #017DD0 !important; }}
QPushButton#btn_primary:pressed {{ background: #074A76 !important; color: #FFFFFF !important; border-color: #074A76 !important; }}
QPushButton#btn_primary:disabled {{ background: #E8EEF4 !important; color: #52677D !important; border-color: #C2CFDB !important; }}

/* ── ปุ่ม Outline ── */
QPushButton#btn_outline {{
    background: #FFFFFF !important; color: #24506E !important;
    border: 1px solid #B8C8D8 !important; border-radius: 8px;
    padding: 7px 16px; font-size: {F_LG}px; font-weight: 600;
}}
QPushButton#btn_outline:hover {{
    background: #dbeafe !important; color: #123262 !important;
    border-color: #93c5fd !important;
}}
QPushButton#btn_outline:pressed {{
    background: #bfdbfe !important; color: #123262 !important;
    border-color: #60a5fa !important;
}}

/* ── ปุ่ม Danger (แดง) ── */
QPushButton#btn_danger {{
    background: #f4f4f4 !important; color: #123262 !important;
    border: 1.5px solid #d0d0d0 !important; border-radius: 8px;
    padding: 7px 16px; font-size: {F_LG}px; font-weight: 600;
}}
QPushButton#btn_danger:hover {{
    background: #123262 !important; color: #ffffff !important;
    border-color: #123262 !important;
}}
QPushButton#btn_danger:pressed {{
    background: #0d1e39 !important; color: #ffffff !important;
    border-color: #0d1e39 !important;
}}

/* ── ปุ่ม Success (เขียว) ── */
QPushButton#btn_success {{
    background: #f4f4f4 !important; color: #123262 !important;
    border: 1.5px solid #d0d0d0 !important; border-radius: 8px;
    padding: 7px 16px; font-size: {F_LG}px; font-weight: 600;
}}
QPushButton#btn_success:hover {{ background: #123262 !important; color: #ffffff !important; border-color: #123262 !important; }}
QPushButton#btn_success:pressed {{ background: #0d1e39 !important; color: #ffffff !important; border-color: #0d1e39 !important; }}
QPushButton#btn_success:disabled {{ background: #f4f4f4 !important; color: #c7c7c7 !important; }}

/* ── ปุ่ม Warning (เหลือง/ส้ม) ── */
QPushButton#btn_warning {{
    background: #f4f4f4 !important; color: #123262 !important;
    border: 1.5px solid #d0d0d0 !important; border-radius: 8px;
    padding: 7px 16px; font-size: {F_LG}px; font-weight: 600;
}}
QPushButton#btn_warning:hover {{ background: #123262 !important; color: #ffffff !important; border-color: #123262 !important; }}
QPushButton#btn_warning:pressed {{ background: #0d1e39 !important; color: #ffffff !important; border-color: #0d1e39 !important; }}

/* ── Checkbox ──
   Keep the native platform indicator so checked state always has a visible
   checkmark, including high-contrast and accessibility modes. */
QCheckBox {{ font-size: {F_LG}px; spacing: 7px; }}

/* ── Tab Widget ── */
{page_tabs_qss()}

/* ── SpinBox arrows ── */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 18px; border: none;
}}
"""


# ─── QSS เฉพาะ หน้า Overview ──────────────────────────────
# ใช้สำหรับ PageOverview.setStyleSheet() เพิ่มเติมจาก build_qss() หลัก
# แก้ที่นี่เพื่อปรับรูปลักษณ์เฉพาะหน้า Overview โดยไม่กระทบหน้าอื่น
def build_overview_qss():
    return f"""

PageOverviewV2 {{ background: {C_BG}; }}
QLabel#overview_status_line {{
    background: transparent; color: {C_TEXT2}; border: none;
    padding: 0 2px 2px 2px; font-size: {F_SM}pt;
}}
QLabel#overview_quality_line {{
    background: #EFF6FF; color: #174EA6;
    border: 1px solid #BFDBFE; border-radius: 6px;
    padding: 6px 10px; font-size: {F_SM}pt;
}}
QFrame#overview_kpi_panel,
QFrame#overview_printer_panel,
QFrame#overview_chart_panel {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px;
}}
QFrame#overview_metric_card {{
    background: {C_CARD}; border: 1px solid {C_TONER_BORDER}; border-radius: 9px;
}}
QLabel#overview_metric_title {{ color: {C_TEXT}; background: transparent; border: none; }}
QLabel#overview_metric_value,
QLabel#overview_metric_detail {{ background: transparent; border: none; }}
QWidget#overview_metric_content {{ background: transparent; border: none; }}
QWidget#overview_toner_group {{ background: transparent; border: none; }}
QFrame#overview_printer_row_v2 {{
    background: {C_CARD}; border: 1px solid {C_TONER_BORDER}; border-radius: 9px;
}}
QFrame#overview_printer_row_v2 QLabel {{
    background: transparent; border: none;
}}
QWidget#overview_printer_identity,
QWidget#overview_printer_details {{
    background: transparent; border: none;
}}
QPushButton#overview_ip_link {{
    background: transparent; color: {C_ACCENT}; border: none;
    padding: 0; margin: 0; text-align: left; font-weight: 500;
}}
QPushButton#overview_ip_link:hover {{
    color: #017DD0; text-decoration: underline;
}}
QPushButton#overview_ip_link:pressed {{ color: #074A76; }}
QLabel#overview_ip_link {{
    background: transparent; border: none; padding: 0; margin: 0;
}}
QWidget#overview_printer_list {{ background: {C_CARD}; }}
QComboBox#overview_period_combo {{
    background: {C_CARD}; color: {C_TEXT};
    border: 1px solid {C_TONER_BORDER}; border-radius: 6px;
    padding: 4px 28px 4px 10px;
    font-size: {F_MD}pt; font-weight: 500;
}}
QComboBox#overview_period_combo:hover,
QComboBox#overview_period_combo:focus {{
    border: 1px solid {C_TONER_BORDER};
}}
QComboBox#overview_period_combo::drop-down {{
    width: 26px; border: none; background: transparent;
}}
QWidget#overview_period_selector {{
    background: {C_TABLE_HEADER}; border: 1px solid {C_TABLE_HEADER}; border-radius: 8px;
}}
QPushButton#overview_period_button {{
    background: {C_TABLE_HEADER}; color: {C_TABLE_HEADER_TEXT};
    border: none; border-right: 1px solid #D8E7F3;
    border-radius: 0; padding: 4px 8px; font-size: {F_LG}pt; font-weight: 600;
}}
QPushButton#overview_period_button[segmentPosition="first"] {{
    border-top-left-radius: 7px; border-bottom-left-radius: 7px;
}}
QPushButton#overview_period_button[segmentPosition="last"] {{
    border-top-right-radius: 7px; border-bottom-right-radius: 7px; border-right: none;
}}
QPushButton#overview_period_button:hover {{ background: {C_ACCENT}; }}
QPushButton#overview_period_button:checked {{
    background: {C_CARD}; color: {C_TABLE_HEADER}; font-weight: 800;
}}

/* ── พื้นหลังหน้า Overview ── */
PageOverview {{
    background: {C_BG};
}}

/* ── Summary strip: one surface, four readable values ── */
QFrame#overview_summary_strip {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
}}
QPushButton#btn_outline:disabled {{
    background: #E8EEF4 !important; color: #52677D !important;
    border-color: #C2CFDB !important;
}}
QFrame#overview_summary_strip QFrame#stat_card {{
    background: transparent;
    border: none;
    border-radius: 0px;
}}

/* ── การ์ด section (Pie / Bar / Top Users) ── */
QFrame#card {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
}}

/* ── Operational and data-quality states ── */
QLabel#overview_status, QLabel#overview_quality {{
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: {F_MD}pt;
}}
QLabel#overview_status[state="success"], QLabel#overview_quality[state="success"] {{
    background: #EAF7EF;
    color: #087A55;
    border-color: #B8DFC9;
}}
QLabel#overview_status[state="warning"], QLabel#overview_quality[state="warning"] {{
    background: #FFF4E5;
    color: #8A4B08;
    border-color: #F4C98B;
}}
QLabel#overview_status[state="error"] {{
    background: #FFF0F0;
    color: #B42318;
    border-color: #F5B7B1;
}}
QLabel#overview_quality[state="info"] {{
    background: #EFF6FF;
    color: #174EA6;
    border-color: #BFDBFE;
}}
QLabel#overview_empty {{
    background: #F8FAFC;
    color: {C_TEXT2};
    border: 1px dashed {C_BORDER};
    border-radius: 8px;
    padding: 24px;
    font-size: {F_MD}pt;
}}
QFrame#overview_printer_row {{
    background: {C_CARD};
    border: none;
    border-bottom: 1px solid {C_BORDER};
}}
QFrame#overview_printer_row[lastRow="true"] {{
    border-bottom: none;
}}

/* ── Overview actions ── */
QPushButton#btn_primary {{
    background: #dbeafe !important;
    color: #123262 !important;
    border: 1px solid #1a3d8a !important;
    border-radius: {BUTTON_RADIUS}px;
    padding: 7px 16px;
    font-size: {F_MD}pt;
    font-weight: 700;
}}
QPushButton#btn_primary:hover {{
    background: #bfdbfe !important;
    color: #123262 !important;
    border-color: #1a3d8a !important;
}}
QPushButton#btn_outline {{
    background: #f4f4f4 !important;
    color: #123262 !important;
    border: 1px solid #d0d0d0 !important;
    border-radius: {BUTTON_RADIUS}px;
    padding: 7px 16px;
    font-size: {F_MD}pt;
    font-weight: 600;
}}
QPushButton#btn_outline:hover {{
    background: #dbeafe !important;
    color: #123262 !important;
    border-color: #93c5fd !important;
}}

/* ── ตาราง Top Users ── */
QTableWidget {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    gridline-color: {C_BORDER};
    font-size: {F_MD}pt;
}}
QTableWidget::item {{
    padding: 3px 8px;
}}
QHeaderView::section {{
    background: #f8fafc;
    color: {C_TEXT2};
    font-size: {F_SM}pt;
    font-weight: 600;
    padding: 4px 8px;
    border: none;
    border-bottom: 1px solid {C_BORDER};
    border-right: 1px solid {C_BORDER};
}}

/* ── ป้ายเวลาอัปเดต ── */
QLabel#lbl_ov_time {{
    color: {C_TEXT3};
    font-size: {F_XS}pt;
}}
"""

