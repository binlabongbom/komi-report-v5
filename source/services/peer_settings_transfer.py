"""Authenticated paged settings delivery on change/reconnect, without polling.

Receipt means complete durable history, not that a conflicted configuration was
applied. Application continues through PeerSetupApplication's reviewed decision.
"""
from services.peer_settings_history import SettingsHistory
from services.peer_settings_outbox import PeerSettingsOutbox, _peer


class PeerSettingsTransfer:
    def __init__(self, *, authorize, path=None):
        if not callable(authorize):
            raise TypeError('A verified settings scope authorizer is required')
        self.authorize = authorize
        self.history, self.outbox = SettingsHistory(path), PeerSettingsOutbox(path)

    def _allowed(self, member, revision, payload):
        _peer(member)
        if self.authorize(member, revision, payload) is not True:
            raise PermissionError('Member cannot exchange this company configuration')
        return True

    def receive(self, member, packet):
        result = self.history.receive_page(packet,
            authorize=lambda revision, payload: self._allowed(member, revision, payload), origin_member=member)
        if result['next_offset'] is None:
            from services.peer_change_events import committed
            committed(self.history.path)
        return {'head': result['remote_head'], 'next_offset': result['next_offset'],
                'committed': result['next_offset'] is None, 'status': result['status']}

    def contains(self, member, revision, document):
        """Verify a resume anchor after a peer restart or database restore."""
        from services.peer_settings_history import _validate_revision
        _validate_revision(revision, document)
        self._allowed(member, revision, document['payload'])
        with self.history._transaction() as conn:
            try:
                present = (self.history._document(conn, revision) == document
                           and bool(self.history._ancestors(conn, revision)))
            except ValueError:
                present = False
            self._allowed(member, revision, document['payload'])
        return {'revision': revision, 'present': present}

    def _remote_contains(self, member, transport, revision, document):
        self._allowed(member, revision, document['payload'])
        receipt = transport.settings_contains(revision, document)
        self._allowed(member, revision, document['payload'])
        if (not isinstance(receipt, dict) or set(receipt) != {'revision', 'present'}
                or receipt['revision'] != revision or type(receipt['present']) is not bool):
            raise ValueError('Invalid settings resume receipt')
        return receipt['present']

    def send(self, member, transport, *, reconnect=False, max_pages=64, page_size=32, cancelled=lambda: False):
        from concurrent.futures import CancelledError
        if type(max_pages) is not int or not 1 <= max_pages <= 256:
            raise ValueError('Invalid settings transfer budget')
        pending = self.outbox.next_delivery(member, reconnect=reconnect)
        if not pending and reconnect:
            # A restored receiver can lose even a previously acknowledged head.
            with self.history._transaction() as conn:
                head = self.history._state(conn, 'head')
                document = self.history._document(conn, head) if head else None
            if document and not self._remote_contains(member, transport, head, document):
                with self.history._transaction() as conn:
                    conn.execute('UPDATE peer_settings_deliveries SET acknowledged_at=NULL,page_offset=0,retry_at=0 '
                                 'WHERE peer_id=? AND revision=?', (member, head))
                pending = self.outbox.next_delivery(member, reconnect=True)
        if not pending:
            return None
        head = pending['revision']
        with self.history._transaction() as conn:
            saved = conn.execute('SELECT page_offset FROM peer_settings_deliveries WHERE peer_id=? AND revision=?', (member, head)).fetchone()
            offset = saved[0] if saved else 0
        try:
            if offset:
                anchor = self.history.export_page(head=head, offset=offset - 1, limit=1)
                revision, document = next(iter(anchor['revisions'].items()))
                if not self._remote_contains(member, transport, revision, document):
                    offset = 0
                    with self.history._transaction() as conn:
                        conn.execute('UPDATE peer_settings_deliveries SET page_offset=0 WHERE peer_id=? AND revision=?',
                                     (member, head))
            for _ in range(max_pages):
                if cancelled():
                    raise CancelledError()
                packet = self.history.export_page(head=head, offset=offset, limit=page_size)
                for revision, document in packet['revisions'].items():
                    self._allowed(member, revision, document['payload'])
                receipt = transport.settings_page(packet)
                for revision, document in packet['revisions'].items():
                    self._allowed(member, revision, document['payload'])
                if (not isinstance(receipt, dict) or set(receipt) != {'head', 'next_offset', 'committed', 'status'}
                        or receipt['head'] != head or receipt['next_offset'] != packet['next_offset']
                        or type(receipt['committed']) is not bool or receipt['committed'] != (packet['next_offset'] is None)
                        or (receipt['status'] == 'incomplete') != (packet['next_offset'] is not None)
                        or receipt['status'] not in {'incomplete', 'initial_review', 'in_sync', 'incoming_newer',
                                                     'local_newer', 'same_values', 'conflict', 'unrelated_history'}):
                    raise ValueError('Peer did not acknowledge the exact settings page')
                if receipt['committed']:
                    self.outbox.acknowledge(member, head)
                    return receipt
                offset = packet['next_offset']
                with self.history._transaction() as conn:
                    conn.execute('''INSERT INTO peer_settings_deliveries(peer_id,revision,page_offset) VALUES(?,?,?)
                        ON CONFLICT(peer_id,revision) DO UPDATE SET page_offset=MAX(page_offset,excluded.page_offset)''',
                        (member, head, offset))
            # No complete-head ACK for a partial transfer. Durable received pages
            # can be resent after restart without changing app configuration.
            return {'head': head, 'next_offset': offset, 'committed': False, 'status': 'incomplete'}
        except Exception as error:
            code = 'unauthorized' if isinstance(error, PermissionError) else 'invalid_response' if isinstance(error, ValueError) else 'transport'
            self.outbox.failed(member, head, error_code=code)
            raise
