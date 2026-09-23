"""Sidebar role from existing election decisions; rendering never elects/probes."""
from i18n import tr
import sqlite3


def reader_role_text(polling):
    pending = tr('กำลังตรวจสอบบทบาท', 'Checking role')
    primary = tr('กำลังเป็นผู้อ่านหลัก', 'Acting as primary reader')
    receiver = tr('กำลังเป็นผู้รับข้อมูล', 'Receiving shared data')
    repository = getattr(polling, 'repository', None)
    if repository is None:
        return pending, ''
    slots = [device.slot for device in repository.list(enabled_only=True)]
    if not slots:
        return tr('ยังไม่มีเครื่องพิมพ์ที่เปิดใช้งาน', 'No enabled printers'), ''
    shared = getattr(polling, 'shared_reads', None)
    runtime = getattr(polling, 'peer_network_runtime', None)
    if runtime is not None and ((shared is None and getattr(runtime, '_future', None) is not None)
                               or runtime.state == 'unavailable'):
        return pending, tr('กำลังตรวจการเชื่อมต่อสมาชิก', 'Checking member connections')
    if shared is None:
        if runtime is not None and runtime.state != 'not_enrolled':
            return pending, ''
        return primary, tr('เครื่องนี้อ่านเครื่องพิมพ์โดยตรง', 'This computer reads printers directly')
    election = shared.router.election
    history = getattr(polling, 'peer_history', None)
    unavailable = {row['member'] for row in history.snapshot() if row.get('error')} if history else set()
    roles, details = [], []
    for slot in slots:
        try:
            owner = election.owner(shared.current_scope(slot))
        except (ValueError, PermissionError, LookupError, sqlite3.Error):
            owner = None
        if owner in unavailable:
            owner = None
        role = pending if owner is None else primary if owner == election.member_id else receiver
        roles.append(role)
        details.append(f'Slot {slot + 1}: {role}')
    if pending in roles:
        label = pending
    elif all(role == primary for role in roles):
        label = primary
    elif all(role == receiver for role in roles):
        label = receiver
    else:
        label = tr('กำลังอ่านและรับข้อมูล', 'Reading and receiving data')
    details.append(tr('บทบาทล่าสุดที่ระบบเลือก อัปเดตตามรอบอ่านและการเชื่อมต่อ',
                      'Last selected role; updated by reading and connection activity'))
    return label, '\n'.join(details)
