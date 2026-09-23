from contextlib import closing
import sqlite3

import pytest

import database
from services.peer_enrollment import EnrollmentSource, open_continuous_pairing, prepare_enrollment
from services.peer_sync_authorization import new_claim_token, claim_pairing_window, open_pairing_window, close_pairing_window
from services.registration_vault import SessionRegistrationSecretStore
from services.peer_transport_factory import local_membership
from test_reader_jobs import fixture


def source(tmp_path, monkeypatch):
    monkeypatch.setenv('KOMI_PEER_SYNC_STATE_FILE', str(tmp_path / 'approval.json'))
    fixture()
    database.set_cfg('company_name', 'Synthetic company')
    database.set_cfg('installation_id', 'SOURCE')
    access = open_continuous_pairing(vault=SessionRegistrationSecretStore(), runtime_root=tmp_path / 'source', host='127.0.0.1')
    endpoint = EnrollmentSource(access)
    path = database.get_db_path()
    token = new_claim_token()
    claim_pairing_window(token, '127.0.0.2')
    database.set_db_path(tmp_path / 'receiver.sqlite3')
    database.init_db()
    return access, endpoint, path, token


def test_first_install_preserves_source_ancestry_and_commits_membership_once(tmp_path, monkeypatch):
    access, endpoint, path, token = source(tmp_path, monkeypatch)
    calls = []
    def request(operation, data):
        calls.append(operation)
        return endpoint.call(token, '127.0.0.2', operation, data)
    vault = SessionRegistrationSecretStore()
    preview = prepare_enrollment(request, vault=vault, runtime_root=tmp_path / 'target', host='127.0.0.2')
    try:
        with database._open(commit=False) as conn:
            assert conn.execute('SELECT COUNT(*) FROM lan_peer_group').fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM devices WHERE enabled=1').fetchone()[0] == 0
        preview.commit(local_settings={'v52_registration_mode': 'offline'})
        assert preview.commit() == preview.head
        local = local_membership(vault=vault)
        assert local.authorize_session(access.member_id)
        assert access.authorize_session(local.member_id)
        assert local.current_scope(0).settings_revision == access.current_scope(0).settings_revision
        assert local.current_scope(0).epoch_id == access.current_scope(0).epoch_id
        assert database.get_cfg('installation_id') == preview.identity.installation_id != 'SOURCE'
        with database._open(commit=False) as conn:
            assert conn.execute('SELECT COUNT(*) FROM billing_ledger').fetchone()[0] == 0
    finally:
        preview.close()


def test_cancel_keeps_live_database_unchanged(tmp_path, monkeypatch):
    access, endpoint, path, token = source(tmp_path, monkeypatch)
    preview = prepare_enrollment(lambda op, data: endpoint.call(token, '127.0.0.2', op, data),
        vault=SessionRegistrationSecretStore(), runtime_root=tmp_path, host='127.0.0.2')
    preview.close()
    with database._open(commit=False) as conn:
        assert not conn.execute('SELECT 1 FROM lan_peer_group').fetchone()
        assert not conn.execute('SELECT 1 FROM peer_settings_revisions').fetchone()


def test_explicit_copy_only_permission_cannot_grant_continuous_membership(tmp_path, monkeypatch):
    access, endpoint, path, _ = source(tmp_path, monkeypatch)
    open_pairing_window('SOURCE', always_open=True)
    token = new_claim_token()
    claim_pairing_window(token, '127.0.0.2')
    with pytest.raises(Exception, match='สมาชิก'):
        endpoint.call(token, '127.0.0.2', 'begin', {'member_id': 'B', 'public_key': 'x'})


def test_persistent_default_migrates_timed_policy_and_survives_restart(tmp_path, monkeypatch):
    from services import peer_sync_authorization as policy
    import json
    monkeypatch.setenv('KOMI_PEER_SYNC_STATE_FILE',str(tmp_path/'policy.json'))
    policy.open_pairing_window('SOURCE',continuous=True,now=1)
    assert policy.ensure_pairing_default('SOURCE',continuous=True,now=10000)
    assert policy.pairing_window_status(now=100000).always_open
    first = policy.new_claim_token()
    policy.claim_pairing_window(first,'127.0.0.2',now=100001)
    before = policy.state_path().read_bytes()
    assert not policy.ensure_pairing_default('SOURCE',continuous=True,now=100002)
    assert policy.state_path().read_bytes() == before
    policy.consume_pairing_token(first,'127.0.0.2','SOURCE',enrollment_transfer=True,now=100003)
    # A later computer joins without anyone reopening the source window.
    second = policy.new_claim_token()
    policy.claim_pairing_window(second,'127.0.0.3',now=200000)
    policy.consume_pairing_token(second,'127.0.0.3','SOURCE',enrollment_transfer=True,now=200001)
    assert json.loads(policy.state_path().read_text())['continuous']
    policy.close_pairing_window()
    policy.ensure_pairing_default('SOURCE',continuous=True,now=200002)
    assert not policy.pairing_window_status(now=200003).open


