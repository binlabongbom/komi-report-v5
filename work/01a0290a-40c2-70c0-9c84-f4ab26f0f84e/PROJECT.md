---
project_id: komi-report-v5-phase-5-pilot-go-live
project_name: KOMI Report V5.1
thread_id: 01a0290a-40c2-70c0-9c84-f4ab26f0f84e
thread_title: Production Phase 5 — Pilot Release & Go-Live Readiness
dashboard_visible: true
department: dev
status: blocked
progress: 100
owner: VEGA
current_phase: Phase 5 complete — PILOT HOLD from live Registration schema mismatch
current_task: hold Pilot until the deployed API accepts the current Desktop serial_number contract
next_action: migrate the deployed schema-v2 allow-list/storage/Dashboard from device_instance_id to serial_number, keep the canonical www endpoint, then rerun current-client E2E
problem: POST https://www.dmskm.com/api/v1/installations/register returns HTTP 422 VALIDATION_ERROR because device_inventory.devices.0.serial_number is not accepted
updated_at: 2026-08-22T19:51:06+07:00
---

# Production Phase 5 — Pilot Release & Go-Live Readiness

## Goal

ตัดสิน **PILOT GO** หรือ **HOLD** สำหรับ KOMI Report V5.1 จากหลักฐานจริง โดยประกอบ Pilot ที่ตรวจย้อนกลับได้ รักษาข้อมูลและกติกา Billing เดิม และไม่ยกระดับ Deferred/VM/synthetic evidence เป็น Production proof.

## Scope

### In

- ตรวจ `main`, `origin/main`, Phase 2 notice commit `e2a90e5` และ Phase 4 branch ล่าสุด แล้วรวมบน `codex/phase-5-pilot-go-live` โดยไม่ merge `main`
- Registration E2E ผ่าน runtime configuration/connection/vault reference ที่โปรแกรมเชื่อมอยู่แล้ว โดยไม่เปิดเผย secret และใช้ synthetic UAT record เท่านั้น
- Registration schema v2 และ Data Notice สำหรับ Company ซึ่งต้องเป็นนิติบุคคล/หน่วยงาน พร้อม forbidden-data gate
- unsigned Pilot package `5.1.0` พร้อม source commit, SHA256, manifest/SBOM และ Publisher warning ตามจริง
- controlled printer acceptance เฉพาะ authority ที่บันทึกไว้ พร้อม raw meter provenance, expected delta, ledger/report/Excel reconciliation และ Hold เมื่อ unsafe
- Backup/Integrity/Restore/Reinstall/rollback โดยรักษา Devices, Prices, History และ Billing Ledger
- support guide, pilot checklist, rollback guide และ compact handoff กลับ Production Control Center

### Out

- Production Phase 3 Update ทั้งหมด: manifest/download/silent-or-forced update/remote command/update telemetry
- Windows code signing, Windows 10/11 native x64 UAT และ Linux production
- การเปลี่ยน Meter/Billing formula, UX redesign หรือ Cloud Meter
- การส่งหรือลบ database/CSV/log/credential/customer evidence และการยิง production แทน staging
- การ merge `main` ก่อน Integration/Regression/Recovery/Pilot evidence ครบ

## Design

- ใช้ evidence ladder แยก Automated, VM preflight, Native, Controlled real-device, Staging E2E และ Signed ชัดเจน; แต่ละ gateผ่านได้เฉพาะหลักฐานระดับของตน
- Registration sender คง fail-closed; ใช้ canonical HTTPS endpoint ที่ connection เดิมชี้อยู่, ไม่ตาม redirect พร้อม credential และให้ HOLD จาก exact live symptom เมื่อ deployed contract ไม่ตรงกับ current Desktop
- Pilot package ต้องผูก source commit/artefact hash/manifest/SBOM เดียวกันและระบุ `Unsigned / Publisher not verified`; ห้ามเปลี่ยนเป็น Production claim
- Recovery ใช้สำเนา synthetic/authorized test data เท่านั้น ตรวจ SQLite integrity และ critical-table fingerprints ก่อนและหลัง restore/reinstall/rollback
- Controlled printer reuse ได้เฉพาะหลักฐาน Phase 4 ที่ระบุ authority/scope/provenance ชัดเจน; การทดสอบใหม่ต้องไม่ส่งงานพิมพ์หรือแก้ config/ข้อมูลจริงโดยไม่มี authority ใหม่

