"""Atomic Wizard configuration, price history and shared audit revision."""
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
import json
from pathlib import Path

from services.peer_change_events import notify_local_change
from database import _open, get_db_path
from services.peer_settings_history import SettingsHistory, _json
from services.pricing import PriceList, PricingRepository
from services.secondary_setup import _setup_snapshot
from services.shared_settings_document import PRICE_KEYS, from_connection, validate
from services.setup_meter_baselines import BaselinePlan, SetupMeterBaselines

# These local values may be saved by setup but must never enter peer history.
LOCAL_KEYS = {"snmp_interval_minutes", "db_path", "installation_id", "v52_registration_mode",
              "desktop_role", "primary_peer_url", "primary_peer_certificate_sha256",
              "primary_installation_id", "peer_enrollment_pending"}
SHARED_KEYS = {"company_name", "client_first_started_at", "pricing_mode", "billing_day",
               "waste_paper_pct", "work_start", "work_end", "sync_schedule_windows"}


def _state(conn):
    return {
        "settings": list(conn.execute("SELECT key,value FROM settings WHERE key IN (" +
            ",".join("?" for _ in LOCAL_KEYS | SHARED_KEYS) + ") ORDER BY key", sorted(LOCAL_KEYS | SHARED_KEYS))),
        "devices": list(conn.execute("SELECT slot,name,host,username,credential_ref,tls_mode,"
            "tls_fingerprint,enabled,model,serial FROM devices ORDER BY slot")),
        "prices": list(conn.execute("SELECT device_slot,effective_date,a3_color,a3_bw,a4_color,a4_bw "
                                    "FROM price_history ORDER BY device_slot,effective_date")),
        "head": SettingsHistory._state(conn, "head"),
        "slot_epochs": list(conn.execute("SELECT device_slot,epoch_id FROM slot_meter_heads ORDER BY device_slot")),
    }


@dataclass(frozen=True)
class SetupPreview:
    database_path: str
    expected_json: str
    before_json: str
    after_json: str
    settings_json: str
    prices_json: str
    devices: tuple
    inventory_json: str | None
    baseline_plan: BaselinePlan | None = None

    @property
    def changes(self):
        old, new = json.loads(self.before_json), json.loads(self.after_json)
        changes = {}
        for key in ("organization", "devices", "price_history"):
            previous = old.get(key) if old else None
            if previous != new[key]:
                if key == "price_history":
                    before = {(r["slot"], r["effective_date"]): r for r in previous or []}
                    after = {(r["slot"], r["effective_date"]): r for r in new[key]}
                    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
                    changes[key] = ([before[k] for k in changed if k in before],
                                    [after[k] for k in changed if k in after])
                else:
                    changes[key] = (previous, new[key])
        for key, value in new["settings"].items():
            previous = old["settings"].get(key) if old else None
            if previous != value:
                changes[key] = (previous, value)
        return changes


