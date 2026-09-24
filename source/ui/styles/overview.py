"""Overview stylesheet rules."""

from . import tokens


def build_overview_qss():
    return f"""

PageOverviewV2 {{ background: {tokens.C_BG}; }}
QLabel#overview_status_line {{
    background: transparent; color: {tokens.C_TEXT2}; border: none;
    padding: 0 2px 2px 2px; font-size: {tokens.F_SM}pt;
}}
QLabel#overview_quality_line {{
    background: #EFF6FF; color: #174EA6;
    border: 1px solid #BFDBFE; border-radius: 6px;
    padding: 6px 10px; font-size: {tokens.F_SM}pt;
}}
QFrame#overview_kpi_panel,
QFrame#overview_printer_panel,
QFrame#overview_chart_panel {{
    background: {tokens.C_CARD}; border: 1px solid {tokens.C_BORDER}; border-radius: 12px;
}}
QFrame#overview_metric_card {{
    background: {tokens.C_CARD}; border: 1px solid {tokens.C_TONER_BORDER}; border-radius: 9px;
}}
QLabel#overview_metric_title {{ color: {tokens.C_TEXT}; background: transparent; border: none; }}
QLabel#overview_metric_value,
QLabel#overview_metric_detail {{ background: transparent; border: none; }}
QWidget#overview_metric_content {{ background: transparent; border: none; }}
QWidget#overview_toner_group {{ background: transparent; border: none; }}
QFrame#overview_printer_row_v2 {{
    background: {tokens.C_CARD}; border: 1px solid {tokens.C_TONER_BORDER}; border-radius: 9px;
}}
QFrame#overview_printer_row_v2 QLabel {{
    background: transparent; border: none;
}}
QWidget#overview_printer_identity,
QWidget#overview_printer_details {{
    background: transparent; border: none;
}}
QPushButton#overview_ip_link {{
    background: transparent; color: {tokens.C_ACCENT}; border: none;
    padding: 0; margin: 0; text-align: left; font-weight: 500;
}}
QPushButton#overview_ip_link:hover {{
    color: #017DD0; text-decoration: underline;
}}
QPushButton#overview_ip_link:pressed {{ color: #074A76; }}
QLabel#overview_ip_link {{
    background: transparent; border: none; padding: 0; margin: 0;
}}
QWidget#overview_printer_list {{ background: {tokens.C_CARD}; }}
QComboBox#overview_period_combo {{
    background: {tokens.C_CARD}; color: {tokens.C_TEXT};
    border: 1px solid {tokens.C_TONER_BORDER}; border-radius: 6px;
    padding: 4px 28px 4px 10px;
    font-size: {tokens.F_MD}pt; font-weight: 500;
}}
QComboBox#overview_period_combo:hover,
QComboBox#overview_period_combo:focus {{
    border: 1px solid {tokens.C_TONER_BORDER};
}}
QComboBox#overview_period_combo::drop-down {{
    width: 26px; border: none; background: transparent;
}}
QWidget#overview_period_selector {{
    background: {tokens.C_TABLE_HEADER}; border: 1px solid {tokens.C_TABLE_HEADER}; border-radius: 8px;
}}
QPushButton#overview_period_button {{
    background: {tokens.C_TABLE_HEADER}; color: {tokens.C_TABLE_HEADER_TEXT};
    border: none; border-right: 1px solid #D8E7F3;
    border-radius: 0; padding: 4px 8px; font-size: {tokens.F_LG}pt; font-weight: 600;
}}
QPushButton#overview_period_button[segmentPosition="first"] {{
    border-top-left-radius: 7px; border-bottom-left-radius: 7px;
}}
QPushButton#overview_period_button[segmentPosition="last"] {{
    border-top-right-radius: 7px; border-bottom-right-radius: 7px; border-right: none;
}}
QPushButton#overview_period_button:hover {{ background: {tokens.C_ACCENT}; }}
QPushButton#overview_period_button:checked {{
    background: {tokens.C_CARD}; color: {tokens.C_TABLE_HEADER}; font-weight: 800;
}}

/* ── พื้นหลังหน้า Overview ── */
PageOverview {{
    background: {tokens.C_BG};
}}

/* ── Summary strip: one surface, four readable values ── */
QFrame#overview_summary_strip {{
    background: {tokens.C_CARD};
    border: 1px solid {tokens.C_BORDER};
    border-radius: 8px;
}}
QPushButton#btn_outline:disabled {{
    background: #E8EEF4; color: #52677D;
    border-color: #C2CFDB;
}}
QFrame#overview_summary_strip QFrame#stat_card {{
    background: transparent;
    border: none;
    border-radius: 0px;
}}

/* ── การ์ด section (Pie / Bar / Top Users) ── */
QFrame#card {{
    background: {tokens.C_CARD};
    border: 1px solid {tokens.C_BORDER};
    border-radius: 10px;
}}

/* ── Operational and data-quality states ── */
QLabel#overview_status, QLabel#overview_quality {{
    border: 1px solid {tokens.C_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: {tokens.F_MD}pt;
}}
QLabel#overview_status[state="success"], QLabel#overview_quality[state="success"] {{
    background: #EAF7EF;
    color: #087A55;
    border-color: #B8DFC9;
}}
QLabel#overview_status[state="warning"], QLabel#overview_quality[state="warning"] {{
    background: #FFF4E5;
    color: #8A4B08;
    border-color: #F4C98B;
}}
QLabel#overview_status[state="error"] {{
    background: #FFF0F0;
    color: #B42318;
    border-color: #F5B7B1;
}}
QLabel#overview_quality[state="info"] {{
    background: #EFF6FF;
    color: #174EA6;
    border-color: #BFDBFE;
}}
QLabel#overview_empty {{
    background: #F8FAFC;
    color: {tokens.C_TEXT2};
    border: 1px dashed {tokens.C_BORDER};
    border-radius: 8px;
    padding: 24px;
    font-size: {tokens.F_MD}pt;
}}
QFrame#overview_printer_row {{
    background: {tokens.C_CARD};
    border: none;
    border-bottom: 1px solid {tokens.C_BORDER};
}}
QFrame#overview_printer_row[lastRow="true"] {{
    border-bottom: none;
}}

/* ── Overview actions ── */
QPushButton#btn_primary {{
    background: #dbeafe;
    color: #123262;
    border: 1px solid #1a3d8a;
    border-radius: {tokens.BUTTON_RADIUS}px;
    padding: 7px 16px;
    font-size: {tokens.F_MD}pt;
    font-weight: 700;
}}
QPushButton#btn_primary:hover {{
    background: #bfdbfe;
    color: #123262;
    border-color: #1a3d8a;
}}
QPushButton#btn_outline {{
    background: #f4f4f4;
    color: #123262;
    border: 1px solid #d0d0d0;
    border-radius: {tokens.BUTTON_RADIUS}px;
    padding: 7px 16px;
    font-size: {tokens.F_MD}pt;
    font-weight: 600;
}}
QPushButton#btn_outline:hover {{
    background: #dbeafe;
    color: #123262;
    border-color: #93c5fd;
}}

/* ── ตาราง Top Users ── */
QTableWidget {{
    background: {tokens.C_CARD};
    border: 1px solid {tokens.C_BORDER};
    border-radius: 6px;
    gridline-color: {tokens.C_BORDER};
    font-size: {tokens.F_MD}pt;
}}
QTableWidget::item {{
    padding: 3px 8px;
}}
QHeaderView::section {{
    background: #f8fafc;
    color: {tokens.C_TEXT2};
    font-size: {tokens.F_SM}pt;
    font-weight: 600;
    padding: 4px 8px;
    border: none;
    border-bottom: 1px solid {tokens.C_BORDER};
    border-right: 1px solid {tokens.C_BORDER};
}}

/* ── ป้ายเวลาอัปเดต ── */
QLabel#lbl_ov_time {{
    color: {tokens.C_TEXT3};
    font-size: {tokens.F_XS}pt;
}}
"""
