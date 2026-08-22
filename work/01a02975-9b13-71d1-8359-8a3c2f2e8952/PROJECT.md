---
project_id: komi-report-v5-phase-6-customer-release-packaging
project_name: KOMI Report V5.1
thread_id: 01a02975-9b13-71d1-8359-8a3c2f2e8952
thread_title: Production Phase 6 — Customer Release Packaging
dashboard_visible: true
department: dev
status: active
progress: 30
owner: VEGA
current_phase: Target-native customer packaging pipeline implemented; final source gate still pending Phase 5 closure
current_task: verify Phase 6 builders and wait for the explicit Phase 5 approved source commit before final builds
next_action: commit the verified packaging pipeline, integrate the final Phase 5 source gate, then build macOS and Windows artifacts
problem: Phase 5 is still active; final customer artifacts are blocked until its latest approved source gate is explicit
updated_at: 2026-08-22T19:45:47+07:00
---

# Production Phase 6 — Customer Release Packaging

## Goal

ส่งมอบ KOMI Report V5.1.0 สำหรับลูกค้าบน macOS และ Windows จาก source identity เดียวกัน โดยแต่ละ OS สร้าง package บน OS เป้าหมายจริง มี provenance/checksum/SBOM/support/recovery evidence และตัดสิน `RELEASE READY` หรือ `HOLD` ตามหลักฐานโดยไม่ยกระดับ unsigned, VM preflight หรือ missing runtime gate.

## Scope

### In

- ล็อก exact approved Phase 5 source gate ก่อนสร้าง final customer artifacts
- ตรวจ version/dependency locks/production runtime flags/Registration configuration/no-Update boundary
- สร้าง macOS `.app` และ distributable DMG/ZIP บน Mac จาก clean source
- ตรวจ launch/first-run/Settings/LAN Web/local DB/graceful quit พร้อม bundle structure, Info.plist, nested code, entitlements, `codesign` และ `spctl`
- สร้าง Windows EXE/installer ภายใน authorized Windows VM จาก clean checkout ของ commit เดียวกัน
- ตรวจ Windows identity/architecture/signing, clean install, first-run, restart, Tray/Auto-start, LAN Web, uninstall/reinstall และ data preservation
- สร้าง manifest, SHA256, inventory, CycloneDX SBOM หรือ equivalent, release notes, install/uninstall/recovery/rollback guide และ support notes จาก artifact จริง
- สแกน final delivery fail-closed เพื่อไม่ให้มี source ที่ไม่จำเป็น, tests/fixtures/demo/Virtual Printer, DB/CSV/log/env/secret/token/credential/customer evidence หรือ Update runtime
- เก็บ artifact ใน explicit ignored release-output path และ commit เฉพาะ source/docs/evidence metadata ที่ปลอดภัย

### Out

- Production Phase 3 Update, silent/forced update, remote command และ update telemetry
- การซื้อ/สร้าง signing certificate หรือการขอ secret ผ่าน chat
- Linux production
- การเปลี่ยน Meter/Billing/Report semantics หรือ UX redesign
- การเรียก ARM64 VM/emulation ว่า native Windows x64 UAT
- การ merge `main` ขณะ release gate เป็น HOLD

## Design

- ใช้ target-native build: macOS build บน Mac และ Windows build ภายใน Windows VM จาก exact clean commit เดียวกัน
- final bundle ของทั้งสอง OS ใช้ version `5.1.0`, source commit, package identity และ release manifest contract เดียวกัน
- builder/gate ทำงาน fail-closed: source gate, clean checkout, architecture, forbidden data, runtime flags, Registration policy, no-Update, manifest/hash/inventory/SBOM ต้องผ่านก่อนติดป้าย customer artifact
- signing state แยกจาก usability: หากไม่มี Developer ID/notarization หรือ Authenticode certificate ให้สร้าง unsigned/ad-hoc artifact ที่ใช้งานทดสอบได้ พร้อมคำเตือน Gatekeeper/Publisher unknown และตัดสิน HOLD
- recovery ใช้สำเนา synthetic/authorized data เท่านั้น; uninstall/reinstall ห้ามลบ user DB และ restore ต้องตรวจ integrity/critical counts

## Architecture

พิจารณา 3 ทางเลือก:

