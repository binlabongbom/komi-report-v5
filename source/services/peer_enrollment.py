"""Reviewed LAN enrollment, with an isolated preview and one local commit.

The installation team handles undiscoverable groups. A company name/broadcast
is not authority; persistent source permission and a pinned TLS connection are.
No Host contract, registration privilege or printer secret is changed here.
"""
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

from database import get_db_path, config_write_transaction
from services.peer_membership import PeerMembership, _json, _unbase, _text
from services.peer_settings_history import SettingsHistory
from services.peer_setup_application import PeerSetupApplication
from services.peer_transport_factory import local_membership, PeerTransportFactory
from services.peer_sync_authorization import (
    open_pairing_window, consume_pairing_token, enrollment_grant, PeerSyncAuthorizationError,
)
from services.slot_epoch_exchange import SlotEpochExchange
from services.peer_contacts import PeerContactExchange
from services.registration_vault import platform_registration_secret_store, SessionRegistrationSecretStore
from services.installation_identity import load_or_create_installation_identity

ROUTE = '/api/v3/peer/enrollment'
MAX_BYTES = 8 * 1024 * 1024
# These are local enrollment/bootstrap tables only. Never copy registration,
# credentials, operational caches, financial records or an entire remote DB.
TABLES = ('settings', 'devices', 'price_history', 'peer_settings_revisions',
    'peer_settings_state', 'peer_settings_events', 'peer_settings_deliveries',
    'web_observation_state', 'web_observations', 'web_observation_outbox',
    'slot_meter_epochs', 'slot_meter_epoch_state', 'slot_meter_heads',
    'slot_meter_assignments', 'slot_meter_maxima', 'slot_meter_epoch_outbox',
    'shared_report_days', 'shared_report_months', 'shared_report_events',
    'lan_peer_group', 'lan_peer_members', 'lan_evidence_origins', 'config_log')


def _connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, timeout=30)


def _state(conn):
    digest = hashlib.sha256()
    for table in TABLES:
        rows = sorted((_json(list(row)) for row in conn.execute(f'SELECT * FROM {table}')))
        digest.update(_json([table, rows]).encode())
    return digest.hexdigest()


def _fresh(conn):
    for table in ('lan_peer_group', 'peer_settings_revisions', 'web_observations',
                  'billing_ledger', 'daily_meter_records', 'report_detail_archives', 'readings'):
        if conn.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
            raise ValueError('ใช้ฐานข้อมูลใหม่สำหรับเข้ากลุ่ม เก็บฐานเดิมไว้ตรวจสอบและให้ทีมติดตั้งช่วยกู้ข้อมูล')
    if conn.execute('SELECT 1 FROM devices WHERE enabled=1').fetchone():
        raise ValueError('ฐานนี้ตั้งค่าแล้ว ให้ใช้ฐานข้อมูลใหม่เพื่อเข้ากลุ่มโดยไม่เขียนทับข้อมูลเดิม')


def prepare_enrollment_source(access, *, runtime_root=None, host=None, port=37853):
    """Prepare reviewed source data under the installation's persistent policy."""
    from services.lan_tls import discover_primary_lan_ip
    from runtime_config import RUNTIME_SETTINGS
    path = access.path
    from services.initial_slot_baselines import ensure_initial_slot_baselines
    ensure_initial_slot_baselines(path)
    with closing(_connect(path)) as conn:
        cfg = dict(conn.execute('SELECT key,value FROM settings'))
        slots = {r[0] for r in conn.execute('SELECT slot FROM devices WHERE enabled=1')}
        reviewed = {r[0] for r in conn.execute('SELECT device_slot FROM slot_meter_heads')}
        if not slots or not slots <= reviewed:
            raise ValueError('อ่าน Web และตรวจฐานมิเตอร์ของทุก Slot ที่หน้าตรวจสอบมิเตอร์ก่อนเปิดแชร์กลุ่ม')
    access.initialize_primary(cfg.get('company_name', ''))
    host = host or discover_primary_lan_ip()
    factory = PeerTransportFactory(access, runtime_root=runtime_root or RUNTIME_SETTINGS.app_home, lan_ips=[host])
    access.accept_contact(factory.own_contact(host=host, port=port))
    SettingsHistory(path).observe_current()
    from services.peer_change_events import committed
    committed(path)
    return access


