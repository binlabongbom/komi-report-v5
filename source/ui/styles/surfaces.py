"""Shared surfaces styles. Keep reusable component rules here."""

from . import tokens

WHITE_BORDERLESS = "background:#FFFFFF; border:0;"


TRANSPARENT = "background:transparent;border:none;"


def card() -> str:
    return f"background: {tokens.C_CARD}; border-radius: 8px; border: none;"


WARNING_BOX = "background:#FFF8E8;color:#75510A;border:1px solid #E8D7A4;border-radius:6px;padding:12px;"


INFO_BOX = "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;border-radius:7px;padding:10px 12px;"


WARNING_NOTICE = "color:#8A4B08;background:#FFF7E8;border:1px solid #F2C879;border-radius:7px;padding:9px 11px;"


READONLY_SUMMARY = "background:#FFFFFF;color:#52677D;border:1px solid #D6E0EA;border-radius:6px;padding:8px 10px;"


INFO_NOTICE = "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;border-radius:6px;padding:9px 11px;"


def muted_note(color: str) -> str:
    return f"color:{color}; background:#F1F5F9; padding:8px; border-radius:6px;"


def divider() -> str:
    return f"color: {tokens.C_BORDER}; background: {tokens.C_BORDER}; max-height: 1px;"


def section_title() -> str:
    return f"color: {tokens.C_TEXT}; padding-bottom: 2px;"


def badge(background, foreground) -> str:
    return f"\n        background: {background}; color: {foreground};\n        border-radius: 4px; padding: 2px 4px;\n    "


def accent_card(top_color) -> str:
    return f"QFrame#card{{\n            background: {tokens.C_CARD};\n            border: 1px solid {tokens.C_BORDER};\n            border-radius: 12px;\n            border-top: 4px solid {top_color};\n        }}"
