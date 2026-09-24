"""Scoped settings presentation rules. Builders receive values, never widgets."""

from . import tokens

SETTINGS_B_IMPORT_PARSER = (
    "QPushButton { background: #EFF6FF !important; color: #2563EB !important; border: 1.5px "
    "solid #BFDBFE !important; border-radius: 8px; padding: 8px 18px; font-weight: 600; } "
    "QPushButton:hover { background: #2563EB !important; color: white !important; "
    "border-color: #2563EB !important; }"
)


SETTINGS_V5_DB_MIGRATION_NOTE = (
    "background:#FFF4E5;color:#8A4B08;border:1px solid #F4C98B;border-radius:6px;padding:8px 10px;"
)


SETTINGS_B_OPEN_IMPORTED = (
    "QPushButton { background: white !important; color: #0F172A !important; border: 1.5px "
    "solid #E2E8F0 !important; border-radius: 8px; padding: 7px 16px; font-weight: 600; } "
    "QPushButton:hover { background: #16A34A !important; color: white !important; "
    "border-color: #16A34A !important; }"
)


def settings_runtime_info() -> str:
    return f"color:{tokens.C_TEXT2};background:#F1F5F9;border:1px solid #D6E0EA;border-radius:6px;padding:9px 11px;"


def settings_pwd_edit() -> str:
    return f"QLineEdit {{ border:1px solid {tokens.C_BORDER}; border-radius:6px; padding:4px 10px; color:{tokens.C_TEXT}; }}"


def settings_btn_cancel() -> str:
    return f"QPushButton {{ background:{tokens.C_BORDER}; color:{tokens.C_TEXT2}; border:none; border-radius:6px; padding:4px 14px; }}"


def settings_btn_ok() -> str:
    return f"QPushButton {{ background:{tokens.C_ACCENT}; color:white; border:none; border-radius:6px; padding:4px 14px; }}QPushButton:hover {{ background:#1E3A8A; }}"


SETTINGS_MAINTENANCE_ROW = (
    "QFrame#maintenance_action_row{background:#F8FAFC;border:1px solid "
    "#D6E0EA;border-radius:7px;} QLabel{background:transparent;border:none;}"
)


FLEET_SETTINGS_HEADER = "QFrame#settings_header{background:transparent;border:none;} QLabel{border:none;}"


FLEET_SETTINGS_OFFLINE_LICENSE_SUMMARY = (
    "color:#52677D;background:#F8FAFC;border:1px solid #D6E0EA;border-radius:6px;padding:8px 10px;"
)


FLEET_SETTINGS_BILLING_IMPACT = (
    "color:#75510A;background:#FFF7E8;border:1px solid #F2C879;border-radius:6px;padding:8px 10px;"
)


FLEET_SETTINGS_SCHEDULE_EDITOR = "QFrame#schedule_editor{background:#F8FAFC;border:none;}"


FLEET_SETTINGS_STAFF_LABEL = "color:#334155;font-weight:700;border:none;margin-top:4px;"


FLEET_SETTINGS_SUPPORT_DETAILS = (
    "QFrame#settings_support_details{background:#F8FAFC;border:1px solid "
    "#D6E0EA;border-radius:8px;} QLabel{background:transparent;border:none;}"
)


FLEET_SETTINGS_TASK_CARD_SHELL = (
    "QFrame#settings_task_card{background:#FFFFFF;border:1px solid "
    "#D6E0EA;border-radius:10px;} QLabel{background:transparent;border:none;}"
)


def fleet_settings_editor(key) -> str:
    return f"QFrame#settings_editor_{key}{{background:#F8FAFC;border:1px solid #D6E0EA;border-radius:8px;}} QLabel{{background:transparent;}}"


FLEET_SETTINGS_FIELD = "QWidget#settings_field{border:none;background:transparent;}"


FLEET_SETTINGS_REMOVE = "QPushButton{padding:0;font-size:14px;}"


