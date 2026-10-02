"""Windows source-only footprint experiment on fresh temporary databases.

Idle mode measures constructed UI/agent surfaces. --active-rounds adds actual
collector persistence with synthetic printer responses, NOT Web/Host workloads.
No release build, network connection or subprocess is allowed in a sample child.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic


def counters():
    class Memory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak_working_set", "working_set", "peak_paged", "paged",
                "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private_bytes",
            )
        ]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.GetCurrentProcess()
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    times = [wintypes.FILETIME() for _ in range(4)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    cpu = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10_000_000
    return {"working_set_bytes": memory.working_set, "private_bytes": memory.private_bytes,
            "peak_working_set_bytes": memory.peak_working_set, "cpu_seconds": cpu}


def sample(mode, directory, *, active_rounds=0):
    import faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["KOMI_DB_PATH"] = str(directory / "isolated.sqlite3")
    os.environ["KOMI_DISCOVERY_DISABLED"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
    def audit(event, args):
        if event in {"socket.connect", "subprocess.Popen", "os.system"}:
            raise OSError("network/process launch forbidden in footprint fixture")
    sys.addaudithook(audit)
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtNetwork import QLocalServer
    import database
    database.init_db()
    database.set_cfg("web_service_enabled", "0")
    if active_rounds:
        from services.device_config import DeviceConfig, DeviceConfigRepository
        DeviceConfigRepository().replace_all([DeviceConfig(slot, f"Fixture {slot + 1}",
            f"192.0.2.{10 + slot}", serial=f"FIXTURE-{slot}") for slot in range(3)])
    application = QApplication([])
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source" / "tests"))
    from qt_render_environment import configure_offscreen_fonts
    configure_offscreen_fonts(application)
    application.setQuitOnLastWindowClosed(False)
    if mode == "desktop":
        from app import MainWindow
        print("fixture: constructing desktop", file=sys.stderr, flush=True)
        owner = MainWindow()
        print("fixture: showing desktop", file=sys.stderr, flush=True)
        owner.show()
        print("fixture: refreshing desktop", file=sys.stderr, flush=True)
        owner._refresh_all()
        print("fixture: desktop prepared", file=sys.stderr, flush=True)
        tray = None
    else:
        from services.background_agent import BackgroundAgent
        from ui.agent_tray import AgentTray
        server = QLocalServer()
        owner = BackgroundAgent(server)
        tray = AgentTray(owner.stop, parent=owner)
    if active_rounds:
        # Use the real collector, persistence, signals and UI, but never contact
        # a printer or Host. Starting WebServiceManager can build release assets
        # in source mode; it is intentionally excluded from this experiment.
        from datetime import datetime, UTC
        from services.snmp_probe import SnmpProbeResult
        from komi_snmp_profiler.models import MeterReading, WebCounterValue, Confidence, WebAuthState
        class FixtureProbe:
            def read(self, host):
                slot = int(host.rsplit(".", 1)[1]) - 10
                return SnmpProbeResult(100000, "Fixture", f"FIXTURE-{slot}")
        class FixtureReader:
            def __init__(self):
                self.rounds = {f"192.0.2.{10 + slot}": 0 for slot in range(3)}
            def read(self, host):
                self.rounds[host] += 1
                total = 1000 + self.rounds[host]
                values = [WebCounterValue("counter.total.total", "Total", total * 100,
                    "Total", "fixture.total", Confidence.VERIFIED)]
                for index in range(100):
                    for field, value in (("total.total", total), ("print.bw_total", total)):
                        values.append(WebCounterValue("counter.user." + field, field, value,
                            "User", f"fixture.user[{index}].{field}", Confidence.VERIFIED,
                            "user", str(index), f"Fixture user {index}"))
                return MeterReading(host, datetime.now(UTC).isoformat(), tuple(values),
                    source="synthetic workload", auth_state=WebAuthState.ADMIN)
        owner.polling.probe = FixtureProbe()
        owner.polling.reader = FixtureReader()
        owner.polling.reading_saved.disconnect(owner.registration.meter_observed)
        owner.polling.resume()
    # Collect after queued paint/layout work. Workers are constructed but never
    # started: this isolates UI overhead and cannot establish active-agent cost.
    result = {}
    samples = []
    monitor = QTimer()
    monitor.setInterval(250)
    monitor.timeout.connect(lambda: samples.append(counters()))
    pump = QTimer()
    pump.setInterval(100)
    rounds_started = 0
    last_round = 0.0
    def active_step():
        nonlocal rounds_started, last_round
        if monotonic() - result["start"] > 75:
            result["error"] = "Workload did not drain within 75 seconds"
            pump.stop()
            finish()
            return
        if owner.polling.active:
            return
        if rounds_started == active_rounds:
            pump.stop()
            finish()
        elif monotonic() - last_round >= 1:
            owner.polling.poll_now()
            rounds_started += 1
            last_round = monotonic()
    pump.timeout.connect(active_step)
    def begin():
        print("fixture: sampling idle", file=sys.stderr, flush=True)
        result["before"] = counters()
        result["start"] = monotonic()
        monitor.start()
        if active_rounds:
            pump.start()
        else:
            QTimer.singleShot(5000, finish)
    def finish():
        print("fixture: finishing sample", file=sys.stderr, flush=True)
        result["after"] = counters()
        monitor.stop()
        result["elapsed_seconds"] = monotonic() - result.pop("start")
        result["one_core_cpu_percent"] = 100 * (result["after"]["cpu_seconds"] - result["before"]["cpu_seconds"]) / result["elapsed_seconds"]
        result["mode"] = mode
        result["pid"] = os.getpid()
        result["fixture"] = "empty DB; Web disabled; workers constructed but not started; offscreen"
        if active_rounds:
            with database._open(commit=False) as conn:
                result["web_events"] = conn.execute("SELECT COUNT(*) FROM web_observations").fetchone()[0]
                result["outgoing_events"] = conn.execute("SELECT COUNT(*) FROM web_observation_outbox").fetchone()[0]
            result["expected_events"] = active_rounds * 3
            result["fixture"] = "3 synthetic printers x 100 users x 2 user counters; real collector/workers/cache/journal; one round per second; Host/scheduler/Web service disabled; offscreen; child launches forbidden"
            result["complete"] = result["web_events"] == result["outgoing_events"] == result["expected_events"]
        result["sampled_peak_working_set_bytes"] = max(item["working_set_bytes"] for item in [result["before"], *samples, result["after"]])
        result["sampled_peak_private_bytes"] = max(item["private_bytes"] for item in [result["before"], *samples, result["after"]])
        result["child_processes"] = 0  # Enforced by audit hook, not assumed.
        if mode == "agent":
            assert not {"app", "pages", "v5_pages", "PyQt6.QtCharts"}.intersection(sys.modules)
        (directory / "sample.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("fixture: closing surface", file=sys.stderr, flush=True)
        if tray is not None:
            tray.close()
        else:
            owner._quitting = True
            owner.close()
        print("fixture: draining workers", file=sys.stderr, flush=True)
        owner.polling.stop(wait=True)
        owner.registration.stop(wait=True)
        # Let Qt dispose widgets while its event dispatcher still exists. The
        # benchmark owns these objects; leaving chart disposal to interpreter
        # teardown can crash Windows offscreen after the sample was written.
        owner.deleteLater()
        QTimer.singleShot(100, application.quit)
        print("fixture: clean quit requested", file=sys.stderr, flush=True)
    QTimer.singleShot(1000, begin)
    application.exec()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", choices=["desktop", "agent"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--active-rounds", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This measurement uses Windows process counters")
    if not 0 <= args.active_rounds <= 60 or not 1 <= args.repeats <= 5:
        parser.error("Use 0-60 active rounds and 1-5 repeats")
    if args.sample:
        sample(args.sample, args.directory, active_rounds=args.active_rounds)
    else:
        results = []
        for mode in ("desktop", "agent"):
            for _ in range(args.repeats):
                with tempfile.TemporaryDirectory(prefix="komi-idle-footprint-") as folder:
                    directory = Path(folder)
                    child = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()), "--sample", mode, "--directory", folder,
                         "--active-rounds", str(args.active_rounds)],
                        capture_output=True, text=True, timeout=100,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    sample_file = directory / "sample.json"
                    if not sample_file.exists():
                        raise RuntimeError(f"{mode} child exited {child.returncode}: {child.stderr}")
                    result = json.loads(sample_file.read_text(encoding="utf-8"))
                    result["exit_code"] = child.returncode
                    result["clean_shutdown"] = child.returncode == 0
                    if child.returncode:
                        result["shutdown_error"] = child.stderr[-4000:]
                    results.append(result)
        payload = json.dumps(results, indent=2)
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        print(payload)
        if any(not row["clean_shutdown"] or row.get("complete") is False for row in results):
            sys.exit(1)
