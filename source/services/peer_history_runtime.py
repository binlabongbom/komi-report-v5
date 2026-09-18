"""Event-driven catch-up lifetime shared by Desktop and the lightweight Agent.

Only a verified membership/transport adapter may attach PeerHistorySession
objects. Discovery results and the legacy setup claim are not such an adapter.
With no attached sessions this owns no worker threads and sends no traffic.
All public methods run on the owning Qt thread; transport calls run off it.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from services.peer_history_session import PeerHistorySession


@dataclass
class _Member:
    session: PeerHistorySession
    cancelled: Event = field(default_factory=Event)
    future: object = None
    queued: bool = False
    wake_again: bool = False
    status: str = "waiting"
    error: str = ""
    after: int = 0
    through: int = 0
    last_success: str = ""


class PeerHistoryRuntime(QObject):
    changed = pyqtSignal()
    history_received = pyqtSignal(str, object)
    _finished = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._members = {}
        self._queue = deque()
        self._running = {}
        self._pool = None
        self._started = False
        self._stopped = False
        self._finished.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    def attach(self, session):
        """Attach a transport with independent, current authorization checks.

        Replacing/revoking a live session cancels it before its next commit.
        This call does not infer membership from its identifier or network IP.
        """
        if not isinstance(session, PeerHistorySession):
            raise TypeError("An authorized PeerHistorySession is required")
        if self._stopped:
            return
        member = session.member
        if not isinstance(member, str) or not member.strip() or len(member) > 256:
            raise ValueError("Invalid member identity")
        old = self._members.get(member)
        if old is not None and old.session is session:
            return  # Repeated readiness notification is not another catch-up.
        if old is not None:
            old.cancelled.set()
        state = self._members[member] = _Member(session)
        if self._started:
            self._enqueue(state)
            self._dispatch()
        self.changed.emit()

    def detach(self, member):
        state = self._members.pop(member, None)
        if state is not None:
            state.cancelled.set()
            self.changed.emit()

    def start(self):
        if self._started or self._stopped:
            return
        self._started = True
        self.network_recovered()

    def network_recovered(self):
        """Wake known sessions on an OS/verified-transport readiness event.

        No timer polls for membership or settings. Failed sessions remain
        pending until another explicit recovery/readiness/retry event.
        """
        if not self._started or self._stopped:
            return
        for state in self._members.values():
            if state.future is not None:
                state.wake_again = True  # Do not lose a reconnect during a call.
            else:
                self._enqueue(state)
        self._dispatch()

    def _enqueue(self, state):
        if not state.queued and not state.cancelled.is_set():
            state.queued = True
            state.status = "waiting"
            self._queue.append(state)

    def _dispatch(self):
        if self._stopped:
            return
        # One transfer at a time bounds memory and disk contention on the light
        # Agent; one session quantum then the next member prevents starvation.
        while self._queue and not self._running:
            state = self._queue.popleft()
            state.queued = False
            if state.cancelled.is_set():
                continue
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-peer-history")
            state.status, state.error = "receiving", ""
            future = self._pool.submit(state.session.run, cancelled=state.cancelled.is_set)
            state.future = future
            self._running[future] = state
            future.add_done_callback(lambda done, item=state: self._notify(item, done))
            self.changed.emit()

    def _notify(self, state, future):
        if self._stopped:
            return
        try:
            self._finished.emit(state, future)
        except RuntimeError:
            # The owning runtime must drain before releasing its process lock;
            # never touch a QObject already deleted during final application exit.
            pass

    def _complete(self, state, future):
        self._running.pop(future, None)
        state.future = None
        if self._stopped:
            return
        if state.cancelled.is_set() or self._members.get(state.session.member) is not state:
            self._dispatch()
            return
        again, state.wake_again = state.wake_again, False
        try:
            result = future.result()
        except Exception as error:
            state.status = "pending"
            state.error = ("unauthorized" if isinstance(error, PermissionError) else
                           "timeout" if isinstance(error, TimeoutError) else
                           "invalid_data" if isinstance(error, (ValueError, TypeError)) else "transport")
        else:
            state.status, state.after, state.through = result.status, result.after, result.through
            if result.status == "complete":
                state.last_success = datetime.now(UTC).isoformat(timespec="seconds")
            if result.observations:
                self.history_received.emit(state.session.member, result)
            # Continue only if a bounded quantum actually committed a page.
            # An oversized dependency must not cause an infinite busy loop.
            again = again or (result.status == "pending" and result.pages > 0)
        if again and not self._stopped and self._members.get(state.session.member) is state:
            self._enqueue(state)
        self.changed.emit()
        self._dispatch()

    def snapshot(self):
        return [{"member": member, "status": state.status, "error": state.error,
                 "after": state.after, "through": state.through,
                 "last_success": state.last_success}
                for member, state in sorted(self._members.items())]

    @property
    def busy(self):
        return bool(self._running or self._queue)

    def stop(self, *, wait=False):
        self._stopped = True
        self._queue.clear()
        for state in (*self._members.values(), *self._running.values()):
            state.cancelled.set()
        remaining = sum(not future.done() for future in self._running)
        for future in self._running:
            future.cancel()
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
        return remaining
