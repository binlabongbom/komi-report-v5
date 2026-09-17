from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from services.web_access import read_web_runtime_values
from services.web_service import WebServiceManager
from services.web_port import read_web_port


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


def _https_open(host: str, port: int) -> bool:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=0.5) as connection:
            with context.wrap_socket(connection, server_hostname=host):
                return True
    except OSError:
        return False


def _wait_for_https(host: str, port: int, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"HTTPS server หยุดก่อนพร้อมใช้งาน (exit {process.returncode})")
        if _https_open(host, port):
            return
        time.sleep(0.25)
    raise TimeoutError(f"HTTPS server ที่ {host}:{port} ไม่พร้อมภายใน {timeout:.0f} วินาที")


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
    if sys.platform.startswith("win"):
        # os.kill(pid, 0) terminates the process on Windows. Query its handle
        # without sending any signal to the Desktop that owns this worker.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
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
    stop_file: Path | None = None,
) -> int:
    source_root = source_root.resolve()
    web_runtime = web_runtime.expanduser().resolve()
    port = read_web_port(web_runtime / ".env.local")
    api_ready = _port_open("127.0.0.1", 8766)
    web_port_open = _port_open("127.0.0.1", port)
    web_ready = _https_open("127.0.0.1", port) if web_port_open else False
    if api_ready and web_ready:
        local_url = f"https://{_lan_ip()}:{port}"
        print(f"KOMI Report Web ทำงานอยู่แล้ว: {local_url}", flush=True)
        if open_browser:
            webbrowser.open(local_url)
        return 0
    if api_ready or web_port_open:
        raise RuntimeError(
            f"พบ Web service เพียงบางส่วน กรุณาปิด process ที่ใช้ port {port}/8766 แล้วเปิดใหม่"
        )
    if not (web_runtime / ".next" / "BUILD_ID").is_file():
        raise FileNotFoundError(f"ไม่พบ Web build ใน runtime: {web_runtime}")

    standalone = (web_runtime / "server.js").is_file()
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    node = shutil.which("node.exe") or shutil.which("node")
    if standalone and node is None:
        raise RuntimeError("ไม่พบ Node.js runtime ที่มากับตัวติดตั้ง")
    if not standalone and npm is None:
        raise RuntimeError("ไม่พบ Node.js/npm กรุณาติดตั้ง Node.js LTS ก่อน")

    api: subprocess.Popen[bytes] | None = None
    web: subprocess.Popen[bytes] | None = None
    proxy = None
    proxy_thread = None
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

        runtime_values = read_web_runtime_values(web_runtime / ".env.local")
        environment.update(runtime_values)
        environment["KOMI_WEB_PORT"] = str(port)
        if standalone:
            certificate = Path(runtime_values.get("KOMI_TLS_CERT_FILE", ""))
            private_key = Path(runtime_values.get("KOMI_TLS_KEY_FILE", ""))
            if not certificate.is_file() or not private_key.is_file():
                raise RuntimeError("ไม่พบ Certificate สำหรับเปิด Web Report ผ่าน HTTPS")
            environment.update(runtime_values)
            environment["HOSTNAME"] = "127.0.0.1"
            environment["PORT"] = "3001"
            web = subprocess.Popen([str(node), "server.js"], cwd=web_runtime, env=environment)
            _wait_for_port("127.0.0.1", 3001, web)
            proxy = WebServiceManager._https_proxy_server(
                certificate=certificate,
                private_key=private_key,
                port=port,
            )
            import threading

            proxy_thread = threading.Thread(
                target=proxy.serve_forever,
                name="komi-installer-https-proxy",
                daemon=True,
            )
            proxy_thread.start()
            _wait_for_https("127.0.0.1", port, web)
        else:
            web = subprocess.Popen([str(npm), "run", "start"], cwd=web_runtime, env=environment)
            _wait_for_https("127.0.0.1", port, web)

        local_url = f"https://{_lan_ip()}:{port}"
        print(f"KOMI Report Web พร้อม: {local_url}", flush=True)
        print(f"ผู้ใช้ใน LAN เปิดแบบเข้ารหัสได้ที่: https://{_lan_ip()}:{port}", flush=True)
        print("ปิดหน้าต่างนี้เพื่อหยุด Web Server", flush=True)
        if open_browser:
            webbrowser.open(local_url)

        while True:
            if stop_file is not None and stop_file.exists():
                return 0
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
        if proxy is not None:
            proxy.shutdown()
            proxy.server_close()
        if proxy_thread is not None and proxy_thread.is_alive():
            proxy_thread.join(timeout=5)
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
