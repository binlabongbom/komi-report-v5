# KOMI Report V5.2.13 — Customer Release Notes

## รุ่น 5.2.13 — แก้การอ่าน Public Counter หลัง JSON endpoint ตอบ 404

- เมื่อ JSON endpoint ตอบ 404 จะใช้ Public Counter XML เดิมได้เฉพาะเมื่อหน้า Web Connection ระบุลิงก์ endpoint นั้นเอง และต้องตรวจพบ aggregate Total Meter ที่ถูกต้อง
- ใช้ session, scheme และ TLS policy เดิม ไม่เดา model profile, ลองรหัสเพิ่ม, ลดระดับ TLS หรือเขียน settings ของเครื่องพิมพ์
- แยกคำแนะนำ 404 ของเครื่องพิมพ์ออกจาก Host API พร้อมแสดง profile/protocol ใน Setup diagnostic
- หากหน้าเครื่องไม่ระบุ endpoint ที่รองรับ จะหยุดและขอหลักฐานจากหน้า Counter ปกติ ไม่อ้างว่า firmware ไม่รองรับ
- ยังไม่มีผลยืนยันจากเครื่องรุ่นที่ผู้ใช้รายงาน; ต้องตรวจ Counter endpoint และยอดจริงก่อนยืนยัน compatibility
- ชุด Windows เป็น unsigned HOLD candidate; ไม่มี production approval, clean-machine installation หรือ live-printer acceptance จากการ build นี้


## รุ่น 5.2.12 — ปรับปรุงวันที่ 25 กันยายน 2026

- Reports จำกัดช่วง preview สูงสุด 12 เดือน และให้เลือกข้อมูลที่จะส่งออก Excel สำหรับประวัติระยะยาว
- Users ใช้ตารางเต็มพื้นที่ พร้อมมุมมองภาพรวม/รายเครื่อง แยก A4/A3 และค่าใช้จ่าย
- ตัวเลือก Public User รวมยอดเครื่องที่ไม่มีข้อมูลแยกผู้ใช้เป็นหนึ่งแถว โดยมุมมองรายเครื่องยังแยกคอลัมน์ Slot และไม่รวมยอดซ้ำกับผู้ใช้จริง
- รักษาชื่อผู้ใช้จริงเมื่อเครื่องส่งชื่อเป็นรหัสตัวเลข และรวมชื่อเดียวกันข้ามเครื่องใน Desktop, Web และ Excel
- Wizard เพิ่มขั้นมิเตอร์เริ่มต้นระหว่างเครื่องพิมพ์กับราคา รองรับการดูทั้งสามเครื่อง และใช้ฐานเดิมต่อสำหรับการอัปเกรด
- แก้การเริ่มอ่านเครื่องที่เพิ่มใหม่และการอ่านต่อจากมิเตอร์ตั้งต้น พร้อมปรับการเตรียมข้อมูลรายงานและ cache
- หน้าแรกเริ่มที่วันนี้ และกราฟแนวโน้มแสดงยอดรายวันย้อนหลัง 14 วันรวมวันนี้
- ปรับการแยกประเภทรายงาน ราคาและวันเปลี่ยนราคา รวมถึงการจัดวางกราฟ คำอธิบายและตาราง

ตัวติดตั้ง Windows ใช้โปรไฟล์ customer-production-behavior; source commit, checksum,
ผล build และสถานะลายเซ็นของไฟล์แต่ละชุดระบุใน `WINDOWS_MANIFEST.json`
สถานะการลงลายเซ็นและการทดสอบกับ Host ต้องอ่านจากหลักฐานของชุด build นั้น ไม่อนุมานจากชื่อไฟล์ตัวติดตั้ง
ไม่เปลี่ยน Host ในรุ่นนี้ สถานะปัจจุบันและข้อจำกัดอยู่ใน `V5_2_12_WORK_PLAN.md`
คู่มือ UI ปัจจุบันคือ `CUSTOMER_GUIDE_V5_2_12_DRAFT.md` และ PDF ที่อยู่ใน `customer-guide`

- เพิ่มการตรวจแก้การแบ่งยอดรายวันจากหลักฐาน Web โดยเก็บบัญชีต้นฉบับและไม่บวกยอดซ้ำ
- เพิ่มหมายเหตุฉบับแก้ไขในรายงาน Desktop, Excel และคำตอบ API รายงานภายในโปรแกรม
- ผู้อ่านร่วมมีการจองตั้งแต่ SNMP การรวมคำขอ Web และการกู้คำขอหมดเวลาแบบจำกัดครั้งใน source
- หน้าการตั้งค่าเครือข่ายแสดงผู้ประสาน/ผู้อ่านและสถานะงานที่รับล่าสุด
- การเปิดใช้ Sync หลายคอมยังขาด verified member/HTTPS provider ของ Host เดิม
  ผลทดสอบ source จำลองไม่ใช่หลักฐานว่าการติดตั้งหลายคอมจริงผ่าน

