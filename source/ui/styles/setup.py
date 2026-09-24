"""Setup component stylesheet definitions."""

SETUP_PANEL = """
        QDialog#setup_wizard_v5 {
            background: #F4F7FA;
            color: #172033;
        }
        QDialog#setup_wizard_v5 QLabel {
            color: #172033;
            background: transparent;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch {
            background: #FFFFFF;
            border: 1px solid #B8C8D8;
            border-radius: 9px;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton {
            min-width: 42px;
            min-height: 30px;
            background: transparent;
            color: #52677D;
            border: 0;
            border-radius: 7px;
            padding: 1px 8px;
            font-weight: 700;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton:hover {
            background: #EEF6FC;
            color: #174F78;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton:checked {
            background: #DCEEFF;
            color: #075B98;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton:focus {
            border: 1px solid #0879C9;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary {
            background: #0879C9;
            color: #FFFFFF;
            border: 1px solid #0879C9;
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 700;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary:hover {
            background: #066BAF;
            border-color: #066BAF;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary:pressed {
            background: #075384;
            border-color: #075384;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary:disabled {
            background: #E5ECF2;
            color: #52677D;
            border-color: #C2CFDB;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_outline {
            background: #FFFFFF;
            color: #24506E;
            border: 1px solid #B8C8D8;
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 600;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_outline:hover {
            background: #EAF3FA;
            color: #123262;
            border-color: #93B9D6;
        }
    """

SETUP_MODAL = """
        QDialog#wizard_modal {
            background: #F4F7FA;
            color: #172033;
        }
        QDialog#wizard_modal QLabel {
            color: #334155;
            background: transparent;
        }
        QDialog#wizard_modal QLineEdit,
        QDialog#wizard_modal QComboBox {
            min-height: 34px;
            background: #FFFFFF;
            color: #172033;
            border: 1px solid #B8C8D8;
            border-radius: 7px;
            padding: 4px 9px;
            selection-background-color: #DCEEFF;
            selection-color: #102A43;
        }
        QDialog#wizard_modal QLineEdit:focus,
        QDialog#wizard_modal QComboBox:focus {
            border: 2px solid #0879C9;
        }
        QDialog#wizard_modal QComboBox::drop-down {
            width: 34px;
            border-left: 1px solid #D6E0EA;
        }
        QDialog#wizard_modal QComboBox QAbstractItemView {
            background: #FFFFFF;
            color: #172033;
            border: 1px solid #B8C8D8;
            selection-background-color: #DCEEFF;
            selection-color: #102A43;
            outline: 0;
            padding: 4px;
        }
    """


CHOICE = (
    "QComboBox{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;"
    "border-radius:7px;padding:5px 40px 5px 10px;font-weight:700;}"
    "QComboBox:focus{border:2px solid #0879C9;}"
    "QComboBox::drop-down{width:34px;border-left:1px solid #D6E0EA;}"
    "QComboBox::down-arrow{image:none;width:0;height:0;}"
    "QComboBox QAbstractItemView{background:#FFFFFF;color:#172033;"
    "border:1px solid #B8C8D8;selection-background-color:#DCEEFF;"
    "selection-color:#102A43;outline:0;padding:4px;}"
)


PRICE_CALENDAR = (
    "QCalendarWidget{background:#FFFFFF;color:#172033;}"
    "QCalendarWidget QWidget#qt_calendar_navigationbar{background:#173A63;}"
    "QCalendarWidget QToolButton{background:transparent;color:#FFFFFF;border:none;"
    "border-radius:4px;padding:5px 8px;font-weight:700;}"
    "QCalendarWidget QToolButton:hover{background:#245783;}"
    "QCalendarWidget QSpinBox{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;"
    "border-radius:4px;padding:3px;}"
    "QCalendarWidget QMenu{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;}"
    "QCalendarWidget QAbstractItemView:enabled{background:#FFFFFF;color:#172033;"
    "selection-background-color:#0879C9;selection-color:#FFFFFF;outline:0;}"
    "QCalendarWidget QAbstractItemView:disabled{color:#94A3B8;}"
)