1. แพ็กทั้งสอง OS จาก Mac: สะดวกแต่ Windows เป็น cross-build และไม่ตอบ native toolchain/installer/runtime gate จึงไม่ใช้
2. target-native release pipeline: clean checkout commit เดียวกัน → native builder ต่อ OS → structural/runtime/signing scan → shared manifest/checksum/SBOM → delivery bundle; เลือกแนวทางนี้เพราะตรวจย้อนกลับได้และตรง Definition of Done
3. hosted CI signing/release service: เหมาะเมื่อมี certificate runner/approval/notarization secrets พร้อม แต่เกิน scope และ credential boundary รอบนี้

Failure ใดใน source identity, forbidden-data scan, artifact runtime, Registration production behavior, signing/native evidence หรือ recovery จะหยุด release decision ที่ `HOLD` โดยเก็บ artifact เป็น unsigned/internal evidence เท่านั้น.

## คำที่ใช้ร่วมกัน

- **Customer artifact**: package ที่สร้างจาก approved source commit, ผ่าน safety/runtime/recovery gate และระบุ signing state ตามจริง; ไม่เท่ากับ Production Ready โดยอัตโนมัติ
- **Native build**: package สร้างด้วย toolchain ภายใน OS เป้าหมาย; Windows ARM64 ที่ใช้ x64 emulation ยังเป็น ARM VM evidence ไม่ใช่ native Windows x64 UAT
- **RELEASE READY**: macOS/Windows artifact, signing/native/runtime/recovery/manifest/safety gates ที่กำหนดผ่านครบ
- **HOLD**: ห้ามปล่อยลูกค้าเพราะอย่างน้อยหนึ่ง gate ที่จำเป็นยังไม่ผ่าน แม้อาจมี unsigned/ad-hoc artifact สำหรับตรวจภายใน

## Progress: 30%

### Phase 6.1 — Baseline and source gate 🟡

- [x] อ่าน project rules, canonical/Phase 4/Phase 5 workbooks และ packaging/signing skills
- [x] สร้าง dedicated worktree/branch โดยไม่แตะ canonical Phase 5 worktree
- [ ] resolve exact approved Phase 5 source commit และยืนยัน Phase 6 clean source identity
- [x] audit version, dependency locks, forbidden-data gate, production runtime flags, Registration/no-Update boundary

### Phase 6.2 — macOS customer package

- [x] เพิ่ม target-native macOS customer builder สำหรับ `.app` + ZIP + DMG + inventory/SBOM/signing evidence แบบ fail-closed
- [ ] build clean macOS `.app` + DMG/ZIP จาก approved commit
- [ ] launch/first-run/Settings/LAN Web/local DB/graceful quit smoke
- [ ] inspect bundle/nested binaries/Info.plist/codesign/spctl/entitlements/notarization state

### Phase 6.3 — Windows VM package

- [x] ยืนยัน VM/Windows edition/OS architecture/Python architecture/toolchain ก่อน build
- [x] เพิ่ม backward-compatible customer profile ให้ Windows builder/installer โดยไม่เปลี่ยน RC/Pilot default เดิม
- [ ] clean checkout exact approved commit ภายใน VM และ build EXE/installer ใน Windows
- [ ] clean install/first-run/restart/Tray/Auto-start/LAN Web/uninstall/reinstall/data-preservation UAT
- [ ] inspect Product/version/publisher/file architecture/Authenticode ตามจริง

### Phase 6.4 — Delivery and recovery

- [x] เพิ่ม shared cross-platform delivery manifest ที่บังคับ version/source/checksum และ HOLD เมื่อ signing/native/UAT gate ขาด
- [ ] generate shared release manifest, SHA256, inventory, SBOM, release/support/install/uninstall/recovery notes
- [ ] scan artifacts 0 forbidden-data/secret findings และยืนยัน no Update/QA fallback
- [ ] backup/restore/integrity/rollback procedure ผ่านบนสำเนา

### Phase 6.5 — Decision and handoff

- [ ] full Python/Web/security/release-safety regression จาก exact final source commit
- [ ] self-review Outcome/Maintainability และตัดสิน RELEASE READY/HOLD
- [ ] final worktree clean, push private branch, sync canonical/Dashboard และ compact handoff กลับ Control Center

## Problem / Blocker

