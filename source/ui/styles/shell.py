"""Scoped shell presentation rules. Builders receive values, never widgets."""

from . import tokens


def splash_screen_card() -> str:
    return f"\n            QFrame {{\n                background: {tokens.C_SIDEBAR};\n                border-radius: 20px;\n            }}\n        "


SPLASH_SCREEN_ACTIVITY = (
    "QProgressBar { background: #334155; border: none; border-radius: 2px; "
    "}QProgressBar::chunk { background: #38BDF8; border-radius: 2px; }"
)


def main_window_sidebar_logo_title(font_size) -> str:
    return (
        f"color:#FFFFFF;background:transparent;border:none;letter-spacing:0.4px;font-size:{font_size}pt;font-weight:bold;"
    )


MAIN_WINDOW_LOGO = "background: transparent; border: none;"


MAIN_WINDOW_LOGO_TITLE = "color:#FFFFFF;background:transparent;border:none;letter-spacing:0.4px;"


def main_window_stack() -> str:
    return f"QStackedWidget#main_content_stack {{ background: {tokens.C_BG}; }}"
