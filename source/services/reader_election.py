"""Demand-driven reader selection among independently verified members.

No heartbeat, membership inference or clock comparison. A live incumbent stays
in charge; simultaneous starts and partition healing use a stable member order.
This is availability-oriented election, not consensus: partitions may both read.
Transport calls must have bounded timeouts and authenticate the responder.
"""
from dataclasses import dataclass
from threading import RLock
from time import monotonic
import math
import uuid

from services.reader_jobs import ReadScope, VerifiedReader, _text


@dataclass(frozen=True)
class ReaderPresence:
    member_id: str
    boot_id: str
    scope: ReadScope
    ready: bool
    incumbent: bool


class ReaderUnavailable(ConnectionError):
    """No verified reachable member can currently own this Slot."""
    diagnostic_code = 'reader_unavailable'


class ReaderElection:
    def __init__(self, *, member_id, authorize, members, current_scope, ready, probe):
        _text(member_id)
        if not all(callable(value) for value in (authorize, members, current_scope, ready, probe)):
            raise TypeError("Verified membership, scope, readiness and transport providers are required")
        self.member_id = member_id
        self.authorize, self.members = authorize, members
        self.current_scope, self.ready, self.probe = current_scope, ready, probe
        self.boot_id = uuid.uuid4().hex
        self._lock = RLock()
        self._owners = {}
        self._partial = {}
        self._generation = 0

    def _authorize(self, member_id, scope):
        expected = scope.document()
        member = self.authorize(member_id, scope.slot)
        if (not isinstance(member, VerifiedReader) or member.member_id != member_id
                or member.scope.document() != expected
                or self.current_scope(scope.slot).document() != expected):
            raise PermissionError("Reader membership or shared Slot changed")
        return member

    def presence(self, requester, scope):
        """Authenticated endpoint: return local state only, never probe peers.

        Keeping this endpoint free of recursive elections avoids A waiting for
        B while B waits for A during simultaneous requests.
        """
        self._authorize(requester, scope)
        self._authorize(self.member_id, scope)
        is_ready = self.ready(scope.slot)
        if type(is_ready) is not bool:
            raise ValueError("Reader readiness must be boolean")
        with self._lock:
            owner = self._owners.get(scope.slot)
            incumbent = is_ready and owner == (scope.document(), self.member_id, self.boot_id)
        return ReaderPresence(self.member_id, self.boot_id, scope, is_ready, incumbent)

    def invalidate(self, slot=None):
        """Discard decisions on scope/lifecycle changes, without network work."""
        with self._lock:
            if slot is None:
                self._owners.clear()
                self._partial.clear()
            else:
                self._owners.pop(slot, None)
                self._partial.pop(slot, None)
            self._generation += 1

    def select(self, scope, *, cancelled=lambda: False, timeout=15, clock=monotonic):
        """Called only for a scheduled/manual request or explicit reconnect.

        Retry one transport failure immediately. Authorization/protocol errors
        are not retried or downgraded to offline. Never hold the state lock over
        network I/O. Transport authenticates the member, boot and full scope.
        """
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("Invalid reader selection timeout")
        deadline = clock() + timeout
        def check():
            if cancelled():
                from concurrent.futures import CancelledError
                raise CancelledError()
            return clock() < deadline
        self._authorize(self.member_id, scope)
        with self._lock:
            generation = self._generation
        candidates = set(self.members(scope.slot)) | {self.member_id}
        for member in candidates:
            _text(member)
        found, exhausted, unreachable = [], False, False
        # Observe this PC before spending the budget on offline members. A
        # large approved roster must not stop an available local collector.
        ordered = [self.member_id] + sorted(candidates - {self.member_id})
        for member in ordered:
            if not check():
                exhausted = True
                break
            self._authorize(member, scope)
            response = None
            for _ in range(2):
                if not check():
                    exhausted = True
                    break
                try:
                    response = (self.presence(self.member_id, scope) if member == self.member_id
                                else self.probe(member, scope))
                    break
                except (TimeoutError, ConnectionError):
                    pass
            self._authorize(member, scope)
            if response is None:
                unreachable = True
                continue
            if (not isinstance(response, ReaderPresence) or response.member_id != member
                    or response.scope.document() != scope.document()
                    or type(response.ready) is not bool or type(response.incumbent) is not bool
                    or (response.incumbent and not response.ready)):
                raise ValueError("Invalid authenticated reader presence")
            _text(response.boot_id)
            if response.ready:
                found.append(response)
        if cancelled():
            from concurrent.futures import CancelledError
            raise CancelledError()
        self._authorize(self.member_id, scope)
        if not found:
            self.invalidate(scope.slot)
            if exhausted:
                raise ReaderUnavailable("Reader selection time budget exhausted")
            raise ReaderUnavailable("No verified reader is ready")
        incumbents = [item for item in found if item.incumbent]
        chosen = min(incumbents or found, key=lambda item: item.member_id)
        self._authorize(chosen.member_id, scope)
        with self._lock:
            if generation != self._generation:
                raise ReaderUnavailable("Reader lifecycle changed during selection")
            self._owners[scope.slot] = (scope.document(), chosen.member_id, chosen.boot_id)
            self._partial[scope.slot] = exhausted or unreachable
        return chosen

    def partial(self, slot):
        """Status only: incomplete probing may mean partitioned coordination."""
        with self._lock:
            return self._partial.get(slot, False)

    def owns(self, scope):
        """Local fence, checked inside the durable grant transaction."""
        presence = self.presence(self.member_id, scope)
        return presence.ready and presence.incumbent

    def owner(self, scope):
        """Last decision for status display only; never a read permission."""
        with self._lock:
            owner = self._owners.get(scope.slot)
            return owner[1] if owner and owner[0] == scope.document() else None
