---
project_id: komi-report-v5-phase-2-registration-privacy
project_name: KOMI Report V5.1
thread_id: 01a02760-f602-7d70-9eea-05cc8685dd8c
thread_title: Production Phase 2 — Registration & Privacy
dashboard_visible: true
department: dev
status: blocked
progress: 88
owner: VEGA
current_phase: Technical Pass complete; Production gate blocked
current_task: finalize reviewed branch delivery and preserve fail-closed production state
next_action: provide approved Privacy Notice and verified staging/API contract artefacts, then run staging E2E and Dashboard read-back
problem: No repository artefact proves OpenAPI v2/deployed staging/bootstrap-token lifecycle or approved DPO/Legal privacy workflow; live Production Registration remains disabled
updated_at: 2026-08-22T13:15:00+07:00
---

# Production Phase 2 — Registration & Privacy

## Goal

ทำ Registration schema v2 ให้เป็นส่วนหนึ่งของ Desktop แบบ local-first ที่ทน offline/restart เก็บ token ใน OS vault เท่านั้น และส่งข้อมูลออกได้เฉพาะเมื่อ Privacy Notice รุ่นที่อนุมัติแล้วถูกยอมรับ โดยไม่ทำให้ Setup หรือ printer polling ล้มตาม network.

## Scope

### In

- ตรวจ OpenAPI/deployed environment/bootstrap/token/error contract จาก artefact หรือ secure configuration จริง
- additive SQLite schema สำหรับ registration profile/status/outbox/attempt history โดยไม่แตะ Billing
- typed repository/client/background worker พร้อม idempotency fingerprint, Retry-After, backoff+jitter และ restart recovery
- installation token อยู่ OS vault; SQLite/log เก็บเพียง reference/status ที่ redact แล้ว
- Setup บันทึก local ให้สำเร็จก่อน enqueue และ network failure ห้าม rollback Setup
- privacy-bounded register/heartbeat schema v2 และ forbidden-field rejection
- Privacy Notice acknowledgement + Settings status/retry แบบไทย/อังกฤษที่เรียบง่าย
- staging UAT/Dashboard read-back เมื่อพิสูจน์ได้ว่าเป็น staging จริง
- full Desktop/Web/security/release-safety regression และ private branch delivery

### Out

- Update/manifest/download หรือ Production Phase 3
- การแก้ API repository, portfolio-site หรือโปรเจกต์อื่น
- การสร้าง test installation ใน production
- การแต่งคำอนุมัติ DPO/Legal, retention, access/export หรือ deletion workflow
- การเปลี่ยน Billing tables/formula/ledger semantics

## Design

- ผู้ใช้จบ Setup จาก local transaction ก่อนเสมอ แล้ว Desktop enqueue registration แบบ durable.
- Settings แสดงเพียง `registered`, `pending`, `offline retry`, `action required` พร้อมปุ่ม Retry และ Privacy Notice viewer/acknowledgement.
- Production sender fail-closed เมื่อไม่มี approved notice version หรือ acknowledgement ที่ตรง version.
- Heartbeat ใช้ cadence จาก typed server policy และส่งเฉพาะ lifecycle/device inventory ใน allow-list.
- Observability บันทึก operation/status/error code/timing ที่ redact แล้ว ไม่บันทึก token, raw payload หรือ serial list.

## Architecture

เลือกสถาปัตยกรรม Small-business modular monolith ที่ต่อเข้ากับ PyQt + SQLite เดิม: Setup/UI → typed `RegistrationRepository` → SQLite outbox → registration worker → HTTPS API; token ผ่าน OS vault adapter จาก Phase 1. แบบนี้เพิ่มความทน offline/restart โดยไม่เพิ่ม distributed service ฝั่ง Desktop และยังแยก worker ออกจาก printer polling ได้ชัดเจน. หากปริมาณ event โตขึ้น ค่อยแยก scheduling/telemetry worker ภายหลังโดยคง repository/client contract เดิม.

Data flow:

1. Setup commit local profile/devices/pricing สำเร็จ
2. Repository validate allow-list, สร้าง operation UUID + deterministic request fingerprint และ enqueue
3. Worker claim due item, อ่าน bootstrap/token จาก OS vault แล้วส่ง HTTPS
4. Success บันทึก typed result/cadence และเก็บ token ลง vault ก่อน mark success
5. Retryable failure บันทึก safe error code + next attempt; 429/503 เคารพ Retry-After
6. Terminal auth/validation failure เปลี่ยนเป็น action required โดยไม่ทำลาย local setup

## คำที่ใช้ร่วมกัน