def test_new_source_bootstraps_on_join_without_approval_button(tmp_path,monkeypatch):
    from services import peer_enrollment as enrollment
    from services.peer_sync_authorization import ensure_pairing_default
    fixture()
    database.set_cfg('company_name','Synthetic company')
    database.set_cfg('installation_id','AUTO-SOURCE')
    monkeypatch.setenv('KOMI_PEER_SYNC_STATE_FILE',str(tmp_path/'auto.json'))
    access = local_membership(vault=SessionRegistrationSecretStore())
    assert access.group() is None
    assert ensure_pairing_default('AUTO-SOURCE',continuous=True)
    token = new_claim_token()
    claim_pairing_window(token,'127.0.0.2')
    original = enrollment.prepare_enrollment_source
    monkeypatch.setattr(enrollment,'prepare_enrollment_source',lambda peer:original(peer,
        runtime_root=tmp_path/'auto-source',host='127.0.0.1'))
    database.set_db_path(tmp_path/'fresh-join.db')
    database.init_db()
    p = prepare_enrollment(lambda op,data:EnrollmentSource(access).call(token,'127.0.0.2',op,data),
        vault=SessionRegistrationSecretStore(),runtime_root=tmp_path/'auto-join',host='127.0.0.2')
    try:
        p.commit()
        assert access.authorize_session(p.identity.installation_id)
    finally:
        p.close()


def test_lost_finish_response_resumes_without_rewriting_setup(tmp_path, monkeypatch):
    access, endpoint, path, token = source(tmp_path, monkeypatch)
    lost = [True]
    def request(op, data):
        result = endpoint.call(token,'127.0.0.2',op,data)
        if op == 'finish' and lost[0]:
            lost[0] = False
            raise OSError('synthetic lost receipt')
        return result
    vault = SessionRegistrationSecretStore()
    p = prepare_enrollment(request,vault=vault,runtime_root=tmp_path,host='127.0.0.2')
    try:
        with pytest.raises(OSError):
            p.commit()
        assert p.committed
        with database._open(commit=False) as conn:
            before = conn.execute('SELECT * FROM peer_settings_revisions').fetchall()
        p.commit()
        with database._open(commit=False) as conn:
            assert before == conn.execute('SELECT * FROM peer_settings_revisions').fetchall()
        assert access.authorize_session(p.identity.installation_id)
    finally:
        p.close()


@pytest.mark.parametrize('failure',['local_change','storage','closed_window','wrong_ip'])
def test_enrollment_failures_do_not_silently_complete(tmp_path,monkeypatch,failure):
    access, endpoint, path, token = source(tmp_path,monkeypatch)
    p = prepare_enrollment(lambda op,data:endpoint.call(token,'127.0.0.2',op,data),
        vault=SessionRegistrationSecretStore(),runtime_root=tmp_path,host='127.0.0.2')
    try:
        if failure == 'local_change':
            database.set_cfg('company_name','Changed after preview')
        elif failure == 'storage':
            with database._open() as conn:
                conn.execute("CREATE TRIGGER fail_join BEFORE INSERT ON lan_peer_members BEGIN SELECT RAISE(ABORT,'fixture'); END")
        elif failure == 'closed_window':
            close_pairing_window()
        else:
            with pytest.raises(Exception):
                endpoint.call(token,'127.0.0.99','finish',{'contact':p.contact})
            return
        with pytest.raises(Exception):
            p.commit()
        assert not access.authorize_session(p.identity.installation_id)
        if failure in {'local_change','storage'}:
            with database._open(commit=False) as conn:
                assert not conn.execute('SELECT 1 FROM lan_peer_group').fetchone()
                assert not conn.execute('SELECT 1 FROM peer_settings_revisions').fetchone()
    finally:
        p.close()


