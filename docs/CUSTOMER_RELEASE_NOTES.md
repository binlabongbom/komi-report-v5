# KOMI Report V5.2.9 — Customer Release Notes

## Package identity

ชุดส่งมอบของแต่ละ OS ต้องมี manifest, SHA-256, file inventory และ CycloneDX SBOM อยู่ข้าง artifact
โดยอ้าง source commit และ shared contract เดียวกัน:

- Contract version: `v5.2-shared-2026-08-25-r2`
- Contract SHA-256: `4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd`

ตรวจ `MACOS_MANIFEST.json`, `WINDOWS_MANIFEST.json` และ `CUSTOMER_RELEASE_MANIFEST.json` ก่อนส่งมอบ.
ถ้า checksum หรือ contract identity ไม่ตรง Builder/Assembler ต้องหยุด. ถ้า decision เป็น `HOLD` ห้ามเรียก
artifact ว่า Production Ready.

## V5.2.9 cleanup — Mac validation candidate

- Users and Printers use six compact two-line cards, separating color/B&W Print and Copy. Unknown subject breakdowns remain unavailable instead of being inferred from totals.
- Removed 16 unreferenced legacy helpers and unused imports/styles. Deferred pyqtgraph/NumPy loading until Reports constructs its legacy graph; existing export and audit paths remain supported.
- Windows builder excludes reviewed NumPy/pyqtgraph test-suite directories while preserving runtime helpers, Qt plugins and Web functionality. Actual package savings require the next Windows build.
- Mac native navigation verified; Windows build/UAT pending. Existing Windows Shell AppUserModelID mismatch between installer and runtime remains tracked for the Windows stage; no installer identity change in this cleanup.

## Runtime behavior

- V5.2.9 คืนชื่อ User/Account จาก RAM Meter export แบบ cache แล้วแสดงตาราง Users แยกตาม Slot และประเภท Counter โดยไม่ตัดหัวคอลัมน์.
- Usage มี checkbox เลือก Slot สำหรับยอดรวมและกราฟ, ตารางตามเครื่องใช้หัว 3 ชั้น และ Legacy แสดง `—` เมื่อเครื่องไม่ระบุประเภทงาน.
- Setup Wizard ไปขั้นถัดไปอัตโนมัติเมื่อทุกเครื่องผ่าน SNMP + Web; หน้า Reports โหลดเฉพาะแท็บที่เปิดเพื่อลดการค้างบนฐานข้อมูลขนาดใหญ่.
- V5.2.9 บรรจุภาพประกอบคู่มือภายในแอปครบถ้วนทั้ง Windows และ macOS เพื่อไม่ให้หน้า
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
- Production Phase 3 Update ไม่รวมใน V5.2.9: ไม่มี silent/forced update, remote command หรือ Update telemetry.

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
