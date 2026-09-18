"""Atomic reviewed application of an authenticated complete peer configuration.

Authorization callbacks must verify the current member/company/revision/Slot
scope from independently trusted material. They must not perform network I/O
inside the transaction. No default production provider is supplied here.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path

from config import DEFAULT_ADMIN_USERNAME
from services.peer_change_events import notify_local_change
from database import _open, config_write_transaction, get_db_path
from services.peer_settings_history import SettingsHistory, _json
from services.peer_settings_outbox import enqueue_revision
from services.pricing import PriceList, PricingRepository
from services.setup_settings import _state
from services.shared_settings_document import from_connection, validate, PRICE_KEYS
from services.slot_epoch_exchange import SlotEpochExchange


@dataclass(frozen=True)
class PeerSetupPreview:
    member: str
    remote_head: str
    expected_json: str
    before_json: str
    after_json: str
    database_path: str
    reason: str
    resolve_conflict: bool

    @property
    def changes(self):
        before, after = json.loads(self.before_json) or {}, json.loads(self.after_json)
        changes = {key: (before.get(key), after.get(key))
                   for key in ("organization", "devices", "slot_epochs", "price_history")
                   if before.get(key) != after.get(key)}
        changes.update({key: (before.get("settings", {}).get(key), value)
                        for key, value in after["settings"].items()
                        if before.get("settings", {}).get(key) != value})
        return changes


class PeerSetupApplication:
    def __init__(self, *, authorize, authorize_epoch):
        if not callable(authorize) or not callable(authorize_epoch):
            raise TypeError("Verified company/settings and epoch authorizers are required")
        self.authorize, self.authorize_epoch = authorize, authorize_epoch

    def _allowed(self, member, revision, payload):
        if (not isinstance(member, str) or not member.strip() or len(member) > 256
                or self.authorize(member, revision, payload) is not True):
            raise PermissionError("Member is not authorized for this complete company configuration")

    @staticmethod
    def _before(conn, state):
        settings = dict(state["settings"])
        return from_connection(conn) if settings.get("company_name") and any(row[7] for row in state["devices"]) else None

    @staticmethod
    def _choice(conn, local, remote, resolve):
        remote_ancestors = SettingsHistory._ancestors(conn, remote)
        if local == remote or not local or local in remote_ancestors:
            return True
        if remote in SettingsHistory._ancestors(conn, local):
            raise ValueError("Incoming settings are older than the applied history")
        if not resolve:
            raise ValueError("Concurrent settings require an explicit reviewed choice")
        return False

    def preview(self, member, remote_head, *, reason, resolve_conflict=False):
        if type(resolve_conflict) is not bool or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
            raise ValueError("A bounded review reason and explicit conflict choice are required")
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            database_path = str(Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve())
            state = _state(conn)
            before = self._before(conn, state)
            after = SettingsHistory._document(conn, remote_head)["payload"]
            validate(after)
            self._allowed(member, remote_head, after)
            self._choice(conn, state["head"], remote_head, resolve_conflict)
            if state["head"] and SettingsHistory._document(conn, state["head"])["payload"] != before:
                raise ValueError("Local settings changed outside the reviewed history")
            self._check_references(conn, state, after)
        return PeerSetupPreview(member, remote_head, _json(state), _json(before), _json(after),
            database_path, reason.strip(), resolve_conflict)

    @staticmethod
    def _check_references(conn, state, payload):
        from services.slot_epoch_store import SlotEpochStore
        prior = dict(state["slot_epochs"])
        incoming = {row["slot"]: row["epoch_id"] for row in payload.get("slot_epochs", [])}
        if not prior.keys() <= incoming.keys():
            raise ValueError("Shared settings cannot discard established Slot baselines")
        devices = {row["slot"]: row for row in payload["devices"]}
        for slot, epoch_id in incoming.items():
            epoch = SlotEpochStore._epoch(conn, epoch_id)
            anchor = epoch["document"]["baseline_event"]["payload"]
            if anchor["slot"] != slot or (slot in devices and anchor["serial"] != devices[slot]["serial"]):
                raise ValueError("Printer and reviewed Slot baseline disagree")
            if slot not in devices and prior.get(slot) != epoch_id:
                raise ValueError("Cannot adopt a new baseline for a disabled Slot")

    @notify_local_change
    def commit(self, preview):
        if (not isinstance(preview, PeerSetupPreview) or type(preview.resolve_conflict) is not bool
                or not isinstance(preview.reason, str) or not 1 <= len(preview.reason.strip()) <= 300
                or preview.database_path != str(Path(get_db_path()).resolve())):
            raise ValueError("Invalid or relocated peer settings review")
        requested = json.loads(preview.after_json)
        validate(requested)
        receipt_key = "peer_setup_review:" + hashlib.sha256(_json(preview.__dict__).encode()).hexdigest()
        history = SettingsHistory()
        exchange = SlotEpochExchange(authorize=self.authorize_epoch, path=preview.database_path)
        with config_write_transaction() as conn:
            if str(Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()) != preview.database_path:
                raise ValueError("Settings database changed after review")
            self._allowed(preview.member, preview.remote_head, requested)
            if SettingsHistory._document(conn, preview.remote_head)["payload"] != requested:
                raise ValueError("Reviewed incoming configuration changed")
            receipt = conn.execute("SELECT new_value FROM config_log WHERE config_key=? ORDER BY id DESC LIMIT 1",
                (receipt_key,)).fetchone()
            if receipt:
                return json.loads(receipt[0])["revision"]
            state = _state(conn)
            before = self._before(conn, state)
            if _json(state) != preview.expected_json or _json(before) != preview.before_json:
                raise ValueError("Settings changed after review; prepare a fresh preview")
            fast_forward = self._choice(conn, state["head"], preview.remote_head, preview.resolve_conflict)
            self._check_references(conn, state, requested)
            stamp = datetime.now(UTC).isoformat()
            slots = [row["slot"] for row in requested["devices"]]
            conn.execute("UPDATE devices SET enabled=0 WHERE slot NOT IN (" + ",".join("?" for _ in slots) + ")", slots)
            for row in requested["devices"]:
                current = conn.execute("SELECT host,serial,tls_mode,tls_fingerprint FROM devices WHERE slot=?", (row["slot"],)).fetchone()
                same = current == (row["host"], row["serial"], row["tls_mode"], row["tls_fingerprint"])
                conn.execute("""INSERT INTO devices(slot,name,host,username,password,credential_ref,tls_mode,tls_fingerprint,
                    enabled,model,serial,connection_status,updated_at) VALUES(?,?,?,?,'','',?,?,1,?,?,'pending',?)
                    ON CONFLICT(slot) DO UPDATE SET name=excluded.name,host=excluded.host,tls_mode=excluded.tls_mode,
                    tls_fingerprint=excluded.tls_fingerprint,enabled=1,model=excluded.model,serial=excluded.serial,
                    updated_at=excluded.updated_at""", (row["slot"], row["name"], row["host"], DEFAULT_ADMIN_USERNAME,
                    row["tls_mode"], row["tls_fingerprint"], row["model"], row["serial"], stamp))
                if not same:
                    # Do not send another physical printer's local credentials
                    # to a new address or carry its success/total into this one.
                    # The OS vault itself is unchanged and remains recoverable.
                    conn.execute("""UPDATE devices SET username=?,password='',credential_ref='',connection_status='pending',
                        last_checked_at=NULL,last_success_at=NULL,last_error='',last_total=NULL WHERE slot=?""",
                        (DEFAULT_ADMIN_USERNAME, row["slot"]))
            settings = {**requested["settings"], "company_name": requested["organization"]["company_name"],
                        "client_first_started_at": requested["organization"]["first_started_at"]}
            for key, value in settings.items():
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))
            conn.execute("DELETE FROM price_history")
            for row in requested["price_history"]:
                PricingRepository.write_prices(conn, row["slot"], date.fromisoformat(row["effective_date"]),
                    PriceList(**{key: row[key] for key in PRICE_KEYS}))
            old_heads = dict(state["slot_epochs"])
            for reference in requested.get("slot_epochs", []):
                exchange.adopt_in_transaction(conn, preview.member, reference["epoch_id"],
                    expected_head=old_heads.get(reference["slot"]))
            self._allowed(preview.member, preview.remote_head, requested)
            if (str(Path(get_db_path()).resolve()) != preview.database_path or from_connection(conn) != requested):
                raise ValueError("Saved setup differs from the reviewed shared configuration")
            if fast_forward:
                revision = preview.remote_head
                conn.execute("INSERT INTO peer_settings_state VALUES('head',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (revision,))
                enqueue_revision(conn, revision, stamp)
            else:
                revision = history._append(conn, requested, [state["head"], preview.remote_head], preview.reason)
            conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                (receipt_key, preview.before_json, _json({"revision": revision, "remote_head": preview.remote_head,
                    "member": preview.member, "reason": preview.reason}), stamp))
            return revision
