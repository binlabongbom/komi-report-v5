"""Local LAN enrollment, separate from Host registration and license rights.

A group capability is released only by the approved setup handoff. Discovery
and company names cannot create membership. Each contact additionally proves
possession of its installation key and its own TLS key. A database contains one
group; the OS vault holds the capability, so copying a DB does not copy access.

This does not claim global company uniqueness across isolated LANs. That needs
an authoritative company binding; a local group is not a replacement license.
"""
import base64
from contextlib import closing, contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
from threading import RLock
import secrets
import sqlite3
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.x509.oid import ExtendedKeyUsageOID

from services.reader_jobs import ReadScope, VerifiedReader

FORMAT = 'komi.lan.enrollment.v1'
CONTACT = 'komi.lan.member.v1'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _unbase(value, size):
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError('Invalid member key encoding')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid member key encoding') from error
    if len(raw) != size:
        raise ValueError('Invalid member key length')
    return raw


def _text(value, *, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Invalid member identity')
    return value


def _hex(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid group identity')
    return value


class PeerMembership:
    """Persistent approved contacts; callers do not pass permissive callbacks.

    Construct explicitly after local identity/vault initialization. No network
    access, group creation or global OS trust modification occurs here.
    """
    def __init__(self, *, path, identity, vault):
        self.path = Path(path).resolve()
        self.identity, self.vault = identity, vault
        self.member_id = _text(identity.installation_id)
        self._key_lock = RLock()
        self._key_cache = None
        # Schema belongs to the normal backed-up migration path. Loading trust
        # must never silently create a partial DB or repair schema corruption.
        with self._connection() as conn:
            conn.execute('SELECT singleton,document FROM lan_peer_group LIMIT 0')
            conn.execute('SELECT member_id,origin,fingerprint,document,revoked FROM lan_peer_members LIMIT 0')

    @contextmanager
    def _connection(self, *, write=False):
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5)) as conn, conn:
            if write:
                conn.execute('BEGIN IMMEDIATE')
            yield conn

    def group(self):
        with self._connection() as conn:
            row = conn.execute('SELECT document FROM lan_peer_group WHERE singleton=1').fetchone()
        return json.loads(row[0]) if row else None

    def _reference(self, group_id):
        return f'komi-report-v5:lan:{self.member_id}:{group_id}'

    def _secret(self, group):
        if not group or group['local_installation_id'] != self.member_id:
            raise PermissionError('This database is not enrolled for this installation')
        # Avoid a Windows Credential Manager call for every counter/event in a
        # page. A runtime owns one immutable group capability; revocation is
        # checked live in the member table on every authorized operation.
        with self._key_lock:
            if self._key_cache is None or self._key_cache[0] != group['group_id']:
                value = self.vault.load(self._reference(group['group_id']))
                if not value:
                    raise PermissionError('LAN membership is unavailable in the local OS vault')
                self._key_cache = (group['group_id'], _unbase(value, 32))
            return self._key_cache[1]

    def initialize_primary(self, company):
        """Called from explicit setup enrollment, never from a LAN beacon."""
        company = _text(' '.join(company.split()), maximum=160)
        existing = self.group()
        if existing:
            self._secret(existing)
            if existing['company'] != company:
                raise PermissionError('This installation already belongs to another company')
            return existing
        invitation = {'format': FORMAT, 'group_id': secrets.token_hex(32),
                      'company': company, 'primary_id': self.member_id,
                      'capability': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')}
        return self.accept_invitation(invitation, company=company, primary_id=self.member_id)

    def accept_invitation(self, invitation, *, company, primary_id):
        """After the existing approved, pinned setup handoff and local review.

        ``company`` and ``primary_id`` are the reviewed source, not values taken
        independently from an unsolicited invitation. Never merge two groups.
        """
        if (not isinstance(invitation, dict) or set(invitation) != {
                'format', 'group_id', 'company', 'primary_id', 'capability'}
                or invitation['format'] != FORMAT or invitation['company'] != company
                or invitation['primary_id'] != primary_id):
            raise PermissionError('Enrollment differs from the approved setup source')
        _text(company, maximum=160)
        _text(primary_id)
        _hex(invitation['group_id'])
        _unbase(invitation['capability'], 32)
        group = {key: invitation[key] for key in ('group_id', 'company', 'primary_id')}
        group['local_installation_id'] = self.member_id
        with self._connection(write=True) as conn:
            row = conn.execute('SELECT document FROM lan_peer_group WHERE singleton=1').fetchone()
            if row:
                current = json.loads(row[0])
                if current != group:
                    raise PermissionError('This computer already belongs to a different group')
                if not hmac.compare_digest(self._secret(current), _unbase(invitation['capability'], 32)):
                    raise PermissionError('Group capability changed; explicit recovery is required')
                return current
            # A vault failure aborts the DB transaction. An orphan vault entry
            # after a disk failure cannot authorize a group without the DB row.
            self.vault.save(self._reference(group['group_id']), invitation['capability'])
            conn.execute('INSERT INTO lan_peer_group VALUES(1,?)', (_json(group),))
        return group

    def invitation(self):
        """Sensitive: only the single-use approved setup route may return this."""
        group = self.group()
        key = self._secret(group)
        return {'format': FORMAT, **{k: group[k] for k in ('group_id', 'company', 'primary_id')},
                'capability': base64.urlsafe_b64encode(key).decode().rstrip('=')}

    def contact(self, *, certificate_pem, url):
        group = self.group()
        key = self._secret(group)
        with self._connection(write=True) as conn:
            origin = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
            if origin is None:
                import uuid
                origin = (str(uuid.uuid4()),)
                conn.execute("INSERT INTO web_observation_state VALUES('origin',?)", origin)
        document = {'format': CONTACT, 'group_id': group['group_id'], 'member_id': self.member_id,
                    'origin': origin[0], 'public_key': self.identity.public_key_base64url,
                    'certificate': certificate_pem, 'url': url}
        with self._connection() as conn:
            old = conn.execute('SELECT document FROM lan_peer_members WHERE member_id=?', (self.member_id,)).fetchone()
        previous = json.loads(old[0]) if old else None
        if previous and {k: v for k, v in previous['document'].items() if k != 'generation'} == document:
            return previous
        document['generation'] = previous['document']['generation'] + 1 if previous else 1
        self._validate_contact(document)
        signature = self.identity.sign(_json(document).encode())
        signed = {'document': document, 'signature': signature}
        return {**signed, 'proof': hmac.new(key, _json(signed).encode(), hashlib.sha256).hexdigest()}

    @staticmethod
    def _validate_contact(document):
        if (not isinstance(document, dict) or set(document) != {'format', 'group_id', 'member_id',
                'origin', 'public_key', 'certificate', 'url', 'generation'} or document['format'] != CONTACT):
            raise ValueError('Invalid peer contact')
        if type(document['generation']) is not int or not 1 <= document['generation'] < 2**63:
            raise ValueError('Invalid contact generation')
        _hex(document['group_id'])
        _text(document['member_id'])
        _text(document['origin'])
        _unbase(document['public_key'], 32)
        pem = _text(document['certificate'], maximum=16384)
        url = urlsplit(_text(document['url'], maximum=300))
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment or not url.port):
            raise ValueError('Peer contact requires a direct HTTPS LAN address')
        address = ipaddress.IPv4Address(url.hostname)
        if address.is_multicast or address.is_unspecified:
            raise ValueError('Invalid peer address')
        cert = x509.load_pem_x509_certificate(pem.encode('ascii'))
        now = datetime.now(UTC)
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValueError('Peer certificate is expired or not yet valid')
        try:
            if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                raise ValueError('A peer contact must use a leaf certificate')
            eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            if (ExtendedKeyUsageOID.SERVER_AUTH not in eku or ExtendedKeyUsageOID.CLIENT_AUTH not in eku
                    or address not in san.get_values_for_type(x509.IPAddress)):
                raise ValueError('Peer certificate does not authorize this address and both TLS roles')
        except x509.ExtensionNotFound as error:
            raise ValueError('Peer certificate lacks required constraints') from error
        return cert.fingerprint(hashes.SHA256()).hex()

    def accept_contact(self, packet):
        packet, fingerprint = self._checked_contact(packet)
        with self._connection(write=True) as conn:
            return self._accept_checked_contact(conn, packet, fingerprint)

    def _checked_contact(self, packet):
        if not isinstance(packet, dict) or set(packet) != {'document', 'signature', 'proof'}:
            raise ValueError('Invalid peer enrollment proof')
        group = self.group()
        key = self._secret(group)
        signed = {k: packet[k] for k in ('document', 'signature')}
        if not hmac.compare_digest(_hex(packet['proof']), hmac.new(key, _json(signed).encode(), hashlib.sha256).hexdigest()):
            raise PermissionError('Peer does not possess this group capability')
        document = packet['document']
        fingerprint = self._validate_contact(document)
        if document['group_id'] != group['group_id']:
            raise PermissionError('Peer belongs to another group')
        try:
            Ed25519PublicKey.from_public_bytes(_unbase(document['public_key'], 32)).verify(
                _unbase(packet['signature'], 64), _json(document).encode())
        except InvalidSignature as error:
            raise PermissionError('Peer installation proof is invalid') from error
        if document['member_id'] == self.member_id and document['public_key'] != self.identity.public_key_base64url:
            raise PermissionError('Installation identity collision')
        return packet, fingerprint

    @staticmethod
    def _accept_checked_contact(conn, packet, fingerprint):
        document = packet['document']
        old = conn.execute('SELECT document,revoked FROM lan_peer_members WHERE member_id=?', (document['member_id'],)).fetchone()
        if old:
            previous = json.loads(old[0])['document']
            if old[1] or any(previous[k] != document[k] for k in ('origin', 'public_key')):
                raise PermissionError('Peer identity changed or was removed; explicit recovery is required')
            if (document['generation'] < previous['generation'] or
                    (document['generation'] == previous['generation'] and _json(packet) != old[0])):
                raise PermissionError('Stale or conflicting peer contact')
            if _json(packet) == old[0]:
                return document['member_id']
        conn.execute('''INSERT INTO lan_peer_members(member_id,origin,fingerprint,document) VALUES(?,?,?,?)
            ON CONFLICT(member_id) DO UPDATE SET fingerprint=excluded.fingerprint,document=excluded.document''',
            (document['member_id'], document['origin'], fingerprint, _json(packet)))
        return document['member_id']

    def remove(self, member):
        if member == self.member_id:
            raise ValueError('Cannot remove the local identity through a peer operation')
        with self._connection(write=True) as conn:
            conn.execute('UPDATE lan_peer_members SET revoked=1 WHERE member_id=?', (member,))

    def contacts(self, *, active_only=True):
        self._secret(self.group())
        with self._connection() as conn:
            rows = conn.execute('SELECT document FROM lan_peer_members' + (' WHERE revoked=0' if active_only else '') + ' ORDER BY member_id').fetchall()
        return [json.loads(row[0]) for row in rows]

    def authorize_session(self, member):
        try:
            self._secret(self.group())
            with self._connection() as conn:
                row = conn.execute('SELECT document FROM lan_peer_members WHERE member_id=? AND revoked=0', (member,)).fetchone()
            if not row:
                return False
            self._validate_contact(json.loads(row[0])['document'])
            return True
        except (ValueError, PermissionError):
            return False

    def resolve_certificate(self, fingerprint):
        with self._connection() as conn:
            row = conn.execute('SELECT member_id FROM lan_peer_members WHERE fingerprint=? AND revoked=0', (fingerprint,)).fetchone()
        return row[0] if row and self.authorize_session(row[0]) else None

    def authorize_certificate(self, member, fingerprint):
        return self.resolve_certificate(fingerprint) == member

    def members(self, slot):
        if type(slot) is not int or slot not in range(3):
            raise ValueError('Invalid shared Slot')
        return tuple(p['document']['member_id'] for p in self.contacts()
                     if self.authorize_session(p['document']['member_id']))

    def authorize_event(self, member, event=None):
        if not self.authorize_session(member):
            return False
        if event is None:
            return True
        from services.web_observations import validate_event
        validate_event(event)
        p = event['payload']
        # History can relay evidence from another approved member, including a
        # removed one. Removal blocks future sessions, not historical records.
        with self._connection() as conn:
            origin = conn.execute('SELECT 1 FROM lan_peer_members WHERE origin=?', (p['origin'],)).fetchone()
        return bool(origin) and type(p['slot']) is int and p['slot'] in range(3)

    def authorize_epoch(self, member, epoch):
        from services.slot_meter_continuity import validate_epoch
        document = validate_epoch(epoch)
        return self.authorize_event(member, document['baseline_event'])

    def authorize_settings(self, member, revision, payload):
        from services.peer_settings_history import _validate_payload
        _hex(revision)
        _validate_payload(payload)
        return self.authorize_session(member)

    def authorize_amendment(self, member, document):
        from services.peer_billing_amendments import validate_document
        validate_document(document)
        return self.authorize_session(member)

    def current_scope(self, slot):
        if type(slot) is not int or slot not in range(3):
            raise ValueError('Invalid shared Slot')
        group = self.group()
        self._secret(group)
        with self._connection() as conn:
            device = conn.execute('SELECT serial FROM devices WHERE slot=? AND enabled=1', (slot,)).fetchone()
            epoch = conn.execute('SELECT epoch_id FROM slot_meter_heads WHERE device_slot=?', (slot,)).fetchone()
            revision = conn.execute("SELECT value FROM peer_settings_state WHERE key='head'").fetchone()
        if not device or not epoch or not revision:
            raise PermissionError('Shared Slot requires reviewed setup and meter baseline')
        scope = ReadScope(group['group_id'], slot, device[0], revision[0], epoch[0])
        scope.document()
        return scope

    def authorize_reader(self, member, slot):
        if not self.authorize_session(member):
            raise PermissionError('Reader is not an approved active member')
        with self._connection() as conn:
            row = conn.execute('SELECT origin FROM lan_peer_members WHERE member_id=? AND revoked=0', (member,)).fetchone()
        if not row:
            raise PermissionError('Reader membership changed')
        return VerifiedReader(member, row[0], self.current_scope(slot))
