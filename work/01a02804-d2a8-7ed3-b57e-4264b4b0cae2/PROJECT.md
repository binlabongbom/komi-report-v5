---
project_id: komi-report-v5-phase-4-native-rc
project_name: KOMI Report V5.1
thread_id: 01a02804-d2a8-7ed3-b57e-4264b4b0cae2
thread_title: Production Phase 4 — Native Packaging & Release Candidate
dashboard_visible: true
department: dev
status: blocked
progress: 95
owner: VEGA
current_phase: Phase 4 real-device acceptance passed for the authorized Slot 1 printer; Production GO blocked
current_task: obtain and verify Windows production code signing
next_action: sign the Windows x64 installer with an approved production certificate and verify Authenticode before merge
problem: Windows production code signing remains unavailable; Windows 10/11 x64 native UAT is explicitly deferred by Bom and is not claimed as passed
updated_at: 2026-08-22T16:46:07+07:00
---

# Production Phase 4 — Native Packaging & Release Candidate

## Goal

สร้าง KOMI Report V5.1.0 Release Candidate ที่ตรวจย้อนกลับได้ รักษา Meter, Billing, Report และ Phase 0–2 fail-closed gates เดิม โดยไม่รวมระบบ Update ของ Phase 3; Windows 10/11 x64 native UAT ถูกเลื่อนไปหลัง Release ตามคำสั่ง Bom และห้ามอ้างว่าเป็นหลักฐานที่ผ่านแล้ว.

## Scope

### In

- reproducible Windows 10/11 x64 package/installer pipeline สำหรับ version `5.1.0`
- artifact identity, source commit, SHA256, file inventory, SBOM และ release-safety result
- ARM64 VM/package preflight สำหรับ clean install, first-run, restart, backup/integrity, restore/rollback และ uninstall/reinstall โดยไม่ claim แทน native x64
- เก็บ Windows 10/11 native clean install, Tray, Auto-start, OS vault, LAN Web HTTPS และ upgrade UAT เป็น post-Release backlog
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
- Windows 10 x64 และ Windows 11 x64 native UAT สำหรับ Release รอบนี้; เก็บเป็น backlog หลัง Release และห้าม claim ว่าผ่าน
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

- **RC**: artifact สำหรับทดสอบ release ที่ trace ได้ แต่ยังไม่ใช่ Production GO จน signing/real-device gates ของขอบเขตรอบนี้ผ่าน; native Windows 10/11 ถูก Deferred และไม่ใช่หลักฐานที่ผ่าน.
- **Windows native x64 evidence**: ผลจาก Windows 10/11 x64 environment จริงตาม target; Windows 11 ARM VM หรือ emulation เป็น VM preflight ไม่ใช่ final acceptance.
- **Controlled real-device proof**: การอ่าน/คำนวณจากเครื่องพิมพ์ที่ได้รับอนุญาต มี expected delta และไม่แตะข้อมูลลูกค้านอก scope.

## Progress: 95%

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
- [x] บันทึก Windows 10 x64 native UAT เป็น Deferred หลัง Release ตามคำสั่ง Bom โดยไม่ claim ว่าผ่าน
- [x] บันทึก Windows 11 x64 native UAT เป็น Deferred หลัง Release ตามคำสั่ง Bom โดยไม่ claim ว่าผ่าน
- [ ] Windows code signing verification
- [x] controlled real-device Meter/Billing/Report/Excel acceptance — scope Slot 1 `10.244.116.6`; Slot 2 offline และอยู่นอก acceptance scope รอบนี้
- [x] macOS arm64 Internal UAT: bundle launch/first-run ผ่าน; ad-hoc signing และ notarization ยัง block customer Production

### Phase 4.5 — Release control and handoff

- [x] support/recovery/rollback guide และ UAT checklist พร้อมใช้งาน
- [x] self-review Outcome/Maintainability; safe merge gate = HOLD เพราะ production signing ยังขาด และ Product GO ยังติด Registration/Privacy แยกต่างหาก
- [x] commit/push private branch; safe merge gate HOLD จึงไม่ fast-forward `main`
- [x] อัปเดต canonical `PROJECT.md` และส่ง compact handoff ไป main thread `01a0146d-a3a6-7252-920a-9bb331faa2be`

