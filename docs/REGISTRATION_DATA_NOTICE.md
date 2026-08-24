# KOMI Report V5.1 — Registration Data Notice

สถานะ: **Approved for KOMI Report V5.1 acknowledgement**
เวอร์ชัน: `KOMI-REG-2026-08-24`

ข้อมูลที่ Desktop ส่งเป็นข้อมูลของนิติบุคคล, Installation และเครื่องพิมพ์ ไม่ใช่ข้อมูลส่วนบุคคล ผู้ใช้กรอกเฉพาะชื่อบริษัท/หน่วยงานและห้ามกรอกชื่อบุคคล ลูกค้าได้รับ KOMI Report เพื่อใช้ร่วมกับเครื่อง Konica Minolta ตามสัญญาหลักสำหรับการเช่าหรือซื้อเครื่อง การทำเครื่องหมายในหน้าติดตั้งจึงเป็นการรับทราบรายการข้อมูลที่ระบบส่ง ไม่ใช่การขอสิทธิ์อ่านข้อมูลงานพิมพ์หรือข้อมูลผู้ใช้งาน

ข้อความไทยและอังกฤษที่แอปแสดงอยู่ที่ `source/services/registration_data_notice.py`.

## ขอบเขตข้อมูล

- ส่ง Installation ID, ชื่อบริษัท/นิติบุคคล, วันที่เริ่มใช้, Version, OS/architecture, timestamps/status และ Device inventory ที่มี Serial Number, Model, Selected และ Slot
- ไม่ส่ง IP, MAC, hostname, Credential, Meter/Counter, User/Account, Document หรือ Application log
- Registration ไม่เปลี่ยนการคำนวณ Meter, Billing, Report หรือ Excel ภายในเครื่อง

## Hosting ที่ยืนยัน

- ระบบหลังบ้านและพื้นที่จัดเก็บ: `https://www.dmskm.com/`
- DNS ที่ตรวจได้ชี้ไป `203.170.129.8`; APNIC ระบุเครือข่ายในประเทศไทย
- HTTPS ตอบ `200` บน `www`, root redirect ไป `www`, certificate ครอบคลุม `dmskm.com` และ `*.dmskm.com`
- เจ้าของระบบยืนยันว่า API/Application log ไม่จัดเก็บ Source IP, Raw request body หรือ Token

## การเก็บและการเข้าถึง

- Current Installation และ Device inventory ล่าสุดเก็บระหว่างที่ Installation ใช้งาน
- Heartbeat/Status history เก็บไม่เกิน 12 เดือน และ Idempotency technical record เก็บไม่เกิน 90 วัน
- เมื่อลูกค้ายกเลิกใช้ ให้ลบหรือยกเลิกการเชื่อมโยง Installation ภายใน 12 เดือนนับจาก Last seen
- เข้าถึงได้เฉพาะ KOMI Report administrator/Support ที่ได้รับสิทธิ์ผ่านระบบหลังบ้านที่ต้อง Login
- ลูกค้าขอตรวจสอบ แก้ไข ส่งออก หรือยกเลิก Installation ผ่านผู้ส่งมอบโปรแกรมได้

## สถานะการเชื่อมต่อ Production

ประกาศฉบับนี้อนุมัติข้อความและขอบเขตข้อมูลแล้ว แต่การส่งจริงยังคง fail-closed จน API ที่ deploy รับ Desktop schema v2 ซึ่งใช้ `device_inventory.devices[].serial_number`. การอนุมัติประกาศไม่ใช่หลักฐานว่า API contract ผ่าน

หากการตั้งค่าในอนาคตเปลี่ยนให้เก็บ Source IP, ชื่อผู้ติดต่อ, อีเมล หรือข้อมูลที่ระบุบุคคลได้ ต้องประเมิน Privacy ใหม่และออก Privacy Notice แยกก่อน Production
