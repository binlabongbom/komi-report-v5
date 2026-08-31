"""Lifecycle manager for the optional local KOMI Web service."""

from __future__ import annotations

import http.client
import http.server
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WebServiceState = Literal["stopped", "starting", "running", "external", "failed"]
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_TRUSTED_EDGE_HEADERS = frozenset({"x-komi-remote-address", "x-forwarded-proto"})


def _proxy_request_headers(
    incoming: object,
    *,
    remote_address: str,
) -> dict[str, str]:
    """Strip client-supplied identity headers and add edge-authenticated values."""

    headers = {
        str(key): str(value)
        for key, value in incoming.items()
        if str(key).casefold() not in _HOP_BY_HOP_HEADERS | _TRUSTED_EDGE_HEADERS
    }
    headers["x-komi-remote-address"] = str(remote_address)
    headers["x-forwarded-proto"] = "https"
    return headers


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
        self._packaged_thread: threading.Thread | None = None
        self._packaged_stop = threading.Event()
        self._last_start_failed = False
        self._lock = threading.RLock()

    def start(self) -> WebServiceStatus:
        with self._lock:
            current = self.status()
            if current.state in {"starting", "running", "external"}:
                return current
            if getattr(sys, "frozen", False):
                bundle_root = Path(
                    getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
                ).resolve()
                seed = bundle_root / "web-runtime-seed"
                node_name = "node.exe" if sys.platform.startswith("win") else "node"
                node = bundle_root / "node-runtime" / node_name
                if not (seed / ".next" / "BUILD_ID").is_file() or not node.is_file():
                    self._last_start_failed = True
                    return self.status(detail="ตัวติดตั้งไม่มี Web runtime ที่สมบูรณ์")
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._packaged_stop.clear()
                self._last_start_failed = False
                self._packaged_thread = threading.Thread(
                    target=self._run_packaged_service,
                    args=(bundle_root, seed, node),
                    name="komi-packaged-web-service",
                    daemon=True,
                )
                self._packaged_thread.start()
                return self.status(detail="กำลังเตรียม Web runtime และเปิด service…")
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
            packaged_thread = self._packaged_thread
            if packaged_thread is not None and packaged_thread.is_alive():
                self._packaged_stop.set()
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=3)
            self._process = None
        if packaged_thread is not None and packaged_thread.is_alive():
            packaged_thread.join(timeout=12)
        with self._lock:
            self._packaged_thread = None
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
            process_running = (
                self._process is not None and self._process.poll() is None
            ) or (
                self._packaged_thread is not None and self._packaged_thread.is_alive()
            )
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

    def _run_packaged_service(self, bundle_root: Path, seed: Path, node: Path) -> None:
        """Run the packaged API and HTTPS Web viewer without system Python/npm.

        PyInstaller's ``sys.executable`` points back to the Desktop executable,
        so the source-mode worker launcher cannot be reused inside a customer
        ``.app``.  The API therefore runs in a bounded background thread while
        the bundled Node executable serves the pre-built Next standalone seed.
        """

        node_process: subprocess.Popen[bytes] | None = None
        api_thread: threading.Thread | None = None
        proxy_thread: threading.Thread | None = None
        proxy_server: http.server.ThreadingHTTPServer | None = None
        api_server = None
        try:
            self._prepare_packaged_runtime(seed)

            from services.lan_tls import discover_primary_lan_ip, resolve_lan_tls
            from services.web_access import read_web_runtime_values, update_web_runtime_values
            from tools.init_web_access import ensure_web_access

            env_path = self.runtime_root / ".env.local"
            ensure_web_access(env_path)
            runtime_values = read_web_runtime_values(env_path)
            customer_mode = runtime_values.get("KOMI_TLS_MODE") == "customer"
            material = resolve_lan_tls(
                self.runtime_root,
                configured_certificate=(
                    runtime_values.get("KOMI_TLS_CERT_FILE", "") if customer_mode else ""
                ),
                configured_private_key=(
                    runtime_values.get("KOMI_TLS_KEY_FILE", "") if customer_mode else ""
                ),
                hostname=socket.gethostname(),
                lan_ips=[discover_primary_lan_ip()],
            )
            update_web_runtime_values(
                env_path,
                {
                    "KOMI_TLS_MODE": material.source,
                    "KOMI_TLS_CERT_FILE": str(material.certificate_path),
                    "KOMI_TLS_KEY_FILE": str(material.private_key_path),
                    "KOMI_WEB_AUTH_STATE_FILE": str(
                        self.runtime_root / "security" / "web-auth-state.json"
                    ),
                },
            )

            import uvicorn

            from web_api import app as api_app

            api_server = uvicorn.Server(
                uvicorn.Config(
                    api_app,
                    host="127.0.0.1",
                    port=8766,
                    access_log=False,
                    log_level="warning",
                )
            )
            api_thread = threading.Thread(
                target=api_server.run,
                name="komi-packaged-web-api",
                daemon=True,
            )
            api_thread.start()
            self._wait_for_port(8766, timeout=20)

            environment = os.environ.copy()
            environment.update(read_web_runtime_values(env_path))
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["HOSTNAME"] = "127.0.0.1"
            environment["PORT"] = "3001"
            log_handle = self.log_path.open("ab")
            try:
                node_process = subprocess.Popen(
                    [str(node), "server.js"],
                    cwd=self.runtime_root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        if sys.platform.startswith("win")
                        else 0
                    ),
                )
            finally:
                log_handle.close()
            self._wait_for_port(3001, timeout=30, process=node_process)

            proxy_server = self._https_proxy_server(
                certificate=material.certificate_path,
                private_key=material.private_key_path,
            )
            proxy_thread = threading.Thread(
                target=proxy_server.serve_forever,
                name="komi-packaged-https-proxy",
                daemon=True,
            )
            proxy_thread.start()
            self._wait_for_port(3000, timeout=10)

            while not self._packaged_stop.wait(0.5):
                if node_process.poll() is not None:
                    raise RuntimeError(f"Web service หยุดทำงาน (exit {node_process.returncode})")
                if api_thread is not None and not api_thread.is_alive():
                    raise RuntimeError("Web API หยุดทำงาน")
        except Exception:
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write("\n[packaged-web-error]\n")
                stream.write(traceback.format_exc())
            with self._lock:
                self._last_start_failed = True
        finally:
            if proxy_server is not None:
                proxy_server.shutdown()
                proxy_server.server_close()
            if proxy_thread is not None and proxy_thread.is_alive():
                proxy_thread.join(timeout=5)
            if node_process is not None and node_process.poll() is None:
                node_process.terminate()
                try:
                    node_process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    node_process.kill()
                    node_process.wait(timeout=3)
            if api_server is not None:
                api_server.should_exit = True
            if api_thread is not None and api_thread.is_alive():
                api_thread.join(timeout=8)

    def _prepare_packaged_runtime(self, seed: Path) -> None:
        seed_build = (seed / ".next" / "BUILD_ID").read_text(encoding="utf-8").strip()
        runtime_build_path = self.runtime_root / ".next" / "BUILD_ID"
        runtime_build = (
            runtime_build_path.read_text(encoding="utf-8").strip()
            if runtime_build_path.is_file()
            else ""
        )
        if runtime_build == seed_build:
            return
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        for relative in (".next", "node_modules"):
            stale = self.runtime_root / relative
            if stale.is_dir():
                shutil.rmtree(stale)
        shutil.copytree(seed, self.runtime_root, dirs_exist_ok=True)

    @staticmethod
    def _https_proxy_server(
        *, certificate: Path, private_key: Path
    ) -> http.server.ThreadingHTTPServer:
        """Expose the standalone Next server through TLS without build tooling."""

        class ProxyHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _proxy(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length) if length else None
                headers = _proxy_request_headers(
                    self.headers,
                    remote_address=str(self.client_address[0]),
                )
                upstream = http.client.HTTPConnection("127.0.0.1", 3001, timeout=30)
                try:
                    upstream.request(self.command, self.path, body=body, headers=headers)
                    response = upstream.getresponse()
                    payload = response.read()
                    self.send_response(response.status, response.reason)
                    for key, value in response.getheaders():
                        if key.casefold() not in _HOP_BY_HOP_HEADERS | {"content-length"}:
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(payload)
                except (OSError, http.client.HTTPException):
                    self.send_error(502, "KOMI Web upstream unavailable")
                finally:
                    upstream.close()

            do_GET = _proxy
            do_HEAD = _proxy
            do_POST = _proxy
            do_PUT = _proxy
            do_PATCH = _proxy
            do_DELETE = _proxy
            do_OPTIONS = _proxy

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = http.server.ThreadingHTTPServer(("0.0.0.0", 3000), ProxyHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(certificate), keyfile=str(private_key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        return server

    @staticmethod
    def _wait_for_port(
        port: int,
        *,
        timeout: float,
        process: subprocess.Popen[bytes] | None = None,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"service หยุดก่อนพร้อมใช้งาน (exit {process.returncode})")
            if _port_open(port):
                return
            time.sleep(0.25)
        raise TimeoutError(f"service port {port} ไม่พร้อมภายใน {timeout:.0f} วินาที")


_manager: WebServiceManager | None = None


def web_service_manager() -> WebServiceManager:
    global _manager
    if _manager is None:
        root = os.environ.get("KOMI_PROJECT_ROOT")
        _manager = WebServiceManager(Path(root) if root else None)
    return _manager
