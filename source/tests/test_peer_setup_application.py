from datetime import UTC, datetime
from dataclasses import replace
import sqlite3

import pytest

import database
from services.peer_setup_application import PeerSetupApplication
from services.peer_settings_history import SettingsHistory
from services.shared_settings import SharedSettingsService
from services.shared_settings_document import from_connection
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore
from test_peer_history_session import peers, session
from test_shared_slot_review import initial
from test_slot_epoch_store import read
from test_slot_meter_continuity import total
from test_subject_history import _reading


def allowed(member, revision, payload):
    return member == "A" and payload["organization"]["company_name"] == "Synthetic company"


def epoch_allowed(member, epoch):
    return member == "A" and epoch["document"]["baseline_event"]["payload"]["slot"] == 0


def application(**kwargs):
    return PeerSetupApplication(authorize=kwargs.get("authorize", allowed),
        authorize_epoch=kwargs.get("authorize_epoch", epoch_allowed))


def replacement_source():
    service, _, _ = initial()
    read("USED", 50000, 18)
    review = service.preview(0, actor="PC-A", reason="Reviewed replacement")
    revision = service.confirm(review)
    at = datetime(2026, 9, 19, 10, tzinfo=UTC)
    WebObservationStore().record(0, _reading(50100, collected_at=at), at=at, serial="USED",
        printer_name="Fixture", epoch_id=review["review"]["epoch"]["id"])
    return revision, SettingsHistory().export()


def received(peers):
    paths, nodes = peers
    revision, packet = replacement_source()
    transfer, _ = session(paths, nodes)
    assert transfer.run().status == "complete"
    database.set_db_path(paths["B"])
    database.set_cfg("installation_id", "LOCAL-B")
    database.set_cfg("v52_registration_mode", "offline")
    SettingsHistory().receive(packet)
    return revision, packet


def db_state():
    with database._open(commit=False) as conn:
        names = ("settings", "devices", "slot_meter_heads", "price_history", "peer_settings_state",
                 "peer_settings_events", "config_log", "billing_ledger")
        return {name: conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall() for name in names}


def test_complete_setup_and_epoch_adopt_together_without_copying_local_identity(peers):
    revision, packet = received(peers)
    service = application()
    old = db_state()
    preview = service.preview("A", revision, reason="Accept verified company setup")
    assert db_state() == old
    assert service.commit(preview) == revision
    with database._open(commit=False) as conn:
        assert from_connection(conn) == packet["revisions"][revision]["payload"]
    assert database.get_cfg("installation_id") == "LOCAL-B"
    assert database.get_cfg("v52_registration_mode") == "offline"
    assert total(SlotEpochStore().current(0)).slot_total == 2100
    settings = SharedSettingsService()
    settings.commit(settings.preview({"billing_day": 10}, reason="newer local edit"))
    assert service.commit(preview) == revision  # Retry cannot undo a subsequent edit.
    assert database.get_cfg("billing_day") == "10"


@pytest.mark.parametrize("table", ["peer_settings_events", "config_log", "slot_meter_heads"])
def test_storage_failure_rolls_back_printers_prices_heads_and_receipt(peers, table):
    revision, _ = received(peers)
    service = application()
    preview = service.preview("A", revision, reason="fixture")
    with database._open() as conn:
        conn.execute(f"CREATE TRIGGER fail_apply BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = db_state()
    with pytest.raises(sqlite3.Error, match="injected"):
        service.commit(preview)
    assert db_state() == before


def test_missing_epoch_or_changed_local_settings_cannot_partially_apply(peers):
    paths, _ = peers
    revision, packet = replacement_source()
    database.set_db_path(paths["B"])
    SettingsHistory().receive(packet)
    service = application()
    before = db_state()
    with pytest.raises(ValueError, match="Unknown reviewed"):
        service.preview("A", revision, reason="fixture")
    assert db_state() == before
    # Receive the dependencies, then prove stale local configuration is fenced.
    transfer, _ = session(*peers)
    transfer.run()
    preview = service.preview("A", revision, reason="fixture")
    database.set_cfg("billing_day", "7")
    before = db_state()
    with pytest.raises(ValueError, match="changed after review"):
        service.commit(preview)
    assert db_state() == before


def test_revocation_inside_epoch_adoption_rolls_back_the_entire_configuration(peers):
    revision, _ = received(peers)
    valid = [True]
    def authorize(member, revision, payload):
        return valid[0] and allowed(member, revision, payload)
    def revoke(member, epoch):
        valid[0] = False
        return epoch_allowed(member, epoch)
    service = application(authorize=authorize, authorize_epoch=revoke)
    preview = service.preview("A", revision, reason="fixture")
    before = db_state()
    with pytest.raises(PermissionError):
        service.commit(preview)
    assert db_state() == before


def test_concurrent_settings_require_review_and_form_a_causal_merge(peers):
    paths, _ = peers
    revision, _ = received(peers)
    service = application()
    service.commit(service.preview("A", revision, reason="initial"))
    settings = SharedSettingsService()
    local = settings.commit(settings.preview({"billing_day": 10}, reason="local choice"))
    database.set_db_path(paths["A"])
    remote = settings.commit(settings.preview({"billing_day": 20}, reason="remote choice"))
    packet = SettingsHistory().export()
    database.set_db_path(paths["B"])
    SettingsHistory().receive(packet)
    with pytest.raises(ValueError, match="Concurrent"):
        service.preview("A", remote, reason="must review")
    merged = service.commit(service.preview("A", remote, reason="Choose incoming configuration", resolve_conflict=True))
    with database._open(commit=False) as conn:
        assert set(SettingsHistory._document(conn, merged)["parents"]) == {local, remote}
    assert database.get_cfg("billing_day") == "20"
    assert total(SlotEpochStore().current(0)).slot_total == 2100
    with pytest.raises(ValueError, match="older"):
        service.preview("A", revision, reason="do not regress", resolve_conflict=True)


def test_replacement_detaches_old_credentials_and_success_without_changing_vault(peers):
    revision, _ = received(peers)
    from services.device_config import DeviceConfig, DeviceConfigRepository
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Prior", "192.0.2.11", serial="OLD",
        username="old-admin", credential_ref="local-secret-reference", last_total=99999,
        last_success_at="2026-09-18T10:00:00+00:00", connection_status="online")])
    service = application()
    service.commit(service.preview("A", revision, reason="replace reviewed printer"))
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT credential_ref,last_total,last_success_at,connection_status FROM devices WHERE slot=0").fetchone() == ("", None, None, "pending")
    assert database.get_cfg("installation_id") == "LOCAL-B"


