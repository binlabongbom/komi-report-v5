"""Windows source-only idle footprint experiment on fresh temporary databases.

This measures constructed UI/agent surfaces, NOT printer/Web/Host workloads.
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


def sample(mode, directory):
    import faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["KOMI_DB_PATH"] = str(directory / "isolated.sqlite3")
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
    # Collect after queued paint/layout work. Workers are constructed but never
    # started: this isolates UI overhead and cannot establish active-agent cost.
    result = {}
    def begin():
        print("fixture: sampling idle", file=sys.stderr, flush=True)
        result["before"] = counters()
        result["start"] = monotonic()
        QTimer.singleShot(5000, finish)
    def finish():
        print("fixture: finishing sample", file=sys.stderr, flush=True)
        result["after"] = counters()
        result["elapsed_seconds"] = monotonic() - result.pop("start")
        result["one_core_cpu_percent"] = 100 * (result["after"]["cpu_seconds"] - result["before"]["cpu_seconds"]) / result["elapsed_seconds"]
        result["mode"] = mode
        result["pid"] = os.getpid()
        result["fixture"] = "empty DB; Web disabled; workers constructed but not started; offscreen"
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
        application.quit()
        print("fixture: clean quit requested", file=sys.stderr, flush=True)
    QTimer.singleShot(1000, begin)
    application.exec()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", choices=["desktop", "agent"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This measurement uses Windows process counters")
    if args.sample:
        sample(args.sample, args.directory)
    else:
        results = []
        for mode in ("desktop", "agent"):
            for _ in range(3):
                with tempfile.TemporaryDirectory(prefix="komi-idle-footprint-") as folder:
                    directory = Path(folder)
                    child = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()), "--sample", mode, "--directory", folder],
                        capture_output=True, text=True, timeout=45,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if child.returncode:
                        raise RuntimeError(f"{mode} child exited {child.returncode}: {child.stderr}")
                    results.append(json.loads((directory / "sample.json").read_text(encoding="utf-8")))
        payload = json.dumps(results, indent=2)
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        print(payload)