## Problem / Blocker

- What failed: Windows installer และ macOS bundle ยังไม่มี production signing. Windows 10/11 x64 native UAT ถูก Bom เลื่อนไปหลัง Release โดยชัดเจน; จึงไม่เป็น current blocker แต่ยังห้ามอ้างว่าผ่าน. Slot 2 `10.244.116.8` ไม่ตอบ SNMP/HTTP/HTTPS หลังตรวจซ้ำ จึงไม่ถูกนำมารวมใน real-device acceptance scope.
- User impact: Phase 4 ปิด real-device gate ได้สำหรับ Slot 1 ที่ได้รับอนุญาต แต่ยังห้าม claim Production GO หรือ merge `main` จน Windows production code signing ผ่าน; Product Production GO ยังขึ้นกับ Registration/Privacy gates ของ Phase 2 แยกต่างหาก.
- Attempts made: สร้าง self-contained x64 installer และรัน automated/ARM64/macOS preflight; อ่าน Slot 1 ผ่าน SNMP และ Administrator Web Connection แบบ read-only ด้วย TLS fingerprint pinning; คำนวณ Billing จาก real baseline/current counters บนสำเนาฐานข้อมูล; Export Excel จาก isolated migrated copy; ตรวจ Slot 2 ซ้ำด้วย SNMP/TCP 80/443 แล้ว timeout โดยไม่แก้หน้าเครื่องหรือส่งงานพิมพ์.
- Model / effort tried: direct execution, high-risk Production review.
- Evidence: Windows artifact commit `0bc1c5d9c168a6ff535725050c5a901f868541e2`, SHA256 `875e5ca1b2d0134213aca8210308e4a41d7920d7e86e7b1162cf3001207debc1`; Slot 1 SNMP/Web Total ตรงกัน `266,488`; real delta จาก baseline `2026-08-11` ถึง `2026-08-22` เท่ากับ `2,260`, gross `3,542.80`, net หลัง waste 2% `3,471.94`; isolated Excel มี 3 sheets, 9 unique daily rows, privacy scan ผ่าน และ SHA256 `abc347f42a2a39c6e4c4a92b7331dc63bcb473d3585d9dc8c36dbb7ad4d7bf41`.
- Needed next: จัดหา approved Windows production signing certificate, sign installer และ verify Authenticode/checksum/manifest ก่อน safe merge. Native Windows 10/11 UAT และ Slot 2 retest อยู่ใน post-Release backlog.

## Decisions and Changes

