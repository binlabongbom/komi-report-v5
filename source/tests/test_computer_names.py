import json
import sqlite3
from types import SimpleNamespace

import database
from services.computer_names import computer_directory, snapshot_readers, local_computer_name
from services.lan_tls import ensure_generated_certificate
from services.pipeline_log import PipelineLogStore
from test_peer_membership import member


def contact(tmp_path, name, hostname, ip):
    peer = member(tmp_path, name)
    peer.initialize_primary('Fixture')
    material = ensure_generated_certificate(tmp_path / name, hostname=hostname, lan_ips=[ip], client_auth=True)
    packet = peer.contact(certificate_pem=material.certificate_path.read_text(), url=f'https://{ip}:3101')
    return packet


def insert(conn, packet):
    doc = packet['document']
    conn.execute('INSERT INTO lan_peer_members(member_id,origin,fingerprint,document,revoked) VALUES(?,?,?,?,0)',
        (doc['member_id'], doc['origin'], doc['member_id'], json.dumps(packet)))


def test_accepted_v1_certificate_name_and_duplicate_names_keep_identity(tmp_path):
    a = contact(tmp_path, 'A', 'office-pc', '192.0.2.10')
    b = contact(tmp_path, 'B', 'office-pc', '192.0.2.11')
    with sqlite3.connect(database.get_db_path()) as conn:
        insert(conn, a)
        insert(conn, b)
        names = computer_directory(conn)
    assert names['members'] == {'A': 'office-pc (192.0.2.10)', 'B': 'office-pc (192.0.2.11)'}
    assert names['origins'][b['document']['origin']] == 'office-pc (192.0.2.11)'
    # No new contact field or wire protocol is needed by old peers.
    assert 'computer_name' not in a['document']


def test_missing_or_malformed_name_falls_back_to_address_never_localhost(tmp_path):
    packet = contact(tmp_path, 'A', 'localhost', '192.0.2.10')
    with sqlite3.connect(database.get_db_path()) as conn:
        insert(conn, packet)
        assert computer_directory(conn)['members']['A'] == '192.0.2.10'
        packet['document']['certificate'] = 'invalid'
        conn.execute('UPDATE lan_peer_members SET document=?', (json.dumps(packet),))
        assert computer_directory(conn)['members']['A'] == '192.0.2.10'


def test_exact_observation_origin_is_reader_not_relay_or_newer_event(tmp_path):
    from test_peer_web_view import saved
    from test_reader_jobs import fixture
    fixture()
    event = saved(301)
    newer = saved(302, 19)
    packet = contact(tmp_path, 'REMOTE', 'reader-pc', '192.0.2.22')
    with sqlite3.connect(database.get_db_path()) as conn:
        insert(conn, packet)
        conn.execute('UPDATE web_observations SET origin_id=? WHERE event_id=?',
            (packet['document']['origin'], event['id']))
    snap = SimpleNamespace(event_id=event['id'], serial='SER-A')
    result = snapshot_readers(database.get_db_path(), {0: snap})
    assert result[0]['name'] == 'reader-pc'
    assert result[0]['at'] == event['payload']['observed_at']
    assert result[0]['at'] != newer['payload']['observed_at']
    snap.serial = 'REPLACED'
    assert snapshot_readers(database.get_db_path(), {0: snap}) == {}
    assert snapshot_readers(tmp_path / 'missing.db', {}) == {}
    assert not (tmp_path / 'missing.db').exists()


def test_local_trace_and_shared_trace_distinguish_executor_from_reader():
    log = PipelineLogStore()
    local = log.append(stage='WEB', action='read')
    shared = log.append(stage='SYNC', action='saved view', reader_name='remote-pc')
    scheduled = log.append(stage='POLICY', action='schedule')
    assert local.reader_name == local.computer_name == local_computer_name()
    assert shared.computer_name == local.computer_name
    assert shared.reader_name == 'remote-pc'
    assert scheduled.reader_name == ''  # A scheduled request does not prove a read.
