---
project_id: komi-report-v5-phase-6-customer-release-packaging
project_name: KOMI Report V5.1
thread_id: 01a02975-9b13-71d1-8359-8a3c2f2e8952
thread_title: Production Phase 6 — Customer Release Packaging
dashboard_visible: true
department: dev
status: blocked
progress: 100
owner: VEGA
current_phase: Phase 6 customer artifacts assembled and verified as internal HOLD evidence
current_task: preserve the HOLD bundle, publish the private branch, and hand off exact blockers to Control Center
next_action: migrate deployed Registration schema-v2 allow-list/persistence/Dashboard to serial_number, rerun current-client E2E, then obtain signing and native Windows x64 evidence before release
problem: RELEASE HOLD — live Registration returns HTTP 422 for serial_number; macOS is ad-hoc/Gatekeeper rejected; Windows is NotSigned ARM64-VM preflight with Tray/Auto-start/LAN UAT not demonstrated
updated_at: 2026-08-22T20:41:00+07:00
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

## Progress: 100% — RELEASE HOLD

### Phase 6.1 — Baseline and source gate 🟡

- [x] อ่าน project rules, canonical/Phase 4/Phase 5 workbooks และ packaging/signing skills
- [x] สร้าง dedicated worktree/branch โดยไม่แตะ canonical Phase 5 worktree
- [x] resolve exact approved Phase 5 source commit และยืนยัน Phase 6 clean source identity
- [x] audit version, dependency locks, forbidden-data gate, production runtime flags, Registration/no-Update boundary

### Phase 6.2 — macOS customer package

- [x] เพิ่ม target-native macOS customer builder สำหรับ `.app` + ZIP + DMG + inventory/SBOM/signing evidence แบบ fail-closed
- [x] build clean macOS `.app` + DMG/ZIP จาก artifact source commit ที่สืบทอด approved Phase 5 gate
- [ ] launch/first-run/Settings/LAN Web/local DB/graceful quit smoke — app bundle smoke, DB creation และ graceful exit ผ่าน; Settings/LAN Web จาก exact artifact ยังไม่ demonstrate
- [x] inspect bundle/nested binaries/Info.plist/codesign/spctl/entitlements/notarization state

### Phase 6.3 — Windows VM package

- [x] ยืนยัน VM/Windows edition/OS architecture/Python architecture/toolchain ก่อน build
- [x] เพิ่ม backward-compatible customer profile ให้ Windows builder/installer โดยไม่เปลี่ยน RC/Pilot default เดิม
- [x] clean checkout exact artifact commit ภายใน VM และ build EXE/installer ใน Windows
- [ ] clean install/first-run/restart/Tray/Auto-start/LAN Web/uninstall/reinstall/data-preservation UAT — clean install/first-run/restart/uninstall/reinstall/data preservation ผ่าน; Tray/Auto-start/LAN Web ยังไม่ demonstrate
- [x] inspect Product/version/publisher/file architecture/Authenticode ตามจริง

### Phase 6.4 — Delivery and recovery

- [x] เพิ่ม shared cross-platform delivery manifest ที่บังคับ version/source/checksum และ HOLD เมื่อ signing/native/UAT gate ขาด
- [x] generate shared release manifest, SHA256, inventory, SBOM, release/support/install/uninstall/recovery notes
- [x] scan artifacts 0 forbidden-data/secret findings และยืนยัน no Update/QA fallback
- [x] backup/restore/integrity/rollback procedure ผ่านบนสำเนา

### Phase 6.5 — Decision and handoff

- [x] full Python/Web/security/release-safety regression จาก exact artifact source commit
- [x] self-review Outcome/Maintainability และตัดสิน RELEASE READY/HOLD
- [x] final worktree clean, push private branch, sync canonical/Dashboard และ compact handoff กลับ Control Center

## Problem / Blocker

- What failed: current Desktop schema v2 ส่ง `device_inventory.devices[].serial_number` แต่ live canonical endpoint `https://www.dmskm.com` ตอบ HTTP 422 `VALIDATION_ERROR`; deployed privacy allow-list/persistence/Dashboard ยังใช้ `device_instance_id`.
- User impact: ชุดนี้ห้ามปล่อยลูกค้าและห้ามเรียก Final/Production Ready; ใช้ได้เฉพาะ authorized internal verification หลังตรวจ checksum.
- Additional trust/evidence blockers: macOS ไม่มี Developer ID/notarization และ `spctl` rejected; Windows Authenticode `NotSigned`, build/UAT เป็น Windows 11 ARM64 VM ที่ใช้ x64 payload emulation ไม่ใช่ native x64; Tray/Auto-start/LAN Web exact-installer UAT ยังไม่ demonstrate.
- Attempts made: backend-compatible synthetic lifecycle/read-back/deactivate ผ่านจาก Phase 5; offline→restart→retry current-client ยังรักษา operation/idempotency แต่กลับ 422 เดิม. Phase 6 ไม่ regress Desktop กลับ `device_instance_id` และไม่ขอ/ฝัง secret.
- Evidence: Phase 5 approved source `be48735cc43703f2f7f172d08562ae895da77793`, docs close `1c6bf94`; `MACOS_MANIFEST.json`, `WINDOWS_MANIFEST.json`, `WINDOWS_BUILD_ENVIRONMENT.json`, `WINDOWS_UAT_EVIDENCE.json`, `CUSTOMER_RELEASE_MANIFEST.json`.
- Needed next: migrate deployed schema-v2 allow-list/persistence/Dashboard ไป `serial_number` โดยรักษา forbidden-data boundary แล้ว rerun current-client live E2E; จากนั้นปิด signing/notarization, Authenticode, native Windows x64 และ exact Tray/Auto-start/LAN Web gates.

