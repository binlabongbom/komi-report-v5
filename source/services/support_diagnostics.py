"""Evidence-based, copyable diagnostics. Never probe or retry a login here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import errno
import hashlib
import json
import re
import socket
import sqlite3
import ssl
import traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit

from komi_version import APP_VERSION
from services.error_codes import ERROR_CODES, CODE_KEYS


# Cause states what the observed failure proves; action names the repair location.
CATALOG = {
    'report_empty': ('ไม่มีข้อมูลสำหรับรายงานที่เลือก', 'การค้นข้อมูลตามช่วงวันที่และประเภทรายงานที่เลือกได้ผลลัพธ์ว่าง จึงยังไม่ได้สร้างไฟล์ Excel', 'Reports > Export Excel: เลือกช่วงวันที่ที่มีข้อมูลและประเภทรายงานที่ต้องการ; รายงานผู้ใช้ต้องมีข้อมูลผู้ใช้ ส่วน Legacy ต้องมีข้อมูลตัวนับในช่วงนั้น'),
    'ui_warning': ('คำเตือนตามเงื่อนไขของหน้าจอ', 'หน้าจอแจ้งเงื่อนไขที่ยังไม่ผ่าน โดยไม่ได้แนบ exception; รหัสนี้ไม่ยืนยันปัญหาเครือข่ายหรือรหัสผ่าน', 'ทำตามข้อความเงื่อนไขและคำแนะนำในหน้าต่าง; รายละเอียดที่คัดลอกมีชื่อหน้าต่าง ข้อความ และรหัสอ้างอิงของคำเตือน'),
    'certificate_revoked': ('ใบรับรองถูกเพิกถอน', 'ตัวตรวจใบรับรองรายงานว่าใบรับรองถูกเพิกถอน', 'เปลี่ยนใบรับรองที่ปลายทางเป็นใบที่ยังใช้ได้และติดตั้ง chain ให้ครบ; ไม่ปิดการตรวจใบรับรอง'),
    'certificate_period': ('เวลาอยู่นอกช่วงที่ใบรับรองใช้ได้', 'ตัวตรวจใบรับรอง Windows รายงานว่าเวลาอยู่นอกช่วงอายุใบรับรอง; รหัสนี้ไม่ได้แยกหมดอายุกับยังไม่เริ่มใช้', 'แก้เวลา Windows ให้ตรงเวลาจริง และให้ปลายทางใช้ใบรับรองที่มีช่วงอายุครอบคลุมเวลาปัจจุบัน'),
    'certificate_distrusted': ('ใบรับรองถูกกำหนดให้ไม่เชื่อถือ', 'Windows รายงาน explicit distrust ของใบรับรอง', 'ให้ผู้ดูแลใบรับรองเปลี่ยนใบรับรองหรือ chain ที่ปลายทางให้ผ่านนโยบายความเชื่อถือขององค์กร'),
    'certificate_revocation_unavailable': ('เข้าถึงบริการตรวจเพิกถอนใบรับรองไม่ได้', 'Windows รายงานว่าบริการตรวจเพิกถอนใบรับรองเข้าไม่ถึง', 'อนุญาตเส้นทางจากคอมนี้ไปยังบริการ CRL/OCSP ของผู้ออกใบรับรองผ่าน Firewall/Proxy; ไม่ปิดการตรวจเพิกถอน'),
    'network_access_denied': ('ระบบปฏิเสธสิทธิ์ใช้เครือข่าย', 'Windows socket รายงาน WSAEACCES; ไม่ใช่สิทธิ์ไฟล์หรือรหัสผ่านเครื่องพิมพ์', 'อนุญาตการเชื่อมต่อของ KOMI ไปยังปลายทางและพอร์ตในรายงานในนโยบาย Firewall/Endpoint Security ของคอมนี้'),
    'access_denied': ('รายการนี้ไม่ได้รับสิทธิ์', 'ระบบปฏิเสธสิทธิ์การทำรายการ; ไม่ใช่หลักฐานว่ารหัสผ่านเครื่องพิมพ์ผิดหรือไฟล์ถูกล็อก', 'แก้สิทธิ์ของบัญชีหรือสมาชิกที่ทำรายการตามขั้นตอนและข้อความต้นทางในรายงาน แล้วดำเนินการใหม่'),
    'input_invalid': ('ข้อมูลไม่ผ่านเงื่อนไขของรายการ', 'ตัวตรวจข้อมูลปฏิเสธค่าที่ส่งเข้ามา โดยมีเหตุผลในข้อความต้นทาง', 'แก้ช่องข้อมูลหรือไฟล์นำเข้าที่ระบุในข้อความต้นทางของหน้าต่างนี้ แล้วบันทึกใหม่'),
    'peer_authorization': ('สิทธิ์เชื่อมสมาชิก LAN ใช้ไม่ได้', 'สิทธิ์ขอเข้ากลุ่ม/เชื่อมสมาชิกไม่มี หมดอายุ หรือไม่ผ่านการยืนยัน; ไม่ใช่รหัสเครื่องพิมพ์', 'KOMI > ตั้งค่า > การตั้งค่าเครือข่าย > รับสมาชิกและใช้ข้อมูลร่วมกัน: เปิดรับสมาชิกที่ต้นทาง แล้วให้เครื่องปลายทางขอสิทธิ์เข้ากลุ่มใหม่'),
    'peer_recovery': ('ตัวตนสมาชิกต้องกู้คืน', 'ระบบหยุดเชื่อมกลุ่มเพราะตัวตนสมาชิกหรือกุญแจยืนยันใช้ไม่ได้ ไม่สร้างตัวตนทับของเดิม', 'KOMI > ตั้งค่า > การตั้งค่าเครือข่าย > ค้นหาและเชื่อมต่อสมาชิกเดิมอีกครั้ง: ดำเนินขั้นตอนกู้คืนสมาชิกตามสิทธิ์ของกลุ่มเดิม'),
    'shared_read_expired': ('สิทธิ์อ่านร่วมหมดเวลา', 'ช่วงเวลาที่ได้รับอนุญาตให้อ่านร่วมสิ้นสุดลง จึงไม่รับผลรอบนี้; ไม่ใช่ timeout ของเครื่องพิมพ์', 'ให้ระบบขอสิทธิ์อ่านร่วมรอบใหม่จากผู้ประสานก่อนอ่านอีกครั้ง; ไม่เพิ่มสิทธิ์หรือส่งผลของรอบที่หมดเวลา'),
    'reader_unavailable': ('ไม่มีผู้อ่านที่ได้รับสิทธิ์ในขณะนี้', 'ระบบเลือกผู้อ่านไม่ได้หรือผู้ประสานยังไม่พร้อมสำหรับขอบเขตการอ่านนี้', 'KOMI > ตั้งค่า > การทำงานอัตโนมัติ > สมาชิกคอมพิวเตอร์: เปิดการอ่านบนคอมที่มีสิทธิ์ในกลุ่ม แล้วให้ระบบเลือกผู้อ่านรอบใหม่'),
    'vault_unavailable': ('เก็บหรืออ่านกุญแจจากระบบไม่ได้', 'Credential Vault ของระบบปฏิบัติการไม่สามารถเก็บหรือคืนข้อมูลที่ต้องใช้', 'ลงชื่อเข้า Windows ด้วยบัญชีที่ติดตั้ง/ลงทะเบียน KOMI และกู้คืน Credential Vault ของบัญชีนั้น; ไม่คัดลอกรหัสผ่านลงไฟล์ข้อความ'),
    'admin_required': ('ปลายทางต้องใช้สิทธิ์ Administrator', 'Web Connection ไม่อนุญาตอ่านในโหมด PublicUser; ยังไม่ได้เป็นผลว่ารหัสผ่านผิด', 'KOMI > อุปกรณ์ > ตั้งค่าเครื่องนี้ > Username / Password: กำหนดบัญชี Administrator ที่ได้รับสิทธิ์อ่านมิเตอร์'),
    'factory_credentials_rejected': ('รหัสเริ่มต้นใช้เข้าสู่เครื่องนี้ไม่ได้', 'การลองบัญชีเริ่มต้นสาธารณะไม่สำเร็จ; ไม่ได้ยืนยันว่ารหัสที่ลูกค้ากำหนดไว้ผิด', 'KOMI > อุปกรณ์ > ตั้งค่าเครื่องนี้: ใส่บัญชี Administrator ที่องค์กรกำหนดแทนรหัสเริ่มต้น'),
    'snmp_failed': ('อ่าน SNMP ไม่สำเร็จ', 'SNMP ไม่ได้คืนข้อมูลที่การอ่านครั้งนี้ต้องใช้; ยังแยก community ผิดกับแพ็กเก็ตถูกทิ้งไม่ได้จากผลนี้', 'ที่เครื่องพิมพ์ > Network > SNMP: เปิด SNMP และกำหนด community/สิทธิ์อ่านให้ตรงกับ KOMI; เส้นทางเครือข่ายต้องอนุญาต UDP พอร์ต SNMP ที่ตั้งไว้'),
    'snmp_meter_missing': ('SNMP ไม่พบ Total Meter', 'คำตอบ Printer-MIB ไม่มี Total Meter ที่โปรไฟล์นี้อ่านได้', 'KOMI > อุปกรณ์ > โปรไฟล์เครื่อง: ใช้โปรไฟล์ที่ตรงรุ่นและ OID ของเครื่อง; ใช้ข้อมูล Web Meter ที่ยืนยันแล้วเพื่อเทียบ mapping'),
    'dependency_missing': ('ส่วนประกอบโปรแกรมไม่ครบ', 'ไม่พบไลบรารีที่ต้องใช้ใน runtime', 'ติดตั้ง KOMI จากแพ็กเกจที่ครบถ้วนทับเวอร์ชันนี้โดยคงฐานข้อมูล; จุดแก้อยู่ที่แพ็กเกจโปรแกรม ไม่ใช่การตั้งค่าเครื่องพิมพ์'),
    'host_tls_handshake': ('เชื่อมต่อ TLS กับ Host ไม่สำเร็จ', 'TLS ระหว่างแอพกับ Host ล้มเหลวก่อนส่ง API; ไม่เกี่ยวกับ PKI หรือรหัสผ่านเครื่องพิมพ์', 'แก้ TLS listener ของ Host หรือ Proxy ที่คั่นการเชื่อมต่อ API ให้รองรับ TLS ของระบบ Windows; ใช้ endpoint HTTPS ตามสัญญา API'),
    'credentials_missing': ('ยังไม่มีข้อมูลเข้าสู่ระบบ', 'การอ่านส่วน Administrator ต้องใช้ข้อมูลเข้าสู่ระบบ แต่ยังไม่ได้กำหนด', 'KOMI > อุปกรณ์ > ตั้งค่าเครื่องนี้ > Username / Password: ใส่บัญชี Administrator ของเครื่องพิมพ์'),
    'auth_rejected': ('เครื่องปฏิเสธการเข้าสู่ระบบ', 'เครื่องตอบกลับว่าเข้าสู่ระบบไม่ได้ ไม่ใช่ข้อผิดพลาดการเจรจา TLS; ผลนี้ยังไม่แยกรหัสผิด บัญชีถูกล็อก หรือสิทธิ์ไม่พอ', 'KOMI > อุปกรณ์ > ตั้งค่าเครื่องนี้ > Username / Password: ใช้บัญชี Administrator ที่ได้รับสิทธิ์; หากบัญชีถูกล็อก ให้ผู้ดูแลปลดล็อกที่ระบบบัญชีของเครื่องก่อนลองใหม่'),
    'password_rejected': ('เครื่องตอบว่ารหัสผ่านไม่ถูกต้อง', 'หน้าเข้าสู่ระบบของเครื่องส่งผลปฏิเสธรหัสผ่านอย่างชัดเจน', 'KOMI > อุปกรณ์ > ตั้งค่าเครื่องนี้ > Password: แก้รหัสให้ตรงกับบัญชี Administrator ของเครื่อง แล้วทดสอบหนึ่งครั้ง'),
    'session_busy': ('มีผู้ใช้ Web Connection อยู่แล้ว', 'เครื่องแจ้งว่ามี session อื่นใช้งานอยู่ จึงยังเปิด session อ่านมิเตอร์ไม่ได้', 'Web Connection ของเครื่องพิมพ์ > session ที่เปิดค้าง > Logout แล้วกดอ่านใหม่ใน KOMI'),
    'tls_handshake': ('เจรจา TLS ไม่สำเร็จ', 'การเชื่อมต่อ HTTPS ล้มเหลวในชั้น TLS; ยังไม่ถึงการยืนยันรหัสผ่าน และผลนี้ไม่ยืนยันว่า PKI ปิดอยู่', 'ที่เครื่องพิมพ์ > PKI: การตั้งค่าที่ต้องใช้คือเปิด TLS ทั้ง User mode และ Admin mode; ใช้ TLS ที่ firmware และโปรไฟล์รุ่นรองรับ โดยไม่ปิดการตรวจใบรับรอง'),
    'tls_protocol': ('เวอร์ชัน TLS ไม่เข้ากัน', 'TLS ส่งข้อผิดพลาดด้าน protocol/version ระหว่างการจับมือ ไม่ใช่ผลตรวจรหัสผ่าน', 'ที่เครื่องพิมพ์ > PKI > TLS (User mode และ Admin mode): ใช้เวอร์ชัน TLS ที่โปรไฟล์รุ่นรองรับ; อัปเดต firmware หากไม่มีเวอร์ชันที่รองรับร่วมกัน'),
    'tls_certificate': ('ยืนยันใบรับรองไม่สำเร็จ', 'ตัวตรวจใบรับรองปฏิเสธ certificate ของปลายทาง ก่อนเข้าสู่ระบบ', 'แก้ certificate chain และ trust ของปลายทางตาม Verify code ในหลักฐาน; สำหรับเครื่องพิมพ์ใช้ใบรับรองที่เชื่อถือได้หรือ fingerprint ที่ยืนยันโดยผู้ดูแล ห้ามข้ามการตรวจ certificate'),
    'certificate_expired': ('ใบรับรองหมดอายุ', 'ตัวตรวจใบรับรองรายงาน certificate_expired', 'ต่ออายุใบรับรองที่ปลายทางและติดตั้ง chain ให้ครบ แล้วเชื่อมต่อใหม่'),
    'certificate_not_yet_valid': ('ใบรับรองยังไม่ถึงวันเริ่มใช้', 'ตัวตรวจใบรับรองรายงาน certificate_not_yet_valid', 'ซิงก์วันเวลาของคอมจากแหล่งเวลาขององค์กร; หากเวลาถูกต้อง ให้ปลายทางใช้ใบรับรองที่อยู่ในช่วงวันใช้งาน'),
    'certificate_name': ('ชื่อปลายทางไม่ตรงใบรับรอง', 'ตัวตรวจใบรับรองรายงาน hostname/IP mismatch', 'ใช้ชื่อ DNS/IP ที่ระบุใน SAN ของ certificate หรือออก certificate ใหม่ให้ตรงกับปลายทางที่ตั้งใน KOMI'),
    'certificate_trust': ('ไม่เชื่อถือผู้ออกใบรับรอง', 'ตัวตรวจใบรับรองไม่สามารถสร้าง chain ไปยัง CA ที่เชื่อถือได้', 'ติดตั้ง intermediate certificate ให้ครบที่ปลายทาง และเพิ่ม CA ขององค์กรใน trust store ที่แอพใช้; ไม่ปิด certificate verification'),
    'certificate_pin': ('ใบรับรองไม่ตรง fingerprint ที่บันทึก', 'certificate ที่ได้รับไม่ตรงค่าที่เคยผูกไว้ จึงหยุดการเชื่อมต่อ', 'ยืนยันใบรับรองใหม่กับผู้ดูแลเครื่องก่อนอัปเดต fingerprint ของเครื่องนี้ใน KOMI; ไม่ยอมรับใบรับรองใหม่อัตโนมัติ'),
    'dns_failed': ('แปลงชื่อปลายทางไม่ได้', 'DNS resolver คืนข้อผิดพลาดก่อนเริ่มเชื่อมต่อปลายทาง', 'แก้ชื่อ Host ในการตั้งค่าปลายทาง หรือ DNS record/ตัว resolver ของเครือข่ายที่ใช้ชื่อดังกล่าว'),
    'connection_refused': ('ปลายทางปฏิเสธการเชื่อมต่อ', 'ระบบเครือข่ายส่ง connection refused กลับมา ยังไม่ถึง TLS หรือการตรวจรหัสผ่าน', 'ที่ปลายทางให้เปิด service บนพอร์ตที่ระบุในรายงาน และกำหนด Firewall ให้รับพอร์ตนั้น; ถ้าตั้งพอร์ตผิดให้แก้ endpoint ใน KOMI'),
    'connection_timeout': ('ไม่ได้รับคำตอบภายในเวลาที่กำหนด', 'คำขอหมดเวลา; timeout อย่างเดียวแยกเครื่องปิด สายหลุด หรือ Firewall ทิ้งแพ็กเก็ตไม่ได้ จึงไม่ระบุว่ารหัสผิด', 'ตำแหน่งแก้คือเส้นทางจากคอมผู้อ่านไปยัง Host/พอร์ตในรายงาน: service ปลายทางและกฎ Firewall/เครือข่ายต้องยอมให้คำขอนี้ผ่าน'),
    'network_unreachable': ('ระบบไม่มีเส้นทางไปปลายทาง', 'ระบบปฏิบัติการรายงาน network/host unreachable ก่อนเข้าสู่ระบบ', 'ตั้ง route, gateway หรือ VPN บนคอมผู้อ่านให้เข้าถึงเครือข่ายปลายทางที่ระบุในรายงาน'),
    'connection_reset': ('การเชื่อมต่อถูกตัด', 'socket รายงาน connection reset; ยังระบุไม่ได้ว่าปลายทางหรืออุปกรณ์ระหว่างทางเป็นผู้ตัด', 'ตำแหน่งแก้คือ service ปลายทางหรืออุปกรณ์เครือข่ายที่ตัด session นี้ โดยใช้เวลาและ endpoint ในรายงานเทียบเหตุการณ์'),
    'http_forbidden': ('ปลายทางไม่อนุญาตคำขอนี้', 'ปลายทางตอบ HTTP 403; ไม่ใช่หลักฐานว่ารหัสผ่านผิด', 'กำหนดสิทธิ์บัญชีหรือ access policy ที่ปลายทางให้อนุญาต endpoint และวิธีเรียกในรายงาน'),
    'endpoint_missing': ('ไม่พบ endpoint ที่ร้องขอ', 'ปลายทางตอบ HTTP 404; ยังไม่ยืนยันว่า firmware ไม่รองรับ', 'แก้ URL หรือโปรไฟล์รุ่นใน KOMI ให้ตรง endpoint ของเครื่อง; ฝั่ง Host ต้องมี route API ตามเวอร์ชันที่แอพใช้'),
    'rate_limited': ('ปลายทางจำกัดจำนวนคำขอ', 'ปลายทางตอบ HTTP 429', 'ลดรอบเรียกปลายทางและให้ระบบรอตาม Retry-After; ไม่กดทดสอบซ้ำระหว่างรอ'),
    'server_error': ('บริการปลายทางเกิดข้อผิดพลาด', 'ปลายทางตอบ HTTP 5xx หลังรับคำขอแล้ว', 'แก้ service ของ endpoint ที่ระบุในรายงาน โดยใช้ HTTP status และเวลาเป็นจุดค้นเหตุการณ์ฝั่งบริการ'),
    'proxy_auth': ('Proxy ต้องการการยืนยันตัวตน', 'Proxy ตอบ HTTP 407 ก่อนคำขอถึงบริการ', 'ตั้งบัญชี/สิทธิ์ Proxy ของคอมผู้อ่านในระบบ Proxy ขององค์กร; ไม่แก้รหัส Administrator ของเครื่องพิมพ์'),
    'response_invalid': ('รูปแบบคำตอบไม่ตรงที่แอพอ่านได้', 'ตัวแปลงข้อมูลไม่สามารถอ่าน JSON/XML จากคำตอบได้', 'แก้โปรไฟล์การอ่านหรือ API ให้ตรงรุ่น/เวอร์ชันปลายทาง; ไม่เปลี่ยนรหัสผ่านเพียงเพราะแปลงข้อมูลไม่ได้'),
    'file_permission': ('ระบบไม่อนุญาตให้เข้าถึงไฟล์', 'ระบบปฏิบัติการปฏิเสธสิทธิ์ไฟล์; PermissionError อย่างเดียวไม่ยืนยันว่า Excel เปิดไฟล์ค้าง', 'ใช้โฟลเดอร์ที่บัญชี Windows นี้มีสิทธิ์เขียน; ถ้ามีโปรแกรมเปิดไฟล์ปลายทางอยู่ให้ปิดไฟล์นั้นก่อนบันทึกซ้ำ'),
    'file_locked': ('ไฟล์ถูกใช้งานโดยโปรแกรมอื่น', 'Windows รายงาน sharing/lock violation', 'ปิดไฟล์ปลายทางใน Excel หรือโปรแกรมที่ใช้อยู่ แล้วส่งออกซ้ำ หรือบันทึกเป็นชื่อใหม่'),
    'disk_full': ('พื้นที่จัดเก็บไม่พอ', 'ระบบปฏิบัติการรายงานพื้นที่ดิสก์เต็ม', 'เพิ่มพื้นที่ว่างบนไดรฟ์ปลายทาง หรือเลือกไดรฟ์บันทึกที่มีพื้นที่พอ'),
    'file_missing': ('ไม่พบไฟล์หรือโฟลเดอร์', 'ระบบปฏิบัติการรายงานว่า path ไม่มีอยู่', 'เลือกไฟล์/โฟลเดอร์ที่มีอยู่จริงในหน้าที่ทำรายการ แล้วดำเนินการอีกครั้ง'),
    'database_locked': ('ฐานข้อมูลติดล็อก', 'SQLite รายงาน BUSY/LOCKED ขณะทำรายการ', 'หยุดงานที่เขียนฐานข้อมูลไฟล์เดียวกันพร้อมกัน แล้วลองรายการอีกครั้ง; ไม่ลบไฟล์ฐานข้อมูลหรือไฟล์ WAL'),
    'database_invalid': ('ฐานข้อมูลเสียหายหรือไม่ใช่ SQLite', 'SQLite รายงาน CORRUPT/NOTADB', 'ตั้งค่า > ขั้นสูง > Database: ใช้สำเนาสำรองที่ผ่านการตรวจสอบ หยุดเขียนทับไฟล์ต้นฉบับเพื่อเก็บหลักฐาน'),
    'operation_failed': ('การทำรายการไม่สำเร็จ', 'ข้อผิดพลาดนี้ยังไม่มีตัวจำแนกสาเหตุเฉพาะ; ไม่สรุปว่าเกิดจาก TLS หรือรหัสผ่าน', 'จุดแก้คือขั้นตอนและชนิด exception ที่แนบในรายงาน; ต้องเพิ่มตัวจำแนกในแอพสำหรับกรณีนี้ ไม่ให้ผู้ใช้เปลี่ยนการตั้งค่าโดยเดา'),
}


def safe_text(value: object) -> str:
    text = str(value)
    def clean_url(match):
        try:
            p = urlsplit(match.group())
            host = p.hostname or ''
            if ':' in host:
                host = f'[{host}]'
            return urlunsplit((p.scheme, host + (f':{p.port}' if p.port else ''), p.path, '', ''))
        except ValueError:
            return '[URL]'
    text = re.sub(r'https?://[^\s<>]+', clean_url, text)
    text = re.sub(r'(?im)(authorization|cookie|set-cookie)\s*[:=][^\r\n]*', r'\1: [REDACTED]', text)
    text = re.sub(r'''(?ix)(password|passwd|token|secret|community|รหัสผ่าน)\s*["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s;,]+)''', r'\1=[REDACTED]', text)
    return text[:12000]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    evidence: tuple[str, ...] = ()

    @property
    def error_code(self):
        return ERROR_CODES[self.code]

    @property
    def summary(self):
        return CATALOG[self.code][0]

    @property
    def action(self):
        return CATALOG[self.code][2]

    def report(self, *, stage='', target='', device='', computer='', at='') -> str:
        title, cause, action = CATALOG[self.code]
        return '\n'.join((
            'KOMI Diagnostic v1', f'App: {APP_VERSION}',
            f'Time: {at or datetime.now().astimezone().isoformat(timespec="seconds")}',
            f'Error Code: {self.error_code}',
            f'Code: {self.code}', f'ขั้นตอน: {safe_text(stage) or "ไม่ระบุ"}',
            f'ปลายทาง: {safe_text(target) or "ไม่ระบุ"}',
            f'เครื่องพิมพ์: {safe_text(device) or "—"}', f'คอมที่ทำรายการ: {safe_text(computer) or socket.gethostname()}',
            f'ปัญหา: {title}', f'สาเหตุที่ยืนยันได้: {cause}',
            'หลักฐาน: ' + ('; '.join(self.evidence) or 'ไม่มี exception แบบมีโครงสร้างในรายการนี้'),
            f'ตำแหน่งและวิธีแก้: {action}',
        ))


def diagnose(error: BaseException | str) -> Diagnostic:
    if not isinstance(error, BaseException):
        # Only consume our explicit persisted code, never guess from arbitrary text.
        text = safe_text(error or '')
        public = re.search(r'(?m)^Error Code: (KOMI-[A-Z]+-[0-9]{3})$', text)
        if public and public[1] in CODE_KEYS:
            return Diagnostic(CODE_KEYS[public[1]])
        match = re.search(r'(?m)^Code: ([a-z_]+)$', text)
        if match and match[1] in CATALOG:
            return Diagnostic(match[1])
        return Diagnostic('operation_failed', ('message=' + text[:1500],) if text else ())
    chain, seen = [], set()
    current = error
    while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 12:
        seen.add(id(current))
        chain.append(current)
        # Implicit context can be a previous fallback attempt (e.g. Public auth
        # followed by Admin TLS). Only an explicit cause describes this failure.
        current = current.reason if isinstance(current, URLError) and isinstance(current.reason, BaseException) else current.__cause__
    evidence = ['exception=' + ' -> '.join(type(item).__name__ for item in chain)]
    if error.__traceback__ is not None:
        evidence.append('location=' + ' -> '.join(
            f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
            for frame in traceback.extract_tb(error.__traceback__, limit=4)))
    code = getattr(error, 'diagnostic_code', '')
    if code not in CATALOG:
        code = 'operation_failed'
    for item in chain:
        endpoint = getattr(item, 'diagnostic_endpoint', '')
        if endpoint:
            evidence.append('endpoint=' + safe_text(endpoint))
        mode = getattr(item, 'diagnostic_mode', '')
        if mode in {'User/Public', 'Admin'}:
            evidence.append('request_mode=' + mode)
        declared = getattr(item, 'diagnostic_code', '')
        if declared in CATALOG:
            code = declared
            if str(item):
                evidence.append('reason=' + safe_text(item))
            continue
        if isinstance(item, HTTPError):
            evidence.append(f'HTTP={item.code}')
            code = {401:'auth_rejected',403:'http_forbidden',404:'endpoint_missing',407:'proxy_auth',429:'rate_limited'}.get(item.code, 'server_error' if item.code >= 500 else code)
        elif isinstance(item, ssl.SSLCertVerificationError):
            number = getattr(item, 'verify_code', None)
            if type(number) is int:
                number &= 0xFFFFFFFF
                evidence.append(f'verify_code={number}')
            code = {
                9:'certificate_not_yet_valid',10:'certificate_expired',18:'certificate_trust',
                19:'certificate_trust',20:'certificate_trust',21:'certificate_trust',23:'certificate_revoked',
                62:'certificate_name',64:'certificate_name',0x800B0101:'certificate_period',
                0x800B0109:'certificate_trust',0x800B010A:'certificate_trust',
                0x800B010C:'certificate_revoked',0x800B010F:'certificate_name',
                0x800B0111:'certificate_distrusted',0x80092013:'certificate_revocation_unavailable',
            }.get(number, 'tls_certificate')
        elif isinstance(item, ssl.SSLError):
            reason = getattr(item, 'reason', '')
            if reason and re.fullmatch('[A-Z0-9_]+', reason):
                evidence.append(f'TLS_reason={reason}')
            code = 'tls_protocol' if reason in {'WRONG_VERSION_NUMBER','UNSUPPORTED_PROTOCOL','TLSV1_ALERT_PROTOCOL_VERSION','NO_PROTOCOLS_AVAILABLE'} else 'tls_handshake'
        elif isinstance(item, socket.gaierror):
            code = 'dns_failed'
        elif isinstance(item, OSError):
            number = getattr(item, 'winerror', None) or item.errno
            if number is not None:
                evidence.append(f'OS_code={number}')
            if number == 10013:
                code = 'network_access_denied'
            elif number in {32,33}:
                code = 'file_locked'
            elif isinstance(item, TimeoutError) or number in {errno.ETIMEDOUT,10060}:
                code = 'connection_timeout'
            elif isinstance(item, ConnectionRefusedError) or number in {errno.ECONNREFUSED,10061}:
                code = 'connection_refused'
            elif isinstance(item, ConnectionResetError) or number in {errno.ECONNRESET,10054}:
                code = 'connection_reset'
            elif number in {errno.EHOSTUNREACH,errno.ENETUNREACH,10051,10065}:
                code = 'network_unreachable'
            elif number in {errno.ENOSPC,112}:
                code = 'disk_full'
            elif isinstance(item, PermissionError):
                code = 'file_permission' if number is not None or item.filename else 'access_denied'
                if code == 'access_denied':
                    evidence.append('reason=' + safe_text(item))
            elif isinstance(item, FileNotFoundError):
                code = 'file_missing'
        elif isinstance(item, sqlite3.Error):
            number = getattr(item, 'sqlite_errorcode', 0)
            evidence.append(f'SQLite_code={number}')
            if number & 255 in {5,6}:
                code = 'database_locked'
            elif number & 255 in {11,26}:
                code = 'database_invalid'
        elif isinstance(item, (json.JSONDecodeError, ET.ParseError)):
            code = 'response_invalid'
        elif isinstance(item, ImportError):
            code = 'dependency_missing'
            evidence.append('module=' + safe_text(getattr(item, 'name', '') or str(item)))
        elif isinstance(item, ValueError):
            code = 'input_invalid'
            evidence.append('reason=' + safe_text(item))
    if code == 'operation_failed':
        evidence.extend('message=' + safe_text(item)[:1500] for item in chain if str(item))
    return Diagnostic(code, tuple(evidence))


def diagnostic_report(error, **context):
    public = context.pop('public', False)
    if isinstance(error, str) and error.startswith('KOMI Diagnostic v1\n'):
        return safe_text(error)
    diagnostic = diagnose(error)
    if str(context.get('stage', '')).startswith('HOST') and diagnostic.code in {'tls_handshake', 'tls_protocol'}:
        diagnostic = Diagnostic('host_tls_handshake', diagnostic.evidence)
    if public:
        diagnostic = Diagnostic(diagnostic.code, tuple(item for item in diagnostic.evidence
                                if not item.startswith(('exception=', 'location=', 'message=', 'reason='))))
    return diagnostic.report(**context)


def with_diagnostic(message, error, stage):
    """Keep the original instruction while preserving the typed cause for the UI."""
    return safe_text(message) + '\n\n' + diagnostic_report(error, stage=stage, target=getattr(error, 'filename', '') or '')


def warning_report(title, message, *, advice='', details=''):
    """Envelope for validation/business notices that have no exception."""
    text = safe_text(message)
    fingerprint = hashlib.sha256((str(title) + '\n' + text).encode()).hexdigest()[:12]
    return '\n'.join((
        'KOMI Warning v1', f'App: {APP_VERSION}',
        f'Time: {datetime.now().astimezone().isoformat(timespec="seconds")}',
        f'Error Code: {ERROR_CODES["ui_warning"]}',
        f'Code: ui_warning_{fingerprint}', f'คอมที่ทำรายการ: {socket.gethostname()}',
        f'หน้าต่าง: {safe_text(title)}', f'ข้อความ: {text}',
        f'คำแนะนำ: {safe_text(advice) or text}', f'รายละเอียด: {safe_text(details) or "—"}',
        'หลักฐาน: คำเตือนจากหน้าจอ; ไม่มี typed exception แนบ จึงไม่สรุปสาเหตุเครือข่ายหรือรหัสผ่าน',
    ))
