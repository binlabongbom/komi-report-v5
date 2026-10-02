from datetime import UTC, datetime
import json

import pytest

from database import _open
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.subject_history import SubjectDailyCacheStore, load_subject_history
from test_subject_history import _reading

STAMP = datetime(2026, 9, 18, 8, tzinfo=UTC)
KEY = "user:u-1"


def pending(tmp_path):
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SERIAL-A")])
    cache = SubjectDailyCacheStore(tmp_path / "subjects")
    for hour, value in ((8, 100), (9, 125), (10, 5), (11, 12)):
        at = STAMP.replace(hour=hour)
        cache.update_reading(0, _reading(value, collected_at=at), at=at)
    return cache


def confirm(cache, preview, stamp=STAMP.replace(hour=12)):
    return cache.confirm_counter_baseline(0, stamp.date(), KEY,
        expected_revision=preview["revision"], actor="TEST-PC", reason="Verified printer user counter", at=stamp)


def test_resume_preserves_usage_audit_and_review_warning(tmp_path):
    cache = pending(tmp_path)
    preview = cache.preview_counter_baseline(0, STAMP.date(), KEY)
    assert (preview["before"], preview["baseline"], preview["preserved_delta"]) == (125, 12, 25)
    resolution = confirm(cache, preview)
    with pytest.raises(ValueError):
        confirm(cache, preview)
    later = STAMP.replace(hour=13)
    state = cache.update_reading(0, _reading(17, collected_at=later), at=later)
    assert state["subjects"][KEY]["delta_total"] == 30
    assert load_subject_history([0], today=STAMP.date(), cache=cache)[0].needs_review
    cache.finalize(0, STAMP.date())
    with _open(commit=False) as conn:
        source = json.loads(conn.execute("SELECT source_json FROM daily_subject_records").fetchone()[0])
    assert source["counter_resolutions"] == [resolution]
    assert source["counter_review"] is None
    tomorrow = STAMP.replace(day=19)
    state = cache.update_reading(0, _reading(22, collected_at=tomorrow), at=tomorrow)
    assert state["subjects"][KEY]["delta_total"] == 5


def test_pending_review_survives_restart_and_day_rollover(tmp_path):
    cache = pending(tmp_path)
    cache.finalize(0, STAMP.date())
    cache = SubjectDailyCacheStore(cache.root)
    tomorrow = STAMP.replace(day=19)
    state = cache.update_reading(0, _reading(300, collected_at=tomorrow), at=tomorrow)
    assert state["subjects"][KEY]["delta_total"] == 0
    assert state["subjects"][KEY]["counter_review"]["before"] == 125
    preview = cache.preview_counter_baseline(0, tomorrow.date(), KEY)
    confirm(cache, preview, tomorrow)
    later = tomorrow.replace(hour=9)
    state = cache.update_reading(0, _reading(307, collected_at=later), at=later)
    assert state["subjects"][KEY]["delta_total"] == 7


@pytest.mark.parametrize("change", ["reading", "identity", "finalized"])
def test_changed_review_cannot_be_applied(tmp_path, change):
    cache = pending(tmp_path)
    preview = cache.preview_counter_baseline(0, STAMP.date(), KEY)
    if change == "reading":
        at = STAMP.replace(hour=11, minute=1)
        cache.update_reading(0, _reading(15, collected_at=at), at=at)
    elif change == "identity":
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Other", "192.0.2.10", serial="SERIAL-B")])
    else:
        cache.finalize(0, STAMP.date())
    path = cache.path(0, STAMP.date())
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(ValueError):
        confirm(cache, preview)
    assert (path.read_bytes() if path.exists() else None) == before


def test_failed_audit_write_keeps_pending_review(tmp_path, monkeypatch):
    cache = pending(tmp_path)
    preview = cache.preview_counter_baseline(0, STAMP.date(), KEY)
    path = cache.path(0, STAMP.date())
    before = path.read_bytes()
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(cache, "_atomic_write", fail)
    with pytest.raises(OSError):
        confirm(cache, preview)
    assert path.read_bytes() == before