## Decisions and Changes

- 2026-08-22 — Delegation อนุมัติ recommended target-native architecture และ scope แล้ว; ทำต่ออัตโนมัติและหยุดเฉพาะ credential/certificate/cost/external data/irreversible action
- 2026-08-22 — dedicated worktree `/Users/wongsakornu-phonram/Projects/dev/komi-report-v5-phase-6-customer-release-packaging` บน branch `codex/phase-6-customer-release-packaging` เริ่มจาก committed Phase 5 HEAD `673784a`; canonical dirty workbook ถูกสงวนไว้ไม่แตะต้อง
- 2026-08-22 — final artifact gate ยังล็อกจน Phase 5 ระบุ approved source commit ล่าสุด; preparatory tooling/tests สามารถทำต่อได้
- 2026-08-22 — Mac environment เป็น macOS 27 arm64 และ `security find-identity` คืน 0 valid identities; customer trust gate จะเป็น HOLD หากไม่มี credential อยู่ใน environment โดยจะไม่ขอ secret ผ่าน chat
- 2026-08-22 — VM เดียวที่ได้รับอนุญาตคือ `Window Test for KOMI`: Windows 11 on ARM build 10.0.26200.9168, Python 3.11 ARM64/Inno Setup จาก Phase 4; build ใน VM ได้แต่ evidence ต้องเป็น ARM64 VM/x64-emulation preflight ไม่ใช่ native x64 UAT
- 2026-08-22 — Phase 5 final approved source gate คือ `be48735cc43703f2f7f172d08562ae895da77793`; final docs close `1c6bf94` ไม่เปลี่ยน source. Phase 6 artifact source commit `c9c45a67f1e024bd81a5153e7faac881a72ec2ed` สืบทอด gate นี้ และ assembly commit คือ `881eccb3102a20cacaf03bce03953c1a39515e62`.
- 2026-08-22 — final decision เป็น `RELEASE HOLD`; bundle ใช้คำว่า `HOLD` และ `production_go=false` เท่านั้น ไม่ใช้ Final/Production Ready.

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 19:34 +07 | Canonical/worktree safety | ห้าม checkout/เปลี่ยน branch/แก้ canonical ขณะ Phase 5 active | canonical คง branch `codex/phase-5-pilot-go-live` และ dirty เฉพาะ workbook เดิม; Phase 6 worktree/branch แยกสำเร็จ | PASS | `git status`, `git worktree list --porcelain` |
| 2026-08-22 19:34 +07 | Phase 5 ref parity | local/remote source ref ล่าสุดต้องตรงก่อนเริ่ม Phase 6 | local/remote Phase 5 ตรง `673784a`; source diff หลัง `be48735` ไม่มี code change | PASS — PREPARATORY | `git fetch`, `git rev-parse`, `git diff --name-status` |
| 2026-08-22 19:39 +07 | Host signing/VM capability | ระบุ trust/architecture state ตามจริงก่อน build | Mac arm64 ไม่มี valid code-sign identity; VM เป็น Windows 11 ARM64, Guest Additions 7.2.14, Python ARM64/Inno 6.7.3 ตาม verified Phase 4 evidence | HOLD — SIGNING / HOLD — X64 NATIVE | `sw_vers`, `uname -m`, `security find-identity`, `VBoxManage showvminfo/guestproperty`, Phase 4 workbook |
| 2026-08-22 19:45 +07 | Phase 6 customer pipeline focused verification | customer profile/shared manifest ต้องรักษา Phase 4/5 contracts และ HOLD fail-closed | Phase 6 + Phase 4 + Phase 5 + release builder `31 passed`; scoped Ruff และ compileall ผ่าน | PASS | `test_phase6_customer_release.py`, release tests, changed tools |
| 2026-08-22 19:58 +07 | Exact artifact-source regression | Python/Web/security/dependency/release-safety ต้องผ่านจาก commit เดียวกัน | Python `522 passed`; Web type/lint/Next build และ npm audit 0; `uv lock --check`, `uv pip check`, pip-audit 0; live TLS 1.3/auth/session/lockout/revocation ผ่าน | PASS | artifact source `c9c45a67f1e024bd81a5153e7faac881a72ec2ed` |
| 2026-08-22 20:00 +07 | macOS customer package | app/ZIP/DMG ต้องเปิด smoke ได้และบันทึก signing/Gatekeeper ตามจริง | arm64 app smoke exit 0, DB created, graceful exit; nested codesign strict ผ่านแบบ ad-hoc, Team ID ไม่มี, `spctl` rejected, notarized=false | HOLD — TRUST | ZIP `a5b7ba77…4f84` 45,178,528 bytes; DMG `a6dd4c2a…12f1f` 51,368,499 bytes |
| 2026-08-22 20:29 +07 | Windows VM clean build | clean checkout exact commit ภายใน Windows และสร้าง installerจริง | Windows 11 Pro ARM64, Python 3.11.9 ARM64; clean checkout `c9c45a`; Inno 6.7.3 สร้าง x64-compatible installer 111,400,302 bytes; Product 5.1.0/Konica Minolta; Authenticode NotSigned | PASS — ARTIFACT / HOLD — NATIVE & SIGNING | installer SHA256 `852b9d8de1f5e05f474f53578542e169fe629877636a139a2f05e44f2f4d7663` |
| 2026-08-22 20:35 +07 | Windows installer/recovery UAT | clean install/first-run/restart/uninstall/reinstall/DB preservation/restore-on-copy ต้องใช้ exact installer | ทุก gateดังกล่าวผ่าน; DB schema v12/integrity ok, synthetic probe คงอยู่หลัง uninstall/reinstall และ restore-on-copy; Tray/Auto-start/LAN Web ยังไม่ demonstrate | PARTIAL PASS — ARM VM PREFLIGHT | `WINDOWS_UAT_EVIDENCE.json`, `windows-uat.txt` |
| 2026-08-22 20:37 +07 | Shared delivery assembly/safety | manifest/source/checksum/SBOM/provenance ตรง artifact และ forbidden findings เป็น 0 | HOLD bundle 204,797,504 bytes, final zip safety/secret scanผ่าน, source `c9c45a`, approved gate `be48735`, assembly `881eccb`, production_go=false | HOLD — SAFE INTERNAL EVIDENCE | SHA256 `db191ff601b8460dae20619354cff12ba2fb71710912cf5a2f03f6ad613efc8e` |