def open_continuous_pairing(*, always_open=True, vault=None, runtime_root=None, host=None, port=37853):
    access = prepare_enrollment_source(local_membership(vault=vault),
        runtime_root=runtime_root, host=host, port=port)
    open_pairing_window(access.member_id, always_open=always_open, continuous=True)
    return access


class EnrollmentSource:
    def __init__(self, access):
        self.access = access

    def call(self, token, requester, operation, data):
        access = self.access
        if len(_json(data).encode()) > MAX_BYTES:
            raise ValueError('Oversized enrollment request')
        try:
            binding = enrollment_grant(token, requester, access.member_id)
        except PeerSyncAuthorizationError:
            if operation != 'begin':
                raise
            consume_pairing_token(token, requester, access.member_id, enrollment_transfer=True)
            binding = None
        if operation == 'begin':
            if set(data) != {'member_id', 'public_key'}:
                raise ValueError('Invalid enrollment identity')
            _text(data['member_id']); _unbase(data['public_key'], 32)
            if data['member_id'] == access.member_id:
                raise PermissionError('Cannot enroll a copy of the source installation')
            # The app/agent enables persistent joining at startup. Bootstrap
            # only after a valid claim, without another source-side button.
            with access._connection() as conn:
                prepared = conn.execute('SELECT 1 FROM lan_peer_members WHERE member_id=?', (access.member_id,)).fetchone()
            if not prepared:
                prepare_enrollment_source(access)
            group = access.group()
            with access._connection() as conn:
                prior = conn.execute('SELECT document,revoked FROM lan_peer_members WHERE member_id=?', (data['member_id'],)).fetchone()
                own = conn.execute('SELECT document FROM lan_peer_members WHERE member_id=? AND revoked=0', (access.member_id,)).fetchone()
            if not own or (prior and (prior[1] or json.loads(prior[0])['document']['public_key'] != data['public_key'])):
                raise PermissionError('Existing member requires explicit recovery with a new installation')
            if binding is None:
                head = SettingsHistory(access.path).observe_current()
                binding = {**data, 'head': head, 'group_id': group['group_id']}
                enrollment_grant(token, requester, access.member_id, binding=binding)
            if any(binding[k] != data[k] for k in data) or binding['group_id'] != group['group_id']:
                raise PermissionError('Enrollment source or member changed')
            return {'invitation': access.invitation(), 'source': json.loads(own[0]), 'head': binding['head']}
        if not binding or binding['group_id'] != access.group()['group_id']:
            raise PermissionError('Start the approved enrollment first')
        history = SettingsHistory(access.path)
        if operation == 'settings' and set(data) == {'offset'}:
            result = history.export_page(head=binding['head'], offset=data['offset'], limit=32)
        elif operation == 'origins' and set(data) == {'after'}:
            result = PeerContactExchange(access=access, authorize=access.authorize_session).page(
                access.member_id, after=data['after'], historical=True)
        elif operation == 'epoch' and set(data) == {'epoch_id'}:
            # A setup grant only reads ancestry referenced by its pinned head.
            with access._connection() as conn:
                payload = history._document(conn, binding['head'])['payload']
                allowed, pending = set(), [r['epoch_id'] for r in payload.get('slot_epochs', [])]
                while pending:
                    key = pending.pop()
                    if key in allowed:
                        continue
                    allowed.add(key)
                    parent = conn.execute('SELECT parent_id FROM slot_meter_epochs WHERE id=?', (key,)).fetchone()
                    if parent and parent[0]:
                        pending.append(parent[0])
            if data['epoch_id'] not in allowed:
                raise PermissionError('Slot baseline is outside this setup approval')
            result = SlotEpochExchange(authorize=access.authorize_epoch, path=access.path).export(access.member_id, data['epoch_id'])
        elif operation == 'finish' and set(data) == {'contact'}:
            doc = data['contact']['document']
            if (doc['member_id'], doc['public_key']) != (binding['member_id'], binding['public_key']):
                raise PermissionError('Joining identity changed after approval')
            # Proof/signature are checked before a member is made active.
            result = {'member_id': access.accept_contact(data['contact']), 'committed': True}
            from services.peer_change_events import committed
            committed(access.path)
        else:
            raise ValueError('Unknown enrollment operation')
        enrollment_grant(token, requester, access.member_id, binding=binding)
        if len(_json(result).encode()) > MAX_BYTES:
            raise ValueError('Enrollment response exceeds page limit')
        return result


