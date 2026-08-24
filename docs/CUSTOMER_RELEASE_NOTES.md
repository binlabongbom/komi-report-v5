# KOMI Report V5.1.0 — Customer Release Notes

## Package identity

ชุดส่งมอบของแต่ละ OS ต้องมี manifest, SHA256, file inventory และ CycloneDX SBOM อยู่ข้าง artifact และต้องระบุ
source commit เดียวกัน. ตรวจ `CUSTOMER_RELEASE_MANIFEST.json` ก่อนติดตั้งเสมอ; ถ้า decision เป็น `HOLD`, checksum
ไม่ตรง หรือ source commit ต่างกัน ให้หยุดและติดต่อผู้ดูแล Release.

## Production behavior

- Desktop เป็นศูนย์ควบคุม local-first สำหรับเครื่องพิมพ์สูงสุด 3 เครื่อง; Web เป็น LAN report viewer แบบ HTTPS.
- Database, logs, Web security material และ scoped installation token อยู่ใน data/runtime path หรือ OS vault ของผู้ใช้.
- Registration ใช้ Production policy ภายในโปรแกรมที่ชี้ไป canonical `https://www.dmskm.com`. Customer installer มี limited
  bootstrap identifier สำหรับย้ายเข้า macOS Keychain/Windows Credential Manager ตอนเปิดครั้งแรก. ค่านี้ถือว่าอ่านออกจาก
  installer ได้และห้าม Server ให้สิทธิ์ Dashboard, delete, Update หรือ remote command; Server ต้องแลกเป็น scoped token ของ
  Installation. หาก OS vault หรือ API contract ใช้ไม่ได้ ระบบหยุดส่งแบบ fail-closed โดย local workflow ยังทำงานได้.
- ไม่มี Lab/test/demo mode, Virtual Printer auto-injection, mock/`.invalid` endpoint หรือ QA-only fallback ใน runtime payload.
- Production Phase 3 Update ไม่รวมใน V5.1.0: ไม่มี silent/forced update, remote command หรือ Update telemetry.

## Trust state

ดู signing state ใน manifest แยกตาม OS:

- macOS ต้องเป็น `developer-id-notarized-verified` และ Gatekeeper `accepted` จึงผ่าน trust gate.
- Windows ต้องเป็น Authenticode `verified` และ Publisher ที่อนุมัติจึงผ่าน trust gate.
- Windows customer shortcut เปิดผ่าน hidden launcher; `START_DEBUG.cmd` ไม่ถูกใช้ใน flow ปกติและสงวนไว้สำหรับ Support.
- ad-hoc/unsigned artifact ใช้ตรวจภายในได้เมื่อ checksum ตรง แต่ยังเป็น `HOLD` สำหรับ customer release และต้องแจ้ง
  Gatekeeper/Unknown Publisher warning ตามจริง.

## Current release gate — HOLD

ชุดนี้ห้ามปล่อยลูกค้าและใช้ได้เฉพาะ authorized internal verification. Current Desktop schema v2 ส่ง
`device_inventory.devices[].serial_number` แต่ live `POST https://www.dmskm.com/api/v1/installations/register`
ตอบ HTTP 422 `VALIDATION_ERROR` เพราะ deployed schema-v2 privacy allow-list ยังไม่รับ
`serial_number`. ห้ามแก้ Desktop ย้อนกลับไปใช้ `device_instance_id`; ต้อง migrate backend boundary ไป `serial_number` โดยรักษา
forbidden-data boundary แล้ว rerun current-client live E2E จึงพิจารณาปลด HOLD ได้. Canonical production endpoint
ต้องเป็น `https://www.dmskm.com` เพราะ non-www redirect และ client ไม่ follow credential redirect โดยตั้งใจ.

## Recovery boundary

Uninstall/reinstall ลบเฉพาะ program files; ห้ามลบ Database, CSV, logs, backup, Web certificate/local secret หรือ OS-vault
entry. ก่อน upgrade/rollback ต้อง backup SQLite ด้วย online backup, ตรวจ `integrity=ok`, SHA256, schema version และ
critical counts ตาม `RELEASE_SUPPORT_AND_RECOVERY.md`.

## Deferred

Linux production, การซื้อ/สร้าง certificate และ Production Phase 3 Update อยู่นอก Release นี้. Windows ARM64 VM หรือ
x64 emulation เป็น preflight เท่านั้นและห้ามเรียก native Windows x64 UAT.
