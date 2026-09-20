"""One authenticated data/reader service for the current Desktop or Agent owner.

The access object is supplied by enrollment, never by a discovery packet. Its
methods recheck current authorization inside repository transactions. This
assembly deliberately does not create membership or choose a company.
"""
from pathlib import Path
from threading import Event, RLock, Thread

from services.peer_billing_amendments import PeerBillingAmendments
from services.peer_contacts import PeerContactExchange, PeerContactPull
from services.peer_delivery import PeerSyncSession, PeerWebDelivery
from services.peer_https import PeerDataEndpoint, PeerHTTPSServer
from services.peer_settings_transfer import PeerSettingsTransfer
from services.reader_election import ReaderElection
from services.reader_jobs import ReaderJobs
from services.shared_reader import ReaderAuthority, SharedReaderCoordinator
from services.shared_web_read import SharedWebRead
from services.slot_epoch_exchange import SlotEpochExchange
from services.web_catchup import WebCatchup
from services.web_observations import WebObservationStore


class PeerNetworkNode:
    """Compose existing services; hold no Qt widgets and run no periodic poll.

    Client factories must return authenticated PeerHTTPSClient-compatible
    transports. They may cache TLS contexts, but certificate authorization must
    remain live. ``ready`` is the existing registration/collection gate.
    """
    def __init__(self, *, access, client_for, ready, on_wake=None, on_data=None):
        methods = ('authorize_session', 'authorize_event', 'authorize_epoch',
                   'authorize_settings', 'authorize_amendment', 'authorize_reader',
                   'current_scope', 'members', 'resolve_certificate')
        if (not all(callable(getattr(access, name, None)) for name in methods)
                or not callable(client_for) or not callable(ready)
                or not isinstance(access.member_id, str) or not access.member_id.strip()):
            raise TypeError('Current membership, scoped authorization and transport are required')
        self.access, self.client_for, self.ready = access, client_for, ready
        self.path = Path(access.path).resolve()
        self.member_id = access.member_id
        self.on_wake = on_wake
        self.on_data = on_data
        self._wake_ids = set()
        self._stopped = Event()
        self._server = self._thread = None
        self._lock = RLock()
        self.authorize_session = self._guard('authorize_session')
        self.authorize_event = self._guard('authorize_event')
        self.authorize_epoch = self._guard('authorize_epoch')
        self.authorize_settings = self._guard('authorize_settings')
        self.authorize_amendment = self._guard('authorize_amendment')
        self.contacts = PeerContactExchange(access=access, authorize=self.authorize_session)
        self.election = ReaderElection(member_id=self.member_id,
            authorize=self.authorize_reader, current_scope=self.current_scope,
            members=access.members, ready=self._ready, probe=self._probe)
        self.jobs = ReaderJobs(authorize=self.authorize_reader, current_scope=self.current_scope,
            path=self.path, authority_ready=self.election.owns)
        self.authority = ReaderAuthority(election=self.election, jobs=self.jobs)
        self.data = PeerDataEndpoint(history=WebCatchup(authorize=self.authorize_event, path=self.path),
            epochs=SlotEpochExchange(authorize=self.authorize_epoch, path=self.path),
            amendments=PeerBillingAmendments(authorize=self.authorize_amendment, path=self.path),
            settings=PeerSettingsTransfer(authorize=self.authorize_settings, path=self.path),
            web=PeerWebDelivery(authorize=self.authorize_event, path=self.path), reader=self.authority)
        self.router = SharedReaderCoordinator(election=self.election, endpoint=self.reader)
        self.shared_reads = SharedWebRead(router=self.router, current_scope=self.current_scope,
            observations=WebObservationStore(self.path), publish=self._publish, fetch=self._fetch)

    def _guard(self, name):
        def allowed(*args):
            return not self._stopped.is_set() and getattr(self.access, name)(*args) is True
        return allowed

    def _ready(self, slot):
        return not self._stopped.is_set() and self.ready(slot) is True

    def authorize_reader(self, member, slot):
        if self._stopped.is_set():
            raise PermissionError('Peer runtime is stopping')
        return self.access.authorize_reader(member, slot)

    def current_scope(self, slot):
        if self._stopped.is_set():
            raise PermissionError('Peer runtime is stopping')
        return self.access.current_scope(slot)

    def resolve_certificate(self, fingerprint):
        if self._stopped.is_set():
            return None
        member = self.access.resolve_certificate(fingerprint)
        return member if member and self.authorize_session(member) else None

    def dispatch(self, member, operation, data):
        if not self.authorize_session(member):
            raise PermissionError('Peer session is not authorized')
        if operation in {'peer.contacts', 'peer.origins'}:
            if set(data) != {'after', 'limit'}:
                raise ValueError('Invalid contact request')
            return self.contacts.page(member, **data, historical=operation == 'peer.origins')
        if operation == 'peer.wake':
            value = data.get('boot_id')
            if (set(data) != {'boot_id'} or not isinstance(value, str) or len(value) != 32
                    or any(c not in '0123456789abcdef' for c in value)):
                raise ValueError('Invalid peer boot identity')
            with self._lock:
                key = (member, value)
                if key not in self._wake_ids:
                    if len(self._wake_ids) >= 4096:
                        self._wake_ids.clear()  # bounded cache, not a member limit
                    self._wake_ids.add(key)
                    if self.on_wake is not None:
                        self.on_wake(member)
            return {'accepted': True}
        result = self.data(member, operation, data)
        if not self.authorize_session(member):
            raise PermissionError('Peer session changed during request')
        if operation in {'web.receive', 'reader.publish', 'epoch.receive'} and self.on_data is not None:
            try:
                self.on_data()
            except RuntimeError:
                pass  # A destroyed UI cannot undo a committed receipt.
        return result

    def session(self, member):
        if member == self.member_id or not self.authorize_session(member):
            raise PermissionError('Cannot attach an unverified or local peer')
        transport = self.client_for(member)
        return PeerSyncSession(member=member, transport=transport, path=self.path,
            boot_id=self.election.boot_id,
            contacts=PeerContactPull(exchange=self.contacts, member=member, transport=transport),
            authorize_session=self.authorize_session, authorize_event=self.authorize_event,
            authorize_epoch=self.authorize_epoch, authorize_settings=self.authorize_settings,
            authorize_amendment=self.authorize_amendment)

    def reader(self, member):
        if not self.authorize_session(member):
            raise PermissionError('Reader endpoint is not authorized')
        if member == self.member_id:
            return self.authority
        # Do not retain an endpoint after certificate/address renewal. The
        # enrollment adapter owns transport caching and live trust decisions.
        return self.client_for(member).reader_endpoint(self.member_id)

    def _probe(self, member, scope, timeout=2):
        transport = self.client_for(member)
        # Factories own immutable/cached clients; do not mutate a timeout shared
        # with sync traffic. Presence uses a separate bounded transport instance.
        from services.peer_https import PeerHTTPSClient
        if isinstance(transport, PeerHTTPSClient):
            transport = PeerHTTPSClient(
                f'https://{transport.host}:{transport.port}', member=member,
                context=transport.context, authorize_certificate=transport.authorize,
                timeout=min(timeout, transport.timeout))
        return transport.reader_endpoint(self.member_id).presence(self.member_id, scope)

    def _publish(self, member, event, scope):
        receipt = self.client_for(member).reader_endpoint(self.member_id).publish(event, scope)
        if receipt != {'event_id': event['id'], 'committed': True}:
            raise ValueError('Authority did not commit the Web result')
        return (event['id'],)

    def _fetch(self, member, event_id, scope):
        if member == self.member_id:
            return self.data._fetch(self.member_id, scope, event_id)
        return self.client_for(member).reader_endpoint(self.member_id).fetch(event_id, scope)

    def start(self, address, *, context):
        """Bind once; address and TLS identity come from the enrolled instance."""
        with self._lock:
            if self._stopped.is_set():
                raise RuntimeError('A stopped peer runtime cannot be restarted')
            if self._server is None:
                server = PeerHTTPSServer(address, context=context,
                    resolve_member=self.resolve_certificate, dispatch=self.dispatch)
                thread = Thread(target=server.serve_forever,
                    kwargs={'poll_interval': .05}, name='komi-peer-https', daemon=True)
                try:
                    thread.start()
                except BaseException:
                    server.server_close()
                    raise
                self._server, self._thread = server, thread
            return self._server.server_address

    def stop(self, *, wait=False):
        # Fence access before stopping accepts. Work already in a transaction
        # rechecks this fence before commit; ownership cannot move early.
        self._stopped.set()
        self.election.invalidate()
        with self._lock:
            if self._server is None:
                return 0
            if self._thread.is_alive():
                self._server.shutdown()
                self._server.server_close()
                self._thread.join()
            if wait:
                self._server.wait_requests()
            return self._server.active_requests
