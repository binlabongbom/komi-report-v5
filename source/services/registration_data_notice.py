"""Reviewable, non-personal Registration Data Notice for KOMI Report."""

from __future__ import annotations

REGISTRATION_NOTICE_VERSION = "KOMI-REG-2026-08-25-V52"

_THAI_NOTICE = f"""ประกาศข้อมูลการลงทะเบียนและ Total Meter ของ KOMI Report V5.2
เวอร์ชัน {REGISTRATION_NOTICE_VERSION} · ใช้กับ KOMI Report V5.2

ข้อมูลชุดนี้ออกแบบให้เป็นข้อมูลของนิติบุคคล การติดตั้ง และอุปกรณ์ ไม่ใช่ข้อมูลส่วนบุคคล ผู้ใช้ต้องกรอกเฉพาะชื่อบริษัท/หน่วยงานและห้ามกรอกชื่อบุคคล

1. ข้อมูลที่ส่ง
• รหัสการติดตั้ง (Installation ID)
• ชื่อบริษัทหรือนิติบุคคลที่ผู้ใช้กรอก
• วันที่เริ่มใช้งาน Version ของโปรแกรม ระบบปฏิบัติการ และสถาปัตยกรรมเครื่อง
• วันเวลาลงทะเบียน/Heartbeat และสถานะ Installation
• จำนวนเครื่อง Konica Minolta ที่ค้นพบ รวมถึง Serial Number, รุ่นเครื่อง, สถานะเลือกใช้งาน และ Slot 1–3 ของเครื่องที่เลือก
• Aggregate Total Meter ล่าสุดของเครื่องที่เลือก, สถานะอ่านได้/อ่านไม่ได้ และวันเวลาที่อ่าน Meter

2. ข้อมูลที่ไม่ส่ง
ไม่ส่ง IP address, MAC address, hostname, Username/Password หรือ Credential, Counter รายละเอียด เช่น Color/B&W/Copy/Print, ชื่อผู้ใช้หรือ Account, ชื่อ/เนื้อหาเอกสาร, Print Job, Raw SNMP/XML/Error และ Application log

3. วัตถุประสงค์
• นับจำนวนบริษัทและ Installation ที่ใช้งาน KOMI Report
• แสดง Version, OS, สถานะ Active 7/30/90 วัน และรุ่นเครื่องสำหรับงาน Support
• ตรวจสอบความเข้ากันได้และแยกสถานะ Desktop ขาดการเชื่อมต่อ, Meter อ่านไม่ได้ หรือไม่มีการพิมพ์ตาม Aggregate Total Meter
การที่ Total Meter ไม่เพิ่มเป็นเพียงคำเตือนให้ตรวจสอบ ไม่ใช่หลักฐานว่าเครื่องเสีย
ข้อมูลจะไม่ถูกขาย ไม่ใช้โฆษณาแบบเจาะจง และไม่ใช้วิเคราะห์ผู้ใช้หรือเนื้อหาเอกสาร

4. เงื่อนไขการใช้งาน
KOMI Report เป็นโปรแกรมที่ให้ใช้ร่วมกับเครื่อง Konica Minolta ตามสัญญาหลักของลูกค้า และต้องลงทะเบียน Online หรือใช้ Offline License ที่ถูกต้องก่อนเริ่มใช้งาน การลงทะเบียนไม่ใช่การขอสิทธิ์เข้าถึงข้อมูลงานพิมพ์หรือข้อมูลผู้ใช้งาน และไม่กระทบการคำนวณ Meter, Billing, Report หรือ Excel ภายในเครื่อง

5. ผู้ที่เข้าถึงได้
เฉพาะผู้ดูแล KOMI Report/Support ที่ได้รับสิทธิ์ และผู้ให้บริการ Hosting ตามหน้าที่ ระบบหลังบ้านต้องใช้ Login และกำหนดสิทธิ์ตามบทบาท ห้ามเปิดข้อมูล Registration เป็นสาธารณะ

6. ระยะเวลาเก็บข้อมูล
เก็บข้อมูลการลงทะเบียน สถานะ และ Aggregate Total Meter ตลอดระยะเวลาที่ใช้งาน KOMI Report เพื่อรองรับการให้บริการและงาน Support ตามสัญญาหลักของลูกค้า

7. ความปลอดภัยและ Web server log
ใช้ HTTPS, Payload allow-list, OS vault, Token แบบ Hash เมื่อระบบรองรับ, MFA/RBAC และไม่บันทึก Token, Raw request body หรือ Source IP ใน Registration database/Application log. Source IP ถูกใช้ชั่วคราวเฉพาะเพื่อเชื่อมต่อเครือข่ายและไม่ถูกจัดเก็บ หากการตั้งค่า Hosting เปลี่ยนให้เก็บข้อมูลดังกล่าว ต้องทบทวนประกาศนี้ก่อนเปิดใช้งานต่อ

8. ติดต่อ
ผู้ดูแลระบบ: ทีม KOMI Report
ช่องทาง Support/ขอแก้ไขหรือลบข้อมูล Installation: ติดต่อผู้ส่งมอบโปรแกรม KOMI Report
ระบบหลังบ้านและพื้นที่จัดเก็บ: https://www.dmskm.com/ ประเทศไทย

ข้อมูลนี้ใช้เฉพาะการลงทะเบียนระบบ การติดตาม Aggregate Total Meter และงาน Support ตามขอบเขตข้างต้น"""

