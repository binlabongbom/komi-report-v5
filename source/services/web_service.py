"""Lifecycle manager for the optional local KOMI Web service."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WebServiceState = Literal["stopped", "starting", "running", "external", "failed"]


@dataclass(frozen=True)
class WebServiceStatus:
    state: WebServiceState
    local_url: str
    lan_url: str
    detail: str
    log_path: Path


def app_data_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KOMI Report V5"
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "KOMI Report V5"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "komi-report-v5"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"


class WebServiceManager:
    """Start one Web worker next to the Desktop process and stop it on exit."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.runtime_root = app_data_home() / "web-runtime"
        self.log_path = app_data_home() / "logs" / "web-service.log"
        self._process: subprocess.Popen[bytes] | None = None
        self._last_start_failed = False
        self._lock = threading.RLock()

    def start(self) -> WebServiceStatus:
        with self._lock:
            current = self.status()
            if current.state in {"starting", "running", "external"}:
                return current
            source_root = self.project_root / "source"
            worker = source_root / "tools" / "web_service_worker.py"
            web_source = self.project_root / "web"
            if not worker.is_file() or not (web_source / "package-lock.json").is_file():
                self._last_start_failed = True
                return self.status(detail="ไม่พบ Web source กลาง กรุณารอ OneDrive sync ให้ครบ")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = self.log_path.open("ab")
            command = [
                sys.executable,
                str(worker),
                "--project-root",
                str(self.project_root),
                "--runtime",
                str(self.runtime_root),
                "--parent-pid",
                str(os.getpid()),
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=source_root,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            except OSError as err:
                self._last_start_failed = True
                log_handle.close()
                return self.status(detail=f"เริ่ม Web service ไม่ได้: {err}")
            log_handle.close()
            self._last_start_failed = False
            return self.status(detail="กำลังเตรียม Web runtime และเปิด service…")

    def stop(self) -> WebServiceStatus:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=3)
            self._process = None
            self._last_start_failed = False
            return self.status()

    def restart(self) -> WebServiceStatus:
        """Restart a worker owned by this Desktop process."""

        with self._lock:
            current = self.status()
            if current.state == "external":
                return self.status(
                    detail="บันทึกรหัสแล้ว แต่ Web service เปิดจากโปรแกรมอื่น กรุณาปิดและเปิดใหม่"
                )
            if self._process is not None and self._process.poll() is None:
                self.stop()
            return self.start()

    def status(self, *, detail: str | None = None) -> WebServiceStatus:
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None
            web_ready = _port_open(3000)
            api_ready = _port_open(8766)
            if web_ready and api_ready:
                state: WebServiceState = "running" if process_running else "external"
                default_detail = "Web service พร้อมใช้งาน"
            elif process_running:
                state = "starting"
                default_detail = "กำลังเตรียม Web runtime หรือรอ service พร้อม"
            elif self._last_start_failed or self._process is not None:
                state = "failed"
                default_detail = "Web service เริ่มไม่สำเร็จ · เปิด Log เพื่อดูรายละเอียด"
            else:
                state = "stopped"
                default_detail = "Web service ปิดอยู่"
            return WebServiceStatus(
                state=state,
                local_url="https://127.0.0.1:3000",
                lan_url=f"https://{_lan_ip()}:3000",
                detail=detail or default_detail,
                log_path=self.log_path,
            )


_manager: WebServiceManager | None = None


def web_service_manager() -> WebServiceManager:
    global _manager
    if _manager is None:
        root = os.environ.get("KOMI_PROJECT_ROOT")
        _manager = WebServiceManager(Path(root) if root else None)
    return _manager
