"""Safe registration diagnostics shared by transport, state and UI.

Never classify by arbitrary exception text or expose raw errors/customer data.
"""
from __future__ import annotations
import errno
import socket
import ssl
from urllib.error import URLError

NETWORK_CODES = frozenset({"offline", "dns_error", "connection_timeout", "connection_refused", "connection_reset", "network_unreachable", "tls_certificate_error", "tls_error", "response_too_large"})
SUPPORT_CODES = NETWORK_CODES | frozenset({"registration_pending", "proxy_auth_required", "host_redirect", "rate_limited", "host_unavailable", "offline_edition"})


def tls_verification_detail(error: BaseException) -> str:
    """Only numeric verifier codes and fixed labels; never raw exception text."""
    seen: set[int] = set()
    while isinstance(error, URLError) and isinstance(error.reason, BaseException):
        if id(error) in seen:
            return ""
        seen.add(id(error))
        error = error.reason
    if not isinstance(error, ssl.SSLCertVerificationError):
        return ""
    number = getattr(error, "verify_code", None)
    if type(number) is not int:
        return ""
    number &= 0xFFFFFFFF
    labels = {
        9: "certificate_not_yet_valid", 10: "certificate_expired",
        18: "untrusted_self_signed", 19: "untrusted_chain",
        20: "issuer_not_found", 21: "incomplete_chain", 23: "certificate_revoked",
        62: "hostname_mismatch", 64: "hostname_mismatch",
        0x800B0101: "certificate_outside_validity_period",
        0x800B0109: "untrusted_root", 0x800B010A: "incomplete_chain",
        0x800B010C: "certificate_revoked", 0x800B010F: "hostname_mismatch",
        0x800B0111: "explicitly_distrusted", 0x80092013: "revocation_check_offline",
    }
    return f" | Verify code: {number} (0x{number:X}) | {labels.get(number, 'certificate_validation_failed')}"


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
