"""Navigation stylesheet rules."""

from . import tokens


def page_tabs_qss(*, compact=False):
    """One left-aligned tab pattern for all desktop page containers."""
    return f"""
QTabWidget::pane {{
    border: 1px solid {tokens.C_BORDER}; border-radius: 0;
    background: {tokens.C_CARD};
}}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar::tab {{
    background: #E5ECF2; color: {tokens.C_TEXT2};
    border: 1px solid {tokens.C_BORDER};
    padding: {4 if compact else 7}px {10 if compact else 18}px; font-size: {12 if compact else tokens.F_LG}px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {tokens.C_CARD}; color: {tokens.C_ACCENT};
    font-weight: 700; border-bottom: 2px solid {tokens.C_ACCENT};
}}
QTabBar::tab:hover {{ background: #DCE7EF; color: {tokens.C_TEXT}; }}
"""
