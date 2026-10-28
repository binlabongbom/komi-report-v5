"""Bounded mutual-TLS LAN transport; never creates or infers membership.

An independently verified adapter supplies CA/certificates and current
certificate-to-member authorization. Nothing listens or connects on import.
Services still authorize company, Slot and decision inside their transactions.
"""
import hashlib
from dataclasses import asdict
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import ssl
import threading
from time import monotonic
from urllib.parse import urlsplit

PATH = '/komi-peer/v1/rpc'
MAX_BYTES = 8 * 1024 * 1024


def _encode(value):
    result = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(result) > MAX_BYTES:
        raise ValueError('Peer message exceeds size limit')
    return result


def _decode(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = item
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON number')
    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)


def tls_context(*, certificate, private_key, ca_file, server=False):
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH,
                                         cafile=str(ca_file))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(str(certificate), str(private_key))
    return context


class PeerHTTPSClient:
    def __init__(self, url, *, member, context, authorize_certificate, timeout=10):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('An explicit HTTPS peer origin is required')
        if (not isinstance(context, ssl.SSLContext) or context.verify_mode != ssl.CERT_REQUIRED
                or not context.check_hostname or not callable(authorize_certificate)
                or not isinstance(member, str) or not member.strip()
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60):
            raise ValueError('Verified TLS, membership and bounded timeout are required')
        self.host, self.port = parsed.hostname, parsed.port or 443
        self.member, self.context, self.authorize = member, context, authorize_certificate
        self.timeout = timeout

    def call(self, operation, data):
        body = _encode({'operation': operation, 'data': data})
        if not isinstance(operation, str) or not operation or len(operation) > 64 or not isinstance(data, dict):
            raise ValueError('Invalid peer operation')
        # No proxy, redirect, HTTP fallback or transport-level write retry.
        # An offline LAN computer must not consume a long RPC processing budget
        # merely connecting. Reader grants can legitimately take longer while
        # their authority checks other members, so bound those phases separately.
        conn = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=min(2, self.timeout))
        deadline = monotonic() + self.timeout
        def remaining():
            budget = deadline - monotonic()
            if budget <= 0:
                raise TimeoutError('Peer request deadline expired')
            return budget
        try:
            conn.connect()
            fingerprint = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
            if self.authorize(self.member, fingerprint) is not True:
                raise PermissionError('Peer certificate does not identify an authorized member')
            sock = conn.sock
            sock.settimeout(remaining())
            conn.request('POST', PATH, body, {'Content-Type': 'application/json', 'Connection': 'close'})
            sock.settimeout(remaining())
            response = conn.getresponse()
            if response.status == 403:
                raise PermissionError('Peer rejected authorization')
            if response.status in (400, 413):
                raise ValueError('Peer rejected request framing')
            length = response.getheader('Content-Length')
            if (not length or not length.isascii() or not length.isdigit() or not 0 < int(length) <= MAX_BYTES
                    or response.getheader('Transfer-Encoding') is not None
                    or response.getheader('Content-Type', '').split(';')[0].strip() != 'application/json'):
                raise ValueError('Invalid peer response framing')
            remaining, chunks = int(length), []
            while remaining:
                budget = deadline - monotonic()
                if budget <= 0:
                    raise TimeoutError('Peer response deadline expired')
                sock.settimeout(budget)
                chunk = response.read1(min(65536, remaining))
                if not chunk:
                    raise ValueError('Truncated peer response')
                chunks.append(chunk)
                remaining -= len(chunk)
            if self.authorize(self.member, fingerprint) is not True:
                raise PermissionError('Peer membership changed during transfer')
            document = _decode(b''.join(chunks))
            if response.status == 409 and document == {'error': 'reader_redirect'}:
                from services.shared_reader import ReaderRedirect
                raise ReaderRedirect('Reader authority changed')
            if response.status == 403:
                raise PermissionError('Peer rejected authorization')
            if response.status in (400, 409, 413):
                raise ValueError('Peer rejected the request or its evidence')
            if response.status != 200 or not isinstance(document, dict) or set(document) != {'result'}:
                raise ConnectionError('Peer request did not complete')
            return document['result']
        finally:
            conn.close()

    def manifest(self, *, after=0):
        return self.call('history.manifest', {'after': after})

    def wake(self, boot_id):
        return self.call('peer.wake', {'boot_id': boot_id})

    def contacts(self, *, after='', limit=32):
        return self.call('peer.contacts', {'after': after, 'limit': limit})

    def origins(self, *, after='', limit=32):
        return self.call('peer.origins', {'after': after, 'limit': limit})

    def page(self, request, *, limit=32):
        return self.call('history.page', {'request': request, 'limit': limit})

    def epoch(self, epoch_id):
        return self.call('epoch.export', {'epoch_id': epoch_id})

    def amendment(self, document):
        return self.call('billing.amendment', {'document': document})

    def amendment_contains(self, document):
        return self.call('billing.contains', {'document': document})

    def reader_endpoint(self, local_member):
        return PeerHTTPSReader(self, local_member)

    def settings_page(self, packet):
        return self.call('settings.receive_page', {'packet': packet})

    def settings_contains(self, revision, document):
        return self.call('settings.contains', {'revision': revision, 'document': document})

    def receive_epoch(self, bundle):
        return self.call('epoch.receive', {'bundle': bundle})

    def receive_web(self, events):
        return self.call('web.receive', {'events': events})


