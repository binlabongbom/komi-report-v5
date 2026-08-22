from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def _wait_for_port(host: str, port: int, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server หยุดก่อนพร้อมใช้งาน (exit {process.returncode})")
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"server ที่ {host}:{port} ไม่พร้อมภายใน {timeout:.0f} วินาที")


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run(
    source_root: Path,
    web_runtime: Path,
    *,
    open_browser: bool = True,
    parent_pid: int | None = None,
) -> int:
    source_root = source_root.resolve()
    web_runtime = web_runtime.expanduser().resolve()
    api_ready = _port_open("127.0.0.1", 8766)
    web_ready = _port_open("127.0.0.1", 3000)
    if api_ready and web_ready:
        local_url = "http://127.0.0.1:3000"
        print(f"KOMI Report Web ทำงานอยู่แล้ว: {local_url}", flush=True)
        if open_browser:
            webbrowser.open(local_url)
        return 0
    if api_ready or web_ready:
        raise RuntimeError(
            "พบ Web service เพียงบางส่วน กรุณาปิด process ที่ใช้ port 3000/8766 แล้วเปิดใหม่"
        )
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("ไม่พบ Node.js/npm กรุณาติดตั้ง Node.js LTS ก่อน")
    if not (web_runtime / ".next" / "BUILD_ID").is_file():
        raise FileNotFoundError(f"ไม่พบ Web build ใน runtime: {web_runtime}")

    api: subprocess.Popen[bytes] | None = None
    web: subprocess.Popen[bytes] | None = None
    previous_handlers: dict[int, signal.Handlers] = {}

    def stop_from_signal(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, stop_from_signal)

    try:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "web_api:app", "--host", "127.0.0.1", "--port", "8766"],
            cwd=source_root,
            env=environment,
        )
        _wait_for_port("127.0.0.1", 8766, api)

        web = subprocess.Popen([npm, "run", "start"], cwd=web_runtime, env=environment)
        _wait_for_port("127.0.0.1", 3000, web)

        local_url = "http://127.0.0.1:3000"
        print(f"KOMI Report Web พร้อม: {local_url}", flush=True)
        print(f"ผู้ใช้ใน Trusted LAN เปิดได้ที่: http://{_lan_ip()}:3000", flush=True)
        print("ปิดหน้าต่างนี้เพื่อหยุด Web Server", flush=True)
        if open_browser:
            webbrowser.open(local_url)

        while True:
            if parent_pid is not None and not _process_alive(parent_pid):
                return 0
            if api.poll() is not None:
                raise RuntimeError(f"Python API หยุดทำงาน (exit {api.returncode})")
            if web.poll() is not None:
                return int(web.returncode or 0)
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        _stop(web)
        _stop(api)
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local KOMI API and Web viewer together.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    return run(args.source, args.runtime, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