- `installation_id`: ตัวตนของการติดตั้ง KOMI บนคอมพิวเตอร์ ไม่ใช่ตัวตนเครื่องพิมพ์
- `serial_number`: ตัวตนเครื่องพิมพ์จริงใน inventory; เป็นข้อมูลที่ส่งได้เฉพาะตาม Privacy Notice ที่อนุมัติ
- `Technical Pass`: implementation และ local/code gates ผ่าน แต่ยังไม่อนุญาต production sender หาก privacy/staging evidence ไม่ครบ
- `Production Pass`: Technical Pass พร้อม approved notice, DPO/Legal, retention, access/export, deletion และ staging acceptance จริง

## Progress: 88%

### Phase 1 — Baseline and contract audit 🔴

- [x] ยืนยัน main/origin clean ที่ Phase 1 baseline และสร้าง branch เฉพาะงาน
- [x] อ่าน canonical PROJECT.md และ Registration API handoff
- [ ] ตรวจ OpenAPI v2, canonical staging environment, bootstrap, token rotate/revoke และ error contract — ไม่พบ artefact ที่เชื่อถือได้ จึง fail-closed
- [x] บันทึก privacy approval/retention/access/export/deletion blocker ตามจริงโดยไม่แต่ง approval

### Phase 2 — Durable local registration

- [x] เพิ่ม migration/profile/status/outbox/attempt history แบบ additive และ Billing-safe
- [x] เพิ่ม typed repository/client และ allow-list/fingerprint/idempotency
- [x] เพิ่ม worker retry/backoff/jitter/Retry-After/restart recovery
- [x] เก็บ installation token ใน OS vault พร้อม unavailable/rollback tests

### Phase 3 — Desktop integration

- [x] เชื่อม Setup local success → enqueue โดย outbox failure ไม่ rollback/misreport local Setup
- [x] เชื่อม heartbeat lifecycle ด้วย executor แยกจาก printer polling
- [x] เพิ่ม Privacy Notice viewer/acknowledgement และ production fail-closed
- [x] เพิ่ม Settings status/manual Retry ไทย/อังกฤษและ redacted observability

### Phase 4 — Verification and delivery

- [x] focused migration/outbox/client/worker/privacy/UI/secret tests
- [ ] staging synthetic UAT + Dashboard read-back/cleanup — ไม่รันเพราะไม่พบ staging artefact; ห้ามใช้ production แทน
- [x] full Python regression, Web build/security, lint/audits และ Phase 0 release-safety
- [ ] outcome/maintainability review, workbook sync, branch/main/private origin clean
- [ ] Dashboard publish handoff กลับ main thread

## Problem / Blocker

- What failed: ไม่พบ OpenAPI v2, deployed staging URL/environment artefact, bootstrap/token rotate-revoke/error contract หรือ approved Privacy Notice/DPO/Legal evidence ใน scope ที่อนุญาต
- User impact: Desktop implementation เป็น Technical Pass แต่ production sender disabled และห้าม claim Production Pass; staging E2E/Dashboard read-back/cleanup ยังไม่ผ่าน
- Attempts made: ตรวจ canonical handoff, repository files/config references และ historical project evidence โดยไม่เปิดเผย URL/credential/token; ไม่พบ secure staging artefact จึงไม่ยิง network
- Model / effort tried: GPT-5.6 high — Production architecture/integration risk
- Evidence: `docs/REGISTRATION_API_HANDOFF.md`, canonical `PROJECT.md`, repository clean baseline `e70a929d7bcd3f83813e1fd8b92254a264e68ad9`
- Needed next: OpenAPI/deployed staging artefact, approved notice version, legal basis, retention, access/export, deletion workflow และ owner ที่ตรวจสอบได้

## Decisions and Changes

