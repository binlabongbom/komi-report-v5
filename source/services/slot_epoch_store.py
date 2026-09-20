"""Transactional local storage of reviewed slot epochs and bounded maximum proofs.

Assignment must be supplied by an authenticated read/epoch context. This store
does not infer an epoch for a legacy unbound event or automatically adopt a
remote decision. Maxima are indexed during assignment, so a replacement preview
does not scan years of Web payloads. The complete journal remains the audit trail.
"""
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from database import get_db_path
from services.slot_meter_continuity import (
    EpochObservation, counter_values, project_epoch, reviewed_epoch, validate_epoch,
    _encoded_number, _number, _json,
)
from services.web_observations import WebObservationStore


class SlotEpochStore:
    def __init__(self, path=None):
        self.path = Path(path or get_db_path()).resolve()

    @contextmanager
    def _connection(self, *, write=False):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn

    @staticmethod
    def _epoch(conn, epoch_id):
        row = conn.execute("SELECT document_json FROM slot_meter_epochs WHERE id=?", (epoch_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown reviewed slot epoch")
        epoch = json.loads(row[0])
        validate_epoch(epoch)
        return epoch

    def _event(self, conn, event_id):
        row = conn.execute("SELECT document_json,archive_id FROM web_observations WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("A committed Web observation is required")
        return json.loads(WebObservationStore(self.path)._document(event_id, row[0], row[1]))

    @staticmethod
    def _head(conn, slot):
        row = conn.execute("SELECT epoch_id FROM slot_meter_heads WHERE device_slot=?", (slot,)).fetchone()
        return row[0] if row else None

    def head(self, slot):
        with self._connection() as conn:
            head = self._head(conn, slot)
            return self._epoch(conn, head) if head else None

    @staticmethod
    def _legacy_identity_conflict(conn, slot, serials):
        placeholders = ",".join("?" for _ in serials)
        serials = tuple(serials)
        return conn.execute(f"""SELECT 1 FROM web_observations WHERE device_slot=? AND device_serial NOT IN ({placeholders})
            UNION ALL SELECT 1 FROM daily_raw_counter_records WHERE device_slot=? AND COALESCE(device_serial_snapshot,'') NOT IN ({placeholders})
            UNION ALL SELECT 1 FROM daily_meter_records WHERE device_slot=? AND
                CASE WHEN json_valid(source_json) THEN COALESCE(json_extract(source_json,'$.device_identity.serial'),'') ELSE '' END NOT IN ({placeholders})
            UNION ALL SELECT 1 FROM daily_subject_records WHERE device_slot=? AND
                CASE WHEN json_valid(source_json) THEN COALESCE(json_extract(source_json,'$.device_identity.serial'),'') ELSE '' END NOT IN ({placeholders})
            UNION ALL SELECT 1 FROM archived_subject_periods WHERE device_slot=? AND
                CASE WHEN json_valid(summary_json) THEN COALESCE(json_extract(summary_json,'$.device_serial_snapshot'),'') ELSE '' END NOT IN ({placeholders})
            LIMIT 1""", (slot, *serials, slot, *serials, slot, *serials, slot, *serials, slot, *serials)).fetchone() is not None

    def _proof(self, conn, epoch):
        anchor_id = epoch["document"]["baseline_event"]["id"]
        ids = {row[0] for row in conn.execute("SELECT DISTINCT event_id FROM slot_meter_maxima WHERE epoch_id=?", (epoch["id"],))}
        ids.discard(anchor_id)
        return [EpochObservation(epoch["id"], self._event(conn, event_id)) for event_id in sorted(ids)]

    def _projection(self, conn, epoch):
        proof = self._proof(conn, epoch)
        result = project_epoch(epoch, proof)
        issues = set(json.loads(conn.execute("SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?", (epoch["id"],)).fetchone()[0]))
        return replace(result, issues=tuple(sorted(set(result.issues) | issues))), proof

    @staticmethod
    def _flag_branch(conn, root, flag):
        for (epoch_id,) in conn.execute("""WITH RECURSIVE descendants(id) AS (
            SELECT id FROM slot_meter_epochs WHERE id=?
            UNION ALL SELECT e.id FROM slot_meter_epochs e JOIN descendants d ON e.parent_id=d.id)
            SELECT id FROM descendants""", (root,)).fetchall():
            row = conn.execute("SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?", (epoch_id,)).fetchone()
            issues = set(json.loads(row[0]))
            if flag not in issues:
                issues.add(flag)
                conn.execute("UPDATE slot_meter_epoch_state SET version=version+1,issues_json=? WHERE epoch_id=?",
                    (_json(sorted(issues)), epoch_id))

    def current(self, slot):
        with self._connection() as conn:
            head = self._head(conn, slot)
            return self._projection(conn, self._epoch(conn, head))[0] if head else None

    def review_latest(self, slot, *, actor, reason):
        """Prepare the current physical printer's latest committed Web baseline."""
        with self._connection() as conn:
            return self._review_latest(conn, slot, actor=actor, reason=reason)

    def _review_latest(self, conn, slot, *, actor, reason):
        device = conn.execute("SELECT serial FROM devices WHERE slot=? AND enabled=1", (slot,)).fetchone()
        if not device or not device[0]:
            raise ValueError("Read the configured printer and confirm its Serial first")
        latest = conn.execute("SELECT event_id FROM web_observations WHERE device_slot=? AND device_serial=? ORDER BY sequence DESC LIMIT 1",
            (slot, device[0])).fetchone()
        if latest is None:
            raise ValueError("No committed Web reading is available for this printer")
        head = self._head(conn, slot)
        previous = self._epoch(conn, head) if head else None
        operation = ("initial" if previous is None else
            "reset" if previous["document"]["baseline_event"]["payload"]["serial"] == device[0] else "replacement")
        return self._preview(conn, slot, latest[0], operation, actor, reason)

    def _preview(self, conn, slot, baseline_event_id, operation, actor, reason):
        if type(slot) is not int or slot not in range(3):
            raise ValueError("Invalid shared slot")
        candidate = self._event(conn, baseline_event_id)
        p = candidate["payload"]
        device = conn.execute("SELECT name,host,serial,enabled FROM devices WHERE slot=?", (slot,)).fetchone()
        if not device or p["slot"] != slot or (p["reading"]["host"], p["serial"]) != (device[1], device[2]) or not device[3]:
            raise ValueError("Read and test the current slot printer before confirmation")
        latest = conn.execute("SELECT event_id FROM web_observations WHERE device_slot=? AND device_serial=? ORDER BY sequence DESC LIMIT 1",
            (slot, p["serial"])).fetchone()
        if not latest or latest[0] != baseline_event_id:
            raise ValueError("A newer Web observation is available; review the latest baseline")
        head = self._head(conn, slot)
        parent, proof, version = None, (), None
        if head is None:
            if self._legacy_identity_conflict(conn, slot, (p["serial"],)):
                raise ValueError("Historical slot identity needs migration review before establishing a new shared baseline")
        if head:
            parent = self._epoch(conn, head)
            projection, proof = self._projection(conn, parent)
            if {"normalization_schema_changed", "counter_without_reviewed_baseline", "late_parent_evidence",
                    "competing_epoch_decisions"}.intersection(projection.issues):
                raise ValueError("Resolve pending slot evidence or mapping changes first")
            version = conn.execute("SELECT version FROM slot_meter_epoch_state WHERE epoch_id=?", (head,)).fetchone()[0]
        epoch = reviewed_epoch(candidate, parent=parent, parent_observations=proof,
            operation=operation, actor=actor, reason=reason)
        state = {"path": str(self.path), "slot": slot, "head": head, "version": version, "device": list(device),
            "candidate": candidate["id"], "epoch": epoch["id"]}
        revision = hashlib.sha256(_json(state).encode("utf-8")).hexdigest()
        return {"epoch": epoch, "revision": revision, "expected_head": head, "operation": operation,
            "slot": slot, "baseline_event_id": baseline_event_id, "actor": actor, "reason": reason}

    def preview(self, slot, baseline_event_id, *, operation, actor, reason):
        with self._connection() as conn:
            return self._preview(conn, slot, baseline_event_id, operation, actor, reason)

    def confirm(self, preview):
        """Recheck the full preview then commit definition, active head and outbox."""
        validate_epoch(preview["epoch"])
        with self._connection(write=True) as conn:
            return self._confirm(conn, preview)

    def _confirm(self, conn, preview):
        validate_epoch(preview["epoch"])
        existing = conn.execute("SELECT document_json FROM slot_meter_epochs WHERE id=?", (preview["epoch"]["id"],)).fetchone()
        if existing and self._head(conn, preview["slot"]) == preview["epoch"]["id"]:
            if json.loads(existing[0]) != preview["epoch"]:
                raise ValueError("Epoch confirmation retry differs")
            return preview["epoch"]["id"]
        fresh = self._preview(conn, preview["slot"], preview["baseline_event_id"], preview["operation"], preview["actor"], preview["reason"])
        if fresh != preview:
            raise ValueError("Slot evidence or settings changed after preview")
        epoch = preview["epoch"]
        if preview["operation"] == "reset":
            self._assign(conn, self._epoch(conn, epoch["document"]["parent"]),
                self._event(conn, preview["baseline_event_id"]))
        conn.execute("INSERT INTO slot_meter_epochs VALUES(?,?,?,?)",
            (epoch["id"], preview["slot"], epoch["document"]["parent"], _json(epoch)))
        conn.execute("INSERT INTO slot_meter_epoch_state(epoch_id) VALUES(?)", (epoch["id"],))
        self._assign(conn, epoch, self._event(conn, preview["baseline_event_id"]))
        conn.execute("INSERT INTO slot_meter_heads VALUES(?,?) ON CONFLICT(device_slot) DO UPDATE SET epoch_id=excluded.epoch_id",
            (preview["slot"], epoch["id"]))
        from services.slot_runtime import invalidate_device_runtime
        invalidate_device_runtime(conn, preview['slot'])
        conn.execute("INSERT INTO slot_meter_epoch_outbox VALUES(?)", (epoch["id"],))
        return epoch["id"]

    def assign(self, event_id, epoch_id):
        """Bind an already-committed event using its verified read/epoch context."""
        with self._connection(write=True) as conn:
            return self._assign(conn, self._epoch(conn, epoch_id), self._event(conn, event_id))

    @staticmethod
    def _assign(conn, epoch, event):
        p, doc = event["payload"], epoch["document"]
        anchor = doc["baseline_event"]["payload"]
        declared = p.get("meter_epoch_id")
        if declared is not None and declared != epoch["id"] and not (
                doc["operation"] == "reset" and declared == doc["parent"] and event["id"] == doc["baseline_event"]["id"]):
            raise ValueError("Web observation declares a different reviewed epoch")
        values = counter_values(event)
        if (p["slot"], p["serial"]) != (anchor["slot"], anchor["serial"]):
            raise ValueError("Wrong slot or serial for reviewed epoch")
        existing = {row[0] for row in conn.execute("SELECT epoch_id FROM slot_meter_assignments WHERE event_id=?", (event["id"],))}
        if epoch["id"] in existing:
            return False
        # An explicitly reviewed reset boundary may be both the old epoch's
        # final observation and the new baseline. Arbitrary rebinding is denied.
        if existing and not (existing == {doc["parent"]} and doc["operation"] == "reset"
                             and event["id"] == doc["baseline_event"]["id"]):
            raise ValueError("Web observation was already assigned to another epoch")
        issues = set(json.loads(conn.execute("SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?", (epoch["id"],)).fetchone()[0]))
        if p["reading"]["schema_version"] != anchor["reading"]["schema_version"]:
            issues.add("normalization_schema_changed")
        baseline = counter_values(doc["baseline_event"])
        for key, value in values.items():
            if key not in baseline:
                issues.add("counter_without_reviewed_baseline")
                continue
            previous = conn.execute("SELECT value_json,event_id,observed_at FROM slot_meter_maxima WHERE epoch_id=? AND counter_key=?",
                (epoch["id"], key)).fetchone()
            incoming = (value, datetime.fromisoformat(p["observed_at"]), event["id"])
            old = (_number(json.loads(previous[0])), datetime.fromisoformat(previous[2]), previous[1]) if previous else None
            if old and value < old[0] and incoming[1] >= old[1]:
                issues.add("lower_counter_or_clock_conflict")
            if old and value > old[0] and incoming[1] <= old[1]:
                issues.add("lower_counter_or_clock_conflict")
            if old is None or incoming > old:
                conn.execute("""INSERT INTO slot_meter_maxima VALUES(?,?,?,?,?) ON CONFLICT(epoch_id,counter_key)
                    DO UPDATE SET value_json=excluded.value_json,event_id=excluded.event_id,observed_at=excluded.observed_at""",
                    (epoch["id"], key, _json(_encoded_number(value)), event["id"], p["observed_at"]))
                if old and value > old[0]:
                    # A closed parent's newly discovered higher value cannot
                    # silently alter an already-reviewed child's carried total.
                    for (child,) in conn.execute("""WITH RECURSIVE descendants(id) AS (
                        SELECT id FROM slot_meter_epochs WHERE parent_id=?
                        UNION ALL SELECT e.id FROM slot_meter_epochs e JOIN descendants d ON e.parent_id=d.id)
                        SELECT id FROM descendants""", (epoch["id"],)).fetchall():
                        state = conn.execute("SELECT issues_json FROM slot_meter_epoch_state WHERE epoch_id=?", (child,)).fetchone()
                        flags = set(json.loads(state[0])) | {"late_parent_evidence"}
                        conn.execute("UPDATE slot_meter_epoch_state SET version=version+1,issues_json=? WHERE epoch_id=?", (_json(sorted(flags)), child))
        conn.execute("INSERT INTO slot_meter_assignments VALUES(?,?)", (event["id"], epoch["id"]))
        from services.shared_report_index import index_event
        index_event(conn, epoch, event)
        conn.execute("UPDATE slot_meter_epoch_state SET version=version+1,issues_json=? WHERE epoch_id=?", (_json(sorted(issues)), epoch["id"]))
        return True
