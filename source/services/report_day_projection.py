"""Bounded, content-validated daily read models for the Users preview.

The current transaction supplies per-device/day mutation tokens maintained by
SQLite triggers. Unchanged days reuse compressed immutable read models; only
changed days fetch source rows again. Archives remain verified by their ordinary
reader, and amendments are applied before caching hot rows. The cache is private
to this process and never persists serialized objects to disk.
"""
from collections import OrderedDict, defaultdict
from datetime import date, timedelta
import pickle
from threading import RLock
import zlib

from database import get_db_path, report_read_checkpoint


class DayProjectionCache:
    def __init__(self, *, max_rows=4_000_000, max_bytes=32 * 1024 * 1024, max_entries=2400):
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.max_entries = max_entries
        self.entries = OrderedDict()
        self.rows = self.bytes = self.hits = self.misses = 0
        self.lock = RLock()

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.rows = self.bytes = self.hits = self.misses = 0

    def find(self, key, signature):
        with self.lock:
            previous = self.entries.get(key)
            if previous is not None and previous[0] == signature:
                self.entries.move_to_end(key)
                self.hits += 1
                return previous[1]
        return None

    @staticmethod
    def restore(payload):
        # Exclusively process-local bytes serialized below from our own
        # immutable records, never bytes from a database/file/network.
        return pickle.loads(zlib.decompress(payload))

    def read(self, key, signature, loader):
        payload = self.find(key, signature)
        if payload is not None:
            return self.restore(payload)
        # Only publish complete blocks; cancellation/errors leave prior data
        # inaccessible under the new content signature.
        result = tuple(loader())
        report_read_checkpoint()
        payload = zlib.compress(pickle.dumps(result, protocol=5), level=1)
        byte_count = len(payload)
        with self.lock:
            self.misses += 1
            previous = self.entries.pop(key, None)
            if previous is not None:
                self.rows -= previous[2]
                self.bytes -= len(previous[1])
            if len(result) <= self.max_rows and byte_count <= self.max_bytes:
                self.entries[key] = signature, payload, len(result)
                self.rows += len(result)
                self.bytes += byte_count
            while (self.rows > self.max_rows or self.bytes > self.max_bytes
                   or len(self.entries) > self.max_entries):
                _key, (_signature, evicted, count) = self.entries.popitem(last=False)
                self.rows -= count
                self.bytes -= len(evicted)
        return result


DAY_PROJECTIONS = DayProjectionCache()


def _missing_ranges(missing):
    """Coalesce adjacent missing days so extending a month to a year is cheap."""
    ranges = []
    for slot, day_text in sorted(missing):
        day = date.fromisoformat(day_text)
        if ranges and ranges[-1][0] == slot and ranges[-1][2] + timedelta(days=1) == day:
            ranges[-1] = (slot, ranges[-1][1], day)
        else:
            ranges.append((slot, day, day))
    return ranges


def iter_projected_days(conn, kind, query, parameters, columns, decoder, archived=(),
                        slots=None, *, start=None, end=None, include_revisions=True):
    """Yield (immutable record, frozen period), preserving detail precedence."""
    from services.report_detail_amendment import _key, current_revisions
    revisions = current_revisions(conn, kind, slots, start=start, end=end,
                                  include_rows=include_revisions)
    excluded = {}
    for key in revisions:
        excluded.setdefault((key[0], key[3]), set()).add(key)
    generation = conn.execute('SELECT token FROM report_projection_generation WHERE singleton=1').fetchone()[0]
    clauses, values = ['kind=?'], [kind]
    if slots:
        clauses.append('device_slot IN (' + ','.join('?' for _ in slots) + ')')
        values.extend(slots)
    if start is not None:
        clauses.append('record_date>=?')
        values.append(start.isoformat())
    if end is not None:
        clauses.append('record_date<=?')
        values.append(end.isoformat())
    tokens = conn.execute('SELECT device_slot,record_date,token FROM report_day_revisions WHERE '
                         + ' AND '.join(clauses) + ' ORDER BY record_date,device_slot', values).fetchall()
    namespace = (str(get_db_path().resolve()), generation, kind, tuple(columns), decoder)
    selected, missing = [], []
    for slot, day, token in tokens:
        report_read_checkpoint()
        ignored = excluded.get((slot, day), set())
        key, signature = (*namespace, slot, day), (token, tuple(sorted(ignored)))
        payload = DAY_PROJECTIONS.find(key, signature)
        selected.append((slot, day, key, signature, payload))
        if payload is None:
            missing.append((slot, day))
    prepared = defaultdict(list)
    if missing:
        # A full miss uses the ordinary query and ordering. On a refresh SQLite
        # restricts reads to dirty keys, never fetching unchanged row payloads.
        if len(missing) == len(selected):
            rows = conn.execute(query, parameters)
        else:
            ranges = _missing_ranges(missing)
            wanted = ' OR '.join('(device_slot=? AND record_date BETWEEN ? AND ?)' for _ in ranges)
            rows = conn.execute(f'SELECT * FROM ({query}) WHERE ({wanted})',
                                [*parameters, *(value for slot, first, last in ranges
                                  for value in (slot, first.isoformat(), last.isoformat()))])
        slot_index, day_index = columns.index('device_slot'), columns.index('record_date')
        for index, row in enumerate(rows):
            if index % 256 == 0:
                report_read_checkpoint()
            pair = row[slot_index], row[day_index]
            ignored = excluded.get(pair)
            if ignored and _key(kind, dict(zip(columns, row))) in ignored:
                continue
            prepared[pair].append(decoder(row))
    for slot, day, key, signature, payload in selected:
        report_read_checkpoint()
        if payload is not None:
            records = DAY_PROJECTIONS.restore(payload)
        else:
            records = DAY_PROJECTIONS.read(key, signature,
                                           lambda: prepared.pop((slot, day), ()))
        for record in records:
            yield record, None
    for item in archived:
        if revisions and _key(kind, item['row']) in revisions:
            continue
        yield decoder(tuple(item['row'][key] for key in columns)), item['period']
    if include_revisions:
        for item in revisions.values():
            yield decoder(tuple(item['row'][key] for key in columns)), item['period']