class PeerHTTPSReader:
    def __init__(self, client, local_member):
        self.client, self.local_member = client, local_member

    def _call(self, operation, requester, scope, **data):
        if requester != self.local_member:
            raise PermissionError('Local reader identity changed')
        scope.document()
        return self.client.call('reader.' + operation, {'requester': requester, 'scope': asdict(scope), **data})

    def presence(self, requester, scope):
        from services.reader_election import ReaderPresence
        from services.reader_jobs import ReadScope
        result = self._call('presence', requester, scope)
        if not isinstance(result, dict) or set(result) != {'member_id', 'boot_id', 'scope', 'ready', 'incumbent'}:
            raise ValueError('Invalid reader presence')
        result['scope'] = ReadScope(**result['scope'])
        if result['member_id'] != self.client.member or result['scope'].document() != scope.document():
            raise ValueError('Reader presence belongs to a different peer or scope')
        return ReaderPresence(**result)

    def request(self, requester, request_id, scope, *, cancelled=lambda: False, probe_only=False):
        from concurrent.futures import CancelledError
        if cancelled():
            raise CancelledError()
        return self._call('request', requester, scope, request_id=request_id, probe_only=probe_only)

    def status(self, requester, job_id, scope):
        return self._call('status', requester, scope, job_id=job_id)

    def finish_probe(self, requester, job_id, scope, *, request_web):
        return self._call('finish_probe', requester, scope, job_id=job_id, request_web=request_web)

    def complete(self, requester, job_id, scope, *, event_id):
        return self._call('complete', requester, scope, job_id=job_id, event_id=event_id)

    def fail(self, requester, job_id, scope, *, reason):
        return self._call('fail', requester, scope, job_id=job_id, reason=reason)

    def publish(self, event, scope):
        receipt = self._call('publish', self.local_member, scope, event=event)
        if receipt != {'event_id': event['id'], 'committed': True}:
            raise ValueError('Peer did not commit the requested Web observation')
        return receipt

    def fetch(self, event_id, scope):
        return self._call('fetch', self.local_member, scope, event_id=event_id)


