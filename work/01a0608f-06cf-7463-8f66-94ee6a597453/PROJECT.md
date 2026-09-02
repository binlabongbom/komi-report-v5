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
- [ ] Commit/push และ Native Windows x64 Joint E2E handoff

## Test Log

| เวลา | การตรวจ | ผล |
|---|---|---|
| 2026-09-02 | Focused deactivation/setup/polling/runtime/tray regression | PASS — 45 passed |
| 2026-09-02 | Full automated regression (`QT_QPA_PLATFORM=offscreen`) | PASS — 749 passed, 1 existing virtual-printer TLS compatibility warning |
| 2026-09-02 | Ruff changed modules + app baseline exclusions, compileall, version gate | PASS — version 5.2.5 |
| 2026-09-02 | Release-safety candidate scan and `git diff --check` | PASS — 329 files, no findings |

## Definition of Done

- Existing configured installation ที่ ineligible เปิด workspace โดยไม่เปิด Setup Wizard
- Deactivated state หยุด scheduled/manual device reads และ meter telemetry ที่ยังไม่ส่ง
- Host activation กลับทำให้ scheduler resume โดยไม่ rerun setup
- Automated tests/release checks ผ่าน; Native Windows x64 Joint E2E รอทำตาม handoff (ไม่ใช่ Production GO)
