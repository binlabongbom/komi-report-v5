"""Commit a reviewed slot baseline and its shared settings reference together."""
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path

from database import get_db_path
from services.peer_settings_history import SettingsHistory, _json
from services.shared_settings_document import from_connection
from services.slot_epoch_store import SlotEpochStore
from services.slot_meter_continuity import counter_key


class SharedSlotReviewService:
    def __init__(self, path=None):
        self.store = SlotEpochStore(path)

    def preview(self, slot, *, actor, reason):
        with self.store._connection() as conn:
            before = from_connection(conn)
            reviewed = self.store._review_latest(conn, slot, actor=actor, reason=reason)
            previous = self.store._epoch(conn, reviewed["expected_head"]) if reviewed["expected_head"] else None
            labels = {}
            for epoch in (previous, reviewed["epoch"]):
                if epoch:
                    for counter in epoch["document"]["baseline_event"]["payload"]["reading"]["counters"]:
                        subject = counter["subject_name"] or counter["subject_id"]
                        labels[counter_key(counter)] = (counter["label"] or counter["canonical_field"]) + (
                            f" · {subject} ({counter['subject_id']})" if subject else "")
            return {"review": reviewed, "settings_head": SettingsHistory._state(conn, "head"),
                "settings": before, "path": str(self.store.path),
                "counter_labels": labels,
                "previous_serial": previous["document"]["baseline_event"]["payload"]["serial"] if previous else None}

    def confirm(self, preview):
        if str(Path(get_db_path()).resolve()) != preview["path"] or preview["path"] != str(self.store.path):
            raise ValueError("Database changed after slot review")
        with self.store._connection(write=True) as conn:
            review = preview["review"]
            head = SettingsHistory._state(conn, "head")
            before = from_connection(conn)
            receipt_key = "slot_review:" + review["epoch"]["id"]
            receipt = conn.execute("SELECT new_value FROM config_log WHERE config_key=? ORDER BY id DESC LIMIT 1",
                                   (receipt_key,)).fetchone()
            if receipt:
                saved = json.loads(receipt[0])
                if saved["preview"] != preview:
                    raise ValueError("Slot review retry differs from confirmed request")
                if self.store._head(conn, review["slot"]) != review["epoch"]["id"]:
                    raise ValueError("Slot has changed since this review")
                return saved["revision"]
            if head != preview["settings_head"] or before != preview["settings"]:
                raise ValueError("Settings changed after slot review")
            # The epoch store rechecks identity, latest observation and parent maxima.
            self.store._confirm(conn, deepcopy(review))
            history = SettingsHistory()
            if not head or history._document(conn, head)["payload"] != before:
                head = history._append(conn, before, [head] if head else [], "local_settings_baseline")
            after = from_connection(conn)
            revision = history._append(conn, after, [head], "slot_baseline_reviewed")
            conn.execute("INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)",
                (receipt_key, head, _json({"preview": preview, "revision": revision}), datetime.now(UTC).isoformat()))
            return revision
