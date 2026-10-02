"""Read-only member display evidence. It never elects, probes or changes roles."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
from time import monotonic
import sqlite3

from i18n import tr
from services.computer_names import computer_directory, local_computer_name


def newest_time(values):
    valid = []
    for value in values:
        if not value:
            continue
        try:
            valid.append((datetime.fromisoformat(str(value)).astimezone(), str(value)))
        except (ValueError, TypeError):
            pass
    return max(valid, default=(None, ''), key=lambda pair: pair[0])[1]


def display_time(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime('%d/%m/%Y %H:%M:%S')
    except (ValueError, TypeError):
        return tr('ยังไม่มีข้อมูล', 'No data yet')


def latest_local_data(polling):
    from services.runtime_snapshots import runtime_snapshots
    times = []
    for device in polling.repository.list(enabled_only=True):
        times.append(getattr(device, 'last_success_at', None))
        snapshot = runtime_snapshots.get(device.slot)
        if snapshot and (not getattr(device, 'serial', '') or snapshot.serial == device.serial):
            times.append(snapshot.collected_at)
    return newest_time(times)


def member_evidence(path):
    """Load metadata and durable acknowledgements off the UI thread."""
    result = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as conn:
        deadline = monotonic() + 2
        conn.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        names = computer_directory(conn)['members']
        for member, origin in conn.execute('SELECT member_id,origin FROM lan_peer_members WHERE revoked=0'):
            # An origin timestamp proves a read; a receipt proves that the peer
            # saved that observation. A sync session alone proves neither.
            read = conn.execute('''SELECT o.observed_at FROM web_observations o
                JOIN devices d ON d.slot=o.device_slot AND d.serial=o.device_serial AND d.enabled=1
                WHERE o.origin_id=? ORDER BY julianday(o.observed_at) DESC LIMIT 1''', (origin,)).fetchone()
            received = conn.execute('''SELECT o.observed_at FROM web_observation_receipts r
                JOIN web_observations o ON o.event_id=r.event_id
                JOIN devices d ON d.slot=o.device_slot AND d.serial=o.device_serial AND d.enabled=1
                WHERE r.peer_id=? ORDER BY julianday(o.observed_at) DESC LIMIT 1''', (member,)).fetchone()
            contact = conn.execute('SELECT MAX(acknowledged_at) FROM web_observation_receipts WHERE peer_id=?', (member,)).fetchone()
            result[member] = dict(name=names.get(member, member),
                data_at=newest_time((read[0] if read else '', received[0] if received else '')),
                connected_at=contact[0] if contact else '')
    return result


def member_rows(polling, evidence):
    devices = polling.repository.list(enabled_only=True)
    node = getattr(polling, 'peer_network', None)
    local = getattr(node, 'member_id', 'local')
    shared = getattr(polling, 'shared_reads', None)
    runtime = getattr(polling, 'peer_network_runtime', None)
    runtime_ready = runtime is None or getattr(runtime, 'state', '') in ('connected', 'not_enrolled')
    if shared is None and getattr(runtime, '_future', None) is not None:
        runtime_ready = False
    states = {row['member']: row for row in polling.peer_history.snapshot()}
    unavailable = {member for member, state in states.items() if state.get('error')}
    owners, allowed = {}, {}
    for d in devices:
        try:
            owners[d.slot] = (shared.router.election.owner(shared.current_scope(d.slot)) if shared
                              else local if runtime_ready else None)
            allowed[d.slot] = set(node.access.members(d.slot)) | {local} if node else {local}
        except (ValueError, PermissionError, LookupError, sqlite3.Error):
            owners[d.slot], allowed[d.slot] = None, set()
        if not runtime_ready or owners.get(d.slot) in unavailable:
            owners[d.slot] = None
    jobs = shared.snapshot() if shared else []
    active_readers = {job['slot']: job['reader'] for job in jobs if job['phase'] == 'reading'}
    result = []
    for member in sorted(set(evidence) | {local}, key=lambda key: (key != local, evidence.get(key, {}).get('name', key))):
        own = member == local
        ev, state = evidence.get(member, {}), states.get(member, {})
        failed = bool(state.get('error'))
        primary, receiving, details = [], [], []
        for d in devices:
            if member not in allowed.get(d.slot, ()):
                continue
            name = f'Slot {d.slot + 1} · {d.name}'
            if owners.get(d.slot) == member:
                primary.append(d.slot)
                details.append(tr('อ่าน: ', 'Read: ') + name)
            elif owners.get(d.slot):
                receiving.append(d.slot)
                source = evidence.get(owners[d.slot], {}).get('name', owners[d.slot])
                if owners[d.slot] == local:
                    source = local_computer_name()
                details.append(tr('รับ: ', 'Receive: ') + name + tr(' จาก ', ' from ') + source)
        if own and getattr(polling, 'is_paused', False):
            role = tr('หยุดอ่านข้อมูล', 'Reading paused')
        elif failed or not runtime_ready:
            role = tr('รอตรวจสอบบทบาท', 'Role awaiting verification')
        elif primary and receiving:
            role = tr('ผู้อ่านหลัก / ผู้รับข้อมูล', 'Primary reader / receiver')
        elif primary:
            role = tr('ผู้อ่านหลัก', 'Primary reader')
        elif receiving:
            role = tr('ผู้รับข้อมูล', 'Receiver')
        else:
            role = tr('รอตรวจสอบบทบาท', 'Role awaiting verification')
        reading = [f'Slot {slot + 1}' for slot, reader in active_readers.items() if reader == member]
        if reading:
            details.append(tr('กำลังอ่าน: ', 'Reading now: ') + ', '.join(reading))
        contact = newest_time((ev.get('connected_at'), state.get('last_success')))
        connection = (tr('คอมนี้', 'This computer') if own else
            tr('รอเชื่อมต่อใหม่', 'Awaiting reconnection') if failed else
            tr('กำลังรับส่ง', 'Transferring') if state.get('status') == 'receiving' else
            tr('เชื่อมต่อสำเร็จล่าสุด', 'Last successful connection') if contact else
            tr('ยังไม่ยืนยันการเชื่อมต่อ', 'Connection not confirmed'))
        result.append(dict(member=member, name=local_computer_name() + tr(' · คอมนี้', ' · This computer') if own else ev.get('name', member),
            role=role, details='\n'.join(details) or '—', connection=connection,
            connected_at=contact if not own else '', data_at=latest_local_data(polling) if own else ev.get('data_at', '')))
    return result
