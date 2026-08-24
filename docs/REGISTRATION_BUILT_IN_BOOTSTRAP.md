# KOMI Report V5.1 — Built-in Registration Bootstrap

## เป้าหมาย

ลูกค้าติดตั้งโปรแกรมแล้วใช้งานได้โดยไม่ต้องรับไฟล์ API config หรือกรอกรหัส Registration เอง. แอปมี Production policy ที่ชี้ไป `https://www.dmskm.com` และแสดงประกาศ `KOMI-REG-2026-08-24` ใน Setup/Settings.

## การทำงาน

1. Customer build รับ bootstrap เดิมจากช่องทาง OS vault ที่อนุญาต ณ เวลา build; ค่าไม่ถูกเขียนลง Git, manifest, checksum output หรือ log.
2. Installer บรรจุค่าในชื่อ resource คงที่ `komi-registration-bootstrap.dat`.
3. เมื่อเปิดแอปหลัง Setup โปรแกรมตรวจ OS vault ก่อน ถ้ามีค่าเดิมจะไม่ overwrite.
4. ถ้ายังไม่มี โปรแกรมอ่าน resource แล้วบันทึกที่ `KOMI Report V5 Registration Credentials / registration-bootstrap-reference` ใน macOS Keychain หรือ Windows Credential Manager.
5. Register สำเร็จแล้ว Server ต้องออก scoped installation token; token นี้อยู่ใน OS vault และ SQLite เก็บเฉพาะ reference.

## Security boundary

bootstrap ที่มากับ installer ถือเป็น **limited public bootstrap identifier** เพราะผู้รับ installer สามารถ extract ได้ จึงต้องไม่มีสิทธิ์ Admin/Dashboard, อ่านรายการลูกค้ารายอื่น, delete/deactivate, Update, remote command หรือเข้าถึงฐานข้อมูล. Server ต้องใช้ payload allow-list, rate limit, idempotency และออก token แยกต่อ Installation.

ห้ามบันทึก IP, MAC, hostname, Credential, Meter/Counter, User/Account, Document หรือ Application log ใน Registration payload. หาก bootstrap/OS vault/API ไม่พร้อม Registration จะ fail-closed แต่ Setup, Meter, Billing, Report และ Excel ภายในเครื่องยังทำงาน.

## Live contract evidence — 2026-08-24

Desktop built-in policy และ bootstrap เดิมเข้าถึง canonical endpoint ได้ แต่ current schema-v2 request ตอบ `HTTP 422 VALIDATION_ERROR`: `device_inventory.devices.0.serial_number` is not accepted by the deployed privacy allow-list. จึงยังห้ามเรียก Registration ว่า Production-ready.

ปลด blocker เมื่อ API deploy allow-list/persistence/Dashboard ที่รับ `serial_number` แล้ว rerun current Desktop register, idempotent replay, heartbeat, Dashboard read-back และ deactivate/cleanup สำเร็จ.
