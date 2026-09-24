"""Shared label styling. Layout and font construction remain separate."""


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