@dataclass
class EnrollmentPreview:
    temporary: object = field(repr=False)
    path: Path
    expected: str
    identity: object = field(repr=False)
    vault: object = field(repr=False)
    invitation: dict = field(repr=False)
    source: str
    head: str
    payload: dict
    request: object = field(repr=False)
    stage: Path
    contact: dict = field(repr=False)
    committed: bool = False
    candidate: dict | None = None

    def snapshot(self):
        """Compatibility view for the existing Wizard; history stays complete."""
        from datetime import date
        from services.secondary_setup import SECONDARY_SETUP_CONTRACT
        devices = []
        for device in self.payload['devices']:
            rows = [r for r in self.payload['price_history'] if r['slot'] == device['slot'] and r['effective_date'] <= date.today().isoformat()]
            price = max(rows, key=lambda r: r['effective_date']) if rows else {}
            devices.append({**device, 'prices': {k: price.get(k, 0.0) for k in ('a3_color', 'a3_bw', 'a4_color', 'a4_bw')}})
        return {'contract': SECONDARY_SETUP_CONTRACT, 'generated_at': '',
            'organization': {**self.payload['organization'], 'primary_installation_id': self.source},
            'settings': self.payload['settings'], 'devices': devices}

    def close(self):
        self.temporary.cleanup()

    def commit(self, *, local_settings=None, repository=None, devices=None):
        """Install validated setup/membership in one transaction; retry is safe.

        Remote completion may fail after the local commit. Keep the preview and
        retry finish, never roll back a member that the source may have accepted.
        """
        from services.setup_settings import LOCAL_KEYS
        if Path(get_db_path()).resolve() != self.path:
            raise ValueError('Database changed after enrollment review')
        local_settings = dict(local_settings or {})
        if self.candidate is not None:
            local_settings['peer_enrollment_pending'] = _json(self.candidate)
        if not set(local_settings) <= LOCAL_KEYS or any(not isinstance(v, str) for v in local_settings.values()):
            raise ValueError('Invalid local enrollment settings')
        if local_settings.get('installation_id', self.identity.installation_id) != self.identity.installation_id:
            raise ValueError('Installation changed after review')
        if not self.committed:
            self.vault.save(f'komi-report-v5:lan:{self.identity.installation_id}:{self.invitation["group_id"]}', self.invitation['capability'])
            def install(conn):
                if _state(conn) != self.expected:
                    raise ValueError('Local setup changed; review enrollment again')
                _fresh(conn)
                conn.execute('PRAGMA defer_foreign_keys=ON')
                for table in reversed(TABLES):
                    conn.execute(f'DELETE FROM {table}')
                for table in TABLES:
                    with closing(_connect(self.stage)) as stage:
                        rows = stage.execute(f'SELECT * FROM {table}').fetchall()
                    if rows:
                        conn.executemany(f'INSERT INTO {table} VALUES({",".join("?" for _ in rows[0])})', rows)
                for key, value in local_settings.items():
                    conn.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
                if conn.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('Incomplete setup ancestry')
            if repository is not None:
                from services.shared_settings_document import from_connection
                def verify(conn):
                    if from_connection(conn) != self.payload:
                        raise ValueError('เครื่องพิมพ์เปลี่ยนจากกลุ่มที่ตรวจ กรุณารับการตั้งค่าใหม่')
                repository.replace_all(list(devices), before_write=install, after_write=verify)
            else:
                with config_write_transaction() as conn:
                    install(conn)
            self.committed = True
        result = self.request('finish', {'contact': self.contact})
        if result != {'member_id': self.identity.installation_id, 'committed': True}:
            raise ValueError('Source did not confirm the enrolled member; retry')
        with config_write_transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key='peer_enrollment_pending'")
        from services.peer_change_events import committed
        committed(self.path)
        return self.head


