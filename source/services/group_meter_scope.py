"""Identify days whose meter opening is governed by an accepted group epoch."""

from datetime import date, datetime
import json


def group_epoch_covers_day(conn, slot: int, day: date) -> bool:
    row = conn.execute(
        """SELECT e.document_json FROM slot_meter_heads h
           JOIN slot_meter_epochs e ON e.id=h.epoch_id WHERE h.device_slot=?""",
        (slot,),
    ).fetchone()
    if row is None:
        return False
    epoch = json.loads(row[0])
    from services.shared_report_index import epoch_calendar
    calendar = epoch_calendar(conn, epoch)
    seen = set()
    while epoch["document"]["parent"] is not None:
        parent_id = epoch["document"]["parent"]
        if parent_id in seen:
            raise ValueError("Cyclic meter epoch")
        seen.add(parent_id)
        parent = conn.execute(
            "SELECT document_json FROM slot_meter_epochs WHERE id=?", (parent_id,)
        ).fetchone()
        if parent is None:
            raise ValueError("Missing reviewed parent epoch")
        epoch = json.loads(parent[0])
    baseline = datetime.fromisoformat(
        epoch["document"]["baseline_event"]["payload"]["observed_at"]
    ).astimezone(calendar)
    return day >= baseline.date()