_ENGLISH_NOTICE = f"""KOMI Report V5.2 Registration and Total Meter Data Notice
Version {REGISTRATION_NOTICE_VERSION} · KOMI Report V5.2

This dataset is designed to contain organisation, installation, and device information—not personal data. Users must enter a company/organisation name only and must not enter a person's name.

1. Data sent
• Installation ID
• Company or legal-entity name entered by the user
• First-use date, application version, operating system, and device architecture
• Registration/Heartbeat timestamps and Installation status
• Number of discovered Konica Minolta printers and each printer's serial number, model, selected status, and local Slot 1–3 when selected
• Latest aggregate Total Meter for selected printers, whether the Meter was readable, and the Meter observation timestamp

2. Data not sent
The application does not send IP address, MAC address, hostname, username/password or credentials, detailed Color/B&W/Copy/Print counters, user or account names, document names or content, print jobs, raw SNMP/XML/errors, or application logs.

3. Purposes
• Count companies and Installations using KOMI Report
• Show version, OS, Active 7/30/90-day status, and printer models for Support
• Distinguish Desktop connectivity loss, an unavailable Meter, and no-print activity using only aggregate Total Meter observations
An unchanged Total Meter is a warning to investigate, not proof that a printer is faulty.
The data is not sold, used for targeted advertising, or used to profile users or document content.

4. Conditions of use
KOMI Report is supplied for use with Konica Minolta devices under the customer's master agreement and requires successful Online Registration or a valid Offline License before use. Registration does not grant access to print-job or user data and does not change local Meter, Billing, Report, or Excel calculations.

5. Access
Access is limited to authorised KOMI Report administrators/Support and the Hosting provider as required to operate the service. The back office must require login and role-based access. Registration data must not be public.

6. Data retention
Registration, status, and aggregate Total Meter data is retained throughout the period in which KOMI Report is used, so the service and Support can be provided under the customer's master agreement.

7. Security and web-server logs
Controls include HTTPS, an allow-listed payload, OS-vault storage, hashed tokens where supported, MFA/RBAC, and no token, raw-request-body, or Source-IP storage in the Registration database or application logs. Source IP is used transiently only to establish the network connection and is not retained. This notice must be reviewed if Hosting configuration changes to retain such data.

8. Contact
System owner: KOMI Report team
Support/Installation correction or deletion channel: Contact the KOMI Report software provider
Back-office system and storage location: https://www.dmskm.com/ — Thailand

This information is used only for system registration, aggregate Total Meter monitoring, and Support within the scope above."""


def registration_data_notice(language: str) -> str:
    """Return the Registration Data Notice in the active UI language."""

    return _ENGLISH_NOTICE if language.strip().lower().startswith("en") else _THAI_NOTICE
