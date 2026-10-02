from collections import OrderedDict
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

import web_api
from services.report_models import build_user_rows
from services.report_user_counters import UserCounter
from services.subject_history import SubjectPeriodUsage


QUERY = "?period_start=2026-07-01&period_end=2026-07-31"


def subject(*, slot=0, serial="A", subject_id="00123", name="สมชาย", day=1, usage=5):
    observed = date(2026, 7, day)
    return SubjectPeriodUsage(
        device_slot=slot, period_start=observed, period_end=observed,
        subject_type="user", subject_id=subject_id, subject_name=name,
        latest_total=100 + usage, period_usage=usage, reset_count=0,
        missing_baseline_days=0, incomplete_days=0, sample_count=2,
        latest_at=f"{observed.isoformat()}T09:00:00+07:00", warnings=(),
        device_identity=f"serial:{serial}" if serial else "",
        device_name_snapshot=f"Printer {slot + 1}", device_serial_snapshot=serial,
        name_observed_on=observed,
    )


def counter(*, slot=0, serial="A", subject_id="00123", name="สมชาย", day=1, usage=5,
            subject_type="user"):
    return UserCounter(slot, date(2026, 7, day), "counter.print.total", "Print", subject_type,
                       subject_id, name, usage, serial, False)


@pytest.fixture(autouse=True)
def isolated_user_pages(monkeypatch):
    monkeypatch.setattr(web_api, "_user_pages", OrderedDict())


def client_for(monkeypatch, subjects, counters=()):
    calls = []
    counter_calls = []

    def load(slots, **kwargs):
        calls.append((slots, kwargs))
        return subjects

    def load_counters(slots, **kwargs):
        counter_calls.append((slots, kwargs))
        return counters

    monkeypatch.setattr(web_api, "report_slots", lambda: sorted({item.device_slot for item in subjects}))
    monkeypatch.setattr(web_api, "load_subject_history", load)
    monkeypatch.setattr(web_api, "load_user_counter_history", load_counters)
    monkeypatch.setattr(web_api, "load_usage_history", lambda *_a, **_kw: pytest.fail("Users must not load device usage"))
    from services import raw_counter_history
    monkeypatch.setattr(raw_counter_history, "load_raw_counter_history",
                        lambda *_a, **_kw: pytest.fail("Users grouping must not load full Raw history"))
    return TestClient(web_api.app), calls, counter_calls


