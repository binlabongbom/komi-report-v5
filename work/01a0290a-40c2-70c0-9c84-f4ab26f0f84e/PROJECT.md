---
project_id: komi-report-v5-phase-5-pilot-go-live
project_name: KOMI Report V5.1
thread_id: 01a0290a-40c2-70c0-9c84-f4ab26f0f84e
thread_title: Production Phase 5 — Pilot Release & Go-Live Readiness
dashboard_visible: true
department: dev
status: testing
progress: 48
owner: VEGA
current_phase: Phase 5.3 integrated regression passed; Pilot artifact build pending
current_task: commit the verified Pilot builder and build a source-identified Windows artifact in the ARM VM preflight environment
next_action: build the unsigned Pilot candidate from the clean integration commit and verify its manifest/checksums
problem: Registration staging E2E is HOLD because no deployed OpenAPI/staging/bootstrap/retention/Dashboard artefact is available; production was not used as a substitute
updated_at: 2026-08-22T17:44:53+07:00
---

# Production Phase 5 — Pilot Release & Go-Live Readiness

## Goal

ตัดสิน **PILOT GO** หรือ **HOLD** สำหรับ KOMI Report V5.1 จากหลักฐานจริง โดยประกอบ Pilot ที่ตรวจย้อนกลับได้ รักษาข้อมูลและกติกา Billing เดิม และไม่ยกระดับ Deferred/VM/synthetic evidence เป็น Production proof.

## Scope

### In

- ตรวจ `main`, `origin/main`, Phase 2 notice commit `e2a90e5` และ Phase 4 branch ล่าสุด แล้วรวมบน `codex/phase-5-pilot-go-live` โดยไม่ merge `main`
- Registration staging E2E เฉพาะเมื่อมี OpenAPI/base URL/bootstrap/token/retention/Dashboard artefact ที่ตรวจว่าเป็น staging จริง
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
- Registration sender คง fail-closed; ถ้าไม่มี verified staging artefact จะบันทึก exact unlock condition และปิด Registration E2E เป็น HOLD โดยไม่ลอง production
- Pilot package ต้องผูก source commit/artefact hash/manifest/SBOM เดียวกันและระบุ `Unsigned / Publisher not verified`; ห้ามเปลี่ยนเป็น Production claim
- Recovery ใช้สำเนา synthetic/authorized test data เท่านั้น ตรวจ SQLite integrity และ critical-table fingerprints ก่อนและหลัง restore/reinstall/rollback
- Controlled printer reuse ได้เฉพาะหลักฐาน Phase 4 ที่ระบุ authority/scope/provenance ชัดเจน; การทดสอบใหม่ต้องไม่ส่งงานพิมพ์หรือแก้ config/ข้อมูลจริงโดยไม่มี authority ใหม่

## Architecture

พิจารณา 3 ทางเลือก:

1. แจก Phase 4 RC เดิมทันที: เร็ว แต่ไม่รวม Phase 2 Data Notice commit และ source identity ไม่ตรง integration branch จึง audit ไม่ได้.
2. staged local-first Pilot kit: รวม Phase 2 + Phase 4 บน integration branch, รัน gate ซ้ำ, สร้าง artefact/manifest/support bundle ใหม่ และคง Registration fail-closed จน staging ผ่าน. เลือกแนวทางนี้เพราะรักษา Desktop local-first และลด blast radius.
3. Production-scale hosted rollout: เปิด Registration/Update/signing/native fleet พร้อมกัน; เกิน scope และไม่มี deployed evidence/certificate/native UAT.

Data flow: verified integration commit → regression/release-safety → unsigned Pilot artefact + manifest/SBOM/checksum → isolated recovery → authorized controlled acceptance → PILOT GO/HOLD handoff. Registration ใช้ local outbox → HTTPS staging เฉพาะเมื่อ policy/bootstrap artefact ผ่าน; มิฉะนั้นหยุดก่อนเปิด vault/network.

## คำที่ใช้ร่วมกัน

- **PILOT GO**: อนุญาตทดสอบแบบจำกัดวงด้วย unsigned package และข้อจำกัดที่ประกาศครบ ไม่ใช่ Production GO.
- **HOLD**: ยังห้ามเริ่ม Pilot เพราะ gate ที่จำเป็นต่อ Pilot ขาดหรือหลักฐานไม่ปลอดภัย; Deferred ไม่ถูกนับเป็น Passed.
- **Publisher warning**: Windows จะแจ้งผู้เผยแพร่ไม่ผ่านการยืนยันเพราะยังไม่มี code signing; เป็นข้อเท็จจริงที่ต้องแจ้งผู้ทดสอบก่อนติดตั้ง.
- **Controlled printer evidence**: read-only หรือ test action ที่มี authority/scope/provenance ชัดเจนและไม่แตะข้อมูลนอกขอบเขต.

## Progress: 48%

### Phase 5.1 — Baseline and integration 🟡

- [x] อ่าน canonical/Phase 2/Phase 4 workbook และกฎ Production ที่มีผล
- [x] ยืนยัน `main == origin/main == 6248ef2`, Phase 2 notice `e2a90e5`, Phase 4 latest `ab529ec`
- [x] สร้าง `codex/phase-5-pilot-go-live` จาก Phase 4 และ merge Phase 2 notice เป็น integration commit `9b08a07`
- [x] inventory integrated code, package artefacts, Registration policy และ test commands

