"""Qt lifecycle for an enrolled LAN service; shared by Desktop and Agent.

Local file notifications refresh membership. They never periodically poll LAN
settings. Key generation, vault access and TLS preparation run off the UI
thread; the runtime attaches only while the collector is idle.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
from threading import Event

from PyQt6.QtCore import QObject, QFileSystemWatcher, QTimer, Qt, pyqtSignal

from services.peer_network import PeerNetworkNode
from services.peer_transport_factory import PeerTransportFactory, PeerRecoveryRequired, local_membership

log = logging.getLogger(__name__)
DEFAULT_PEER_PORT = 37853


class PeerNetworkRuntime(QObject):
    changed = pyqtSignal()
    _prepared = pyqtSignal(object)
    _peer_wake = pyqtSignal(str)

    def __init__(self, polling, *, runtime_root=None, membership_loader=local_membership,
                 host=None, port=DEFAULT_PEER_PORT, bind_host='0.0.0.0', enabled=None):
        super().__init__(polling)
        from database import get_db_path
        from runtime_config import RUNTIME_SETTINGS
        self.polling = polling
        self.path = Path(get_db_path()).resolve()
        self.runtime_root = runtime_root or RUNTIME_SETTINGS.app_home
        self.membership_loader, self.host, self.port = membership_loader, host, port
        self.bind_host = bind_host
        self.enabled = (os.environ.get('KOMI_DISCOVERY_DISABLED') != '1') if enabled is None else enabled
        self.state, self.error = 'not_enrolled', ''
        self._stopped = Event()
        self._pool = self._future = self._pending = None
        self._digest = None
        self._sessions = set()
        self._again = self._started = False
        self._discover_requested = True
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._changed)
        self._watcher.directoryChanged.connect(self._changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self.reload)
        self._prepared.connect(self._install, Qt.ConnectionType.QueuedConnection)
        self._peer_wake.connect(polling.peer_history.peer_reconnected, Qt.ConnectionType.QueuedConnection)
        polling.activity_changed.connect(self._install_pending, Qt.ConnectionType.QueuedConnection)

    def start(self):
        if self._started or not self.enabled or self._stopped.is_set():
            return
        self._started = True
        self._watch_paths()
        self.reload()

    def _watch_paths(self):
        paths = [str(self.path.parent), str(self.path), str(self.path) + '-wal']
        existing = set(self._watcher.files()) | set(self._watcher.directories())
        self._watcher.addPaths([p for p in paths if p not in existing and Path(p).exists()])

    def _changed(self, _path):
        if self._stopped.is_set():
            return
        self._watch_paths()
        self._debounce.start()

    def reload(self):
        if not self._started or self._stopped.is_set():
            return
        if self._future is not None:
            self._again = True
            return
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='komi-peer-enrollment')
        discover, self._discover_requested = self._discover_requested, False
        self._future = self._pool.submit(self._prepare, self._digest, discover)
        self._future.add_done_callback(self._completed)
        self.changed.emit()

    def _prepare(self, previous_digest, discover=False):
        if self._stopped.is_set():
            return None
        with closing(sqlite3.connect(self.path)) as conn:
            present = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lan_peer_group'").fetchone()
            if not present or not conn.execute('SELECT 1 FROM lan_peer_group').fetchone():
                return None
            rows = conn.execute('SELECT document,revoked FROM lan_peer_members ORDER BY member_id').fetchall()
            origins = conn.execute('SELECT document FROM lan_evidence_origins ORDER BY member_id').fetchall()
            group = conn.execute('SELECT document FROM lan_peer_group').fetchone()[0]
        digest = hashlib.sha256(json.dumps([group, rows, origins], sort_keys=True).encode()).hexdigest()
        if digest == previous_digest and not discover:
            return {'unchanged': True}
        access = self.membership_loader(path=self.path)
        access._secret(access.group())
        from services.secondary_setup import _active_ipv4_subnets
        from services.lan_tls import discover_primary_lan_ip
        interfaces = _active_ipv4_subnets()
        ips = [str(ip) for ip, _ in interfaces]
        host = self.host or discover_primary_lan_ip()
        factory = PeerTransportFactory(access, runtime_root=self.runtime_root, lan_ips=ips + [host])
        packet = factory.own_contact(host=host, port=self.port)
        access.accept_contact(packet)
        with access._connection() as conn:
            pending = conn.execute("SELECT value FROM settings WHERE key='peer_enrollment_pending'").fetchone()
        if pending and pending[0]:
            from services.secondary_setup import SecondaryPeerClient, SecondaryPeerCandidate, SecondarySetupError
            try:
                SecondaryPeerClient().finish_pending_enrollment(SecondaryPeerCandidate(**json.loads(pending[0])), access, contact=packet)
            except (SecondarySetupError, OSError, ValueError, KeyError) as error:
                raise PeerRecoveryRequired('enrollment_pending') from error
        if discover:
            from services.peer_contact_discovery import refresh_known_contacts
            refresh_known_contacts(access, interfaces, cancelled=self._stopped.is_set)
        contacts = access.contacts()
        members = [p['document']['member_id'] for p in contacts if access.authorize_session(p['document']['member_id'])]
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute('SELECT document,revoked FROM lan_peer_members ORDER BY member_id').fetchall()
            origins = conn.execute('SELECT document FROM lan_evidence_origins ORDER BY member_id').fetchall()
        digest = hashlib.sha256(json.dumps([group, rows, origins], sort_keys=True).encode()).hexdigest()
        return {'access': access, 'factory': factory, 'context': factory.context(server=True),
                'members': members, 'digest': digest}

    def _completed(self, future):
        try:
            self._prepared.emit(future)
        except RuntimeError:
            pass

    def _install(self, future):
        if future is not self._future:
            return
        self._future = None
        if self._stopped.is_set():
            return
        try:
            result = future.result()
            if result is None:
                self.state, self.error = 'not_enrolled', ''
            elif not result.get('unchanged'):
                self._pending = result
                self._install_pending()
        except Exception as error:
            self.state = 'unavailable'
            self.error = (error.code if isinstance(error, PeerRecoveryRequired) else
                          'authorization' if isinstance(error, PermissionError) else
                          'configuration' if isinstance(error, ValueError) else 'transport')
            log.warning('Peer enrollment runtime unavailable (%s)', self.error)
        self.changed.emit()
        if self._again:
            self._again = False
            self._debounce.start()

    def _install_pending(self):
        if self._stopped.is_set() or self._pending is None or self.polling.active_slots():
            return
        result, self._pending = self._pending, None
        factory = result['factory']
        node = self.polling.peer_network
        try:
            if node is None:
                node = PeerNetworkNode(access=result['access'], client_for=factory.client,
                    ready=lambda slot: not self.polling._stopped and not self.polling.is_paused,
                    on_wake=self._peer_wake.emit)
                self.polling.bind_peer_network(node, address=(self.bind_host, self.port),
                    context=result['context'], members=result['members'])
            else:
                if node.member_id != result['access'].member_id:
                    raise PermissionError('Local installation changed; restart required')
                node.client_for = factory.client
                node._server.tls_context = result['context']
                node.election.invalidate()
                for member in self._sessions - set(result['members']):
                    self.polling.peer_history.detach(member)
                for member in result['members']:
                    if member != node.member_id:
                        session = node.session(member)
                        # A roster/address change is a new event even within
                        # the same process boot. Wake existing peers so they
                        # learn a newly approved third computer promptly.
                        session.reconnected()
                        self.polling.peer_history.attach(session)
            self._sessions = set(result['members']) - {node.member_id}
            self._digest = result['digest']
            self.state, self.error = 'connected', ''
        except Exception as error:
            self.state = 'unavailable'
            self.error = 'authorization' if isinstance(error, PermissionError) else 'transport'
            log.warning('Peer enrollment could not attach (%s)', self.error)
        self.changed.emit()

    def network_recovered(self):
        if self._stopped.is_set():
            return
        # Refresh local material and previously enrolled contact addresses even
        # if membership rows have not changed. Discovery never enrolls a PC.
        self._digest = None
        self._discover_requested = True
        if self.polling.peer_network is not None:
            self.polling.peer_network.election.invalidate()
        self.reload()

    def stop(self, *, wait=False):
        self._stopped.set()
        self._debounce.stop()
        paths = self._watcher.files() + self._watcher.directories()
        if paths:
            self._watcher.removePaths(paths)
        remaining = int(self._future is not None and not self._future.done())
        if self._future is not None:
            self._future.cancel()
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
        self._pending = None
        return remaining