def get_users(client, suffix=""):
    response = client.get(f"/api/v1/reports/users{QUERY}{suffix}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("printers", [2, 3])
def test_same_thai_name_across_printer_local_ids_has_one_report_key(monkeypatch, printers):
    subjects = tuple(subject(slot=slot, serial=f"S-{slot}", subject_id=str(100 + slot), usage=slot + 3)
                     for slot in range(printers))
    client, calls, _ = client_for(monkeypatch, subjects)
    body = get_users(client)
    assert body["total"] == printers
    assert {item["report_user_key"] for item in body["items"]} == {"user:name:สมชาย"}
    assert len(calls) == 1
    for original, item in zip(subjects, body["items"]):
        assert item["subject_name"] == "สมชาย"
        assert item["subject_id"] == original.subject_id
        assert item["device_slot"] == original.device_slot
        assert item["device_identity"] == item["report_device_identity"] == original.device_identity
        assert item["device_serial_snapshot"] == original.device_serial_snapshot
        assert item["device_name_snapshot"] == original.device_name_snapshot
        assert item["usage"] == original.period_usage
        assert item["latest_total"] == original.latest_total
        assert item["warnings"] == [] and not item["needs_review"]


def test_numeric_placeholders_do_not_group_slots_replacements_or_distinct_ids(monkeypatch):
    subjects = (subject(name="123"), subject(slot=1, serial="B", name="00123"),
                subject(serial="REPLACEMENT", name=""), subject(subject_id="123", name="00123"))
    client, _, _ = client_for(monkeypatch, subjects)
    items = get_users(client)["items"]
    assert len({item["report_user_key"] for item in items}) == 4
    assert [item["subject_name"] for item in items] == ["00123", "00123", "00123", "123"]
    assert [item["report_device_identity"] for item in items] == [
        "serial:A", "serial:B", "serial:REPLACEMENT", "serial:A"]


@pytest.mark.parametrize("latest_name,expected", [("123", "สมชาย"), ("", "สมชาย"), ("สมศักดิ์", "สมศักดิ์")])
def test_known_real_name_survives_placeholder_and_latest_real_rename_wins(monkeypatch, latest_name, expected):
    subjects = (replace(subject(day=2, name=latest_name, usage=7), warnings=("Check source",)),
                subject())  # Deliberately newest first.
    client, _, _ = client_for(monkeypatch, subjects)
    items = get_users(client)["items"]
    assert {item["subject_name"] for item in items} == {expected}
    assert {item["report_user_key"] for item in items} == {f"user:name:{expected}"}
    assert sum(item["usage"] for item in items) == 12
    assert items[0]["latest_total"] == 107
    assert items[0]["warnings"] == ["Check source"] and items[0]["needs_review"]
    assert subjects[0].subject_name == latest_name


def test_real_name_observation_day_is_independent_of_latest_counter_day(monkeypatch):
    subjects = (replace(subject(day=4), name_observed_on=date(2026, 7, 1)),
                subject(day=2, name="สมศักดิ์"))
    client, _, _ = client_for(monkeypatch, subjects)
    assert {item["subject_name"] for item in get_users(client)["items"]} == {"สมศักดิ์"}


def test_same_name_account_and_user_keep_distinct_report_keys(monkeypatch):
    subjects = (subject(), replace(subject(slot=1, serial="B"), subject_type="account"))
    client, _, _ = client_for(monkeypatch, subjects)
    items = get_users(client)["items"]
    assert {item["report_user_key"] for item in items} == {"user:name:สมชาย", "account:name:สมชาย"}


def test_legacy_slot_alias_preserves_original_identity_without_crossing_replacements(monkeypatch):
    legacy = subject(serial="", name="123")
    known = subject(day=2)
    client, _, _ = client_for(monkeypatch, (legacy, known))
    items = get_users(client)["items"]
    assert {item["report_device_identity"] for item in items} == {"serial:A"}
    assert {item["report_user_key"] for item in items} == {"user:name:สมชาย"}
    assert items[0]["device_identity"] == items[0]["device_serial_snapshot"] == ""

    replacement = subject(serial="B", name="วิภา", day=3)
    client, _, _ = client_for(monkeypatch, (legacy, known, replacement))
    items = get_users(client)["items"]
    assert [item["report_device_identity"] for item in items] == ["slot:0", "serial:A", "serial:B"]
    assert [item["subject_name"] for item in items] == ["00123", "สมชาย", "วิภา"]
    assert len({item["report_user_key"] for item in items}) == 3


def test_paging_uses_resolved_full_selection_without_reloading_or_reresolving(monkeypatch):
    subjects = (subject(name="123"), subject(slot=1, serial="B", subject_id="456", name="สมชาย"),
                subject(day=2, name="สมชาย"))
    client, calls, counter_calls = client_for(monkeypatch, subjects)
    first = get_users(client, "&limit=1")
    assert first["items"][0]["subject_name"] == "สมชาย"  # Name lies on a later page.
    token = first["snapshot_token"]
    assert first["next_offset"] == 1
    monkeypatch.setattr(web_api, "build_subject_name_index", lambda *_a, **_kw: pytest.fail("Cached page must retain resolved names"))
    monkeypatch.setattr(web_api, "load_subject_history", lambda *_a, **_kw: pytest.fail("Cached page must not reload history"))
    monkeypatch.setattr(web_api, "load_user_counter_history", lambda *_a, **_kw: pytest.fail("Cached page must not reload counters"))
    pages = [first] + [get_users(client, f"&limit=1&offset={offset}&snapshot_token={token}")
                       for offset in (1, 2)]
    assert len(calls) == 1
    assert counter_calls == [([0, 1], {"period_start": date(2026, 7, 1),
                                      "period_end": date(2026, 7, 31), "incremental": True})]
    assert {page["snapshot_token"] for page in pages} == {token}
    assert [page["next_offset"] for page in pages] == [1, 2, None]
    assert {item["report_user_key"] for page in pages for item in page["items"]} == {"user:name:สมชาย"}
    assert sum(item["usage"] for page in pages for item in page["items"]) == 15
    repeated = get_users(client, f"&limit=1&snapshot_token={token}")
    assert repeated["items"] == first["items"]


def test_raw_only_real_name_matches_desktop_group_across_local_ids(monkeypatch):
    subjects = (subject(day=4, name="123"),
                subject(slot=1, serial="B", subject_id="456", usage=7))
    counters = (counter(), counter(slot=1, serial="B", subject_id="456", usage=7))
    client, _, counter_calls = client_for(monkeypatch, subjects, counters)
    first = get_users(client, "&limit=1")
    second = get_users(client, f"&limit=1&offset=1&snapshot_token={first['snapshot_token']}")
    items = first["items"] + second["items"]
    desktop = build_user_rows(subjects, counters)
    assert len(desktop) == 1 and desktop[0]["usage"] == 12
    assert {item["subject_name"] for item in items} == {desktop[0]["name"]}
    assert {item["report_user_key"] for item in items} == {desktop[0]["key"]}
    assert sum(item["usage"] for item in items) == desktop[0]["usage"]
    assert len(counter_calls) == 1
    assert subjects[0].subject_name == "123"


def test_later_raw_real_rename_survives_newest_numeric_raw(monkeypatch):
    subjects = (replace(subject(day=4), name_observed_on=date(2026, 7, 1)),)
    counters = (counter(day=4, name="123"), counter(day=3, name="สมศักดิ์"))
    client, _, _ = client_for(monkeypatch, subjects, counters)
    item = get_users(client)["items"][0]
    assert item["subject_name"] == "สมศักดิ์"
    assert item["report_user_key"] == build_user_rows(subjects, counters)[0]["key"]
    assert item["usage"] == subjects[0].period_usage


@pytest.mark.parametrize("foreign", [
    {"subject_id": "123"}, {"serial": "REPLACED"}, {"slot": 1}, {"subject_type": "account"},
])
def test_foreign_raw_cannot_supply_name_or_report_identity(monkeypatch, foreign):
    subjects = (subject(name="123"),)
    counters = (counter(name="Foreign name", **foreign),)
    client, _, _ = client_for(monkeypatch, subjects, counters)
    item = get_users(client)["items"][0]
    assert item["subject_name"] == "00123"
    assert item["report_user_key"] == "user:slot:0:device:serial:A:id:00123"
    assert item["report_device_identity"] == "serial:A"


def test_competing_raw_printers_disable_legacy_slot_name_fallback(monkeypatch):
    subjects = (subject(serial="", name="123"),)
    counters = (counter(), counter(serial="B", name="วิภา"))
    client, _, _ = client_for(monkeypatch, subjects, counters)
    item = get_users(client)["items"][0]
    assert item["subject_name"] == "00123"
    assert item["report_device_identity"] == "slot:0"
    assert item["report_user_key"] == build_user_rows(subjects, counters)[0]["key"]


def test_empty_subject_selection_does_not_load_counter_history(monkeypatch):
    client, _, counter_calls = client_for(monkeypatch, ())
    body = get_users(client)
    assert body["items"] == [] and body["total"] == 0
    assert counter_calls == []
