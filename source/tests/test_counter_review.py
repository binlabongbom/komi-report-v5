from datetime import UTC, datetime
import json

import pytest

from database import _open
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from test_daily_cache import _reading

KEY = "counter.paper.full_color.a4"
STAMP = datetime(2026, 9, 18, 8, tzinfo=UTC)


def pending(tmp_path):
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SERIAL-A")])
    cache = DailyCacheStore(tmp_path / "cache")
    for hour, value in ((8, 100), (9, 120), (10, 7), (11, 12)):
        at = STAMP.replace(hour=hour)
        cache.update_reading(0, _reading(value, at), at=at)
    return cache


def confirm(cache, preview):
    return cache.confirm_counter_baseline(0, STAMP.date(), KEY,
        expected_revision=preview["revision"], actor="TEST-PC", reason="Verified physical meter",
        at=STAMP.replace(hour=12))


def test_review_resumes_only_future_delta_and_preserves_audit_and_billing_hold(tmp_path):
    cache = pending(tmp_path)
    preview = cache.preview_counter_baseline(0, STAMP.date(), KEY)
    assert (preview["before"], preview["baseline"], preview["preserved_delta"]) == (120, 12, 20)
    resolution = confirm(cache, preview)
    later = STAMP.replace(hour=13)
    state = cache.update_reading(0, _reading(17, later), at=later)
    assert state["delta"][KEY] == 25
    assert not state["counter_review"]
    assert state["counter_resolutions"] == [resolution]
    assert resolution["actor"] == "TEST-PC"
    assert resolution["device_identity"]["serial"] == "SERIAL-A"
    cache.finalize(0, STAMP.date())
    with _open(commit=False) as conn:
        source = json.loads(conn.execute("SELECT source_json FROM daily_meter_records").fetchone()[0])
    assert source["reset_detected"]
    assert source["counter_resolutions"] == [resolution]
    next_day = STAMP.replace(day=19)
    cache.record_heartbeat(0, total=17, at=next_day)
    later = next_day.replace(hour=9)
    resumed = cache.update_reading(0, _reading(22, later), at=later)
    assert resumed["delta"][KEY] == 5
    assert not resumed["counter_review"]


@pytest.mark.parametrize("change", ["reading", "identity", "finalized"])
def test_stale_or_closed_review_cannot_change_cache(tmp_path, change):
    cache = pending(tmp_path)
    preview = cache.preview_counter_baseline(0, STAMP.date(), KEY)
    if change == "reading":
        later = STAMP.replace(hour=11, minute=5)
        cache.update_reading(0, _reading(13, later), at=later)
    elif change == "identity":
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Other", "192.0.2.10", serial="SERIAL-B")])
    else:
        cache.finalize(0, STAMP.date())
    path = cache.path(0, STAMP.date())
    before = path.read_bytes() if path.exists() else None
    with _open(commit=False) as conn:
        records_before = conn.execute("SELECT source_json,delta_json FROM daily_meter_records").fetchall()
    with pytest.raises(ValueError):
        confirm(cache, preview)
    assert (path.read_bytes() if path.exists() else None) == before
    with _open(commit=False) as conn:
        assert conn.execute("SELECT source_json,delta_json FROM daily_meter_records").fetchall() == records_before


def test_confirmed_review_is_not_applied_twice_and_a_new_drop_needs_review(tmp_path):
    cache = pending(tmp_path)
    preview = cache.preview_counter_baseline(0, STAMP.date(), KEY)
    confirm(cache, preview)
    with pytest.raises(ValueError):
        confirm(cache, preview)
    later = STAMP.replace(hour=13)
    state = cache.update_reading(0, _reading(2, later), at=later)
    assert state["delta"][KEY] == 20
    assert state["counter_review"][KEY]["before"] == 12
    assert len(state["counter_resolutions"]) == 1


def test_carried_review_requires_fresh_web_observation(tmp_path):
    cache = pending(tmp_path)
    cache.finalize(0, STAMP.date())
    next_day = STAMP.replace(day=19)
    cache.record_heartbeat(0, total=12, at=next_day)
    with pytest.raises(ValueError, match="current Web"):
        cache.preview_counter_baseline(0, next_day.date(), KEY)
