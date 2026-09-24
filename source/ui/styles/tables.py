"""Tables component stylesheet definitions."""

FROZEN_TABLE = (
    "QTableWidget { border: 1px solid #E2E8F0; border-radius: 0px; }"
    "QTableWidget::item { border-radius: 0px; }"
    "QHeaderView::section { background: #F8FAFC; border: 1px solid #E2E8F0;"
    " border-radius: 0px; padding: 4px 6px; font-weight: 600; }"
)


SCHEDULE = (
    "QTableWidget{background:#FFFFFF;alternate-background-color:#F8FAFC;"
    "border:1px solid #D6E0EA;border-radius:7px;}"
    "QHeaderView::section{background:#EAF2F8;color:#123262;border:none;"
    "border-right:1px solid #D6E0EA;padding:5px 4px;font-weight:700;}"
    "QTableWidget QLineEdit,QTableWidget QSpinBox,QTableWidget QTimeEdit{"
    "font-size:12px;padding:2px 4px;min-height:28px;max-height:30px;}"
)


NETWORK_ACTIVITY = (
    "QTableWidget{background:white;alternate-background-color:#F8FAFC;"
    "border:1px solid #D7E0E8;border-radius:6px;color:#24364B;}"
    "QHeaderView::section{background:#EDF2F7;color:#42526B;font-weight:600;"
    "border:none;border-bottom:1px solid #D7E0E8;padding:10px 8px;}"
    "QTableWidget::item{padding:8px;border-bottom:1px solid #EDF2F7;}"
    "QTableWidget::item:selected{background:#E0EDFA;color:#123262;}"
)


ERROR_LIST_PANEL_TABLE = (
    "QTableWidget{background:white;border:1px solid "
    "#D7E0E8;}QHeaderView::section{background:#EDF2F7;color:#123262;padding:6px;border:1px "
    "solid #D7E0E8;}QTableWidget::item{padding:6px;}"
)


READER_MEMBERS_PANEL_TABLE = (
    "QTableWidget{background:white;border:1px solid "
    "#D7E0E8;}QHeaderView::section{background:#EDF2F7;color:#123262;padding:6px;border:1px "
    "solid #D7E0E8;}QTableWidget::item{padding:5px;}"
)


DETAIL_TABLE = (
    "QTableWidget { border: 1px solid #E2E8F0; }QHeaderView::section { background: #F8FAFC; "
    "border: 1px solid #E2E8F0; padding: 4px; font-weight: 600; }"
)


GROUP_HEADER = (
    "QTableWidget { border: 1px solid #CBD5E1; border-radius: 0px; background: #F8FAFC; "
    "}QTableWidget::item { border: 1px solid #CBD5E1; padding: 4px 6px; border-radius: 0px; "
    "font-weight: 600; color: #123262; }"
)


COMPACT_CELL = "QTableWidget::item { padding:2px 4px; }"
MATRIX_CELL = "QTableWidget::item { padding:2px; }"
