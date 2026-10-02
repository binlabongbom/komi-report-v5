"""Scoped devices presentation rules. Builders receive values, never widgets."""

from . import tokens


def overview_v2_view_bar() -> str:
    return f"background:{tokens.C_CARD};border:none;"


IMPORT_BTN_DELETE_SEL = (
    "QPushButton { background: #FEE2E2; color: #DC2626; border: 1.5px solid #FCA5A5; "
    "border-radius: 7px; padding: 4px 16px; font-weight: 600; } QPushButton:hover { "
    "background: #DC2626; color: white; }"
)


IMPORT_B_CLR = (
    "QPushButton { background: white !important; color: #0F172A !important; border: 1.5px "
    "solid #E2E8F0 !important; border-radius: 8px; padding: 8px 12px; font-weight: 600; "
    "font-size: 16px; } QPushButton:hover { background: #2563EB !important; color: white "
    "!important; border-color: #E2E8F0 !important; }"
)


IMPORT_OVERLAY = (
    "QLabel { background-color: rgba(200, 200, 200, 200); border: 2px dashed #999999; "
    "border-radius: 8px; color: #333333; font-weight: 600; }"
)


IMPORT_CARD_FRAME = "QFrame { background: transparent; }"


IMPORT_TBL_ACTIVITY = "QTableWidget { background: #F8FAFC; } QTableWidget::item:hover { background: #DBEAFE; }"


IMPORT_BTN_EDIT_MODE = (
    "QPushButton { background: #F1F5F9; color: #64748B; border: 1.5px solid #CBD5E1; "
    "border-radius: 7px; padding: 4px 16px; font-weight: 600; } QPushButton:hover { "
    "background: #CBD5E1; color: #0F172A; }"
)


IMPORT_CARD_FRAME_SET_DRAG_HIGHLIGHT = (
    "QFrame { border: 1px solid #E2E8F0 !important; border-radius: 8px; background: rgba(200, 200, 200, 0.15); }"
)


def import_section_title() -> str:
    return f"color:{tokens.C_SECTION_TEXT};padding-top:10px;padding-bottom:4px;background:transparent;"


IMPORT_TABLE = (
    "QTableWidget#import_web_table::item{padding:0 8px;}QTableWidget#import_web_table "
    "QHeaderView::section{padding:0 8px;}"
)


IMPORT_TABLE_SUBJECT_TABLE = (
    "QTableWidget#import_subject_table::item{padding:0 "
    "8px;}QTableWidget#import_subject_table QHeaderView::section{padding:0 8px;}"
)


IMPORT_PANEL = "QWidget#toner_level_row{background:#FFFFFF;border:none;}"


IMPORT_PANEL_PAPER_TRAY_TILES = "QWidget#paper_tray_tiles{background:transparent;border:none;}"


def import_device_card(slot_color) -> str:
    return f"QFrame#import_device_card{{background:white;border:1px solid {tokens.C_BORDER};border-top:4px solid {slot_color};border-radius:8px;}}QFrame#import_device_card QLabel{{background:transparent;}}"


def device_overview_card(slot_color) -> str:
    return f"QFrame#card{{border:1px solid {tokens.C_BORDER};border-top:4px solid {slot_color};border-radius:8px;}}"


def import_empty() -> str:
    return f"background:{tokens.C_EMPTY_BG};color:{tokens.C_MUTED_TEXT};padding:9px;border-radius:5px;"


IMPORT_NAME = "background:transparent;border:none;font-size:10px;font-weight:700;"


def import_tile(background, foreground, border) -> str:
    return f"background:{background};color:{foreground};border:1px solid {border};border-radius:6px;"


DEVICE_OVERVIEW_BASELINE = "background:#FFF7E8;color:#7A5411;padding:8px;border-radius:5px;font-size:11px;"
