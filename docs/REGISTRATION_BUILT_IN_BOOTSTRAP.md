# KOMI Report V5.2.4 — Registration Identity (ไม่มี Built-in Bootstrap)

> ชื่อไฟล์นี้คงไว้เพื่อไม่ให้ลิงก์เอกสารเดิมเสีย แต่ V5.2.4 **ไม่ใช้และไม่บรรจุ**
> `komi-registration-bootstrap.dat`, shared API key หรือ master key ในตัวติดตั้งแล้ว

## การทำงานของ Schema 3

1. เมื่อติดตั้งครั้งแรก Desktop สร้าง Ed25519 key pair เฉพาะ Installation ภายในเครื่องลูกค้า.
2. Private key เก็บใน macOS Keychain หรือ Windows Credential Manager และห้ามส่งออกจากเครื่อง.
3. Registration ส่งเฉพาะ public key, proof ที่เซ็นด้วย private key และข้อมูลตาม allow-list ของ
   contract V5.2.4.
4. Host ตรวจ proof แล้วออก scoped installation token; token เก็บใน OS vault เช่นกัน.
5. Status และ Meter ใช้ installation token ตามขอบเขตที่กำหนด. ไม่มี key กลางที่ลูกค้าหลายรายใช้ร่วมกัน.

Contract identity ที่ต้องตรงกันทุก artifact และทุกหลักฐานคือ:

- Contract version: `v5.2-shared-2026-08-25-r2`
- Contract SHA-256: `4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd`

## Security boundary

- ห้ามฝัง shared/master bootstrap key, private key, token หรือ customer payload ใน EXE/APP/manifest/log.
- Registration payload ต้องใช้ allow-list; ห้ามส่ง IP, MAC, hostname, Credential, User/Account,
  Document, Print Job, raw SNMP/XML, raw error หรือ application log.
- หาก OS vault, signature verification หรือ API contract ใช้ไม่ได้ ให้หยุดส่งแบบ fail-closed โดยไม่ลบ
  Database, History, Billing หรือ Excel ภายในเครื่อง.
- Offline License เป็น no-send gate: เมื่อใช้งานโหมด Offline ต้องไม่ส่ง Registration, Status หรือ Meter.

## Joint Staging E2E evidence สำหรับ Packaging

ตัว Builder รับไฟล์ JSON ผ่าน `--joint-e2e-evidence`. ไฟล์นี้เป็นเพียงสรุปผลทดสอบที่ผ่านการ sanitize
ไม่ใช่ credential และไม่ถูกบรรจุ raw file ลงตัวติดตั้ง. ต้องระบุ identity ตรงกับ version, source commit และ
contract ข้างต้น พร้อมผล boolean ต่อไปนี้:

- `joint_e2e_passed`
- `dashboard_readback_passed`
- `cleanup_deactivate_passed`

ถ้าไม่ส่งไฟล์นี้ Builder ยังสร้าง **unsigned HOLD candidate** สำหรับตรวจภายในได้ แต่ manifest ต้องระบุ
`verified=false`, `release_decision=HOLD` และ `production_go=false`. หากส่งไฟล์ผิดรูปแบบหรือ identity ไม่ตรง
Builder ต้องหยุดทันทีและห้ามลดระดับเป็น warning.