### Phase 5.2 — Registration and data boundary

- [ ] ยืนยัน deployed staging/OpenAPI/base URL/bootstrap/token/retention/Dashboard access artefact — **HOLD: artefact absent**
- [x] รัน register/replay/offline-restart-retry/heartbeat/bad-revoked token/Retry-After/forbidden payload/inventory/Dashboard/cleanup บน staging หรือบันทึก HOLD พร้อม unlock condition — local contract ผ่าน; staging/Dashboard HOLD
- [x] ยืนยัน Data Notice/Company rule และ forbidden data ไม่เข้า payload/log/package

### Phase 5.3 — Pilot package and regression

- [x] รัน full Python/Web/security/release-safety บน integration commit
- [ ] สร้าง unsigned Pilot package 5.1.0 พร้อม source commit/SHA256/manifest/SBOM/Publisher warning
- [ ] ตรวจ package ไม่มี database/CSV/log/credential/customer evidence และไม่มี Update runtime path

### Phase 5.4 — Acceptance and recovery

- [ ] ประเมิน controlled printer/Billing/Report/Excel evidence ตาม authority และ provenance
- [ ] ทดสอบ Backup/Integrity/Restore/Reinstall/rollback พร้อม critical-table preservation
- [x] ตรวจ support guide, pilot checklist และ rollback guide

### Phase 5.5 — Decision and handoff

- [ ] self-review Outcome/Maintainability และตัดสิน PILOT GO/HOLD
- [ ] อัปเดต canonical workbook/Dashboard sync และส่ง compact handoff กลับ task หลัก
- [ ] push private integration branch โดยไม่ merge `main`

## Problem / Blocker

- What failed: ไม่พบ deployed OpenAPI v2, verified staging base URL, bootstrap/token lifecycle, retention execution และ Dashboard access/read-back artefact; จึงไม่มีสิทธิ์เปิด vault หรือส่ง synthetic Registration request ไป production.
- User impact: Registration E2E/Dashboard/cleanup เป็น `HOLD — SAFE`; overall PILOT GO ยังให้ไม่ได้จนกว่าจะมี staging proof หรือมีการเปลี่ยน scope อย่างชัดเจน. Desktop local-first และ package work เดินหน้าต่อโดย Registration fail-closed.
- Attempts made: ตรวจ tracked docs/source/config contract, policy loader และ repository references; พบเพียง placeholder/synthetic `.invalid` และ owner-confirmed dmskm.com production boundary ไม่ใช่ staging artefact. รัน local Registration contract regressionแทนโดยไม่ส่ง network.
- Model / effort tried: Direct execution, Production high-risk review.
- Evidence: `docs/REGISTRATION_API_HANDOFF.md`, `source/services/registration_policy.py`, focused Registration `141 passed`, full regression `518 passed`.
- Needed next: ส่ง non-secret OpenAPI 3.x + staging base URL/environment proof + bootstrap method/vault reference + token rotate/revoke/error contract + retention/access/deletion/Dashboard role evidence ผ่านช่องทางที่ไม่เปิด secret แล้วจึงรัน synthetic staging E2E และ cleanup/deactivate.

## Decisions and Changes

- 2026-08-22 — Delegation อนุมัติ design/scope แล้ว; ใช้ Direct execution ต่อเนื่องและหยุดถามเฉพาะ production credential, real-data export, cost หรือ scope expansion.
- 2026-08-22 — เลือก staged local-first Pilot kit; Phase 3 Update, signing, native Windows x64 และ Linux คง Deferred ไม่ใช่ Passed.
- 2026-08-22 — integration branch เริ่มจาก Phase 4 latest `ab529ec` และ merge Phase 2 notice `e2a90e5`; `main` ไม่เปลี่ยน.
- 2026-08-22 — ไม่พบ staging artefact ที่ตรวจสอบได้; Registration E2E เป็น HOLD และไม่ยิง production แทน. Pilot builder บังคับ source commit/checksum/unsigned/fail-closed/no-Update contract ก่อนสร้าง bundle.

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

## Definition of Done

- [x] Regression/security/release-safety ผ่านบน integration commit
- [x] Registration E2E ผ่านบน verified staging หรือมี HOLD พร้อม exact blocker/unlock condition — HOLD พร้อม unlock condition ข้างต้น
- [ ] Pilot package ตรวจย้อนกลับได้, unsigned warning ถูกต้อง และไม่มี forbidden data/Update runtime
- [ ] Controlled printer + Report/Excel + recovery evidence ผ่านตาม authorized scope; unsafe evidence คง Hold
- [ ] Devices/Prices/History/Billing Ledger ถูกเก็บครบหลัง backup/restore/reinstall/rollback
- [ ] support/pilot/rollback guides พร้อมและ PILOT GO/HOLD handoff ถูกส่งกลับ main task — guides พร้อม; handoff รอ final decision
- [ ] canonical workbook/Dashboard sync ครบและ `main` ยังไม่ถูก merge
