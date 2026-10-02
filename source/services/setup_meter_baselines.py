"""Review new-slot Web evidence and commit it inside the setup transaction.

Legacy history is never re-based merely because it predates reviewed epochs.
No printer reads, schema changes or writes occur while classifying/preparing.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import uuid

from database import get_db_path
from komi_snmp_profiler.models import Confidence, MeterReading
from services.reconciliation import reconcile_web_counters
from services.slot_epoch_store import SlotEpochStore
from services.slot_meter_continuity import counter_values, reviewed_epoch
from services.web_observations import WebObservationStore, _json, validate_event

MAX_READING_AGE_SECONDS = 30 * 60
_PENDING_ISSUES = {"normalization_schema_changed", "counter_without_reviewed_baseline",
                   "late_parent_evidence", "competing_epoch_decisions"}
_HISTORY_TABLES = (("readings", "slot"),
    ("daily_meter_records", "device_slot"), ("daily_raw_counter_records", "device_slot"),
    ("daily_subject_records", "device_slot"), ("archived_subject_periods", "device_slot"),
    ("report_archive_days", "device_slot"), ("billing_ledger", "device_slot"),
    ("web_observations", "device_slot"))


def _device_key(device):
    # Only the connection/physical identity matters. A label can be edited after
    # testing. Credentials only enter this digest, never observations/audit logs.
    values = [device.slot, device.host.strip(), device.serial.strip(), device.username,
              device.password, device.tls_mode, device.tls_fingerprint, bool(device.enabled)]
    return hashlib.sha256(_json(values).encode("utf-8")).hexdigest()


def _validate_reading(device, reading, *, now=None):
    if not isinstance(reading, MeterReading) or reading.host != device.host.strip() or not device.serial.strip():
        raise ValueError(f"Slot {device.slot + 1}: ผลอ่านต้องตรงกับ IP และ Serial ของเครื่องที่เลือก")
    stamp = datetime.fromisoformat(reading.collected_at)
    if stamp.tzinfo is None:
        raise ValueError("ผลอ่านมิเตอร์ไม่มีเขตเวลา")
    age = ((now or datetime.now(UTC)) - stamp).total_seconds()
    if age < -60 or age > MAX_READING_AGE_SECONDS:
        raise ValueError(f"Slot {device.slot + 1}: ผลอ่านมิเตอร์เกิน 30 นาทีหรือเวลาไม่ถูกต้อง กรุณาทดสอบเครื่องอีกครั้ง")
    counters = [item for item in reading.counters if item.canonical_field.startswith("counter.")]
    if not counters or any(item.confidence != Confidence.VERIFIED for item in counters):
        raise ValueError(f"Slot {device.slot + 1}: Counter ยังไม่ได้ยืนยัน จึงใช้เป็นฐานมิเตอร์ไม่ได้")
    values = {item.canonical_field: item.count for item in counters if item.subject_type is None}
    if "counter.total.total" not in values or not reconcile_web_counters(values).billing_safe:
        raise ValueError(f"Slot {device.slot + 1}: มิเตอร์แยกประเภทไม่ครบหรือผลรวมไม่ตรง จึงใช้เป็นฐานไม่ได้")


@dataclass(frozen=True)
class BaselineRequirement:
    slot: int
    operation: str
    reason: str

    @property
    def requires_confirmation(self):
        return self.operation in {"initial", "replacement"}


@dataclass(frozen=True)
class ReadingEvidence:
    reading: MeterReading
    device_key: str
    read_id: str
    captured_at: str


@dataclass(frozen=True)
class BaselineEntry:
    slot: int
    operation: str
    evidence: ReadingEvidence
    event_json: str
    epoch_json: str
    expected_json: str


@dataclass(frozen=True)
class BaselinePlan:
    database_path: str
    entries: tuple[BaselineEntry, ...]
    slot_epochs: tuple[tuple[int, str], ...]
    devices: tuple


class SetupMeterBaselines:
    def __init__(self, path=None):
        self.path = Path(path or get_db_path()).resolve()
        self.store = SlotEpochStore(self.path)

    @staticmethod
    def capture(device, reading):
        _validate_reading(device, reading)
        return ReadingEvidence(reading, _device_key(device), str(uuid.uuid4()), datetime.now(UTC).isoformat())

    @staticmethod
    def validate_evidence(device, evidence):
        if not isinstance(evidence, ReadingEvidence) or evidence.device_key != _device_key(device):
            raise ValueError(f"Slot {device.slot + 1}: การเชื่อมต่อเปลี่ยนหลังอ่านมิเตอร์ กรุณาทดสอบเครื่องอีกครั้ง")
        _validate_reading(device, evidence.reading)

    @staticmethod
    def _has_history(conn, slot):
        # A legacy daily runtime-cache may not have been finalized to SQL yet.
        # SNMP last_total alone is deliberately not history: a newly added
        # printer can have an SNMP total but no successful Web read.
        row = conn.execute("SELECT last_success_at FROM devices WHERE slot=?", (slot,)).fetchone()
        if row and row[0]:
            return True
        # Prefer compact, indexed legacy tables before inspecting the journal.
        return any(conn.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (slot,)).fetchone()
                   for table, column in _HISTORY_TABLES)

    def _classify(self, conn, device):
        head = self.store._head(conn, device.slot)
        if head:
            previous = self.store._epoch(conn, head)["document"]["baseline_event"]["payload"]["serial"]
            if previous == device.serial.strip():
                return BaselineRequirement(device.slot, "preserve", "ใช้ฐานมิเตอร์เดิม")
            return BaselineRequirement(device.slot, "replacement", "เปลี่ยนเครื่อง: ยืนยันฐานใหม่และรักษายอดเครื่องเดิม")
        if conn.execute("SELECT 1 FROM slot_meter_epochs WHERE device_slot=? LIMIT 1", (device.slot,)).fetchone():
            raise ValueError(f"Slot {device.slot + 1}: มีฐานมิเตอร์เดิมแต่ไม่มีฐานที่ใช้งานอยู่ ไม่สร้างฐานทับประวัติ")
        if self._has_history(conn, device.slot):
            old = conn.execute("SELECT serial FROM devices WHERE slot=?", (device.slot,)).fetchone()
            if old and old[0] and device.serial and old[0] != device.serial:
                raise ValueError(f"Slot {device.slot + 1}: เครื่องเดิมมีประวัติรุ่นเก่า ต้องตรวจการเปลี่ยนเครื่องโดยรักษาฐานเก่าก่อน")
            return BaselineRequirement(device.slot, "legacy", "ใช้ประวัติและฐานเดิมจากรุ่นก่อน ไม่เริ่มนับใหม่")
        return BaselineRequirement(device.slot, "initial", "เครื่องใหม่: ยืนยันมิเตอร์เริ่มต้นก่อนเริ่มนับการใช้งาน")

    def classify(self, devices):
        with self.store._connection() as conn:
            return tuple(self._classify(conn, device) for device in devices if device.enabled)

    def _state(self, conn, slot):
        head = self.store._head(conn, slot)
        version = conn.execute("SELECT version,issues_json FROM slot_meter_epoch_state WHERE epoch_id=?", (head,)).fetchone() if head else None
        latest = conn.execute("SELECT MAX(sequence) FROM web_observations WHERE device_slot=?", (slot,)).fetchone()[0]
        return {"head": head, "version": version, "latest": latest, "history": self._has_history(conn, slot)}

    def prepare(self, devices, evidence_by_slot, confirmed_slots, *, actor="setup_wizard"):
        devices = tuple(device for device in devices if device.enabled)
        entries = []
        with self.store._connection() as conn:
            origin_row = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
            origin = origin_row[0] if origin_row else str(uuid.uuid4())
            epochs = dict(conn.execute("SELECT device_slot,epoch_id FROM slot_meter_heads"))
            for device in devices:
                requirement = self._classify(conn, device)
                if not requirement.requires_confirmation:
                    continue
                evidence = evidence_by_slot.get(device.slot)
                if device.slot not in confirmed_slots or not isinstance(evidence, ReadingEvidence):
                    raise ValueError(f"Slot {device.slot + 1}: ต้องอ่านและยืนยันตารางมิเตอร์เริ่มต้นก่อนบันทึก")
                self.validate_evidence(device, evidence)
                reading = evidence.reading.to_dict()
                reading.update(counters=list(reading["counters"]), warnings=list(reading["warnings"]))
                payload = {"format": "komi.web.observation.v1", "origin": origin,
                    "read_id": evidence.read_id, "slot": device.slot, "serial": device.serial,
                    "printer_name": device.name.strip(), "observed_at": datetime.fromisoformat(evidence.reading.collected_at).isoformat(),
                    "reading": reading}
                event = {"id": hashlib.sha256(_json(payload).encode("utf-8")).hexdigest(), "payload": payload}
                validate_event(event)
                counter_values(event)
                parent, proof = None, ()
                if requirement.operation == "replacement":
                    parent = self.store._epoch(conn, epochs[device.slot])
                    projection, proof = self.store._projection(conn, parent)
                    if _PENDING_ISSUES.intersection(projection.issues):
                        raise ValueError(f"Slot {device.slot + 1}: ฐานเดิมมีหลักฐานค้างตรวจ ไม่เปลี่ยนฐานจนกว่าจะยืนยันหลักฐานเดิม")
                epoch = reviewed_epoch(event, parent=parent, parent_observations=proof,
                    operation=requirement.operation, actor=actor,
                    reason="ผู้ใช้ตรวจและยืนยันตารางมิเตอร์เริ่มต้นใน Wizard")
                entries.append(BaselineEntry(device.slot, requirement.operation, evidence,
                    _json(event), _json(epoch), _json(self._state(conn, device.slot))))
                epochs[device.slot] = epoch["id"]
        return BaselinePlan(str(self.path), tuple(entries), tuple(sorted(epochs.items())), devices)

    def validate_devices(self, plan, devices):
        if plan.database_path != str(self.path):
            raise ValueError("ฐานข้อมูลเปลี่ยนหลังตรวจมิเตอร์เริ่มต้น")
        current = {device.slot: _device_key(device) for device in devices if device.enabled}
        if current != {device.slot: _device_key(device) for device in plan.devices}:
            raise ValueError("การเชื่อมต่อเครื่องพิมพ์เปลี่ยนหลังตรวจมิเตอร์เริ่มต้น")

    def check_current(self, conn, plan):
        """Before setup writes, reject a read or epoch change after review."""
        self.validate_devices(plan, plan.devices)
        for entry in plan.entries:
            if _json(self._state(conn, entry.slot)) != entry.expected_json:
                raise ValueError(f"Slot {entry.slot + 1}: มีผลอ่านหรือฐานมิเตอร์ใหม่หลังตรวจ กรุณาตรวจตารางอีกครั้ง")
            device = next(item for item in plan.devices if item.slot == entry.slot)
            _validate_reading(device, entry.evidence.reading)

    def apply(self, conn, plan):
        """After device writes, add evidence/epochs/outboxes without committing."""
        self.validate_devices(plan, plan.devices)
        for entry in plan.entries:
            event, epoch = json.loads(entry.event_json), json.loads(entry.epoch_json)
            p = event["payload"]
            device = next(item for item in plan.devices if item.slot == entry.slot)
            _validate_reading(device, entry.evidence.reading)
            row = conn.execute("SELECT host,serial,username,tls_mode,tls_fingerprint,enabled FROM devices WHERE slot=?", (entry.slot,)).fetchone()
            expected = (device.host.strip(), device.serial, device.username, device.tls_mode, device.tls_fingerprint, int(device.enabled))
            if row != expected:
                raise ValueError("เครื่องพิมพ์ที่บันทึกไม่ตรงกับผลอ่านมิเตอร์")
            saved = WebObservationStore(self.path).record_in_transaction(conn, entry.slot,
                entry.evidence.reading, serial=p["serial"], printer_name=p["printer_name"],
                at=datetime.fromisoformat(p["observed_at"]), read_id=p["read_id"], origin=p["origin"])
            if saved != event:
                raise ValueError("ผลอ่านมิเตอร์เปลี่ยนหลังยืนยัน")
            review = self.store._preview(conn, entry.slot, event["id"], entry.operation,
                epoch["document"]["actor"], epoch["document"]["reason"])
            if review["epoch"] != epoch:
                raise ValueError("หลักฐานฐานมิเตอร์เดิมเปลี่ยนหลังยืนยัน")
            self.store._confirm(conn, review)
