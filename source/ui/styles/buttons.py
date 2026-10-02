"""Shared button variants; geometry and interaction policy live in ui.button_system."""

EDIT = (
    "QPushButton { background: #EFF6FF; color: #2563EB; border: 1.5px solid #BFDBFE;"
    " border-radius: 7px; padding: 4px 16px; font-weight: 600; }"
    " QPushButton:hover { background: #2563EB; color: white; }"
)


def dialog_action(*, compact: bool = False, pressed: bool = False) -> str:
    padding = "7px 16px" if compact else "8px 18px"
    rules = (
        "QPushButton { background: white !important; color: #0F172A !important; "
        "border: 1.5px solid #E2E8F0 !important; border-radius: 8px; "
        f"padding: {padding}; font-weight: 600; }} "
        "QPushButton:hover { background: #2563EB !important; color: white !important; "
        "border-color: #E2E8F0 !important; }"
    )
    if pressed:
        rules += (
            " QPushButton:pressed { background: #1E40AF !important; color: white !important; "
            "border-color: white !important; }"
        )
    return rules


def parser_action(*, primary: bool = False) -> str:
    return "QPushButton{border-radius:7px;padding:7px 14px;font-weight:700;" + (
        "background:#087FBE;color:#FFFFFF;border:1px solid #087FBE;}QPushButton:hover{background:#076BA0;}"
        if primary
        else "background:#FFFFFF;color:#0B4F71;border:1px solid #B8CDE0;}QPushButton:hover{background:#EEF7FC;}"
    )
