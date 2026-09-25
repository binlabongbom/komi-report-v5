"""Evidence checks for the same stable codes used in runtime diagnostics."""
from dataclasses import dataclass

from services.error_codes import ERROR_CODES
from services.support_diagnostics import CATALOG


CHECKS = {
    'attribution_rejected': 'หลักฐานมี request_mode=Admin, endpoint, AuthType/TrackType และ ResultInfo ที่ไม่ใช่ Ack; แยกจาก HTTP/TLS/รหัสผ่านและยอดผู้ใช้เป็นศูนย์ เพราะคำขอข้อมูลรายผู้ใช้ยังไม่สำเร็จ',
    'slot_baseline_missing': 'พบเครื่องที่เปิดใช้และ revision การตั้งค่าแล้ว แต่ไม่พบฐานของ Slot ใน slot_meter_heads; ข้อผิดพลาดเกิดก่อนติดต่อเครื่องพิมพ์ จึงไม่ใช่ผลตรวจ TLS หรือรหัสผ่าน',
    'dns_failed': 'หลักฐานต้องเป็น DNS/socket.gaierror; ดูชื่อ Host ในช่องปลายทางของรายงาน',
    'connection_refused': 'ดู endpoint และ OS_code ที่ระบุ connection refused; ขั้นตอนยังไม่ถึงการเข้าสู่ระบบ',
    'connection_timeout': 'ดูขั้นตอน ปลายทาง และเวลา timeout ในรายงาน; ผลนี้ระบุตำแหน่งคำขอที่ล้มเหลว แต่ไม่ยืนยัน TLS ปิดหรือรหัสผิด',
    'connection_reset': 'ดู OS_code ของ connection reset และเวลา/endpoint ของ session ที่ถูกตัด',
    'network_unreachable': 'ดู OS_code network/host unreachable และเครือข่ายของ Host ปลายทาง',
    'network_access_denied': 'OS_code 10013 หมายถึงนโยบายเครือข่ายของคอมนี้ปฏิเสธ socket',
    'tls_handshake': 'ดู TLS_reason และ request_mode ในหลักฐานว่าเป็น User/Public หรือ Admin; TLS ต้องเปิดใน PKI ทั้งสองโหมด',
    'tls_protocol': 'ดู TLS_reason ที่ระบุ protocol/version; ใช้ endpoint และ request_mode เพื่อชี้โหมด PKI ที่เกิดปัญหา',
    'tls_certificate': 'ดู verify_code และปลายทางในรายงาน เพื่อแยกการตรวจใบรับรองออกจากการตรวจรหัสผ่าน',
    'certificate_expired': 'verify_code ระบุหมดอายุ; เทียบเวลาที่แนบกับวันสิ้นสุดของใบรับรองปลายทาง',
    'certificate_not_yet_valid': 'verify_code ระบุยังไม่เริ่มใช้; เทียบเวลาที่แนบกับวันเริ่มต้นของใบรับรอง',
    'certificate_name': 'verify_code ระบุ hostname/IP mismatch; ชื่อ Host ที่ตั้งต้องอยู่ใน Subject Alternative Name ของใบรับรอง',
    'certificate_trust': 'verify_code ระบุ chain/CA ไม่เชื่อถือ; เป็นปัญหาใบรับรอง ไม่ใช่รหัสผ่าน',
    'certificate_pin': 'หลักฐานระบุ fingerprint ไม่ตรงค่าที่บันทึกสำหรับปลายทางนี้',
    'certificate_revoked': 'verify_code ระบุ revoked; ใบรับรองถูกผู้ออกเพิกถอนแล้ว',
    'certificate_period': 'Windows verify_code 0x800B0101 ระบุช่วงอายุใบรับรองไม่ครอบคลุมเวลาที่ใช้ตรวจ',
    'certificate_distrusted': 'Windows verify_code 0x800B0111 ระบุ explicit distrust',
    'certificate_revocation_unavailable': 'Windows verify_code 0x80092013 ระบุเข้าไม่ถึงบริการตรวจเพิกถอน CRL/OCSP',
    'host_tls_handshake': 'ขั้นตอน HOST และ endpoint ในรายงานระบุการเชื่อม Host; ใช้การตั้งค่า TLS ของ Host ไม่ใช่ PKI เครื่องพิมพ์',
    'credentials_missing': 'เงื่อนไขนี้เกิดก่อนส่งบัญชีเข้าสู่ระบบ: ไม่มีข้อมูล Administrator สำหรับ Slot ที่ระบุ',
    'auth_rejected': 'มี HTTP 401 หรือผลปฏิเสธการเข้าสู่ระบบจากเครื่อง; ผลนี้ยังไม่แยกรหัสผิด บัญชีล็อก หรือสิทธิ์ไม่พอ',
    'password_rejected': 'ต้องมีผลตอบกลับจากหน้าเข้าสู่ระบบที่ระบุรหัสผ่านไม่ถูกต้องอย่างชัดเจน',
    'admin_required': 'ผลตอบกลับระบุ PublicUser ไม่มีสิทธิ์อ่านส่วนที่ร้องขอ; ดู request_mode ในรายงาน',
    'factory_credentials_rejected': 'ผลนี้เป็นการปฏิเสธบัญชีเริ่มต้น; ไม่ใช่ผลทดสอบรหัส Administrator ที่องค์กรกำหนด',
    'session_busy': 'Web Connection ตอบว่ามี session อื่นใช้งานอยู่; ไม่ได้ระบุรหัสผ่านผิด',
    'access_denied': 'ดูขั้นตอนและ reason ในรายงานว่าสิทธิ์ของรายการใดถูกปฏิเสธ',
    'vault_unavailable': 'ดูบัญชี Windows/คอมและขั้นตอนอ่านหรือเขียน Credential Vault ในรายงาน',
    'snmp_failed': 'ดู Slot, endpoint และขั้นตอน SNMP; ไม่มีคำตอบเพียงอย่างเดียวยังแยก community ผิดกับแพ็กเก็ตถูกทิ้งไม่ได้',
    'snmp_meter_missing': 'มีคำตอบ SNMP แต่ไม่มี Total Meter ตาม Printer-MIB/OID ที่โปรไฟล์ใช้',
    'peer_authorization': 'หลักฐานระบุสิทธิ์เชื่อมสมาชิก LAN ใช้ไม่ได้; ดูสมาชิกต้นทางและขั้นตอนที่แนบ',
    'peer_recovery': 'หลักฐานระบุตัวตน/กุญแจสมาชิกเดิมใช้ไม่ได้ จึงต้องใช้ขั้นตอนกู้คืนสมาชิก',
    'shared_read_expired': 'เวลาของสิทธิ์อ่านร่วมหมดลงก่อนส่งผล; ไม่ใช่ timeout ติดต่อเครื่องพิมพ์',
    'reader_unavailable': 'ตั้งค่า > การทำงานอัตโนมัติ > สมาชิกคอมพิวเตอร์: ดูบทบาทล่าสุดประกอบขอบเขตการอ่านในรายงาน',
    'http_forbidden': 'HTTP 403 ยืนยันว่าปลายทางรับคำขอแต่ไม่อนุญาต endpoint นี้',
    'endpoint_missing': 'HTTP 404 และ URL ในรายงานระบุ path ที่ปลายทางหาไม่พบ',
    'rate_limited': 'HTTP 429 ยืนยันการจำกัดคำขอ; ใช้เวลา Retry-After หากปลายทางส่งมา',
    'server_error': 'HTTP 5xx ระบุข้อผิดพลาดฝั่งบริการ; ใช้ status/endpoint/เวลาในรายงานค้นเหตุการณ์ฝั่งบริการ',
    'proxy_auth': 'HTTP 407 เป็นคำตอบจาก Proxy; คำขอยังไม่ถึงบริการปลายทาง',
    'response_invalid': 'ดู exception JSON/XML และ endpoint ของคำตอบที่ตัวแปลงข้อมูลอ่านไม่ได้',
    'input_invalid': 'ดู reason และชื่อขั้นตอนในรายละเอียดที่คัดลอก โปรแกรมแนบค่าหรือเงื่อนไขที่ไม่ผ่านไว้',
    'report_empty': 'ดูช่วงวันที่และรายการที่เลือกใน Export Excel; โปรแกรมไม่พบแถวข้อมูลของการเลือกครั้งนี้',
    'file_permission': 'ดู path และ OS_code/PermissionError; หากไม่มี sharing violation ยังสรุปไม่ได้ว่าไฟล์เปิดค้าง',
    'file_locked': 'Windows OS_code 32 หรือ 33 ยืนยัน sharing/lock violation ของ path ในรายงาน',
    'disk_full': 'OS_code ENOSPC หรือ 112 ระบุดิสก์เต็ม; path ระบุไดรฟ์ที่ต้องเพิ่มพื้นที่',
    'file_missing': 'FileNotFoundError และ path ในรายงานระบุไฟล์หรือโฟลเดอร์ที่หาไม่พบ',
    'database_locked': 'SQLite_code BUSY/LOCKED ระบุฐานข้อมูลกำลังถูกใช้; ใช้ขั้นตอนและเวลาในรายงานระบุงานที่ชนกัน',
    'database_invalid': 'SQLite_code CORRUPT/NOTADB ระบุไฟล์เสียหายหรือรูปแบบไม่ใช่ SQLite',
    'dependency_missing': 'ดู module และ exception ImportError/ModuleNotFoundError ในหลักฐานเพื่อระบุส่วนประกอบที่ขาด',
    'operation_failed': 'รายละเอียดที่คัดลอกมี exception, location, ขั้นตอน และข้อความต้นทางสำหรับระบุจุดแก้ในโค้ด; รหัสนี้ไม่ยืนยันสาเหตุเฉพาะ',
    'ui_warning': 'รายละเอียดที่คัดลอกมีชื่อหน้าต่าง ข้อความเงื่อนไข คำแนะนำ และรหัสอ้างอิงคำเตือน; เป็นเงื่อนไขหน้าจอที่ไม่มี exception',
}


@dataclass(frozen=True)
class ErrorReference:
    code: str
    problem: str
    check: str
    action: str


def error_references():
    return tuple(ErrorReference(public, CATALOG[key][0] + '\n' + CATALOG[key][1],
                                CHECKS[key], CATALOG[key][2])
                 for key, public in sorted(ERROR_CODES.items(), key=lambda pair: pair[1]))
