from dataclasses import replace
from datetime import UTC, datetime
import json

import pytest

from database import _open
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.slot_replacement import preview_replacement, confirm_replacement
from services.reconciliation import ReconciliationReport
from test_daily_cache import _reading

STAMP = datetime(2026, 9, 18, 8, tzinfo=UTC)
KEY = "counter.paper.full_color.a4"


def setup(tmp_path):
    repo = DeviceConfigRepository()
    repo.replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="OLD")])
    cache = DailyCacheStore(tmp_path / "cache")
    cache.update_reading(0, _reading(100, STAMP), at=STAMP)
    at = STAMP.replace(hour=9)
    cache.update_reading(0, _reading(120, at), at=at)
    repo.update_runtime(0, serial="USED", status="online", checked_at=at.isoformat())
    at = STAMP.replace(hour=10)
    cache.update_reading(0, _reading(9000, at), at=at)
    return cache, repo


def confirm(cache, preview):
    return confirm_replacement(cache, 0, STAMP.date(), expected_revision=preview["revision"],
                               actor="PC-A", reason="Checked serial and physical meter",
                               at=STAMP.replace(hour=12))


def test_used_printer_preserves_usage_and_old_evidence_without_meter_jump(tmp_path):
    cache, _ = setup(tmp_path)
    before = cache.path(0, STAMP.date()).read_bytes()
    preview = preview_replacement(cache, 0, STAMP.date())
    assert cache.path(0, STAMP.date()).read_bytes() == before
    assert preview["baseline"][KEY] == 9000
    assert preview["preserved_delta"][KEY] == 20
    assert cache.load(0, STAMP.date())["latest"][KEY] == 120
    audit = confirm(cache, preview)
    at = STAMP.replace(hour=13)
    state = cache.update_reading(0, _reading(9015, at), at=at,
                                 reconciliation=ReconciliationReport(checked_count=16, issues=()))
    assert state["delta"][KEY] == 35
    assert state["device_segments"][0]["device_identity"]["serial"] == "OLD"
    assert state["device_segments"][0]["latest"][KEY] == 120
    assert state["slot_replacements"] == [audit]
    with pytest.raises(ValueError):
        confirm(cache, preview)
    cache.finalize(0, STAMP.date())
    with _open(commit=False) as conn:
        source = json.loads(conn.execute("SELECT source_json FROM daily_meter_records").fetchone()[0])
        kind, reason = conn.execute("SELECT entry_kind,hold_reason FROM billing_ledger").fetchone()
    assert source["device_segments"][0]["delta"][KEY] == 20
    assert source["slot_replacements"] == [audit]
    assert (kind, reason) == ("hold", "device_identity_conflict")
    next_day = STAMP.replace(day=19)
    cache.record_heartbeat(0, total=9015, at=next_day)
    at = next_day.replace(hour=9)
    state = cache.update_reading(0, _reading(9020, at), at=at)
    assert state["delta"][KEY] == 5


@pytest.mark.parametrize("change", ["new_reading", "serial", "host", "finalized"])
def test_changed_or_finalized_preview_cannot_apply(tmp_path, change):
    cache, repo = setup(tmp_path)
    preview = preview_replacement(cache, 0, STAMP.date())
    if change == "new_reading":
        at = STAMP.replace(hour=11)
        cache.update_reading(0, _reading(9005, at), at=at)
    elif change == "serial":
        repo.update_runtime(0, serial="OTHER", status="online", checked_at=STAMP.isoformat())
    elif change == "host":
        repo.replace_all([DeviceConfig(0, "Office", "192.0.2.11", serial="USED")])
    else:
        cache.finalize(0, STAMP.date())
    path = cache.path(0, STAMP.date())
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(ValueError):
        confirm(cache, preview)
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("change", ["schema", "counter_set"])
def test_changed_mapping_requires_separate_review(tmp_path, change):
    cache, _ = setup(tmp_path)
    at = STAMP.replace(hour=11)
    reading = _reading(9005, at)
    reading = (replace(reading, schema_version="other") if change == "schema" else
               replace(reading, counters=(replace(reading.counters[0], canonical_field="other"),)))
    cache.update_reading(0, reading, at=at)
    with pytest.raises(ValueError):
        preview_replacement(cache, 0, STAMP.date())
    assert cache.load(0, STAMP.date())["delta"][KEY] == 20


def test_late_or_wrong_host_cannot_replace_quarantined_observation(tmp_path):
    cache, _ = setup(tmp_path)
    at = STAMP.replace(hour=9, minute=30)
    cache.update_reading(0, _reading(8990, at), at=at)
    at = STAMP.replace(hour=11)
    cache.update_reading(0, replace(_reading(99, at), host="192.0.2.99"), at=at)
    assert preview_replacement(cache, 0, STAMP.date())["baseline"][KEY] == 9000


def test_two_replacements_keep_segments_without_double_counting(tmp_path):
    cache, repo = setup(tmp_path)
    confirm(cache, preview_replacement(cache, 0, STAMP.date()))
    at = STAMP.replace(hour=13)
    cache.update_reading(0, _reading(9015, at), at=at)
    repo.update_runtime(0, serial="THIRD", status="online", checked_at=at.isoformat())
    at = STAMP.replace(hour=14)
    cache.update_reading(0, _reading(500, at), at=at)
    preview = preview_replacement(cache, 0, STAMP.date())
    confirm_replacement(cache, 0, STAMP.date(), expected_revision=preview["revision"],
                        actor="PC-A", reason="Second replacement", at=STAMP.replace(hour=15))
    at = STAMP.replace(hour=16)
    state = cache.update_reading(0, _reading(503, at), at=at)
    assert state["delta"][KEY] == 38  # 20 old + 15 used + 3 third
    assert [item["device_identity"]["serial"] for item in state["device_segments"]] == ["OLD", "USED"]
    assert len(state["slot_replacements"]) == 2


def test_unconfirmed_replacement_survives_finalization_as_evidence(tmp_path):
    cache, _ = setup(tmp_path)
    cache.finalize(0, STAMP.date())
    with _open(commit=False) as conn:
        row = conn.execute("SELECT delta_json,source_json FROM daily_meter_records").fetchone()
    assert json.loads(row[0])[KEY] == 20
    source = json.loads(row[1])
    assert source["device_identity"]["serial"] == "OLD"
    assert source["replacement_candidate"]["device_identity"]["serial"] == "USED"
    assert source["replacement_candidate"]["baseline"][KEY] == 9000
