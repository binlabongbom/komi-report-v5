"""Start a separate installation after key loss without erasing the old DB."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from migrations import validate_current_schema


def create_clean_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise FileExistsError('เลือกชื่อฐานข้อมูลใหม่ ข้อมูลเดิมจะไม่ถูกเขียนทับ')
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.komi-new-', suffix='.sqlite3', dir=destination.parent)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old, closing(sqlite3.connect(temporary)) as new:
            old.execute('BEGIN')
            validate_current_schema(old)
            schema = old.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name").fetchall()
            for (statement,) in schema:
                new.execute(statement)
            new.executemany('INSERT INTO schema_migrations VALUES(?,?,?)', old.execute('SELECT * FROM schema_migrations').fetchall())
            new.execute(f'PRAGMA user_version={int(old.execute("PRAGMA user_version").fetchone()[0])}')
            new.commit()
            validate_current_schema(new)
            if new.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('ฐานข้อมูลใหม่ตรวจสอบไม่ผ่าน')
        # Atomic exclusive publish. A concurrent file creation is never replaced.
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination
