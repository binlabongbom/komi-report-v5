"""Bounded transfer of reviewed slot decisions, separate from head adoption.

The caller supplies a real membership/decision authorization callback. This
module is not an HTTP endpoint and deliberately has no permissive default.
Receiving evidence never changes printer settings, active heads or invoices.
"""
from services.slot_epoch_store import SlotEpochStore
from services.slot_meter_continuity import (
    EpochObservation, validate_epoch, verify_parent_carry, _json, _number,
)
from services.web_observations import WebObservationStore, validate_event


MAX_TRANSFER_BYTES = 8 * 1024 * 1024
MAX_PROOF_EVENTS = 128


class SlotEpochExchange:
    def __init__(self, *, authorize, path=None):
        if not callable(authorize):
            raise TypeError("An explicit slot decision authorizer is required")
        self.authorize = authorize
        self.store = SlotEpochStore(path)

    def _allowed(self, member, epoch):
        # A truthy object/name is not a verification result.
        if self.authorize(member, epoch) is not True:
            raise PermissionError("Member is not authorized for this slot decision")

    def export(self, member, epoch_id):
        with self.store._connection() as conn:
            epoch = self.store._epoch(conn, epoch_id)
            self._allowed(member, epoch)
            ids = epoch["document"]["parent_evidence"]
            if len(ids) > MAX_PROOF_EVENTS:
                raise ValueError("Epoch proof needs a paged evidence transfer")
            bundle = {"epoch": epoch, "parent_evidence": [self.store._event(conn, key) for key in ids]}
            self._validate(bundle)
            return bundle

    @staticmethod
    def _validate(bundle):
        if not isinstance(bundle, dict) or set(bundle) != {"epoch", "parent_evidence"}:
            raise ValueError("Invalid slot decision transfer")
        doc = validate_epoch(bundle["epoch"])
        events = bundle["parent_evidence"]
        if not isinstance(events, list) or len(events) > MAX_PROOF_EVENTS:
            raise ValueError("Invalid slot proof count")
        for event in events:
            validate_event(event)
        if [event["id"] for event in events] != doc["parent_evidence"]:
            raise ValueError("Exact reviewed parent evidence is required")
        if len(_json(bundle).encode("utf-8")) > MAX_TRANSFER_BYTES:
            raise ValueError("Oversized slot decision transfer")
        return doc

    def receive(self, member, bundle):
        """Commit verified ancestry and its proof before returning a receipt ID."""
        doc = self._validate(bundle)
        epoch = bundle["epoch"]
        self._allowed(member, epoch)
        with self.store._connection(write=True) as conn:
            parent = self.store._epoch(conn, doc["parent"]) if doc["parent"] else None
            proof = [EpochObservation(doc["parent"], event) for event in bundle["parent_evidence"]]
            verify_parent_carry(epoch, parent, proof)
            existing = conn.execute("SELECT document_json FROM slot_meter_epochs WHERE id=?", (epoch["id"],)).fetchone()
            if existing:
                if existing[0] != _json(epoch):
                    raise ValueError("Conflicting stored slot decision")
                return epoch["id"]
            # Parent first: a v2 reset boundary declares the parent epoch.
            for event in bundle["parent_evidence"]:
                WebObservationStore._insert(conn, event, validate_event(event))
                self.store._assign(conn, parent, event)
            baseline = doc["baseline_event"]
            WebObservationStore._insert(conn, baseline, validate_event(baseline))
            if doc["operation"] == "reset":
                self.store._assign(conn, parent, baseline)
            conn.execute("INSERT INTO slot_meter_epochs VALUES(?,?,?,?)",
                (epoch["id"], baseline["payload"]["slot"], doc["parent"], _json(epoch)))
            conn.execute("INSERT INTO slot_meter_epoch_state(epoch_id) VALUES(?)", (epoch["id"],))
            self.store._assign(conn, epoch, baseline)
            # Local evidence can be newer than the remote review. Preserve both
            # facts and hold adoption; never rewrite the remote signed content.
            if parent:
                projection, _ = self.store._projection(conn, parent)
                carry = {key: _number(value) for key, value in doc["carried"].items()}
                if ("late_parent_evidence" in projection.issues or
                        any(item.slot_total > carry.get(item.key, -1) for item in projection.counters)):
                    conn.execute("UPDATE slot_meter_epoch_state SET issues_json=? WHERE epoch_id=?",
                        (_json(["late_parent_evidence"]), epoch["id"]))
            return epoch["id"]

    def adopt(self, member, epoch_id, *, expected_head):
        """Explicit compare-and-swap after shared printer settings are applied.

        Conflicting branches and local higher parent evidence require review.
        This does not release legacy cache/billing holds or initialize old data.
        """
        with self.store._connection(write=True) as conn:
            epoch = self.store._epoch(conn, epoch_id)
            self._allowed(member, epoch)
            slot = epoch["document"]["baseline_event"]["payload"]["slot"]
            head = self.store._head(conn, slot)
            if head != expected_head:
                raise ValueError("Active slot decision changed; refresh before adoption")
            if head == epoch_id:
                return epoch_id
            chain, cursor = [], epoch
            while cursor["id"] != head:
                chain.append(cursor)
                if len(chain) > 1024:
                    raise ValueError("Slot ancestry exceeds adoption limit")
                parent_id = cursor["document"]["parent"]
                if parent_id is None:
                    if head is not None:
                        raise ValueError("Conflicting slot decision branch needs review")
                    break
                cursor = self.store._epoch(conn, parent_id)
            for decision in chain:
                issues = self.store._projection(conn, decision)[0].issues
                if {"late_parent_evidence", "normalization_schema_changed", "counter_without_reviewed_baseline"}.intersection(issues):
                    raise ValueError("Slot evidence needs review before adoption")
                # A second locally known child is an explicit conflict, even
                # when neither child has been adopted on this computer yet.
                parent = decision["document"]["parent"]
                siblings = conn.execute("SELECT id FROM slot_meter_epochs WHERE device_slot=? AND parent_id IS ?",
                    (slot, parent)).fetchall()
                if len(siblings) != 1:
                    raise ValueError("Conflicting slot decision branch needs review")
            if head is None and self.store._legacy_identity_conflict(conn, slot,
                    {item["document"]["baseline_event"]["payload"]["serial"] for item in chain}):
                raise ValueError("Historical slot identity needs migration review before adoption")
            identity = epoch["document"]["baseline_event"]["payload"]
            device = conn.execute("SELECT serial,enabled FROM devices WHERE slot=?", (slot,)).fetchone()
            if device != (identity["serial"], 1):
                raise ValueError("Apply the reviewed shared printer settings before adoption")
            conn.execute("INSERT INTO slot_meter_heads VALUES(?,?) ON CONFLICT(device_slot) DO UPDATE SET epoch_id=excluded.epoch_id",
                (slot, epoch_id))
            return epoch_id
