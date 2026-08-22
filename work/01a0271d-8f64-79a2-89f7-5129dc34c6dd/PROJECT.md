---
project_id: komi-report-v5-production-phase-0
project_name: KOMI Report V5.1
thread_id: 01a0271d-8f64-79a2-89f7-5129dc34c6dd
thread_title: Production Phase 0 — Release Safety Baseline
dashboard_visible: true
department: dev
status: done
progress: 100
owner: VEGA
current_phase: Production Phase 0 complete
current_task: Hand off the verified release-safety baseline to Production control
next_action: Keep Phase 1 closed until the main Production thread explicitly starts it
problem: none
updated_at: 2026-08-22T08:49:42+07:00
---

# Production Phase 0 — Release Safety Baseline

## Goal

ทำให้ต้นฉบับ KOMI Report V5.1 สร้าง Release ได้โดยไม่ติดข้อมูลลูกค้า/ความลับ และตรวจย้อนกลับถึง commit ได้ โดยไม่เปลี่ยน Meter, Billing, Registration, Update, UX หรือ behavior ของโปรแกรม

## Scope

### In

- Inventory Git, release builders, version metadata และ runtime/export files
- Block database, CSV, log, environment, token, credential, export/output และ customer data จาก Git/Release
- Automated fail-closed safety gate, version alignment `5.1.0`, manifest, SHA256 และ clean-checkout verification
- Local baseline commit และ private GitHub remote เมื่อ authentication/name/permission พร้อม

### Out

- การแก้ Meter, Billing, Registration, Update, UX หรือ business logic
- การลบ/แก้ฐานข้อมูล, CSV, log หรือ customer data
- Phase 1, signing/notarization และ native customer UAT

## Design

- ใช้ allow-list สำหรับไฟล์ Release และตรวจ deny-list ซ้ำก่อน/หลังสร้าง archive
- รายงาน finding เฉพาะ category + relative path ไม่แสดงค่า secret
- เก็บ export จริงไว้ตำแหน่งเดิมแบบ recoverable แต่ block ด้วย Git ignore และ release gate
- Manifest ต้องมี version, Git commit, source state, build time, SHA256 และ artifact identity

## Architecture

เลือกโครงสร้าง Small-business modular gate: release builder เรียก shared `release_safety.py` ก่อนเขียน artifact และตรวจ archive ซ้ำภายหลัง ใช้ร่วมกันกับ Source, macOS และ Windows packager โดยไม่เข้า runtime/business modules

ทางเลือกที่ไม่เลือก:

1. Ignore อย่างเดียว — ป้องกัน Git ได้แต่ release builder ยังหยิบไฟล์จริงเข้า ZIP ได้
2. ตรวจหลังแพ็กอย่างเดียว — พบช้าและเสี่ยงสร้าง artifact ที่มีข้อมูลแล้ว
3. Shared fail-closed gate — เลือก เพราะตรวจได้ทั้งก่อน/หลังแพ็กและทดสอบ negative case ได้

## Progress: 100%

### Phase 0A — Inventory and containment

- [x] ตรวจ Git/release builder/version metadata โดยไม่เปิดเผยข้อมูลจริง
- [x] ระบุ export จริง 2 จุดและเลือกคงไฟล์ไว้โดย block แทนการย้ายเสี่ยง
- [x] เพิ่ม Git ignore สำหรับ runtime data/export/credential patterns

### Phase 0B — Safety implementation

- [x] เพิ่ม shared release-content safety gate
- [x] เพิ่ม manifest traceability fields และ SHA256
- [x] ทำ runtime/build metadata ให้ตรง `5.1.0`
- [x] พิสูจน์ safety gate ผ่านและ fail ตามกรณีจำลอง

### Phase 0C — Baseline and verification

- [x] Secret/data scan ก่อน first commit
- [x] สร้าง local baseline commit/tag
- [x] Build จาก clean checkout/temp clone และตรวจ artifact contents
- [x] สร้าง/push private remote เมื่อ GitHub พร้อมและไม่มีชื่อชน
- [x] Sync canonical summary; Dashboard publish ส่งกลับ Main/VEGA เพราะห้ามแก้โปรเจกต์อื่นใน Phase 0

