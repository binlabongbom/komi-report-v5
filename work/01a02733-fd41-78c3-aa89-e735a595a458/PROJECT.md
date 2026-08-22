---
project_id: komi-report-v5-phase-1-security
project_name: KOMI Report V5.1
thread_id: 01a02733-fd41-78c3-aa89-e735a595a458
thread_title: Production Phase 1 — Security Baseline
dashboard_visible: true
department: dev
status: testing
progress: 95
owner: VEGA
current_phase: Production Phase 1 — Security Baseline
current_task: review final diff และปิด delivery gate ก่อน merge/push
next_action: commit branch, fast-forward main, push private origin และยืนยัน repository clean
problem: none
updated_at: 2026-08-22T09:39:22+07:00
---

# Production Phase 1 — Security Baseline

## Goal

ปิด security baseline ของ KOMI Report V5.1 โดยเข้ารหัส LAN Web, ป้องกัน Web login/session,
ย้าย printer credential ออกจาก SQLite ไป OS vault และบังคับ printer TLS ที่เชื่อถือได้หรือ pin ไว้
โดยไม่เปลี่ยน Meter/Billing semantics และไม่เริ่ม Registration/Update.

## Scope

### In

- ปิด npm/Python production dependency ระดับ Critical/High พร้อม audit จาก environment จริง
- LAN Web ใช้ HTTPS; Python API bind loopback เท่านั้น และ HTTP ห้าม expose บน LAN โดยปริยาย
- per-install certificate รองรับ localhost, hostname, LAN IP, safe regeneration และ customer-provided certificate
- Web login throttling/temporary lockout, expiring session, auth epoch/revocation และ secure cookie บน HTTPS
- credential-store abstraction สำหรับ Windows Credential Manager/DPAPI และ macOS Keychain; SQLite เก็บ reference/metadata เท่านั้น
- rollback-safe migration จาก legacy plaintext ด้วย temp DB/fake vault; vault ใช้ไม่ได้ต้องไม่เขียน plaintext
- Web Connection verify trusted TLS หรือ explicit certificate fingerprint pinning โดย default
- security tests, secret/log scan, Ruff/typecheck/build, full Python regression และ local live checks

### Out

- Meter, Billing ledger, report totals และ calculation semantics
- Registration payload/API, Update client หรือ Phase 2
- UX redesign ที่ไม่จำเป็นต่อ security
- การแก้ OS trust store/ติดตั้ง Root CA เงียบ ๆ
- production DB, credential จริง หรือข้อมูลลูกค้าจริง
- Dashboard portfolio-site mutation; ส่ง publish handoff กลับ main thread เท่านั้น

## Design

- ทำทีละส่วนที่ตรวจซ้ำได้: audit → HTTPS → auth → credential vault → printer TLS → full gates
- migration ใช้ transaction และลบ plaintext หลัง vault save สำเร็จเท่านั้น; failure คงค่าเดิมเพื่อ rollback และรายงาน blocked state
- customer certificate เป็น explicit config; certificate ของโปรแกรมเป็น per-install และไม่แตะ OS trust store
- insecure printer compatibility ต้อง explicit พร้อม warning และไม่เป็นค่าเริ่มต้น

## Architecture

- คง local-first modular monolith: PyQt6 Desktop เป็น control surface, Next.js เป็น LAN report viewer และ FastAPI เป็น loopback-only report API
- LAN traffic terminate TLS ที่ Next.js HTTPS listener; HTTP listener ไม่ bind LAN
- certificate service จัด identity/SAN/lifecycle แยกจาก process launcher และ validate customer certificate/key ก่อนใช้
- OS credential vault อยู่หลัง typed abstraction; SQLite เก็บ opaque reference และ migration state
- printer connector ใช้ verified system trust หรือ SHA-256 certificate pin; insecure mode เป็น explicit compatibility override

## Progress: 95%

### Outcome 1 — Baseline and dependency risk 🟡

- [x] สร้าง workbook/branch จาก clean main และบันทึก approved architecture/DoD
- [x] npm production audit ไม่มี unresolved Critical/High
- [x] Python production audit ไม่มี unresolved Critical/High และ Lab-only dependency ไม่ปะปน production path

### Outcome 2 — LAN HTTPS

- [x] per-install/customer certificate lifecycle ผ่าน automated tests
- [x] Python API เป็น loopback-only และ HTTP LAN ถูก block
- [x] local live HTTPS handshake ผ่านพร้อม SAN/hostname/IP evidence

### Outcome 3 — Web authentication

- [x] rate limit/temporary lockout ไม่เก็บ plaintext
- [x] session expiry, logout, password-change revocation และ restart behavior ผ่าน automated tests
- [x] live login/lockout/expiry/revocation check ผ่าน และ HTTPS cookie เป็น Secure

