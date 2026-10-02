"""Scoped legacy presentation rules. Builders receive values, never widgets."""

from . import tokens

NO_PARSER_MATCH_DIALOG_ICON = "font-size:36px; background:transparent; border:none;"


NO_PARSER_MATCH_DIALOG_BTN_OPEN = (
    "QPushButton { background:#2563EB; color:white; border:none; border-radius:8px; "
    "padding:8px 18px; font-weight:600; font-size:10pt; }QPushButton:hover { "
    "background:#1E3A8A; }"
)


NO_PARSER_MATCH_DIALOG_BTN_CONFIRM = (
    "QPushButton { background:#F0FDF4; color:#16A34A; border:1.5px solid #16A34A; "
    "border-radius:8px; padding:6px 18px; font-weight:600; font-size:10pt; "
    "}QPushButton:hover { background:#16A34A; color:white; }"
)


NO_PARSER_MATCH_DIALOG_BTN_CANCEL = (
    "QPushButton { background:transparent; color:#94A3B8; border:none; font-size:9pt; "
    "}QPushButton:hover { color:#0F172A; text-decoration:underline; }"
)


def preview_dialog_mode_badge(mode_color) -> str:
    return f"background: {mode_color}; color: white; padding: 4px 10px; border-radius: 4px;"


PREVIEW_DIALOG_CANCEL_BTN = (
    "QPushButton { background: white !important; color: #0F172A !important; border: 1.5px "
    "solid #E2E8F0 !important; border-radius: 8px; padding: 7px 16px; font-weight: 600; } "
    "QPushButton:hover { background: #2563EB !important; color: white !important; "
    "border-color: #E2E8F0 !important; } QPushButton:pressed { background: #1E40AF "
    "!important; color: white !important; border-color: white !important; }"
)


def manual_sec() -> str:
    return f"color:{tokens.C_ACCENT}; font-weight:bold; padding-bottom:4px;border-bottom: 2px solid {tokens.C_ACCENT}; margin-top:18px; margin-bottom:6px;"


MANUAL_STEP = "background:transparent; border:0;"


def manual_badge(font_size) -> str:
    return f"background:{tokens.C_ACCENT}; color:white; border-radius:15px;font-weight:bold; font-size:{font_size}pt;"


MANUAL_CARD = "QFrame#manual_document_block { background:#FFFFFF; border:0; border-radius:0; padding:0; }"


def manual_txt(color, weight_rule) -> str:
    return f"color:{color}; background:transparent; border:0; {weight_rule}"


def manual_tip() -> str:
    return f"color:{tokens.C_TEXT2}; background:#EEF6FF; border:0; border-left:4px solid {tokens.C_ACCENT}; padding:8px 12px;"


def manual_guide_screenshot() -> str:
    return f"color:{tokens.C_TEXT2}; background:transparent; border:0; font-style:italic; padding:2px 8px;"


def manual_preview() -> str:
    return f"background:#F7F8FA;border:1px solid {tokens.C_BORDER};padding:8px;"


def manual_open_button() -> str:
    return f"QPushButton {{ background:{tokens.C_ACCENT};color:white;border:0;border-radius:6px;padding:9px 14px;font-weight:bold; }} QPushButton:disabled {{ background:#AAB4BF; }}"


MANUAL_MANUAL_SCROLL = "QScrollArea#manual_single_page_scroll { background:transparent; border:0; }"


MANUAL_MANUAL_CONTENT = "QWidget#manual_word_content { background:#FFFFFF; }"


def manual_contents() -> str:
    return f"QFrame#manual_toc_frame {{ background-color:{tokens.C_CARD}; border:1px solid {tokens.C_BORDER}; border-radius:10px; }}"


def preview_dialog_parser_banner(color) -> str:
    return f"QFrame {{ background: {color}18; border: 1.5px solid {color}60; border-left: 5px solid {color}; border-radius: 8px; }}"


def manual_card_title() -> str:
    return f"color:{tokens.C_TEXT}; font-weight:bold; background:transparent; border:0; border-bottom:1px solid {tokens.C_ACCENT}; padding:2px 0 8px 0;"


def preview_dialog_badge(color) -> str:
    return f"background:{color}; color:white; padding:2px 8px; border-radius:4px; border:none;"


def manual_toc_button(*, active: bool) -> str:
    if active:
        return (
            f"text-align:left; color:{tokens.C_ACCENT}; background-color:#EAF3FB; "
            f"border:1px solid {tokens.C_ACCENT}; border-radius:6px; padding:9px 8px; "
            "font-weight:bold;"
        )
    return (
        f"text-align:left; color:{tokens.C_TEXT2}; background-color:transparent; "
        "border:1px solid transparent; border-radius:6px; padding:9px 8px;"
    )
