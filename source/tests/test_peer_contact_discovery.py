from copy import deepcopy
import ipaddress
import json

from fastapi.testclient import TestClient

import database
import web_api
from services.peer_contact_discovery import refresh_known_contacts, fetch_contact
from test_peer_membership import joined
from test_peer_contacts import add_peer
from test_peer_https import certificates


def test_public_contact_contains_only_public_proof_and_never_enrolls(tmp_path, certificates):
    client = TestClient(web_api.app)
    assert client.get('/api/v1/peer/contact').status_code == 404
    a, _ = joined(tmp_path, certificates)
    database.set_db_path(a.path)
    database.set_cfg('installation_id', 'A')
    response = client.get('/api/v1/peer/contact')
    assert response.status_code == 200
    packet = next(p for p in a.contacts() if p['document']['member_id'] == 'A')
    assert response.json() == packet
    assert a.invitation()['capability'] not in response.text
    assert 'PRIVATE KEY' not in response.text
    assert client.post('/api/v1/peer/contact').status_code == 405


def test_discovery_can_renew_only_an_existing_signed_identity(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    old = next(p for p in a.contacts() if p['document']['member_id'] == 'B')
    new = b.contact(certificate_pem=old['document']['certificate'], url='https://127.0.0.1:3102')
    b.accept_contact(new)
    interfaces = [(ipaddress.IPv4Address('127.0.0.2'), ipaddress.IPv4Network('127.0.0.0/8'))]
    discover = lambda _: [('127.0.0.1', 3000)]
    assert refresh_known_contacts(a, interfaces, discover=discover, fetch=lambda *_: new) == 1
    assert next(p for p in a.contacts() if p['document']['member_id'] == 'B') == new
    assert refresh_known_contacts(a, interfaces, discover=discover, fetch=lambda *_: old) == 0
    altered = deepcopy(new)
    altered['document']['generation'] += 1
    assert refresh_known_contacts(a, interfaces, discover=discover, fetch=lambda *_: altered) == 0
    c, packet = add_peer(tmp_path, a, 'C')
    assert refresh_known_contacts(b, interfaces, discover=discover, fetch=lambda *_: packet) == 0
    assert not b.authorize_session('C')


def test_unenrolled_or_cancelled_refresh_does_not_probe(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    def forbidden(*_):
        raise AssertionError('Unexpected discovery')
    assert refresh_known_contacts(a, [], discover=forbidden) == 0
    assert refresh_known_contacts(a, [object()], cancelled=lambda: True, discover=forbidden) == 0


def test_public_https_contact_has_a_total_deadline_even_for_trickled_body(certificates):
    import ssl
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread, Event
    from time import monotonic
    import pytest
    stop = Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '1000')
            self.send_header('Connection', 'close')
            self.end_headers()
            while not stop.wait(.1):
                try:
                    self.wfile.write(b' ')
                    self.wfile.flush()
                except OSError:
                    break
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates['B']['certificate'], certificates['B']['private_key'])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()
    started = monotonic()
    try:
        import http.client
        with pytest.raises((OSError, ValueError, http.client.HTTPException)):
            fetch_contact('127.0.0.1', server.server_port)
        assert monotonic() - started < 4
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(3)