def test_clean_reinstallation_preserves_old_database_and_cannot_inherit_identity(tmp_path,monkeypatch):
    from services.peer_reinstallation import create_clean_database
    access, endpoint, path, token = source(tmp_path,monkeypatch)
    destination = tmp_path/'reinstalled.db'
    with closing(sqlite3.connect(path)) as conn:
        before = conn.execute('SELECT * FROM settings').fetchall()
    create_clean_database(path,destination)
    with pytest.raises(FileExistsError):
        create_clean_database(path,destination)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT * FROM settings').fetchall() == before
    database.set_db_path(destination)
    database.init_db()
    with database._open(commit=False) as conn:
        for table in ('lan_peer_group','lan_peer_members','web_observations'):
            assert not conn.execute(f'SELECT 1 FROM {table}').fetchone()
        cfg = dict(conn.execute('SELECT key,value FROM settings'))
        assert not cfg.get('installation_id')
        assert not cfg.get('company_name')
    p = prepare_enrollment(lambda op,data:endpoint.call(token,'127.0.0.2',op,data),
        vault=SessionRegistrationSecretStore(),runtime_root=tmp_path,host='127.0.0.2')
    try:
        p.commit()
        assert p.identity.installation_id != access.member_id
    finally:
        p.close()


def test_wizard_commits_credentials_atomically_and_preserves_reviewed_setup(tmp_path, monkeypatch):
    from dataclasses import replace
    from services.device_config import DeviceConfigRepository
    from v5_pages import SetupWizardV5
    from services.secondary_setup import SecondaryPeerCandidate
    from test_peer_history_runtime import until
    access, endpoint, path, token = source(tmp_path, monkeypatch)
    p = prepare_enrollment(lambda op,data:endpoint.call(token,'127.0.0.2',op,data),
        vault=SessionRegistrationSecretStore(),runtime_root=tmp_path,host='127.0.0.2')
    with closing(sqlite3.connect(p.stage)) as conn:
        # The staging repository is read only here; no platform vault is used.
        row = conn.execute('SELECT name,host,model,serial,tls_mode,tls_fingerprint FROM devices WHERE enabled=1').fetchone()
    wizard = SetupWizardV5()
    wizard.secondary_enrollment = p
    monkeypatch.setattr(wizard, '_test_all', lambda: None)
    monkeypatch.setattr(wizard, '_show_wizard_message', lambda *args: pytest.fail(str(args)))
    completed = []
    monkeypatch.setattr(wizard, '_complete_setup_registration', lambda *args: completed.append(args))
    try:
        candidate = SecondaryPeerCandidate('https://192.0.2.1:8443','Synthetic company',1,'5.2.12','0'*64)
        wizard._apply_secondary_snapshot(candidate,p.snapshot())
        assert not wizard.shared_price_mode.isEnabled()
        assert not wizard.shared_price_row['a4_color'].isEnabled()
        devices = wizard._configs()
        devices = [replace(d,password='synthetic-local-password') for d in devices]
        wizard._save_enrollment(p,{'installation_id':p.identity.installation_id},'Synthetic company','offline',p.identity.installation_id,devices)
        until(lambda: bool(completed))
        repository = DeviceConfigRepository()
        assert repository.get(0).password == 'synthetic-local-password'
        with database._open(commit=False) as conn:
            assert conn.execute('SELECT password FROM devices WHERE enabled=1').fetchone() == ('',)
        assert access.authorize_session(p.identity.installation_id)
    finally:
        wizard.secondary_enrollment = None
        wizard.close()
        p.close()


def test_enrolled_members_exchange_over_real_tls_and_survive_source_offline(tmp_path, monkeypatch):
    from services.peer_network import PeerNetworkNode
    from services.peer_transport_factory import PeerTransportFactory
    from services.web_observations import WebObservationStore
    from test_subject_history import _reading
    from datetime import datetime, UTC
    import socket
    access, endpoint, path, token = source(tmp_path,monkeypatch)
    peers, nodes, factories, contexts = {'SOURCE':access}, {}, {}, {}
    def start(peer, root, port=0):
        factory = PeerTransportFactory(peer,runtime_root=root,lan_ips=['127.0.0.1'])
        node = PeerNetworkNode(access=peer,client_for=factory.client,ready=lambda slot:True)
        context = factory.context(server=True)
        address = node.start(('127.0.0.1',port),context=context)
        own = factory.own_contact(host='127.0.0.1',port=address[1])
        peer.accept_contact(own)
        factories[peer.member_id], nodes[peer.member_id], contexts[peer.member_id] = factory,node,context
        return own
    try:
        start(access,tmp_path/'source')
        for index in range(2):
            database.set_db_path(tmp_path/f'joined-{index}.db')
            database.init_db()
            open_pairing_window('SOURCE',continuous=True)
            token = new_claim_token()
            claim_pairing_window(token,'127.0.0.2')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1',0))
                port = reservation.getsockname()[1]
            root = tmp_path/f'runtime-{index}'
            vault = SessionRegistrationSecretStore()
            p = prepare_enrollment(lambda op,data:endpoint.call(token,'127.0.0.2',op,data),vault=vault,
                runtime_root=root,host='127.0.0.1',port=port)
            try:
                p.commit()
                peer = local_membership(vault=vault)
                peers[peer.member_id] = peer
                start(peer,root,port)
            finally:
                p.close()
        for key, factory in factories.items():
            factory.refresh_server_trust(contexts[key])
        names = [name for name in peers if name != 'SOURCE']
        for name in names:
            assert nodes['SOURCE'].session(name).run().status == 'complete'
        for name in names:
            assert nodes[name].session('SOURCE').run().status == 'complete'
            factories[name].refresh_server_trust(contexts[name])
        b,c = names
        assert peers[b].authorize_session(c) and peers[c].authorize_session(b)
        nodes['SOURCE'].stop(wait=True)
        scope = peers[b].current_scope(0)
        event = WebObservationStore(peers[b].path).record(0,
            _reading(345,collected_at=datetime(2026,9,18,10,tzinfo=UTC)),
            serial=scope.serial,printer_name='Synthetic printer',epoch_id=scope.epoch_id)
        assert nodes[b].session(c).run().status == 'complete'
        assert event in WebObservationStore(peers[c].path).page()['events']
        assert nodes[b].session(c).run().sent == 0
    finally:
        for node in nodes.values():
            node.stop(wait=True)