def prepare_enrollment(request, *, vault=None, runtime_root=None, host=None, port=37853, cancelled=lambda: False):
    """Fetch and verify into a temporary local DB; live setup stays untouched."""
    from concurrent.futures import CancelledError
    from services.lan_tls import discover_primary_lan_ip
    from runtime_config import RUNTIME_SETTINGS
    def call(operation, data):
        if cancelled():
            raise CancelledError()
        result = request(operation, data)
        if cancelled():
            raise CancelledError()
        return result
    path = Path(get_db_path()).resolve()
    temporary = TemporaryDirectory(prefix='komi-enrollment-')
    stage = Path(temporary.name) / 'preview.sqlite3'
    try:
        with closing(_connect(path)) as conn, closing(sqlite3.connect(stage)) as copy:
            conn.execute('BEGIN')
            _fresh(conn)
            expected = _state(conn)
            row = conn.execute("SELECT value FROM settings WHERE key='installation_id'").fetchone()
            member = row[0] if row and row[0] else str(uuid4())
            conn.backup(copy)
        vault = vault or platform_registration_secret_store()
        identity = load_or_create_installation_identity(vault, member)
        start = call('begin', {'member_id': member, 'public_key': identity.public_key_base64url})
        invitation, source, head = start['invitation'], start['source'], start['head']
        with closing(_connect(stage)) as conn, conn:
            conn.execute("INSERT INTO settings VALUES('installation_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (member,))
        # Preview capability never enters a file. Only confirmed enrollment saves
        # it in the platform vault. The temporary DB contains public proofs only.
        access = PeerMembership(path=stage, identity=identity, vault=SessionRegistrationSecretStore())
        access.accept_invitation(invitation, company=invitation['company'], primary_id=invitation['primary_id'])
        source_id = access.accept_contact(source)
        exchange = PeerContactExchange(access=access, authorize=access.authorize_session)
        after = ''
        while True:
            page = call('origins', {'after': after})
            exchange.receive(source_id, page, after=after, historical=True)
            after = page['after']
            if not page['more']:
                break
        history, offset = SettingsHistory(stage), 0
        while True:
            page = call('settings', {'offset': offset})
            if page['head'] != head or page['offset'] != offset:
                raise ValueError('Source changed the approved settings head')
            history.receive_page(page, authorize=lambda revision, payload: access.authorize_settings(source_id, revision, payload), origin_member=source_id)
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        with access._connection() as conn:
            payload = history._document(conn, head)['payload']
        if payload['organization']['company_name'] != invitation['company']:
            raise ValueError('Setup company does not match the selected group')
        slots = {r['slot'] for r in payload['devices']}
        if slots != {r['slot'] for r in payload.get('slot_epochs', [])}:
            raise ValueError('Source must review every active Slot baseline before enrollment')
        epochs = SlotEpochExchange(authorize=access.authorize_epoch, path=stage)
        done = set()
        for reference in payload['slot_epochs']:
            chain, key = [], reference['epoch_id']
            while key and key not in done:
                bundle = call('epoch', {'epoch_id': key})
                if bundle['epoch']['id'] != key or key in {x['epoch']['id'] for x in chain} or len(chain) >= 1024:
                    raise ValueError('Invalid Slot baseline ancestry')
                chain.append(bundle)
                key = bundle['epoch']['document']['parent']
            for bundle in reversed(chain):
                done.add(epochs.receive(source_id, bundle))
        application = PeerSetupApplication(authorize=access.authorize_settings, authorize_epoch=access.authorize_epoch, path=stage)
        application.commit(application.preview(source_id, head, reason='Approved continuous LAN enrollment'))
        host = host or discover_primary_lan_ip()
        factory = PeerTransportFactory(access, runtime_root=runtime_root or RUNTIME_SETTINGS.app_home, storage_path=path, lan_ips=[host])
        contact = factory.own_contact(host=host, port=port)
        access.accept_contact(contact)
        return EnrollmentPreview(temporary, path, expected, identity, vault, invitation,
            source_id, head, payload, request, stage, contact)
    except BaseException:
        temporary.cleanup()
        raise
