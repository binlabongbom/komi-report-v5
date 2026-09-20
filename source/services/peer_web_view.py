"""Present committed shared Web snapshots without rereading the printer.

This refreshes live Web/User views and invalidates shared report projections.
It never rewrites closed records or fabricates a successful Web time from SNMP.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from services.shared_web_read import SharedWebRead
from services.slot_meter_continuity import counter_values, _number
from services.web_observations import validate_event


def latest_shared_views(path):
    """Use indexed per-epoch maxima; do not scan years or open archived blobs."""
    result = []
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('BEGIN')
        devices = conn.execute('''SELECT d.slot,d.serial,d.host,h.epoch_id FROM devices d
            JOIN slot_meter_heads h ON h.device_slot=d.slot WHERE d.enabled=1 ORDER BY d.slot''').fetchall()
        for slot, serial, host, epoch in devices:
            maxima = conn.execute('SELECT counter_key,value_json,event_id FROM slot_meter_maxima WHERE epoch_id=?', (epoch,)).fetchall()
            device_maxima = [(key, value, event) for key, value, event in maxima if json.loads(key)[1] is None]
            if not device_maxima:
                device_maxima = maxima  # Account-only Web models still have real saved readings.
            if not device_maxima:
                continue
            selected = next((row for row in device_maxima if json.loads(row[0])[0] == 'counter.total.total'), device_maxima[0])
            stored = conn.execute('SELECT document_json,archive_id FROM web_observations WHERE event_id=?', (selected[2],)).fetchone()
            if not stored or stored[1] is not None or not stored[0]:
                continue  # Old detailed data is fetched only on explicit request.
            event = json.loads(stored[0])
            validate_event(event)
            p = event['payload']
            if (p['slot'], p['serial'], p['reading']['host']) != (slot, serial, host):
                continue
            values = counter_values(event)
            if any(key not in values or values[key] != _number(json.loads(value)) for key, value, _ in device_maxima):
                continue  # Do not invent a single fresh reading from conflicting samples.
            result.append({'slot': slot, 'serial': serial, 'host': host, 'epoch_id': epoch,
                           'event_id': event['id'], 'reading': SharedWebRead._reading(event)})
    return result


def refresh_shared_reports_and_views(path, *, backfill=True):
    from services.shared_report_index import backfill_batch
    indexed = backfill_batch(path) if backfill else 0
    return latest_shared_views(path), indexed == 32


class PeerWebViewRuntime(QObject):
    _wake = pyqtSignal()
    _finished = pyqtSignal(object)

    def __init__(self, polling):
        super().__init__(polling)
        from database import get_db_path
        self.polling, self.path = polling, Path(get_db_path()).resolve()
        self._pool = self._future = None
        self._pending = self._stopped = False
        self._backfill_needed = True
        self._wake.connect(self._schedule, Qt.ConnectionType.QueuedConnection)
        self._finished.connect(self._apply, Qt.ConnectionType.QueuedConnection)
        polling.peer_history.history_received.connect(self.notify)
        polling.shared_settings_applied.connect(self.notify)
        polling.activity_changed.connect(self._idle, Qt.ConnectionType.QueuedConnection)

    def notify(self, *_args):
        self._wake.emit()

    def _idle(self):
        if self._pending:
            self._schedule()

    def _schedule(self):
        if self._stopped:
            return
        self._pending = True
        if self._future is not None or self.polling.active_slots():
            return
        self._pending = False
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='komi-peer-view')
        self._future = self._pool.submit(refresh_shared_reports_and_views, self.path, backfill=self._backfill_needed)
        self._future.add_done_callback(self._completed)

    def _completed(self, future):
        try:
            self._finished.emit(future)
        except RuntimeError:
            pass

    def _apply(self, future):
        if future is not self._future:
            return
        self._future = None
        if self._stopped:
            return
        from database import get_db_path
        from services.runtime_snapshots import runtime_snapshots
        if Path(get_db_path()).resolve() != self.path:
            return
        if self.polling.active_slots():
            self._pending = True
            return
        try:
            rows, more = future.result()
            self._backfill_needed = more
            self._pending |= more
            refreshed = set()
            for row in rows:
                # Configuration application runs on this same Qt owner thread.
                # A delayed worker result cannot overwrite a newly adopted Slot.
                scope = self.polling.peer_network.current_scope(row['slot'])
                if (scope.serial, scope.epoch_id) != (row['serial'], row['epoch_id']):
                    self._pending = True
                    continue
                before = runtime_snapshots.get(row['slot'])
                if before is not None and before.event_id == row['event_id']:
                    continue
                snapshot = runtime_snapshots.update(row['slot'], row['reading'], serial=row['serial'],
                    epoch_id=row['epoch_id'], event_id=row['event_id'], preserve_newer=True)
                if snapshot is not before:
                    self.polling.device_updated.emit(row['slot'])
                    refreshed.add(row['slot'])
            # A newly received historical event can change reports while the
            # maximum/live snapshot remains identical. Invalidate those views too.
            with closing(sqlite3.connect(self.path)) as conn:
                slots = [r[0] for r in conn.execute('SELECT device_slot FROM slot_meter_heads')]
            for slot in set(slots) - refreshed:
                self.polling.device_updated.emit(slot)
        except (ValueError, PermissionError, OSError, sqlite3.Error):
            # Committed evidence remains available for review/recovery. A view
            # refresh is not permission to re-read or modify financial records.
            import logging
            logging.getLogger(__name__).warning('Shared Web view is awaiting valid Slot evidence')
        if self._pending:
            self._schedule()

    def stop(self, *, wait=False):
        self._stopped = True
        remaining = int(self._future is not None and not self._future.done())
        if self._future is not None:
            self._future.cancel()
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
        return remaining
