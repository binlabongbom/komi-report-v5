"""Bounded startup/reconnect catch-up through an authenticated peer transport.

The transport must implement manifest(after), page(request, limit) and
epoch(epoch_id), with bounded network timeouts. This module neither discovers
members nor establishes TLS trust. It must be invoked by an explicit startup,
reconnect or resume event, never a periodic settings poll.
"""
from dataclasses import dataclass
import threading

from services.slot_epoch_exchange import SlotEpochExchange
from services.slot_meter_continuity import _json
from services.web_catchup import WebCatchup
from services.web_observations import validate_event, MAX_PAGE_BYTES


class _BudgetReached(Exception):
    pass


class _Cancelled(Exception):
    pass


@dataclass(frozen=True)
class CatchupResult:
    status: str
    pages: int
    observations: int
    imported_epochs: int
    after: int
    through: int


class PeerHistorySession:
    def __init__(self, *, member, transport, authorize_session, authorize_event, authorize_epoch, path=None):
        if not callable(authorize_session):
            raise TypeError("Verified session authorization is required")
        self.member, self.transport = member, transport
        self.authorize_session = authorize_session
        self.history = WebCatchup(authorize=authorize_event, path=path)
        self.epochs = SlotEpochExchange(authorize=authorize_epoch, path=path)
        self._lock = threading.Lock()

    def _check(self, cancelled):
        if cancelled():
            raise _Cancelled()
        if self.authorize_session(self.member) is not True:
            raise PermissionError("Peer session is not currently authorized")

    def run(self, *, cancelled=lambda: False, max_pages=16, max_bytes=32 * 1024 * 1024,
            max_epochs=32, page_size=32):
        for value, maximum in ((max_pages, 128), (max_bytes, 128 * 1024 * 1024),
                               (max_epochs, 128), (page_size, 128)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid catch-up work budget")
        if not callable(cancelled):
            raise TypeError("Cancellation check is required")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("This peer catch-up session is already running")
        state = None
        pages = observations = imported = used = 0
        try:
            def spend(value):
                nonlocal used
                size = len(_json(value).encode("utf-8"))
                if used + size > max_bytes:
                    raise _BudgetReached()
                used += size

            def known(epoch_id):
                with self.epochs.store._connection() as conn:
                    return conn.execute("SELECT 1 FROM slot_meter_epochs WHERE id=?", (epoch_id,)).fetchone() is not None

            def ensure_epoch(epoch_id):
                nonlocal imported
                stack, seen = [], set()
                current = epoch_id
                while current and not known(current):
                    self._check(cancelled)
                    if current in seen or len(stack) >= 128:
                        raise ValueError("Invalid or excessively deep slot ancestry")
                    if imported + len(stack) >= max_epochs:
                        # Do not discard useful verified parents when a chain is
                        # too long. Explicitly require a larger bounded budget.
                        raise ValueError("Slot ancestry exceeds this session's epoch budget")
                    bundle = self.transport.epoch(current)
                    self._check(cancelled)
                    doc = self.epochs._validate(bundle)
                    if bundle["epoch"]["id"] != current:
                        raise ValueError("Peer returned a different requested slot epoch")
                    self.epochs._allowed(self.member, bundle["epoch"])
                    spend(bundle)
                    stack.append(bundle)
                    seen.add(current)
                    current = doc["parent"]
                for bundle in reversed(stack):
                    self._check(cancelled)
                    self.epochs.receive(self.member, bundle)
                    imported += 1

            self._check(cancelled)
            saved = self.history.progress(self.member)
            manifest = self.transport.manifest(after=saved["after"] if saved else 0)
            self._check(cancelled)
            state = self.history.begin(self.member, manifest)
            while not state["complete"] and pages < max_pages:
                self._check(cancelled)
                page = self.transport.page(state, limit=page_size)
                self._check(cancelled)
                # Validate the page before fetching dependencies or committing
                # unrelated facts from an invalid/replayed transport response.
                if (not isinstance(page, dict) or set(page) != {"stream", "after", "through", "next", "complete", "items"}
                        or type(page["after"]) is not int or type(page["through"]) is not int
                        or any(page.get(key) != state[key] for key in ("stream", "after", "through"))
                        or type(page["next"]) is not int or not state["after"] < page["next"] <= state["through"]
                        or type(page["complete"]) is not bool or page["complete"] != (page["next"] == state["through"])
                        or not isinstance(page["items"], list) or not 1 <= len(page["items"]) <= page_size):
                    raise ValueError("Invalid catch-up page from peer")
                previous, event_bytes, needed = state["after"], 0, []
                for item in page["items"]:
                    if (not isinstance(item, dict) or set(item) != {"sequence", "event"}
                            or type(item["sequence"]) is not int or not previous < item["sequence"] <= page["next"]):
                        raise ValueError("Invalid catch-up sequence from peer")
                    document = validate_event(item["event"])
                    self.history._allowed(self.member, item["event"])
                    event_bytes += len(document.encode("utf-8"))
                    epoch_id = item["event"]["payload"].get("meter_epoch_id")
                    if epoch_id and epoch_id not in needed:
                        needed.append(epoch_id)
                    previous = item["sequence"]
                if previous != page["next"] or event_bytes > MAX_PAGE_BYTES:
                    raise ValueError("Incomplete or oversized catch-up page")
                spend(page)
                for epoch_id in needed:
                    ensure_epoch(epoch_id)
                self._check(cancelled)
                receipt = self.history.receive_page(self.member, page)
                pages += 1
                observations += len(receipt)
                state = self.history.progress(self.member)
            status = "complete" if state["complete"] else "pending"
        except _BudgetReached:
            status = "pending"
        except _Cancelled:
            status = "cancelled"
        finally:
            self._lock.release()
        return CatchupResult(status, pages, observations, imported,
                             state["after"] if state else 0, state["through"] if state else 0)
