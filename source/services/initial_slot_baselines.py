"""Initialize missing first-use baselines from consistent local Web evidence.

This never resets/replaces an established epoch, changes accounting, or assigns
old unbound observations to a guessed epoch. All enabled slots commit together.
"""
from datetime import datetime
import json

from services.peer_change_events import committed
from services.peer_settings_history import SettingsHistory
from services.shared_settings_document import from_connection
from services.slot_epoch_store import SlotEpochStore
from services.slot_meter_continuity import counter_values
from services.reconciliation import reconcile_web_counters


class InitialBaselineRequired(ValueError):
    """Safe, user-facing explanation of evidence that needs attention."""


def ensure_initial_slot_baselines(path):
    store = SlotEpochStore(path)
    created = []
    with store._connection(write=True) as conn:
        devices = conn.execute('SELECT slot,host,serial FROM devices WHERE enabled=1 ORDER BY slot').fetchall()
        if not devices:
            raise InitialBaselineRequired('ต้นทางยังไม่มีเครื่องพิมพ์ที่เปิดใช้งาน กรุณาตั้งค่าเครื่องพิมพ์ก่อนเข้าร่วม')
        reviews = []
        for slot, host, serial in devices:
            prefix = f'เครื่องต้นทาง Slot {slot + 1}: '
            head = store._head(conn, slot)
            if head:
                if store._epoch(conn, head)['document']['baseline_event']['payload']['serial'] != serial:
                    raise InitialBaselineRequired(prefix + 'Serial เปลี่ยน กรุณาตรวจฐานมิเตอร์ก่อนเข้าร่วม')
                continue
            if not serial:
                raise InitialBaselineRequired(prefix + 'ยังไม่มี Serial กรุณาทดสอบและอ่านเครื่องพิมพ์ก่อนเข้าร่วม')
            if conn.execute('SELECT 1 FROM slot_meter_epochs WHERE device_slot=? LIMIT 1', (slot,)).fetchone():
                raise InitialBaselineRequired(prefix + 'พบฐานเดิมที่ยังไม่สมบูรณ์ กรุณาตรวจฐานมิเตอร์')
            rows = conn.execute('SELECT event_id FROM web_observations WHERE device_slot=? ORDER BY sequence', (slot,)).fetchall()
            if not rows:
                raise InitialBaselineRequired(prefix + 'ยังไม่มีผลอ่าน Web กรุณาอ่านเครื่องพิมพ์แล้วลองเข้าร่วมอีกครั้ง')
            origin = conn.execute("SELECT value FROM web_observation_state WHERE key='origin'").fetchone()
            schema = keys = previous = previous_at = None
            events = []
            try:
                for (event_id,) in rows:
                    event = store._event(conn, event_id)
                    values = counter_values(event)
                    payload, reading = event['payload'], event['payload']['reading']
                    if (payload['serial'], reading['host']) != (serial, host):
                        raise ValueError('identity')
                    if not origin or payload['origin'] != origin[0] or payload.get('meter_epoch_id'):
                        raise ValueError('existing shared history')
                    if any(c['confidence'] != 'verified' for c in reading['counters'] if c['canonical_field'].startswith('counter.')):
                        raise ValueError('unverified reading')
                    device_values = {c['canonical_field']: c['count'] for c in reading['counters'] if c['subject_type'] is None}
                    if not reconcile_web_counters(device_values).billing_safe:
                        raise ValueError('inconsistent totals')
                    if schema is not None and (schema != reading['schema_version'] or keys != values.keys()):
                        raise ValueError('counter mapping changed')
                    schema, keys = reading['schema_version'], values.keys()
                    at = datetime.fromisoformat(payload['observed_at'])
                    if previous is not None and (at < previous_at or any(values[k] < previous[k] for k in keys)
                                                or (at == previous_at and values != previous)):
                        raise ValueError('lower counter or clock conflict')
                    previous, previous_at = values, at
                    events.append(event)
                review = store._preview(conn, slot, events[-1]['id'], 'initial',
                    'system:first-use', 'สร้างฐานเริ่มต้นอัตโนมัติจากผลอ่าน Web ที่ตรวจสอบแล้ว')
            except (ValueError, KeyError, TypeError) as error:
                raise InitialBaselineRequired(prefix + 'ข้อมูล Web หรือประวัติมิเตอร์ต้องตรวจสอบ กรุณาเปิดตรวจฐานมิเตอร์บนต้นทาง') from error
            reviews.append(review)
        if reviews:
            history = SettingsHistory(store.path)
            before = from_connection(conn)
            head = history._state(conn, 'head')
            if not head or history._document(conn, head)['payload'] != before:
                head = history._append(conn, before, [head] if head else [], 'local_settings_baseline')
            for review in reviews:
                store._confirm(conn, review)
                created.append(review['slot'])
            revision = history._append(conn, from_connection(conn), [head], 'slot_baseline_initialized')
            conn.execute('INSERT INTO config_log(config_key,old_value,new_value,changed_at) VALUES(?,?,?,?)',
                ('initial_slot_baselines', '', json.dumps({'slots': created, 'revision': revision}), datetime.now().astimezone().isoformat()))
    if created:
        committed(store.path)
    return tuple(created)
