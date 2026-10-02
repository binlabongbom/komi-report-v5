"""Restartable bounded history transfer; transport and membership are injected.

Call at Agent/network startup or to resume interrupted work, never periodically
to poll settings. The caller first exchanges required reviewed epoch ancestry.
Neither this repository nor a broadcast response proves company membership.
"""
import hashlib
import json
import uuid

from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore, validate_event, _json, _text, MAX_PAGE_BYTES


def _cursor(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("Invalid catch-up cursor")
    return value


class WebCatchup:
    def __init__(self, *, authorize, path=None):
        if not callable(authorize):
            raise TypeError("Verified membership authorization is required")
        self.authorize = authorize
        self.store = SlotEpochStore(path)

    def _allowed(self, member, event=None):
        _text(member)
        # None requests authorization for this installation's company history;
        # each concrete event also requires its slot/serial/epoch authorization.
        if self.authorize(member, event) is not True:
            raise PermissionError("Member is not authorized for this history")

    @staticmethod
    def _stream(conn):
        conn.execute("INSERT OR IGNORE INTO web_observation_state VALUES('catchup_stream',?)", (uuid.uuid4().hex,))
        return conn.execute("SELECT value FROM web_observation_state WHERE key='catchup_stream'").fetchone()[0]

    @staticmethod
    def _saved(conn, member):
        row = conn.execute("SELECT state_json FROM web_catchup_progress WHERE peer_id=?", (member,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _save(conn, member, state):
        conn.execute("INSERT INTO web_catchup_progress VALUES(?,?) ON CONFLICT(peer_id) DO UPDATE SET state_json=excluded.state_json",
            (member, _json(state)))

    def progress(self, member):
        self._allowed(member)
        with self.store._connection() as conn:
            return self._saved(conn, member)

    def manifest(self, member, *, after=0):
        self._allowed(member)
        _cursor(after)
        with self.store._connection(write=True) as conn:
            stream = self._stream(conn)
            high = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM web_observations").fetchone()[0]
            anchor = conn.execute("SELECT event_id FROM web_observations WHERE sequence=?", (after,)).fetchone()
            return {"stream": stream, "through": high, "after": after, "anchor": anchor[0] if anchor else None}

    def begin(self, member, manifest):
        """Resume the unfinished snapshot, or pin new history on an explicit wake.

        An anchor mismatch detects sender reset/restore even if its stream token
        was restored from backup. Replaying from zero deduplicates existing data.
        """
        self._allowed(member)
        if not isinstance(manifest, dict) or set(manifest) != {"stream", "through", "after", "anchor"}:
            raise ValueError("Invalid history manifest")
        _text(manifest["stream"])
        _cursor(manifest["through"])
        _cursor(manifest["after"])
        if manifest["anchor"] is not None:
            _text(manifest["anchor"], 64)
        with self.store._connection(write=True) as conn:
            previous = self._saved(conn, member)
            if manifest["after"] != (previous["after"] if previous else 0):
                raise ValueError("History progress changed during handshake")
            matches = (previous is not None and previous["stream"] == manifest["stream"]
                and previous["anchor"] == manifest["anchor"] and previous["after"] <= manifest["through"])
            after = previous["after"] if matches else 0
            through = (previous["through"] if matches and not previous["complete"]
                       and previous["through"] <= manifest["through"] else manifest["through"])
            state = {"stream": manifest["stream"], "after": after, "through": through,
                "anchor": previous["anchor"] if matches else None, "complete": after == through, "last_page_hash": None}
            self._save(conn, member, state)
            return state

    def export_page(self, member, request, *, limit=32):
        self._allowed(member)
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("Invalid history page limit")
        after, through = _cursor(request["after"]), _cursor(request["through"])
        if after > through:
            raise ValueError("Invalid history snapshot")
        with self.store._connection() as conn:
            stream = conn.execute("SELECT value FROM web_observation_state WHERE key='catchup_stream'").fetchone()
            if stream is None or stream[0] != request["stream"]:
                raise ValueError("History stream changed; repeat handshake")
            high = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM web_observations").fetchone()[0]
            if through > high:
                raise ValueError("History snapshot was restored; repeat handshake")
            rows = conn.execute("SELECT sequence,event_id FROM web_observations WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
                (after, through, limit)).fetchall()
            items, size = [], 0
            for sequence, event_id in rows:
                event = self.store._event(conn, event_id)
                self._allowed(member, event)
                encoded = validate_event(event)
                length = len(encoded.encode("utf-8"))
                if items and size + length > MAX_PAGE_BYTES:
                    break
                items.append({"sequence": sequence, "event": event})
                size += length
            cursor = items[-1]["sequence"] if items else after
            if cursor < through and not items:
                raise ValueError("Missing history snapshot; repeat handshake")
            return {"stream": request["stream"], "after": after, "through": through,
                "next": cursor, "complete": cursor == through, "items": items}

    def receive_page(self, member, page):
        """Commit the entire authorized page and resume cursor in one transaction."""
        self._allowed(member)
        if not isinstance(page, dict) or set(page) != {"stream", "after", "through", "next", "complete", "items"}:
            raise ValueError("Invalid history page")
        _text(page["stream"])
        after, through, cursor = (_cursor(page[key]) for key in ("after", "through", "next"))
        if (not after <= cursor <= through or type(page["complete"]) is not bool
                or page["complete"] != (cursor == through)
                or not isinstance(page["items"], list) or len(page["items"]) > 128):
            raise ValueError("Invalid history page bounds")
        previous, documents, size = after, [], 0
        for item in page["items"]:
            if not isinstance(item, dict) or set(item) != {"sequence", "event"}:
                raise ValueError("Invalid history page item")
            sequence = _cursor(item["sequence"])
            if not previous < sequence <= cursor:
                raise ValueError("History page is not in source sequence order")
            document = validate_event(item["event"])
            self._allowed(member, item["event"])
            documents.append(document)
            size += len(document.encode("utf-8"))
            previous = sequence
        if size > MAX_PAGE_BYTES or previous != cursor or (not page["items"] and not page["complete"]):
            raise ValueError("History page is incomplete or oversized")
        digest = hashlib.sha256(_json(page).encode("utf-8")).hexdigest()
        with self.store._connection(write=True) as conn:
            state = self._saved(conn, member)
            if state is None or (state["stream"], state["through"]) != (page["stream"], through):
                raise ValueError("History page has no matching snapshot handshake")
            receipt = tuple(item["event"]["id"] for item in page["items"])
            if state["last_page_hash"] == digest and state["after"] == cursor:
                return receipt
            if state["after"] != after:
                raise ValueError("History page arrived out of order; resume from saved progress")
            for item, document in zip(page["items"], documents):
                WebObservationStore._insert(conn, item["event"], document)
            state.update(after=cursor, complete=page["complete"], last_page_hash=digest)
            if page["items"]:
                state["anchor"] = page["items"][-1]["event"]["id"]
            self._save(conn, member, state)
            return receipt
