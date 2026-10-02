"""Reviewed local baselines for exact Web counters, committed with their audit."""
from datetime import date, datetime
import hashlib
import json
import uuid

from database import _open


def _revision(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class RawCounterReviewStore:
    def load(self, slot: int, day: date) -> dict:
        with _open(commit=False) as conn:
            rows = conn.execute("""SELECT r.id,r.label,r.subject_name,r.subject_id,r.source_path
                FROM daily_raw_counter_records r JOIN devices d ON d.slot=r.device_slot
                WHERE r.device_slot=? AND r.record_date=? AND r.counter_review_json!='null'
                AND r.device_serial_snapshot=d.serial ORDER BY r.id""", (slot, day.isoformat())).fetchall()
        return {"counter_review": {str(row[0]): {} for row in rows}, "source": {"counter_sources": {
            str(row[0]): {"label": f"Raw · {row[1]} · {row[2] or row[3] or row[4]}"} for row in rows}}}

    @staticmethod
    def _candidate(conn, slot: int, day: date, key: str) -> tuple[dict, dict]:
        cursor = conn.execute("SELECT * FROM daily_raw_counter_records WHERE id=? AND device_slot=? AND record_date=?",
                              (key, slot, day.isoformat()))
        values = cursor.fetchone()
        if values is None:
            raise ValueError("Missing Web observation")
        row = dict(zip((column[0] for column in cursor.description), values))
        device = conn.execute("SELECT name,serial,host FROM devices WHERE slot=?", (slot,)).fetchone()
        if (not device or not device[1] or row["device_serial_snapshot"] != device[1]
                or not json.loads(row["counter_review_json"]) or not row["sample_count"]):
            raise ValueError("A pending serial-bound Web observation is required")
        if conn.execute("SELECT 1 FROM daily_meter_records WHERE device_slot=? AND record_date=?",
                        (slot, day.isoformat())).fetchone():
            raise ValueError("Finalized days require an amended-report workflow")
        return row, dict(zip(("name", "serial", "host"), device))

    def preview_counter_baseline(self, slot: int, day: date, key: str) -> dict:
        with _open(commit=False) as conn:
            row, identity = self._candidate(conn, slot, day, key)
        issue = json.loads(row["counter_review_json"])
        return {"revision": _revision(row), "device_identity": identity, "key": key,
                "label": f"Raw · {row['label']} · {row['subject_name'] or row['subject_id'] or row['source_path']}",
                "before": issue["before"], "detected_at": issue["at"], "baseline": row["closing_value"],
                "observed_at": row["last_success"], "preserved_delta": row["delta_value"]}

    def confirm_counter_baseline(self, slot: int, day: date, key: str, *,
                                 expected_revision: str, actor: str, reason: str,
                                 at: datetime | None = None) -> dict:
        stamp = at or datetime.now().astimezone()
        if stamp.date() != day or not actor.strip() or not reason.strip():
            raise ValueError("Resolution needs today's observation, actor and reason")
        with _open() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row, identity = self._candidate(conn, slot, day, key)
            if _revision(row) != expected_revision:
                raise ValueError("Counter changed after preview; review again")
            observed = datetime.fromisoformat(row["last_success"])
            if stamp.timestamp() < observed.timestamp():
                raise ValueError("Resolution cannot precede its observation")
            issue = json.loads(row["counter_review_json"])
            resolution = {"id": str(uuid.uuid4()), "key": key, "review_at": issue["at"],
                          "previous_counter": issue["before"], "baseline": row["closing_value"],
                          "observed_at": row["last_success"], "resolved_at": stamp.isoformat(),
                          "actor": actor.strip(), "reason": reason.strip(), "device_identity": identity,
                          "preserved_delta": row["delta_value"]}
            resolutions = json.loads(row["counter_resolutions_json"])
            resolutions.append(resolution)
            conn.execute("""UPDATE daily_raw_counter_records
                SET counter_review_json='null',counter_resolutions_json=?,updated_at=? WHERE id=?""",
                (json.dumps(resolutions, sort_keys=True, ensure_ascii=False), stamp.isoformat(), row["id"]))
        return resolution