- What failed: ยังไม่มี failure ของ Phase 6 แต่ Phase 5 canonical task ยังอยู่สถานะ Testing และมี workbook changes ที่ยังไม่ commit
- User impact: เริ่มเตรียม pipeline/evidence ได้ แต่ห้ามสร้างหรือติดป้าย final customer artifact จน approved Phase 5 source gate ล่าสุดชัดเจน
- Attempts made: fetch private origin, ยืนยัน local/remote Phase 5 branch ตรงที่ `673784a`; diff จาก source gate `be48735` ถึง HEAD เปลี่ยนเฉพาะ canonical/Phase 5 workbooks
- Model / effort tried: Direct execution, Production high-risk review
- Evidence: canonical `git status`, `git worktree list`, Phase 5 workbook และ branch refs
- Needed next: Phase 5 ปิด live Registration decision และประกาศ exact approved source commit; จากนั้น integrate commit นั้นเข้า Phase 6 ก่อน final build

## Decisions and Changes

- 2026-08-22 — Delegation อนุมัติ recommended target-native architecture และ scope แล้ว; ทำต่ออัตโนมัติและหยุดเฉพาะ credential/certificate/cost/external data/irreversible action
- 2026-08-22 — dedicated worktree `/Users/wongsakornu-phonram/Projects/dev/komi-report-v5-phase-6-customer-release-packaging` บน branch `codex/phase-6-customer-release-packaging` เริ่มจาก committed Phase 5 HEAD `673784a`; canonical dirty workbook ถูกสงวนไว้ไม่แตะต้อง
- 2026-08-22 — final artifact gate ยังล็อกจน Phase 5 ระบุ approved source commit ล่าสุด; preparatory tooling/tests สามารถทำต่อได้
- 2026-08-22 — Mac environment เป็น macOS 27 arm64 และ `security find-identity` คืน 0 valid identities; customer trust gate จะเป็น HOLD หากไม่มี credential อยู่ใน environment โดยจะไม่ขอ secret ผ่าน chat
- 2026-08-22 — VM เดียวที่ได้รับอนุญาตคือ `Window Test for KOMI`: Windows 11 on ARM build 10.0.26200.9168, Python 3.11 ARM64/Inno Setup จาก Phase 4; build ใน VM ได้แต่ evidence ต้องเป็น ARM64 VM/x64-emulation preflight ไม่ใช่ native x64 UAT

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 19:34 +07 | Canonical/worktree safety | ห้าม checkout/เปลี่ยน branch/แก้ canonical ขณะ Phase 5 active | canonical คง branch `codex/phase-5-pilot-go-live` และ dirty เฉพาะ workbook เดิม; Phase 6 worktree/branch แยกสำเร็จ | PASS | `git status`, `git worktree list --porcelain` |
| 2026-08-22 19:34 +07 | Phase 5 ref parity | local/remote source ref ล่าสุดต้องตรงก่อนเริ่ม Phase 6 | local/remote Phase 5 ตรง `673784a`; source diff หลัง `be48735` ไม่มี code change | PASS — PREPARATORY | `git fetch`, `git rev-parse`, `git diff --name-status` |
| 2026-08-22 19:39 +07 | Host signing/VM capability | ระบุ trust/architecture state ตามจริงก่อน build | Mac arm64 ไม่มี valid code-sign identity; VM เป็น Windows 11 ARM64, Guest Additions 7.2.14, Python ARM64/Inno 6.7.3 ตาม verified Phase 4 evidence | HOLD — SIGNING / HOLD — X64 NATIVE | `sw_vers`, `uname -m`, `security find-identity`, `VBoxManage showvminfo/guestproperty`, Phase 4 workbook |
| 2026-08-22 19:45 +07 | Phase 6 customer pipeline focused verification | customer profile/shared manifest ต้องรักษา Phase 4/5 contracts และ HOLD fail-closed | Phase 6 + Phase 4 + Phase 5 + release builder `31 passed`; scoped Ruff และ compileall ผ่าน | PASS | `test_phase6_customer_release.py`, release tests, changed tools |

## Definition of Done

- [ ] มี macOS distributable และ Windows installer จริง พร้อม path/size/SHA256
- [ ] ทั้งสอง artifact ใช้ version/source identity/shared manifest เดียวกัน
- [ ] smoke/install/restart/uninstall/reinstall/recovery ผ่านตามระดับหลักฐานจริง
- [ ] artifact scan พบ 0 tests/demo/Virtual Printer/forbidden data/secrets/Update runtime/QA fallback
- [ ] signing/native/runtime state ระบุจริงและตัดสิน RELEASE READY หรือ HOLD พร้อม exact blocker
- [ ] workbook/canonical/Dashboard sync, private branch push และ compact handoffกลับ taskหลักครบ