## Problem / Blocker

- Phase 0: none.
- นอกขอบเขต Phase 0: signing/notarization, native Windows/macOS package UAT, clean install/upgrade/backup/restore และ Registration API/DPO gates ยังต้องปิดใน Production phase ถัดไป
- `npm ci` รายงาน dependency audit 4 high-severity findings; TypeScript/Next build ผ่าน แต่ dependency remediation ต้องแยก review เพื่อไม่เปลี่ยน behavior ใน Phase 0

## Decisions and Changes

- 2026-08-22 — ใช้ shared fail-closed release gate และคงไฟล์ export จริงไว้ตำแหน่งเดิมโดย block; ไม่ลบหรือย้ายเพราะยังไม่มี authoritative destination
- 2026-08-22 — ใช้ `5.1.0` เป็น version metadata เดียว และไม่เปลี่ยน schema/business logic

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 | Initial repository inventory | รู้ Git/build/version/data state โดยไม่เปิดเผยข้อมูล | No commits; พบ CSV 1 และ XLSX output 1; metadata บางจุดไม่ตรง | PASS | `git status`, filename-only inventory, metadata search |
| 2026-08-22 | Release safety negative cases | CSV/output และ token signature ต้องทำให้ gate fail โดยไม่แสดงค่า secret | ทั้ง forbidden-path/file-type และ GitHub-token category ถูก reject | PASS | `8 passed` in `test_release_builder.py` |
| 2026-08-22 | Full source regression | Phase 0 ต้องไม่เปลี่ยน behavior | `399 passed` | PASS | `source/.venv/bin/python -m pytest source/tests -q` |
| 2026-08-22 | Web typecheck/build | Version-only change ต้อง build ได้ | TypeScript และ Next production build ผ่านหลัง `npm ci` | PASS | `npm run lint`, `npm run build` |
| 2026-08-22 | Pre-commit candidate scan | Candidate tracked files ต้องไม่มี secret/data signature และ export จริงต้องถูก ignore | 223 candidate files, 0 findings, 0 files >5 MB; CSV/XLSX อยู่ ignored | PASS | shared `release_safety.py`, `git check-ignore` |
| 2026-08-22 | First baseline commit/tag | Source ที่ scan แล้วต้องมี immutable local baseline | Commit `85e308f`, annotated tag `v5.1.0-phase0` | PASS | `git log`, `git tag` |
| 2026-08-22 | Clean-checkout build attempt 1 | Source archive ต้อง build จาก temp clone | เรียก module จาก repo root ผิดตำแหน่ง ทำให้ `ModuleNotFoundError: tools` | FAIL — invocation corrected | `/tmp/komi-phase0-clean.eN3aoh/repo` |
| 2026-08-22 | Clean-checkout build attempt 2 | Manifest/ZIP ต้องผ่านทุก assertion | Build สำเร็จ แต่ assertion ใช้ commit SHA ที่พิมพ์ผิดเอง; manifest มี SHA จริงครบ | FAIL — assertion corrected | `/tmp/komi-phase0-clean.CP65D1/repo` |
| 2026-08-22 | Clean-checkout artifact verification | Artifact ต้องชี้ commit/tag, checksum ตรง และไม่มี forbidden content | `5.1.0`, commit `85e308f…`, source `clean`, 204 files, SHA256 `a15776f0…`, forbidden entries 0 | PASS | temp clone + independent ZIP/manifest verification |
| 2026-08-22 | Private remote | ชื่อ repo ไม่ชน, private, push/tag สำเร็จ | `binlabongbom/komi-report-v5`, private=true, viewer=ADMIN, main/tag pushed | PASS | GitHub CLI read-back |

## Definition of Done

- [x] ไม่มี customer data/secret ใน tracked files และ artifact
- [x] Release safety test ผ่านและพิสูจน์กรณี fail ได้
- [x] Runtime/build metadata ทุกจุดตรง `5.1.0`
- [x] Artifact มี SHA256 และชี้กลับ commit ได้
- [x] Clean-checkout build ผ่านและ artifact contents ผ่าน safety audit
- [x] มี local baseline commit/tag
- [x] Private remote ถูก push หาก environment พร้อม หรือมี evidence-based blocker
