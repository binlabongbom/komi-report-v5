"""Apply the reviewed v5.2.11 changes to the exact v5.2.10 source, once.

This authoring helper is not shipped in the customer runtime. It validates every
replacement and parses all changed Python files before writing any of them.
"""
from __future__ import annotations
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
changes: dict[str, str] = {}

def read(path: str) -> str:
    return changes.get(path, (ROOT / path).read_text(encoding="utf-8"))

def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    if text.count(old) != count:
        raise RuntimeError(f"Unexpected source at {path}: expected {count} replacements, got {text.count(old)}")
    changes[path] = text.replace(old, new)

def method(path: str, class_name: str, name: str, replacement: str) -> None:
    text = read(path)
    tree = ast.parse(text)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    target = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    lines = text.splitlines(keepends=True)
    changes[path] = ''.join(lines[:target.lineno - 1]) + replacement.rstrip() + '\n' + ''.join(lines[target.end_lineno:])

ERRORS = r'''"""Safe registration diagnostics shared by transport, state and UI.

Never classify by arbitrary exception text or expose raw errors/customer data.
"""
from __future__ import annotations
import errno
import socket
import ssl
from urllib.error import URLError

NETWORK_CODES = frozenset({"offline", "dns_error", "connection_timeout", "connection_refused", "connection_reset", "network_unreachable", "tls_certificate_error", "tls_error", "response_too_large"})
SUPPORT_CODES = NETWORK_CODES | frozenset({"registration_pending", "proxy_auth_required", "host_redirect", "rate_limited", "host_unavailable", "offline_edition"})


def classify_network_error(error: BaseException) -> str:
    reason = error
    seen: set[int] = set()
    while isinstance(reason, URLError) and isinstance(reason.reason, BaseException):
        if id(reason) in seen:
            return "offline"
        seen.add(id(reason))
        reason = reason.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "tls_certificate_error"
    if isinstance(reason, ssl.SSLError):
        return "tls_error"
    if isinstance(reason, socket.gaierror):
        return "dns_error"
    number = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
    if isinstance(reason, TimeoutError) or number in {errno.ETIMEDOUT, 10060}:
        return "connection_timeout"
    if isinstance(reason, ConnectionRefusedError) or number in {errno.ECONNREFUSED, 10061}:
        return "connection_refused"
    if isinstance(reason, ConnectionResetError) or number in {errno.ECONNRESET, 10054}:
        return "connection_reset"
    if number in {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}:
        return "network_unreachable"
    return "offline"


class RegistrationNetworkError(RuntimeError):
    def __init__(self, code: str = "offline") -> None:
        self.code = code if code in NETWORK_CODES else "offline"
        self.retryable = self.code != "response_too_large"
        super().__init__(self.code)


MESSAGES = {
    "offline": ("ติดต่อ Host ไม่สำเร็จ ตรวจสอบการเชื่อมต่อและ Proxy แล้วลองอีกครั้ง", "Host connection failed. Check connectivity and proxy settings, then retry."),
    "dns_error": ("ค้นหาชื่อ Host ไม่สำเร็จ ตรวจสอบ DNS ของเครื่องนี้", "Host name lookup failed. Check this computer's DNS."),
    "connection_timeout": ("การเชื่อมต่อ Host หมดเวลา ลองอีกครั้งเมื่อเครือข่ายพร้อม", "Host connection timed out. Retry when the network is available."),
    "connection_refused": ("Host ปฏิเสธการเชื่อมต่อ ให้ผู้ดูแลตรวจ Service และ Firewall", "Connection refused. Ask the administrator to check the service and firewall."),
    "connection_reset": ("การเชื่อมต่อถูกตัดระหว่างทาง กรุณาลองอีกครั้ง", "The connection was reset. Please retry."),
    "network_unreachable": ("ไม่พบเส้นทางไปยัง Host ตรวจสอบ Network หรือ VPN", "No route to the Host. Check the network or VPN."),
    "tls_certificate_error": ("ยืนยัน Certificate ของ Host ไม่สำเร็จ ตรวจสอบเวลาเครื่องและ CA กับผู้ดูแล ห้ามปิดการตรวจ Certificate", "Host certificate verification failed. Check the system clock and CA with the administrator; do not disable verification."),
    "tls_error": ("เชื่อมต่อ TLS ไม่สำเร็จ ให้ผู้ดูแลตรวจ Proxy และ TLS", "TLS negotiation failed. Ask the administrator to check proxy and TLS settings."),
    "response_too_large": ("ข้อมูลตอบกลับจาก Host เกินขนาดที่อนุญาต ติดต่อผู้ดูแล", "The Host response exceeds the size limit. Contact support."),
    "registration_pending": ("ยังไม่ได้รับผลการลงทะเบียน กำลังรอผล คุณยกเลิกหน้าต่างได้โดยไม่ลบการตั้งค่า", "Registration is still pending. You may close this dialog without deleting the saved setup."),
    "proxy_auth_required": ("Proxy ต้องการการยืนยันตัวตน ติดต่อผู้ดูแล Network", "The proxy requires authentication. Contact the network administrator."),
    "host_redirect": ("Host ส่ง Redirect แทน API ที่กำหนด ติดต่อผู้ดูแล", "The Host returned a redirect instead of the configured API. Contact support."),
    "rate_limited": ("Host จำกัดจำนวนคำขอ ระบบจะรอตามเวลาที่ Host กำหนด", "The Host is rate limiting requests. The app will respect its retry delay."),
    "host_unavailable": ("Host ยังไม่พร้อมให้บริการ ระบบจะลองใหม่ตามกำหนด", "The Host is temporarily unavailable. A retry is scheduled."),
    "offline_edition": ("ตัวติดตั้ง Offline ไม่เชื่อมต่อ Host กรุณาใช้ Offline License", "The Offline edition cannot contact the Host. Use an Offline License."),
    "client_not_configured": ("ยังไม่ได้ตั้งค่าการเชื่อมต่อ Host", "The Host connection is not configured."),
    "validation_error": ("Host ไม่รับข้อมูลการลงทะเบียนชุดนี้ ติดต่อผู้ดูแล", "The Host rejected this registration data. Contact support."),
    "contract_invalid": ("รูปแบบข้อมูลตอบกลับจาก Host ไม่ถูกต้อง ติดต่อผู้ดูแล", "The Host response contract is invalid. Contact support."),
    "vault_unavailable": ("ไม่สามารถเก็บข้อมูลลงทะเบียนอย่างปลอดภัยได้ ตรวจสอบ OS credential vault", "Secure registration storage is unavailable. Check the OS credential vault."),
}


def error_message(code: str) -> tuple[str, str]:
    return MESSAGES.get(code, ("ลงทะเบียนไม่สำเร็จ ติดต่อผู้ดูแลพร้อม Support Code", "Registration failed. Contact support with the Support Code."))


def safe_support_code(code: str) -> str:
    known = SUPPORT_CODES | frozenset(MESSAGES) | {"registration_conflict", "registration_required", "installation_token_unavailable", "request_fingerprint_mismatch", "http_error", "needs_review", "retrying"}
    return code if code in known else "needs_review"
'''
EDITION = '''"""Build-time edition; Offline cannot be enabled for Host traffic by config/env.

Only the packaging pipeline replaces BUILD_EDITION in the staged payload.
Offline activation still requires a valid Host-signed license.
"""
BUILD_EDITION = "normal"


def is_offline_edition() -> bool:
    if BUILD_EDITION not in {"normal", "offline"}:
        raise RuntimeError("Invalid KOMI build edition")
    return BUILD_EDITION == "offline"
'''

