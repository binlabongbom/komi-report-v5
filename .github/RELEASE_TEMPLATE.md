# KOMI Report {{VERSION}}

> Windows x64 release

## Download

ดาวน์โหลด installer จาก **Assets** ด้านล่างของ Release นี้

ไฟล์หลัก:

- `KOMI_Report_{{VERSION_FILE}}_Windows_x64_Installer.exe`
- `INSTALLER.sha256`
- `RELEASE_INFO.json`

> หาก installer ยังไม่ได้ code signing ให้ตรวจ SHA-256 กับ `INSTALLER.sha256` ก่อนติดตั้ง และปฏิบัติตาม Customer Installation Guide

## What's New

### New

- {{CUSTOMER_VISIBLE_NEW_FEATURE}}

### Improved

- {{CUSTOMER_VISIBLE_IMPROVEMENT}}

### Fixed

- {{CUSTOMER_VISIBLE_FIX}}

## Quick Start

### New installation

1. Download installer และ `INSTALLER.sha256`
2. ตรวจ SHA-256
3. Run installer
4. เปิด KOMI Report
5. ทำ First-run Wizard
6. เลือกเครื่องพิมพ์สูงสุด 3 เครื่อง
7. ตรวจ Model / Serial Number / Web Connection
8. ตั้งราคา รอบบิล และตำแหน่งเครื่อง
9. ทำ Online Registration
10. เปิด **อุปกรณ์ → อ่านข้อมูลตอนนี้** เพื่อตรวจการเชื่อมต่อ

### Existing installation / Upgrade

1. Backup Database ก่อน Upgrade
2. อ่านหัวข้อ **Upgrade Notes** ด้านล่าง
3. Download และตรวจ SHA-256
4. ติดตั้ง version ใหม่ตาม Installation Guide
5. เปิดโปรแกรมและตรวจ Database / Registration
6. ทดสอบ **อ่านข้อมูลตอนนี้** อย่างน้อย 1 รอบ
7. ตรวจ Reports และ Excel Export

## Example Usage

### ตรวจ Meter และสถานะเครื่อง

**อุปกรณ์ → อ่านข้อมูลตอนนี้**

ใช้ตรวจ Total Meter, Toner, Paper Tray และ Counter ที่เครื่องรุ่นนั้นรองรับ

### ดูยอดใช้งาน

**รายงาน → Overview**

กำหนดช่วงวันที่เพื่อดู Print/Copy, Color/BW, ยอดรวม ค่าใช้จ่าย และแนวโน้ม

### วิเคราะห์ตาม User / Account

**รายงาน → Users**

ข้อมูลจะแสดงเมื่อเครื่องพิมพ์เปิด User Authentication หรือ Account Track และส่งข้อมูลดังกล่าวมา

### Export Excel

**รายงาน → ส่งออก Excel**

ไฟล์มี 6 sheets: การใช้งานรายเครื่อง, มุมมองผู้ใช้, มุมมองรายวัน และ Legacy อีก 3 มุมมอง

### ดูรายงานจากเครื่องอื่นใน LAN

เปิด **การตั้งค่าขั้นสูง → Web Report**

ใช้ read-only without password เฉพาะ Trusted LAN และห้าม expose ออก Public Internet

## Upgrade Notes

- {{DATABASE_MIGRATION_OR_NONE}}
- {{BREAKING_CHANGE_OR_NONE}}
- {{SPECIAL_ACTION_OR_NONE}}

## Known Issues

- {{KNOWN_ISSUE_OR_NONE}}

## Documentation

- [User Guide](../../blob/main/docs/CUSTOMER_GUIDE_V5_2.md)
- [Installation Guide](../../blob/main/docs/CUSTOMER_INSTALL_GUIDE.md)
- [Customer Release Notes](../../blob/main/docs/CUSTOMER_RELEASE_NOTES.md)

## Support

เมื่อแจ้งปัญหา กรุณาแนบ KOMI Report version, Windows version, Printer model/Serial Number, ขั้นตอนที่ทำให้เกิดปัญหา, screenshot และ log ที่เกี่ยวข้อง

---

### Build Information

<details>
<summary>Technical build details</summary>

- Source: `main @ {{COMMIT_SHA}}`
- Target: Windows x64
- Runtime: {{RUNTIME}}
- Validation: {{VALIDATION_SUMMARY}}

</details>