DEVICE_TABLE = (
    "QTableWidget#setup_device_table{background:#FFFFFF;color:#172033;"
    "border:1px solid #C9D9E8;gridline-color:#D6E0EA;}"
    "QTableWidget#setup_device_table:focus{border:2px solid #1769AA;}"
    "QTableWidget#setup_device_table::item {padding:0 10px;}"
    "QTableWidget#setup_device_table QHeaderView::section{background:#EAF1F7;"
    "color:#173A63;border:none;border-right:1px solid #C9D9E8;"
    "border-bottom:1px solid #B8C8D8;padding:8px 10px;font-weight:700;}"
    "QTableWidget#setup_device_table QTableCornerButton::section{background:#EAF1F7;"
    "border:none;border-right:1px solid #C9D9E8;border-bottom:1px solid #B8C8D8;}"
)


PRICE_SCROLL = (
    "QScrollArea#wizard_price_scroll{background:#F4F7FA;border:none;}"
    "QScrollArea#wizard_price_scroll QScrollBar:vertical{background:#E7EDF4;"
    "width:9px;border:none;border-radius:4px;}"
    "QScrollArea#wizard_price_scroll QScrollBar::handle:vertical{background:#91A4B8;"
    "min-height:28px;border:none;border-radius:4px;}"
    "QScrollArea#wizard_price_scroll QScrollBar::add-line:vertical,"
    "QScrollArea#wizard_price_scroll QScrollBar::sub-line:vertical{height:0;border:none;}"
)


SETUP_WIZARD_STYLE_WIZARD_COMBO = (
    "QAbstractItemView{background:#FFFFFF;color:#172033;border:1px solid "
    "#B8C8D8;selection-background-color:#DCEEFF;selection-color:#102A43;outline:0;padding:4px"
    ";}"
)


SETUP_WIZARD_COMPANY_SCROLL = "QScrollArea{background:#F4F7FA;border:none;}"


SETUP_WIZARD_CONTENT = "QWidget#company_setup_content{background:#F4F7FA;}"


SETUP_WIZARD_SECONDARY_JOIN_CARD = (
    "QFrame#secondary_join_card{background:#F0F8FF;border:1px solid "
    "#B9D7EE;border-radius:8px;} QLabel{background:transparent;border:none;}"
)


SETUP_WIZARD_COMPANY_CARD = "QFrame#company_setup_card{background:#FFFFFF;border:1px solid #C9D9E8;border-radius:8px;}"


SETUP_WIZARD_SECONDARY_EXISTING_BUTTON = (
    "QPushButton{background:transparent;color:#1769AA;border:none;padding:2px "
    "0;text-align:left;font-weight:650;}QPushButton:hover{color:#075B98;}QPushButton:focus{bo"
    "rder:1px solid #0879C9;border-radius:4px;}"
)


SETUP_WIZARD_PRIVACY_CARD = (
    "QFrame#registration_privacy_card{background:#FFFFFF;border:1px solid "
    "#C9D9E8;border-radius:8px;} QLabel{border:none;background:transparent;}"
)


SETUP_WIZARD_COMPANY_NOTICE = (
    "background:#EEF6F9;color:#245268;border:1px solid #C7DFE8;border-radius:6px;padding:10px;"
)


SETUP_WIZARD_SAFETY = "background:#EEF6F9;color:#245268;border:1px solid #C7DFE8;border-radius:6px;padding:9px;"


SETUP_WIZARD_SELECTION_BADGE = "background:#EAF1FA;color:#1769AA;padding:7px 11px;font-weight:700;border-radius:5px;"


SETUP_WIZARD_SCAN_PROGRESS_BAR = (
    "QProgressBar{background:#E7EEF5;border:1px solid "
    "#C5D5E5;border-radius:6px;color:#173A63;text-align:center;font-weight:700;min-height:24p"
    "x;}QProgressBar::chunk{background:#1685D1;border-radius:5px;}"
)


SETUP_WIZARD_REVIEW_PANEL = "QFrame#setup_review_panel{background:#FFFFFF;border:1px solid #CBD5E1;border-radius:8px;}"


SETUP_WIZARD_REVIEW_READY_NOTE = (
    "background:#EDF8F2;color:#176B49;border:1px solid #B8DFC9;border-radius:6px;padding:12px;"
)


SETUP_WIZARD_CONTENT_PRICE_PAGE = "QWidget#wizard_price_content{background:#F4F7FA;color:#172033;}"


