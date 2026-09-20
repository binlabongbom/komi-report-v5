"""Send committed local work to verified peers, with bounded event-driven work.

Transport and scope authorizers are supplied by the membership adapter. These
services never turn a discovery response into membership or start a listener.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from threading import Lock

from services.peer_history_session import PeerHistorySession
from services.peer_settings_transfer import PeerSettingsTransfer
from services.peer_billing_amendments import PeerBillingAmendments
from services.web_catchup import WebCatchup
from services.web_observations import WebObservationStore, validate_event, MAX_PAGE_BYTES


class PeerWebDelivery:
    def __init__(self, *, authorize, path=None):
        self.history = WebCatchup(authorize=authorize, path=path)
        self.observations = WebObservationStore(path)

    def receive(self, member, events):
        self.history._allowed(member)
        if not isinstance(events, list) or not 1 <= len(events) <= 128:
            raise ValueError('Invalid Web delivery count')
        documents = [validate_event(event) for event in events]
        if sum(len(document.encode('utf-8')) for document in documents) > MAX_PAGE_BYTES:
            raise ValueError('Oversized Web delivery')
        with self.history.store._connection(write=True) as conn:
            for event, document in zip(events, documents):
                self.history._allowed(member, event)
                WebObservationStore._insert(conn, event, document)
            for event in events:
                self.history._allowed(member, event)
        return {'event_ids': [event['id'] for event in events], 'committed': True}


@dataclass(frozen=True)
class SyncResult:
    status: str
    pages: int
    observations: int
    imported_epochs: int
    after: int
    through: int
    sent: int
    more_work: bool
    errors: tuple


class PeerSyncSession(PeerHistorySession):
    """The Agent's existing runtime can attach this session once authenticated.

    Receive missing history, send local settings/Web/decisions, and continue only
    while a bounded quantum made progress. Failure in one outgoing queue does
    not block another queue. No local clock wins a settings conflict.
    """
    def __init__(self, *, authorize_settings, authorize_amendment, boot_id=None, contacts=None, **kwargs):
        super().__init__(**kwargs)
        path = self.history.store.path
        self.settings = PeerSettingsTransfer(authorize=authorize_settings, path=path)
        self.amendments = PeerBillingAmendments(authorize=authorize_amendment, path=path)
        self.web = PeerWebDelivery(authorize=kwargs['authorize_event'], path=path)
        self._reconnect = True
        self._amendment_cursor = None
        self._delivery_lock = Lock()
        self._state_lock = Lock()
        self.boot_id = boot_id
        self._wake_id = boot_id
        self._announced = False
        self.contacts = contacts

    def reconnected(self, *, announce=True):
        with self._state_lock:
            self._reconnect = True
            if announce and self.boot_id is not None:
                import uuid
                self._wake_id = uuid.uuid4().hex
                self._announced = False

    def run(self, *, cancelled=lambda: False, **budgets):
        if not self._delivery_lock.acquire(blocking=False):
            raise RuntimeError('This peer synchronization session is already running')
        try:
            return self._run(cancelled=cancelled, **budgets)
        except Exception:
            # A failed startup/manifest must not consume the obligation to
            # recheck receipts on the next bounded retry.
            with self._state_lock:
                self._reconnect = True
            raise
        finally:
            self._delivery_lock.release()

    def _run(self, *, cancelled, **budgets):
        with self._state_lock:
            announce = self.boot_id is not None and not self._announced
            wake_id = self._wake_id
            reconnect, self._reconnect = self._reconnect, False
        if announce:
            if cancelled():
                raise CancelledError()
            if self.authorize_session(self.member) is not True:
                raise PermissionError('Peer session is no longer authorized')
            receipt = self.transport.wake(wake_id)
            if receipt != {'accepted': True} or self.authorize_session(self.member) is not True:
                raise PermissionError('Peer did not authorize the startup notification')
            with self._state_lock:
                if self._wake_id == wake_id:
                    self._announced = True
        if reconnect:
            self._amendment_cursor = 0
            if self.contacts is not None:
                self.contacts.reset()
        if self.contacts is not None and self.contacts.run(cancelled=cancelled):
            return SyncResult('pending', 0, 0, 0, 0, 0, 0, True, ())
        received = super().run(cancelled=cancelled, **budgets)
        if received.status == 'cancelled':
            return received
        sent, errors = 0, []
        more = received.status == 'pending' and received.pages > 0
        pushed = set()
        def check():
            if cancelled():
                raise CancelledError()
            if self.authorize_session(self.member) is not True:
                raise PermissionError('Peer session is no longer authorized')
        def push_epoch(epoch_id):
            chain, current = [], epoch_id
            while current and current not in pushed:
                check()
                if len(chain) + len(pushed) >= 128 or current in {b['epoch']['id'] for b in chain}:
                    raise ValueError('Slot ancestry exceeds the delivery budget')
                bundle = self.epochs.export(self.member, current)
                chain.append(bundle)
                current = bundle['epoch']['document']['parent']
            for bundle in reversed(chain):
                check()
                key = bundle['epoch']['id']
                receipt = self.transport.receive_epoch(bundle)
                check()
                self.epochs._allowed(self.member, bundle['epoch'])
                if receipt != {'epoch_id': key, 'committed': True}:
                    raise ValueError('Peer did not commit the requested Slot evidence')
                pushed.add(key)
        # Settings may reference a baseline before any new Web event exists.
        try:
            check()
            with self.settings.history._transaction() as conn:
                head = self.settings.history._state(conn, 'head')
                document = self.settings.history._document(conn, head) if head else None
            if document:
                self.settings._allowed(self.member, head, document['payload'])
                for reference in document['payload'].get('slot_epochs', []):
                    push_epoch(reference['epoch_id'])
            receipt = self.settings.send(self.member, self.transport, reconnect=reconnect,
                                         max_pages=4, cancelled=cancelled)
            if receipt:
                sent += 1
                more |= not receipt['committed']
        except CancelledError:
            raise
        except Exception as error:
            errors.append(('settings', self._error(error)))
        try:
            check()
            events = self.web.observations.pending(self.member, limit=32)
            for event in events:
                self.history._allowed(self.member, event)
                epoch = event['payload'].get('meter_epoch_id')
                if epoch:
                    push_epoch(epoch)
            if events:
                receipt = self.transport.receive_web(events)
                check()
                for event in events:
                    self.history._allowed(self.member, event)
                ids = [event['id'] for event in events]
                if receipt != {'event_ids': ids, 'committed': True}:
                    raise ValueError('Peer did not commit the requested Web observations')
                self.web.observations.acknowledge(self.member, ids)
                sent += len(events)
                more |= bool(self.web.observations.pending(self.member, limit=1))
        except CancelledError:
            raise
        except Exception as error:
            errors.append(('web', self._error(error)))
        try:
            check()
            if self._amendment_cursor is not None:
                audit = self.amendments.recheck(self.member, self.transport, after=self._amendment_cursor)
                self._amendment_cursor = audit['after'] if audit['more'] else None
                more |= audit['more']
            for _ in range(4):
                if not self.amendments.deliver_one(self.member, self.transport, reconnect=reconnect):
                    break
                sent += 1
                check()
            else:
                more |= self.amendments.pending(self.member) is not None
        except CancelledError:
            raise
        except Exception as error:
            errors.append(('amendments', self._error(error)))
        return SyncResult('pending' if errors or more or received.status == 'pending' else 'complete',
            received.pages, received.observations, received.imported_epochs, received.after, received.through,
            sent, more, tuple(errors))

    @staticmethod
    def _error(error):
        return ('unauthorized' if isinstance(error, PermissionError) else
                'timeout' if isinstance(error, TimeoutError) else
                'invalid_data' if isinstance(error, (ValueError, TypeError)) else 'transport')