class SetupSettingsService:
    def __init__(self, repository):
        self.repository = repository

    def preview(self, devices, settings, prices, *, registration_devices=None, baseline_plan=None):
        if not set(settings) <= LOCAL_KEYS | SHARED_KEYS or any(not isinstance(v, str) for v in settings.values()):
            raise ValueError("Unsupported setup settings")
        devices = tuple(devices)
        baselines = SetupMeterBaselines()
        if baseline_plan is not None:
            baselines.validate_devices(baseline_plan, devices)
        # Read the OS vault migration before taking the snapshot, never during review.
        self.repository._ensure_migrated()
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            expected = _state(conn)
            if baseline_plan is not None:
                baselines.check_current(conn, baseline_plan)
            config = dict(expected["settings"])
            before = from_connection(conn) if config.get("company_name") and any(row[7] for row in expected["devices"]) else None
            # A legacy successful read may still exist only in runtime-cache.
            # Editing its label/price must not erase the SQL marker and make the
            # next wizard mistake that established machine for a new slot.
            previous = {row[0]: row[1:] for row in conn.execute(
                "SELECT slot,host,serial,last_success_at FROM devices")}
            baselined = {entry.slot for entry in baseline_plan.entries} if baseline_plan else set()
            retained = []
            for device in devices:
                old = previous.get(device.slot)
                same_identity = old and ((old[1] == device.serial) if old[1] and device.serial else old[0] == device.host)
                if same_identity and device.slot not in baselined and old[2] and not device.last_success_at:
                    device = replace(device, last_success_at=old[2])
                retained.append(device)
            devices = tuple(retained)
        config.update(settings)
        class EmptyPrices:
            def get_prices(self, *_args):
                return PriceList()
        snapshot = _setup_snapshot([device for device in devices if device.enabled], EmptyPrices(), config.get)
        snapshot["organization"].pop("primary_installation_id")
        snapshot["organization"]["first_started_at"] = config.get("client_first_started_at", "")
        for device in snapshot["devices"]:
            device.pop("prices")
        columns = ("slot", "effective_date", *PRICE_KEYS)
        history = {(row[0], row[1]): dict(zip(columns, row)) for row in expected["prices"]}
        updates = []
        for slot, effective, value in prices:
            row = {"slot": slot, "effective_date": effective.isoformat(),
                   **{key: getattr(value, key) for key in PRICE_KEYS}}
            if (slot, row["effective_date"]) in {(r["slot"], r["effective_date"]) for r in updates}:
                raise ValueError("Duplicate price update")
            updates.append(row)
            history[(slot, row["effective_date"])] = row
        after = {"format_version": 2, "organization": snapshot["organization"],
                 "settings": snapshot["settings"], "devices": snapshot["devices"],
                 "price_history": [history[key] for key in sorted(history)]}
        epochs = baseline_plan.slot_epochs if baseline_plan is not None else expected["slot_epochs"]
        if epochs:
            after.update(format_version=3, slot_epochs=[{"slot": slot, "epoch_id": epoch}
                for slot, epoch in epochs])
        validate(after)
        for row in after["price_history"]:
            for key in PRICE_KEYS:
                row[key] = float(row[key])
        return SetupPreview(str(Path(get_db_path()).resolve()), _json(expected), _json(before),
                            _json(after), _json(settings), _json(updates), devices,
                            _json(list(registration_devices)) if registration_devices is not None else None,
                            baseline_plan)

    @notify_local_change
    def commit(self, preview):
        history = SettingsHistory()
        baselines = SetupMeterBaselines()
        result = []
        def before_write(conn):
            if str(Path(get_db_path()).resolve()) != preview.database_path or _json(_state(conn)) != preview.expected_json:
                raise ValueError("การตั้งค่าเปลี่ยนหลังเปิดหน้าต่างยืนยัน กรุณาตรวจและบันทึกใหม่")
            if preview.baseline_plan is not None:
                baselines.validate_devices(preview.baseline_plan, preview.devices)
                baselines.check_current(conn, preview.baseline_plan)
        def after_write(conn):
            before, after = json.loads(preview.before_json), json.loads(preview.after_json)
            settings = json.loads(preview.settings_json)
            for key, value in settings.items():
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            for row in json.loads(preview.prices_json):
                PricingRepository.write_prices(conn, row["slot"], date.fromisoformat(row["effective_date"]),
                                               PriceList(**{key: row[key] for key in PRICE_KEYS}))
            if preview.baseline_plan is not None:
                baselines.apply(conn, preview.baseline_plan)
            if from_connection(conn) != after:
                raise ValueError("Saved configuration differs from reviewed settings")
            head = history._state(conn, "head")
            if before and (not head or history._document(conn, head)["payload"] != before):
                head = history._append(conn, before, [head] if head else [], "local_settings_baseline")
            if not head or history._document(conn, head)["payload"] != after:
                head = history._append(conn, after, [head] if head else [], "setup_settings_saved")
                conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                             ("shared_setup", preview.before_json, preview.after_json, datetime.now(UTC).isoformat()))
            result.append(head)
        self.repository.replace_all(list(preview.devices),
            registration_devices=json.loads(preview.inventory_json) if preview.inventory_json is not None else None,
            before_write=before_write, after_write=after_write)
        return result[0]
