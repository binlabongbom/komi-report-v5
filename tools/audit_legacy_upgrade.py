"""Rehearse 5.2.4 database/cache continuity using an isolated synthetic fixture.

Uses the checked-out release fixture from the prior upgrade audit. Never opens
the configured customer database and never contacts a printer or LAN peer.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
from contextlib import closing
from datetime import date, datetime

REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "outputs/upgrade-v5.2.4-name-fix-2026-09-25"
TOTAL = "counter.total.total"


def reading(host, total, stamp):
    from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
    values = {TOTAL: total, "counter.print.total": total,
              "counter.print.full_color_total": total, "counter.print.full_color_large": 0,
              "counter.print.bw_total": 0, "counter.print.bw_large": 0,
              "counter.copy.total": 0, "counter.copy.full_color_total": 0,
              "counter.copy.full_color_large": 0, "counter.copy.bw_total": 0,
              "counter.copy.bw_large": 0, "counter.scan_fax.document_read_total": 0}
    return MeterReading(host=host, collected_at=stamp.isoformat(), counters=tuple(
        WebCounterValue(field, field, value, "Meter", "fixture", Confidence.VERIFIED)
        for field, value in values.items()), source="fixture", auth_state=WebAuthState.ADMIN)


def child(mode, output):
    spec = importlib.util.spec_from_file_location("legacy_rehearsal", REFERENCE / "verify_upgrade.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    legacy.ROOT, legacy.REPO = output, REPO
    legacy.DB = output / "runtime/customer-synthetic.sqlite3"
    import database
    from services.daily_cache import DailyCacheStore
    from services.device_config import DeviceConfigRepository
    cache = DailyCacheStore()
    legacy.child(mode)
    if mode == "create":
        from komi_version import APP_VERSION
        assert APP_VERSION == "5.2.4"
        for device in DeviceConfigRepository().list():
            for hour, total in ((8, 1000), (9, 1020)):
                stamp = datetime.fromisoformat(f"2026-09-25T{hour:02}:00:00+07:00")
                cache.update_reading(device.slot, reading(device.host, total, stamp), at=stamp)
            state = cache.load(device.slot, date(2026, 9, 25))
            assert state["opening"][TOTAL] == 1000 and state["delta"][TOTAL] == 20
        print("Actual 5.2.4 cache created: three printers, opening 1000, latest 1020, delta 20.")
        return

    from PyQt6.QtCore import QCoreApplication
    from services.background_polling import BackgroundPollingCoordinator
    from services.snmp_probe import SnmpProbeResult
    import app
    qt_app = QCoreApplication.instance() or QCoreApplication([])
    assert qt_app is not None
    repository = DeviceConfigRepository()
    assert app._v5_setup_is_complete(repository) is True
    assert app._check_v5_setup(None) is True
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT count(*) FROM slot_meter_heads").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM lan_peer_group").fetchone()[0] == 0
        before = {name: list(conn.execute(f'SELECT * FROM "{name}"')) for name in
                  ("readings", "price_history", "billing_ledger", "daily_meter_records",
                   "daily_subject_records", "daily_raw_counter_records")}

    class FakePrinter:
        total = 1030
        stamp = datetime.fromisoformat("2026-09-25T10:00:00+07:00")

        def read(self, host):
            return reading(host, self.total, self.stamp)

    printer = FakePrinter()

    class FakeProbe:
        def read(self, host):
            slot = int(host.split(".")[-1]) - 10
            return SnmpProbeResult(printer.total, "bizhub C450i", f"FIXTURE-{slot}")

    coordinator = BackgroundPollingCoordinator(repository, probe=FakeProbe(), reader=printer,
                                               cache=cache, clock=lambda: printer.stamp)
    outcomes = []
    try:
        # Exercise the actual membership decision, not just a mocked empty group.
        assert coordinator.peer_network_runtime._prepare(None) is None
        assert coordinator.shared_reads is None
        for device in repository.list():
            first = cache.load(device.slot, date(2026, 9, 25))
            assert first["opening"][TOTAL] == 1000 and first["delta"][TOTAL] == 20
            checks = []
            for hour, total, expected in ((10, 1030, 30), (11, 1040, 40)):
                printer.total = total
                printer.stamp = datetime.fromisoformat(f"2026-09-25T{hour}:00:00+07:00")
                assert coordinator._poll_device(device, force_web=True) is True
                state = cache.load(device.slot, printer.stamp.date())
                assert state["opening"][TOTAL] == 1000
                assert state["latest"][TOTAL] == total
                assert state["delta"][TOTAL] == expected
                assert not state.get("identity_baseline_mismatch")
                assert not state.get("counter_review")
                checks.append({"read_total": total, "opening": 1000, "usage": expected})
            outcomes.append({"slot": device.slot + 1, "reads": checks})
        with database._open(commit=False) as conn:
            # Raw today's rows append; all original historical rows stay identical.
            for name, rows in before.items():
                after = list(conn.execute(f'SELECT * FROM "{name}"'))
                assert all(row in after for row in rows), name
            assert conn.execute("SELECT count(*) FROM slot_meter_heads").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM web_observations").fetchone()[0] == 6
        result = {"complete": True, "scope": "Isolated source-level 5.2.4 upgrade; synthetic printers, no installer/network",
                  "first_run_wizard_skipped": True, "no_slot_epoch_required": True,
                  "standalone_runtime_skips_peer_binding": True, "all_existing_history_rows_unchanged": True,
                  "old_daily_cache_opening_preserved": True, "printer_reads": outcomes}
        (output / "continuity-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        coordinator.stop()

    # A customer may have only committed history, without runtime cache or raw
    # detail. Prove that the historical closing still supplies the opening.
    closed_outcomes = []
    backup = next((output / "runtime").glob("customer-synthetic.pre-v34-*.sqlite3"))
    for blank_serial in (False, True):
        variant = output / ("closed-history-blank-serial" if blank_serial else "closed-history")
        variant.mkdir()
        path = variant / "customer-synthetic.sqlite3"
        with closing(sqlite3.connect(backup)) as old, closing(sqlite3.connect(path)) as copied:
            old.backup(copied)
            counters = {c.canonical_field: c.count for c in reading(
                "192.0.2.10", 1020, datetime.fromisoformat("2026-07-16T12:00:00+07:00")).counters}
            source = {"device_identity": {"name": "Fixture 1", "host": "192.0.2.10",
                                         "serial": "" if blank_serial else "FIXTURE-0"},
                      "reconciliation": {"billing_safe": True}}
            copied.execute("DELETE FROM daily_raw_counter_records WHERE device_slot=0")
            copied.execute("UPDATE daily_meter_records SET closing_json=?,source_json=? WHERE device_slot=0 AND record_date='2026-07-16'",
                           (json.dumps(counters), json.dumps(source)))
            if blank_serial:
                copied.execute("UPDATE devices SET serial='' WHERE slot=0")
            copied.commit()
            original = legacy.snapshot(copied)
        database.set_db_path(path)
        database.init_db()
        with database._open(commit=False) as conn:
            assert legacy.snapshot(conn, original["columns"]) == original
        repository = DeviceConfigRepository()
        assert app._check_v5_setup(None) is True
        cache = DailyCacheStore(variant / "runtime-cache")
        from services.subject_history import SubjectDailyCacheStore
        coordinator = BackgroundPollingCoordinator(repository, probe=FakeProbe(), reader=printer,
            cache=cache, subject_cache=SubjectDailyCacheStore(variant / "subjects"), clock=lambda: printer.stamp)
        try:
            assert coordinator.peer_network_runtime._prepare(None) is None
            checks = []
            for hour, total, expected in ((10, 1030, 10), (11, 1040, 20)):
                printer.total = total
                printer.stamp = datetime.fromisoformat(f"2026-09-25T{hour}:00:00+07:00")
                assert coordinator._poll_device(repository.get(0), force_web=True) is True
                state = cache.load(0, printer.stamp.date())
                assert state["opening"][TOTAL] == 1020, state
                assert state["delta"][TOTAL] == expected, state
                assert not state.get("identity_baseline_mismatch")
                checks.append({"read_total": total, "opening": 1020, "usage": expected})
            closed_outcomes.append({"missing_runtime_cache": True, "missing_raw_detail": True,
                                    "blank_historical_serial": blank_serial, "reads": checks})
        finally:
            coordinator.stop()
    (output / "closed-history-result.json").write_text(json.dumps(closed_outcomes, indent=2), encoding="utf-8")
    print(json.dumps(closed_outcomes, indent=2))


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], Path(sys.argv[3]))
        return
    output = REPO / "outputs" / ("upgrade-v5.2.4-continuity-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    runtime = output / "runtime"
    runtime.mkdir(parents=True)
    home = runtime / "isolated-user"
    for folder in (home, home / "AppData/Roaming", home / "AppData/Local"):
        folder.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("KOMI_")}
    env.update(KOMI_APP_HOME=str(runtime), KOMI_DB_PATH=str(runtime / "customer-synthetic.sqlite3"),
               KOMI_RUNTIME_CONFIG=str(runtime / "runtime.toml"), KOMI_LOG_DIR=str(runtime / "logs"),
               KOMI_DISCOVERY_DISABLED="1", KOMI_V46_DATABASE=str(runtime / "absent.sqlite3"),
               USERPROFILE=str(home), APPDATA=str(home / "AppData/Roaming"),
               LOCALAPPDATA=str(home / "AppData/Local"), QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1")
    for mode, source in (("create", REFERENCE / "old-release/source"), ("migrate", REPO / "source")):
        env["PYTHONPATH"] = str(source)
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mode, str(output)],
                       env=env, cwd=runtime, check=True)
    print(f"Evidence: {output}")


if __name__ == "__main__":
    main()
