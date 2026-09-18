"""Read-only queue/conflict status; no membership discovery or cold-file reads."""
from contextlib import closing
import sqlite3
from pathlib import Path
from time import monotonic


def load_network_activity(path, members):
    if not isinstance(members, list) or len(members) > 100:
        raise ValueError("Choose at most 100 members per status page")
    if any(not isinstance(member, str) or not member.strip() or len(member) > 256 for member in members):
        raise ValueError("Invalid member identity")
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        deadline = monotonic() + 3
        conn.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        head = conn.execute("SELECT value FROM peer_settings_state WHERE key='head'").fetchone()
        # Incoming revisions already included in the current ancestry are not
        # conflicts merely because the old review marker still exists.
        from services.peer_settings_history import SettingsHistory
        reviews = {row[0] for row in conn.execute("SELECT value FROM peer_settings_state WHERE key LIKE 'review:%'")}
        ancestors = SettingsHistory._ancestors(conn, head[0] if head else None) if reviews else set()
        slot_reviews = [row[0] + 1 for row in conn.execute("""SELECT h.device_slot FROM slot_meter_heads h
            JOIN slot_meter_epoch_state s ON s.epoch_id=h.epoch_id WHERE s.issues_json!='[]'
            ORDER BY h.device_slot""")]
        queues = {}
        outgoing = conn.execute("SELECT COUNT(*) FROM web_observation_outbox").fetchone()[0]
        for member in members:
            acknowledged = conn.execute("""SELECT COUNT(*) FROM web_observation_receipts r
                JOIN web_observation_outbox o ON o.event_id=r.event_id
                WHERE r.peer_id=?""", (member,)).fetchone()[0]
            pending_settings = conn.execute("""SELECT COUNT(*) FROM peer_settings_events e
                JOIN peer_settings_state s ON s.key='head' AND s.value=e.revision
                WHERE NOT EXISTS(SELECT 1 FROM peer_settings_deliveries d
                    WHERE d.peer_id=? AND d.revision=e.revision AND d.acknowledged_at IS NOT NULL)""",
                (member,)).fetchone()[0]
            pending_amendments = conn.execute('''SELECT COUNT(*) FROM peer_billing_amendments a
                WHERE NOT EXISTS(SELECT 1 FROM peer_billing_deliveries d WHERE d.member_id=?
                    AND d.amendment_id=a.amendment_id AND d.acknowledged_at IS NOT NULL)''', (member,)).fetchone()[0]
            queues[member] = {"web_pending": outgoing - acknowledged, "settings_pending": bool(pending_settings),
                              "amendments_pending": pending_amendments}
    return {"queues": queues, "settings_reviews": len(reviews - ancestors), "slot_reviews": slot_reviews}
