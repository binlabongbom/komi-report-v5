"""TLS material and clients for enrolled LAN contacts, without global trust."""
import hashlib
import json
from pathlib import Path
import ssl
from threading import RLock

from services.lan_tls import ensure_generated_certificate
from services.peer_https import PeerHTTPSClient
from services.peer_membership import PeerMembership
from services.installation_identity import load_or_create_installation_identity
from services.registration_vault import platform_registration_secret_store


class PeerRecoveryRequired(PermissionError):
    """Non-secret reason for stopping enrollment rather than replacing identity."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def local_membership(*, path=None, vault=None):
    from database import get_db_path
    from contextlib import closing
    import sqlite3
    from komi_snmp_profiler.credential_store import CredentialStoreError
    path = Path(path or get_db_path()).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='installation_id'").fetchone()
        group_row = conn.execute('SELECT document FROM lan_peer_group WHERE singleton=1').fetchone()
        own = conn.execute('SELECT document,revoked FROM lan_peer_members WHERE member_id=?',
                           (row[0] if row else '',)).fetchone()
        origins = conn.execute('SELECT document FROM lan_evidence_origins WHERE member_id=?',
                               (row[0] if row else '',)).fetchall()
    if not row or not row[0]:
        raise PermissionError('Local installation setup is incomplete')
    group = json.loads(group_row[0]) if group_row else None
    if group and group.get('local_installation_id') != row[0]:
        raise PeerRecoveryRequired('installation_mismatch')
    if own and own[1]:
        raise PeerRecoveryRequired('member_removed')
    try:
        vault = vault if vault is not None else platform_registration_secret_store()
        # A restored DB must not silently generate a replacement key under the
        # old member ID. Initial setup retains its existing creation behavior.
        try:
            identity = load_or_create_installation_identity(vault, row[0],
                create_if_missing=not bool(group or own or origins))
        except (PermissionError, ValueError) as error:
            raise PeerRecoveryRequired('identity_missing') from error
        for (raw,) in origins + ([(own[0],)] if own else []):
            if json.loads(raw)['document']['public_key'] != identity.public_key_base64url:
                raise PeerRecoveryRequired('identity_changed')
        access = PeerMembership(path=path, identity=identity, vault=vault)
        if group:
            try:
                access._secret(group)
            except (PermissionError, ValueError) as error:
                raise PeerRecoveryRequired('group_secret_missing') from error
            for (raw,) in origins + ([(own[0],)] if own else []):
                access._checked_contact(json.loads(raw), require_current=False)
        return access
    except CredentialStoreError as error:
        raise PeerRecoveryRequired('vault_unavailable') from error


class PeerTransportFactory:
    def __init__(self, membership, *, runtime_root, hostname=None, lan_ips=None, storage_path=None):
        self.membership = membership
        key = hashlib.sha256((str(storage_path or membership.path) + ':' + membership.member_id).encode()).hexdigest()[:32]
        self.material = ensure_generated_certificate(Path(runtime_root) / 'peer-transport' / key,
            hostname=hostname, lan_ips=lan_ips, client_auth=True)
        self._lock = RLock()
        self._contexts = {}

    def own_contact(self, *, host, port):
        return self.membership.contact(certificate_pem=self.material.certificate_path.read_text('ascii'),
            url=f'https://{host}:{port}')

    def context(self, *, server=False):
        # Every connection still checks exact fingerprint and current membership.
        # Trust anchors here are only approved leaf certificates, never a company
        # CA with a private key copied to every PC and never the OS trust store.
        contacts = self.membership.contacts()
        certificates = sorted({packet['document']['certificate'] for packet in contacts})
        certificates.append(self.material.certificate_path.read_text('ascii'))
        key = (server, hashlib.sha256(''.join(certificates).encode()).hexdigest())
        with self._lock:
            if key not in self._contexts:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.verify_mode = ssl.CERT_REQUIRED
                context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
                context.load_verify_locations(cadata='\n'.join(certificates))
                context.load_cert_chain(str(self.material.certificate_path), str(self.material.private_key_path))
                self._contexts = {k: v for k, v in self._contexts.items() if k[0] != server}
                self._contexts[key] = context
            return self._contexts[key]

    def refresh_server_trust(self, context):
        certificates = [packet['document']['certificate'] for packet in self.membership.contacts()]
        if certificates:
            # OpenSSL does not remove trust anchors in place. The live exact
            # fingerprint resolver denies removed/rotated contacts immediately.
            context.load_verify_locations(cadata='\n'.join(certificates))

    def client(self, member):
        if not self.membership.authorize_session(member):
            raise PermissionError('Peer transport requires current enrollment')
        packet = next((p for p in self.membership.contacts() if p['document']['member_id'] == member), None)
        if packet is None:
            raise PermissionError('Peer contact was removed')
        return PeerHTTPSClient(packet['document']['url'], member=member, context=self.context(),
            authorize_certificate=self.membership.authorize_certificate, timeout=20)
