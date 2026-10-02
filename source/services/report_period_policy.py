"""Calendar-based limits for report selections; stored history is never trimmed."""
from calendar import monthrange
from datetime import date, timedelta

PREVIEW_YEARS = 1
EXPORT_YEARS = 5


def latest_allowed_end(start: date, years: int) -> date:
    """Inclusive end of N calendar years, including a leap-day opening.

    Jan 1 ends on Dec 31. A Feb 29 opening ends on Feb 28 when
    its anniversary year is not a leap year, rather than losing that day.
    """
    if start.year + years > date.max.year:
        return date.max
    anniversary = date(start.year + years, start.month, 1) + timedelta(days=start.day - 1)
    return anniversary - timedelta(days=1)


def latest_export_start(end: date) -> date:
    year = max(date.min.year, end.year - EXPORT_YEARS)
    day = min(end.day, monthrange(year, end.month)[1])
    return date(year, end.month, day) + timedelta(days=1)


def current_preview_period(today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    return (today.replace(day=1).isoformat(),
            today.replace(day=monthrange(today.year, today.month)[1]).isoformat())


class ReportPeriodLimitError(ValueError):
    diagnostic_code = 'input_invalid'

    def __init__(self, start: date, end: date, years: int):
        self.start, self.end, self.years = start, end, years
        self.latest_end = latest_allowed_end(start, years)
        kind = 'Preview' if years == PREVIEW_YEARS else 'Export Excel'
        detail = '12 เดือน' if years == PREVIEW_YEARS else f'{years} ปี'
        super().__init__(f'{kind} เลือกช่วงได้สูงสุด {detail} ต่อครั้ง '
                         f'เมื่อเริ่ม {start:%d/%m/%Y} วันสิ้นสุดต้องไม่เกิน {self.latest_end:%d/%m/%Y}')


def validate_report_period(start: date, end: date, *, years: int) -> None:
    if start > end:
        raise ValueError('วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด')
    if end > latest_allowed_end(start, years):
        raise ReportPeriodLimitError(start, end, years)


def validate_preview_period(period: tuple[str, str]) -> None:
    validate_report_period(*map(date.fromisoformat, period), years=PREVIEW_YEARS)
