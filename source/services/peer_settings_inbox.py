"""Apply an authorized descendant, or retain an explicit configuration review.

The caller coordinates this with idle meter collection and UI refresh. This
service never assumes a company from the sender name or silently joins a new
installation to a company. Incoming identities were stored with the history.
"""
from database import _open
from services.peer_settings_history import SettingsHistory
from services.peer_setup_application import PeerSetupApplication


class PeerSettingsInbox:
    def __init__(self, *, authorize, authorize_epoch):
        self.application = PeerSetupApplication(authorize=authorize, authorize_epoch=authorize_epoch)

    def pending(self, *, limit=32):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid incoming settings page size')
        with _open(commit=False) as conn:
            rows = conn.execute('''SELECT s.value,r.value FROM peer_settings_state r
                JOIN peer_settings_state s ON s.key='sender:' || r.value
                WHERE r.key LIKE 'review:%' ORDER BY r.key''')
            local = SettingsHistory._state(conn, 'head')
            ancestors = SettingsHistory._ancestors(conn, local)
            result = []
            for member, head in rows:
                if head not in ancestors:
                    result.append({'member': member, 'head': head,
                                   'status': SettingsHistory()._classify(conn, head)['status']})
                    if len(result) == limit:
                        break
            return result

    def prepare(self, member, head, *, resolve_conflict=False):
        with _open(commit=False) as conn:
            if SettingsHistory._state(conn, 'sender:' + head) != member:
                raise PermissionError('Configuration is not bound to this incoming member')
        return self.application.preview(member, head, reason='verified_peer_update', resolve_conflict=resolve_conflict)

    def apply_descendant(self, member, head):
        with _open(commit=False) as conn:
            status = SettingsHistory()._classify(conn, head)['status']
        if status != 'incoming_newer':
            # Initial installation, unrelated histories and conflict decisions
            # are left for the user's existing settings confirmation flow.
            return {'status': status, 'applied': False}
        preview = self.prepare(member, head)
        self.application.commit(preview)
        return {'status': 'in_sync', 'applied': True}
