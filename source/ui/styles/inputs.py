"""Shared input and legend control styles."""


def legend_checkbox(color: str, *, muted: bool = False) -> str:
    text = " color: #999999;" if muted else ""
    return (
        f"QCheckBox {{ spacing: 3px;{text} }}"
        "QCheckBox::indicator { width: 13px; height: 13px; }"
        f"QCheckBox::indicator:checked {{ background: {color}; border: 1px solid {color}; border-radius: 2px; }}"
        "QCheckBox::indicator:unchecked { background: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 2px; }"
    )
