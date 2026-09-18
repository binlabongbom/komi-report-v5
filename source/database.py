# ═══════════════════════════════════════════════════════════
# database.py  —  จัดการ SQLite database และ parser ไฟล์
# ═══════════════════════════════════════════════════════════

import copy
import hashlib
import hmac
import json
import logging
import shutil
import sqlite3
import tempfile
import threading
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from config import DB_PATH, DEFAULT_PRICE, MAX_HIST, SLOT_NAMES
from migrations import (
    apply_migrations,
    backup_before_migration,
    require_supported_schema_version,
    schema_version,
    validate_current_schema,
)
from parser import (  # noqa: F401
    PARSER_REGISTRY,
    compute_diff,
    detect_parser,
    format_warnings,
    has_warnings,
    parse_file,
    parse_for_slot,
)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# path ของ database (อาจเปลี่ยนได้จากหน้า ตั้งค่า)
# ──────────────────────────────────────────────────────────
_db_path = DB_PATH
_read_cache_lock = threading.RLock()
_all_readings_cache: dict[int, list] = {}
_monthly_summary_cache: dict[int, dict] = {}


def _clear_read_caches(slot: int | None = None):
    """Clear derived reading caches after writes or database path changes."""
    with _read_cache_lock:
        if slot is None:
            _all_readings_cache.clear()
            _monthly_summary_cache.clear()
        else:
            _all_readings_cache.pop(slot, None)
            _monthly_summary_cache.pop(slot, None)


_USAGE_RESET_TABLES = (
    "web_observation_receipts",
    "web_observation_outbox",
    "web_observations",
    "legacy_history_items",
    "billing_ledger",
    "daily_subject_records",
    "daily_raw_counter_records",
    "daily_meter_records",
    "legacy_history_imports",
    "price_snapshot",
    "config_log",
    "readings",
)

_USAGE_RESET_SEQUENCES = (
    "legacy_history_items",
    "billing_ledger",
    "daily_subject_records",
    "daily_raw_counter_records",
    "daily_meter_records",
    "legacy_history_imports",
    "price_snapshot",
    "config_log",
    "readings",
)

_FACTORY_RESET_TABLES = (
    "web_observation_receipts",
    "web_observation_outbox",
    "web_observations",
    "web_observation_state",
    "peer_settings_deliveries",
    "peer_settings_events",
    "peer_settings_state",
    "peer_settings_revisions",
    "registration_attempt_history",
    "registration_outbox",
    "registration_profile",
    "v52_telemetry_success",
    "v52_telemetry_outbox",
    "v52_runtime_state",
    "legacy_history_items",
    "billing_ledger",
    "daily_subject_records",
    "daily_raw_counter_records",
    "parser_mapping_change_log",
    "parser_mapping_overrides",
    "cost_category_history",
    "price_history",
    "daily_meter_records",
    "legacy_history_imports",
    "price_snapshot",
    "config_log",
    "readings",
    "devices",
    "settings",
)

_FACTORY_RESET_SEQUENCES = (
    "registration_attempt_history",
    "legacy_history_items",
    "billing_ledger",
    "daily_subject_records",
    "daily_raw_counter_records",
    "parser_mapping_change_log",
    "cost_category_history",
    "price_history",
    "daily_meter_records",
    "legacy_history_imports",
    "price_snapshot",
    "config_log",
    "readings",
)


