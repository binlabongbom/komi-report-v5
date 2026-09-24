"""Shared label styling. Layout and font construction remain separate."""

from html import escape


def paper_size_detail(a3_value: str, a4_value: str) -> str:
    """Render metadata labels separately from safely escaped counter values."""
    return (
        "<span style='color:#64748B'>A3</span> "
        f"<span style='color:#111827'>{escape(a3_value)}</span>"
        "<span style='color:#94A3B8'>  |  </span>"
        "<span style='color:#64748B'>A4</span> "
        f"<span style='color:#111827'>{escape(a4_value)}</span>"
    )


def label(
    color: str,
    *,
    background: str | None = None,
    border: str | None = None,
    font_size: str | None = None,
    font_weight: str | None = None,
    padding: str | None = None,
) -> str:
    """Build text rules without broad selectors or inherited widget side effects."""
    values = {
        "color": color,
        "background": background,
        "border": border,
        "font-size": font_size,
        "font-weight": font_weight,
        "padding": padding,
    }
    return "".join(f"{name}:{value};" for name, value in values.items() if value is not None)
