"""Bounded exchange of installation-signed contacts over an enrolled session.

Discovery hints cannot call this into existence: both the HTTPS session and
every contact's group proof must verify. Local removals and newer generations
are retained when another computer has an older copy of the roster.
"""
import json

MAX_CONTACTS = 32
MAX_BYTES = 1024 * 1024


def _cursor(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('Invalid contact cursor')
    return value


class PeerContactExchange:
    def __init__(self, *, access, authorize):
        self.access, self.authorize = access, authorize

    def _allowed(self, member):
        if self.authorize(member) is not True:
            raise PermissionError('Contact exchange requires an enrolled session')

    def page(self, member, *, after='', limit=MAX_CONTACTS):
        self._allowed(member)
        _cursor(after)
        if type(limit) is not int or not 1 <= limit <= MAX_CONTACTS:
            raise ValueError('Invalid contact page size')
        # Fetch only one page; the number of company computers is not capped.
        with self.access._connection() as conn:
            rows = conn.execute('''SELECT member_id,document FROM lan_peer_members
                WHERE revoked=0 AND member_id>? ORDER BY member_id LIMIT ?''', (after, limit + 1)).fetchall()
        documents = [json.loads(row[1]) for row in rows[:limit]]
        self._allowed(member)
        return {'contacts': documents, 'after': rows[min(len(rows), limit) - 1][0] if rows else after,
                'more': len(rows) > limit}

    def receive(self, member, page, *, after=''):
        self._allowed(member)
        _cursor(after)
        if (not isinstance(page, dict) or set(page) != {'contacts', 'after', 'more'}
                or not isinstance(page['contacts'], list) or len(page['contacts']) > MAX_CONTACTS
                or type(page['more']) is not bool or len(json.dumps(page).encode()) > MAX_BYTES):
            raise ValueError('Invalid contact page')
        _cursor(page['after'])
        # Validate all signatures before any mutation, then make the page
        # atomic. Authorization is rechecked before committing the page.
        prepared = [self.access._checked_contact(packet) for packet in page['contacts']]
        names = [item[0]['document']['member_id'] for item in prepared]
        if (names != sorted(set(names)) or any(name <= after for name in names)
                or page['after'] != (names[-1] if names else after) or (page['more'] and not names)):
            raise ValueError('Contact page does not advance in order')
        with self.access._connection(write=True) as conn:
            for packet, fingerprint in prepared:
                document = packet['document']
                old = conn.execute('SELECT document,revoked FROM lan_peer_members WHERE member_id=?',
                    (document['member_id'],)).fetchone()
                if old:
                    previous = json.loads(old[0])['document']
                    if any(previous[k] != document[k] for k in ('origin', 'public_key')):
                        raise PermissionError('Conflicting installation identity in contact page')
                    if old[1] or previous['generation'] > document['generation']:
                        continue
                self.access._accept_checked_contact(conn, packet, fingerprint)
            self._allowed(member)
        return {'after': page['after'], 'more': page['more']}


class PeerContactPull:
    def __init__(self, *, exchange, member, transport):
        self.exchange, self.member, self.transport = exchange, member, transport
        self.after = ''
        self.complete = False

    def reset(self):
        self.after, self.complete = '', False

    def run(self, *, cancelled, max_pages=4):
        from concurrent.futures import CancelledError
        for _ in range(max_pages):
            if self.complete:
                return False
            if cancelled():
                raise CancelledError()
            self.exchange._allowed(self.member)
            page = self.transport.contacts(after=self.after)
            if cancelled():
                raise CancelledError()
            receipt = self.exchange.receive(self.member, page, after=self.after)
            self.after = receipt['after']
            self.complete = not receipt['more']
        return not self.complete
