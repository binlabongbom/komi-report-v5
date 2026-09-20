"""TLS material and clients for enrolled LAN contacts, without global trust."""
import hashlib
from pathlib import Path
import ssl
from threading import RLock

from services.lan_tls import ensure_generated_certificate
from services.peer_https import PeerHTTPSClient
from services.peer_membership import PeerMembership
from services.installation_identity import load_or_create_installation_identity
from services.registration_vault import platform_registration_secret_store


def local_membership(*, path=None, vault=None):
    from database import get_db_path
    from contextlib import closing
    import sqlite3
    path = path or get_db_path()
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='installation_id'").fetchone()
    if not row or not row[0]:
        raise PermissionError('Local installation setup is incomplete')
    vault = vault if vault is not None else platform_registration_secret_store()
    identity = load_or_create_installation_identity(vault, row[0])
    return PeerMembership(path=path, identity=identity, vault=vault)


class PeerTransportFactory:
    def __init__(self, membership, *, runtime_root, hostname=None, lan_ips=None):
        self.membership = membership
        key = hashlib.sha256((str(membership.path) + ':' + membership.member_id).encode()).hexdigest()[:32]
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