FLEET_SETTINGS_AUTOSTART_STATUS = (
    "color:#16875D;background:#EDF8F2;border:1px solid #B8DFC9;border-radius:5px;padding:7px 9px;"
)


FLEET_SETTINGS_AUTOSTART_STATUS_WARNING = (
    "color:#8A4B08;background:#FFF4E5;border:1px solid #F4C98B;border-radius:5px;padding:7px 9px;"
)


FLEET_SETTINGS_AUTOSTART_STATUS_INACTIVE = (
    "color:#64748B;background:#F8FAFC;border:1px solid #D6E0EA;border-radius:5px;padding:7px 9px;"
)


BUILD_NETWORK_SETTINGS_WEB_SERVICE_CARD = (
    "QFrame#web_service_settings{background:transparent;border:none;}QLabel{background:transparent;border:none;}"
)


BUILD_NETWORK_SETTINGS_WEB_SERVICE_URL = (
    "color:#123262;background:#FFFFFF;border:1px solid #C9D8E6;border-radius:6px;padding:7px 9px;font-weight:700;"
)


BUILD_NETWORK_SETTINGS_WEB_ADVANCED_TOGGLE = "QToolButton{border:none;color:#64748B;padding:4px 0;}"


BUILD_NETWORK_SETTINGS_WEB_SECURITY = (
    "QFrame#web_security{background:transparent;border:none;}QLabel{background:transparent;border:none;}"
)


BUILD_NETWORK_SETTINGS_PEER_SYNC = (
    "QFrame#peer_sync_authorization{background:transparent;border:none;}QLabel{background:transparent;border:none;}"
)


def transparent_editor(object_name: str) -> str:
    return "QFrame#" + object_name + "{background:transparent;border:none;}"


PIPELINE_LOG_SCHEDULE_CARD = (
    "QFrame#schedule_timeline_card{background:white;border:1px solid "
    "#D6E0EA;border-radius:8px;}QLabel{background:transparent;border:none;}"
)


PIPELINE_LOG_SCHEDULE_BAND = "QFrame#schedule_timeline_band{background:transparent;border:none;}"


PIPELINE_LOG_LIVE_DETAIL = "background:#F8FAFC;border:1px solid #D6E0EA;border-radius:6px;padding:7px;color:#334155;"


PIPELINE_LOG_SECTION = (
    "QFrame#sync_technical_section{background:white;border:1px solid "
    "#D6E0EA;border-radius:8px;}QLabel{background:transparent;border:none;}"
)


WEB_ACCESS_CODE_DIALOG_ERROR = (
    "color:#B42318;background:#FEF3F2;border:1px solid #F2B8B5;border-radius:6px;padding:8px 10px;"
)


PIPELINE_LOG_REFRESH_STATUS = (
    "QFrame{background:white;border:1px solid #D6E0EA;border-radius:8px;}QLabel{background:transparent;border:none;}"
)


def pipeline_log_segment(background, border) -> str:
    return f"QFrame{{background:{background};border:1px solid {border};border-radius:5px;}}QLabel{{background:transparent;border:none;}}"


WEEKDAY_SELECTOR_BOX = "QCheckBox{font-size:11px;spacing:2px;padding:0;}"


REFRESH_STATUS_STYLE = "background:#FFF4E5;color:#8A4B08;border:1px solid #F4C98B;padding:11px 13px;font-weight:700;"


REFRESH_STATUS_STYLE_INACTIVE = (
    "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;padding:11px 13px;font-weight:700;"
)


REFRESH_STATUS_STYLE_SUCCESS = (
    "background:#EDF8F2;color:#16875D;border:1px solid #B8DFC9;padding:11px 13px;font-weight:700;"
)


def detail_warning(warning: bool) -> str:
    return (
        "color:#8A4B08;background:#FFF7E8;border:1px solid #F2C879;border-radius:7px;padding:8px 10px;"
        if warning
        else "color:#52677D;border:none;"
    )
