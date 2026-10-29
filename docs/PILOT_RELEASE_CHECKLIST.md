# KOMI Report V5.2.15 — Unsigned Pilot Checklist

**WAIT BUILD:** checklist นี้ยังไม่ใช่ผลทดสอบแพ็กเกจรุ่นนี้ ตรวจสถานะ source ล่าสุดจาก
`V5_2_14_WORK_PLAN.md` และทดสอบเครื่องนี้ + Proxmox VM 105 หลังได้รับอนุมัติ build เท่านั้น

เอกสารนี้ใช้กับ Pilot แบบจำกัดวงเท่านั้น ไม่ใช่ Production GO. Windows code signing และ Windows 10/11 native x64 UAT
ยังเป็น **Deferred / ยังไม่ผ่าน** และห้ามใช้ผลจาก Windows ARM VM แทนหลักฐาน native x64.

## ขอบเขต Pilot

- ระบุผู้รับผิดชอบ, เครื่องทดสอบ, เครื่องพิมพ์ที่ได้รับอนุญาต, ช่วงเวลา และ rollback owner ก่อนติดตั้ง.
- ใช้เฉพาะสำเนาฐานข้อมูล synthetic หรือข้อมูลที่เจ้าของอนุญาตชัดเจน; ห้ามส่งหรือลบ DB/CSV/log/credential/customer evidence.
- Registration/Heartbeat ต้อง fail-closed เมื่อไม่มี verified staging policy; ห้ามใช้ Production API แทน staging.
- ไม่มี Update manifest/download, forced/silent update, remote command หรือ Update telemetry ใน package นี้.

## คำเตือน Publisher ที่ต้องแจ้งผู้ทดสอบ

Installer นี้ **ไม่ได้ code-sign**. Windows อาจแสดง `Unknown publisher` หรือ `Publisher could not be verified`.
ผู้ทดสอบต้องตรวจชื่อไฟล์และ SHA256 จาก `CHECKSUMS.sha256` ให้ตรงก่อนเปิด และต้องเข้าใจว่านี่คือ Unsigned Pilot
Candidate ไม่ใช่ installer ที่ยืนยัน Publisher/Authenticode แล้ว.

## ก่อนติดตั้ง

- [ ] `PILOT_MANIFEST.json`, `RC_MANIFEST.json`, `CHECKSUMS.sha256`, `FILE_INVENTORY.json` และ `SBOM.cdx.json` อยู่ครบ
- [ ] source commit ใน manifest ตรง integration commit ที่อนุมัติ
- [ ] SHA256 ของ installer และ Pilot ZIP ตรง sidecar
- [ ] `signing` ระบุ unsigned/unverified ตามจริง และ `production_go=false`
- [ ] Phase 0 release-safety scan ไม่มี DB/CSV/XLSX/log/env/key/credential/customer evidence
- [ ] Registration runtime เป็น fail-closed/no policy artefact และ Update runtime absent
- [ ] Backup ด้วย SQLite online backup สำเร็จ, `integrity=ok`, และบันทึก critical counts ก่อนติดตั้ง

## Acceptance ระหว่าง Pilot

- [ ] Clean install/first run/restart/Tray/Auto-start/LAN Web HTTPS ผ่านในขอบเขตเครื่องทดสอบ
- [ ] Devices, Prices, History และ Billing Ledger ก่อน/หลัง restart/reinstall ตรงกัน
- [ ] Controlled printer มี authority, model/serial/slot, opening/closing timestamp และ raw provenance ครบ
- [ ] expected delta = reconciled usage = append-only ledger usage = Report/Excel totals
- [ ] ค่าใช้จ่ายใช้ price snapshot เดียวกัน; หาก completeness/safety ไม่ครบต้อง Hold และยอดเป็น 0
- [ ] Registration E2E ใช้ verified staging เท่านั้นและ cleanup/deactivate สำเร็จ หรือบันทึก HOLD พร้อม unlock condition

## Stop / HOLD criteria

หยุด Pilot ทันทีเมื่อ checksum/commit ไม่ตรง, package มี forbidden data, database integrity ไม่ใช่ `ok`, critical counts ลดลง,
Registration พยายามออก network โดยไม่มี approved staging policy, Meter provenance ไม่ครบ, Report/Excel ไม่ตรง ledger,
หรือ rollback path ใช้งานไม่ได้. ห้ามแก้ข้อมูลจริงเพื่อบังคับให้ผลผ่าน.

## Rollback

1. Exit แอปและยืนยัน process หยุด.
2. Backup/inspect สภาพปัจจุบันก่อน rollback.
3. ถอน installer เฉพาะ program files; ห้ามลบ data root หรือ OS-vault entry.
4. ติดตั้ง previous approved package แล้ว restore เฉพาะ backup ที่ `integrity=ok` และ schema รองรับ.
5. ตรวจ Devices, Prices, History, Billing Ledger, OS vault, LAN Web และ Report/Excel ซ้ำ.

ขั้นตอนคำสั่งละเอียดอยู่ใน `RELEASE_SUPPORT_AND_RECOVERY.md`.
