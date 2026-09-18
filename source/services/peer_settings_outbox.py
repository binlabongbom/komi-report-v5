"""Durable settings announcements and per-member delivery receipts.

This repository never discovers or authenticates a member. Its caller must use
the identity of an already authenticated member, not an arbitrary broadcast IP.
No network polling or automatic membership is introduced here.
"""
from datetime import UTC, datetime
from contextlib import closing
import math
import sqlite3

from database import get_db_path


def enqueue_revision(conn, revision, created_at):
    """Use the caller's transaction: revision, active values and event commit together."""
    conn.execute("INSERT OR IGNORE INTO peer_settings_events(revision,created_at) VALUES(?,?)",
                 (revision, created_at))


def _peer(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("An authenticated member identity is required")
    return value


def _now(value):
    stamp = datetime.now(UTC).timestamp() if value is None else value
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0:
        raise ValueError("Invalid local retry time")
    return stamp


class PeerSettingsOutbox:
    def __init__(self, path=None):
        self.path = path or get_db_path()

    def next_delivery(self, peer_id, *, now=None, reconnect=False):
        """Coalesce edits to the active head; its ancestry includes earlier edits.

        Reconnect may bypass the retry delay, but never an existing receipt.
        The current revision remains pending after reading it or restarting.
        """
        peer_id, stamp = _peer(peer_id), _now(now)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute("""SELECT e.revision,d.acknowledged_at,COALESCE(d.retry_at,0),COALESCE(d.attempts,0)
                FROM peer_settings_events e JOIN peer_settings_state s ON s.key='head' AND s.value=e.revision
                LEFT JOIN peer_settings_deliveries d ON d.revision=e.revision AND d.peer_id=?""", (peer_id,)).fetchone()
        if not row or row[1] is not None or (row[2] > stamp and not reconnect):
            return None
        return {"revision": row[0], "attempts": row[3]}

    def failed(self, peer_id, revision, *, error_code, now=None):
        peer_id, stamp = _peer(peer_id), _now(now)
        if error_code not in {"offline", "timeout", "tls", "unauthorized", "invalid_response", "transport"}:
            raise ValueError("Use a bounded delivery error code")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM peer_settings_events WHERE revision=?", (revision,)).fetchone():
                raise ValueError("Unknown outgoing settings revision")
            row = conn.execute("SELECT acknowledged_at,attempts FROM peer_settings_deliveries WHERE peer_id=? AND revision=?",
                               (peer_id, revision)).fetchone()
            if row and row[0] is not None:
                return  # A delayed failure must not undo a successful receipt.
            attempts = (row[1] if row else 0) + 1
            retry_at = stamp + min(300, 2 ** min(attempts, 9))
            conn.execute("""INSERT INTO peer_settings_deliveries(peer_id,revision,attempts,retry_at,error_code)
                VALUES(?,?,?,?,?) ON CONFLICT(peer_id,revision) DO UPDATE SET
                attempts=excluded.attempts,retry_at=excluded.retry_at,error_code=excluded.error_code""",
                (peer_id, revision, attempts, retry_at, error_code))

    def acknowledge(self, peer_id, revision, *, now=None):
        """Record verified receipt of a complete head and all its ancestors.

        Call only after the remote confirms durable import, not after an HTTP
        send or while pages are incomplete. Old receipts cannot acknowledge a
        newer change made during delivery.
        """
        from services.peer_settings_history import SettingsHistory
        peer_id, stamp = _peer(peer_id), _now(now)
        acknowledged = datetime.fromtimestamp(stamp, UTC).isoformat()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM peer_settings_events WHERE revision=?", (revision,)).fetchone():
                raise ValueError("Unknown outgoing settings revision")
            for ancestor in SettingsHistory._ancestors(conn, revision):
                if conn.execute("SELECT 1 FROM peer_settings_events WHERE revision=?", (ancestor,)).fetchone():
                    conn.execute("""INSERT INTO peer_settings_deliveries(peer_id,revision,acknowledged_at)
                        VALUES(?,?,?) ON CONFLICT(peer_id,revision) DO UPDATE SET
                        acknowledged_at=COALESCE(peer_settings_deliveries.acknowledged_at,excluded.acknowledged_at),
                        retry_at=0,error_code=''""", (peer_id, ancestor, acknowledged))