## Architecture

พิจารณา 3 ทางเลือก:

1. แจก Phase 4 RC เดิมทันที: เร็ว แต่ไม่รวม Phase 2 Data Notice commit และ source identity ไม่ตรง integration branch จึง audit ไม่ได้.
2. staged local-first Pilot kit: รวม Phase 2 + Phase 4 บน integration branch, รัน gate ซ้ำ, สร้าง artefact/manifest/support bundle ใหม่ และคง Registration fail-closed จน staging ผ่าน. เลือกแนวทางนี้เพราะรักษา Desktop local-first และลด blast radius.
3. Production-scale hosted rollout: เปิด Registration/Update/signing/native fleet พร้อมกัน; เกิน scope และไม่มี deployed evidence/certificate/native UAT.

Data flow: verified integration commit → regression/release-safety → unsigned Pilot artefact + manifest/SBOM/checksum → isolated recovery → authorized controlled acceptance → PILOT GO/HOLD handoff. Registration ใช้ local outbox → canonical HTTPS endpoint ผ่าน vault reference เดิม → authenticated Dashboard read-back → deactivate synthetic UAT record.

## คำที่ใช้ร่วมกัน

- **PILOT GO**: อนุญาตทดสอบแบบจำกัดวงด้วย unsigned package และข้อจำกัดที่ประกาศครบ ไม่ใช่ Production GO.
- **HOLD**: ยังห้ามเริ่ม Pilot เพราะ gate ที่จำเป็นต่อ Pilot ขาดหรือหลักฐานไม่ปลอดภัย; Deferred ไม่ถูกนับเป็น Passed.
- **Publisher warning**: Windows จะแจ้งผู้เผยแพร่ไม่ผ่านการยืนยันเพราะยังไม่มี code signing; เป็นข้อเท็จจริงที่ต้องแจ้งผู้ทดสอบก่อนติดตั้ง.
- **Controlled printer evidence**: read-only หรือ test action ที่มี authority/scope/provenance ชัดเจนและไม่แตะข้อมูลนอกขอบเขต.

## Progress: 100%

### Phase 5.1 — Baseline and integration ✅

- [x] อ่าน canonical/Phase 2/Phase 4 workbook และกฎ Production ที่มีผล
- [x] ยืนยัน `main == origin/main == 6248ef2`, Phase 2 notice `e2a90e5`, Phase 4 latest `ab529ec`
- [x] สร้าง `codex/phase-5-pilot-go-live` จาก Phase 4 และ merge Phase 2 notice เป็น integration commit `9b08a07`
- [x] inventory integrated code, package artefacts, Registration policy และ test commands

### Phase 5.2 — Registration and data boundary

- [x] resolve runtime configuration/connection/vault reference ที่แอปใช้อยู่จริงโดยไม่แสดง secret
- [x] รัน live E2E ครบตามรายการและบันทึก HOLD จาก current Desktop `serial_number` HTTP 422; backend-compatible payload ผ่าน register/replay/heartbeat/auth/rate-limit/read-back/deactivate เพื่อแยก API availability ออกจาก contract mismatch
- [x] ยืนยัน Data Notice/Company rule และ forbidden data ไม่เข้า payload/log/package

### Phase 5.3 — Pilot package and regression

- [x] รัน full Python/Web/security/release-safety บน integration commit
- [x] สร้าง unsigned Pilot package 5.1.0 พร้อม source commit/SHA256/manifest/SBOM/Publisher warning
- [x] ตรวจ package ไม่มี database/CSV/log/credential/customer evidence และไม่มี Update runtime path

### Phase 5.4 — Acceptance and recovery

- [x] ประเมิน controlled printer/Billing/Report/Excel evidence ตาม authority และ provenance
- [x] ทดสอบ Backup/Integrity/Restore/Reinstall/rollback พร้อม critical-table preservation
- [x] ตรวจ support guide, pilot checklist และ rollback guide