class PeerDataEndpoint:
    """Bind the transport to existing transaction/authorization services."""
    def __init__(self, *, history, epochs, amendments, reader=None, settings=None, web=None):
        self.history, self.epochs, self.amendments = history, epochs, amendments
        self.reader = reader
        self.settings = settings
        self.web = web

    def __call__(self, member, operation, data):
        if operation.startswith('reader.') and self.reader is not None:
            from services.reader_jobs import ReadScope
            if data.get('requester') != member or not isinstance(data.get('scope'), dict):
                raise PermissionError('Reader requester must match its authenticated certificate')
            scope = ReadScope(**data['scope'])
            scope.document()
            extras = {k: v for k, v in data.items() if k not in {'scope', 'requester'}}
            routes = {
                'reader.presence': (set(), lambda: asdict(self.reader.election.presence(member, scope))),
                'reader.request': ({'request_id', 'probe_only'}, lambda: self.reader.request(member, extras['request_id'], scope, probe_only=extras['probe_only'])),
                'reader.status': ({'job_id'}, lambda: self.reader.status(member, extras['job_id'], scope)),
                'reader.finish_probe': ({'job_id', 'request_web'}, lambda: self.reader.finish_probe(member, extras['job_id'], scope, request_web=extras['request_web'])),
                'reader.complete': ({'job_id', 'event_id'}, lambda: self.reader.complete(member, extras['job_id'], scope, event_id=extras['event_id'])),
                'reader.fail': ({'job_id', 'reason'}, lambda: self.reader.fail(member, extras['job_id'], scope, reason=extras['reason'])),
                'reader.publish': ({'event'}, lambda: self._publish(member, scope, extras['event'])),
                'reader.fetch': ({'event_id'}, lambda: self._fetch(member, scope, extras['event_id'])),
            }
            if operation not in routes or set(extras) != routes[operation][0]:
                raise ValueError('Unknown reader operation or invalid fields')
            return routes[operation][1]()
        handlers = {
            'history.manifest': ({'after'}, lambda: self.history.manifest(member, after=data['after'])),
            'history.page': ({'request', 'limit'}, lambda: self.history.export_page(member, data['request'], limit=data['limit'])),
            'epoch.export': ({'epoch_id'}, lambda: self.epochs.export(member, data['epoch_id'])),
            'epoch.receive': ({'bundle'}, lambda: {'epoch_id': self.epochs.receive(member, data['bundle']), 'committed': True}),
            'billing.amendment': ({'document'}, lambda: self.amendments.receive(member, data['document'])),
            'billing.contains': ({'document'}, lambda: self.amendments.contains(member, data['document'])),
        }
        if self.settings is not None:
            handlers['settings.receive_page'] = ({'packet'}, lambda: self.settings.receive(member, data['packet']))
            handlers['settings.contains'] = ({'revision', 'document'},
                lambda: self.settings.contains(member, data['revision'], data['document']))
        if self.web is not None:
            handlers['web.receive'] = ({'events'}, lambda: self.web.receive(member, data['events']))
        if operation not in handlers or set(data) != handlers[operation][0]:
            raise ValueError('Unknown peer operation or invalid fields')
        return handlers[operation][1]()

    def _publish(self, member, scope, event):
        from services.web_observations import WebObservationStore, validate_event
        document = validate_event(event)
        p = event['payload']
        jobs = self.reader.jobs
        with jobs._write(scope) as conn:
            verified, encoded = jobs._member(member, scope)
            jobs._expire(conn, scope.slot, encoded, jobs._now())
            job = conn.execute('SELECT * FROM reader_jobs WHERE id=? AND scope_json=?', (p['read_id'], encoded)).fetchone()
            if ((p['slot'], p['serial'], p.get('meter_epoch_id'), p['origin']) !=
                    (scope.slot, scope.serial, scope.epoch_id, verified.observation_origin)
                    or job is None or job['reader_id'] != member or (job['phase'] != 'reading' and
                        not (job['phase'] == 'complete' and job['event_id'] == event['id']))):
                raise PermissionError('Web observation does not belong to the authenticated read grant')
            WebObservationStore._insert(conn, event, document)
            jobs._member(member, scope)
        return {'event_id': event['id'], 'committed': True}

    def _fetch(self, member, scope, event_id):
        from services.slot_epoch_store import SlotEpochStore
        self.reader.jobs._member(member, scope)
        store = SlotEpochStore(self.reader.jobs.path)
        with store._connection() as conn:
            event = store._event(conn, event_id)
        p = event['payload']
        if (p['slot'], p['serial'], p.get('meter_epoch_id')) != (scope.slot, scope.serial, scope.epoch_id):
            raise PermissionError('Web observation belongs to a different reader scope')
        self.reader.jobs._member(member, scope)
        return event


class PeerHTTPSServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(self, address, *, context, resolve_member, dispatch, timeout=10):
        if (not isinstance(context, ssl.SSLContext) or context.verify_mode != ssl.CERT_REQUIRED
                or context.protocol != ssl.PROTOCOL_TLS_SERVER or not callable(resolve_member)
                or not callable(dispatch) or type(timeout) not in (int, float)
                or not math.isfinite(timeout) or not 0 < timeout <= 60):
            raise ValueError('Mutual TLS and current member authorization are required')
        self.tls_context, self.resolve_member, self.dispatch = context, resolve_member, dispatch
        self.peer_timeout = timeout
        self._capacity = threading.BoundedSemaphore(16)
        self._active_lock = threading.Lock()
        self._active_requests = 0
        self._idle = threading.Event()
        self._idle.set()
        super().__init__(address, _Handler)

    @property
    def active_requests(self):
        with self._active_lock:
            return self._active_requests

    def wait_requests(self):
        self._idle.wait()

    def _request_finished(self):
        with self._active_lock:
            self._active_requests -= 1
            if not self._active_requests:
                self._idle.set()
        self._capacity.release()

    def process_request(self, request, address):
        if not self._capacity.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self._active_lock:
            self._active_requests += 1
            self._idle.clear()
        try:
            super().process_request(request, address)
        except BaseException:
            self._request_finished()
            raise

    def process_request_thread(self, request, address):
        try:
            request.settimeout(self.peer_timeout)
            # Handshake in the bounded worker, never on the accept loop.
            with self.tls_context.wrap_socket(request, server_side=True) as secured:
                self.finish_request(secured, address)
        except (OSError, ValueError):
            pass
        finally:
            self.shutdown_request(request)
            self._request_finished()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def handle_one_request(self):
        import socket
        def expire():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # Bound headers as well as the body; resetting a socket timeout by
        # trickling a header must not hold the runtime ownership lock forever.
        self._input_timer = threading.Timer(self.server.peer_timeout, expire)
        self._input_timer.daemon = True
        self._input_timer.start()
        try:
            super().handle_one_request()
        finally:
            self._input_timer.cancel()

    def log_message(self, *_):
        pass  # Never emit certificates, financial bodies or peer errors to stdout.

    def _reply(self, status, document):
        raw = _encode(document)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        from services.shared_reader import ReaderRedirect
        try:
            if self.path != PATH or self.headers.get('Transfer-Encoding') is not None:
                raise ValueError('Invalid peer request path or framing')
            lengths = self.headers.get_all('Content-Length', [])
            if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                    or not 0 < int(lengths[0]) <= MAX_BYTES
                    or self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json'):
                raise ValueError('Invalid peer request length')
            fingerprint = hashlib.sha256(self.connection.getpeercert(binary_form=True)).hexdigest()
            member = self.server.resolve_member(fingerprint)
            authorized = isinstance(member, str) and bool(member.strip()) and len(member) <= 256
            remaining, chunks = int(lengths[0]), []
            deadline = monotonic() + self.server.peer_timeout
            while remaining:
                budget = deadline - monotonic()
                if budget <= 0:
                    raise TimeoutError('Request deadline expired')
                self.connection.settimeout(budget)
                chunk = self.rfile.read1(min(65536, remaining))
                if not chunk:
                    raise ValueError('Truncated peer request')
                # Drain a correctly framed, bounded request before closing TLS.
                # Closing with unread body bytes can reset the TCP connection on
                # Linux and discard our 403. Never retain/decode unauthorized data.
                if authorized:
                    chunks.append(chunk)
                remaining -= len(chunk)
            if not authorized:
                raise PermissionError('Unrecognized peer certificate')
            document = _decode(b''.join(chunks))
            if (not isinstance(document, dict) or set(document) != {'operation', 'data'}
                    or not isinstance(document['operation'], str) or len(document['operation']) > 64
                    or not isinstance(document['data'], dict)):
                raise ValueError('Invalid peer request')
            self._input_timer.cancel()  # Reader arbitration has its own deadline.
            if self.server.resolve_member(fingerprint) != member:
                raise PermissionError('Peer membership changed')
            result = self.server.dispatch(member, document['operation'], document['data'])
            self._reply(200, {'result': result})
        except ReaderRedirect:
            self._reply(409, {'error': 'reader_redirect'})
        except PermissionError:
            self._reply(403, {'error': 'unauthorized'})
        except (ValueError, TypeError, KeyError, RecursionError):
            self._reply(409, {'error': 'invalid_or_conflicting_request'})
        except Exception:
            self._reply(503, {'error': 'unavailable'})