SETUP_WIZARD_MODE_SECTION = "QFrame#price_mode_section{background:transparent;border:none;}"


SETUP_WIZARD_EFFECTIVE_DATE = (
    "QDateEdit{background:#FFFFFF;color:#172033;border:1px solid "
    "#B8C7D9;border-radius:6px;padding:7px 11px;font-weight:700;}QDateEdit:focus{border:2px "
    "solid #1769AA;}"
)


SETUP_WIZARD_SHARED_PRICE_BOX = "QFrame#shared_price_box{background:transparent;border:none;}"


SETUP_WIZARD_PER_DEVICE_PRICE_BOX = "QFrame#per_device_price_box{background:transparent;border:none;}"


SETUP_WIZARD_BILLING_SECTION = "QFrame#billing_section{background:transparent;border-top:1px solid #D6E0EA;}"


SETUP_WIZARD_CELL = "QWidget#price_value_cell{background:#FFFFFF;border:none;}"


SETUP_WIZARD_MATRIX = "QFrame#price_matrix{background:#D6E0EA;border:1px solid #D6E0EA;border-radius:6px;}"


SETUP_WIZARD_SECTION = "QFrame{background:#FFFFFF;border:none;border-bottom:1px solid #E2E8F0;}"


def device_price_card(slot) -> str:
    return f"QFrame#device_price_card_{slot}{{background:transparent;border:none;border-top:1px solid #D6E0EA;}}"


SETUP_WIZARD_SPIN = (
    "QDoubleSpinBox{background:#FFFFFF;color:#172033;border:1px solid "
    "#B8C7D9;border-radius:6px;padding:8px "
    "11px;font-weight:700;}QDoubleSpinBox:focus{border:2px solid #1769AA;background:#F8FCFF;}"
)


def setup_wizard_checkbox_container(background) -> str:
    return f"background:{background};"


SETUP_WIZARD_REGISTRATION_STATUS_LABEL = (
    "background:#FFF8E8;color:#75510A;border:1px solid #E8D7A4;border-radius:16px;font-weight:700;"
)


COMPANY_PAGE_COMPANY_NAME_NORMAL_STYLE = (
    "QLineEdit{background:#FFFFFF;color:#172033;border:1px solid "
    "#B8C7D9;border-radius:6px;padding:8px 11px;}QLineEdit:focus{border:2px solid #1769AA;}"
)


COMPANY_PAGE_COMPANY_NAME_ERROR_STYLE = (
    "QLineEdit{background:#FFF7F6;color:#172033;border:2px solid "
    "#B42318;border-radius:6px;padding:7px 10px;}QLineEdit:focus{border:2px solid #B42318;}"
)


COMPANY_PAGE_READONLY_STYLE = (
    "QLineEdit{background:#F1F5F9;color:#475569;border:1px solid "
    "#D6E0EA;border-radius:6px;padding:8px 11px;font-weight:700;}"
)


PRICE_PAGE_MODE_STYLE = (
    "QPushButton{background:#FFFFFF;color:#172033;border:1px solid "
    "#CBD5E1;border-radius:6px;padding:14px "
    "18px;font-weight:700;text-align:left;}QPushButton:hover{border-color:#7C91AA;background:"
    "#F8FAFC;}QPushButton:checked{background:#EAF3FB;color:#0B4F8A;border:2px solid "
    "#1769AA;}QPushButton:focus{border:2px solid #1769AA;background:#F8FCFF;}"
)


PRICE_PAGE_BILLING_INPUT_STYLE = (
    "QDoubleSpinBox,QComboBox{background:#FFFFFF;color:#172033;border:1px solid "
    "#B8C7D9;border-radius:6px;padding:7px "
    "11px;font-weight:700;}QDoubleSpinBox:focus,QComboBox:focus{border:2px solid #1769AA;}"
)


UPDATE_PROGRESS_STYLE = "background:#EDF8F2;color:#176B49;border-radius:5px;font-weight:700;"


UPDATE_PROGRESS_STYLE_ACTIVE = "background:#DCEEFF;color:#0B4F8A;border-radius:5px;font-weight:800;"


UPDATE_PROGRESS_STYLE_INACTIVE = "background:#E9EEF4;color:#64748B;border-radius:5px;font-weight:600;"
