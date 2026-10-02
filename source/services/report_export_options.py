"""Lightweight export choices shared by the dialog and background writer."""
from dataclasses import dataclass
from datetime import date


REPORT_SECTIONS = (
    ('printers', 'การใช้งานรายเครื่อง', 'Printer usage'),
    ('users', 'มุมมองผู้ใช้', 'Users'),
    ('daily', 'มุมมองรายวัน', 'Daily usage'),
    ('legacy_printers', 'Legacy-รายเครื่อง', 'Legacy printers'),
    ('legacy_users', 'Legacy-ผู้ใช้', 'Legacy users'),
    ('legacy_daily', 'Legacy-รายวัน', 'Legacy daily'),
)
ALL_REPORT_SECTIONS = tuple(key for key, _thai, _english in REPORT_SECTIONS)


def validate_sections(sections):
    selected = frozenset(sections)
    if not selected or selected.difference(ALL_REPORT_SECTIONS):
        raise ValueError('เลือกรายงานที่ต้องการส่งออกอย่างน้อยหนึ่งรายการ')
    return tuple(key for key in ALL_REPORT_SECTIONS if key in selected)


@dataclass(frozen=True)
class ReportExportSelection:
    start: date
    end: date
    sections: tuple[str, ...] = ALL_REPORT_SECTIONS