รายการรุ่นก่อนด้านล่างเป็นประวัติ ไม่ใช้รับรองการทดสอบรุ่นนี้

## Package identity

ชุดส่งมอบของแต่ละ OS ต้องมี manifest, SHA-256, file inventory และ CycloneDX SBOM อยู่ข้าง artifact
โดยอ้าง source commit และ shared contract เดียวกัน:

- Contract version: `v5.2-shared-2026-08-25-r2`
- Contract SHA-256: `4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd`

ตรวจ `MACOS_MANIFEST.json`, `WINDOWS_MANIFEST.json` และ `CUSTOMER_RELEASE_MANIFEST.json` ก่อนส่งมอบ.
ถ้า checksum หรือ contract identity ไม่ตรง Builder/Assembler ต้องหยุด. ถ้า decision เป็น `HOLD` ห้ามเรียก
artifact ว่า Production Ready.

## V5.2.11 cleanup — Mac validation candidate

- Users and Printers use six compact two-line cards, separating color/B&W Print and Copy. Unknown subject breakdowns remain unavailable instead of being inferred from totals.
- Removed 16 unreferenced legacy helpers and unused imports/styles. Deferred pyqtgraph/NumPy loading until Reports constructs its legacy graph; existing export and audit paths remain supported.
- Windows builder excludes reviewed NumPy/pyqtgraph test-suite directories while preserving runtime helpers, Qt plugins and Web functionality. Actual package savings require the next Windows build.
- Mac native navigation verified; Windows build/UAT pending. Existing Windows Shell AppUserModelID mismatch between installer and runtime remains tracked for the Windows stage; no installer identity change in this cleanup.

## Runtime behavior

- V5.2.11 คืนชื่อ User/Account จาก RAM Meter export แบบ cache แล้วแสดงตาราง Users แยกตาม Slot และประเภท Counter โดยไม่ตัดหัวคอลัมน์.
- Usage มี checkbox เลือก Slot สำหรับยอดรวมและกราฟ, ตารางตามเครื่องใช้หัว 3 ชั้น และ Legacy แสดง `—` เมื่อเครื่องไม่ระบุประเภทงาน.
- Setup Wizard ไปขั้นถัดไปอัตโนมัติเมื่อทุกเครื่องผ่าน SNMP + Web; หน้า Reports โหลดเฉพาะแท็บที่เปิดเพื่อลดการค้างบนฐานข้อมูลขนาดใหญ่.
- V5.2.11 บรรจุภาพประกอบคู่มือภายในแอปครบถ้วนทั้ง Windows และ macOS เพื่อไม่ให้หน้า
  คู่มือแสดงพื้นที่ว่างหรือข้อความว่าไม่พบภาพประกอบหลังติดตั้งจริง.
- ช่องเลือกช่วงวันที่ในหน้า Report เปิดปฏิทินเมื่อคลิกได้ทั้งช่อง และไม่รับการพิมพ์วันที่โดยตรง
  เพื่อลดวันที่ผิดรูปแบบ.
- ซ่อน Offline Activation ออกจาก Setup Wizard และ Settings ชั่วคราว โดยคง Online Registration
  เป็นขั้นตอนมาตรฐาน; local Database, Meter, Billing, Report และ Excel ไม่ถูกลบหรือเปลี่ยนความหมาย.
- สืบทอดจาก V5.2.3: แยกกรณี Legacy Administrator session ถูกใช้งานออกจากกรณีรหัสผ่านผิด
  โปรแกรมจะไม่สั่ง Logout session ของผู้ใช้อื่น และจะแสดงปุ่มเปิด Web Connection
  เพื่อให้ผู้ใช้ Logout ก่อนตรวจสอบใหม่; จะขอรหัสผ่านเฉพาะเมื่อเครื่องปฏิเสธรหัสจริง.
- สืบทอดการแก้การเชื่อมต่อ Web Connection ของเครื่อง Legacy บน Windows ที่ใช้
  OpenSSL legacy renegotiation โดยเปิด compatibility option เฉพาะ device profile ที่ระบุ
  `TLS11_LEGACY`; เครื่อง Modern และ TLS policy ส่วนกลางไม่ถูกลดระดับ.
- TLS handshake/certificate failure ถูกแยกจาก authentication failure ชัดเจน จึงไม่แสดง
  “ต้องใส่รหัส” เมื่อรหัสยังไม่ได้ถูกตรวจจริง.
