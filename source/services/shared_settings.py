"""Reviewed, atomic changes to the shared billing and collection settings.

Printer replacement, price effective dates and registration need their own
workflows. This service deliberately cannot apply those parts of a peer snapshot.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path

from database import _open, config_write_transaction, get_db_path
from services.peer_settings_history import SettingsHistory, _json
from services.shared_settings_document import from_connection
from services.sync_schedule import dump_schedule_windows, load_schedule_windows

EDITABLE_KEYS = frozenset({"billing_day", "waste_paper_pct", "sync_schedule_windows"})


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
        before = json.loads(self.before_json)["settings"]
        after = json.loads(self.after_json)["settings"]
        return {key: (before[key], after[key]) for key in sorted(EDITABLE_KEYS)
                if before[key] != after[key]}


def _normalized_changes(changes):
    if not isinstance(changes, dict) or not changes or not set(changes) <= EDITABLE_KEYS:
        raise ValueError("Unsupported shared setting change")
    values = dict(changes)
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
        Applying a device/price/organization change through this path is rejected.
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
        if allowed != after:
            raise ValueError("This change requires the printer, pricing or setup workflow")
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
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
                conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                             (key, str(before["settings"][key]), str(value), datetime.now(UTC).isoformat()))
            if fast_forward:
                # Receiving an existing edit must not create another edit and
                # cause an endless revision exchange between identical peers.
                conn.execute("UPDATE peer_settings_state SET value=? WHERE key='head'", (preview.remote_head,))
                return preview.remote_head
            parents = [head] + ([preview.remote_head] if preview.remote_head else [])
            return history._append(conn, after, parents, preview.reason)

    def preview_undo(self, revision, *, keys, reason):
        """Undo selected fields with a new edit; unrelated later edits survive."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("An undo reason is required")
        selected = frozenset(keys)
        if not selected or not selected <= EDITABLE_KEYS:
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
                if now["settings"][key] != record["payload"]["settings"][key]:
                    raise ValueError("A selected field has changed again; review the newer edit")
            after = deepcopy(now)
            after["settings"].update({key: old["settings"][key] for key in selected})
        return SettingsPreview(head, _json(now), _json(after), f"undo:{revision}: {reason.strip()}", self._database_path())
