"""Finish an interrupted new-slot setup using its unchanged first reading.

Only the Primary can repair this narrow case. A local setup revision must prove
the slot was newly added after shared baselines existed. Exactly one local Web
reading and zero-usage raw rows must agree. Legacy usage is never re-based.
"""
from datetime import datetime
import json

from services.peer_change_events import committed
from services.peer_settings_history import SettingsHistory
from services.reconciliation import reconcile_web_counters
from services.shared_settings_document import from_connection
from services.slot_epoch_store import SlotEpochStore
from services.slot_meter_continuity import counter_values

RECOVERY_ACTOR = "system:pending-setup"
_HISTORY = (("readings", "slot"), ("daily_meter_records", "device_slot"),
    ("daily_subject_records", "device_slot"), ("archived_subject_periods", "device_slot"),
    ("report_archive_days", "device_slot"), ("billing_ledger", "device_slot"))


def _added_locally_after_enrollment(conn, slot, serial, observed_at):
    head = SettingsHistory._state(conn, "head")
    node = SettingsHistory._state(conn, "node_id")
    visited = set()
    while head and head not in visited and len(visited) < 256:
        visited.add(head)
        doc = SettingsHistory._document(conn, head)
        devices = {d["slot"]: d["serial"] for d in doc["payload"]["devices"]}
        if devices.get(slot) != serial or len(doc["parents"]) != 1:
            return False
        parent = SettingsHistory._document(conn, doc["parents"][0])
        if slot not in {d["slot"] for d in parent["payload"]["devices"]}:
            return (doc["actor"] == node and doc["reason"] == "setup_settings_saved"
                    and bool(parent["payload"].get("slot_epochs"))
                    and datetime.fromisoformat(doc["created_at"]) <= observed_at)
        head = doc["parents"][0]
    return False


def pending_initial_review(store, conn, slot):
    """Return a proven repair preview, or None; never write while inspecting."""
    group = conn.execute("SELECT document FROM lan_peer_group WHERE singleton=1").fetchone()
    if not group:
        return None
    group = json.loads(group[0])
    if not group.get("primary_id") or group["primary_id"] != group.get("local_installation_id"):
        return None
    device = conn.execute("SELECT host,serial FROM devices WHERE slot=? AND enabled=1", (slot,)).fetchone()
    if not device or not device[1] or conn.execute(
        "SELECT 1 FROM slot_meter_epochs WHERE device_slot=? LIMIT 1", (slot,)
    ).fetchone():
        return None
    if any(conn.execute(f"SELECT 1 FROM {table} WHERE {key}=? LIMIT 1", (slot,)).fetchone()
           for table, key in _HISTORY):
        return None
    rows = conn.execute("SELECT event_id FROM web_observations WHERE device_slot=? ORDER BY sequence LIMIT 2", (slot,)).fetchall()
    if len(rows) != 1:
        return None
    event = store._event(conn, rows[0][0])
    p = event["payload"]
    reading = p["reading"]
    origin = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
    if (not origin or p["origin"] != origin[0] or p.get("meter_epoch_id")
            or (reading["host"], p["serial"]) != device
            or conn.execute("SELECT 1 FROM slot_meter_assignments WHERE event_id=?", (event["id"],)).fetchone()):
        return None
    if not _added_locally_after_enrollment(conn, slot, p["serial"], datetime.fromisoformat(p["observed_at"])):
        return None
    counter_values(event)
    counters = reading["counters"]
    if any(c["confidence"] != "verified" for c in counters):
        return None
    values = {c["canonical_field"]: c["count"] for c in counters if c["subject_type"] is None}
    if "counter.total.total" not in values or not reconcile_web_counters(values).billing_safe:
        return None
    raw = conn.execute("""SELECT canonical_field,source_path,subject_type,subject_id,opening_value,
        closing_value,delta_value,reset_count,sample_count,first_success,last_success,
        device_serial_snapshot,incomplete,counter_review_json,counter_resolutions_json
        FROM daily_raw_counter_records WHERE device_slot=?""", (slot,)).fetchall()
    expected = {(c["canonical_field"], c["source_path"], c["subject_type"] or "", c["subject_id"] or ""): c["count"]
                for c in counters}
    if len(raw) != len(expected):
        return None
    at = datetime.fromisoformat(p["observed_at"])
    for key, path, kind, subject, opening, closing, delta, resets, samples, first, last, serial, incomplete, issue, resolutions in raw:
        amount = expected.get((key, path, kind or "", subject or ""))
        if (amount is None or opening != amount or closing != amount or delta or resets or samples != 1
                or serial != p["serial"] or incomplete or json.loads(issue or "null")
                or json.loads(resolutions or "[]") or not first or not last
                or abs((datetime.fromisoformat(first) - at).total_seconds()) >= 1
                or abs((datetime.fromisoformat(last) - at).total_seconds()) >= 1):
            return None
    return store._preview(conn, slot, event["id"], "initial", RECOVERY_ACTOR,
        "กู้ฐานมิเตอร์ที่ขาดจากขั้นเพิ่มเครื่อง โดยใช้ผลอ่านครั้งแรกเดิมและยอดใช้งานศูนย์")


def recover_pending_slot_baselines(path):
    """Commit only missing metadata and its settings revision atomically."""
    store = SlotEpochStore(path)
    repaired = []
    with store._connection(write=True) as conn:
        reviews = []
        for (slot,) in conn.execute("SELECT slot FROM devices WHERE enabled=1 ORDER BY slot"):
            try:
                review = pending_initial_review(store, conn, slot)
            except (ValueError, KeyError, TypeError):
                # Ambiguous evidence remains blocked for explicit meter review.
                review = None
            if review:
                reviews.append(review)
        if reviews:
            history = SettingsHistory(path)
            before = from_connection(conn)
            head = history._state(conn, "head")
            if not head or history._document(conn, head)["payload"] != before:
                head = history._append(conn, before, [head] if head else [], "local_settings_baseline")
            for review in reviews:
                store._confirm(conn, review)
                repaired.append(review["slot"])
            revision = history._append(conn, from_connection(conn), [head], "pending_slot_baselines_recovered")
            conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                ("pending_slot_baselines_recovered", "", json.dumps({"slots": repaired, "revision": revision}),
                 datetime.now().astimezone().isoformat()))
    if repaired:
        committed(path)
    return tuple(repaired)