### Phase 5.5 — Decision and handoff

- [x] self-review Outcome/Maintainability และตัดสิน **PILOT HOLD** ใหม่จาก live execution
- [x] อัปเดต canonical workbook/Dashboard sync และส่ง compact handoffกลับ task หลัก
- [x] push private integration branch โดยไม่ merge `main`

## Problem / Blocker

- What changed: ยกเลิก missing-artefact HOLD เดิมแล้ว และพิสูจน์ว่า deployed API/connection/Dashboard ใช้งานได้จริงจาก live synthetic UAT.
- Exact blocker: current Desktop schema v2 ส่ง `device_inventory.devices[].serial_number`; live `POST https://www.dmskm.com/api/v1/installations/register` ตอบ `HTTP 422 VALIDATION_ERROR` ว่า field นี้ไม่อยู่ใน privacy allow-list. Backend-compatible schema เดิมยังรับ `device_instance_id` จึงเป็น deployed contract mismatch ไม่ใช่ API unavailable.
- Endpoint symptom: `https://dmskm.com/api/v1/health` ตอบ `301` ไป `https://www.dmskm.com/api/v1/health`; current client ไม่ตาม redirect เพื่อกัน credential forwarding จึงต้องใช้ canonical `www` base URL หรือแก้ server ให้ endpoint เดิมไม่ redirect.
- Unlock condition: migrate API schema-v2 allow-list, persistence และ Dashboard จาก `device_instance_id` เป็น `serial_number` ตาม current Desktop contract โดยคง forbidden-data boundary; จากนั้น rerun current-client register/replay/offline-restart-retry/heartbeat/auth/Retry-After/read-back/deactivate. ไม่ต้องขอ artefact หรือ secret ใหม่จาก Bom.

## Decisions and Changes

