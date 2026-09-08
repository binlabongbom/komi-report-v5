# KOMI Report V5.2.10 — คู่มือติดตั้ง ย้ายเครื่อง และกู้คืนข้อมูล

## สถานะชุดติดตั้ง

ชุดติดตั้ง V5.2.10 ตามคู่มือนี้เป็น **UNSIGNED INSTALLATION CANDIDATE** สำหรับการติดตั้งที่ลูกค้าและผู้ดูแลระบบยอมรับสถานะ Unknown Publisher/ไม่ notarized แล้วเท่านั้น ไม่ใช่หลักฐานว่า Microsoft หรือ Apple รับรอง Publisher

ค่า SHA-256 ใช้ยืนยันว่าไฟล์ที่ได้รับตรงกับไฟล์ที่ผู้ส่งมอบจัดทำและไม่เสียหายระหว่างส่ง แต่ไม่สามารถแทน Digital Signature, Authenticode, Developer ID หรือการตรวจ Malware ได้

## ก่อนติดตั้ง

1. รับไฟล์ติดตั้งและ `CHECKSUMS.sha256` จากผู้ส่งมอบผ่านช่องทางที่เชื่อถือได้
2. ตรวจ SHA-256 ให้ตรงกับ `CHECKSUMS.sha256` ทุกตัวอักษรก่อนเปิดไฟล์ หากไม่ตรงให้หยุดและขอไฟล์ใหม่
3. หากมีโปรแกรมเดิม ให้เลือก Exit จาก System Tray/Menu Bar ก่อน
4. สำรอง Database เดิม ตรวจความสมบูรณ์ และจด Database Path ที่ใช้งานอยู่
5. เตรียมชื่อบริษัท IP ของเครื่องพิมพ์ และสิทธิ์ Administrator ของเครื่องพิมพ์เฉพาะกรณีที่โปรแกรมร้องขอ

## Windows

ตรวจ Hash ใน PowerShell โดยเปลี่ยนชื่อไฟล์ให้ตรงกับไฟล์ที่ได้รับ:

```powershell
Get-FileHash .\KOMI_Report_V5_2_10_Windows_x64_Installer.exe -Algorithm SHA256
```

1. ตรวจว่าค่า Hash ตรงกับ `CHECKSUMS.sha256`
2. เปิดตัวติดตั้ง `.exe` และติดตั้งแบบ per-user
3. ชุดติดตั้ง unsigned อาจแสดง **Unknown Publisher** หรือ Microsoft Defender SmartScreen
4. ถ้าหน้าต่างมี **More info → Run anyway** ให้ใช้ได้เฉพาะเมื่อรับไฟล์จากผู้ส่งมอบที่เชื่อถือได้และ SHA-256 ตรงเท่านั้น
5. Smart App Control หรือ App Control Policy ขององค์กรอาจบล็อกโดยไม่มีปุ่ม Run anyway ในกรณีนี้ให้หยุดติดตั้งและให้ฝ่าย IT ตรวจ/อนุญาต Artifact ที่มี SHA-256 ตรง ห้ามปิด Defender, Smart App Control หรือแก้ Policy เพื่อหลบการตรวจ
6. เปิด KOMI Report V5.2.10 จาก Start Menu หรือ Desktop shortcut
7. ทำ Setup Wizard ตามหัวข้อ Primary หรือ Secondary ใน `CUSTOMER_GUIDE_V5_2.md`
8. ตรวจหน้าอุปกรณ์ด้วยปุ่ม **อ่านข้อมูลตอนนี้**
9. ตรวจ Web Report จาก URL ใน Settings → การตั้งค่าขั้นสูง → รายงานผ่าน LAN
10. Restart Windows แล้วตรวจว่า Database, Auto-start, System Tray และ Web Report ยังใช้ค่าเดิม

การเปิดปกติไม่ควรมี Command Prompt/Terminal ค้างอยู่ หากต้องการข้อมูลสำหรับ Support ให้ใช้ปุ่มส่งออก Log ในการตั้งค่าขั้นสูง