PEER_DEFAULT = r'''
def ensure_pairing_default(installation_id: str, *, primary: bool = True, now: float | None = None) -> bool:
    """Migrate a Primary to persistent approval once; preserve explicit choices.

    Legacy 'off' was represented by no file, so it cannot be distinguished from
    a never-configured default. Schema 2 persists an explicit disabled state.
    Never replace live claims on an ordinary restart.
    """
    if not primary:
        return False
    identity = str(installation_id or "").strip()
    if not identity:
        return False
    path = state_path()
    current = float(time.time() if now is None else now)
    with _state_lock(path):
        payload = _read_state(path)
        if path.exists() and not payload:
            raise PeerSyncAuthorizationError("สถานะ Peer Sync เสียหาย กรุณาตั้งค่าใหม่โดยผู้ดูแล")
        if payload.get("schema") == 2 and payload.get("installation_id") == identity:
            return False
        if payload.get("schema") == 2:
            disabled = bool(payload.get("disabled"))
            always = bool(payload.get("always_open")) and not disabled
        else:
            disabled, always = False, True
        _write_state(path, {
            "schema": 2, "disabled": disabled, "always_open": always,
            "claims": {}, "window_expires_at": 0.0,
            "installation_id": identity, "requester_ip": "", "token_sha256": "",
            "token_expires_at": 0.0, "used": False,
            "default_migrated_at": current,
        })
    return True
'''
POLL = '''    def _poll_registration_result(self) -> None:
        if not self._registration_in_progress:
            return
        runtime = self.registration_runtime
        if runtime is None:
            self._show_registration_failure("client_not_configured")
            return
        snapshot = runtime.snapshot()
        # Wait for the active attempt, not stale status left by a previous one.
        if snapshot.get("request_in_progress"):
            if self._registration_deadline and datetime.now().astimezone() >= self._registration_deadline:
                self.registration_result_copy.setText(tr(*error_message("registration_pending")))
            return
        status = str(snapshot.get("status") or "")
        if status == "registered":
            self._registration_succeeded()
            return
        if status in {"needs_review", "retrying"}:
            self._show_registration_failure(str(snapshot.get("support_code") or status))
            return
        if self._registration_deadline and datetime.now().astimezone() >= self._registration_deadline:
            # The UI deadline is not a network diagnosis. Keep observing so a
            # late success updates this same dialog; Cancel remains available.
            self.registration_result_copy.setText(tr(*error_message("registration_pending")))
'''
FAILURE = '''    def _show_registration_failure(self, code: str) -> None:
        if self._registration_poll_timer is not None:
            self._registration_poll_timer.stop()
        self._registration_in_progress = False
        self.next_button.setEnabled(True)
        self.registration_progress.setVisible(False)
        safe = safe_support_code(code)
        self.registration_result_copy.setStyleSheet(f"color:{C_RED};font-weight:700;")
        self.registration_result_copy.setText(
            tr(*error_message(safe)) + "\\nSupport Code: " + safe
            + "\\n" + tr("การตั้งค่าถูกเก็บไว้แล้ว กดยกเลิกเพื่อกลับไปตรวจสอบ", "Your setup is saved. Cancel to review it.")
        )
        self.registration_retry_button.setVisible(True)
        self.registration_offline_button.setVisible(OFFLINE_ACTIVATION_ENABLED)
        self.registration_status_label.setText(tr("ต้องลงทะเบียน", "Registration required"))
'''


