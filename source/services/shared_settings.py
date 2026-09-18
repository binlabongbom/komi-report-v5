"""Reviewed, atomic changes to the shared billing and collection settings.

Printer replacement and registration need their own workflows. Dated price
history can be explicitly reviewed alongside billing and collection settings.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, date
import json
import math
import re
from pathlib import Path

from database import _open, config_write_transaction, get_db_path
from services.peer_settings_history import SettingsHistory, _json
from services.shared_settings_document import from_connection, validate_price_history, PRICE_KEYS
from services.peer_settings_outbox import enqueue_revision
from services.sync_schedule import dump_schedule_windows, load_schedule_windows

EDITABLE_KEYS = frozenset({"billing_day", "waste_paper_pct", "sync_schedule_windows", "pricing_mode", "work_start", "work_end"})
UNDO_KEYS = EDITABLE_KEYS | {"price_history"}


@dataclass(frozen=True)
class SettingsPreview:
    expected_head: str | None
    before_json: str
    after_json: str
    reason: str
    database_path: str
    remote_head: str | None = None

    @property
    def changes(self):
        old, new = json.loads(self.before_json), json.loads(self.after_json)
        before, after = old["settings"], new["settings"]
        changes = {key: (before[key], after[key]) for key in sorted(EDITABLE_KEYS)
                if before[key] != after[key]}
        if old["price_history"] != new["price_history"]:
            left = {(r["slot"], r["effective_date"]): r for r in old["price_history"]}
            right = {(r["slot"], r["effective_date"]): r for r in new["price_history"]}
            changed = sorted(key for key in left.keys() | right.keys() if left.get(key) != right.get(key))
            changes["price_history"] = ([left[key] for key in changed if key in left],
                                         [right[key] for key in changed if key in right])
        return changes


def _normalized_changes(changes):
    if not isinstance(changes, dict) or not changes or not set(changes) <= EDITABLE_KEYS:
        raise ValueError("Unsupported shared setting change")
    values = dict(changes)
    if "pricing_mode" in values and (not isinstance(values["pricing_mode"], str) or values["pricing_mode"] not in {"shared", "per_device", "deferred"}):
        raise ValueError("Invalid pricing mode")
    for key in ("work_start", "work_end"):
        if key in values:
            if not isinstance(values[key], str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", values[key]):
                raise ValueError("Invalid working time")
    if "billing_day" in values:
        value = values["billing_day"]
        if type(value) is not int or not 1 <= value <= 31:
            raise ValueError("Billing day must be between 1 and 31")
    if "waste_paper_pct" in values:
        value = values["waste_paper_pct"]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Waste percentage must be between 0 and 100")
        values["waste_paper_pct"] = float(value)
    if "sync_schedule_windows" in values:
        value = values["sync_schedule_windows"]
        if not isinstance(value, str):
            raise ValueError("Invalid reading schedule")
        windows = load_schedule_windows(value)
        if windows is None:
            raise ValueError("Invalid reading schedule")
        values["sync_schedule_windows"] = dump_schedule_windows(windows)
    return values


class SharedSettingsService:
    def history_page(self, *, before_rowid=None, limit=50):
        """Read a bounded page without recording an observation or changing head."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid history page size")
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            head = SettingsHistory._state(conn, "head")
            local_ancestors = SettingsHistory._ancestors(conn, head)
            pending = {row[0] for row in conn.execute("SELECT value FROM peer_settings_state WHERE key LIKE 'review:%'")}
            rows = conn.execute(
                "SELECT rowid,revision,document_json FROM peer_settings_revisions "
                "WHERE rowid<? ORDER BY rowid DESC LIMIT ?",
                (before_rowid if before_rowid is not None else 9223372036854775807, limit),
            ).fetchall()
            entries = []
            for rowid, revision, raw in rows:
                document = json.loads(raw)
                previous = (SettingsHistory._document(conn, document["parents"][0])["payload"]
                            if len(document["parents"]) == 1 else None)
                fields = [key for key in sorted(EDITABLE_KEYS) if previous is not None
                          and previous["settings"][key] != document["payload"]["settings"][key]]
                if (previous is not None and "price_history" in previous and "price_history" in document["payload"]
                        and previous["price_history"] != document["payload"]["price_history"]):
                    fields.append("price_history")
                entries.append({"rowid": rowid, "revision": revision, "document": document,
                                "previous": previous, "incoming": revision in pending and revision not in local_ancestors,
                                "undo_fields": fields if revision in local_ancestors else [], "current": revision == head})
        return entries

    @staticmethod
    def _database_path():
        return str(Path(get_db_path()).resolve())

    @staticmethod
    def _payload(conn):
        return from_connection(conn)

    def preview(self, changes, *, reason):
        values = _normalized_changes(changes)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A change reason is required")
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            before = self._payload(conn)
            head = SettingsHistory._state(conn, "head")
        after = deepcopy(before)
        after["settings"].update(values)
        return SettingsPreview(head, _json(before), _json(after), reason.strip(), self._database_path())

    def preview_choice(self, remote_head, *, chosen_head, reason):
        """Prepare an explicit peer choice without changing any app settings.

        The caller must already have authenticated/imported the peer history.
        Applying a device/organization change through this path is rejected.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A choice reason is required")
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            before = self._payload(conn)
            local = SettingsHistory._state(conn, "head")
            if not local or chosen_head not in {local, remote_head}:
                raise ValueError("Choose a local or incoming revision")
            if SettingsHistory._document(conn, local)["payload"] != before:
                raise ValueError("Settings changed outside the reviewed history")
            SettingsHistory._ancestors(conn, remote_head)
            after = SettingsHistory._document(conn, chosen_head)["payload"]
        self._check_scope(before, after)
        return SettingsPreview(local, _json(before), _json(after), reason.strip(), self._database_path(), remote_head)

    @staticmethod
    def _check_scope(before, after):
        if after.get("format_version") != 2 or "price_history" not in after:
            raise ValueError("Legacy snapshots require the setup workflow")
        allowed = deepcopy(before)
        changes = {key: after["settings"][key] for key in EDITABLE_KEYS
                   if before["settings"][key] != after["settings"][key]}
        if changes:
            # Empty string is the legacy schedule, permitted when restoring it.
            validate = {key: value for key, value in changes.items()
                        if not (key == "sync_schedule_windows" and value == "")}
            if validate:
                _normalized_changes(validate)
            allowed["settings"].update(changes)
        if before["price_history"] != after["price_history"]:
            validate_price_history(after["price_history"])
            allowed["price_history"] = deepcopy(after["price_history"])
            changes["price_history"] = allowed["price_history"]
        if allowed != after:
            raise ValueError("This change requires the printer or setup workflow")
        return changes

    def commit(self, preview):
        """Persist the reviewed fields and history head in one SQLite commit."""
        before, after = json.loads(preview.before_json), json.loads(preview.after_json)
        changes = self._check_scope(before, after)
        if not isinstance(preview.reason, str) or not preview.reason.strip():
            raise ValueError("A change reason is required")
        history = SettingsHistory()
        with config_write_transaction() as conn:
            head = history._state(conn, "head")
            if (self._database_path() != preview.database_path
                    or head != preview.expected_head or self._payload(conn) != before):
                raise ValueError("การตั้งค่าเปลี่ยนหลังเปิดหน้าต่างยืนยัน กรุณาตรวจและบันทึกใหม่")
            fast_forward = False
            if preview.remote_head:
                remote_ancestors = history._ancestors(conn, preview.remote_head)
                choices = [history._document(conn, key)["payload"]
                           for key in (head, preview.remote_head) if key]
                if after not in choices:
                    raise ValueError("Invalid peer revision choice")
                if preview.remote_head in history._ancestors(conn, head) and not changes:
                    return head
                fast_forward = (head in remote_ancestors
                                and after == history._document(conn, preview.remote_head)["payload"])
            elif not changes:
                return head
            # Capture pre-existing legacy values before their first audited edit.
            if not head or history._document(conn, head)["payload"] != before:
                head = history._append(conn, before, [head] if head else [], "local_settings_baseline")
            for key, value in changes.items():
                if key == "price_history":
                    from services.pricing import PriceList, PricingRepository
                    # Earlier price versions remain immutable in revisions and
                    # issued ledger rows; this is the reviewed active schedule.
                    conn.execute("DELETE FROM price_history")
                    for row in value:
                        PricingRepository.write_prices(conn, row["slot"], date.fromisoformat(row["effective_date"]),
                            PriceList(**{field: row[field] for field in PRICE_KEYS}))
                    conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                        (key, _json(before[key]), _json(value), datetime.now(UTC).isoformat()))
                    continue
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
                conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                             (key, str(before["settings"][key]), str(value), datetime.now(UTC).isoformat()))
            if self._payload(conn) != after:
                raise ValueError("Saved settings differ from the reviewed revision")
            if fast_forward:
                # Receiving an existing edit must not create another edit and
                # cause an endless revision exchange between identical peers.
                conn.execute("UPDATE peer_settings_state SET value=? WHERE key='head'", (preview.remote_head,))
                enqueue_revision(conn, preview.remote_head, datetime.now(UTC).isoformat())
                return preview.remote_head
            parents = [head] + ([preview.remote_head] if preview.remote_head else [])
            return history._append(conn, after, parents, preview.reason)

    def preview_undo(self, revision, *, keys, reason):
        """Undo selected fields with a new edit; unrelated later edits survive."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("An undo reason is required")
        selected = frozenset(keys)
        if not selected or not selected <= UNDO_KEYS:
            raise ValueError("Select supported fields to undo")
        with _open(commit=False) as conn:
            conn.execute("BEGIN")
            head = SettingsHistory._state(conn, "head")
            if revision not in SettingsHistory._ancestors(conn, head):
                raise ValueError("The revision is not in local history")
            record = SettingsHistory._document(conn, revision)
            if len(record["parents"]) != 1:
                raise ValueError("Select a non-merge change with a previous value")
            old = SettingsHistory._document(conn, record["parents"][0])["payload"]
            now = self._payload(conn)
            for key in selected:
                if key == "price_history":
                    # Preserve unrelated later price edits; undo only keys
                    # changed by the selected revision, after checking each.
                    if key not in old or key not in record["payload"]:
                        raise ValueError("Legacy snapshots require the setup workflow")
                    prior = {(r["slot"], r["effective_date"]): r for r in old[key]}
                    edited = {(r["slot"], r["effective_date"]): r for r in record["payload"][key]}
                    current = {(r["slot"], r["effective_date"]): r for r in now[key]}
                    affected = {k for k in prior.keys() | edited.keys() if prior.get(k) != edited.get(k)}
                    if any(current.get(k) != edited.get(k) for k in affected):
                        raise ValueError("A selected price has changed again; review the newer edit")
                    for k in affected:
                        if k in prior:
                            current[k] = prior[k]
                        else:
                            current.pop(k, None)
                    prices_after = [current[k] for k in sorted(current)]
                    continue
                if now["settings"][key] != record["payload"]["settings"][key]:
                    raise ValueError("A selected field has changed again; review the newer edit")
            after = deepcopy(now)
            after["settings"].update({key: old["settings"][key] for key in selected if key in EDITABLE_KEYS})
            if "price_history" in selected:
                after["price_history"] = prices_after
        return SettingsPreview(head, _json(now), _json(after), f"undo:{revision}: {reason.strip()}", self._database_path())