## Artifact index — ignored local output, authorized internal verification only

- macOS ZIP: `outputs/01a02975-9b13-71d1-8359-8a3c2f2e8952/customer-release/macos/KOMI_Report_V5_1_0_macOS_arm64.zip` — 45,178,528 bytes — SHA256 `a5b7ba77ed3d5d97faa24fd08ce0e7deb3d4f1f68807d20fe37de0c35c554f84`
- macOS DMG: `outputs/01a02975-9b13-71d1-8359-8a3c2f2e8952/customer-release/macos/KOMI_Report_V5_1_0_macOS_arm64.dmg` — 51,368,499 bytes — SHA256 `a6dd4c2aaa3c9cb4f02c3c5cd4edb6d5119301f45097cdfec687a0fba6c12f1f`
- Windows installer: `outputs/01a02975-9b13-71d1-8359-8a3c2f2e8952/customer-release/windows/KOMI_Report_V5_1_0_Windows_x64_Installer.exe` — 111,400,302 bytes — SHA256 `852b9d8de1f5e05f474f53578542e169fe629877636a139a2f05e44f2f4d7663`
- Combined HOLD bundle: `outputs/01a02975-9b13-71d1-8359-8a3c2f2e8952/customer-release/delivery/KOMI_Report_V5_1_0_Customer_Release_HOLD.zip` — 204,797,504 bytes — SHA256 `db191ff601b8460dae20619354cff12ba2fb71710912cf5a2f03f6ad613efc8e`
- All manifests, checksum sidecars, inventories, SBOMs, signing/build/UAT evidence sit beside the artifacts. Binary/output files remain ignored and are not committed to Git.

## Definition of Done

- [x] มี macOS distributable และ Windows installer จริง พร้อม path/size/SHA256
- [x] ทั้งสอง artifact ใช้ version/source identity/shared manifest เดียวกัน
- [x] smoke/install/restart/uninstall/reinstall/recovery ผ่านตามระดับหลักฐานจริง
- [x] artifact scan พบ 0 tests/demo/Virtual Printer/forbidden data/secrets/Update runtime/QA fallback
- [x] signing/native/runtime state ระบุจริงและตัดสิน RELEASE READY หรือ HOLD พร้อม exact blocker
- [x] workbook/canonical/Dashboard sync, private branch push และ compact handoffกลับ taskหลักครบ