- 2026-08-22 — Architecture/DoD จาก delegation ได้รับอนุมัติแล้ว; เริ่ม Direct execution บน `codex/phase-2-registration-privacy`.
- 2026-08-22 — Production sender ต้อง fail-closed; หาก legal/privacy evidence ไม่ครบ จะส่งมอบได้เพียง Technical Pass / Production blocked.
- 2026-08-22 — Update เป็น Phase 3 และอยู่นอก scope โดยเด็ดขาด.
- 2026-08-22 — ใช้ non-secret policy artefact จาก `KOMI_REGISTRATION_POLICY_FILE`; policy ที่หาย/invalid, Notice ไม่อนุมัติ หรือ acknowledgement ไม่ตรง version จะหยุดก่อนเปิด vault/network.
- 2026-08-22 — Independent review พบ stale outbox, redirect credential forwarding, worker wedge, untrusted error code, reset/vault และ acknowledgement gaps; แก้พร้อม regression tests แล้ว.
- 2026-08-22 — Outbox supersede operation เก่า, ตรวจ payload fingerprint ก่อนส่ง, จำกัด attempt history 50 รายการ และ prune serial-bearing completed payload เมื่อ lifecycle ใหม่สำเร็จ.

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 09:53 +07 | Phase 2 baseline | main/origin ต้องตรง Phase 1 commit และ worktree clean | HEAD/origin `e70a929…`, clean; branch สร้างสำเร็จ | PASS | `git status`, `git rev-parse` |
| 2026-08-22 09:53 +07 | Required instruction/skill review | ใช้ canonical workbook, practical engineering, architecture options, system design และ Python rules | อ่านกฎ/skill/reference ครบ; `practical-engineering` และ `architecture-options` เป็น references ของ bom-project-builder | PASS | `Projects/AGENTS.md`, skill files |
| 2026-08-22 13:40 +07 | Focused Phase 2 regression + independent final review | migration/outbox/client/worker/privacy/UI/reset/race/secret boundary ต้องผ่านและไม่มี P1/P2 ค้าง | `156 passed in 16.60s`; scoped Ruff และ `git diff --check` ผ่าน; reviewer ไม่พบ actionable finding | PASS | `source/tests/test_registration_*.py`, migration/Setup/Settings/lifecycle/reset tests |
| 2026-08-22 13:43 +07 | Full Python regression | baseline ทั้งหมดต้องไม่ถอย | `497 passed, 1 warning in 47.52s`; warning เป็น explicit virtual-printer TLS compatibility fixture เดิม | PASS | `source/tests/` |
| 2026-08-22 12:57 +07 | Web build/security/lint/audit | Web boundary จาก Phase 1 ต้องคงเดิม | security `2 passed`; TypeScript lint/build ผ่าน; `npm audit --omit=dev` = 0 vulnerabilities | PASS | `web/` |
| 2026-08-22 12:58 +07 | Python dependency audit | ไม่มี known vulnerability ใน runtime venv | `No known vulnerabilities found` | PASS | `uvx pip-audit --path source/.venv/lib/python3.12/site-packages` |
| 2026-08-22 13:01 +07 | Phase 0 release safety + live security | release allow-list/secret scan และ LAN HTTPS/auth/session ต้องไม่อ่อนลง | release builder `8 passed`; live security check ผ่าน TLS 1.3, auth/session/lockout/revocation และ Web build/audit | PASS | `test_release_builder.py`, `security_live_check.py --project-root .` |
| 2026-08-22 13:04 +07 | Focused visual/accessibility | Settings status/privacy/acknowledgement ต้องเรียบง่ายและไม่ clip ที่ 1024px | Thai offscreen render ตรวจด้วยตาแล้ว; checkbox disabled ชัดเมื่อยังไม่มี approved/current notice; existing English/accessibility UI tests ผ่าน | PASS — FOCUSED | `/tmp/komi-phase2-settings-final.png`, `test_settings_v5.py` |
| 2026-08-22 13:05 +07 | Staging E2E/Dashboard/cleanup | ต้องใช้ staging artefact จริงและ synthetic identity เท่านั้น | ไม่พบ staging artefact/OpenAPI ใน scope; ไม่สร้าง record และไม่ยิง production | BLOCKED — SAFE | repository/config audit |

## Definition of Done

- [x] durable outbox/retry/idempotency/restart recovery ผ่าน
- [x] scoped installation token อยู่ vault; SQLite/log/artefact ไม่มี secret
- [x] schema v2 allow-list และ forbidden-field rejection ผ่าน
- [x] Setup offline จบได้และภายหลัง recover ได้
- [x] heartbeat cadence/retry/auth failures ทำงานตาม typed policy โดยไม่ชน printer polling
- [x] Privacy Notice/version acknowledgement และ production fail-closed ผ่าน
- [x] Thai/English Settings status/retry/privacy UI ผ่าน focused visual/accessibility checks
- [ ] staging E2E + Dashboard read-back ตรงกันและไม่สร้าง duplicate
- [ ] API/bootstrap/token/retention contracts ถูกบันทึกโดยไม่เปิด secret — client-side fail-closed contract บันทึกแล้ว แต่ deployed contract artefact ยังขาด
- [x] approved Privacy Notice/DPO/Legal evidence มีจริง หรือรายงาน Technical Pass / Production blocked ชัดเจน — รายงาน blocked ตามจริง
- [x] full regression, Web build/security, audits และ Phase 0 release safety ผ่าน
- [ ] branch delivery/private origin clean และไม่เริ่ม Phase 3