def test_all_three_slots_fail_or_apply_together_and_keep_one_company_set(peers):
    paths, _ = peers
    from services.device_config import DeviceConfig, DeviceConfigRepository
    from services.shared_slot_review import SharedSlotReviewService
    from services.slot_epoch_exchange import SlotEpochExchange
    database.set_cfg("company_name", "Synthetic company")
    database.set_cfg("client_first_started_at", "2026-09-01")
    devices = [DeviceConfig(slot, f"Printer {slot + 1}", f"192.0.2.{10 + slot}", serial=f"SERIAL-{slot}") for slot in range(3)]
    DeviceConfigRepository().replace_all(devices)
    at = datetime(2026, 9, 18, 10, tzinfo=UTC)
    reviews = SharedSlotReviewService()
    for device in devices:
        reading = replace(_reading(1000 * (device.slot + 1), collected_at=at), host=device.host)
        WebObservationStore().record(device.slot, reading, serial=device.serial, printer_name=device.name, at=at)
        revision = reviews.confirm(reviews.preview(device.slot, actor="PC-A", reason="Initial physical baseline"))
    packet = SettingsHistory().export()
    scope = lambda member, epoch: member in {"A", "B"} and epoch["document"]["baseline_event"]["payload"]["slot"] in range(3)
    source = SlotEpochExchange(authorize=scope)
    bundles = [source.export("B", SlotEpochStore().head(slot)["id"]) for slot in range(3)]
    database.set_db_path(paths["B"])
    database.set_cfg("installation_id", "LOCAL-B")
    for bundle in bundles:
        SlotEpochExchange(authorize=scope).receive("A", bundle)
    SettingsHistory().receive(packet)
    reject_last = lambda member, epoch: scope(member, epoch) and epoch["document"]["baseline_event"]["payload"]["slot"] != 2
    service = application(authorize_epoch=reject_last)
    preview = service.preview("A", revision, reason="Use the company's three Slots")
    before = db_state()
    with pytest.raises(PermissionError):
        service.commit(preview)
    assert db_state() == before
    assert application(authorize_epoch=scope).commit(preview) == revision
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM devices WHERE enabled=1").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 3
        assert from_connection(conn) == packet["revisions"][revision]["payload"]
    assert [total(SlotEpochStore().current(slot)).slot_total for slot in range(3)] == [1000, 2000, 3000]
    assert database.get_cfg("installation_id") == "LOCAL-B"


def test_price_only_update_preserves_same_printer_local_credential_and_runtime(peers):
    paths, _ = peers
    revision, _ = received(peers)
    service = application()
    service.commit(service.preview("A", revision, reason="initial"))
    with database._open() as conn:
        conn.execute("UPDATE devices SET credential_ref='local-only',last_total=50100,connection_status='online' WHERE slot=0")
    database.set_db_path(paths["A"])
    changes = SharedSettingsService()
    updated = changes.commit(changes.preview({"waste_paper_pct": 5}, reason="company setting"))
    packet = SettingsHistory().export()
    database.set_db_path(paths["B"])
    SettingsHistory().receive(packet)
    assert service.commit(service.preview("A", updated, reason="apply verified edit")) == updated
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT credential_ref,last_total,connection_status FROM devices WHERE slot=0").fetchone() == ("local-only", 50100, "online")


def test_unverified_company_member_cannot_prepare_setup(peers):
    revision, _ = received(peers)
    before = db_state()
    with pytest.raises(PermissionError):
        application().preview("Unverified LAN reply", revision, reason="fixture")
    assert db_state() == before


def test_database_switch_during_apply_rolls_back_original_target(peers):
    paths, _ = peers
    revision, _ = received(peers)
    def switching(member, epoch):
        database.set_db_path(paths["A"])
        return epoch_allowed(member, epoch)
    service = application(authorize_epoch=switching)
    preview = service.preview("A", revision, reason="fixture")
    before = db_state()
    with pytest.raises(ValueError, match="Saved setup differs"):
        service.commit(preview)
    database.set_db_path(paths["B"])
    assert db_state() == before


def test_complete_preview_uses_existing_confirmation_without_saving_on_cancel(peers):
    from PyQt6.QtWidgets import QApplication
    from ui.shared_settings_confirmation import SharedSettingsConfirmation
    app = QApplication.instance() or QApplication([])
    revision, _ = received(peers)
    service = application()
    before = db_state()
    preview = service.preview("A", revision, reason="fixture")
    assert {"organization", "devices", "slot_epochs"} <= preview.changes.keys()
    dialog = SharedSettingsConfirmation(preview)
    dialog.show()
    app.processEvents()
    labels = [dialog.table.item(index, 0).text() for index in range(dialog.table.rowCount())]
    assert "ฐานมิเตอร์ของ Slot" in labels
    dialog.reject()
    assert db_state() == before
