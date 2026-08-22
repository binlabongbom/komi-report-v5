# KOMI Report V5.1.0 — Customer Release Notes

## Package identity

ชุดส่งมอบของแต่ละ OS ต้องมี manifest, SHA256, file inventory และ CycloneDX SBOM อยู่ข้าง artifact และต้องระบุ
source commit เดียวกัน. ตรวจ `CUSTOMER_RELEASE_MANIFEST.json` ก่อนติดตั้งเสมอ; ถ้า decision เป็น `HOLD`, checksum
ไม่ตรง หรือ source commit ต่างกัน ให้หยุดและติดต่อผู้ดูแล Release.

## Production behavior

- Desktop เป็นศูนย์ควบคุม local-first สำหรับเครื่องพิมพ์สูงสุด 3 เครื่อง; Web เป็น LAN report viewer แบบ HTTPS.
- Database, logs, Web security material และ OS-vault secrets อยู่ใน data/runtime path ของผู้ใช้ ไม่ฝังใน program files.
- Registration ใช้ external approved policy/configuration และ OS vault; package ไม่มี URL/token/credential/secret ฝังอยู่.
  หาก policy หายหรือ invalid ระบบหยุดส่งแบบ fail-closed โดย Desktop local workflow ยังทำงานได้.
- ไม่มี Lab/test/demo mode, Virtual Printer auto-injection, mock/`.invalid` endpoint หรือ QA-only fallback ใน runtime payload.
- Production Phase 3 Update ไม่รวมใน V5.1.0: ไม่มี silent/forced update, remote command หรือ Update telemetry.

## Trust state

ดู signing state ใน manifest แยกตาม OS:

- macOS ต้องเป็น `developer-id-notarized-verified` และ Gatekeeper `accepted` จึงผ่าน trust gate.
- Windows ต้องเป็น Authenticode `verified` และ Publisher ที่อนุมัติจึงผ่าน trust gate.
- ad-hoc/unsigned artifact ใช้ตรวจภายในได้เมื่อ checksum ตรง แต่ยังเป็น `HOLD` สำหรับ customer release และต้องแจ้ง
  Gatekeeper/Unknown Publisher warning ตามจริง.

## Current release gate — HOLD

ชุดนี้ห้ามปล่อยลูกค้าและใช้ได้เฉพาะ authorized internal verification. Current Desktop schema v2 ส่ง
`device_inventory.devices[].serial_number` แต่ live `POST https://www.dmskm.com/api/v1/installations/register`
ตอบ HTTP 422 `VALIDATION_ERROR` เพราะ deployed schema-v2 privacy allow-list/persistence/Dashboard ยังใช้
`device_instance_id`. ห้ามแก้ Desktop ย้อนกลับ; ต้อง migrate backend boundary ไป `serial_number` โดยรักษา
forbidden-data boundary แล้ว rerun current-client live E2E จึงพิจารณาปลด HOLD ได้. Canonical production endpoint
ต้องเป็น `https://www.dmskm.com` เพราะ non-www redirect และ client ไม่ follow credential redirect โดยตั้งใจ.

## Recovery boundary

Uninstall/reinstall ลบเฉพาะ program files; ห้ามลบ Database, CSV, logs, backup, Web certificate/local secret หรือ OS-vault
entry. ก่อน upgrade/rollback ต้อง backup SQLite ด้วย online backup, ตรวจ `integrity=ok`, SHA256, schema version และ
critical counts ตาม `RELEASE_SUPPORT_AND_RECOVERY.md`.

## Deferred

Linux production, การซื้อ/สร้าง certificate และ Production Phase 3 Update อยู่นอก Release นี้. Windows ARM64 VM หรือ
x64 emulation เป็น preflight เท่านั้นและห้ามเรียก native Windows x64 UAT.
