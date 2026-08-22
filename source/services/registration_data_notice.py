"""Reviewable, non-personal Registration Data Notice for KOMI Report."""

from __future__ import annotations

DRAFT_NOTICE_VERSION = "DRAFT-2026-08-22"

_THAI_NOTICE = f"""ประกาศข้อมูลการลงทะเบียน KOMI Report V5.1
เวอร์ชัน {DRAFT_NOTICE_VERSION} · ร่างเพื่อการตรวจสอบ

ข้อมูลชุดนี้ออกแบบให้เป็นข้อมูลของนิติบุคคล การติดตั้ง และอุปกรณ์ ไม่ใช่ข้อมูลส่วนบุคคล ผู้ใช้ต้องกรอกเฉพาะชื่อบริษัท/หน่วยงานและห้ามกรอกชื่อบุคคล

1. ข้อมูลที่ส่ง
• รหัสการติดตั้ง (Installation ID)
• ชื่อบริษัทหรือนิติบุคคลที่ผู้ใช้กรอก
• วันที่เริ่มใช้งาน Version ของโปรแกรม ระบบปฏิบัติการ และสถาปัตยกรรมเครื่อง
• วันเวลาลงทะเบียน/Heartbeat และสถานะ Installation
• จำนวนเครื่อง Konica Minolta ที่ค้นพบ รวมถึง Serial Number, รุ่นเครื่อง, สถานะเลือกใช้งาน และ Slot 1–3 ของเครื่องที่เลือก

2. ข้อมูลที่ไม่ส่ง
ไม่ส่ง IP address, MAC address, hostname, Username/Password หรือ Credential, Meter/Counter, ชื่อผู้ใช้หรือ Account, ชื่อ/เนื้อหาเอกสาร และ Application log

3. วัตถุประสงค์
• นับจำนวนบริษัทและ Installation ที่ใช้งาน KOMI Report
• แสดง Version, OS, สถานะ Active 7/30/90 วัน และรุ่นเครื่องสำหรับงาน Support
• ตรวจสอบความเข้ากันได้และแก้ปัญหาการลงทะเบียนโดยไม่อ่านข้อมูลงานพิมพ์
ข้อมูลจะไม่ถูกขาย ไม่ใช้โฆษณาแบบเจาะจง และไม่ใช้วิเคราะห์ผู้ใช้หรือเนื้อหาเอกสาร

4. ความสมัครใจ
ผู้ใช้เลือกไม่ส่งข้อมูลได้ การไม่รับทราบประกาศนี้ไม่กระทบ Meter, Billing, Report หรือ Excel ภายในเครื่อง แต่ Installation จะไม่ปรากฏในระบบหลังบ้านและทีม Support จะไม่เห็นสถานะจากระยะไกล

5. ผู้ที่เข้าถึงได้
เฉพาะผู้ดูแล KOMI Report/Support ที่ได้รับสิทธิ์ และผู้ให้บริการ Hosting ตามหน้าที่ ระบบหลังบ้านต้องใช้ Login และกำหนดสิทธิ์ตามบทบาท ห้ามเปิดข้อมูล Registration เป็นสาธารณะ

6. ระยะเวลาเก็บที่เสนอ
• ข้อมูล Installation ปัจจุบันและ Device inventory ล่าสุด: ระหว่างที่ Installation ยัง Active
• Heartbeat และประวัติสถานะ: ไม่เกิน 12 เดือน
• Idempotency/Technical delivery record ที่ไม่มี Token หรือ Raw body: ไม่เกิน 90 วัน
• เมื่อ Inactive, Deactivated หรือ Revoked: ลบหรือทำให้ไม่สามารถเชื่อมโยงกลับได้ภายใน 12 เดือนนับจาก Last seen
ระยะเวลานี้ต้องยืนยันกับระบบ Hosting ก่อนเปิดใช้งานจริง

7. ความปลอดภัยและ Web server log
ใช้ HTTPS, Payload allow-list, OS vault, Token แบบ Hash เมื่อระบบรองรับ, MFA/RBAC และไม่บันทึก Token, Raw request body หรือ Source IP ใน Registration database/Application log. Source IP ถูกใช้ชั่วคราวเฉพาะเพื่อเชื่อมต่อเครือข่ายและไม่ถูกจัดเก็บ หากการตั้งค่า Hosting เปลี่ยนให้เก็บข้อมูลดังกล่าว ต้องทบทวนประกาศนี้ก่อนเปิดใช้งานต่อ

8. ติดต่อ
ผู้ดูแลระบบ: ทีม KOMI Report
ช่องทาง Support/ขอแก้ไขหรือลบข้อมูล Installation: ติดต่อผู้ส่งมอบโปรแกรม KOMI Report
ระบบหลังบ้านและพื้นที่จัดเก็บ: https://www.dmskm.com/ ประเทศไทย

รายการที่ต้องยืนยันก่อนเปิด Production: Retention ที่ทำได้จริง, OpenAPI/Staging contract และผู้อนุมัติการเปิดใช้งาน"""

_ENGLISH_NOTICE = f"""KOMI Report V5.1 Registration Data Notice
Version {DRAFT_NOTICE_VERSION} · Review draft

This dataset is designed to contain organisation, installation, and device information—not personal data. Users must enter a company/organisation name only and must not enter a person's name.

1. Data sent
• Installation ID
• Company or legal-entity name entered by the user
• First-use date, application version, operating system, and device architecture
• Registration/Heartbeat timestamps and Installation status
• Number of discovered Konica Minolta printers and each printer's serial number, model, selected status, and local Slot 1–3 when selected

2. Data not sent
The application does not send IP address, MAC address, hostname, username/password or credentials, meter/counter values, user or account names, document names or content, or application logs.

3. Purposes
• Count companies and Installations using KOMI Report
• Show version, OS, Active 7/30/90-day status, and printer models for Support
• Check compatibility and diagnose Registration without reading print-job data
The data is not sold, used for targeted advertising, or used to profile users or document content.

4. Optional delivery
Users may choose not to send the data. Declining this notice does not affect local Meter, Billing, Report, or Excel functions. The Installation will not appear in the back-office system and Support will not have remote lifecycle status.

5. Access
Access is limited to authorised KOMI Report administrators/Support and the Hosting provider as required to operate the service. The back office must require login and role-based access. Registration data must not be public.

6. Proposed retention
• Current Installation record and latest device inventory: while the Installation remains Active
• Heartbeat and lifecycle history: no longer than 12 months
• Idempotency/technical delivery records that exclude tokens and raw bodies: no longer than 90 days
• After Inactive, Deactivated, or Revoked: delete or de-link within 12 months of Last seen
These periods must be confirmed against the deployed Hosting system before activation.

7. Security and web-server logs
Controls include HTTPS, an allow-listed payload, OS-vault storage, hashed tokens where supported, MFA/RBAC, and no token, raw-request-body, or Source-IP storage in the Registration database or application logs. Source IP is used transiently only to establish the network connection and is not retained. This notice must be reviewed if Hosting configuration changes to retain such data.

8. Contact
System owner: KOMI Report team
Support/Installation correction or deletion channel: Contact the KOMI Report software provider
Back-office system and storage location: https://www.dmskm.com/ — Thailand

Items required before Production: proven retention, OpenAPI/Staging contract, and the release approver."""


def registration_data_notice(language: str) -> str:
    """Return the Registration Data Notice in the active UI language."""

    return _ENGLISH_NOTICE if language.strip().lower().startswith("en") else _THAI_NOTICE
