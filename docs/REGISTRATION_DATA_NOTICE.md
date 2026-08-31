# KOMI Report V5.2.1 — Registration, Status and Aggregate Total Meter Data Notice

สถานะ: ข้อความฉบับปัจจุบันที่ใช้กับ Desktop schema 3
เวอร์ชันประกาศ: `KOMI-REG-2026-08-25-V52`

ข้อมูลชุดนี้ออกแบบให้เป็นข้อมูลของนิติบุคคล การติดตั้ง และอุปกรณ์ ไม่ใช่ข้อมูลส่วนบุคคล ผู้ใช้ต้องกรอกเฉพาะชื่อบริษัท/หน่วยงานและห้ามกรอกชื่อบุคคล KOMI Report ใช้ข้อมูลนี้เฉพาะการลงทะเบียน การติดตามสถานะระบบ Aggregate Total Meter และงาน Support ตามสัญญาหลักของลูกค้า

ข้อความไทยและอังกฤษที่แอปแสดงอยู่ที่ `source/services/registration_data_notice.py`

## ข้อมูลที่ส่งตาม schema 3

Desktop ส่งข้อมูลแยกเป็น 3 ประเภทเท่านั้น:

### 1. Registration

- Schema/event/client identifier และ Installation ID
- Public verification key และ Ed25519 request proof สำหรับยืนยันตัว Installation; private key ไม่ออกจากเครื่องลูกค้า
- ชื่อบริษัทหรือนิติบุคคลที่ผู้ใช้กรอก
- วันที่เริ่มใช้ Version ระบบปฏิบัติการ และสถาปัตยกรรมเครื่อง
- วันเวลาสร้างคำขอลงทะเบียน
- Device inventory ของเครื่อง Konica Minolta ที่ค้นพบ: จำนวนที่พบ, Serial Number, รุ่น, สถานะเลือกใช้ และ Slot 1–3 เฉพาะเครื่องที่เลือก

### 2. Status

- Installation ID, Version, ระบบปฏิบัติการ และสถาปัตยกรรมเครื่อง
- วันเวลาที่ Desktop ส่งสถานะ

Status ใช้บอกว่า Desktop ยังติดต่อระบบได้ ไม่ได้ใช้สรุปว่าเครื่องพิมพ์เสีย หาก Desktop ขาดการติดต่อเกินระยะเวลาที่กำหนด ระบบหลังบ้านจึงแจ้งให้ Support ตรวจสอบ

### 3. Aggregate Total Meter

- Installation ID และวันเวลาที่ส่ง
- Serial Number, รุ่น, Slot, Aggregate Total Meter ล่าสุด, สถานะอ่านได้/อ่านไม่ได้ และวันเวลาที่อ่าน Meter ของเครื่องที่เลือกไม่เกิน 3 เครื่อง

Aggregate Total Meter ที่ไม่เพิ่มเป็นเพียงคำเตือนให้ตรวจสอบ ไม่ใช่หลักฐานว่าเครื่องพิมพ์เสีย

## ข้อมูลที่ไม่ส่ง

- ไม่ส่ง IP address, MAC address หรือ hostname
- ไม่ส่ง Username/Password, Credential, private key, access token หรือ cookie
- ไม่ส่ง Counter รายละเอียด เช่น Color/B&W, Copy/Print, ขนาดกระดาษ, FAX, ระดับหมึก หรือสถานะถาดกระดาษ
- ไม่ส่งชื่อผู้ใช้, Account Track, รหัสผู้ใช้ หรือข้อมูลที่ระบุตัวบุคคล
- ไม่ส่งชื่อ/เนื้อหาเอกสาร, Print Job หรือข้อมูลจากไฟล์ลูกค้า
- ไม่ส่ง Raw SNMP, Raw XML/JSON, Raw error, Application log หรือ Raw request body

Registration, Status และ Aggregate Total Meter ไม่เปลี่ยนการคำนวณ Meter, Billing, Report หรือ Excel ที่เก็บอยู่ใน Database ของลูกค้า

## วัตถุประสงค์

- นับจำนวนบริษัทและ Installation ที่ใช้งาน KOMI Report
- แสดง Version, OS, สถานะการติดต่อ และรุ่นเครื่องสำหรับงาน Support
- แยก Desktop ขาดการเชื่อมต่อ, Meter อ่านไม่ได้ และ Total Meter ไม่เพิ่ม เพื่อให้ Support ตรวจสอบสาเหตุที่ถูกต้อง

ข้อมูลไม่ถูกขาย ไม่ใช้โฆษณาแบบเจาะจง และไม่ใช้วิเคราะห์ผู้ใช้หรือเนื้อหาเอกสาร

## ระยะเวลาเก็บข้อมูล

เก็บข้อมูล Registration, Status และ Aggregate Total Meter ตลอดระยะเวลาที่ลูกค้าใช้งาน KOMI Report เพื่อรองรับการให้บริการและงาน Support ตามสัญญาหลักของลูกค้า

## การเข้าถึงและความปลอดภัย

- เข้าถึงได้เฉพาะผู้ดูแล KOMI Report/Support และผู้ให้บริการ Hosting ที่ได้รับสิทธิ์ตามหน้าที่
- ระบบหลังบ้านต้องใช้ Login และกำหนดสิทธิ์ตามบทบาท ห้ามเปิดข้อมูล Registration เป็นสาธารณะ
- ใช้ HTTPS และ Payload allow-list; private installation key เก็บใน OS vault ของเครื่องลูกค้า
- ไม่เก็บ Token, Raw request body หรือ Source IP ใน Registration database/Application log; Source IP ใช้ชั่วคราวเพื่อเชื่อมต่อเครือข่ายเท่านั้น
- หาก Hosting เปลี่ยนขอบเขตให้เก็บข้อมูลอื่น ต้องทบทวนประกาศนี้ก่อนเปิดใช้การเปลี่ยนแปลง

## ติดต่อ

- ผู้ดูแลระบบ: ทีม KOMI Report
- ขอแก้ไขหรือลบข้อมูล Installation: ติดต่อผู้ส่งมอบโปรแกรม KOMI Report
- ระบบหลังบ้านและพื้นที่จัดเก็บ: `https://www.dmskm.com/` ประเทศไทย

ประกาศนี้อธิบายขอบเขตข้อมูลเท่านั้น ผลการทดสอบ API หรือสถานะพร้อมใช้งานของ Release ต้องอ้างอิงหลักฐาน Release/E2E ของชุดติดตั้งเดียวกันแยกต่างหาก
