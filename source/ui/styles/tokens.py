"""Desktop design tokens. Business and storage defaults belong in config.py.

This module has no Qt, database or service dependencies.
"""

import sys

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


SLOT_COLORS = ["#2563EB", "#DC2626", "#16A34A"]

SLOT_LIGHT = ["#DBEAFE", "#FEE2E2", "#DCFCE7"]

C_BG = "#F0F0F0"

C_SIDEBAR = "#102A43"

C_SB_H = "#183B5B"

C_CARD = "#ffffff"

C_BORDER = "#919191"

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

C_TEXT = "#191919"

C_TEXT2 = "#505050"

C_TEXT3 = "#5B6573"

C_ACCENT = "#0065A3"

C_SECTION_TEXT = "#283C50"

C_MUTED_TEXT = "#5B6573"

C_GREEN = "#16A34A"

C_RED = "#DC2626"

C_ORANGE = "#EA580C"

C_PURPLE = "#7C3AED"

C_YELLOW = "#CA8A04"

F_XS = _platform_value(11, windows=9)

F_SM = _platform_value(11, windows=10)

F_MD = _platform_value(12, windows=11)

F_LG = _platform_value(13, windows=12)

F_XL = _platform_value(16, windows=13)

F_2XL = _platform_value(28, windows=24)

F_NUM = _platform_value(40, windows=34)

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

DEFAULT_FONT_NAME = UI_FONT_FAMILY

DEFAULT_FONT_SIZE = _platform_value(11, windows=11)

WINDOW_MIN_WIDTH = 1024

WINDOW_DEFAULT_WIDTH = _platform_value(1280, windows=1240)

WINDOW_DEFAULT_HEIGHT = _platform_value(800, windows=780)

SIDEBAR_WIDTH = _platform_value(230, windows=228)

NAV_BUTTON_HEIGHT = _platform_value(46, windows=44)

BUTTON_HEIGHT = _platform_value(40, windows=38)

BUTTON_LARGE_HEIGHT = _platform_value(48, windows=48)

BUTTON_LINK_HEIGHT = _platform_value(32, windows=32)

BUTTON_ICON_SIZE = _platform_value(38, windows=38)

BUTTON_RADIUS = 8

BUTTON_MOTION_MS = 120

LOGO_SCALED_WIDTH = _platform_value(54, windows=50)

LOGO_MARGIN_BOTTOM = _platform_value(14, windows=12)

SIDEBAR_MARGIN_LEFT = _platform_value(12, windows=10)

SIDEBAR_MARGIN_TOP = _platform_value(20, windows=16)

SIDEBAR_MARGIN_RIGHT = _platform_value(12, windows=10)

SIDEBAR_MARGIN_BOTTOM = _platform_value(16, windows=14)

SIDEBAR_SPACING = _platform_value(4, windows=3)

PAGE_OVERVIEW_MARGIN_L = 16

PAGE_OVERVIEW_MARGIN_T = 14

PAGE_OVERVIEW_MARGIN_R = 16

PAGE_OVERVIEW_MARGIN_B = 14

STATUS_PADDING = "4px 8px"

GRAPH_TITLE_SIZE = _platform_value(24, windows=20)

GRAPH_AXIS_LABEL_SIZE = _platform_value(14, windows=12)

GRAPH_TOOLTIP_SIZE = _platform_value(13, windows=11)

GRAPH_VALUE_SIZE = _platform_value(11, windows=10)

GRAPH_BG_COLOR = "#FFFFFF"

GRAPH_BAR_WIDTH = 0.25

GRAPH_GRID_ALPHA = 0.30

GRAPH_TOOLTIP_COLOR = "#555555"

GRAPH_TOOLTIP_BG = "#FFFFFF"

GRAPH_COLORS_MACHINE = [  # สี bar สำหรับแต่ละเครื่อง
    "#2563EB",  # Machine 0 (น้ำเงิน)
    "#DC2626",  # Machine 1 (แดง)
    "#16A34A",  # Machine 2 (เขียว)
]

GRAPH_COLORS_TYPE = {  # สี bar สำหรับประเภทงาน
    "copy_color": "#EA580C",  # Copy สี (ส้ม)
    "copy_bw": "#787670",  # Copy ขาวดำ (เทา)
    "print_color": "#2563EB",  # Print สี (น้ำเงิน)
    "print_bw": "#7C3AED",  # Print ขาวดำ (ม่วง)
    "meter_color": "#DB2777",  # Meter สี / Label (ชมพู-แดง)
    "meter_bw": "#475569",  # Meter ขาวดำ / Label (สเลต)
}
