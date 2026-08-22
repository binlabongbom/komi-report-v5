# KOMI Report V5.1 — Registration Data Notice

สถานะ: **Draft / ยืนยัน Data boundary แล้ว**  
เวอร์ชัน: `DRAFT-2026-08-22`

ข้อมูลที่ Desktop ส่งเป็นข้อมูลของนิติบุคคล, Installation และเครื่องพิมพ์ ไม่ใช่ข้อมูลส่วนบุคคล โดยผู้ใช้กรอกเฉพาะชื่อบริษัท/หน่วยงาน และ API ไม่จัดเก็บ Source IP หรือข้อมูลอื่นที่เชื่อมโยงกลับไปยังบุคคล ตามคำยืนยันของเจ้าของระบบวันที่ 2026-08-22

ข้อความไทยและอังกฤษที่แอปแสดงอยู่ที่ `source/services/registration_data_notice.py`.

## ขอบเขตข้อมูล

- ส่ง Installation ID, ชื่อบริษัท/นิติบุคคล, วันที่เริ่มใช้, Version, OS/architecture, timestamps/status และ Device inventory ที่มี Serial Number, Model, Selected และ Slot
- ไม่ส่ง IP, MAC, hostname, Credential, Meter/Counter, User/Account, Document หรือ Application log
- การไม่ส่งไม่กระทบ Meter, Billing, Report หรือ Excel ภายในเครื่อง

## Hosting ที่ยืนยัน

- ระบบหลังบ้านและพื้นที่จัดเก็บ: `https://www.dmskm.com/`
- DNS ที่ตรวจได้ชี้ไป `203.170.129.8`; APNIC ระบุเครือข่ายในประเทศไทย
- HTTPS ตอบ `200` บน `www`, root redirect ไป `www`, certificate ครอบคลุม `dmskm.com` และ `*.dmskm.com`
- เจ้าของระบบยืนยันว่า API/Application log ไม่จัดเก็บ Source IP, Raw request body หรือ Token

## สิ่งที่เหลือก่อนเปิด Production Registration

1. ยืนยัน OpenAPI/Staging และ endpoint path ที่ Desktop ใช้จริง
2. ยืนยัน Retention 12 เดือนสำหรับ Heartbeat/Status และ 90 วันสำหรับ Technical delivery record จากระบบที่ deploy
3. ยืนยัน Dashboard ใช้ Login/MFA/RBAC และไม่เปิด Registration data สาธารณะ

หากการตั้งค่าในอนาคตเปลี่ยนให้เก็บ Source IP, ชื่อผู้ติดต่อ, อีเมล หรือข้อมูลที่ระบุบุคคลได้ ต้องประเมิน Privacy ใหม่และออก Privacy Notice แยกก่อน Production
