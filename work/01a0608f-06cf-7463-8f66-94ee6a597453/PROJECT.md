---
project_name: KOMI Report V5
thread_title: "แก้พฤติกรรม KOMI Report V5.2.5 เมื่อ Host deactive installation"
status: ready_for_native_uat
updated_at: 2026-09-02
dashboard_visible: false
---

# KOMI Report V5.2.5 — Deactivated Installation History Mode

## Goal

เมื่อ Host deactive installation แอป Desktop เปิด workspace และอ่าน Report, User, Usage, History เดิมได้ แต่ห้ามเริ่ม SNMP/Web device polling หรือสร้าง reading/meter telemetry ใหม่ จน Host activate กลับ

## Scope and design

- Setup gate ตัดสินจาก local device/company setup เท่านั้น ไม่ผูกกับ Registration eligibility
- Polling coordinator มี temporary pause/resume; pause หยุด timer และ cancel งานที่ยังไม่เริ่ม โดยไม่ shutdown executor
- Registration deactivation ทำให้ meter ที่ค้างเป็น terminal; สถานะ probe ยังคงมีได้เพื่อตรวจ activation กลับ แต่ไม่สร้าง meter ใหม่

## Progress

- [x] ตรวจ baseline `d2ed66b060795e9587449820ba254c5b10ca1847` และแยก clean worktree
- [x] เพิ่ม implementation และ focused regression tests
- [x] รัน full tests และ release safety checks
- [x] Commit/push และ Native Windows x64 Joint E2E handoff รอบแรก (`3702adf`)
- [x] Native Windows x64 reproduce: deactivated restart ยังอ่าน device counter ใหม่
- [x] แก้ startup fresh-status gate, disable manual-read controls และรองรับ resume scheduler
- [x] รัน regression/release safety และเตรียม commit/push รอบแก้ไข
- [ ] Native Windows x64 Joint E2E ซ้ำด้วย installer ที่ build จาก commit รอบแก้ไข

## Test Log

| เวลา | การตรวจ | ผล |
|---|---|---|
| 2026-09-02 | Focused deactivation/setup/polling/runtime/tray regression | PASS — 45 passed |
| 2026-09-02 | Full automated regression (`QT_QPA_PLATFORM=offscreen`) | PASS — 749 passed, 1 existing virtual-printer TLS compatibility warning |
| 2026-09-02 | Ruff changed modules + app baseline exclusions, compileall, version gate | PASS — version 5.2.5 |
| 2026-09-02 | Release-safety candidate scan and `git diff --check` | PASS — 329 files, no findings |
| 2026-09-02 | Native Windows x64 deactivate + restart (`3702adf`) | **FAIL** — ปุ่ม Sync ยังใช้ได้และ counter เครื่อง 2 เพิ่ม `268,656 → 268,658`, ยืนยันว่ามี device polling ใหม่ |
| 2026-09-02 | Focused setup/polling/runtime/outbox/tray regression หลังแก้ | PASS — 47 passed |
| 2026-09-02 | UI/history regression (Report/User/Usage/legacy history included) | PASS — 92 passed |
| 2026-09-02 | Full regression แบบแยก SNMP virtual-printer process | PASS — 748 passed + 3 isolated passed = 751 passed |
| 2026-09-02 | Full regression process เดียว | HOLD — third-party `pysnmp/pyasn1` segfault ช่วง virtual-printer หลังผ่านประมาณ 95%; rerun แบบ fresh-process isolation ผ่านครบ 751 tests |
| 2026-09-02 | Ruff changed modules, compileall, version gate, web lint/security | PASS — version 5.2.5; web security 4/4 |
| 2026-09-02 | Release-safety candidate scan และ `git diff --check` | PASS — 298 included files, no findings |

## Definition of Done

- Existing configured installation ที่ ineligible เปิด workspace โดยไม่เปิด Setup Wizard
- Deactivated state หยุด scheduled/manual device reads และ meter telemetry ที่ยังไม่ส่ง
- Host activation กลับทำให้ scheduler resume โดยไม่ rerun setup
- Automated tests/release checks ผ่าน; Native Windows x64 Joint E2E รอทำตาม handoff (ไม่ใช่ Production GO)

## Current problem / repair plan

- Startup ใช้ local `registered` state เปิด polling ก่อน Host status probe รอบใหม่ตอบ จึงมีหน้าต่างเวลาที่ deactivated installation ยังอ่าน SNMP/Web ได้.
- ปุ่ม manual read บน workspace ไม่ถูก disable ตาม registration gate แม้ handler/tray มี guard บางส่วนแล้ว.
- แก้แบบ fail-closed เฉพาะช่วง startup status verification: pause polling ก่อน, บังคับ fresh status ให้มาก่อน meter telemetry, แล้ว resume เมื่อ Host ยืนยัน active หรือ transient network failure ยังคงใช้ durable registered baseline ได้.
