"""Route scheduled/manual requests to the selected durable reader authority.

Providers bind calls to an authenticated member. No live endpoint is installed
without that provider. Election is demand driven; a manual grant does not change
the scheduled owner. A reply identifies a job, not a new printer observation.
"""
from dataclasses import dataclass

from services.reader_jobs import ReadScope


class ReaderRedirect(ConnectionError):
    """The contacted member has converged to a different authority."""


@dataclass(frozen=True)
class RoutedRead:
    authority: str
    scope: ReadScope
    job: dict


class ReaderAuthority:
    def __init__(self, *, election, jobs):
        if jobs.authority_ready is None:
            raise ValueError("Durable reader jobs require an elected-authority fence")
        self.election, self.jobs = election, jobs

    def request(self, requester, request_id, scope, *, cancelled=lambda: False, probe_only=False):
        # Authenticate before discovery; an unauthorized caller must not trigger
        # network work or learn which other members are available.
        self.election._authorize(requester, scope)
        selected = self.election.select(scope, cancelled=cancelled)
        if selected.member_id != self.election.member_id:
            raise ReaderRedirect("Reader authority changed; resolve again")
        return self.jobs.request(requester, request_id, scope, probe_only=probe_only)

    def finish_probe(self, requester, job_id, scope, *, request_web):
        return self.jobs.finish_probe(requester, job_id, scope, request_web=request_web)

    def status(self, requester, job_id, scope):
        return self.jobs.status(requester, job_id, scope)

    def complete(self, requester, job_id, scope, *, event_id):
        return self.jobs.complete(requester, job_id, scope, event_id=event_id)

    def fail(self, requester, job_id, scope, *, reason):
        return self.jobs.fail(requester, job_id, scope, reason=reason)


class SharedReaderCoordinator:
    def __init__(self, *, election, endpoint):
        if not callable(endpoint):
            raise TypeError("Authenticated reader endpoint provider is required")
        self.election, self.endpoint = election, endpoint

    def request(self, scope, request_id, *, manual, cancelled=lambda: False, probe_only=False):
        if type(manual) is not bool:
            raise ValueError("Read request kind must be explicit")
        # Reuse the request ID on a lost reply; never turn it into a new job.
        # At most one redirect/transport retry; later recovery is a new runtime
        # event, not an unbounded retry loop or a settings polling timer.
        for attempt in range(2):
            selected = self.election.select(scope, cancelled=cancelled)
            if not manual and selected.member_id != self.election.member_id:
                return None
            self.election._authorize(selected.member_id, scope)
            try:
                result = self.endpoint(selected.member_id).request(
                    self.election.member_id, request_id, scope, cancelled=cancelled, probe_only=probe_only)
            except ReaderRedirect:
                if attempt:
                    raise
                continue
            except (TimeoutError, ConnectionError):
                # An ambiguous reply must be retried against the SAME authority.
                # Re-electing here could create another read while the first runs.
                result = self.endpoint(selected.member_id).request(
                    self.election.member_id, request_id, scope, cancelled=cancelled, probe_only=probe_only)
            self.election._authorize(selected.member_id, scope)
            return RoutedRead(selected.member_id, scope, result)
        raise ReaderRedirect("Reader selection did not stabilize")

    def status(self, read):
        self.election._authorize(read.authority, read.scope)
        result = self.endpoint(read.authority).status(self.election.member_id, read.job["job_id"], read.scope)
        self.election._authorize(read.authority, read.scope)
        return result