- 2026-08-22 — Delegation อนุมัติ design/scope แล้ว; ใช้ Direct execution ต่อเนื่องและหยุดถามเฉพาะ production credential, real-data export, cost หรือ scope expansion.
- 2026-08-22 — เลือก staged local-first Pilot kit; Phase 3 Update, signing, native Windows x64 และ Linux คง Deferred ไม่ใช่ Passed.
- 2026-08-22 — integration branch เริ่มจาก Phase 4 latest `ab529ec` และ merge Phase 2 notice `e2a90e5`; `main` ไม่เปลี่ยน.
- 2026-08-22 — ~~ไม่พบ staging artefact จึง HOLD~~ ถูก supersede โดย correction ของ Bom; ไม่ใช้เป็น final blocker.
- 2026-08-22 — final decision รอบแรกจาก missing artefact ถูก supersede; final correction decision คือ **PILOT HOLD จาก live HTTP 422 serial_number contract mismatch**.
- 2026-08-22 — Reuse real-printer evidence Phase 4 เฉพาะ authorized Slot 1 จากวันเดียวกัน เพราะ diff `0bc1c5d..be48735` ไม่แตะ Billing/Meter/Report/Excel modules; ไม่ยิงเครื่องจริงซ้ำโดยไม่มี authority window ใหม่.
- 2026-08-22 — **Correction จาก Bom:** Registration API และ connection ปัจจุบันเป็น authoritative runtime source. ยกเลิก missing-repo-artefact blocker, ห้ามขอค่าใหม่ซ้ำ และ resume จาก live execution path เดิม.
- 2026-08-22 — API availability กับ Desktop compatibility แยก gate: backend-compatible synthetic flow ผ่านครบและ cleanup แล้ว แต่ current Desktop payload ต้องผ่านด้วยจึงจะเป็น PILOT GO; ห้ามแปลง backend-only pass เป็น Production/Pilot claim.

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 17:37 +07 | Git baseline/fetch | refs ล่าสุดและ worktree clean ก่อนสร้าง branch | `main == origin/main == 6248ef2`; Phase 2 `e2a90e5`; Phase 4 `ab529ec`; clean | PASS | `git fetch`, `git status`, `git rev-parse`, `git branch -vv` |
| 2026-08-22 17:37 +07 | Integration branch | รวม Phase 2 notice + Phase 4 RC โดยไม่ merge main | merge commit `9b08a07` มี parent `ab529ec` และ `e2a90e5`; `main` คง `6248ef2` | PASS | `git show -s --format=%H\ %P`, `git log --graph` |
| 2026-08-22 17:41 +07 | Registration artefact audit | พบ verified staging/OpenAPI/bootstrap/retention/Dashboard proof ก่อน network | พบเฉพาะ handoff placeholders/synthetic `.invalid`; ไม่มี deployed staging artefact; ไม่เปิด vaultและไม่ยิง production | HOLD — SAFE | tracked `docs/` + `source/services/registration_policy.py` audit |
| 2026-08-22 17:42 +07 | Pilot builder contract | commit/checksum/unsigned/Registration/Update/data boundary ต้อง fail-closed | Phase 5/Phase 4/release/Data Notice focused `29 passed`; Ruff/compileall/diff check ผ่าน | PASS | `test_phase5_pilot_release.py`, release tests |
| 2026-08-22 17:43 +07 | Full Python regression | Integration ต้องไม่เปลี่ยน Meter/Billing/Report/Setup/Registration semantics | `518 passed, 1 expected virtual-printer TLS compatibility warning in 36.14s` | PASS | `source/tests` |
| 2026-08-22 17:43 +07 | Web/security/dependency gates | TypeScript/security/build/audit และ live TLS/auth ต้องคงผ่าน | Web type/security/build ผ่าน, npm 0 vulnerabilities; live TLS 1.3/auth/session/lockout/revocation ผ่าน; Python dependency compatibleและ 0 known vulnerabilities | PASS | `web`, `security_live_check.py`, `uv pip check`, `uvx pip-audit` |
| 2026-08-22 17:44 +07 | Focused Registration contract | replay/retry/restart/heartbeat/auth/Retry-After/allow-list/UI local contract ต้องผ่าน | คำสั่งแรกอ้าง test filenames ที่ไม่มีอยู่และไม่รัน; แก้เป็นไฟล์จริงแล้ว `141 passed in 9.60s`; ไม่มี network | PASS AFTER COMMAND FIX | tracked Registration/Setup/Settings tests |
| 2026-08-22 18:04 +07 | Verified source archive | archive ต้องผูก clean commit, file count ตรง และมี installer definition/docs ครบ | รอบแรก CLI/manifest count ต่าง 230/231 จึงแก้ test; รอบถัดไปขาด Inno script จึงเพิ่ม packaging root; final 232 entries, commit `be48735`, SHA256 `d5d9f043…`, safety ผ่าน | PASS AFTER 2 REPAIRS | `build_local_release.py`, `test_release_builder.py`, source ZIP |
| 2026-08-22 18:13 +07 | Windows unsigned artifact build | integrated installer ต้องมี commit/hash/SBOM/inventory และ fail-closed boundaries | attempt แรกหยุดเพราะ tool path ต่าง user context; attempt สองถึง Inno แล้วพบ source archive ขาด `.iss`; attempt สามผ่าน: SHA256 `39807a0645…`, 8,570 files, `windows-arm64-vm-preflight`, `unverified-blocked`, `production_go=false` | PASS — ARTIFACT / ARM VM PREFLIGHT | `RC_MANIFEST.json`, `CHECKSUMS.sha256`, `FILE_INVENTORY.json`, `SBOM.cdx.json` |
| 2026-08-22 18:13 +07 | Pilot bundle verification | bundle ต้องมี installer/evidence/guides, Publisher warning, commit/hash ตรงและ safety scanผ่าน | `KOMI_Report_V5_1_0_Unsigned_Pilot.zip`, SHA256 `36c2853ff0…`, 9 entries, `release_decision=HOLD`, ZIP safety ผ่าน | PASS — PACKAGE / HOLD DECISION | `PILOT_MANIFEST.json`, Pilot ZIP sidecar |
| 2026-08-22 17:55 +07 | Local isolated recovery | schema 12 backup/restore ต้องรักษา Devices/Prices/History/Billing Ledger | append-only trigger ปฏิเสธการลบ ledger; restore จาก `integrity=ok` backup คืน critical countsครบและ `critical_counts_match_backup=true` | PASS — SYNTHETIC | `/tmp/komi-phase5-recovery-db725f8` isolated DB |
| 2026-08-22 18:36 +07 | Windows installer/recovery/reinstall preflight | clean install/smoke/backup/restore/uninstall/reinstall ต้องรักษา DB และไม่กลบ stale state | ถอน Phase 4 test install ด้วย official uninstallerและเก็บ synthetic DB; รอบแรกถูก stale cleanup race ลบ new root จึง reboot/stabilizeและใช้ UAT root ใหม่; UAT-2 ผ่าน clean install, smoke, schema 12 integrity, critical counts, uninstall preservation, reinstall read-back | PASS AFTER STALE-CLEANUP REPAIR — ARM VM PREFLIGHT | `pilot-installer-uat-2.txt`, `installed-pilot-precondition.txt` |
| 2026-08-22 18:37 +07 | Installed Pilot identity | reinstall ต้องมี current Data Notice/checklist/warning และ launcher/uninstaller | launcher/uninstaller, Registration Data Notice, Pilot checklist, `Unsigned Pilot Candidate` และ `PUBLISHER WARNING` อยู่ครบ; UAT-2 DB/backup อยู่ครบ | PASS — ARM VM PREFLIGHT | `installed-pilot-precondition.txt` |
| 2026-08-22 18:37 +07 | Controlled printer evidence reuse | reuse ได้เฉพาะ authority/provenance ชัดและ semantics ไม่เปลี่ยน | Phase 4 authorized Slot 1 evidenceมี SNMP/Web Total `266,488`, expected delta `2,260`, gross `3,542.80`, net `3,471.94`, Report/Excel fail-closed; diff ถึง `be48735` ไม่แตะ Billing/Meter/Report/Excel paths | PASS — REUSED SAME-DAY CONTROLLED EVIDENCE | Phase 4 workbook + path-level Git diff |
| 2026-08-22 18:38 +07 | Final Python regression | final committed sourceต้องไม่ถอย | `518 passed, 1 expected virtual-printer TLS compatibility warning in 32.34s` | PASS | `source/tests` |
| 2026-08-22 18:47 +07 | Branch publication | private integration branchต้องตรวจย้อนกลับได้และห้ามแตะ main | pushed `codex/phase-5-pilot-go-live` at `f9334e7`; remote `main` คง `6248ef2` | PASS | `git push`, `git ls-remote`, `git rev-parse` |
| 2026-08-22 18:47 +07 | Dashboard sync/verify | canonical และ task workbookต้องเข้า Dashboard data โดย build/test/lint ผ่าน | synced 26 projects; build ผ่าน; 8 testsผ่าน; ESLint ผ่าน | PASS | `npm --prefix ~/Projects/portfolio-site run dashboard:update` |
| 2026-08-22 18:48 +07 | Control Center handoff | task หลักต้องได้รับ Outcome → Evidence → Blocker/Next | ส่ง compact handoff ไป thread `01a0146d-a3a6-7252-920a-9bb331faa2be` สำเร็จ | PASS | Codex task message acknowledgement |
| 2026-08-22 19:31 +07 | Runtime/vault connection discovery | ใช้ connection เดิมโดยไม่ขอค่าใหม่และไม่เปิด secret | พบ canonical HTTPS service, legacy OS-vault bootstrap reference และ authenticated Dashboard session; secret ไม่ถูกพิมพ์หรือบันทึก | PASS | process/config path audit, OS vault reference, deployed API delivery read-only review |
| 2026-08-22 19:34 +07 | Live health/canonical endpoint | service ต้อง reachable และ client ต้องไม่ส่ง credential ผ่าน redirect | non-www health `301` ไป canonical `www`; canonical health `200`, database `ok`, schema versions 1/2, TLS 1.3 | PASS WITH CANONICAL-URL REQUIREMENT | live HTTPS responses |
| 2026-08-22 19:36 +07 | Current Desktop register | strict schema v2 ที่ใช้ `serial_number`, พบ 4/เลือก 3 ต้องถูก deployed API รับ | `POST /api/v1/installations/register` ตอบ `HTTP 422 VALIDATION_ERROR`: `device_inventory.devices.0.serial_number` ไม่ถูก privacy allow-list | **HOLD — LIVE CONTRACT MISMATCH** | current `registration_envelope.py` ผ่าน `RegistrationClient` contract + live response |
| 2026-08-22 19:39 +07 | Backend-compatible live matrix | แยก API availability/auth/rate-limit/Dashboard จาก Desktop mismatch | schema เดิมผ่าน register `201`, replay response เดิม, heartbeat `200`, bad token `401`, reused key/different body `409`, forbidden field `422`, >3 discovered/3 selected accepted, 4 selected rejected, rate limit `429` พร้อม `Retry-After` | PASS — BACKEND ONLY, NOT DESKTOP GO | synthetic live requests; no customer payload |
| 2026-08-22 19:42 +07 | Dashboard read-back/cleanup/revocation | synthetic record ต้องอ่านกลับได้และปิดใช้งานหลังจบ | authenticated Dashboard แสดง schema v2, 4 discovered/3 selected และ heartbeat; deactivate เฉพาะ synthetic installation สำเร็จ; token หลังปิดตอบ `403 INSTALLATION_DISABLED` | PASS — CLEANUP/REVOKED TOKEN | authenticated Dashboard + live heartbeat response |
| 2026-08-22 19:46 +07 | Offline/restart/retry current client | outbox ต้องทน offline/restartและ retry ด้วย operation เดิม | isolated DB เก็บ attempt `offline/retry`; restart คง idempotency key; manual retry ไป canonical live แล้วจบ `action_required`, `HTTP 422 validation_error` | PASS DURABILITY / HOLD LIVE CONTRACT | isolated schema-12 DB attempt history |
| 2026-08-22 19:47 +07 | Relevant regression | Registration/release/recovery/Billing/Excel/printer gates ต้องไม่ถอย | `126 passed`, มีเพียง 2 warning เดิมจาก virtual-printer compatibility | PASS | focused pytest suite |
| 2026-08-22 19:48 +07 | Pilot package identity refresh | HOLD reason/hash/source/installer ต้องตรวจย้อนกลับได้ | bundle regenerated with `registration_e2e=hold-live-contract-mismatch`; Pilot SHA256 `cdbc661a86…`; installer SHA256 `39807a0645…`; source SHA256 `d5d9f043…`; source commitคง `be48735cc43703f2f7f172d08562ae895da77793` | PASS — PACKAGE / HOLD | `PILOT_MANIFEST.json`, ZIP sidecar, `RC_MANIFEST.json`, source manifest |
| 2026-08-22 19:51 +07 | Correction Dashboard sync/verify | final live HOLD state ต้องเข้า Dashboard data และยัง build/test/lint ได้ | synced 33 projects; build ผ่าน; 8 testsผ่าน; ESLint ผ่าน | PASS | `npm --prefix ~/Projects/portfolio-site run dashboard:update` |

## Definition of Done

- [x] Regression/security/release-safety ผ่านบน integration commit
- [x] Registration E2E รันกับ deployed environment แล้ว: API/backend evidence ผ่าน แต่ current Desktop ถูก live HTTP 422; มี exact blocker/unlock condition และ synthetic cleanup ครบ
- [x] Pilot package ตรวจย้อนกลับได้, unsigned warning ถูกต้อง และไม่มี forbidden data/Update runtime
- [x] Controlled printer + Report/Excel + recovery evidence ผ่านตาม authorized scope; unsafe evidence คง Hold
- [x] Devices/Prices/History/Billing Ledger ถูกเก็บครบหลัง backup/restore/reinstall/rollback
- [x] support/pilot/rollback guides พร้อมและ PILOT GO/HOLD handoff ถูกส่งกลับ main task
- [x] canonical workbook/Dashboard sync ครบและ `main` ยังไม่ถูก merge
