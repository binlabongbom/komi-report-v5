from contextlib import closing
from copy import deepcopy
import sqlite3

import pytest

import database
from services.installation_identity import load_or_create_installation_identity
from services.peer_membership import PeerMembership
from services.registration_vault import SessionRegistrationSecretStore
from test_peer_https import certificates


def member(tmp_path, name, *, clone=None):
    path = tmp_path / (name + '.db')
    with closing(sqlite3.connect(clone or database.get_db_path())) as source, closing(sqlite3.connect(path)) as target:
        source.backup(target)
        target.execute("DELETE FROM web_observation_state WHERE key='origin'")
        target.commit()
    vault = SessionRegistrationSecretStore()
    identity = load_or_create_installation_identity(vault, name)
    return PeerMembership(path=path, identity=identity, vault=vault)


def joined(tmp_path, certificates):
    a, b = member(tmp_path, 'A'), member(tmp_path, 'B')
    a.initialize_primary('Synthetic company')
    b.accept_invitation(a.invitation(), company='Synthetic company', primary_id='A')
    for name, peer in [('A', a), ('B', b)]:
        packet = peer.contact(certificate_pem=certificates[name]['certificate'].read_text(), url='https://127.0.0.1:3101')
        a.accept_contact(packet)
        b.accept_contact(packet)
    return a, b


def test_enrollment_separates_installations_and_binds_exact_certificates(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    assert a.group()['group_id'] == b.group()['group_id']
    assert a.member_id != b.member_id
    assert a.members(0) == ('A', 'B')
    assert a.authorize_certificate('B', certificates['B']['fingerprint'])
    assert not a.authorize_certificate('A', certificates['B']['fingerprint'])
    assert not a.authorize_session('uninvited')
    assert len({p['document']['origin'] for p in a.contacts()}) == 2
    with sqlite3.connect(a.path) as conn:
        text = repr(conn.execute('SELECT document FROM lan_peer_group').fetchall())
    assert a.invitation()['capability'] not in text


def test_company_name_or_second_group_cannot_reenroll_existing_installation(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    stranger = member(tmp_path, 'stranger')
    stranger.initialize_primary('Synthetic company')
    with pytest.raises(PermissionError, match='different group'):
        b.accept_invitation(stranger.invitation(), company='Synthetic company', primary_id='stranger')
    packet = stranger.contact(certificate_pem=certificates['B']['certificate'].read_text(), url='https://127.0.0.1:3101')
    with pytest.raises(PermissionError, match='capability'):
        a.accept_contact(packet)
    with pytest.raises(ValueError, match='Slot'):
        a.members(3)


def test_copied_database_has_no_access_under_new_identity_or_empty_vault(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    copied = member(tmp_path, 'copied', clone=b.path)
    assert not copied.authorize_session('A')
    restored = PeerMembership(path=b.path, identity=b.identity, vault=SessionRegistrationSecretStore())
    assert not restored.authorize_session('A')
    assert a.authorize_session('B')


def test_tampered_or_removed_contact_cannot_rejoin_by_replay(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    original = b.contact(certificate_pem=certificates['B']['certificate'].read_text(), url='https://127.0.0.1:3101')
    changed = deepcopy(original)
    changed['document']['member_id'] = 'A'
    with pytest.raises(PermissionError, match='capability'):
        a.accept_contact(changed)
    a.remove('B')
    assert not a.authorize_session('B')
    with pytest.raises(PermissionError, match='removed'):
        a.accept_contact(original)
    assert not a.resolve_certificate(certificates['B']['fingerprint'])


def test_contact_address_must_match_certificate(tmp_path, certificates):
    a, _ = joined(tmp_path, certificates)
    with pytest.raises(ValueError, match='address'):
        a.contact(certificate_pem=certificates['A']['certificate'].read_text(), url='https://192.0.2.4:3101')


def test_old_signed_contact_cannot_undo_an_address_change(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    old = next(p for p in a.contacts() if p['document']['member_id'] == 'B')
    new = b.contact(certificate_pem=certificates['B']['certificate'].read_text(), url='https://127.0.0.1:3102')
    b.accept_contact(new)
    a.accept_contact(new)
    with pytest.raises(PermissionError, match='Stale'):
        a.accept_contact(old)
    assert b.contact(certificate_pem=certificates['B']['certificate'].read_text(), url='https://127.0.0.1:3102') == new


def test_reusing_member_id_with_different_installation_key_is_rejected(tmp_path, certificates):
    a, b = joined(tmp_path, certificates)
    fresh_vault = SessionRegistrationSecretStore()
    impostor_path = tmp_path / 'impostor.db'
    # Fresh schema for this synthetic installation, never a production DB.
    with closing(sqlite3.connect(b.path)) as source, closing(sqlite3.connect(impostor_path)) as target:
        source.backup(target)
    impostor = PeerMembership(path=impostor_path,
        identity=load_or_create_installation_identity(fresh_vault, 'B'), vault=fresh_vault)
    fresh_vault.save(impostor._reference(b.group()['group_id']), b.invitation()['capability'])
    packet = impostor.contact(certificate_pem=certificates['B']['certificate'].read_text(), url='https://127.0.0.1:3101')
    with pytest.raises(PermissionError, match='identity changed'):
        a.accept_contact(packet)