### Outcome 4 — Printer credential protection

- [x] OS vault abstraction และ fake vault/temp DB tests ผ่าน
- [x] legacy plaintext migration rollback-safe และไม่เหลือ plaintext ใน SQLite/log
- [x] vault unavailable fail safely โดยไม่เขียน plaintext

### Outcome 5 — Printer TLS and defaults

- [x] trusted TLS หรือ fingerprint pinning เป็น default
- [x] insecure compatibility explicit พร้อม warning และไม่ log credential
- [x] ลบ hard-coded/default credential และ legacy settings password โดยรักษาค่าผู้ใช้เดิม

### Outcome 6 — Production verification and delivery

- [x] security regression, scans, focused Ruff/typecheck/build และ release safety ผ่าน
- [x] full Python regression ผ่านโดย Meter/Billing semantics ไม่เปลี่ยน
- [x] npm/pip production audit ไม่มี unresolved Critical/High
- [x] self-review Outcome/Maintainability ผ่านและ canonical PROJECT.md sync
- [ ] merge/fast-forward main, push private origin และ repository clean

## Problem / Blocker

None.

## Decisions and Changes

- 2026-08-22 — เริ่ม Phase 1 บน branch `codex/phase-1-security-baseline` จาก clean main `afbd0d1`;
  architecture/security constraints ได้รับอนุมัติใน delegation และ Phase 0 gates ห้ามอ่อนลง.
- 2026-08-22 — `practical-engineering` และ `architecture-options` ใช้จาก reference ภายใน
  `bom-project-builder`; ไม่มี standalone skill package.

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 09:03 +07 | Repository/branch baseline | main สะอาดและตรง private origin ก่อนเริ่ม | `main...origin/main`, HEAD/origin `afbd0d1`; สร้าง branch `codex/phase-1-security-baseline` สำเร็จ | PASS | `git status --short --branch`, `git log`, `git remote -v` |
| 2026-08-22 09:12 +07 | Production dependency remediation | npm/Python actual production path ต้องไม่มี Critical/High | Next 16.3.2, PostCSS 8.5.26, Sharp 0.35.3, Nanoid 3.3.18, cryptography 50.0.0, keyring 25.7.0; npm/pip actual env + lock audits ได้ 0 known vulnerabilities | PASS | `web/package-lock.json`, `source/requirements*.lock.txt`, `npm audit --omit=dev`, `pip-audit` |
| 2026-08-22 09:24 +07 | LAN HTTPS + auth live check | TLS/SAN/LAN handshake, HTTP block, API loopback, lockout/expiry/restart/revoke/logout ผ่าน process จริง | TLS 1.3; LAN handshake/SAN PASS; HTTP blocked; API loopback; `401×4→429`, restart ยัง 429; Secure/HttpOnly/SameSite; expiry 307, restart 200, password-change 307, logout 200→307 | PASS — LIVE | `source/tools/security_live_check.py` temp DB/runtime; no customer data/credential output |
| 2026-08-22 09:29 +07 | OS vault/legacy migration/printer TLS | SQLite/log ไม่มี plaintext; failure rollback-safe; verified/pinned default | fake-vault/temp DB migration/new-save failure tests ผ่าน; macOS backend `keyring.backends.macOS.Keyring`; virtual HTTPS pin pass/wrong pin reject; insecure Lab emits warning | PASS | `source/services/device_config.py`, `source/komi_snmp_profiler/credential_store.py`, `source/tests/test_device_config.py`, `source/tests/test_virtual_printer.py` |
| 2026-08-22 09:39 +07 | Final regression/build/safety | full Python, Web security/typecheck/build, Ruff, Phase 0 safety และ scans ผ่าน | Python `410 passed`; Web security `2 passed`; TypeScript/build PASS; focused Ruff PASS; release tests 8 PASS; tracked candidates 230/0 และ releasable set 210/0 | PASS | pytest/npm/Ruff/release-safety outputs |

## Definition of Done

- [x] LAN listener เข้ารหัส, direct API ยัง loopback และ HTTP LAN ถูก block
- [x] login throttling/lockout/session expiry/revocation ผ่าน automated + live check
- [x] new/migrated printer credential ไม่อยู่ SQLite/log แบบ plaintext และ legacy migration rollback-safe
- [x] printer TLS verified/pinned by default
- [x] npm/pip production audits ไม่มี unresolved Critical/High; blocker ต้องคง status ไม่เป็น done
- [x] focused tests, full regression, Web typecheck/build และ release safety tests ผ่าน
- [ ] branch merged to main, private origin pushed และ repository clean
- [ ] ส่ง Outcome → Evidence → Blocker/Next step กลับ main thread
