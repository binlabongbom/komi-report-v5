"""Report palette and scoped styles, separate from data and chart construction."""

from . import tokens

NAVY = "#123262"
BLUE = "#1677C8"
ORANGE = "#E58A18"
SLATE = "#56677A"
GREEN = "#16805A"
LINE = "#D9E2EA"
MUTED = "#66788A"
PANEL = "#FFFFFF"
DEVICE_COLORS = (BLUE, ORANGE, "#D65364")


def base_qss() -> str:
    return (
        f"QWidget#cloud_reports{{background:#F3F6F8;color:#243244;}}"
        "QWidget#cloud_reports QLabel{background:transparent;border:none;}"
        f"QFrame#cloud_report_toolbar,QFrame#cloud_report_panel{{"
        f"background:{PANEL};border:1px solid {LINE};border-radius:7px;}}"
        "QLabel#cloud_title{font-weight:700;color:#102A43;}"
        f"QLabel#cloud_subtitle,QLabel#cloud_panel_subtitle{{color:{MUTED};font-size:12px;}}"
        "QLabel#cloud_panel_title{font-size:15px;font-weight:750;color:#25364A;}"
        f"QFrame#cloud_overview_kpi_panel{{background:{PANEL};border:1px solid {LINE};border-radius:12px;}}"
        "QFrame#cloud_overview_metric_card{background:#FFFFFF;border:1px solid #D7E0EA;border-radius:9px;}"
        "QWidget#cloud_overview_metric_content{background:transparent;border:none;}"
        "QLabel#cloud_overview_metric_title{color:#25364A;font-size:15px;font-weight:750;}"
        f"QLabel#cloud_overview_metric_detail{{color:{MUTED};font-size:11px;}}"
        "QLabel#cloud_overview_metric_value{font-size:24px;font-weight:800;}"
        f"QTableWidget{{background:white;border:1px solid {LINE};gridline-color:#E8EDF2;"
        "alternate-background-color:#F7F9FB;selection-background-color:#E8F2FB;"
        "selection-color:#203247;}"
        "QTableWidget::item{padding:8px 10px;}"
        "QHeaderView::section{background:#F1F4F7;color:#526476;border:0;"
        "border-bottom:1px solid #D9E2EA;padding:8px 10px 8px 1px;font-weight:700;}"
        "QLabel#cloud_period_label{color:#526476;font-size:11px;font-weight:700;}"
        "QDateEdit#cloud_period_date{background:white;color:#243244;border:1px solid #B9CBDD;"
        "border-radius:6px;padding:8px 10px;min-width:132px;font-weight:700;}"
        f"QDateEdit#cloud_period_date:hover,QDateEdit#cloud_period_date:focus{{border-color:{BLUE};}}"
        "QDateEdit#cloud_period_date::drop-down{border:0;width:24px;}"
        f"QPushButton#cloud_primary{{background:{BLUE};color:white;border:0;border-radius:5px;"
        "padding:9px 14px;font-weight:700;}"
        f"QPushButton#cloud_export{{background:white;color:{NAVY};border:1px solid #B9CBDD;"
        "border-radius:5px;padding:9px 14px;font-weight:700;}"
        f"QPushButton#cloud_export:hover{{background:#EEF5FB;border-color:{BLUE};}}"
        f"QPushButton#cloud_retry{{color:{NAVY};background:white;border:1px solid #B9CBDD;"
        "border-radius:4px;padding:4px 6px;font-size:11px;}"
        f"QPushButton#cloud_reset{{background:#EEF3F7;color:{NAVY};border:1px solid {LINE};"
        "border-radius:5px;padding:7px 11px;font-weight:700;}"
        "QWidget#cloud_calendar_control{background:transparent;border:0;}"
        f"QPushButton#cloud_calendar_button{{background:#FFFFFF;color:{NAVY};"
        "border:1px solid #B9CBDD;border-radius:4px;"
        "padding:0;margin:0;font-size:16px;}"
        f"QPushButton#cloud_calendar_button:hover,QPushButton#cloud_calendar_button:focus{{"
        f"background:#EEF5FB;border-color:{BLUE};}}"
        "QPushButton#cloud_calendar_button:pressed{background:#DDECF8;}"
        f"QPushButton#cloud_granularity{{background:#EEF3F7;color:{NAVY};border:1px solid {LINE};"
        "border-radius:5px;min-width:30px;padding:6px 8px;font-weight:800;}"
        f"QPushButton#cloud_granularity:checked{{background:{NAVY};color:white;border-color:{NAVY};}}"
        f"QLabel#cloud_filter_badge{{background:#FFF2DE;color:#95570A;border:1px solid #F2D09B;"
        "border-radius:11px;padding:5px 9px;font-weight:700;}"
        "QLabel#cloud_error{background:#FFF0F1;color:#A61D2D;border:1px solid #F1BBC1;"
        "border-radius:5px;padding:9px 12px;font-weight:700;}"
    )


