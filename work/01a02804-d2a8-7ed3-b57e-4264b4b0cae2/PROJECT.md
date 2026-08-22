---
project_id: komi-report-v5-phase-4-native-rc
project_name: KOMI Report V5.1
thread_id: 01a02804-d2a8-7ed3-b57e-4264b4b0cae2
thread_title: Production Phase 4 — Native Packaging & Release Candidate
dashboard_visible: true
department: dev
status: blocked
progress: 78
owner: VEGA
current_phase: Phase 4 Technical RC assembled and preflighted; Production GO blocked
current_task: close evidence, push the private Phase 4 branch and hand off exact blockers
next_action: repeat the approved installer/UAT matrix on native Windows 10 and 11 x64, sign the artifact, then run controlled real-device acceptance
problem: available Windows VM is ARM64; native Windows x64, signing, tray/autostart/OS-vault/LAN HTTPS/restart/upgrade and controlled real-device evidence remain unavailable
updated_at: 2026-08-22T15:45:00+07:00
---

# Production Phase 4 — Native Packaging & Release Candidate

## Goal

สร้าง KOMI Report V5.1.0 Release Candidate ที่ตรวจย้อนกลับได้ ติดตั้ง/อัปเกรด/สำรอง/กู้คืน/ถอนติดตั้งได้บน Windows 10/11 x64 และรักษา Meter, Billing, Report, Phase 0–2 fail-closed gates เดิม โดยไม่รวมระบบ Update ของ Phase 3.

## Scope

### In

- reproducible Windows 10/11 x64 package/installer pipeline สำหรับ version `5.1.0`
- artifact identity, source commit, SHA256, file inventory, SBOM และ release-safety result
- clean install, first-run, restart, Tray, Auto-start, OS vault และ LAN Web HTTPS UAT
- upgrade, SQLite backup/integrity, restore/rollback และ uninstall/reinstall UAT
- controlled real-device Meter/Billing/Report/Excel acceptance เมื่อ test authority และขอบเขตชัดเจน
- macOS arm64 Internal UAT เท่าที่ environment รองรับ โดยแยก unsigned evidence ออกจาก signing/notarization
- full Python/Web/security/dependency/release-safety regression และ forbidden-data/secret scan
- support, recovery, rollback และ release handoff ที่ระบุ blocker ตามหลักฐานจริง

### Out

- signed manifest, update check, download/updater, update event telemetry, forced/silent update หรือ remote update command ทุกชนิด
- Phase 5 และ Linux packaging/UAT
- การเปลี่ยน Meter, Billing ledger, pricing, report/export semantics หรือทำให้ Hold/fail-closed อ่อนลง
- การเปิด Registration/Heartbeat production ก่อน OpenAPI/Staging และ Privacy/DPO/Legal gates ผ่าน
- customer production data/device actions นอก controlled test scope
- portfolio-site และ Dashboard publication; ส่ง compact handoff ให้ main thread ทำต่อ

## Design

- ใช้ target-native build: package ถูกสร้างบน Windows x64 เท่านั้นจึงติดป้าย Windows x64 RC ได้; build จาก macOS หรือ Windows ARM VM เป็น preflight เท่านั้น.
- builder ทำงาน non-interactive และ fail-closed: ตรวจ version/commit/architecture/clean source, สร้าง staging ใหม่, สแกนก่อนและหลัง pack, แล้วเขียน evidence หลัง artifact ผ่านเท่านั้น.
- installer/portable payload ไม่รวม DB, CSV/XLSX, log, `.env*`, key/certificate private material, credential, cache, customer evidence หรือ source development artifacts.
- evidence แยก Automated, VM, Native, Real-device และ Signed ชัดเจน; ไม่มีการเลื่อนระดับหลักฐานอัตโนมัติ.
- Registration/Heartbeat production ยังคง disabled/fail-closed และ Release นี้ต้องไม่มี Update runtime path.

## Architecture

พิจารณา 3 ทางเลือก:

1. build script เดิมแบบ interactive + คัดลอก EXE: ง่ายแต่เปลี่ยน version/source และ deploy side effect ระหว่าง build จึงทำซ้ำและ audit ยาก.
2. target-native modular RC pipeline: แยก preflight → PyInstaller → installer/package → safety scan → SBOM/checksum/evidence; เหมาะกับ release นี้และ reuse gate Phase 0 ได้.
3. full CI signing/release service: เหมาะเมื่อ certificate runner และ approval chain พร้อม แต่ซับซ้อนเกิน gate ที่มีอยู่ตอนนี้.

