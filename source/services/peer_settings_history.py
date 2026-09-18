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
from services.secondary_setup import SECONDARY_SETUP_CONTRACT, validate_setup_snapshot
from services.shared_settings_document import from_connection, validate as validate_document
from services.peer_settings_outbox import enqueue_revision

CONTRACT = "komi-peer-settings-history/v1"
PAGE_CONTRACT = "komi-peer-settings-page/v1"
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
    if isinstance(payload, dict) and "format_version" in payload:
        validate_document(payload)
        return
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


def _validate_revision(revision, document):
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
        enqueue_revision(conn, revision, document["created_at"])
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
            payload = from_connection(conn)
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
            _validate_revision(revision, document)
        with self._transaction() as conn:
            for revision, document in packet["revisions"].items():
                conn.execute("INSERT OR IGNORE INTO peer_settings_revisions VALUES(?,?)", (revision, _json(document)))
            remote = packet["head"]
            # Validate all supplied nodes, including ones unrelated to packet head.
            for revision in packet["revisions"]:
                self._ancestors(conn, revision)
            return self._record_incoming_review(conn, remote)

    def _record_incoming_review(self, conn, remote):
        result = self._classify(conn, remote)
        obsolete = self._ancestors(conn, remote) | self._ancestors(conn, result["local_head"])
        for (key,) in conn.execute("SELECT key FROM peer_settings_state WHERE key LIKE 'review:%'").fetchall():
            if key[7:] in obsolete:
                conn.execute("DELETE FROM peer_settings_state WHERE key=?", (key,))
        if result["status"] not in {"in_sync", "local_newer"}:
            conn.execute("INSERT OR REPLACE INTO peer_settings_state(key,value) VALUES(?,?)",
                         ("review:" + remote, remote))
        return result

    def _classify(self, conn, remote):
        remote_ancestors = self._ancestors(conn, remote)
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

    def export_page(self, *, head=None, offset=0, limit=64):
        """Export ancestors first, pinned to an immutable head across local edits.

        Packets remain bounded by bytes as well as count. A single oversized
        revision fails explicitly; it is never silently truncated.
        """
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_REVISIONS:
            raise ValueError("Invalid history page cursor")
        with self._transaction() as conn:
            local = self._state(conn, "head")
            head = head or local
            if not head or head not in self._ancestors(conn, local):
                raise ValueError("Unknown local history head")
            ordered, seen, documents = [], set(), {}
            pending = [(head, False)]
            while pending:
                revision, expanded = pending.pop()
                if revision in seen:
                    continue
                document = documents.get(revision) or self._document(conn, revision)
                documents[revision] = document
                if expanded:
                    seen.add(revision)
                    ordered.append(revision)
                else:
                    pending.append((revision, True))
                    pending.extend((parent, False) for parent in reversed(document["parents"]))
            if offset >= len(ordered):
                raise ValueError("History page cursor outside this head")
            packet = {"contract": PAGE_CONTRACT, "head": head, "offset": offset,
                      "next_offset": None, "revisions": {}}
            for index in range(offset, min(len(ordered), offset + limit)):
                revision = ordered[index]
                packet["revisions"][revision] = documents[revision]
                packet["next_offset"] = index + 1 if index + 1 < len(ordered) else None
                if len(_json(packet).encode("utf-8")) > MAX_PACKET_BYTES:
                    del packet["revisions"][revision]
                    packet["next_offset"] = index
                    break
            if not packet["revisions"]:
                raise ValueError("One settings revision exceeds the transfer limit")
            return packet

    def receive_page(self, packet, *, authorize=None, origin_member=None):
        """Persist a verified page; retries are idempotent and never apply values.

        Missing previous pages roll back this page. The last page classifies the
        complete ancestry so callers cannot treat a partial transfer as a choice.
        Transport must authenticate the peer before calling this method.
        """
        if origin_member is not None:
            from services.peer_settings_outbox import _peer
            _peer(origin_member)
            if not callable(authorize):
                raise PermissionError('Persisting an incoming member requires scope authorization')
        if (not isinstance(packet, dict)
                or set(packet) != {"contract", "head", "offset", "next_offset", "revisions"}
                or packet["contract"] != PAGE_CONTRACT or not isinstance(packet["head"], str)
                or type(packet["offset"]) is not int or packet["offset"] < 0
                or not isinstance(packet["revisions"], dict)
                or not 1 <= len(packet["revisions"]) <= MAX_REVISIONS
                or (packet["next_offset"] is not None and
                    (type(packet["next_offset"]) is not int or
                     packet["next_offset"] != packet["offset"] + len(packet["revisions"])))
                or len(_json(packet).encode("utf-8")) > MAX_PACKET_BYTES):
            raise ValueError("Invalid settings history page")
        for revision, document in packet["revisions"].items():
            _validate_revision(revision, document)
        def check_authorization():
            if authorize is not None:
                if not callable(authorize) or any(authorize(revision, document['payload']) is not True
                        for revision, document in packet['revisions'].items()):
                    raise PermissionError('Member cannot import this settings history')
        check_authorization()
        with self._transaction() as conn:
            for revision, document in packet["revisions"].items():
                conn.execute("INSERT OR IGNORE INTO peer_settings_revisions VALUES(?,?)", (revision, _json(document)))
            for revision in packet["revisions"]:
                self._ancestors(conn, revision)
            local, remote = self._state(conn, "head"), packet["head"]
            check_authorization()
            if packet["next_offset"] is not None:
                return {"status": "incomplete", "local_head": local, "remote_head": remote,
                        "next_offset": packet["next_offset"]}
            if remote not in packet["revisions"]:
                raise ValueError("Final history page must include its head")
            result = {**self._record_incoming_review(conn, remote), "next_offset": None}
            if origin_member is not None:
                conn.execute('INSERT INTO peer_settings_state(key,value) VALUES(?,?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('sender:' + remote, origin_member))
            return result

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
