"""Exercise installed database initialization using synthetic records only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

mode, source, db_file, snapshot = sys.argv[1:]
sys.path.insert(0, source)
import database
from migrations import CURRENT_SCHEMA_VERSION

path = Path(db_file)
assert Path(os.environ['KOMI_DB_PATH']).resolve() == path.resolve()
database.init_db()
with sqlite3.connect(path) as conn:
    if mode == 'seed':
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('ci_synthetic_marker','synthetic-only')")
        conn.execute("INSERT INTO devices(slot,name,host) VALUES(0,'Synthetic printer','192.0.2.10')")
        conn.commit()
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION
    names = ('readings', 'devices', 'daily_meter_records', 'daily_subject_records', 'billing_ledger')
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names if name in tables}
    if mode in ('seed', 'upgrade'):
        assert conn.execute("SELECT value FROM settings WHERE key='ci_synthetic_marker'").fetchone() == ('synthetic-only',)
        assert conn.execute("SELECT name,host FROM devices WHERE slot=0").fetchone() == ('Synthetic printer','192.0.2.10')
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
if mode == 'seed':
    baseline = {'schema_version': version, 'counts': counts, 'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()}
    Path(snapshot).write_text(json.dumps(baseline), encoding='utf-8')
    shutil.copyfile(path, path.with_suffix('.original-copy'))
elif mode == 'upgrade':
    baseline = json.loads(Path(snapshot).read_text(encoding='utf-8'))
    assert baseline['counts'] == {key: counts[key] for key in baseline['counts']}
    assert version >= baseline['schema_version']
    assert hashlib.file_digest(path.with_suffix('.original-copy').open('rb'), 'sha256').hexdigest() == baseline['sha256']
print(json.dumps({'mode': mode, 'schema_version': version, 'counts': counts, 'integrity': 'ok', 'foreign_keys': 'ok'}))