เลือกข้อ 2. Data flow คือ clean source commit → target-native build environment → staged application → installer/portable artifact → fail-closed scan → checksum/SBOM/inventory/evidence. Failure ใดหยุดก่อน publish และเก็บเฉพาะ evidence ที่ไม่ปนข้อมูลจริง.

## คำที่ใช้ร่วมกัน

- **RC**: artifact สำหรับทดสอบ release ที่ trace ได้ แต่ยังไม่ใช่ Production GO จน native/signing/real-device gates ผ่าน.
- **Windows native x64 evidence**: ผลจาก Windows 10/11 x64 environment จริงตาม target; Windows 11 ARM VM หรือ emulation เป็น VM preflight ไม่ใช่ final acceptance.
- **Controlled real-device proof**: การอ่าน/คำนวณจากเครื่องพิมพ์ที่ได้รับอนุญาต มี expected delta และไม่แตะข้อมูลลูกค้านอก scope.

## Progress: 78%

### Phase 4.1 — Baseline and workbook ✅

- [x] ตรวจ `main`, `origin/main`, clean worktree และ approved baseline `6248ef2`
- [x] สร้าง branch `codex/phase-4-native-release-candidate`
- [x] สร้าง workbook เดียวของ task นี้
- [x] inventory builder/spec/support matrix/release runbook/VM เบื้องต้น

### Phase 4.2 — Reproducible Windows x64 RC pipeline

- [x] เพิ่ม fail-closed non-interactive Windows x64 RC builder
- [x] สร้าง installer artifact พร้อม identity, source commit, SHA256 และ file inventory
- [x] สร้าง SBOM/file-inventory/checksum contract และ native-runtime safety allowlist แบบจำกัด root
- [x] ยืนยัน Registration fail-closed และ Update runtime path absent/deferred ด้วย automated gate

### Phase 4.3 — Regression and package verification

- [x] full Python regression ด้วย `source/.venv/bin/python`
- [x] Web type/lint/build/security tests และ production dependency audits
- [x] security/release-safety/secret/data scan
- [x] package smoke, DB migration/backup/integrity/restore preflight และ no semantic drift automated checks

### Phase 4.4 — Environment UAT

- [x] Windows 11 ARM VM clean install/installed smoke/first-run/backup/integrity/restore/uninstall/reinstall preflight โดยติดป้าย VM/ARM ชัดเจน
- [ ] Windows 10 x64 native UAT
- [ ] Windows 11 x64 native UAT
- [ ] Windows code signing verification
- [ ] controlled real-device Meter/Billing/Report/Excel acceptance
- [x] macOS arm64 Internal UAT: bundle launch/first-run ผ่าน; ad-hoc signing และ notarization ยัง block customer Production

### Phase 4.5 — Release control and handoff

- [x] support/recovery/rollback guide และ UAT checklist พร้อมใช้งาน
- [x] self-review Outcome/Maintainability; safe merge gate = HOLD เพราะ native/signing/real-device evidence ขาด
- [ ] commit/push private branch; fast-forward main เฉพาะเมื่อ merge gate ผ่าน
- [ ] อัปเดต canonical `PROJECT.md` และส่ง compact handoff ไป main thread

## Problem / Blocker

- What failed: target VM `Window Test for KOMI` เป็น Windows 11 on ARM64 (`platformArchitecture=ARM`) ไม่ใช่ Windows 10/11 x64; Windows installer และ macOS bundle ไม่มี production signing และยังไม่มี approved controlled real-device scope.
- User impact: ใช้ VM ทำ Windows packaging/behavior preflight ได้ แต่ยังปิด Windows x64 native, signing และ real-device Definition of Done ไม่ได้ จึงห้าม claim Production GO.
- Attempts made: สร้าง self-contained x64 installer จาก official hash-verified CPython/Node runtimes; รัน ARM64 VM clean install, installed smoke, first-run UI, synthetic DB backup/integrity/restore, uninstall/reinstall; รัน macOS arm64 bundle launch/first-run และตรวจ signing/notarization ตามจริง.
- Model / effort tried: direct execution, high-risk Production review.
- Evidence: Windows artifact commit `0bc1c5d9c168a6ff535725050c5a901f868541e2`, SHA256 `875e5ca1b2d0134213aca8210308e4a41d7920d7e86e7b1162cf3001207debc1`; VM evidence ระบุ `windows-arm64-vm-preflight` และ `production_go=false`; macOS artifact SHA256 `ab6e7003d63dd381acd73dcf5df091e8d36f980774ef9f8570476ad8dc08bd0f`, ad-hoc/not notarized.
- Needed next: จัด Windows 10 และ 11 x64 native environment + signing certificate + controlled printer acceptance scope แล้วรัน restart/tray/autostart/OS-vault/LAN HTTPS/upgrade matrix ก่อนพิจารณา Production GO.

