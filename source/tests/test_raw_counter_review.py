from datetime import datetime
import json
import sqlite3

import pytest

from database import _open
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.raw_counter_history import RawCounterHistoryStore, load_raw_counter_history
from services.raw_counter_review import RawCounterReviewStore
from test_raw_counter_history import _reading

STAMP = datetime.fromisoformat("2026-09-18T08:00:00+07:00")


def pending():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SERIAL-A")])
    store = RawCounterHistoryStore()
    for hour, value in ((8, 100), (9, 125), (10, 5), (11, 12)):
        at = STAMP.replace(hour=hour)
        store.update_reading(0, _reading(at, value), at=at)
    review = RawCounterReviewStore()
    key = next(iter(review.load(0, STAMP.date())["counter_review"]))
    return store, review, key


def confirm(review, key, preview, stamp=STAMP.replace(hour=12)):
    return review.confirm_counter_baseline(0, stamp.date(), key, expected_revision=preview["revision"],
        actor="TEST-PC", reason="Verified exact counter", at=stamp)


def test_raw_review_preserves_usage_and_audit_then_resumes_future_delta():
    store, review, key = pending()
    preview = review.preview_counter_baseline(0, STAMP.date(), key)
    assert (preview["before"], preview["baseline"], preview["preserved_delta"]) == (125, 12, 25)
    resolution = confirm(review, key, preview)
    with pytest.raises(ValueError):
        confirm(review, key, preview)
    later = STAMP.replace(hour=13)
    store.update_reading(0, _reading(later, 17), at=later)
    row = load_raw_counter_history([0])[-1]
    assert row.delta_value == 30
    assert row.needs_review and row.baseline_reviewed and not row.pending_review
    with _open(commit=False) as conn:
        audit = json.loads(conn.execute("SELECT counter_resolutions_json FROM daily_raw_counter_records").fetchone()[0])
    assert audit == [resolution]
    tomorrow = STAMP.replace(day=19)
    store.update_reading(0, _reading(tomorrow, 22), at=tomorrow)
    row = load_raw_counter_history([0])[-1]
    assert row.delta_value == 5 and not row.needs_review


def test_pending_review_crosses_day_and_restart_without_counting_absolute_meter():
    store, review, _ = pending()
    tomorrow = STAMP.replace(day=19)
    store = RawCounterHistoryStore()
    store.update_reading(0, _reading(tomorrow, 300), at=tomorrow)
    row = load_raw_counter_history([0])[-1]
    assert row.delta_value == 0 and row.pending_review and row.needs_review
    key = next(iter(review.load(0, tomorrow.date())["counter_review"]))
    preview = review.preview_counter_baseline(0, tomorrow.date(), key)
    confirm(review, key, preview, tomorrow)
    later = tomorrow.replace(hour=9)
    store.update_reading(0, _reading(later, 305), at=later)
    row = load_raw_counter_history([0])[-1]
    assert row.delta_value == 5 and row.needs_review


@pytest.mark.parametrize("change", ["reading", "identity"])
def test_changed_raw_review_cannot_be_applied(change):
    store, review, key = pending()
    preview = review.preview_counter_baseline(0, STAMP.date(), key)
    if change == "reading":
        at = STAMP.replace(hour=11, minute=1)
        store.update_reading(0, _reading(at, 15), at=at)
    else:
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Other", "192.0.2.10", serial="SERIAL-B")])
    with pytest.raises(ValueError):
        confirm(review, key, preview)
    with _open(commit=False) as conn:
        assert conn.execute("SELECT counter_resolutions_json FROM daily_raw_counter_records").fetchone()[0] == '[]'


def test_raw_audit_failure_rolls_back_hold_release():
    _, review, key = pending()
    preview = review.preview_counter_baseline(0, STAMP.date(), key)
    with _open() as conn:
        conn.execute("""CREATE TRIGGER fail_raw_audit BEFORE UPDATE OF counter_resolutions_json
            ON daily_raw_counter_records BEGIN SELECT RAISE(ABORT,'injected audit failure'); END""")
    with pytest.raises(sqlite3.Error):
        confirm(review, key, preview)
    assert review.preview_counter_baseline(0, STAMP.date(), key) == preview


def test_raw_review_labels_are_visible_in_screen_and_excel():
    pending()
    from services.report_excel_export import _raw_total
    from ui.cloud_reports import CloudReportsWidget
    rows = load_raw_counter_history([0])
    assert "รอตรวจสอบ" in _raw_total(rows)
    assert "25" in _raw_total(rows)
    assert "25" in CloudReportsWidget._raw_value(rows)
    assert CloudReportsWidget._raw_value(rows) != "25"


def test_upgrade_preserves_legacy_usage_and_requires_review():
    from migrations import _migration_022_raw_counter_reviews
    _, _, _ = pending()
    with _open() as conn:
        conn.execute("ALTER TABLE daily_raw_counter_records DROP COLUMN counter_review_json")
        conn.execute("ALTER TABLE daily_raw_counter_records DROP COLUMN counter_resolutions_json")
        # Reproduce the old release's already-recorded absolute post-drop usage.
        conn.execute("UPDATE daily_raw_counter_records SET delta_value=37")
        _migration_022_raw_counter_reviews(conn)
    row = load_raw_counter_history([0])[0]
    assert row.delta_value == 37 and row.pending_review
    tomorrow = STAMP.replace(day=19)
    RawCounterHistoryStore().update_reading(0, _reading(tomorrow, 20), at=tomorrow)
    assert load_raw_counter_history([0])[-1].delta_value == 0
