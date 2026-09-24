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
    "offline": ("การเชื่อมต่อ Host ไม่สำเร็จและยังไม่มีรหัสระบบที่แยกสาเหตุได้ · จุดล้มเหลวคือการเชื่อมต่อ API ไม่ใช่รหัสเครื่องพิมพ์", "The Host API connection failed without a classified system error; this is not a printer password result."),
    "dns_error": ("DNS แปลงชื่อ Host ไม่สำเร็จ · แก้ DNS record หรือ DNS resolver ที่คอมนี้ใช้ให้รองรับชื่อ Host ที่กำหนด", "DNS could not resolve the Host. Repair its DNS record or the resolver configured on this computer."),
    "connection_timeout": ("การเชื่อมต่อ Host หมดเวลา ลองอีกครั้งเมื่อเครือข่ายพร้อม", "Host connection timed out. Retry when the network is available."),
    "connection_refused": ("ปลายทางปฏิเสธ TCP ก่อนถึง TLS · เปิดบริการ API บนพอร์ตที่ระบุและอนุญาตพอร์ตนั้นใน Firewall ปลายทาง", "TCP was refused before TLS. Enable the API listener and permit its configured port in the destination firewall."),
    "connection_reset": ("การเชื่อมต่อถูกตัดระหว่างทาง กรุณาลองอีกครั้ง", "The connection was reset. Please retry."),
    "network_unreachable": ("ระบบปฏิบัติการไม่มีเส้นทางไป Host · ตั้ง route, gateway หรือ VPN ของคอมนี้ให้เข้าถึงเครือข่าย Host", "The OS has no route to the Host. Restore the route, gateway or VPN for its network."),
    "tls_certificate_error": ("ยืนยัน Certificate ของ Host ไม่สำเร็จ ตรวจสอบเวลาเครื่องและ CA กับผู้ดูแล ห้ามปิดการตรวจ Certificate", "Host certificate verification failed. Check the system clock and CA with the administrator; do not disable verification."),
    "tls_error": ("TLS ระหว่างคอมกับ Host ล้มเหลวก่อนส่ง API · จุดแก้คือ TLS listener ของ Host หรือ Proxy ไม่ใช่ PKI ของเครื่องพิมพ์", "TLS failed before the Host API request. Repair the Host or proxy TLS listener; printer PKI is unrelated."),
    "response_too_large": ("คำตอบ API เกินขนาดที่แอพยอมรับ · แก้ API ให้คืน payload ตามขนาดในสัญญาการเชื่อมต่อ ไม่เพิ่มขีดจำกัดเพื่อรับข้อมูลที่ไม่ตรงสัญญา", "The API response exceeds the contract size limit. Correct the API payload rather than bypassing the limit."),
    "registration_pending": ("ยังไม่ได้รับผลการลงทะเบียน กำลังรอผล คุณยกเลิกหน้าต่างได้โดยไม่ลบการตั้งค่า", "Registration is still pending. You may close this dialog without deleting the saved setup."),
    "proxy_auth_required": ("Proxy ตอบ HTTP 407 · ตั้งบัญชีหรือสิทธิ์ Proxy ของ Windows ให้ผ่านบริการ API ไม่ใช่แก้รหัสเครื่องพิมพ์", "Proxy HTTP 407: configure this Windows account's proxy authorization, not the printer password."),
    "host_redirect": ("Host ส่ง Redirect แทน API · แก้ route หรือ reverse proxy ของ endpoint นี้ให้คืน API โดยตรง ไม่เปลี่ยนไปหน้า Login", "The endpoint redirected instead of returning the API. Correct its route or reverse proxy so it does not redirect to a login page."),
    "rate_limited": ("Host จำกัดจำนวนคำขอ ระบบจะรอตามเวลาที่ Host กำหนด", "The Host is rate limiting requests. The app will respect its retry delay."),
    "host_unavailable": ("Host ยังไม่พร้อมให้บริการ ระบบจะลองใหม่ตามกำหนด", "The Host is temporarily unavailable. A retry is scheduled."),
    "offline_edition": ("ตัวติดตั้ง Offline ไม่เชื่อมต่อ Host กรุณาใช้ Offline License", "The Offline edition cannot contact the Host. Use an Offline License."),
    "client_not_configured": ("ยังไม่ได้ตั้งค่าการเชื่อมต่อ Host", "The Host connection is not configured."),
    "validation_error": ("Host ปฏิเสธข้อมูลลงทะเบียน · จุดแก้คือช่องข้อมูลลงทะเบียนและ schema API ตามผล validation ที่ Host ส่งกลับ ไม่ใช่เครือข่ายหรือ TLS", "The Host rejected registration data. Correct the registration fields or API schema using the validation response; this is not a network or TLS failure."),
    "contract_invalid": ("คำตอบ Host ไม่ตรงสัญญา API · ปรับเวอร์ชัน Desktop และ Host API ให้ใช้ schema เดียวกัน ไม่บันทึกคำตอบที่ไม่ผ่าน validation", "The Host response violates the API contract. Align Desktop and Host API schemas; invalid responses are not saved."),
    "vault_unavailable": ("ไม่สามารถเก็บข้อมูลลงทะเบียนอย่างปลอดภัยได้ ตรวจสอบ OS credential vault", "Secure registration storage is unavailable. Check the OS credential vault."),
}


def error_message(code: str) -> tuple[str, str]:
    return MESSAGES.get(code, ("ลงทะเบียนไม่สำเร็จ · แอพยังไม่มีตัวจำแนกสำหรับผล API นี้ จึงไม่ระบุว่าเกิดจาก TLS หรือรหัสผ่าน", "Registration failed with an unclassified API result. No TLS or password cause has been established."))


def safe_support_code(code: str) -> str:
    known = SUPPORT_CODES | frozenset(MESSAGES) | {"registration_conflict", "registration_required", "installation_token_unavailable", "request_fingerprint_mismatch", "http_error", "needs_review", "retrying"}
    return code if code in known else "needs_review"
