"""Names survive the same archive/revision boundaries as their usage totals."""
import json
from datetime import date

import pytest

from database import _open, set_cfg
from services.subject_history import load_subject_history
from test_report_detail_archive import archive_all, fixture


@pytest.mark.parametrize('old_summary_format', [False, True])
def test_named_day_followed_by_id_survives_separate_archive_blocks(old_summary_format):
    _, _, archive = fixture()
    set_cfg('billing_day', '31')
    with _open() as conn:
        conn.execute("UPDATE daily_subject_records SET subject_id='123', subject_name='123'")
        conn.execute("UPDATE daily_subject_records SET subject_name='สมชาย' WHERE record_date='2024-01-02'")
    period = (date(2024, 1, 1), date(2024, 1, 31))
    before = load_subject_history([0], only_period=period)
    assert len(before) == 1 and before[0].subject_name == 'สมชาย'
    assert before[0].name_observed_on == date(2024, 1, 2)
    assert archive_all(archive)
    if old_summary_format:
        with _open() as conn:
            for rowid, payload in conn.execute('SELECT rowid,summary_json FROM archived_subject_periods').fetchall():
                item = json.loads(payload)
                item.pop('_name_date', None)
                conn.execute('UPDATE archived_subject_periods SET summary_json=? WHERE rowid=?',
                             (json.dumps(item), rowid))
    after = load_subject_history([0], only_period=period)
    assert len(after) == 1 and after[0].subject_name == 'สมชาย'
    assert after[0].period_usage == before[0].period_usage
    assert after[0].latest_total == before[0].latest_total
    if not old_summary_format:
        assert after == before


def test_new_real_name_uses_name_date_when_archive_counters_are_later():
    _, _, archive = fixture()
    set_cfg('billing_day', '31')
    with _open() as conn:
        conn.execute("UPDATE daily_subject_records SET subject_id='123', subject_name='123'")
        conn.execute("UPDATE daily_subject_records SET subject_name='สมชาย' WHERE record_date='2024-01-02'")
        conn.execute("UPDATE daily_subject_records SET subject_name='สมชาย ฝ่ายขาย' WHERE record_date='2024-01-03'")
    period = (date(2024, 1, 1), date(2024, 1, 31))
    before = load_subject_history([0], only_period=period)
    assert before[0].subject_name == 'สมชาย ฝ่ายขาย'
    assert before[0].name_observed_on == date(2024, 1, 3)
    assert archive_all(archive)
    assert load_subject_history([0], only_period=period) == before
