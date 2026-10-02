"""Immutable parsed Web observations and atomic outgoing work.

This is evidence storage, not a billing reducer or an authentication service.
The transport must authorize a member and the shared slot/serial before import.
Imported older values never rewrite local caches or last-success timestamps.
"""
from contextlib import closing
from datetime import datetime, UTC
import hashlib
import json
import math
import sqlite3
import uuid

from services.peer_change_events import notify_local_change
from database import get_db_path
from komi_snmp_profiler.models import Confidence, WebAuthState

MAX_EVENT_BYTES = 4 * 1024 * 1024
MAX_PAGE_BYTES = 8 * 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _text(value, maximum=256, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError("Invalid Web observation text")


def _timestamp(value):
    _text(value, 64)
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("An explicit observation timezone is required")


def validate_event(event):
    if not isinstance(event, dict) or set(event) != {"id", "payload"}:
        raise ValueError("Invalid Web observation envelope")
    payload = event["payload"]
    if not isinstance(payload, dict):
        raise ValueError("Invalid Web observation payload")
    fields = {"format", "read_id", "origin", "slot", "serial", "printer_name", "observed_at", "reading"}
    if payload.get("format") == "komi.web.observation.v2":
        fields.add("meter_epoch_id")
    elif payload.get("format") != "komi.web.observation.v1":
        raise ValueError("Invalid Web observation payload")
    if set(payload) != fields:
        raise ValueError("Invalid Web observation payload")
    if "meter_epoch_id" in payload:
        value = payload["meter_epoch_id"]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("Invalid Web meter epoch identity")
    for key in ("read_id", "origin", "serial"):
        _text(payload[key])
    _text(payload["printer_name"], empty=True)
    if type(payload["slot"]) is not int or payload["slot"] not in range(3):
        raise ValueError("Invalid shared slot")
    _timestamp(payload["observed_at"])
    reading = payload["reading"]
    if not isinstance(reading, dict) or set(reading) != {"host", "collected_at", "source", "auth_state", "schema_version", "warnings", "counters"}:
        raise ValueError("Invalid parsed Web reading")
    for key in ("host", "source", "schema_version"):
        _text(reading[key])
    _timestamp(reading["collected_at"])
    WebAuthState(reading["auth_state"])
    if not isinstance(reading["warnings"], list) or len(reading["warnings"]) > 1000:
        raise ValueError("Invalid reading warnings")
    for warning in reading["warnings"]:
        _text(warning, 2048)
    counters = reading["counters"]
    if not isinstance(counters, list) or not counters or len(counters) > 20000:
        raise ValueError("Invalid Web counter count")
    identities = set()
    for counter in counters:
        if not isinstance(counter, dict) or set(counter) != {"canonical_field", "label", "count", "category", "source_path", "confidence", "subject_type", "subject_id", "subject_name"}:
            raise ValueError("Invalid parsed Web counter")
        for key in ("canonical_field", "label", "category", "source_path"):
            _text(counter[key], 2048, empty=key != "canonical_field")
        for key in ("subject_type", "subject_id", "subject_name"):
            if counter[key] is not None:
                _text(counter[key], 2048, empty=True)
        Confidence(counter["confidence"])
        value = counter["count"]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid absolute Web counter")
        identity = tuple(counter[key] for key in ("canonical_field", "source_path", "subject_type", "subject_id", "subject_name"))
        if identity in identities:
            raise ValueError("Duplicate counter in one observation")
        identities.add(identity)
    encoded = _json(payload).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES or hashlib.sha256(encoded).hexdigest() != event["id"]:
        raise ValueError("Oversized or altered Web observation")
    return _json(event)


class WebObservationStore:
    def __init__(self, path=None):
        self.path = path or get_db_path()

    def _document(self, event_id, document, archive_id):
        if archive_id is None:
            return document
        from services.web_observation_archive import WebObservationArchive
        return WebObservationArchive(self.path).read_document(archive_id, event_id)

    @notify_local_change
    def record(self, slot, reading, *, serial, printer_name, at=None, read_id=None, epoch_id=None):
        """Durably capture a completed Web result before updating presentations."""
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            return self.record_in_transaction(conn, slot, reading, serial=serial,
                printer_name=printer_name, at=at, read_id=read_id, epoch_id=epoch_id)

    def record_in_transaction(self, conn, slot, reading, *, serial, printer_name,
                              at=None, read_id=None, epoch_id=None, origin=None):
        """Join setup's transaction; the caller owns commit and change notification."""
        if not conn.in_transaction:
            raise ValueError("Recording requires an existing write transaction")
        stamp = at or datetime.now().astimezone()
        device = conn.execute("SELECT serial,host FROM devices WHERE slot=?", (slot,)).fetchone()
        if not serial or not device or device != (serial, reading.host):
            raise ValueError("Printer identity changed during Web reading")
        row = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
        if row and origin is not None and origin != row[0]:
            raise ValueError("Web observation origin changed after review")
        origin = row[0] if row else origin or str(uuid.uuid4())
        conn.execute("INSERT OR IGNORE INTO web_observation_state VALUES('origin',?)", (origin,))
        # The local observation origin is not company membership proof.
        reading_dict = reading.to_dict()
        reading_dict["counters"] = list(reading_dict["counters"])
        reading_dict["warnings"] = list(reading_dict["warnings"])
        payload = {"format": "komi.web.observation.v1", "origin": origin,
                   "read_id": read_id or str(uuid.uuid4()), "slot": slot, "serial": serial,
                   "printer_name": printer_name, "observed_at": stamp.isoformat(), "reading": reading_dict}
        if epoch_id is not None:
            from services.slot_epoch_store import SlotEpochStore
            if SlotEpochStore._head(conn, slot) != epoch_id:
                raise ValueError("Slot meter epoch changed during Web reading")
            payload.update(format="komi.web.observation.v2", meter_epoch_id=epoch_id)
        event = {"id": hashlib.sha256(_json(payload).encode("utf-8")).hexdigest(), "payload": payload}
        document = validate_event(event)
        self._insert(conn, event, document)
        conn.execute("INSERT OR IGNORE INTO web_observation_outbox VALUES(?)", (event["id"],))
        return event

    @staticmethod
    def _insert(conn, event, document):
        payload = event["payload"]
        existing = conn.execute("SELECT event_id FROM web_observations WHERE origin_id=? AND read_id=?",
                                (payload["origin"], payload["read_id"])).fetchone()
        if existing and existing[0] != event["id"]:
            raise ValueError("Conflicting results for the same Web read job")
        conn.execute("""INSERT OR IGNORE INTO web_observations
            (event_id,origin_id,read_id,device_slot,device_serial,observed_at,document_json,recorded_at) VALUES(?,?,?,?,?,?,?,?)""",
            (event["id"], payload["origin"], payload["read_id"], payload["slot"], payload["serial"], payload["observed_at"], document,
             datetime.now(UTC).isoformat()))
        if payload.get("meter_epoch_id") is not None:
            from services.slot_epoch_store import SlotEpochStore
            epoch = SlotEpochStore._epoch(conn, payload["meter_epoch_id"])
            SlotEpochStore._assign(conn, epoch, event)

    def receive(self, events, *, expected_slot, expected_serial, expected_epoch=None):
        """Import a bounded authorized batch, idempotently, without projecting usage.

        Callers must validate membership and shared slot authority beforehand.
        A transport receipt can be sent only after this transaction commits.
        """
        if not isinstance(events, list) or len(events) > 128:
            raise ValueError("Invalid observation batch")
        documents = [validate_event(event) for event in events]
        if sum(len(doc.encode("utf-8")) for doc in documents) > MAX_PAGE_BYTES:
            raise ValueError("Oversized observation batch")
        for event in events:
            payload = event["payload"]
            if (payload["slot"], payload["serial"]) != (expected_slot, expected_serial):
                raise ValueError("Observation does not match the authorized slot and serial")
            if payload.get("meter_epoch_id") != expected_epoch:
                raise ValueError("Observation does not match the authorized meter epoch")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            for event, document in zip(events, documents):
                self._insert(conn, event, document)
        return tuple(event["id"] for event in events)

    def page(self, *, after=0, through=None, limit=32):
        """Pin a local high-water mark; all observations remain individually addressable."""
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("Invalid observation cursor")
        with closing(sqlite3.connect(self.path)) as conn:
            high = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM web_observations").fetchone()[0]
            through = high if through is None else through
            if type(through) is not int or not after <= through <= high:
                raise ValueError("Invalid observation high-water mark")
            rows = conn.execute("""SELECT sequence,event_id,document_json,archive_id FROM web_observations
                WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?""", (after, through, limit))
            events, size, cursor = [], 0, after
            for sequence, event_id, document, archive_id in rows:
                document = self._document(event_id, document, archive_id)
                length = len(document.encode("utf-8"))
                if events and size + length > MAX_PAGE_BYTES:
                    break
                events.append(json.loads(document))
                size += length
                cursor = sequence
        return {"events": events, "through": through, "next": cursor, "complete": cursor == through}

    def pending(self, peer_id, *, limit=32):
        _text(peer_id)
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("Invalid delivery limit")
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute("""SELECT o.event_id,o.document_json,o.archive_id FROM web_observations o
                JOIN web_observation_outbox q ON q.event_id=o.event_id
                LEFT JOIN web_observation_receipts r ON r.event_id=o.event_id AND r.peer_id=?
                WHERE r.event_id IS NULL ORDER BY o.sequence LIMIT ?""", (peer_id, limit))
            events, size = [], 0
            for event_id, document, archive_id in rows:
                document = self._document(event_id, document, archive_id)
                length = len(document.encode("utf-8"))
                if events and size + length > MAX_PAGE_BYTES:
                    break
                events.append(json.loads(document))
                size += length
        return events

    def acknowledge(self, peer_id, event_ids):
        """Persist only authenticated receipts for records durably stored remotely."""
        _text(peer_id)
        if not isinstance(event_ids, (list, tuple)) or len(event_ids) > 128:
            raise ValueError("Invalid observation receipt batch")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            for event_id in event_ids:
                if not conn.execute("SELECT 1 FROM web_observation_outbox WHERE event_id=?", (event_id,)).fetchone():
                    raise ValueError("Unknown outgoing observation")
                conn.execute("INSERT OR IGNORE INTO web_observation_receipts VALUES(?,?,?)",
                             (peer_id, event_id, datetime.now(UTC).isoformat()))
