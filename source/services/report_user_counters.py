"""Small, immutable Counter evidence used only while preparing Users reports.

Keep canonical keys and daily identity boundaries intact: category derivation
and daily cost allocation still use the same functions as the full Raw report.
"""
from datetime import date
from typing import NamedTuple

from database import _open, report_read_checkpoint
from services.raw_counter_history import _review_metadata, iter_raw_counter_rows


class UserCounter(NamedTuple):
    device_slot: int
    record_date: date
    canonical_field: str
    label: str
    subject_type: str
    subject_id: str
    subject_name: str
    delta_value: float
    device_serial_snapshot: str
    needs_review: bool

    @property
    def is_subject(self) -> bool:
        return bool(self.subject_type)


_COLUMNS = (
    'device_slot', 'record_date', 'canonical_field', 'label', 'subject_type',
    'subject_id', 'subject_name', 'delta_value', 'device_serial_snapshot',
    'reset_count', 'counter_review_json', 'counter_resolutions_json',
)


def _user_counter_from_row(row):
    pending, reviewed, _remarks = _review_metadata(row[10], row[11])
    return UserCounter(
        int(row[0]), date.fromisoformat(str(row[1])), str(row[2]), str(row[3]),
        str(row[4]), str(row[5]), str(row[6]), float(row[7]), str(row[8]),
        bool(pending or reviewed or int(row[9])),
    )


def load_user_counter_history(slots, *, period_start=None, period_end=None, incremental=False):
    """Read only presentation evidence, retaining archive/revision precedence."""
    report_read_checkpoint()
    original = []
    with _open(commit=False) as connection:
        connection.execute('BEGIN')
        if incremental:
            from services.report_day_projection import iter_projected_days
            from services.report_detail_archive import ReportDetailArchive
            clauses, parameters = [], []
            if slots:
                clauses.append('device_slot IN (' + ','.join('?' for _ in slots) + ')')
                parameters.extend(slots)
            if period_start is not None:
                clauses.append('record_date>=?')
                parameters.append(period_start.isoformat())
            if period_end is not None:
                clauses.append('record_date<=?')
                parameters.append(period_end.isoformat())
            query = 'SELECT ' + ','.join(_COLUMNS) + ' FROM daily_raw_counter_records'
            if clauses:
                query += ' WHERE ' + ' AND '.join(clauses)
            query += (' ORDER BY device_slot,device_serial_snapshot,canonical_field,source_path,'
                      'subject_type,subject_id,record_date,id')
            archived = ReportDetailArchive().details(connection, 'raw', slots,
                                                     start=period_start, end=period_end)
            projected = (record for record, _period in iter_projected_days(
                connection, 'raw', query, parameters, _COLUMNS, _user_counter_from_row,
                archived, slots, start=period_start, end=period_end))
        else:
            rows = iter_raw_counter_rows(connection, slots, _COLUMNS,
                                         period_start=period_start, period_end=period_end)
            projected = (_user_counter_from_row(row) for row in rows)
        for index, record in enumerate(projected):
            if index % 256 == 0:
                report_read_checkpoint()
            original.append(record)
    from services.shared_report_history import raw_records
    with _open(commit=False) as connection:
        selected_slots = list(slots) if slots is not None else [
            row[0] for row in connection.execute('SELECT slot FROM devices')]
        shared = raw_records(connection, selected_slots, start=period_start,
                             end=period_end, existing=original)
    original.extend(UserCounter(
        row.device_slot, row.record_date, row.canonical_field, row.label,
        row.subject_type, row.subject_id, row.subject_name, row.delta_value,
        row.device_serial_snapshot, row.needs_review,
    ) for row in shared)
    # Preserve full Raw iteration order, including daily floating-point sums
    # and the first name used for otherwise unmatched subject identities.
    return tuple(sorted(original, key=lambda row: (
        row.record_date, row.device_slot, row.subject_type,
        row.subject_name, row.canonical_field)))
