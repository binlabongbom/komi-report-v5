"""Run local live Phase 1 HTTPS/auth checks without customer data or fixed credentials."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cryptography import x509

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from services.lan_tls import discover_primary_lan_ip  # noqa: E402
from services.web_access import (  # noqa: E402
    set_web_access_code,
    update_web_runtime_values,
)
from tools.prepare_web_runtime import prepare  # noqa: E402

_WEB_PORT = 3000
_API_PORT = 8766


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, str] | None = None,
    cookie: str = "",
) -> tuple[int, dict[str, str], bytes]:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection("127.0.0.1", _WEB_PORT, context=context, timeout=3)
    headers = {"content-type": "application/json"}
    if cookie:
        headers["cookie"] = cookie
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
    finally:
        connection.close()


def _wait_https(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Web HTTPS process stopped with exit {process.returncode}")
        try:
            if _request("GET", "/login")[0] == 200:
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError("Web HTTPS did not become ready")


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _start_web(runtime: Path, log_handle) -> subprocess.Popen[bytes]:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is unavailable")
    process = subprocess.Popen(
        [npm, "run", "start"],
        cwd=runtime,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_https(process)
    except Exception as err:
        log_handle.flush()
        diagnostic = Path(log_handle.name).read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"Web HTTPS startup failed:\n{diagnostic}") from err
    return process


def _login(code: str, cookie_name: str = "komi_session") -> tuple[int, str, str]:
    status, headers, _ = _request(
        "POST",
        "/auth/session",
        body={"user": "admin", "code": code},
    )
    set_cookie = headers.get("set-cookie", "")
    cookie = set_cookie.split(";", 1)[0] if set_cookie.startswith(f"{cookie_name}=") else ""
    return status, cookie, set_cookie


def _plain_http_blocked() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _WEB_PORT), timeout=2) as connection:
            connection.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            response = connection.recv(16)
        return not response.startswith(b"HTTP/")
    except (ConnectionError, OSError, TimeoutError):
        return True


def run(project_root: Path) -> dict[str, object]:
    global _API_PORT, _WEB_PORT

    _WEB_PORT = _free_port()
    _API_PORT = _free_port()
    project_root = project_root.resolve()
    source_root = project_root / "source"
    web_source = project_root / "web"
    access_code = secrets.token_urlsafe(32)
    replacement_code = secrets.token_urlsafe(32)
    web_process: subprocess.Popen[bytes] | None = None
    api_process: subprocess.Popen[bytes] | None = None
    with tempfile.TemporaryDirectory(prefix="komi-phase1-live-") as temporary:
        runtime = Path(temporary) / "web-runtime"
        prepare(web_source, runtime)
        env_path = runtime / ".env.local"
        set_web_access_code(env_path, access_code)
        update_web_runtime_values(
            env_path,
            {"KOMI_WEB_SESSION_SECONDS": "2", "KOMI_WEB_PORT": str(_WEB_PORT)},
        )
        environment = os.environ.copy()
        environment["KOMI_DB_PATH"] = str(Path(temporary) / "live-check.db")
        with (Path(temporary) / "api.log").open("wb") as api_log, (
            Path(temporary) / "web.log"
        ).open("wb") as web_log:
            try:
                api_process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "web_api:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(_API_PORT),
                    ],
                    cwd=source_root,
                    env=environment,
                    stdout=api_log,
                    stderr=subprocess.STDOUT,
                )
                web_process = _start_web(runtime, web_log)
                with socket.create_connection(("127.0.0.1", _WEB_PORT), timeout=2) as raw:
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    with context.wrap_socket(raw, server_hostname="localhost") as secured:
                        certificate_der = secured.getpeercert(binary_form=True)
                        tls_version = secured.version()
                if not certificate_der:
                    raise RuntimeError("HTTPS handshake returned no certificate")
                certificate = x509.load_der_x509_certificate(certificate_der)
                san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                dns_names = {value.lower() for value in san.get_values_for_type(x509.DNSName)}
                ip_names = {str(value) for value in san.get_values_for_type(x509.IPAddress)}
                lan_ip = discover_primary_lan_ip()
                if "localhost" not in dns_names or "127.0.0.1" not in ip_names or lan_ip not in ip_names:
                    raise RuntimeError("generated certificate SAN does not cover localhost and current LAN IP")
                with socket.create_connection((lan_ip, _WEB_PORT), timeout=2) as lan_raw:
                    with context.wrap_socket(lan_raw, server_hostname=lan_ip) as lan_secured:
                        lan_handshake = lan_secured.version() is not None
                if not _plain_http_blocked():
                    raise RuntimeError("plain HTTP unexpectedly returned an HTTP response")
                with socket.create_connection(("127.0.0.1", _API_PORT), timeout=2):
                    api_loopback = True

                lockout_codes = []
                for _ in range(5):
                    status, _, _ = _request(
                        "POST",
                        "/auth/session",
                        body={"user": "blocked-user", "code": "incorrect"},
                    )
                    lockout_codes.append(status)
                state_text = (runtime / "security" / "web-auth-state.json").read_text(encoding="utf-8")
                if "blocked-user" in state_text or "incorrect" in state_text:
                    raise RuntimeError("auth state persisted plaintext login input")

                login_status, expiring_cookie, set_cookie = _login(access_code)
                if login_status != 200 or not expiring_cookie:
                    raise RuntimeError("valid login failed")
                cookie_flags = {
                    "secure": "secure" in set_cookie.lower(),
                    "httponly": "httponly" in set_cookie.lower(),
                    "samesite_strict": "samesite=strict" in set_cookie.lower(),
                }
                time.sleep(3)
                expiry_status = _request("GET", "/", cookie=expiring_cookie)[0]

                update_web_runtime_values(env_path, {"KOMI_WEB_SESSION_SECONDS": "30"})
                _stop(web_process)
                web_process = _start_web(runtime, web_log)
                lockout_after_restart = _request(
                    "POST",
                    "/auth/session",
                    body={"user": "blocked-user", "code": "incorrect"},
                )[0]
                _, restart_cookie, _ = _login(access_code)
                _stop(web_process)
                web_process = _start_web(runtime, web_log)
                restart_status = _request("GET", "/", cookie=restart_cookie)[0]

                set_web_access_code(env_path, replacement_code)
                _stop(web_process)
                web_process = _start_web(runtime, web_log)
                revoked_status = _request("GET", "/", cookie=restart_cookie)[0]
                replacement_status, logout_cookie, _ = _login(replacement_code)
                logout_status, logout_headers, _ = _request(
                    "DELETE", "/auth/session", cookie=logout_cookie
                )
                cleared_cookie = logout_headers.get("set-cookie", "").split(";", 1)[0]
                after_logout = _request("GET", "/", cookie=cleared_cookie)[0]

                result = {
                    "tls": tls_version,
                    "lan_handshake": lan_handshake,
                    "san_covers_localhost_and_lan": True,
                    "http_lan_blocked": True,
                    "api_loopback_connect": api_loopback,
                    "lockout_codes": lockout_codes,
                    "auth_state_plaintext": False,
                    "cookie_flags": cookie_flags,
                    "session_expiry_status": expiry_status,
                    "lockout_after_restart": lockout_after_restart,
                    "session_restart_status": restart_status,
                    "password_change_revoked_status": revoked_status,
                    "replacement_login_status": replacement_status,
                    "logout_status": logout_status,
                    "after_logout_status": after_logout,
                }
                expected = {
                    "session_expiry_status": 307,
                    "lockout_after_restart": 429,
                    "session_restart_status": 200,
                    "password_change_revoked_status": 307,
                    "replacement_login_status": 200,
                    "logout_status": 200,
                    "after_logout_status": 307,
                }
                if lockout_codes[-1] != 429 or not all(cookie_flags.values()):
                    raise RuntimeError(f"live auth checks failed: {result}")
                for key, value in expected.items():
                    if result[key] != value:
                        raise RuntimeError(f"live auth check {key} expected {value}, got {result[key]}")
                return result
            finally:
                _stop(web_process)
                _stop(api_process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run KOMI Phase 1 local HTTPS/auth live checks")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.project_root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