- Desktop เป็นศูนย์ควบคุม local-first สำหรับเครื่องพิมพ์สูงสุด 3 เครื่อง; Web เป็น LAN report viewer แบบ HTTPS.
- Database, logs, Web security material, Ed25519 private key และ scoped installation token อยู่ใน data/runtime
  path หรือ OS vault ของเครื่องลูกค้า ไม่อยู่ในโฟลเดอร์ติดตั้งหรือ manifest.
- Registration ใช้ schema 3 Ed25519 public-client. แต่ละ Installation สร้าง key pair ของตนเองและไม่มี
  shared/master bootstrap key หรือ `komi-registration-bootstrap.dat` ฝังใน EXE/APP.
- หาก OS vault หรือ API contract ใช้ไม่ได้ ระบบหยุดส่งแบบ fail-closed โดย local Meter, Billing, Report และ
  Excel ยังคงทำงานตามข้อมูลในเครื่อง.
- ไม่มี Lab/test/demo mode, Virtual Printer auto-injection, mock/`.invalid` endpoint หรือ QA fallback ใน runtime.
- Production Phase 3 Update ไม่รวมใน V5.2.11: ไม่มี silent/forced update, remote command หรือ Update telemetry.

## Evidence และ Trust state

- Builder รับ sanitized Joint Desktop-Staging E2E JSON ผ่าน `--joint-e2e-evidence` และตรวจ product version,
  source commit, contract version/hash, Dashboard read-back และ cleanup/deactivate แบบ fail-closed.
- ไม่มีไฟล์ Joint E2E ยังสร้าง unsigned candidate สำหรับตรวจภายในได้ แต่ต้องแสดง blocker ใน manifest.
- macOS ต้องเป็น `developer-id-notarized-verified` และ Gatekeeper `accepted` จึงผ่าน trust gate.
- Windows ต้องเป็น Authenticode `verified` และมี native Windows x64 UAT จึงผ่าน trust gate.
- Windows ARM64 VM หรือ x64 emulation เป็น preflight เท่านั้น ไม่ใช่ native Windows x64 evidence.
- ad-hoc/unsigned artifact ใช้ตรวจภายในได้เมื่อ checksum ตรง แต่ยังเป็น `HOLD` และต้องแจ้ง
  Gatekeeper/Unknown Publisher warning ตามจริง.

Packaging ชุดนี้ไม่อนุญาตให้ตัวเองประกาศ Production GO แม้ evidence รายการย่อยจะครบ:
`release_decision` ต้องเป็น `HOLD` และ `production_go=false` จนกว่าจะมี external release approval ที่ตรวจสอบได้.

## Recovery boundary

Uninstall/reinstall ลบเฉพาะ program files; ห้ามลบ Database, CSV, logs, backup, Web certificate/local secret หรือ
OS-vault entry. ก่อน upgrade/rollback ต้อง backup SQLite ด้วย online backup, ตรวจ `integrity=ok`, SHA-256,
schema version และ critical counts ตาม `RELEASE_SUPPORT_AND_RECOVERY.md`.

## Deferred

Linux production, การซื้อ/สร้าง signing certificate และ Production Phase 3 Update อยู่นอก Release นี้.


### V5.2.9 — LAN follow-up

- การเปิด/ปิดรายงานโดยไม่ใช้รหัสมีผลกับ Web service ของตัวติดตั้งทันทีหลังบันทึก; หน้า Login เดิมกลับไปหน้ารายงานเมื่อเปิดโหมดนี้
- ผู้ดูแลยังเข้าสู่ระบบผ่านปุ่ม “เข้าสู่ระบบผู้ดูแล” ได้
- ตั้ง Port สำหรับ HTTPS Web Report ได้ (1024–65535 ยกเว้น3001/8766); ใช้ IP:Port เดียวกันที่เครื่องอื่น
- Secondary เลือก Port ของ Primary ได้ทั้งค้นหาอัตโนมัติและระบุ IP
- อนุญาต Secondary Sync ได้แบบปิด, เปิด5นาที หรือเปิดตลอดและจำค่าหลังเปิดโปรแกรมใหม่; การเปิดตลอดมีผลขณะที่โปรแกรมและ Web service ทำงาน


### V5.2.11 — Reports staged loading

- เตรียมโครง Overview ระหว่าง Splash แล้วอ่านข้อมูลเบื้องหลัง
- ทยอยเตรียม Users/Printers หลังหน้าต่างหลักแสดง และ Usage เมื่อเปิด Reports
- Legacy สร้างเมื่อเลือกใช้ การ์ดขึ้นก่อนตารางและกราฟ
- แสดงสถานะระหว่างโหลด พร้อมลองใหม่เมื่อช้า/ผิดพลาด และเก็บข้อมูลเดิมระหว่างรีเฟรช
- ป้องกันผลลัพธ์เก่าทับแท็บหรือช่วงวันที่ที่เลือกใหม่