## Decisions and Changes

- 2026-08-22 — Bom deferred Production Phase 3 Update ทั้งหมด; Phase 4 ห้ามสร้างหรือแก้ Update code/runtime path.
- 2026-08-22 — Windows 10/11 x64 เป็น customer target, macOS arm64 เป็น Internal UAT และ Linux deferred.
- 2026-08-22 — Registration/Heartbeat คง fail-closed; Phase 2 ยังเป็น Technical Pass / Production blocked.
- 2026-08-22 — ใช้ Windows 11 ARM VM ที่ Bom เตรียมไว้สำหรับ preflight เท่านั้น ไม่เลื่อนเป็น native x64 evidence.
- 2026-08-22 — RC ใช้ source-layout runtime (`source/`) + official CPython x64 + Node.js 24 LTS x64 + traced Next standalone seed เพื่อให้ Desktop และ LAN Web HTTPS ทำงานจาก installer เดียวโดยไม่ต้องติดตั้ง Python/Node เพิ่ม.
- 2026-08-22 — Installer เป็น per-user stable AppId และไม่ลบ Database/Web security/OS-vault data ตอน uninstall; restore ต้อง offline, สร้าง rollback backup และตรวจ critical counts.

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 12:46 +07 | Git baseline | clean `main` ตรง approved baseline และ `origin/main` | ทั้งสามตำแหน่งตรง `6248ef2`; worktree clean | PASS | `git status`, `git rev-parse` |
| 2026-08-22 12:48 +07 | Packaging inventory | ทราบ builder/spec/gates เดิมก่อนแก้ | พบ interactive `source/build.py`, PyInstaller onedir spec, Phase 0 source/Windows kit/macOS safety builders, support matrix/runbook และ release source archive | PASS — INVENTORY | source/docs/release files |
| 2026-08-22 12:50 +07 | VM target inspection | ยืนยัน OS/architecture ก่อนอ้าง Windows evidence | VM เป็น Windows 11 ARM64 ไม่ใช่ x64; running, Guest Additions 7.2.14, readonly DEV share | HOLD — X64 NATIVE | `VBoxManage showvminfo` |
| 2026-08-22 14:32 +07 | Phase 4 focused tests | RC environment labels, Update/Registration gates, inventory/SBOM, installer preservation และ DB recovery ต้อง fail-closed | focused Phase 4 + legacy release builder `18 passed`; หลังเพิ่ม archive identity focused `11 passed`; Ruff/compileall ผ่าน | PASS | `source/tests/test_phase4_release_candidate.py`, `source/tests/test_release_builder.py` |
| 2026-08-22 14:36 +07 | Full Python regression | packaging/recovery ห้ามเปลี่ยน Meter/Billing/Report semantics | `507 passed in 35.90s`; warning เดียวจาก explicit Virtual Printer TLS compatibility fixture | PASS | `QT_QPA_PLATFORM=offscreen source/.venv/bin/python -m pytest -q source/tests` |
| 2026-08-22 14:38 +07 | Web/security/dependency gates | TypeScript/security/standalone build และ production dependencies ต้องผ่าน | `npm ci`, `tsc`, security 2/2, Next standalone production build และ `npm audit --omit=dev` ผ่าน; 0 vulnerabilities | PASS | `web/package.json`, `web/next.config.ts` |
| 2026-08-22 14:40 +07 | Python dependency + release safety | lock/env compatible, known vulnerability 0 และ source archive ไม่มี forbidden data/secrets | `uv pip check`/`uv lock --check` ผ่าน; installed-env `pip-audit` พบ 0; source archive 223 files ผ่าน safety scan. การ audit lock โดยสร้าง temp venv abort จึงเปลี่ยนไป audit installed locked env | PASS AFTER SAFE ALTERNATIVE | `source/.venv`, `release/MANIFEST.json` |
| 2026-08-22 14:49 +07 | VM toolchain preparation | official toolchain ต้องติดตั้งแบบตรวจ hashได้และห้ามทำให้ VM evidence กลายเป็น native | `winget` verified/installed Python 3.11.9 ARM64 + Inno Setup 6.7.3; VM ยังติดป้าย ARM64 preflight | PASS — VM TOOLCHAIN | `outputs/.../vm-evidence/prepare-vm.txt`, installer logs |
| 2026-08-22 15:03 +07 | macOS arm64 Internal UAT | bundle ต้อง launch/first-run ได้และ signing state ต้องรายงานตามจริง | Mach-O arm64 bundle เปิดและแสดง first-run จาก isolated DB; package scan ผ่าน; `codesign` เป็น ad-hoc และ `spctl` reject เพราะไม่ notarized | PASS — INTERNAL / BLOCKED — CUSTOMER | `release/MACOS_MANIFEST.json`, local screenshot `/tmp/komi-phase4-inspect/macos-first-run.png` |
| 2026-08-22 15:25 +07 | Windows x64 RC artifact build | artifact ต้อง trace source/runtime, มี checksum/inventory/SBOM, ไม่มี Update/Registration enablement หรือ forbidden data | installer 8,570 files; identity `komi-report-v5-windows-x64-rc-5.1.0-0bc1c5d9c168`; Phase 0 scan ผ่าน; Authenticode `NotSigned`; `production_go=false` | PASS — ARTIFACT / BLOCKED — SIGNING | `outputs/.../rc-output/RC_MANIFEST.json`, `CHECKSUMS.sha256`, `FILE_INVENTORY.json`, `SBOM.cdx.json` |
| 2026-08-22 15:34 +07 | Windows 11 ARM64 installer/recovery preflight | clean install/smoke/backup/integrity/restore/uninstall/reinstall ต้องรักษา critical tables | ทุกขั้นผ่านด้วย synthetic recovery-only DB; integrity `ok`, schema 12, critical counts ตรง backup และ uninstall เก็บ user DB ไว้ | PASS — ARM64 VM PREFLIGHT | `outputs/.../vm-evidence/installer-uat.txt` |
| 2026-08-22 15:39 +07 | Installed first-run visual preflight | เปิด wizard จาก installed x64 payload โดยไม่ทำ printer/network action | V5.1.0 first-run 1/4 เปิดจาก isolated root; ปิดโดยไม่ submit setup | PASS — ARM64 VM PREFLIGHT | `outputs/.../vm-evidence/windows-installed-first-run.png`, `installed-first-run.txt` |
| 2026-08-22 15:44 +07 | Final Python/Web/security regression | tracked Phase 4 changes ต้องไม่เปลี่ยน Meter/Billing/Report semantics | Python `513 passed, 1 expected TLS fixture warning`; Ruff ผ่าน; Web type/security/standalone build ผ่าน; npm/pip audit พบ 0 known vulnerabilities | PASS | `source/tests`, `web` build/audit logs in task run |

## Definition of Done

- [ ] Windows 10/11 x64 native clean install/launch/first-run/restart/tray/autostart/LAN Web HTTPS/OS vault ผ่าน
- [ ] upgrade + backup + integrity + restore/rollback ผ่านและ Devices/Prices/History/Billing Ledger ไม่สูญหาย
- [ ] controlled printer proof ทำให้ raw meter, expected delta, posted ledger และ Export totals ตรงกัน
- [x] artifact มี SHA256/SBOM/source commit/build identity และไม่มี forbidden data/secrets
- [x] full Python/Web/security/dependency/release gates ผ่าน
- [x] Registration/Heartbeat ยัง fail-closed และไม่มี Update code/runtime path ใน Release นี้
- [ ] signed Windows x64 artifact ผ่าน verification
- [x] macOS arm64 Internal UAT แยกจาก customer Production claim
- [x] blocker ทุกข้อรายงานตามจริง; ไม่มี Production GO หาก gate ใดยังขาด
