"""Isolated synthetic history benchmark; never opens the configured customer DB.

Writes five years of actual daily rows for up to 200 users on three printers. Web
round storage is explicitly estimated from a measured representative payload,
not presented as five years of physically written Web observations.
"""
from datetime import date, datetime, timedelta, UTC
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(directory: Path, *, years=5, users=100, printers=3):
    import database
    from services.billing_periods import billing_month_range
    from services.device_config import DeviceConfig, DeviceConfigRepository
    from services.monthly_history import load_monthly_usage
    from services.subject_history import load_subject_history
    from services.raw_counter_history import load_raw_counter_history
    from services.web_observations import WebObservationStore, validate_event
    from komi_snmp_profiler.models import MeterReading, WebCounterValue, WebAuthState

    if not 1 <= years <= 5 or not 1 <= users <= 200 or not 1 <= printers <= 3:
        raise ValueError("Benchmark bounds: 1–5 years, 1–200 users, 1–3 printers")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    original = database.get_db_path()
    path = directory / "synthetic-history.sqlite3"
    end = date(2026, 9, 18)
    start = end.replace(year=end.year - years)
    slots = list(range(printers))
    result = {"synthetic": True, "database": str(path), "start": str(start), "end_exclusive": str(end),
              "years": years, "users": users, "printers": printers,
              "assumptions": [f"Same {users} users available on each printer", "Daily rows for every calendar day",
                  "One user total counter, not every model-specific counter", "No attachments or OS-vault data",
                  "Web-round storage below is an extrapolation, not five years of written rounds"]}
    try:
        database.set_db_path(path)
        database.init_db()
        DeviceConfigRepository().replace_all([DeviceConfig(slot, f"Fixture {slot + 1}", f"192.0.2.{slot + 10}",
            serial=f"FIXTURE-{slot}") for slot in slots])
        database.set_cfg("billing_day", "31")
        total = sum(10 + user % 5 for user in range(users))
        counter = "counter.total.total"
        started = time.perf_counter()
        with database._open() as conn:
            for index in range((end - start).days):
                day = start + timedelta(days=index)
                stamp = f"{day}T17:00:00+07:00"
                period_start, period_end = billing_month_range(day, 31)
                for slot in slots:
                    identity = {"name": f"Fixture {slot + 1}", "serial": f"FIXTURE-{slot}", "host": f"192.0.2.{slot + 10}"}
                    source = json.dumps({"device_identity": identity, "reconciliation": {"billing_safe": True}})
                    delta = json.dumps({counter: total})
                    categories = json.dumps({counter: "a4_bw"})
                    row_id = conn.execute("""INSERT INTO daily_meter_records
                        (device_slot,record_date,opening_json,closing_json,delta_json,category_json,source_json,
                         first_success,last_success,sample_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (slot, str(day), json.dumps({counter: index * total}), json.dumps({counter: (index + 1) * total}),
                         delta, categories, source, stamp, stamp, 32, stamp)).lastrowid
                    conn.execute("""INSERT INTO billing_ledger
                        (entry_kind,device_slot,device_identity,device_name_snapshot,device_serial_snapshot,record_date,
                         period_start,period_end,source_daily_record_id,source_hash,idempotency_key,delta_json,category_json,
                         price_cents_json,gross_cents,waste_basis_points,net_cents,billing_day,attestation_json,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("posting", slot, f"serial:FIXTURE-{slot}", identity["name"], identity["serial"], str(day),
                         str(period_start), str(period_end), row_id, f"synthetic:{row_id}", f"synthetic:{row_id}",
                         delta, categories, '{"a4_bw":100}', total * 100, 0, total * 100, 31, '{"billing_safe":true}', stamp))
                    subjects, raw = [], []
                    for user in range(users):
                        usage = 10 + user % 5
                        opening = 1000 + index * usage
                        subjects.append((slot, str(day), "user", str(user), f"Fixture user {user}", opening,
                                         opening + usage, usage, 32, stamp, stamp, source, stamp))
                        raw.append((slot, str(day), "counter.user.total.total", "User Total", "/fixture/users",
                                    "user", str(user), f"Fixture user {user}", opening, opening + usage, usage,
                                    32, stamp, stamp, "fixture", identity["name"], identity["serial"], stamp, stamp))
                    conn.executemany("""INSERT INTO daily_subject_records
                        (device_slot,record_date,subject_type,subject_id,subject_name,opening_total,closing_total,
                         delta_total,sample_count,first_success,last_success,source_json,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", subjects)
                    conn.executemany("""INSERT INTO daily_raw_counter_records
                        (device_slot,record_date,canonical_field,label,source_path,subject_type,subject_id,subject_name,
                         opening_value,closing_value,delta_value,sample_count,first_success,last_success,source_name,
                         device_name_snapshot,device_serial_snapshot,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", raw)
                if index % 365 == 0:
                    print(f"generated_days={index + 1}", flush=True)
        result["write_seconds"] = round(time.perf_counter() - started, 3)
        with database._open(commit=False) as conn:
            result["rows"] = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                              for table in ("daily_meter_records", "daily_subject_records", "daily_raw_counter_records", "billing_ledger")}
            result["expected_total_pages"] = (end - start).days * printers * total
            assert conn.execute("SELECT SUM(delta_total) FROM daily_subject_records").fetchone()[0] == result["expected_total_pages"]
        result["daily_history_bytes"] = path.stat().st_size
        timings = {}
        operations = {
            "monthly_devices_all_years": lambda: load_monthly_usage(slots, today=end),
            "subjects_last_month": lambda: load_subject_history(slots, today=end,
                period_start=end - timedelta(days=30), period_end=end),
            "raw_last_month": lambda: load_raw_counter_history(slots,
                period_start=end - timedelta(days=30), period_end=end),
        }
        for name, operation in operations.items():
            elapsed = []
            for _ in range(3):
                tick = time.perf_counter()
                rows = operation()
                elapsed.append((time.perf_counter() - tick) * 1000)
            timings[name] = {"runs_ms": [round(value, 2) for value in elapsed],
                             "median_ms": round(statistics.median(elapsed), 2), "returned_rows": len(rows)}
            print(f"{name}={timings[name]}", flush=True)
        result["queries"] = timings
        reading = MeterReading(host="192.0.2.10", collected_at=datetime(2026, 9, 18, tzinfo=UTC).isoformat(),
            counters=tuple(WebCounterValue("counter.user.total.total", "Total", 1000 + user,
                "User", f"/fixture/users/{user}", subject_type="user", subject_id=str(user),
                subject_name=f"Fixture user {user}") for user in range(users)), source="fixture", auth_state=WebAuthState.ADMIN)
        event = WebObservationStore().record(0, reading, serial="FIXTURE-0", printer_name="Fixture 1")
        encoded = validate_event(event).encode("utf-8")
        result["measured_one_web_round_bytes"] = len(encoded)
        result["measured_one_web_round_zlib_bytes"] = len(zlib.compress(encoded))
        result["estimated_five_year_web_payload_bytes"] = {
            str(minutes): len(encoded) * ((end - start).days * printers * (8 * 60 // minutes))
            for minutes in (5, 15, 30, 60)}
        result["web_estimate_notes"] = "8 hours/day, every calendar day; excludes indexes, receipts, devices' extra counters, backups and file-system overhead. Compression size is one payload only; production compression/archive is not enabled."
        (directory / "benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return result
    finally:
        database.set_db_path(original)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="New directory only; existing directories are refused")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--printers", type=int, default=3)
    args = parser.parse_args()
    run(args.directory, years=args.years, users=args.users, printers=args.printers)