def test_https_client_to_api_enrolls_and_resumes_after_restart(tmp_path,monkeypatch):
    import hashlib
    import json
    import ssl
    from dataclasses import replace
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from fastapi.testclient import TestClient
    import web_api
    import services.peer_enrollment as enrollment
    import services.peer_transport_factory as transport
    from services.lan_tls import ensure_generated_certificate
    from services.secondary_setup import SecondaryPeerClient, SecondaryPeerCandidate, SecondarySetupError
    access, endpoint, path, token = source(tmp_path,monkeypatch)
    monkeypatch.setattr(transport,'local_membership',lambda:access)
    api = TestClient(web_api.app)
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            headers = dict(self.headers)
            headers['x-komi-remote-address'] = self.client_address[0]
            response = api.post(self.path,content=self.rfile.read(int(self.headers.get('Content-Length',0))),headers=headers)
            self.send_response(response.status_code)
            self.send_header('Content-Length',str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        def log_message(self,*args):
            pass
    material = ensure_generated_certificate(tmp_path/'edge',lan_ips=['127.0.0.1'])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(material.certificate_path,material.private_key_path)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.socket = context.wrap_socket(server.socket,server_side=True)
    worker = Thread(target=server.serve_forever,daemon=True)
    worker.start()
    client = SecondaryPeerClient()
    # Production rejects loopback discovery; the harness uses loopback exclusively.
    monkeypatch.setattr(client,'_peer_endpoint',lambda candidate:('127.0.0.1',server.server_port))
    vault = SessionRegistrationSecretStore()
    prepare = enrollment.prepare_enrollment
    monkeypatch.setattr(enrollment,'prepare_enrollment',lambda request,**kw:prepare(request,
        vault=vault,runtime_root=tmp_path/'receiver',host='127.0.0.1',**kw))
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(material.certificate_path.read_text())).hexdigest()
    candidate = SecondaryPeerCandidate(f'https://127.0.0.1:{server.server_port}','Synthetic company',1,'5.2.12',fingerprint)
    p = None
    try:
        open_pairing_window('SOURCE',continuous=True,always_open=True)
        with pytest.raises(SecondarySetupError,match='Certificate'):
            client.prepare_enrollment(replace(candidate,certificate_sha256='0'*64))
        assert api.post('/api/v3/peer/enrollment',json={'operation':'begin','data':{}}).status_code == 401
        p = client.prepare_enrollment(candidate)
        # Request credentials may expire internally; persistent source access
        # lets the real HTTPS client renew them without another approval click.
        from services.peer_sync_authorization import state_path
        policy = json.loads(state_path().read_text())
        for grant in policy['enrollment_transfers'].values():
            grant['expires_at'] = 0
        state_path().write_text(json.dumps(policy),encoding='utf-8')
        assert p.request('settings',{'offset':0})['head'] == p.head
        close_pairing_window()
        with pytest.raises(SecondarySetupError):
            p.commit()
        assert p.committed and database.get_cfg('peer_enrollment_pending')
        assert not access.authorize_session(p.identity.installation_id)
        # Restart loses the preview/token; only the committed marker and vault remain.
        p.close()
        peer = local_membership(vault=vault)
        open_pairing_window('SOURCE',continuous=True)
        client.finish_pending_enrollment(candidate,peer,contact=p.contact)
        assert not database.get_cfg('peer_enrollment_pending')
        assert access.authorize_session(peer.member_id)
    finally:
        if p is not None:
            p.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
        api.close()