def _create_billing_ledger_immutability_triggers(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS billing_ledger_no_update
           BEFORE UPDATE ON billing_ledger
           BEGIN SELECT RAISE(ABORT, 'billing ledger is append-only'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS billing_ledger_no_delete
           BEFORE DELETE ON billing_ledger
           BEGIN SELECT RAISE(ABORT, 'billing ledger is append-only'); END"""
    )


def _ensure_first_run_setting_defaults(connection: sqlite3.Connection) -> None:
    for slot in range(3):
        defaults = {
            f"machine_type_{slot}": "summary",
            f"multiplier_{slot}": "1.0",
            f"parser_{slot}": "",
        }
        for key, value in defaults.items():
            connection.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value),
            )


def set_db_path(path: Path):
    """เปลี่ยน path ของ database (ต้องเรียกก่อน init_db)"""
    global _db_path, _cfg_cache
    _db_path = Path(path)
    _cfg_cache = None
    _clear_read_caches()

def get_db_path():
    return _db_path


def copy_database_for_first_run(destination: Path) -> Path:
    """Create a verified SQLite copy at a new first-run destination.

    The active database remains untouched. Existing destination files are
    rejected so choosing a creation path can never overwrite customer data.
    """
    source = Path(_db_path).expanduser().resolve(strict=False)
    target = Path(destination).expanduser().resolve(strict=False)
    if source == target:
        return target
    if not source.is_file():
        raise FileNotFoundError(f"ไม่พบฐานข้อมูลต้นทาง: {source}")
    if target.exists():
        raise FileExistsError(
            "Path นี้มีไฟล์อยู่แล้ว กรุณาเลือกชื่อใหม่ หรือใช้ปุ่มนำเข้าฐานข้อมูลเดิม"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}-", suffix=".pending", dir=target.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        source_uri = f"{source.as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_conn, closing(
            sqlite3.connect(temporary_path)
        ) as target_conn:
            source_conn.backup(target_conn)
            result = target_conn.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("Database copy failed integrity check")
        temporary_path.replace(target)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return target

def _conn():
    """[V4.5] เปิด connection + เปิด foreign_keys + WAL mode"""
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


@contextmanager
def _open(commit: bool = True):
    """[V4.5] context manager — ensure connection close + transaction rollback on error"""
    conn = _conn()
    try:
        yield conn
        if commit:
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
# INIT DATABASE — สร้างตารางถ้ายังไม่มี
# ══════════════════════════════════════════════════════════
def _date_to_iso(date_str: str) -> str:
    """[V4.5] แปลง date string หลาย format → ISO 'YYYY-MM-DD' เพื่อใช้ sort/filter"""
    if not date_str:
        return ""
    s = str(date_str).strip().split()[0] if str(date_str).strip() else ""
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def init_db():
    """
    [V4.5] สร้าง/อัปเกรด database — ใช้ transaction + PRAGMA user_version
    รองรับ: DB ใหม่ (สร้างเปล่า) และ DB เก่า v1.x → v4.x (migration อัตโนมัติ)
    Schema version: 9; additive migrations are recorded in schema_migrations.
    """
    before_version = schema_version(_db_path)
    require_supported_schema_version(before_version)
    backup_path = backup_before_migration(_db_path, from_version=before_version)
    if backup_path:
        log.info("database backup created before migration: %s", backup_path)
    with _open() as c:
        # SQLite DDL participates in this explicit transaction. Any failed
        # migration or schema validation leaves the original DB untouched.
        c.execute("BEGIN IMMEDIATE")
        # ─── ตรวจสอบก่อนว่าตาราง readings มีอยู่แล้วหรือยัง ───
        tbl_exists = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='readings'"
        ).fetchone()

        if not tbl_exists:
            # DB ใหม่ — สร้างตารางพร้อม schema ล่าสุด
            c.execute("""CREATE TABLE readings(
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                slot          INTEGER NOT NULL,
                machine_name  TEXT,
                serial        TEXT,
                read_date     TEXT,
                read_date_iso TEXT,
                billing_month TEXT,
                mode          TEXT,
                data_json     TEXT,
                imported_at   TEXT,
                file_name     TEXT,
                parser_name   TEXT DEFAULT ''
            )""")
        else:
            # DB เก่า — ตรวจสอบและเพิ่ม column ที่ขาด (migration)
            existing_cols = [row[1] for row in
                             c.execute("PRAGMA table_info(readings)").fetchall()]

            # เพิ่ม billing_month ถ้าไม่มี (upgrade จาก v1.x → v2.x)
            if "billing_month" not in existing_cols:
                c.execute("ALTER TABLE readings ADD COLUMN billing_month TEXT")
                # backfill ใช้ imported_at แทน datetime.now() (ตรงความหมายกว่า)
                old_rows = c.execute("SELECT id, read_date, imported_at FROM readings").fetchall()
                for rec_id, rd, imp_at in old_rows:
                    bm = None
                    if rd:
                        for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                            try:
                                bm = datetime.strptime(rd.strip(), fmt).strftime("%Y-%m")
                                break
                            except ValueError:
                                pass
                    if not bm and imp_at:
                        try:
                            bm = datetime.strptime(imp_at[:10], "%Y-%m-%d").strftime("%Y-%m")
                        except (ValueError, TypeError):
                            pass
                    if not bm:
                        bm = "0000-00"  # ระบุชัดว่า unknown
                    c.execute("UPDATE readings SET billing_month=? WHERE id=?", (bm, rec_id))

            # เพิ่ม parser_name ถ้าไม่มี (upgrade → v3.x)
            if "parser_name" not in existing_cols:
                c.execute("ALTER TABLE readings ADD COLUMN parser_name TEXT DEFAULT ''")

            # [V4.5] เพิ่ม read_date_iso ถ้าไม่มี + backfill
            if "read_date_iso" not in existing_cols:
                c.execute("ALTER TABLE readings ADD COLUMN read_date_iso TEXT")
                old_rows = c.execute("SELECT id, read_date FROM readings").fetchall()
                for rec_id, rd in old_rows:
                    iso = _date_to_iso(rd)
                    if iso:
                        c.execute("UPDATE readings SET read_date_iso=? WHERE id=?", (iso, rec_id))

        # ─── ตาราง settings ───
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            key   TEXT PRIMARY KEY,
            value TEXT
        )""")

        # ─── ตาราง price_snapshot (บันทึก snapshot ของราคาในแต่ละการอัพ) ───
        c.execute("""CREATE TABLE IF NOT EXISTS price_snapshot(
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            reading_id    INTEGER,
            price_json    TEXT,
            saved_at      TEXT,
            FOREIGN KEY(reading_id) REFERENCES readings(id) ON DELETE CASCADE
        )""")

        # ─── ตาราง config_log (บันทึกการเปลี่ยนแปลง Pricelist และวันตัดรอบ) ───
        c.execute("""CREATE TABLE IF NOT EXISTS config_log(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key  TEXT,
            old_value   TEXT,
            new_value   TEXT,
            changed_at  TEXT
        )""")

        # [V4.5] indexes สำหรับ query ที่ใช้บ่อย
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_slot_id ON readings(slot, id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_slot_billing ON readings(slot, billing_month)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_dup ON readings(slot, serial, read_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_imported ON readings(imported_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_iso ON readings(read_date_iso DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_price_snapshot_rid ON price_snapshot(reading_id)")

        # ─── V5 device fleet และ daily rollup ───────────────
        c.execute("""CREATE TABLE IF NOT EXISTS devices(
            slot              INTEGER PRIMARY KEY CHECK(slot BETWEEN 0 AND 2),
            name              TEXT NOT NULL,
            host              TEXT NOT NULL UNIQUE,
            username          TEXT NOT NULL DEFAULT 'administrator',
            password          TEXT NOT NULL DEFAULT '',
            credential_ref    TEXT NOT NULL DEFAULT '',
            tls_mode          TEXT NOT NULL DEFAULT 'system',
            tls_fingerprint   TEXT NOT NULL DEFAULT '',
            enabled           INTEGER NOT NULL DEFAULT 1,
            model             TEXT NOT NULL DEFAULT '',
            serial            TEXT NOT NULL DEFAULT '',
            connection_status TEXT NOT NULL DEFAULT 'pending',
            last_checked_at   TEXT,
            last_success_at   TEXT,
            last_error        TEXT NOT NULL DEFAULT '',
            last_total        INTEGER,
            updated_at        TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS daily_meter_records(
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            device_slot    INTEGER NOT NULL,
            record_date    TEXT NOT NULL,
            opening_json   TEXT NOT NULL,
            closing_json   TEXT NOT NULL,
            delta_json     TEXT NOT NULL,
            category_json  TEXT NOT NULL DEFAULT '{}',
            source_json    TEXT NOT NULL DEFAULT '{}',
            first_success  TEXT,
            last_success   TEXT,
            sample_count   INTEGER NOT NULL DEFAULT 0,
            error_count    INTEGER NOT NULL DEFAULT 0,
            incomplete     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL,
            UNIQUE(device_slot, record_date),
            FOREIGN KEY(device_slot) REFERENCES devices(slot) ON DELETE CASCADE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS price_history(
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            device_slot    INTEGER NOT NULL,
            effective_date TEXT NOT NULL,
            a3_color       REAL NOT NULL DEFAULT 0,
            a3_bw          REAL NOT NULL DEFAULT 0,
            a4_color       REAL NOT NULL DEFAULT 0,
            a4_bw          REAL NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL,
            UNIQUE(device_slot, effective_date),
            FOREIGN KEY(device_slot) REFERENCES devices(slot) ON DELETE CASCADE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS cost_category_history(
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            device_slot    INTEGER NOT NULL,
            raw_key        TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            category       TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            UNIQUE(device_slot, raw_key, effective_date),
            FOREIGN KEY(device_slot) REFERENCES devices(slot) ON DELETE CASCADE
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_daily_meter_date ON daily_meter_records(record_date, device_slot)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_price_effective ON price_history(device_slot, effective_date DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cost_category_effective ON cost_category_history(device_slot, raw_key, effective_date DESC)")
        # Billing postings are deliberately separate from raw daily meter rows.
        # Existing installations are never backfilled: only a newly-finalized,
        # attested day may create a ledger entry.
        c.execute("""CREATE TABLE IF NOT EXISTS billing_ledger(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_kind TEXT NOT NULL CHECK(entry_kind IN ('posting','hold','reversal','replacement')),
            device_slot INTEGER NOT NULL,
            device_identity TEXT NOT NULL,
            device_name_snapshot TEXT NOT NULL DEFAULT '',
            device_serial_snapshot TEXT NOT NULL DEFAULT '',
            record_date TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            source_daily_record_id INTEGER,
            source_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            replaces_ledger_id INTEGER,
            delta_json TEXT NOT NULL,
            category_json TEXT NOT NULL,
            price_cents_json TEXT NOT NULL,
            gross_cents INTEGER NOT NULL,
            waste_basis_points INTEGER NOT NULL,
            net_cents INTEGER NOT NULL,
            billing_day INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'THB',
            formula_version TEXT NOT NULL DEFAULT 'komi.billing.v1',
            hold_reason TEXT,
            attestation_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(replaces_ledger_id) REFERENCES billing_ledger(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_billing_ledger_period ON billing_ledger(device_slot, record_date)")
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_one_initial_event
                     ON billing_ledger(source_daily_record_id)
                     WHERE source_daily_record_id IS NOT NULL AND entry_kind IN ('posting','hold')""")
        _create_billing_ledger_immutability_triggers(c)
        c.execute("""CREATE TABLE IF NOT EXISTS daily_subject_records(
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            device_slot      INTEGER NOT NULL,
            record_date      TEXT NOT NULL,
            subject_type     TEXT NOT NULL,
            subject_id       TEXT NOT NULL,
            subject_name     TEXT NOT NULL,
            opening_total    REAL NOT NULL,
            closing_total    REAL NOT NULL,
            delta_total      REAL NOT NULL,
            reset_count      INTEGER NOT NULL DEFAULT 0,
            missing_baseline INTEGER NOT NULL DEFAULT 0,
            sample_count     INTEGER NOT NULL DEFAULT 0,
            first_success    TEXT,
            last_success     TEXT,
            incomplete       INTEGER NOT NULL DEFAULT 0,
            warnings_json    TEXT NOT NULL DEFAULT '[]',
            source_json      TEXT NOT NULL DEFAULT '{}',
            created_at       TEXT NOT NULL,
            UNIQUE(device_slot, record_date, subject_type, subject_id),
            FOREIGN KEY(device_slot) REFERENCES devices(slot) ON DELETE CASCADE
        )""")
        c.execute("""CREATE INDEX IF NOT EXISTS idx_daily_subject_period
                     ON daily_subject_records(record_date, device_slot, subject_type, subject_id)""")

        # ─── Migration: เพิ่มค่า default สำหรับเครื่องใหม่ถ้ายังไม่มี ───
        _ensure_first_run_setting_defaults(c)

        applied = apply_migrations(c)
        validate_current_schema(c)
        if applied:
            log.info("database migrations applied: %s", applied)

# ══════════════════════════════════════════════════════════
# SETTINGS — อ่าน/เขียนค่าตั้งค่า
# ══════════════════════════════════════════════════════════
_cfg_cache = None
_cfg_lock = threading.RLock()  # [V4.5] thread-safe cache

@contextmanager
def config_write_transaction():
    """Keep cached readers out until an external settings transaction commits.

    Callers use this connection for all writes, including their audit records.
    Invalidate on either outcome so a rolled-back value cannot survive in cache.
    """
    global _cfg_cache
    with _cfg_lock:
        try:
            with _open() as connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        finally:
            _cfg_cache = None

def get_cfg(key: str, default: str = "") -> str:
    """อ่านค่า setting จาก database (ใช้ cache ลด I/O) — thread-safe"""
    global _cfg_cache
    with _cfg_lock:
        if _cfg_cache is None:
            with _open(commit=False) as c:
                rows = c.execute("SELECT key, value FROM settings").fetchall()
            _cfg_cache = {k: v for k, v in rows}
        return _cfg_cache.get(key, default)

def set_cfg(key: str, value: str):
    """[V4.5] บันทึกค่า setting + log การเปลี่ยนแปลง ภายใน transaction เดียว"""
    global _cfg_cache
    with _cfg_lock:
        old_value = get_cfg(key, None)
        loggable = (
            key.startswith("price_")
            or key.startswith("machine_name_")
            or key.startswith("machine_type_")
            or key.startswith("multiplier_")
            or key.startswith("parser_")
            or key in {"billing_day", "waste_paper_pct", "db_path"}
        )
        with _open() as c:
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
            if old_value != value and loggable:
                c.execute("""INSERT INTO config_log(config_key,old_value,new_value,changed_at)
                             VALUES(?,?,?,?)""",
                          (key, old_value, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if _cfg_cache is not None:
            _cfg_cache[key] = value

def get_price(key: str, slot: int = -1) -> float:
    """
    อ่านราคาต่อแผ่น
    - slot >= 0: ราคาเฉพาะเครื่อง (เช่น slot=0 → a4_color ของเครื่อง 1)
    - slot = -1: ราคาทั่วไป (ถ้าไม่ได้กำหนด)
    """
    if slot >= 0:
        cfg_key = f"price_{slot}_{key}"
    else:
        cfg_key = f"price_{key}"
    return float(get_cfg(cfg_key, str(DEFAULT_PRICE.get(key, 0))))

def get_billing_day() -> int:
    """[V4.5] วันตัดรอบบิล (1-31) — clamp ป้องกันค่า invalid"""
    raw = get_cfg("billing_day", "25") or "25"
    try:
        v = int(raw)
    except (ValueError, TypeError):
        log.warning("invalid billing_day %r, fallback to 25", raw)
        v = 25
    return max(1, min(31, v))

def get_waste_paper_pct() -> float:
    """% กระดาษเสีย (0-100) — ค่าเริ่มต้น 5.0"""
    from config import DEFAULT_WASTE_PCT
    return float(get_cfg("waste_paper_pct", str(DEFAULT_WASTE_PCT)))

def set_waste_paper_pct(pct: float):
    """ตั้งค่า % กระดาษเสีย"""
    set_cfg("waste_paper_pct", str(round(float(pct), 2)))

def get_settings_password() -> str:
    """รหัสผ่านสำหรับเปลี่ยนค่าตั้งค่า"""
    from config import DEFAULT_SETTINGS_PASSWORD
    return get_cfg("settings_password", DEFAULT_SETTINGS_PASSWORD)


def _hash_pwd(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def verify_settings_password(entered: str) -> bool:
    """
    ตรวจสอบรหัสผ่าน โดย hash ด้วย SHA-256 ก่อนเปรียบเทียบ
    - ถ้า stored ยังเป็น plaintext (ไม่ใช่ hex 64 ตัว) จะ migrate อัตโนมัติ
    - ใช้ hmac.compare_digest เพื่อป้องกัน timing attack
    """
    from config import DEFAULT_SETTINGS_PASSWORD
    stored = get_cfg("settings_password") or DEFAULT_SETTINGS_PASSWORD
    if not stored:
        return False
    # Migration: ถ้า stored ไม่ใช่ SHA-256 hex (64 ตัว) แปลว่าเป็น plaintext เก่า
    if len(stored) != 64 or not all(c in '0123456789abcdef' for c in stored):
        hashed = _hash_pwd(stored)
        set_cfg("settings_password", hashed)
        stored = hashed
    return hmac.compare_digest(stored, _hash_pwd(entered))


def set_settings_password(plain: str) -> None:
    """[V4.5] บันทึกรหัสผ่านใหม่ — hash ก่อนเก็บเสมอ (ห้าม plaintext)"""
    if not plain:
        raise ValueError("password cannot be empty")
    set_cfg("settings_password", _hash_pwd(plain))


# ══════════════════════════════════════════════════════════
# BILLING MONTH — คำนวณเดือนบิลจากวันที่และวันตัดรอบ
# ══════════════════════════════════════════════════════════
def calc_billing_month(date_str: str) -> str:
    """
    คำนวณเดือนบิลโดยยึดวันที่ในไฟล์เป็นหลัก:
    - ถ้าวันที่ <= billing_day: ใช้เดือนปัจจุบันของวันที่นั้น
    - ถ้าวันที่ > billing_day: ใช้เดือนถัดไปของวันที่นั้น
    """
    # 1. พยายามแปลง string เป็น object วันที่
    dt = None
    date_part = date_str.strip().split()[0] if date_str else ""
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(date_part, fmt)
            break
        except ValueError:
            continue
    
    # ถ้า parse วันที่ไม่ได้จริงๆ ให้ใช้เวลาปัจจุบันของเครื่อง (fallback)
    if not dt:
        dt = datetime.now()

    # 2. ดึงวันตัดรอบ (เช่น 25)
    billing_day = get_billing_day()
    
    # 3. คำนวณเดือนบิล
    # ถ้าวันในไฟล์ <= วันตัดรอบ ให้ใช้เดือนของวันนั้นเลย
    # ถ้าวันในไฟล์ > วันตัดรอบ ให้บวกไปอีก 1 เดือน
    if dt.day <= billing_day:
        target_date = dt
    else:
        # วิธีเพิ่ม 1 เดือนที่ปลอดภัยกำหนด day=1 ป้องกัน IndexError (เช่น 31 ม.ค. ไป ก.พ.)
        if dt.month == 12:
            target_date = dt.replace(year=dt.year + 1, month=1, day=1)
        else:
            target_date = dt.replace(month=dt.month + 1, day=1)
            
    return target_date.strftime("%Y-%m")
# ══════════════════════════════════════════════════════════
# SAVE / QUERY — บันทึกและดึงข้อมูล
# ══════════════════════════════════════════════════════════
def save_reading(slot: int, parsed: dict, fname: str = "") -> int:
    """
    [V4.5] บันทึก reading + price snapshot + trim — ใน transaction เดียว (atomic)
    """
    read_date = parsed.get("date", "")
    billing_month = calc_billing_month(read_date)
    read_iso = _date_to_iso(read_date)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # snapshot ราคาก่อนเปิด transaction (ไม่ต้องอยู่ใน DB lock)
    current_prices = {}
    for key in ("a4_color", "a4_bw", "a3_color", "a3_bw"):
        current_prices[f"{slot}_{key}"] = get_price(key, slot)

    with _open() as c:
        cur = c.execute("""INSERT INTO readings
            (slot,machine_name,serial,read_date,read_date_iso,billing_month,mode,data_json,imported_at,file_name,parser_name)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (slot,
             parsed.get("machine_name", ""),
             parsed.get("serial", ""),
             read_date,
             read_iso,
             billing_month,
             parsed.get("mode", ""),
             json.dumps(parsed, ensure_ascii=False),
             now_str,
             fname,
             parsed.get("parser_name", "")))
        new_id = cur.lastrowid

        c.execute("""INSERT INTO price_snapshot(reading_id,price_json,saved_at)
                     VALUES(?,?,?)""",
                  (new_id, json.dumps(current_prices, ensure_ascii=False), now_str))

        # ลบเรคอร์ดเก่าเกิน MAX_HIST (FK CASCADE จะลบ price_snapshot ตาม)
        c.execute("""DELETE FROM readings WHERE slot=? AND id NOT IN
            (SELECT id FROM readings WHERE slot=? ORDER BY id DESC LIMIT ?)""",
            (slot, slot, MAX_HIST))

    _clear_read_caches(slot)
    return new_id

def check_duplicate(slot: int, serial: str, read_date: str) -> bool:
    """ตรวจสอบว่ามีไฟล์ซ้ำ (SN + วันที่เดียวกัน) หรือไม่"""
    with _open(commit=False) as c:
        row = c.execute("""SELECT id FROM readings
            WHERE slot=? AND serial=? AND read_date=?""",
            (slot, serial, read_date)).fetchone()
    return row is not None

def get_slot_serial(slot: int) -> str:
    """ดึง Serial ล่าสุดของ slot นั้น (เพื่อตรวจสอบว่าอัพไฟล์ถูกเครื่อง)"""
    with _open(commit=False) as c:
        row = c.execute("""SELECT serial FROM readings
            WHERE slot=? ORDER BY id DESC LIMIT 1""", (slot,)).fetchone()
    return row[0] if row else ""

def get_last_two(slot: int):
    """ดึงข้อมูล 2 รายการล่าสุดของ slot (ปัจจุบัน, ก่อนหน้า)"""
    with _open(commit=False) as c:
        rows = c.execute(
            "SELECT data_json FROM readings WHERE slot=? ORDER BY id DESC LIMIT 2", (slot,)
        ).fetchall()
    if not rows: return None, None
    return json.loads(rows[0][0]), (json.loads(rows[1][0]) if len(rows)>1 else None)

def get_all_readings(slot: int) -> list:
    """ดึงข้อมูลทุกรายการของ slot เรียงจากเก่าไปใหม่"""
    with _read_cache_lock:
        cached = _all_readings_cache.get(slot)
        if cached is not None:
            return copy.deepcopy(cached)

    with _open(commit=False) as c:
        rows = c.execute(
            "SELECT data_json,imported_at,billing_month,id FROM readings WHERE slot=? ORDER BY id ASC",
            (slot,)
        ).fetchall()
    parsed_rows = [(json.loads(r[0]), r[1], r[2], r[3]) for r in rows]
    with _read_cache_lock:
        _all_readings_cache[slot] = copy.deepcopy(parsed_rows)
    return parsed_rows

def get_monthly_summary(slot: int) -> dict:
    """
    รวมยอดการใช้งานตามเดือนบิล
    คืนค่า dict {billing_month: {a4_color, a4_bw, a3_color, a3_bw, total, ...}}
    """
    with _read_cache_lock:
        cached = _monthly_summary_cache.get(slot)
        if cached is not None:
            return copy.deepcopy(cached)

    readings = get_all_readings(slot)
    monthly = {}
    prev_data = None
    for data, imp_at, billing_month, rec_id in readings:
        if billing_month not in monthly:
            monthly[billing_month] = {
                "a4_color":0,"a4_bw":0,"a3_color":0,"a3_bw":0,
                "total_color":0,"total_bw":0,"total":0,
                "meter_color":0,"meter_bw":0,
                "records": [], "machine_name": data.get("machine_name",""),
                "serial": data.get("serial","")
            }
        # คำนวณยอดส่วนต่าง (usage = current - previous)
        m = monthly[billing_month]
        sm = data.get("summary",{})
        pc = data.get("paper_color",{})
        mt = data.get("meters", {})
        if prev_data:
            psm = prev_data.get("summary",{}); ppc = prev_data.get("paper_color",{})
            pmt = prev_data.get("meters", {})
            m["a4_color"]    += max(0, pc.get("a4_color",0)    - ppc.get("a4_color",0))
            m["a4_bw"]       += max(0, pc.get("a4_bw",0)       - ppc.get("a4_bw",0))
            m["a3_color"]    += max(0, pc.get("a3_color",0)    - ppc.get("a3_color",0))
            m["a3_bw"]       += max(0, pc.get("a3_bw",0)       - ppc.get("a3_bw",0))
            m["total_color"] += max(0, sm.get("total_color",0) - psm.get("total_color",0))
            m["total_bw"]    += max(0, sm.get("total_bw",0)    - psm.get("total_bw",0))
            m["total"]       += max(0, sm.get("total",0)       - psm.get("total",0))
            m["meter_color"] += max(0, mt.get("color_meter",0) - pmt.get("color_meter",0))
            m["meter_bw"]    += max(0, mt.get("bw_meter",0)    - pmt.get("bw_meter",0))
        else:
            # รายการแรกสุด ใช้ยอดสะสม
            m["a4_color"]    = pc.get("a4_color",0)
            m["a4_bw"]       = pc.get("a4_bw",0)
            m["a3_color"]    = pc.get("a3_color",0)
            m["a3_bw"]       = pc.get("a3_bw",0)
            m["total_color"] = sm.get("total_color",0)
            m["total_bw"]    = sm.get("total_bw",0)
            m["total"]       = sm.get("total",0)
            m["meter_color"] = mt.get("color_meter",0)
            m["meter_bw"]    = mt.get("bw_meter",0)
        m["records"].append({"data":data,"imp_at":imp_at,"id":rec_id})
        prev_data = data
    with _read_cache_lock:
        _monthly_summary_cache[slot] = copy.deepcopy(monthly)
    return monthly

def calc_cost(a4c, a4bw, a3c, a3bw, slot: int = -1) -> float:
    """
    คำนวณค่าใช้จ่าย (บาท)
    - slot >= 0: ใช้ราคาของเครื่องนั้น (เช่น slot=0 → เครื่อง 1)
    - slot = -1: ใช้ราคาทั่วไป
    """
    return (a4c  * get_price("a4_color", slot) +
            a4bw * get_price("a4_bw", slot)   +
            a3c  * get_price("a3_color", slot) +
            a3bw * get_price("a3_bw", slot))

def delete_reading(rec_id: int):
    """ลบ record ตาม id (FK CASCADE จะลบ price_snapshot ด้วย)"""
    with _open() as c:
        row = c.execute("SELECT slot FROM readings WHERE id=?", (rec_id,)).fetchone()
        c.execute("DELETE FROM readings WHERE id=?", (rec_id,))
    _clear_read_caches(row[0] if row else None)

def clear_slot(slot: int):
    """ลบข้อมูลทั้งหมดของ slot"""
    with _open() as c:
        c.execute("DELETE FROM readings WHERE slot=?", (slot,))
    _clear_read_caches(slot)


def _delete_rows_and_sequences(
    connection: sqlite3.Connection,
    *,
    tables: tuple[str, ...],
    sequences: tuple[str, ...],
) -> None:
    for table in tables:
        connection.execute(f"DELETE FROM {table}")
    if sequences:
        placeholders = ",".join("?" for _ in sequences)
        connection.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
            sequences,
        )


def _stage_runtime_cache() -> Path | None:
    """Atomically detach derived cache so a failed reset can restore it."""

    cache_root = Path(get_db_path()).parent / "runtime-cache"
    if not cache_root.exists():
        return None
    cache_root.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(prefix=".runtime-cache-reset-", dir=cache_root.parent)
    )
    staged.rmdir()
    cache_root.replace(staged)
    return staged


def _restore_runtime_cache(staged: Path | None) -> None:
    if staged is None or not staged.exists():
        return
    cache_root = Path(get_db_path()).parent / "runtime-cache"
    if cache_root.exists():
        raise RuntimeError(
            "คืน runtime cache หลัง rollback ไม่สำเร็จ เพราะมี cache ใหม่ถูกสร้างระหว่าง reset"
        )
    staged.replace(cache_root)


def _discard_runtime_cache(staged: Path | None) -> None:
    """Discard old and concurrently recreated derived cache after commit."""

    cache_root = Path(get_db_path()).parent / "runtime-cache"
    for candidate in (staged, cache_root):
        if candidate is None or not candidate.exists():
            continue
        try:
            shutil.rmtree(candidate)
        except OSError:
            log.exception("cannot remove derived runtime cache after reset: %s", candidate)


def _registration_secret_references(
    connection: sqlite3.Connection,
) -> tuple[str, ...]:
    """Collect every legacy token and V5.2 token/key reference before reset."""

    from services.installation_identity import installation_private_key_reference
    from services.registration_vault import installation_token_reference

    references: set[str] = set()
    installation_ids: set[str] = set()

    legacy = connection.execute(
        "SELECT installation_id,token_ref FROM registration_profile WHERE singleton_id=1"
    ).fetchone()
    if legacy:
        if legacy[0] and str(legacy[0]).strip():
            installation_ids.add(str(legacy[0]).strip())
        if legacy[1] and str(legacy[1]).strip():
            references.add(str(legacy[1]).strip())

    runtime = connection.execute(
        "SELECT installation_id FROM v52_runtime_state WHERE singleton_id=1"
    ).fetchone()
    if runtime and runtime[0] and str(runtime[0]).strip():
        installation_ids.add(str(runtime[0]).strip())

    for installation_id in installation_ids:
        references.add(installation_token_reference(installation_id))
        references.add(installation_private_key_reference(installation_id))
    return tuple(sorted(references))


def _restore_registration_secrets(
    registration_secret_store,
    secret_snapshot: dict[str, str | None],
) -> list[Exception]:
    failures: list[Exception] = []
    if registration_secret_store is None:
        return failures
    for reference, secret in secret_snapshot.items():
        if secret is None:
            continue
        try:
            registration_secret_store.save(reference, secret)
        except Exception as error:  # pragma: no cover - OS vault failure boundary
            failures.append(error)
    return failures


def reset_usage_data():
    """Clear report/billing history while preserving setup and configuration."""

    staged_cache: Path | None = None
    try:
        with _open() as c:
            c.execute("BEGIN IMMEDIATE")
            staged_cache = _stage_runtime_cache()
            c.execute("DROP TRIGGER IF EXISTS billing_ledger_no_update")
            c.execute("DROP TRIGGER IF EXISTS billing_ledger_no_delete")
            _delete_rows_and_sequences(
                c,
                tables=_USAGE_RESET_TABLES,
                sequences=_USAGE_RESET_SEQUENCES,
            )
            _create_billing_ledger_immutability_triggers(c)
            validate_current_schema(c)
    except Exception:
        try:
            _restore_runtime_cache(staged_cache)
        except Exception as restore_error:
            raise RuntimeError(
                "ล้างข้อมูลไม่สำเร็จ และคืน runtime cache หลัง rollback ไม่สำเร็จ"
            ) from restore_error
        raise

    _discard_runtime_cache(staged_cache)
    _clear_read_caches()


def reset_db():
    """Compatibility alias for the legacy data-only reset action."""
    reset_usage_data()


def factory_reset_v5(*, registration_secret_store=None) -> None:
    """Reset all local state while serialized with registration token commits."""

    from services.registration_vault import registration_state_lock

    with registration_state_lock:
        _factory_reset_v5_locked(registration_secret_store=registration_secret_store)


def _factory_reset_v5_locked(*, registration_secret_store=None) -> None:
    """Return V5 to a true first-run state without deleting the SQLite file.

    This removes device configuration, pricing, usage, daily evidence and the
    local runtime cache. The append-only ledger triggers and first-run defaults
    are restored inside the same transaction; a deliberate factory reset is
    the one authorised exception to ordinary ledger history.
    """
    global _cfg_cache

    secret_references: tuple[str, ...] = ()
    secret_snapshot: dict[str, str | None] = {}
    with _open(commit=False) as c:
        secret_references = _registration_secret_references(c)
    if secret_references:
        if registration_secret_store is None:
            from services.registration_vault import platform_registration_secret_store

            registration_secret_store = platform_registration_secret_store()
        secret_snapshot = {
            reference: registration_secret_store.load(reference)
            for reference in secret_references
        }

    staged_cache: Path | None = None
    try:
        with _open() as c:
            c.execute("BEGIN IMMEDIATE")
            staged_cache = _stage_runtime_cache()
            c.execute("DROP TRIGGER IF EXISTS billing_ledger_no_update")
            c.execute("DROP TRIGGER IF EXISTS billing_ledger_no_delete")
            _delete_rows_and_sequences(
                c,
                tables=_FACTORY_RESET_TABLES,
                sequences=_FACTORY_RESET_SEQUENCES,
            )

            _ensure_first_run_setting_defaults(c)
            _create_billing_ledger_immutability_triggers(c)
            validate_current_schema(c)

            for reference in secret_references:
                registration_secret_store.delete(reference)
    except Exception:
        secret_failures = _restore_registration_secrets(
            registration_secret_store,
            secret_snapshot,
        )
        try:
            _restore_runtime_cache(staged_cache)
        except Exception as restore_error:
            raise RuntimeError(
                "Factory Reset ไม่สำเร็จ และคืน runtime cache หลัง rollback ไม่สำเร็จ"
            ) from restore_error
        if secret_failures:
            raise RuntimeError(
                "Factory Reset ไม่สำเร็จ และคืน Registration secret หลัง rollback ไม่ครบ"
            ) from secret_failures[0]
        raise

    _cfg_cache = None
    _clear_read_caches()
    _discard_runtime_cache(staged_cache)

# ══════════════════════════════════════════════════════════
# ARCHIVE — คัดลอกไฟล์ที่ import ไปเก็บไว้ในโฟลเดอร์ตาม machine name
# ══════════════════════════════════════════════════════════

_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


def sanitize_filename(name: str) -> str:
    """[V4.5] ทำความสะอาดชื่อสำหรับเป็น path บน Windows
    - ตัดอักขระต้องห้าม \\/:*?\"<>|
    - ตัด . และ space ท้าย (Windows treats as same name)
    - หลีก reserved names (CON, PRN, NUL, COM1-9, LPT1-9)
    - กัน path traversal (ตัด .. และ separator)
    """
    if not name:
        return "Unknown"
    s = "".join(ch if ch not in r'\/:*?"<>|' else "_" for ch in str(name))
    s = s.replace("..", "_").strip(" .")
    if not s:
        return "Unknown"
    if s.upper().split(".")[0] in _WIN_RESERVED:
        s = "_" + s
    return s[:120]  # จำกัดความยาว


def archive_import_file(src_path: str, machine_name: str) -> Path | None:
    """
    คัดลอกไฟล์ที่ import ไปเก็บไว้ที่:
        <DB_dir>/imported/<machine_name>/<filename>

    - สร้างโฟลเดอร์อัตโนมัติถ้ายังไม่มี
    - ถ้าไฟล์ชื่อซ้ำ จะเพิ่ม _1, _2, ... ต่อท้ายก่อนนามสกุล
    - คืนค่า Path ปลายทาง หรือ None ถ้าคัดลอกไม่สำเร็จ
    """
    try:
        src = Path(src_path)
        # [V4.5] sanitize ครอบคลุม Windows reserved + path traversal
        safe_name = sanitize_filename(machine_name)
        custom_base = get_cfg("imported_path", "")
        base_dir = Path(custom_base) if custom_base else Path(_db_path).parent / "imported"
        dest_dir = (base_dir / safe_name).resolve()
        # ป้องกัน path traversal: dest_dir ต้องอยู่ใต้ base_dir
        base_resolved = base_dir.resolve()
        if not str(dest_dir).startswith(str(base_resolved)):
            log.error("path traversal attempt: %r → %r", machine_name, dest_dir)
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / sanitize_filename(src.name)
        # หากชื่อไฟล์ซ้ำ ให้เพิ่ม suffix _1, _2, ...
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1

        shutil.copy2(src, dest)
        return dest
    except Exception:
        log.exception("archive_import_file failed: src=%r machine=%r", src_path, machine_name)
        return None


def reset_settings_to_default():
    """[V4.5] รีเซทการตั้งค่าทั้งหมดกลับเป็นค่าเริ่มต้น (transaction-safe)"""
    global _cfg_cache
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _cfg_lock:
        # populate cache ก่อนเพื่อให้ get old value ถูกต้อง
        if _cfg_cache is None:
            with _open(commit=False) as c:
                rows = c.execute("SELECT key, value FROM settings").fetchall()
            _cfg_cache = {k: v for k, v in rows}

        cache_snapshot = dict(_cfg_cache)

        with _open() as c:
            def _reset(key, new_val):
                old = cache_snapshot.get(key)
                c.execute("DELETE FROM settings WHERE key=?", (key,))
                c.execute(
                    """INSERT INTO config_log(config_key,old_value,new_value,changed_at)
                       VALUES(?,?,?,?)""",
                    (key, old, str(new_val), now)
                )

            for slot in range(3):
                for key, val in DEFAULT_PRICE.items():
                    _reset(f"price_{slot}_{key}", val)
            for slot in range(3):
                _reset(f"machine_name_{slot}", SLOT_NAMES[slot])
            _reset("billing_day", 25)

        _cfg_cache = None


# ══════════════════════════════════════════════════════════
# QUERY FUNCTIONS — ดึงข้อมูลสรุปจาก database
# ══════════════════════════════════════════════════════════

def get_price_snapshot(reading_id: int) -> dict:
    """ดึง snapshot ของ pricelist ที่บันทึกไว้สำหรับ reading_id"""
    with _open(commit=False) as c:
        row = c.execute("""SELECT price_json FROM price_snapshot WHERE reading_id=?
                           ORDER BY saved_at DESC LIMIT 1""", (reading_id,)).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return {}
    return {}


def get_config_log(limit: int = 100) -> list:
    """ดึงประวัติการเปลี่ยนแปลง Pricelist และวันตัดรอบ"""
    with _open(commit=False) as c:
        rows = c.execute("""SELECT id, config_key, old_value, new_value, changed_at
                            FROM config_log ORDER BY changed_at DESC LIMIT ?""",
                         (limit,)).fetchall()
    return [{"id": r[0], "config_key": r[1], "old_value": r[2],
             "new_value": r[3], "changed_at": r[4]} for r in rows]


def get_latest_read_date() -> str:
    """[V4.5] คืนค่า read_date ล่าสุด — เรียงด้วย read_date_iso เพื่อให้ถูก format
    fallback ไปเรียงด้วย imported_at ถ้า ISO ว่าง"""
    with _open(commit=False) as c:
        # ใช้ read_date_iso เป็นหลัก (เรียง string ISO ได้ถูก)
        row = c.execute("""SELECT read_date FROM readings
                           WHERE read_date_iso IS NOT NULL AND read_date_iso != ''
                           ORDER BY read_date_iso DESC, id DESC LIMIT 1""").fetchone()
        if row:
            return row[0]
        # fallback: เรียงตาม imported_at (เครื่อง record ล่าสุดที่ import)
        row = c.execute("SELECT read_date FROM readings ORDER BY imported_at DESC, id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def get_activity_log(limit: int = 200) -> list:
    """ดึงรายการ import ล่าสุดจาก readings ทุก slot"""
    with _open(commit=False) as c:
        rows = c.execute("""SELECT id, slot, machine_name, serial, file_name,
                                   read_date, imported_at, billing_month,
                                   COALESCE(parser_name, '') as parser_name
                            FROM readings ORDER BY imported_at DESC LIMIT ?""",
                         (limit,)).fetchall()
    keys = ["id", "slot", "machine_name", "serial",
            "file_name", "read_date", "imported_at", "billing_month", "parser_name"]
    return [dict(zip(keys, r)) for r in rows]


def get_month_top_users(billing_month: str) -> list:
    """
    รวบรวมผู้ใช้ที่พิมพ์มากที่สุดในบิลเดือนนั้น จากทุก slot
    คืน list[(name, color, bw, total)] เรียงจากมากไปน้อย
    """
    import collections
    users = collections.defaultdict(lambda: [0, 0, 0])  # {name: [color, bw, total]}

    with _open(commit=False) as c:
        for slot in range(3):
            # baseline = record ล่าสุดก่อนเดือนนี้ (สำหรับคำนวณ delta)
            baseline_row = c.execute(
                """SELECT data_json FROM readings
                   WHERE slot=? AND billing_month<? ORDER BY id DESC LIMIT 1""",
                (slot, billing_month)).fetchone()
            baseline = json.loads(baseline_row[0]) if baseline_row else None

            # latest = record ล่าสุดในเดือนนี้
            latest_row = c.execute(
                """SELECT data_json FROM readings
                   WHERE slot=? AND billing_month=? ORDER BY id DESC LIMIT 1""",
                (slot, billing_month)).fetchone()
            if not latest_row:
                continue
            latest = json.loads(latest_row[0])

            accs = latest.get("accounts") or []
            if accs:
                baseline_accounts = {
                    x.get("name"): x
                    for x in (baseline.get("accounts") if baseline else []) or []
                    if x.get("name")
                }
                for a in accs:
                    color_total = a.get("color_a4", 0) + a.get("color_a3", 0)
                    bw_total    = a.get("bw_a4",    0) + a.get("bw_a3",    0)
                    total       = a.get("total", 0)

                    p = baseline_accounts.get(a.get("name"))
                    if p:
                        color_total = max(0, color_total - (p.get("color_a4", 0) + p.get("color_a3", 0)))
                        bw_total    = max(0, bw_total    - (p.get("bw_a4",    0) + p.get("bw_a3",    0)))
                        total       = max(0, total       -  p.get("total", 0))

                    users[a["name"]][0] += color_total
                    users[a["name"]][1] += bw_total
                    users[a["name"]][2] += total
            else:
                # Summary/Production mode — นับทั้งหมดเป็น "Public"
                pc = latest.get("paper_color", {})
                sm = latest.get("summary",     {})
                cf = pc.get("a4_color", 0) + pc.get("a3_color", 0)
                cb = pc.get("a4_bw",    0) + pc.get("a3_bw",    0)
                t  = sm.get("total", 0)

                if baseline:
                    bpc = baseline.get("paper_color", {})
                    bsm = baseline.get("summary",     {})
                    cf = max(0, cf - (bpc.get("a4_color", 0) + bpc.get("a3_color", 0)))
                    cb = max(0, cb - (bpc.get("a4_bw",    0) + bpc.get("a3_bw",    0)))
                    t  = max(0, t  -  bsm.get("total", 0))

                users["Public"][0] += cf
                users["Public"][1] += cb
                users["Public"][2] += t

    sorted_users = sorted(users.items(), key=lambda x: x[1][2], reverse=True)
    return [(name, v[0], v[1], v[2]) for name, v in sorted_users]
