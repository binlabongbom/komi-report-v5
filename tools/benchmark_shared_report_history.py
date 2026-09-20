"""Synthetic source-only report benchmark; never opens the installed customer DB.

Run with PYTHONPATH=source. No listener, installer, Host request or real printer.
One sample/day gives the same compact daily row count as frequent daily reads.
"""
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import perf_counter

import database
from komi_snmp_profiler.models import MeterReading, WebCounterValue, Confidence, WebAuthState
from services.device_config import DeviceConfigRepository
from services.raw_counter_history import load_raw_counter_history
from services.report_snapshot import load_report_snapshot
from services.slot_epoch_store import SlotEpochStore
from services.subject_history import load_subject_history
from services.web_observations import WebObservationStore


def run(*, users=100, days=365):
    previous = database.get_db_path()
    with TemporaryDirectory(prefix='komi-shared-report-benchmark-') as root:
        try:
            path = Path(root) / 'synthetic.sqlite3'
            database.set_db_path(path)
            database.init_db()
            database.set_cfg('billing_day', '31')
            with database._open() as conn:
                conn.execute("INSERT INTO devices(slot,name,host,serial,enabled,updated_at) VALUES(0,'Synthetic','192.0.2.10','SYNTHETIC-ONLY',1,'2025-01-01')")
            origin = datetime(2025, 1, 1, 10, tzinfo=UTC)
            def reading(day):
                counters = [WebCounterValue('counter.user.total.total', 'Total', 1000 + day * (n + 1),
                    'User', f'user[{n}].total', Confidence.VERIFIED, 'user', str(n), f'Synthetic user {n}') for n in range(users)]
                counters.append(WebCounterValue('counter.total.total', 'Total', 100000 + day * users,
                    'Device', 'device.total', Confidence.VERIFIED))
                at = origin + timedelta(days=day)
                return at, MeterReading(host='192.0.2.10', collected_at=at.isoformat(), counters=tuple(counters),
                                       source='synthetic-benchmark', auth_state=WebAuthState.ADMIN)
            store = WebObservationStore(path)
            at, r = reading(0)
            anchor = store.record(0, r, serial='SYNTHETIC-ONLY', printer_name='Synthetic', at=at)
            epochs = SlotEpochStore(path)
            epoch = epochs.confirm(epochs.preview(0, anchor['id'], operation='initial', actor='benchmark', reason='Synthetic baseline'))
            began = perf_counter()
            for day in range(1, days):
                at, r = reading(day)
                store.record(0, r, serial='SYNTHETIC-ONLY', printer_name='Synthetic', at=at, epoch_id=epoch)
            indexing = perf_counter() - began
            started = perf_counter()
            with database.report_read_database(path, cancelled=Event()):
                subjects = load_subject_history([0], only_periods=((date(2025, 1, 1), date(2025, 1, 31)),
                                                                  (date(2025, 12, 1), date(2025, 12, 31))))
            subjects_seconds = perf_counter() - started
            started = perf_counter()
            with database.report_read_database(path, cancelled=Event()):
                raw = load_raw_counter_history([0], period_start=date(2025, 1, 1), period_end=date(2025, 12, 31))
            raw_seconds = perf_counter() - started
            started = perf_counter()
            snapshot = load_report_snapshot(0, ('2025-12-01', '2025-12-31'), cache=None, subject_cache=None,
                repository=DeviceConfigRepository(), cancelled=Event(), database_path=path)
            snapshot_seconds = perf_counter() - started
            return {'users': users, 'days': days, 'index_seconds': round(indexing, 3),
                    'subject_two_periods_seconds': round(subjects_seconds, 3), 'subject_rows': len(subjects),
                    'raw_year_seconds': round(raw_seconds, 3), 'raw_rows': len(raw),
                    'overview_snapshot_seconds': round(snapshot_seconds, 3),
                    'overview_users': len(snapshot.data['subjects']), 'database_bytes': path.stat().st_size}
        finally:
            database.set_db_path(previous)


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