def density_qss(compact: bool) -> str:
    sizes = {
        "cloud_subtitle": 11 if compact else 12,
        "cloud_panel_title": 13 if compact else 15,
        "cloud_panel_subtitle": 11 if compact else 12,
        "cloud_overview_metric_title": 11 if compact else 13,
        "cloud_overview_metric_value": 24 if compact else 32,
        "cloud_overview_metric_detail": 10 if compact else 11,
    }
    density_qss = "".join(f"QLabel#{name}{{font-size:{size}px;}}" for name, size in sizes.items())
    density_qss += (
        f"QDateEdit#cloud_period_date{{font-size:{11 if compact else 12}px;padding:4px 7px;min-width:126px;}}"
        f"QPushButton#cloud_export,QPushButton#cloud_primary{{font-size:{11 if compact else 12}px;padding:6px 10px;}}"
    )
    return density_qss


PERIOD_CALENDAR = (
    "QCalendarWidget QWidget{background:#FFFFFF;color:#243244;}"
    "QCalendarWidget QToolButton{background:#EEF4F8;color:#25364A;border:0;"
    "padding:6px;font-weight:700;}"
    "QCalendarWidget QAbstractItemView{background:#FFFFFF;color:#243244;"
    "selection-background-color:#1677C8;selection-color:#FFFFFF;outline:0;}"
    "QCalendarWidget QSpinBox{background:#FFFFFF;color:#243244;border:1px solid #B9CBDD;}"
)


EXPORT_PROGRESS = """
            QDialog#excel_export_progress { background:#FFFFFF; }
            QLabel { color:#123262; background:transparent; }
            QProgressBar { border:1px solid #C9D8E6; border-radius:7px;
                background:#EEF4FA; color:#123262; min-height:24px; text-align:center; }
            QProgressBar::chunk { background:#1677C8; border-radius:6px; }
            QPushButton { background:#FFFFFF; color:#123262; border:1px solid #C9D8E6;
                border-radius:6px; padding:8px 20px; }
            QPushButton:hover { background:#EEF4FA; }
            QPushButton:disabled { color:#66788A; background:#F3F6F8; }
        """


def billing_day_badge(slot_light) -> str:
    return f"color:{tokens.C_ACCENT}; background:{slot_light}; padding:4px 14px; border-radius:5px;"


def history_pie_container() -> str:
    return f"background: {tokens.C_BG};"


LEGACY_HISTORY_IMPORT_DIALOG_BOUNDARY = (
    "background:#FFF7E6;color:#7A4B00;border:1px solid #F2D28B;border-radius:6px;padding:10px 12px;font-weight:700;"
)


LEGACY_HISTORY_IMPORT_DIALOG_PREVIEW_SUMMARY = (
    "background:#F8FAFC;color:#173A63;border:1px solid #D7E1EA;border-radius:7px;padding:14px;"
)


HISTORY_PANEL = "QFrame#reports_header{background:#ECF3F8;border:1px solid #C3D2DF;border-radius:8px;}"


HISTORY_REPORT_ADVANCED_PANEL = (
    "QFrame#report_advanced_panel{background:#F8FAFC;border:1px solid #C9D5E1;border-radius:8px;}"
)


HISTORY_REPORTS_ERROR = (
    "background:#FFF1F1;color:#B42318;padding:9px 11px;border:1px solid #FDA29B;border-radius:5px;font-weight:700;"
)


HISTORY_REPORT_PERIOD_NOTE = "background:#EEF6F9;color:#245268;padding:8px 10px;border-radius:5px;"


HISTORY_REPORT_PROVISIONAL_SUMMARY = "background:#DCEEFF;color:#074F8C;padding:9px 11px;border-left:4px solid #0B75C9;"


HISTORY_REPORT_COST_DETAIL_SUMMARY = (
    "background:#F8FAFC;color:#344054;padding:7px 10px;border:1px solid #E4E7EC;border-radius:5px;"
)


HISTORY_REPORTS_OVERVIEW = "background:white;border:1px solid #C9D5E1;border-radius:8px;"


CLOUD_REPORTS_WIDGET_CHART_VIEW = "background:white;border:0;"


CLOUD_REPORTS_WIDGET_BUTTON = "QPushButton:checked { background:#123262; color:white; border:1px solid #123262; }"


EXPORT_PROGRESS_DIALOG_TITLE = "font-size:13.5pt;font-weight:700;"


PRINTER_USAGE_TABLE_HOST = "background:#F8FAFC;"


PRINTER_USAGE_TABLE_BUTTON = (
    "QToolButton { color:#123262; background:#E8F2FA; border:1px solid #AABBCF; "
    "border-radius:4px; font-size:18px; } QToolButton:focus { border:2px solid #0065A3; }"
)


BILLING_AUDIT_HINT = "background:#EEF6F9;color:#245268;border:1px solid #C8E1EA;border-radius:6px;padding:6px;"


def billing_audit_coverage(style) -> str:
    return f"{style}border-radius:6px;padding:10px 12px;font-weight:700;"


REFRESH_COVERAGE_STYLE = "background:#FFF0F0;color:#A61B1B;border:1px solid #F4B4B4;"


REFRESH_COVERAGE_STYLE_WARNING = "background:#FFF8E8;color:#7A4A00;border:1px solid #EACB88;"


REFRESH_COVERAGE_STYLE_SUCCESS = "background:#EDF8F2;color:#146C4A;border:1px solid #B8DFC9;"


def quality_summary(warning: bool) -> str:
    return (
        "background:#FFF4E5;color:#8A4B08;padding:9px 12px;font-weight:700;"
        if warning
        else "background:#F8FAFC;color:#123262;padding:9px 12px;font-weight:700;"
    )