def plan() -> None:
    if (ROOT / "source/services/build_edition.py").exists():
        raise RuntimeError("v5.2.11 authoring changes are already applied; do not reapply")
    changes["source/services/registration_errors.py"] = ERRORS
    changes["source/services/build_edition.py"] = EDITION
    p = "source/services/v5_2_client.py"
    replace(p, "import json\n", "import json\nfrom datetime import UTC, datetime\nfrom email.utils import parsedate_to_datetime\nfrom services.build_edition import is_offline_edition\nfrom services.registration_errors import RegistrationNetworkError, classify_network_error\n")
    replace(p, "class V52NetworkError(RuntimeError):", "class V52NetworkError(RegistrationNetworkError):")
    replace(p, 'raise V52NetworkError("V5.2 response exceeds size limit")', 'raise V52NetworkError("response_too_large")')
    replace(p, 'raise V52NetworkError("V5.2 network request failed") from err', 'raise V52NetworkError(classify_network_error(err)) from None')
    replace(p, '        if request_fingerprint(operation.payload) != operation.request_fingerprint:', '        if is_offline_edition():\n            return self._failure("offline_edition", retryable=False)\n        if request_fingerprint(operation.payload) != operation.request_fingerprint:')
    replace(p, '        except V52NetworkError:\n            return self._failure("offline", retryable=True)', '        except V52NetworkError as err:\n            return self._failure(err.code, retryable=err.retryable,\n                                 retry_after_seconds=300 if err.code.startswith("tls_") else None)')
    replace(p, '        declared = error_payload.get("retryable")', '''        if code == "http_error":
            code = ({407: "proxy_auth_required", 429: "rate_limited"}.get(response.status)
                    or ("host_redirect" if 300 <= response.status < 400 else "host_unavailable" if response.status >= 500 else "http_error"))
        declared = error_payload.get("retryable")''')
    replace(p, '                except ValueError:\n                    return None', '''                except ValueError:
                    try:
                        deadline = parsedate_to_datetime(str(value))
                        if deadline.tzinfo is None:
                            deadline = deadline.replace(tzinfo=UTC)
                        return max(0, int((deadline - datetime.now(UTC)).total_seconds()))
                    except (ValueError, TypeError, OverflowError):
                        return None''')
    p = "source/services/v5_2_runtime.py"
    replace(p, "import random\n", "import random\nfrom services.build_edition import is_offline_edition\nfrom services.registration_errors import SUPPORT_CODES\n")
    replace(p, '        candidate = value.strip().lower()', '        allowed.update(SUPPORT_CODES)\n        candidate = value.strip().lower()')
    replace(p, '            client=client,', '            client=None if is_offline_edition() else client,')
    replace(p, '    def start(self) -> None:\n        self.processor.recover_after_restart()', '''    def start(self) -> None:
        state = self.state_repository.internal()
        if is_offline_edition() and state is not None and state["mode"] != "offline":
            self.set_mode("offline")
        self.processor.recover_after_restart()''')
    replace(p, '    def set_mode(self, mode: V52Mode) -> None:\n        with registration_state_lock:', '''    def set_mode(self, mode: V52Mode) -> None:
        if is_offline_edition() and mode != "offline":
            raise ValueError("Offline edition requires Offline License activation")
        with registration_state_lock:''')
    replace(p, '    def snapshot(self) -> dict[str, object]:\n        return self.state_repository.snapshot(now=self.clock())', '''    def snapshot(self) -> dict[str, object]:
        snapshot = self.state_repository.snapshot(now=self.clock())
        snapshot["request_in_progress"] = bool(self._future is not None and not self._future.done())
        return snapshot''')
    replace(p, '        result = self.client.send(operation, installation_token=request_token)', '''        if is_offline_edition():
            self.outbox.cancel_unsent(now=self.clock())
            return
        result = self.client.send(operation, installation_token=request_token)''')
    p = "source/services/v5_2_runtime_state.py"
    replace(p, 'from database import _open', 'from database import _open\nfrom services.registration_errors import SUPPORT_CODES')
    replace(p, '        return value if value in allowed else "needs_review"', '        return value if value in allowed | SUPPORT_CODES else "needs_review"')
    p = "source/services/peer_sync_authorization.py"
    replace(p, '                "schema": 1,', '                "schema": 2,\n                "disabled": False,')
    replace(p, '        path.unlink(missing_ok=True)', '''        previous = _read_state(path)
        _write_state(path, {"schema": 2, "disabled": True, "always_open": False,
                            "installation_id": previous.get("installation_id", ""),
                            "claims": {}, "used": True, "window_expires_at": 0.0})''')
    changes[p] = read(p) + PEER_DEFAULT
    p = "source/app.py"
    replace(p, 'from services.v5_2_client import V52ContractClient, V52RuntimeConfig', 'from services.build_edition import is_offline_edition\nfrom services.peer_sync_authorization import ensure_pairing_default, PeerSyncAuthorizationError\nfrom services.v5_2_client import V52ContractClient, V52RuntimeConfig')
    replace(p, '                    base_url="https://www.dmskm.com",\n                    environment="production",\n                )\n            ),', '                    base_url="https://www.dmskm.com",\n                    environment="production",\n                )\n            ) if not is_offline_edition() else None,')
    replace(p, '        if get_cfg("web_service_enabled", "1") != "0":\n            status = self.web_service.start()', '''        if get_cfg("web_service_enabled", "1") != "0":
            try:
                ensure_pairing_default(get_cfg("installation_id", ""),
                                       primary=get_cfg("desktop_role", "primary") != "secondary")
            except PeerSyncAuthorizationError:
                log.warning("Peer Sync authorization requires local administrator review")
            status = self.web_service.start()''')
    p = "source/v5_pages.py"
    replace(p, 'from services.v5_2_runtime_state import V52RuntimeStateRepository', 'from services.build_edition import is_offline_edition\nfrom services.registration_errors import error_message, safe_support_code\nfrom services.v5_2_runtime_state import V52RuntimeStateRepository')
    replace(p, 'OFFLINE_ACTIVATION_ENABLED = False', 'OFFLINE_ACTIVATION_ENABLED = is_offline_edition()')
    replace(p, '                if existing_registration_state is not None\n                else "online"', '                if existing_registration_state is not None\n                else ("offline" if is_offline_edition() else "online")')
    replace(p, '        self._start_online_registration()\n\n    def _registration_dialog_ui', '''        if is_offline_edition():
            self._open_offline_registration()
        else:
            self._start_online_registration()

    def _registration_dialog_ui''')
    replace(p, '    def _start_online_registration(self) -> None:\n        if self._registration_in_progress:', '''    def _start_online_registration(self) -> None:
        if is_offline_edition():
            self._open_offline_registration()
            return
        if self._registration_in_progress:''')
    replace(p, '        runtime = self._registration_service()\n        dialog = QDialog(self)\n        dialog.setWindowTitle(tr("ลงทะเบียน Offline", "Offline Registration"))', '        runtime = self._registration_service()\n        runtime.set_mode("offline")\n        dialog = QDialog(self)\n        dialog.setWindowTitle(tr("ลงทะเบียน Offline", "Offline Registration"))')
    method(p, "SetupWizardV5", "_poll_registration_result", POLL)
    method(p, "SetupWizardV5", "_show_registration_failure", FAILURE)
    for path in ("source/komi_version.py", "source/pyproject.toml", "source/uv.lock", "source/app.spec", "web/package.json", "web/package-lock.json", "packaging/windows/KOMI_Report_V5.iss", "docs/RELEASE_SUPPORT_AND_RECOVERY.md", "docs/CUSTOMER_RELEASE_NOTES.md", "docs/PILOT_RELEASE_CHECKLIST.md", "docs/RELEASE_RUNBOOK.md", "docs/CUSTOMER_INSTALL_GUIDE.md", "docs/CUSTOMER_GUIDE_V5_2.md", "source/tests/test_v5_2_version_authority.py", "source/tests/test_release_builder.py"):
        text = read(path).replace("5.2.10", "5.2.11").replace("5_2_10", "5_2_11")
        if path == "source/app.spec":
            text = text.replace('"50210"', '"50211"')
        changes[path] = text
    p = "source/tools/build_windows_rc.py"
    replace(p, '    customer_release: bool = False,\n) -> Path:\n    installer_name =', '    customer_release: bool = False,\n    edition: str = "normal",\n) -> Path:\n    if edition not in {"normal", "offline"}:\n        raise ReleaseContractError("Invalid installer edition")\n    installer_name =')
    replace(p, '    output_base = installer_name.removesuffix(".exe")', '    if edition == "offline":\n        installer_name = installer_name.replace("_Windows_x64_", "_Windows_x64_Offline_")\n    output_base = installer_name.removesuffix(".exe")')
    replace(p, '    parser.add_argument("--output", type=Path, default=RELEASE_ROOT)', '    parser.add_argument("--edition", choices=("normal", "offline"), default="normal")\n    parser.add_argument("--output", type=Path, default=RELEASE_ROOT)')
    replace(p, '    installer = compile_installer(\n', '''    edition_path = payload_root / "source" / "services" / "build_edition.py"
    edition_text = edition_path.read_text(encoding="utf-8")
    if edition_text.count('BUILD_EDITION = "normal"') != 1:
        raise ReleaseContractError("Unexpected staged build-edition authority")
    edition_path.write_text(edition_text.replace('BUILD_EDITION = "normal"', f'BUILD_EDITION = "{args.edition}"'), encoding="utf-8")
    installer = compile_installer(
''')
    replace(p, '        iscc=find_iscc(args.iscc),\n        customer_release=args.customer_release,', '        iscc=find_iscc(args.iscc),\n        customer_release=args.customer_release,\n        edition=args.edition,')
    replace(p, '    manifest["release_profile"] =', '    manifest["edition"] = args.edition\n    manifest["external_host_traffic"] = "disabled" if args.edition == "offline" else "registration-status-meter"\n    manifest["offline_activation"] = "host-signed-license-required"\n    manifest["release_profile"] =')
    changes["docs/V5_2_11_CANDIDATE.md"] = '''# KOMI Report 5.2.11 candidate

This is an unapproved candidate, not a Production GO. Main is unchanged.

- Normal: Online Registration, redacted transport diagnostics and late-result handling.
- Offline: no Registration/Status/Meter transport; a Host-signed Offline License remains required. No private/master key is bundled. Missing public verification keys are a delivery blocker, never a reason to bypass activation.
- Primary: persistent Peer Sync default after setup/startup, including one-time legacy migration. Explicit Off in this version survives restarts. Legacy Off was represented by an absent file and cannot be distinguished from never-configured; upgrading therefore applies the requested new default once.
- The LAN service is available while Desktop/tray is running, not after Exit, sleep or power-off. Existing explicit Web-service disable is respected.
- Always-open claims are not device authentication. Use a trusted LAN, scope the OS firewall to approved subnets/profiles, never expose the service to the Internet. Secrets/history are excluded from setup snapshots.
- Both installers share the existing per-user AppId/data path: alternatives for in-place install, not side-by-side editions. Back up before switching edition; switching to Offline requires offline activation.

Required validation: native Windows tests; fresh install and 5.2.10 upgrade; second-machine handoff; no Internet with LAN retained; license import/mismatch/expiry; no credentials in diagnostics; final installer SHA256 and signature evidence. No automatic publish or installation onto the runner's real user data.
'''


def main() -> None:
    plan()
    for path, text in changes.items():
        if path.endswith(".py"):
            ast.parse(text, filename=path)
    for path, text in changes.items():
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"changed": sorted(changes)}, indent=2))

if __name__ == "__main__":
    main()
