# KOMI Report

> Print meter, device monitoring and reporting for selected Konica Minolta devices.

KOMI Report ช่วยอ่านและเก็บ Total Meter / Counter จากเครื่องพิมพ์ที่เลือกไว้ สรุปการใช้งาน Print/Copy ดูสถานะอุปกรณ์ และส่งออกรายงาน Excel โดยข้อมูลหลักเก็บอยู่ใน Database ของลูกค้า

## Download

**Current stable release: V5.2.6 — Windows x64**

- [Download latest release](https://github.com/binlabongbom/komi-report-v5/releases/latest)
- [Installation guide](docs/CUSTOMER_INSTALL_GUIDE.md)
- [User guide](docs/CUSTOMER_GUIDE_V5_2.md)
- [Release notes](docs/CUSTOMER_RELEASE_NOTES.md)

> V5.2.6 installer ปัจจุบันเป็น unsigned installation candidate. ก่อนติดตั้งให้ตรวจ SHA-256 จากไฟล์ `INSTALLER.sha256` ที่แนบมากับ Release และปฏิบัติตามคำแนะนำใน Installation Guide

## What KOMI Report does

| Feature | Description |
|---|---|
| Dashboard | สรุปยอดใช้งาน ค่าใช้จ่าย และสถานะเครื่อง |
| Device Monitoring | อ่าน Total Meter, Toner, Paper Tray และ Counter ที่รุ่นนั้นรองรับ |
| Reports | Overview, Users, Printers, Usage และ Legacy views |
| Excel Export | ส่งออกข้อมูลเป็น workbook 6 sheets สำหรับวิเคราะห์ต่อ |
| Primary / Secondary | ให้หลายเครื่องใช้งานร่วมกับ Primary ภายใน LAN |
| Web Report | เปิดรายงานแบบ read-only ให้เครื่องอื่นใน Trusted LAN |
| Parser Mapping | ปรับ mapping ของ Counter แยกตาม Serial Number เมื่ออุปกรณ์ส่งข้อมูลต่างกัน |

KOMI Report V5.2.6 รองรับการเลือกเครื่องพิมพ์สูงสุด 3 เครื่องต่อ installation ตาม customer release ปัจจุบัน

## Quick Start

### 1. Download

เปิด [Latest Release](https://github.com/binlabongbom/komi-report-v5/releases/latest) และดาวน์โหลด Windows x64 installer พร้อม `INSTALLER.sha256`

### 2. Verify installer

ตรวจ SHA-256 ของ installer ให้ตรงกับค่าที่อยู่ใน `INSTALLER.sha256` ก่อนติดตั้ง โดยเฉพาะ release ที่ยังไม่ได้ code signing

ดูขั้นตอนเต็มที่ [Customer Installation Guide](docs/CUSTOMER_INSTALL_GUIDE.md)

### 3. First Run

Wizard จะพาไปตามขั้นตอนหลัก:

1. กรอกชื่อบริษัทและตรวจ Database Path
2. Import Database เดิมหากเป็นการย้าย/กู้คืนข้อมูล
3. ค้นหาเครื่องพิมพ์ใน LAN
4. เลือกเครื่องพิมพ์สูงสุด 3 เครื่อง
5. ตรวจ Model, Serial Number และ Web Connection
6. กำหนด Slot และชื่อจุดติดตั้ง
7. ตั้งราคา A4/A3 สี/ขาวดำ รอบบิล และเปอร์เซ็นต์กระดาษเสีย
8. ตรวจข้อมูลและบันทึก
9. ทำ Online Registration ก่อนเปิดใช้งานครั้งแรก

### 4. Read device data

ไปที่ **อุปกรณ์ → อ่านข้อมูลตอนนี้**

ข้อมูลที่แสดงขึ้นอยู่กับความสามารถของแต่ละรุ่น เช่น:

- Model / Serial Number
- Total Meter
- Toner C/M/Y/K
- Paper Tray
- Detailed Counter
- User Authentication / Account Track

ค่า `—` หมายถึงอุปกรณ์ไม่ส่งค่าหรือยังอ่านค่าไม่ได้ ไม่ใช่ค่า 0

### 5. View reports

ไปที่ **รายงาน** แล้วกำหนดช่วงวันที่ จากนั้นเลือกมุมมอง:

- **Overview** — Print/Copy สีและขาวดำ ยอดรวม ค่าใช้จ่าย และแนวโน้ม
- **Users** — การใช้งานตาม User/Account เมื่ออุปกรณ์มีข้อมูล Authentication
- **Printers** — เปรียบเทียบเครื่องพิมพ์
- **Usage** — มุมมอง D/M/Y พร้อม Print/Copy, A3/A4, Color/BW
- **Legacy** — Raw counter categories สำหรับตรวจสอบข้อมูลเฉพาะรุ่น

### 6. Export Excel

เลือก **ส่งออก Excel** เพื่อสร้าง workbook ที่มี 6 sheets:

1. การใช้งานรายเครื่อง
2. มุมมองผู้ใช้
3. มุมมองรายวัน
4. Legacy-รายเครื่อง
5. Legacy-ผู้ใช้
6. Legacy-รายวัน

## Primary / Secondary

หากมี Primary อยู่ใน LAN เครื่อง Secondary สามารถค้นพบข้อมูลบริษัท เครื่องพิมพ์ ราคา และรอบบิลจาก Primary ได้

ก่อน Sync ให้เปิดที่ Primary:

**การตั้งค่าขั้นสูง → รายงานผ่าน LAN → อนุญาต Secondary Sync 5 นาที**

จากนั้นจึง Sync จาก Secondary

## Web Report

KOMI Report สามารถเปิด Web Report ให้เครื่องอื่นใน LAN ดูรายงานได้ โดยมีตัวเลือก read-only แบบไม่ใช้รหัส

> ใช้โหมดนี้เฉพาะ Trusted LAN เท่านั้น และไม่ควร expose Web Report ออก Public Internet

## Documentation

### สำหรับผู้ใช้งาน

- [คู่มือผู้ใช้งาน V5.2](docs/CUSTOMER_GUIDE_V5_2.md)
- [คู่มือติดตั้ง](docs/CUSTOMER_INSTALL_GUIDE.md)
- [Release Notes](docs/CUSTOMER_RELEASE_NOTES.md)

### สำหรับทีมพัฒนา / ผู้ดูแล

- [File & Folder Guide](docs/FILE_AND_FOLDER_GUIDE.md)
- [Release Build & GitHub Workflow](docs/RELEASE_BUILD_AND_GITHUB_WORKFLOW.md)
- [Release Runbook](docs/RELEASE_RUNBOOK.md)
- [Release Support & Recovery](docs/RELEASE_SUPPORT_AND_RECOVERY.md)

## Screenshots

พื้นที่นี้เตรียมไว้สำหรับภาพจาก build จริง เพื่อไม่ให้ documentation แสดง UI ที่ไม่ตรงกับ software

ภาพที่ควรเพิ่มในรอบถัดไป:

- Dashboard / ภาพรวม
- Device page
- Reports Overview
- Usage report
- Settings
- First-run Wizard

เมื่อมีภาพแล้วให้เก็บใน `docs/images/` และอ้างจาก README / User Guide / Release ตาม feature ที่เกี่ยวข้อง

## Support information

เมื่อแจ้งปัญหา ควรเตรียม:

- KOMI Report version
- Windows version
- Printer model / Serial Number
- ขั้นตอนที่ทำให้เกิดปัญหา
- Screenshot
- Log ที่เกี่ยวข้อง

ดูรายละเอียดการวิเคราะห์และ recovery ที่ [Release Support & Recovery](docs/RELEASE_SUPPORT_AND_RECOVERY.md)

---

### Development note

Canonical development source อยู่ที่ `~/Projects/dev/komi-report-v5` และไม่อยู่ใน OneDrive แต่ละ OS ต้องใช้ dependency, build และ runtime ของระบบนั้นเอง การส่งให้เครื่องลูกค้าให้ใช้ Release package ที่ build และ validate สำหรับ OS นั้นเท่านั้น
