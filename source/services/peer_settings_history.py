"""Durable causal history for shared settings, independent of wall-clock order.

Receiving history never applies printer/pricing settings. Transport authorization
and applying a reviewed decision remain responsibilities of the caller.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import sqlite3
import uuid

from database import get_db_path
from services.secondary_setup import SECONDARY_SETUP_CONTRACT, setup_snapshot_from_connection, validate_setup_snapshot

CONTRACT = "komi-peer-settings-history/v1"
MAX_REVISIONS = 256
MAX_PACKET_BYTES = 128 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def shared_settings(snapshot):
    normalized = validate_setup_snapshot(snapshot)
    organization = dict(normalized["organization"])
    del organization["primary_installation_id"]
    return {"organization": organization, "settings": normalized["settings"],
            "devices": normalized["devices"]}


def _validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"organization", "settings", "devices"}:
        raise ValueError("Invalid shared settings")
    organization = payload["organization"]
    if not isinstance(organization, dict) or set(organization) != {"company_name", "first_started_at"}:
        raise ValueError("Invalid shared organization fields")
    normalized = shared_settings({"contract": SECONDARY_SETUP_CONTRACT, "generated_at": "",
        **payload, "organization": {**organization, "primary_installation_id": ""}})
    if _json(normalized) != _json(payload):
        raise ValueError("Shared settings must be normalized")


def _revision(document):
    return hashlib.sha256(_json(document).encode("utf-8")).hexdigest()


class SettingsHistory:
    def __init__(self, path=None):
        self.path = path or get_db_path()

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _state(conn, key):
        row = conn.execute("SELECT value FROM peer_settings_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _document(conn, revision):
        row = conn.execute("SELECT document_json FROM peer_settings_revisions WHERE revision=?", (revision,)).fetchone()
        if not row:
            raise ValueError("Missing settings history; fetch ancestors first")
        return json.loads(row[0])

    @classmethod
    def _ancestors(cls, conn, head):
        found, pending = set(), [head] if head else []
        while pending:
            revision = pending.pop()
            if revision in found:
                continue
            found.add(revision)
            pending.extend(cls._document(conn, revision)["parents"])
        return found

    def _append(self, conn, payload, parents, reason):
        node = self._state(conn, "node_id")
        if not node:
            node = str(uuid.uuid4())
            conn.execute("INSERT INTO peer_settings_state VALUES('node_id',?)", (node,))
        document = {"parents": sorted(set(parents)), "payload": deepcopy(payload),
                    "actor": node, "created_at": datetime.now(UTC).isoformat(), "reason": reason}
        revision = _revision(document)
        conn.execute("INSERT INTO peer_settings_revisions VALUES(?,?)", (revision, _json(document)))
        conn.execute("INSERT INTO peer_settings_state VALUES('head',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (revision,))
        return revision

    def observe(self, snapshot):
        """Record a changed local snapshot; generated time/installation ID are local."""
        payload = shared_settings(snapshot)
        _validate_payload(payload)
        with self._transaction() as conn:
            head = self._state(conn, "head")
            if head and self._document(conn, head)["payload"] == payload:
                return head
            return self._append(conn, payload, [head] if head else [], "local_settings_observed")

    def observe_current(self):
        """Capture DB values and advance history under the same write lock.

        An API handler must not record a previously captured snapshot after a
        newer settings save has committed, turning a read into an apparent undo.
        """
        with self._transaction() as conn:
            payload = shared_settings(setup_snapshot_from_connection(conn))
            _validate_payload(payload)
            head = self._state(conn, "head")
            if head and self._document(conn, head)["payload"] == payload:
                return head
            return self._append(conn, payload, [head] if head else [], "local_settings_observed")

    def export(self):
        with self._transaction() as conn:
            head = self._state(conn, "head")
            if not head:
                raise ValueError("No local settings revision")
            ancestors = self._ancestors(conn, head)
            if len(ancestors) > MAX_REVISIONS:
                raise ValueError("History requires paged transfer")
            packet = {"contract": CONTRACT, "head": head,
                      "revisions": {key: self._document(conn, key) for key in sorted(ancestors)}}
            if len(_json(packet).encode("utf-8")) > MAX_PACKET_BYTES:
                raise ValueError("History requires paged transfer")
            return packet

    def receive(self, packet):
        """Validate/import ancestry atomically and classify; never move local head."""
        if (not isinstance(packet, dict) or set(packet) != {"contract", "head", "revisions"}
                or packet["contract"] != CONTRACT or not isinstance(packet["revisions"], dict)
                or not 1 <= len(packet["revisions"]) <= MAX_REVISIONS
                or packet["head"] not in packet["revisions"]
                or len(_json(packet).encode("utf-8")) > MAX_PACKET_BYTES):
            raise ValueError("Invalid settings history packet")
        for revision, document in packet["revisions"].items():
            if (not isinstance(document, dict)
                    or set(document) != {"parents", "payload", "actor", "created_at", "reason"}
                    or not isinstance(document["parents"], list)
                    or len(document["parents"]) > 2
                    or any(not isinstance(parent, str) for parent in document["parents"])
                    or any(not isinstance(document[key], str) or not document[key]
                           for key in ("actor", "created_at", "reason"))
                    or revision != _revision(document)):
                raise ValueError("Invalid settings revision")
            _validate_payload(document["payload"])
        with self._transaction() as conn:
            for revision, document in packet["revisions"].items():
                conn.execute("INSERT OR IGNORE INTO peer_settings_revisions VALUES(?,?)", (revision, _json(document)))
            remote = packet["head"]
            remote_ancestors = self._ancestors(conn, remote)
            # Validate all supplied nodes, including ones unrelated to packet head.
            for revision in packet["revisions"]:
                self._ancestors(conn, revision)
            local = self._state(conn, "head")
            if not local:
                status = "initial_review"
            elif local == remote:
                status = "in_sync"
            elif local in remote_ancestors:
                status = "incoming_newer"
            elif remote in self._ancestors(conn, local):
                status = "local_newer"
            elif self._document(conn, local)["payload"] == self._document(conn, remote)["payload"]:
                status = "same_values"
            elif self._ancestors(conn, local) & remote_ancestors:
                status = "conflict"
            else:
                status = "unrelated_history"
            return {"status": status, "local_head": local, "remote_head": remote}

    def resolve(self, remote_head, *, expected_local_head, chosen_head, reason):
        """Journal an explicit choice. Does not apply the selected app settings."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Resolution requires a reason")
        with self._transaction() as conn:
            local = self._state(conn, "head")
            if local != expected_local_head or chosen_head not in {local, remote_head} or not chosen_head:
                raise ValueError("Settings changed after preview")
            self._ancestors(conn, remote_head)
            payload = self._document(conn, chosen_head)["payload"]
            return self._append(conn, payload, [key for key in (local, remote_head) if key], reason.strip())