## macOS

ตรวจ Hash ใน Terminal โดยเปลี่ยน path/ชื่อไฟล์ให้ตรงกับไฟล์ที่ได้รับ:

```bash
shasum -a 256 "/path/to/KOMI_Report_V5_2_10_macOS.dmg"
```

1. ตรวจว่าค่า Hash ตรงกับ `CHECKSUMS.sha256`
2. เปิด DMG แล้วลาก KOMI Report V5.2.10 ไป Applications
3. ชุดติดตั้ง unsigned/not notarized อาจถูก Gatekeeper ปฏิเสธ และไม่รับประกันว่าจะมีปุ่ม Open Anyway
4. หาก macOS หรือนโยบายองค์กรปฏิเสธ ให้หยุดติดตั้งและส่ง Hash/ข้อความแจ้งเตือนให้ผู้ส่งมอบหรือฝ่าย IT ตรวจ ห้ามปิด Gatekeeper, ใช้คำสั่งลบ quarantine หรือแก้ Policy เพื่อหลบการตรวจ
5. เมื่อระบบอนุญาตตามนโยบายแล้ว ให้เปิดแอปและทำ Setup Wizard
6. ตรวจหน้าอุปกรณ์ Web Report และ System Tray/Menu Bar
7. Restart macOS แล้วตรวจว่า Database และค่าต่างๆ ยังอยู่

## ย้าย Database Path

1. เปิด Settings → การตั้งค่าขั้นสูง
2. สร้าง Backup และตรวจความสมบูรณ์ก่อน
3. เลือกเปลี่ยน Path โปรแกรมจะสร้างสำเนาที่ตรวจสอบแล้วและใช้เมื่อเปิดครั้งถัดไป
4. ปิดโปรแกรมด้วย Exit แล้วเปิดใหม่
5. ตรวจ Path ใหม่ จำนวนเครื่อง ราคา ประวัติ และรายงาน

Database ที่กำลังใช้จะไม่ถูกเขียนทับระหว่างการเตรียม Path ใหม่

## Restore จาก Backup

1. Exit โปรแกรมให้หยุดสนิท
2. เปิดโปรแกรมอีกครั้ง แล้วไป Settings → การตั้งค่าขั้นสูง
3. เลือก Backup ที่ต้องการและอ่านคำเตือน
4. โปรแกรมจะตรวจ integrity และเตรียมใช้สำเนาที่เลือกเมื่อเปิดครั้งถัดไป
5. เปิดโปรแกรมใหม่และตรวจ Devices, Prices, Reports และ Billing

## ถอนและติดตั้งใหม่

การถอนโปรแกรมไม่ควรลบ Database, Backup และค่าที่เก็บใน OS vault หากต้องการลบข้อมูลลูกค้า ต้องทำเป็นงานแยกหลัง Backup และได้รับอนุญาต

1. Exit โปรแกรมและ Backup Database
2. ถอนโปรแกรม
3. ติดตั้ง V5.2.10 ใหม่
4. เลือก Database เดิมหรือ Import ใน Wizard
5. ตรวจเครื่องพิมพ์ ราคา ประวัติ รายงาน Auto-start และ Web Report

## การขอความช่วยเหลือ

เปิด Settings → การตั้งค่าขั้นสูง → โปรแกรม Log และการบำรุงรักษา แล้วเลือก **ส่งออก Log สำหรับ Support** ชุด Support ไม่ควรมีรหัสผ่านหรือ Token แบบอ่านได้

เมื่อแจ้งปัญหาการติดตั้ง ให้ส่งเฉพาะชื่อไฟล์, SHA-256, Version ของ OS, ข้อความแจ้งเตือน และภาพหน้าจอที่ไม่มีข้อมูลลูกค้า ห้ามส่งรหัสผ่าน, `.komilicense`, `.komirequest`, Token หรือ Database ทางแชตทั่วไป
