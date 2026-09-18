from contextlib import contextmanager
from datetime import datetime, timedelta, UTC
import hashlib
import ipaddress
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from services.peer_https import PeerHTTPSClient, PeerHTTPSServer, PeerDataEndpoint, tls_context, MAX_BYTES


@pytest.fixture
def certificates(tmp_path):
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Isolated KOMI fixture CA')])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1))
        .not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False).sign(ca_key, hashes.SHA256()))
    ca_file = tmp_path / 'ca.pem'
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    result = {'ca_file': ca_file}
    for identity in ('A', 'B'):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identity)]))
            .issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
            .sign(ca_key, hashes.SHA256()))
        cert_file, key_file = tmp_path / (identity + '.pem'), tmp_path / (identity + '-key.pem')
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        result[identity] = {'certificate': cert_file, 'private_key': key_file, 'ca_file': ca_file,
                           'fingerprint': hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()}
    return result


def context(certificates, identity, *, server=False):
    return tls_context(**{k: v for k, v in certificates[identity].items() if k != 'fingerprint'}, server=server)


@contextmanager
def server(certificates, dispatch, *, allow=True):
    host = PeerHTTPSServer(('127.0.0.1', 0), context=context(certificates, 'B', server=True),
        resolve_member=lambda fingerprint: 'A' if allow and fingerprint == certificates['A']['fingerprint'] else None,
        dispatch=dispatch, timeout=2)
    thread = threading.Thread(target=host.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()
    try:
        yield f'https://127.0.0.1:{host.server_port}'
    finally:
        host.shutdown()
        host.server_close()
        thread.join(timeout=5)


def client(certificates, url, authorize=None):
    return PeerHTTPSClient(url, member='B', context=context(certificates, 'A'), timeout=2,
        authorize_certificate=authorize or (lambda member, fingerprint: member == 'B' and fingerprint == certificates['B']['fingerprint']))


def test_real_mutual_tls_delivers_amendment_and_history(certificates, tmp_path):
    from test_billing_web_amendment import setup, confirm
    from test_peer_billing_amendments import clone, peer
    from services.web_catchup import WebCatchup
    from services.slot_epoch_exchange import SlotEpochExchange
    from services.peer_history_session import PeerHistorySession
    from services.web_observations import WebObservationStore
    import database
    service, args, _ = setup()
    target = clone(tmp_path, 'B-database')
    confirm(service, args, service.preview(*args))
    endpoint = PeerDataEndpoint(history=WebCatchup(authorize=lambda *a: True, path=target),
        epochs=SlotEpochExchange(authorize=lambda *a: True, path=target), amendments=peer(target))
    with server(certificates, endpoint) as url:
        transport = client(certificates, url)
        assert peer().deliver_one('B', transport)
        assert peer().pending('B') is None
        assert transport.epoch(args[1])['epoch']['id'] == args[1]
        original = database.get_db_path()
        c_path = tmp_path / 'C-database.sqlite3'
        try:
            database.set_db_path(c_path)
            database.init_db()
        finally:
            database.set_db_path(original)
        session = PeerHistorySession(member='B', transport=transport, path=c_path,
            authorize_session=lambda *a: True, authorize_event=lambda *a: True, authorize_epoch=lambda *a: True)
        assert session.run(page_size=1).status == 'complete'
        assert len(WebObservationStore(c_path).page()['events']) == 2


def test_valid_ca_but_wrong_membership_does_not_dispatch(certificates):
    calls = []
    with server(certificates, lambda *a: calls.append(a)) as url:
        with pytest.raises(PermissionError):
            client(certificates, url, lambda *a: False).call('ping', {})
    assert calls == []
    with server(certificates, lambda *a: calls.append(a), allow=False) as url:
        with pytest.raises(PermissionError):
            client(certificates, url).call('ping', {})
    assert calls == []


def test_certificate_and_hostname_validation_cannot_fallback(certificates):
    calls = []
    with server(certificates, lambda *a: calls.append(a)) as url:
        with pytest.raises(ssl.SSLCertVerificationError):
            client(certificates, url.replace('127.0.0.1', 'localhost')).call('ping', {})
        untrusted = ssl.create_default_context()
        untrusted.load_cert_chain(str(certificates['A']['certificate']), str(certificates['A']['private_key']))
        with pytest.raises(ssl.SSLCertVerificationError):
            PeerHTTPSClient(url, member='B', context=untrusted, authorize_certificate=lambda *a: True).call('ping', {})
    assert calls == []


def test_revocation_before_accepting_response_and_no_implicit_retry(certificates):
    checks, calls = [], []
    def authorize(*args):
        checks.append(args)
        return len(checks) == 1
    with server(certificates, lambda *a: calls.append(a) or {'ok': True}) as url:
        with pytest.raises(PermissionError):
            client(certificates, url, authorize).call('ping', {})
    assert len(calls) == 1


def test_invalid_transport_options_and_oversized_payload(certificates):
    for url in ('http://127.0.0.1', 'https://user:pass@127.0.0.1', 'https://127.0.0.1/path', 'https://127.0.0.1/?token=x'):
        with pytest.raises(ValueError):
            client(certificates, url)
    insecure = ssl._create_unverified_context()
    with pytest.raises(ValueError):
        PeerHTTPSClient('https://127.0.0.1', member='B', context=insecure, authorize_certificate=lambda *a: True)
    transport = client(certificates, 'https://127.0.0.1:1')
    with pytest.raises(ValueError, match='size limit'):
        transport.call('test', {'value': 'a' * MAX_BYTES})


def test_reader_grant_publish_and_fetch_over_tls(certificates, tmp_path):
    from test_reader_election import cluster
    from test_shared_web_read import reading
    from services.web_observations import WebObservationStore
    from services.shared_reader import ReaderRedirect
    elections, authorities, _, online, _, _, _, scope, _, _ = cluster(tmp_path)
    online.discard('A')
    online.discard('C')  # B is the elected authority; A is still a verified requester.
    endpoint = PeerDataEndpoint(history=None, epochs=None, amendments=None, reader=authorities['B'])
    with server(certificates, endpoint) as url:
        transport = client(certificates, url)
        remote = transport.reader_endpoint('A')
        assert remote.presence('A', scope[0]).member_id == 'B'
        grant = remote.request('A', 'manual-on-A', scope[0])
        assert grant['reader_id'] == 'A' and grant['can_read']
        event = WebObservationStore(authorities['A'].jobs.path).record(0, reading(), serial=scope[0].serial,
            printer_name='Fixture', epoch_id=scope[0].epoch_id, read_id=grant['job_id'])
        assert remote.publish(event, scope[0])['committed'] is True
        assert remote.complete('A', grant['job_id'], scope[0], event_id=event['id'])['phase'] == 'complete'
        assert remote.fetch(event['id'], scope[0]) == event
        assert remote.status('A', grant['job_id'], scope[0])['event_id'] == event['id']
        with pytest.raises(PermissionError):
            transport.call('reader.status', {'requester': 'C', 'scope': scope[0].__dict__, 'job_id': grant['job_id']})
        # A scope-preserving redirect remains a reader redirect, never an HTTP redirect.
        def redirect(*a, **k):
            raise ReaderRedirect('changed')
        authorities['B'].request = redirect
        with pytest.raises(ReaderRedirect):
            remote.request('A', 'another', scope[0])