- 2026-08-22 — Bom deferred Production Phase 3 Update ทั้งหมด; Phase 4 ห้ามสร้างหรือแก้ Update code/runtime path.
- 2026-08-22 — Windows 10/11 x64 เป็น customer target, macOS arm64 เป็น Internal UAT และ Linux deferred.
- 2026-08-22 — Registration/Heartbeat คง fail-closed; Phase 2 ยังเป็น Technical Pass / Production blocked.
- 2026-08-22 — ใช้ Windows 11 ARM VM ที่ Bom เตรียมไว้สำหรับ preflight เท่านั้น ไม่เลื่อนเป็น native x64 evidence.
- 2026-08-22 — RC ใช้ source-layout runtime (`source/`) + official CPython x64 + Node.js 24 LTS x64 + traced Next standalone seed เพื่อให้ Desktop และ LAN Web HTTPS ทำงานจาก installer เดียวโดยไม่ต้องติดตั้ง Python/Node เพิ่ม.
- 2026-08-22 — Installer เป็น per-user stable AppId และไม่ลบ Database/Web security/OS-vault data ตอน uninstall; restore ต้อง offline, สร้าง rollback backup และตรวจ critical counts.
- 2026-08-22 — BTHL0564 access ถูกเพิ่มเป็น external blocker: cross-host handoff จะลองใหม่เมื่อ private project/Phase 4 branch ถูกบันทึกเป็น Codex saved project บน host นั้น หรือเมื่อมี authorized SSH/remote path ที่ใช้งานได้; ห้ามลด native-evidence gate เพื่อเลี่ยง blocker.
- 2026-08-22 — Bom อนุมัติให้เลื่อน Windows 10 x64 และ Windows 11 x64 native UAT ไปหลัง Release; รายการนี้ถูกถอดจาก current Phase 4 gate แต่ยังคง backlog และห้าม claim ว่าผ่าน.
- 2026-08-22 — Controlled real-device acceptance จำกัด scope ที่ Slot 1 `10.244.116.6`: read-only SNMP/Web, Billing projection และ Report/Excel isolated copy เท่านั้น; ไม่ส่งงานพิมพ์ ไม่แก้หน้าเครื่อง และไม่แตะ SAFEQ. Slot 2 `.8` offline และอยู่นอก scope รอบนี้.

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
| 2026-08-22 15:49 +07 | BTHL0564 native-host access preflight | host ต้องมี matching saved project หรือ authorized remote path ก่อนเริ่ม native x64 UAT | Codex handoff ตอบ `No matching saved project was found on BTHL0564.`; read-only SSH port 22 timeout; ไม่มี installation หรือ remote mutation | HOLD — ACCESS | main-thread continuation from `01a0146d-a3a6-7252-920a-9bb331faa2be` |
| 2026-08-22 16:46 +07 | Live printer SNMP/Web acceptance | authorized printer ต้องตอบทั้ง SNMP และ Web Meter ด้วย identity/Total ตรงกัน; ห้าม retry password เกินหนึ่งครั้ง | Slot 1 `.6` ผ่าน SNMP + fingerprint-pinned Administrator Web; model/serial ตรงฐานข้อมูล, Total ทั้งสองทาง `266,488`, Web counters 96 รายการ. Slot 2 `.8` timeout ซ้ำใน SNMP/TCP 80/443 จึงอยู่นอก scope | PASS — SLOT 1 / OFFLINE — SLOT 2 | read-only live probes; no print/config change |
| 2026-08-22 16:46 +07 | Real-counter Billing acceptance | production pricing functions ต้องคำนวณ real delta ตรงสูตรอิสระ โดยไม่เขียนฐานข้อมูลจริง | baseline `2026-08-11` → current `2026-08-22`: Total delta `2,260`; billable A4 Color `1,646`, A4 B&W `413`, A3 Color `82`, A3 B&W `21`; gross `3,542.80`, waste 2%, net `3,471.94`; independent formula ตรง | PASS — ISOLATED REAL COUNTERS | temporary SQLite copy deleted after verification |
| 2026-08-22 16:46 +07 | Real-history Report/Excel acceptance | export ต้องใช้ canonical Hold semantics, 3 sheets, no duplicate dates และไม่รั่ว IP/Serial/Credential | isolated schema 12 copy integrity `ok`; 26 real daily records ทั้งหมดคง Hold จึงรายงาน 0 ตาม fail-closed; 3 sheets, 9 unique dates, totals match, user empty state และ privacy scan ผ่าน; XLSX SHA256 `abc347f42a2a39c6e4c4a92b7331dc63bcb473d3585d9dc8c36dbb7ad4d7bf41` | PASS — FAIL-CLOSED | temporary XLSX/database deleted after verification |

## Definition of Done

- [x] Windows 10/11 x64 native UAT ถูก Deferred หลัง Release โดย Bom และไม่ถูก claim ว่าผ่าน
- [x] upgrade + backup + integrity + restore/rollback preflight ผ่านใน ARM64 VM; native x64 evidence ถูก Deferred และไม่ถูก claim ว่าผ่าน
- [x] controlled printer proof สำหรับ Slot 1 ทำให้ SNMP/Web raw meter, expected delta, Billing projection และ fail-closed Report/Export totals ตรงกัน; canonical ledger ที่ unsafe ยังคง Hold
- [x] artifact มี SHA256/SBOM/source commit/build identity และไม่มี forbidden data/secrets
- [x] full Python/Web/security/dependency/release gates ผ่าน
- [x] Registration/Heartbeat ยัง fail-closed และไม่มี Update code/runtime path ใน Release นี้
- [ ] signed Windows x64 artifact ผ่าน verification
- [x] macOS arm64 Internal UAT แยกจาก customer Production claim
- [x] blocker ทุกข้อรายงานตามจริง; ไม่มี Production GO หาก gate ใดยังขาด
