from datetime import date
import sqlite3

import pytest

import database
from services.peer_settings_history import SettingsHistory
from services.pricing import PricingRepository, PriceList
from services.shared_settings import SharedSettingsService
from test_shared_settings import configured, state


def save_price(day, value):
    PricingRepository().set_prices(0, date.fromisoformat(day), PriceList(a4_bw=value))
    return SettingsHistory().observe_current()


def prices():
    with database._open(commit=False) as conn:
        return conn.execute("SELECT device_slot,effective_date,a4_bw FROM price_history ORDER BY device_slot,effective_date").fetchall()


def incoming_price_fixture(tmp_path):
    original = database.get_db_path()
    configured()
    root = save_price("2026-01-01", 1)
    packet = SettingsHistory().export()
    other = tmp_path / "B.sqlite3"
    configured(other)
    PricingRepository().set_prices(0, date(2026, 1, 1), PriceList(a4_bw=1))
    SettingsHistory().receive(packet)
    with database._open() as conn:
        conn.execute("INSERT INTO peer_settings_state VALUES('head',?)", (root,))
    remote = save_price("2026-10-01", 2)
    packet = SettingsHistory().export()
    database.set_db_path(original)
    SettingsHistory().receive(packet)
    return remote, original


def test_received_price_schedule_applies_atomically_without_touching_installation(tmp_path):
    remote, original = incoming_price_fixture(tmp_path)
    identity = database.get_cfg("installation_id")
    service = SharedSettingsService()
    before = prices(), state()
    preview = service.preview_choice(remote, chosen_head=remote, reason="reviewed_peer_choice")
    assert (prices(), state()) == before
    assert preview.changes["price_history"][0] == []
    assert preview.changes["price_history"][1][0]["effective_date"] == "2026-10-01"
    assert service.commit(preview) == remote
    assert PricingRepository().get_prices(0, date(2026, 9, 30)).a4_bw == 1
    assert PricingRepository().get_prices(0, date(2026, 10, 1)).a4_bw == 2
    assert database.get_cfg("installation_id") == identity
    before = prices(), state()
    service.commit(service.preview_choice(remote, chosen_head=remote, reason="duplicate delivery"))
    assert (prices(), state()) == before


def test_failed_price_insert_rolls_back_deleted_prices_and_head(tmp_path):
    remote, _ = incoming_price_fixture(tmp_path)
    service = SharedSettingsService()
    preview = service.preview_choice(remote, chosen_head=remote, reason="test")
    with database._open() as conn:
        conn.execute("""CREATE TRIGGER fail_price BEFORE INSERT ON price_history
            WHEN NEW.effective_date='2026-10-01' BEGIN SELECT RAISE(ABORT,'injected price failure'); END""")
    before = prices(), state()
    with pytest.raises(sqlite3.IntegrityError):
        service.commit(preview)
    assert (prices(), state()) == before


def test_price_undo_preserves_unrelated_later_date_and_settings():
    service = configured()
    save_price("2026-01-01", 1)
    changed = save_price("2026-01-01", 2)
    save_price("2026-11-01", 3)
    service.commit(service.preview({"billing_day": 15}, reason="unrelated billing change"))
    preview = service.preview_undo(changed, keys=["price_history"], reason="restore one price")
    assert len(preview.changes["price_history"][0]) == 1
    revision = service.commit(preview)
    assert prices() == [(0, "2026-01-01", 1), (0, "2026-11-01", 3)]
    assert database.get_cfg("billing_day") == "15"
    assert revision != changed
    assert changed in SettingsHistory().export()["revisions"]


def test_price_undo_refuses_same_price_edited_again():
    service = configured()
    save_price("2026-01-01", 1)
    changed = save_price("2026-01-01", 2)
    save_price("2026-01-01", 3)
    before = prices(), state()
    with pytest.raises(ValueError, match="changed again"):
        service.preview_undo(changed, keys=["price_history"], reason="stale")
    assert (prices(), state()) == before


def test_received_price_conflict_requires_choice_and_keeps_both_parents(tmp_path):
    remote, _ = incoming_price_fixture(tmp_path)
    local = save_price("2026-10-01", 4)
    service = SharedSettingsService()
    merged = service.commit(service.preview_choice(remote, chosen_head=remote, reason="choose incoming price"))
    document = SettingsHistory().export()["revisions"][merged]
    assert set(document["parents"]) == {remote, local}
    assert PricingRepository().get_prices(0, date(2026, 10, 1)).a4_bw == 2


def test_stale_confirmation_cannot_replace_a_newer_price(tmp_path):
    remote, _ = incoming_price_fixture(tmp_path)
    service = SharedSettingsService()
    preview = service.preview_choice(remote, chosen_head=remote, reason="choose incoming")
    save_price("2026-11-01", 5)
    before = prices(), state()
    with pytest.raises(ValueError, match="เปลี่ยน"):
        service.commit(preview)
    assert (prices(), state()) == before


def test_pricing_mode_and_working_hours_use_reviewed_atomic_history():
    service = configured()
    changed = service.commit(service.preview({"pricing_mode": "per_device", "work_start": "07:30", "work_end": "18:45"}, reason="reviewed schedule"))
    assert database.get_cfg("work_start") == "07:30"
    service.commit(service.preview_undo(changed, keys=["work_start"], reason="restore start only"))
    assert database.get_cfg("work_start") == "08:00"
    assert database.get_cfg("work_end") == "18:45"
    assert database.get_cfg("pricing_mode") == "per_device"


@pytest.mark.parametrize("change", [{"work_start": "25:00"}, {"work_end": "01:99"}, {"pricing_mode": "free"}])
def test_invalid_shared_working_hours_or_pricing_mode_cannot_save(change):
    service = configured()
    before = state()
    with pytest.raises(ValueError):
        service.preview(change, reason="invalid fixture")
    assert state() == before


def test_history_price_undo_notifies_runtime_and_refreshes_parent(monkeypatch):
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import QWidget
    from ui import shared_settings_history as ui
    from test_shared_settings_history_ui import select_revision
    configured()
    save_price("2026-01-01", 1)
    changed = save_price("2026-01-01", 2)
    calls = []
    class Parent(QWidget):
        changed = pyqtSignal()
        def refresh_from_config(self):
            calls.append("refresh")
    parent = Parent()
    parent.changed.connect(lambda: calls.append("runtime"))
    monkeypatch.setattr(ui, "confirm_shared_settings", lambda *_: True)
    def review(dialog):
        select_revision(dialog, changed)
        assert dialog.undo.isEnabled()
        dialog._undo()
        return 0
    monkeypatch.setattr(ui.SharedSettingsHistoryDialog, "exec", review)
    ui.show_shared_settings_history(parent)
    assert calls == ["refresh", "runtime"]
    assert prices() == [(0, "2026-01-01", 1)]
