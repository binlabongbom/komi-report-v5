"""Forget transient physical-meter state after a reviewed Slot boundary."""


def invalidate_device_runtime(conn, slot):
    # Keep credentials and immutable history. A raw total from the previous
    # epoch must not suppress the first Web read after a same-serial reset.
    conn.execute('''UPDATE devices SET connection_status='pending',last_checked_at=NULL,
        last_success_at=NULL,last_error='',last_total=NULL WHERE slot=?''', (slot,))


def polling_scope(device):
    from database import _open
    with _open(commit=False) as conn:
        row = conn.execute('SELECT epoch_id FROM slot_meter_heads WHERE device_slot=?', (device.slot,)).fetchone()
    return device.host, device.serial, row[0] if row else None
