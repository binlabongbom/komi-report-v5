---
project_id: komi-report-v5-2-production-meter-monitoring
project_name: KOMI Report V5.2
thread_id: 01a03696-8cdf-7023-b5ce-58c090fd09f1
thread_title: KOMI V5.2 — Production Print & Meter Alert
dashboard_visible: true
department: dev
status: testing
progress: 74
owner: VEGA
current_phase: Phase G partial — Windows V5.2 RC built and installed in Windows VM
current_task: preserve the verified Windows RC while waiting for Host/API Joint Staging and remaining release gates
next_action: API team deploys R2 to separate Staging, then run Joint Desktop–Staging E2E before customer Production GO; macOS packaging remains separate
problem: Windows artifact is unsigned and VM evidence is Windows 11 ARM64 x64-emulation preflight, not native x64 or Production GO; Host runtime/Staging remains external
updated_at: 2026-08-25T15:47:00+07:00
---

# KOMI Report V5.2 — Production Print & Meter Alert

## Goal

ยกระดับ Build ใหม่เป็น KOMI Report `5.2.0` จาก source identity เดียว และเพิ่มการส่ง Total Meter แบบ aggregate ต่อเครื่องเพื่อให้ Host แยกคำเตือน “ไม่มีการพิมพ์เกิน 1 วัน — ควรตรวจสอบ” ออกจาก “Desktop/การเชื่อมต่อขาดหาย” โดยไม่เดาว่าเครื่องเสียและไม่ขยายข้อมูลเกิน Privacy boundary ที่อนุมัติ.

## Scope

### In

- version authority เดียวสำหรับ Desktop UI/config, Python package, Web package, API-reported version, PyInstaller, Windows installer, artifact name/manifest และ active V5.2 docs
- Build ใหม่เริ่มที่ `5.2.0` และ fail-closed เมื่อ metadata ใดไม่อยู่ในสาย `5.2.x` หรือไม่ตรง authority
- read-only Production Print discovery/profile จาก model, OID และ Web Meter ที่มีหลักฐานจริง
- Web connector รองรับ TLS 1.1, 1.2 และ 1.3 แบบ per-device capability negotiation; legacy policy ต้องถูก scope เฉพาะ profile และห้ามลด TLS policy ทั้งโปรแกรม
- ระยะแรกคง Desktop UI และ Host UI เดิมทั้งหมด; เปลี่ยนเฉพาะโครงสร้างอ่าน Meter หลัง Bom อนุมัติผล discovery
- แยก Status heartbeat และ aggregate Meter batch ทุก `21,600s` + jitter ±10%; ไม่เกิน 8 normal requests/วัน/Installation
- payload ใช้ `serial_number`, `model`, selected slot, `total_meter`, `meter_observed_at`, `heartbeat_at` และ field ขั้นต่ำที่จำเป็นเท่านั้น
- durable local outbox coalesce เป็น latest Status 1 + latest Meter batch 1, retry/idempotency และ restart recovery; Host เป็นผู้คำนวณ `last_meter_changed_at` และ alert
- alert แยก `no_print_activity` กับ `client_offline`, รองรับ counter ลดลง/reset/replacement, timezone, quiet-hours, วันหยุด, maintenance และ mute
- Host alert list เรียงความเร่งด่วน พร้อม last heartbeat, last meter change, model/serial ที่อนุญาต และสถานะ new/acknowledged/resolved
- rollback-safe migration โดยรักษา DB/History/Billing/Excel ของ V5.1
- local/staging/synthetic UAT และ real Production Print read-only acceptance

### Out

- Production deployment, real Production mutation หรือการเปลี่ยน privacy contract จริงก่อน Bom อนุมัติ
- credential, bootstrap key, token หรือการตีความ “Registration Key” เป็น secret/API key
- IP, MAC, hostname, credential, user, document, job, application log หรือ counter รายละเอียดอื่นใน telemetry
- forced/silent updater; Production Phase 3 Update ยังคง deferred
- การเปลี่ยนชื่อ V5.1 artifact, commit, manifest หรือ evidence ย้อนหลังเป็น V5.2
- การใช้ synthetic/VM/Lab เป็น Production Print หรือ native customer proof
- Host/API implementation, Dashboard alert implementation และ Production deployment ใน Desktop task นี้
- automatic downgrade/fallback ไป schema v2, shared/master API key หรือการใช้ V5.1 API pack เป็น Production config

## Design

- C450i และ C750i เป็น regression control จาก V5.1; รุ่นอื่นต้องคืน Total Meter ความหมายเดียวกันโดยไม่ทำให้สองรุ่นเดิมเสีย.
- ใช้ targeted SNMP `GET` ของ identity, serial และ Total เป็นฐานที่ model-neutral; ไม่บังคับ `GETNEXT/GETBULK walk` เพราะ AccurioPress บางรุ่นตอบ exact OID แต่ปฏิเสธ walk.
- Web Meter เป็นหลักฐานเทียบและแหล่ง counter รายละเอียด: แยก modern JSON Web Connection, legacy XML Web Connection และ unavailable/unsupported โดยไม่เดา endpoint.
- TLS transport เลือกเวอร์ชันสูงสุดที่เครื่องรองรับในช่วง 1.1–1.3; TLS 1.1 และ legacy server-connect เปิดเฉพาะ explicit legacy profile พร้อม certificate pin/customer trust และห้ามใช้ global `verify=False` ใน Production.
- Desktop อ่าน Total Meter ที่ aggregate แล้วจาก device profile ที่ยืนยันได้ เก็บ event ลง durable outbox หลัง local transaction สำเร็จ และส่งผ่าน HTTPS แบบ retryable/idempotent.
- Heartbeat หนึ่งรายการผูกกับ installation และ device ด้วย `serial_number` + selected slot; model ใช้เพื่อแสดงผลและตรวจ replacement ไม่ใช้แทน identity.
- Host ใช้เวลารับจาก server เป็นหลัก เก็บ sample ที่ตรวจ schema แล้ว อัปเดต last heartbeat และคำนวณ `last_meter_changed_at` เมื่อ counter เพิ่มเท่านั้น.
- Counter ลดลงไม่ถือว่า activity เพิ่มและไม่ถือว่า fault: บันทึก reset/replacement candidate แยก แล้วตั้ง baseline ใหม่ตาม identity/rule ที่ตรวจได้.
- Heartbeat ซ้ำด้วย idempotency key เดิมต้องไม่สร้าง sample หรือ transition ซ้ำ.
- เมื่อ heartbeat ยังมาแต่ meter ไม่เพิ่มเกิน policy threshold ให้ warning `no_print_activity`; เมื่อ heartbeat หายเกิน threshold ให้ `client_offline` ซึ่งมี priority สูงกว่าและไม่แสดงสอง alert ซ้อนกันสำหรับอาการเดียว.
- Quiet-hours, วันหยุด, maintenance และ mute ระงับการแจ้งเตือนชั่วคราวโดยไม่ลบ sample/history และไม่แก้เวลาที่ Meter เปลี่ยนจริง.
- Dashboard ใช้ข้อความกลาง ๆ ว่า “ควรตรวจสอบ” ไม่ฟันธง hardware fault และให้ผู้ดูแล acknowledge/resolve พร้อม audit timestamp.

## Architecture

### ทางเลือกที่พิจารณา

1. **Desktop-only:** เหมือนแต่ละสาขาจดบันทึกเอง; ทำง่ายแต่ Host ไม่สามารถเปรียบเทียบ last heartbeat/meter change จากศูนย์กลาง จึงไม่ตอบโจทย์ alert.
2. **Modular Host monolith — เลือกใช้:** เหมือนอาคารเดียวที่แบ่ง front desk, ห้องเก็บข้อมูล และฝ่ายติดตามชัดเจน; Desktop → HTTPS API → relational persistence → alert job → Dashboard. Deploy/rollback ง่ายและแยก module พอสำหรับงานปัจจุบัน.
3. **Monolith + external job queue:** เหมือนอาคารเดิมเพิ่มคลังส่งงาน; เหมาะเมื่อ heartbeat volume สูงหรือ alert job เริ่มช้า. ออกแบบ boundary รองรับได้แต่ยังไม่เพิ่ม dependency ตอนนี้.
4. **Microservices/event bus:** เหมือนหลายสาขาที่ต้องมีศูนย์ประสานงาน; scale ได้มากแต่เพิ่ม operational cost, failure modes และ migration complexity โดยยังไม่มี load/ownership ที่คุ้มค่า จึง deferred.

### Data flow และ recovery

`read-only device profile → aggregate Total Meter → local transaction/outbox → HTTPS heartbeat → schema/idempotency gate → meter sample + current state → alert calculation → dashboard`

- Desktop offline: outbox เก็บ event และ retry โดยไม่ block Meter/Billing/Report.
- Host unavailable: event ยังอยู่ใน outbox; `Retry-After` และ backoff เดิมยังทำงาน.
- Duplicate request: idempotency gate คืนผลเดิมโดยไม่เพิ่ม sample/alert transition.
- Migration failure: transaction rollback และ restore จาก pre-migration backup; V5.1 schema/data ยังเปิดได้ตาม recovery gate.
- Alert job failure: heartbeat/sample ยัง durable; job rerun จาก server state ได้โดยไม่ต้องขอ Desktop ส่งใหม่.

## คำที่ใช้ร่วมกัน

- **Registration Key:** Registration/Heartbeat payload contract เท่านั้น ไม่ใช่ API key หรือ secret.
- **Total Meter:** ตัวเลขรวมการใช้งานต่อเครื่องที่ profile ยืนยันว่าเป็น aggregate; ไม่ส่ง counter ย่อย.
- **ไม่มีการพิมพ์เกิน 1 วัน:** Heartbeat ยังมาแต่ Total Meter ไม่เพิ่มเกิน policy threshold หลังหักช่วงที่ suppress; เป็น warning ไม่ใช่หลักฐานว่าเครื่องเสีย.
- **Client offline:** Host ไม่ได้รับ heartbeat เกิน threshold; ชี้ไปที่ Desktop/เครือข่าย ไม่สรุปสถานะเครื่องพิมพ์.
- **Production proof:** หลักฐาน read-only จาก model/device จริงที่มี authority และบันทึกเวลา/วิธีอ่านครบ; synthetic, Lab และ VM เป็น preflight เท่านั้น.

## Progress: 74%

### Phase A — Baseline and design ✅

- [x] ตรวจ canonical checkout, user changes, worktrees, branches และ remote refs โดยไม่แตะ unrelated changes
- [x] เลือก approved baseline `22a6717` ที่รวม Production Registration ปัจจุบัน
- [x] สร้าง dedicated worktree/branch `codex/v5-2-production-meter-monitoring`
- [x] บันทึก design, architecture, risks, Privacy boundary และ Definition of Done
- [x] รัน baseline focused regression ของ version/registration
- [x] ตรวจ current API contract, shared contract checksum และ version authority inventory จนครบ

### Phase B — V5.2 version migration

- [x] เพิ่ม authority `5.2.0` แหล่งเดียวและ validator สำหรับ derived metadata
- [x] อัปเดต current UI/config/Python/Web/PyInstaller/Inno/API-reported identity และ active V5.2 docs
- [x] เพิ่ม fail-closed tests สำหรับ mismatch, non-5.2.x และ artifact/manifest identity
- [x] บังคับ customer artifact builders เป็น HOLD จน Final schema-3 vectors และ Joint Staging E2E ผ่าน

### Phase C — Production Print discovery/profile

- [x] รับ model/device authority และ test access จาก Bom สำหรับ 12 เครื่อง รวม AccurioPress C12010S
- [x] ยืนยัน identity จริงจาก SNMP: 8 bizhub, 3 AccurioPress; รายการ C358 ที่ให้มาตอบจริงเป็น C368
- [x] ยืนยัน Total OID แบบ targeted GET บน 10 เครื่อง; C84hc ผ่านครั้งแรกแต่ timeout ในการทดสอบซ้ำ
- [x] เทียบ SNMP ↔ Web Total สำเร็จบน C450i, C750i, C300i, C3350i, 950i, C751i และ AccurioPress C7090
- [x] ยืนยันว่า C84hc/C5070 ไม่รองรับ SNMP walk ในช่วงทดสอบ แม้ exact GET เคยตอบ; C5070 targeted GET ซ้ำผ่าน 3/3
- [x] ยืนยัน C12010S targeted SNMP 3/3 และ public legacy XML; Web Total ตรง KM private OID แต่ไม่ตรง Printer-MIB primary
- [ ] ยืนยัน C84hc targeted GET ซ้ำเมื่ออุปกรณ์/เครือข่ายพร้อม และเทียบ Web Meter ของ C458/C368/C84hc/C5070
- [x] สร้าง explicit device profile/capability contract และ negative/unknown behavior
- [x] ผ่าน profile tests กับ captured evidence; ยังไม่เรียก synthetic ว่า Production proof

### Phase D — Desktop telemetry

- [x] สร้าง aggregate meter sample จาก selected devices/profile ที่ยืนยันแล้ว สูงสุด 3 เครื่องต่อ batch
- [x] เพิ่ม Registration schema 3, minimal Status และ Meter allow-list โดยไม่ส่ง field ต้องห้าม
- [x] สร้าง installation Ed25519 identity ผ่าน vault abstraction โดยไม่เก็บ private key/token ใน plaintext DB/log
- [x] เก็บ latest Status/Meter ใน durable outbox, retry/replay/coalesce/restart แบบ idempotent
- [x] ทำ scheduler policy 6h+jitter, startup/network cooldown 15m, server clamp และ Retry-After/15m→1h→6h
- [x] สร้าง signed `.komirequest` และ strict Host-signed `.komilicense` verifier; Offline License ปิด telemetry
- [x] เชื่อม V5.2 coordinator เข้ากับ first-run/app restart/network recovery/graceful stop และ Wizard/Settings แบบ Online Registration / Offline License พร้อม bilingual status
- [x] ทำ Shared Contract R2 ให้ Desktop/API ใช้ raw Ed25519 key, canonical golden vector, response fields, token rotation และ Offline License hash/algorithm ตรงกัน

### Phase E — Host contract and UI

- [ ] เพิ่ม OpenAPI/schema validation/persistence/migration + rollback
- [ ] คำนวณ last heartbeat/last meter changed ฝั่ง server
- [ ] แยก no-print warning กับ client-offline alert และ suppression policies
- [ ] ทำ Dashboard severity order/read-back/acknowledge/resolve/audit

### Phase F — UAT

- [x] local contract fixture E2E: Register → token vault → Status → aggregate Meter; ไม่มี Production call/shared key
- [x] local cross-language compatibility: Desktop-signed Registration ผ่าน Node/API verifier และ Node/Host-signed Offline License ผ่าน Desktop verifier
- [ ] Joint Staging E2E กับ Final Host bundle และ Dashboard read-back
- [ ] time simulation >24h: unchanged vs offline vs suppressed
- [ ] reset/replacement/idempotent duplicate/acknowledge/resolve
- [x] local regression DB/History/Billing/Excel และ Web build/security
- [ ] real Production Print read-only acceptance

### Phase G — Packaging

- [ ] build Mac/Windows 5.2 artifacts จาก source identity เดียว
- [x] build Windows V5.2.0 RC จาก clean source archive ภายใน Windows VM พร้อมติดตั้ง/เปิดครั้งแรก/ปิดหน้าต่างไป Tray/เปิดใหม่ และ DB integrity smoke
- [ ] build macOS V5.2 artifact จาก source identity เดียว
- [ ] manifest/checksum/SBOM/signing/notarization/native labels ตรงหลักฐาน
- [ ] ตัดสิน GO/HOLD โดยไม่ยกระดับ VM/synthetic/unsigned evidence

## Problem / Blocker

- Shared Contract R2/OpenAPI/public golden vector พร้อมในชุดส่งทีม API แล้ว แต่ private Host runtime, migration, Dashboard, deployed OpenAPI และ Host public key/kid สำหรับ Offline License ยังต้องให้ทีม API apply/deploy/ส่งหลักฐานจาก separate Staging; ห้ามเรียก Production/สร้าง customer artifact ก่อน Joint Staging E2E.
- Joint Staging E2E เป็น external gate แยกจาก local focused/full gates; V5.1 API pack ใช้ได้เฉพาะ reference fixture และไม่มีสิทธิ์ทำ automatic downgrade/fallback.
- C84hc ตอบ identity/Total targeted GET ในรอบแรก แต่ timeout ทั้ง walk และ targeted GET ซ้ำ 3 รอบ จึงเป็น `HOLD — device/network unavailable` ไม่ใช่เครื่องไม่รองรับ.
- C5070 ตอบ targeted GET ซ้ำ 3/3 แต่ทุก SNMP walk timeout; implementation เดิมจึงล้มเหลวแม้ Total OID ใช้งานได้.
- Post-implementation smoke รอบ `2026-08-25 10:50–11:00 +07` พบ C5070/C7090 ไม่ตอบ bounded SNMP/Web request และ C12010S Web แจ้ง session busy; หยุด probe เพิ่มเพื่อไม่รบกวนรุ่นเก่า. นี่เป็น device/session availability HOLD ไม่ใช่ product regression หรือ unsupported proof.
- C368 authenticated Web Meter/TLS flow ยังไม่ได้ทดสอบครบ; ห้ามสรุปจาก C458 ว่าพฤติกรรมเหมือนกันทุก firmware.
- C7090 ใช้ legacy XML Web Connection `system_counter.xml`; JSON connector เดิมได้ HTTP 404 แต่ XML Total ตรงกับ SNMP.
- C12010S ใช้ public legacy XML เช่นกัน แต่ Printer-MIB primary `250,132` ไม่ใช่ Web Total; KM private OID คืน `250,206` ตรง Web. ห้ามใช้ primary OID แบบ universal โดยไม่มี profile/calibration.
- รายการจาก Bom ระบุ C358 แต่เครื่องใน slot ทดสอบตอบ identity เป็น `KONICA MINOLTA bizhub C368`; ต้องใช้ identity จริงในการเลือก profileและไม่เก็บ network address ในรายงาน.
- Deployed Registration API มี schema-v2 `serial_number` gate ค้างจาก V5.1; local implementation ต้อง preserve `serial_number` และไม่ยิง/แก้ Production จนได้รับอนุมัติ.

## Decisions and Changes

- 2026-08-25 — Freeze Shared Contract `v5.2-shared-2026-08-25-r2`: public key ใช้ raw Ed25519 32 bytes แบบ unpadded base64url, hash decoded raw bytes, schema-v3 Registration สำเร็จเป็น `registered`, Meter response ต้องมี `accepted_observations`, Status รองรับ token rotation และ Offline License ต้องมี `algorithm: Ed25519`.
- 2026-08-25 — ใช้ Desktop local-first + modular Host monolith; ไม่สร้าง microservices.
- 2026-08-25 — V5.2 เริ่ม `5.2.0`; V5.1 artifacts/evidence เป็น immutable history และไม่ rename ย้อนหลัง.
- 2026-08-25 — server เป็น authority ของ last heartbeat, last meter changed และ alert state; client ส่งเฉพาะ observation ที่ allow-list.
- 2026-08-25 — no-print activity เป็น warning; client-offline เป็น connectivity state และ suppress no-print ที่ซ้อนกัน.
- 2026-08-25 — branch เริ่มจาก `22a67176acc6f1298c07076901c1cdd9d867821c`; canonical checkout ที่ dirty ไม่ถูกแก้/reset.
- 2026-08-25 — Bom กำหนดให้ UI ทั้งหมดคงเดิม และให้ milestone แรกแก้เฉพาะโครงสร้างอ่าน Meter หลายรุ่น.
- 2026-08-25 — ใช้ C450i/C750i เป็น V5.1 regression control และทดสอบจริงเพิ่มอีก 9 รายการ.
- 2026-08-25 — Discovery แนะนำ targeted exact SNMP GET เป็น Total Meter base; Web protocol เป็น capability แยก ไม่ใช้การล้มเหลวของ Web/Walk ปฏิเสธ Total ที่ exact GET ยืนยันได้.
- 2026-08-25 — รุ่นเก่า C7090/C84hc/C5070 อาจปฏิเสธการเชื่อมต่อ Web เมื่อมีผู้ใช้อื่นล็อกอินอยู่; SNMP targeted read จึงเป็น primary path และ Web session ต้องเป็น single-session, bounded และ logout เสมอ.
- 2026-08-25 — C5070 รองรับ public legacy XML ที่ `/wcd/system_counter.xml`; adapter ต้องอ่าน `TotalCounter/Type=Total/Count` แล้ว normalize เป็น Total Meter contract เดียวกับ JSON โดยไม่ส่ง counter ย่อยเป็น telemetry.
- 2026-08-25 — C12010S ต้องเลือก KM private Total OID ที่ Web-calibrated; targeted read หมายถึงอ่าน candidate OIDs แบบ exact GET แล้วเลือกตาม explicit model/capability profile ไม่ใช่เลือก Printer-MIB primary เหมือนกันทุกเครื่อง.
- 2026-08-25 — C7090 legacy XML profile ใช้ aggregate `TotalCounter/Type=Total/Count`; Printer-MIB และ KM private candidates ตรง Web จึงเลือก Printer-MIB primary ได้สำหรับรุ่นนี้โดยยังตรวจ fallback candidate.
- 2026-08-25 — Web Meter transport ต้องรองรับ TLS 1.1/1.2/1.3 และ negotiate เวอร์ชันสูงสุด; legacy TLS/renegotiation เป็น explicit device capability ไม่ใช่ global downgrade. Production trust ใช้ certificate pin/customer CA ไม่ใช่ปิด verification.
- 2026-08-25 — C458 handshake จริงผ่าน TLS 1.1 และ 1.2 แต่ไม่รองรับ TLS 1.3; Python custom SSL context ที่ scope เฉพาะ request ผ่าน 1.1/1.2 โดยใช้ legacy-server-connect. Capability test ปิด verification ชั่วคราวเท่านั้นและไม่ใช่ Production implementation.
- 2026-08-25 — C458 เป็น admin-only legacy XML profile (`/wcd/a_system_counter.xml`): ใช้ bounded Admin session, อ่าน aggregate Total แล้ว logout เสมอ. Targeted SNMP ยังเป็น primary path ที่เหมาะกว่าเพื่อลด single-session contention; Web ใช้ calibration/validation.
- 2026-08-25 — Implemented profile registry เฉพาะรุ่นที่มีหลักฐาน: C5070/C7090/C12010S ใช้ targeted-only SNMP + public legacy XML; C458 ใช้ targeted-only SNMP + admin legacy XML + TLS 1.1 legacy compatibility แบบ scoped. C368/C84hc ยังเป็น generic จน real-device evidence ผ่าน.
- 2026-08-25 — Scheduler ไม่เพิ่ม Web failure counter และไม่เปลี่ยนเครื่องเป็น Offline เมื่อผลเป็น `session_busy` หรือ endpoint `unsupported` ขณะที่ SNMP ยังตอบ; สองผลนี้ถูก log เป็น warning แยกจาก connectivity failure.
- 2026-08-25 — Canonical Desktop/Host request ใช้ `docs/V5_2_HOST_API_IMPLEMENTATION_REQUEST.md` SHA-256 `4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd`.
- 2026-08-25 — Status และ Meter ใช้ interval `21,600s` + jitter ±10%, startup/network cooldown `900s`, server clamp `3,600–43,200s`, outbox latest Status 1 + latest Meter 1 และ retry `15m → 1h → 6h` โดยเคารพ `Retry-After`; Host offline threshold เป็น `259,200s`, ส่วน no-print `86,400s` ใช้เฉพาะ online + Meter ok.
- 2026-08-25 — Installation identity เป็น Ed25519; private key และ issued token ผ่าน macOS Keychain/Windows Credential Manager abstraction เท่านั้น. Desktop ไม่มีช่อง/ค่า shared API key และ default legacy V2 coordinator ถูก disable สำหรับ `5.2.x`.
- 2026-08-25 — Exact seam สำหรับ Final API bundle คือ `services/contract_adapters/v1_draft.py`; เปลี่ยน canonicalization/golden vectors ผ่าน adapter โดยไม่รื้อ outbox, scheduler หรือ Meter business logic.
- 2026-08-25 — API intake pack SHA-256 `ecbb03e83c64e9df406d6425293f52ec2366a8d166c13da0b9853f576bc2a35a` และ OpenAPI SHA-256 `c0e21b6e63920dcbbb9b5ef1f1115c053e78bb5563a76962779003702609166a` เป็น V5.1 schema 1/2 reference-only; ไม่รัน `curl-examples.sh`, ไม่คัดลอก secret และไม่ใช้เป็น Production config.
- 2026-08-25 — Draft Meter unavailable serialization ใช้ `status=unavailable` กับ `total_meter=null`; ต้องยืนยันกับ Final golden vectors ก่อน Staging และไม่ทำ silent fallback หากไม่ตรง.
- 2026-08-25 — Customer artifact builders ของ V5.2 fail-closed จน Final schema-3 vectors และ Joint Staging E2E ได้รับ approval; milestone นี้ไม่สร้าง artifact.
- 2026-08-25 — Application lifecycle ใช้ `V52RuntimeCoordinator` แบบ explicit-client-only; app start/restart อ่าน durable state, OS network recovery เคารพ cooldown 15 นาที, graceful stop เก็บ outbox สำหรับ restart recovery และ Meter observation ไม่ส่งทันทีแต่รวมใน batch รอบ 6 ชั่วโมง.
- 2026-08-25 — Offline License mode หยุด scheduler และบล็อก Registration/Status/Meter telemetryจริงโดยไม่ลบ Device/DB/History/Billing; เปลี่ยนกลับ Online ได้โดยใช้ state เดิมและไม่มี legacy schema-2 fallback.
- 2026-08-25 — Wizard คง 4 ขั้นเดิมและ Settings ใช้ card เดิม เพิ่มเฉพาะ Online/Offline mode, retry, export `.komirequest`, import `.komilicense`, expiry/bound devices และ support detail แบบซ่อน; user UI ไม่แสดง API key, token, public key หรือ raw error.

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-25 08:43 +07 | Git/worktree baseline audit | ระบุ dirty canonical และ approved source โดยไม่ทับ user changes | canonical มี modified `PROJECT.md` + untracked docs; remote/current Production Registration ตรงที่ `22a6717`; branch Phase 6 เป็น ancestor | PASS | `git status`, `worktree list`, `rev-parse`, `merge-base` |
| 2026-08-25 08:45 +07 | Focused V5.1 baseline | version/registration tests ต้องผ่านก่อนเริ่ม migration | 76 passed in 2.69s | PASS | pytest: release builder, launchers, registration envelope/client/worker/repository/notice |
| 2026-08-25 09:07 +07 | 11-device identity/Total targeted probe | exact GET ต้องคืน model/serial/Total โดยไม่ write | ทั้ง 11 ตอบรอบแรก; Printer-MIB Total และ KM private Total ตรงกันทุกเครื่อง; พบ C368 แทนรายการ C358 | PASS WITH IDENTITY CORRECTION | live SNMP v2c GET, 9 exact OIDs/device |
| 2026-08-25 09:13 +07 | Modern Web Connection public/admin read | Web Total ต้องเท่ากับ SNMP Total | C450i, C750i, C300i admin ผ่าน; 950i, C751i public ผ่าน; Total ตรงทุกเครื่อง | PASS — 5 MODELS | read-only Web JSON API + logout |
| 2026-08-25 09:17 +07 | HTTP/legacy Web capability | แยก protocol โดยไม่เดา endpoint | C3350i public JSON ผ่าน HTTP; C7090 ใช้ legacy XML; C458/C368 ถูก OpenSSL บล็อกเพราะ unsafe legacy renegotiation; C84hc/C5070 Web timeout | PARTIAL / HOLD BY MODEL | HTTP/HTTPS reachability and bounded read-only requests |
| 2026-08-25 09:23 +07 | AccurioPress C7090 legacy Web Meter | legacy XML Total ต้องเท่ากับ SNMP observation ใกล้เวลาเดียวกัน | XML `system_counter.xml` Total เพิ่มจาก SNMP 1 หน้าระหว่างการอ่านและรักษาความหมายเดียวกัน | PASS — REAL DEVICE | live legacy Web XML session, no mutation |
| 2026-08-25 09:27 +07 | Existing `SnmpTotalProbe` on 11 devices | V5.1 probe ควรอ่าน Total ได้ทุกเครื่องที่ exact OID ตอบ | ผ่าน 9/11; C84hc/C5070 timeout เพราะ bulk walk แม้ exact OID เคยตอบ | FAIL — REPRODUCED | current source `SnmpTotalProbe.read` |
| 2026-08-25 09:31 +07 | Targeted Total stability 3 cycles | Primary Printer-MIB และ KM private Total ต้องตรงและตอบซ้ำ | ผ่าน 10/11; C5070 ผ่าน 3/3; C84hc timeout 3/3 หลัง first-pass success | PASS 10 / HOLD 1 | live exact SNMP GET, three cycles |
| 2026-08-25 09:55 +07 | C5070 fresh targeted-only production read | อ่าน identity/serial/aggregate Total ได้ 3 รอบโดยไม่ Web login, walk หรือ write และ Total OID สองตำแหน่งต้องตรงกัน | เครื่องตอบ `KONICA MINOLTA AccurioPress C5070`; Printer-MIB Total = KM private Total = `25,121` ทั้ง 3 รอบ | PASS — REAL DEVICE 3/3 | live SNMP v2c exact GET, five allow-listed OIDs per cycle, 2-second pacing |
| 2026-08-25 09:58 +07 | C5070 bounded public Web capability probe | Web root และ legacy counter path ต้องตอบโดยไม่รบกวน session อื่น | Web root ตอบ HTTP 200 และระบุ legacy `/wcd/` flow; `system_counter.xml` ตอบ XML `DirectAccessError` ระหว่างที่ browser session อื่นยัง active | HOLD — SESSION BUSY, NOT UNSUPPORTED | read-only HTTP GET; no credentials, login, write or session takeover |
| 2026-08-25 10:00 +07 | C5070 public legacy XML read after active session closed | XML aggregate Total ต้องตรงกับ screenshot และ targeted SNMP โดยไม่ admin login/write | PublicUser XML `TotalCounter Type=Total Count=25,121`; fresh Printer-MIB Total = KM private Total = `25,121`; Copy `5,478` + Print `19,643` = Total | PASS — REAL DEVICE WEB/SNMP | live HTTP legacy XML + live exact SNMP GET; admin credentials not used |
| 2026-08-25 10:08 +07 | C12010S targeted SNMP candidate stability | identity/serial และ candidate Total ต้องตอบซ้ำโดยไม่ walk/write | 3/3 stable; Printer-MIB `250,132`, KM private `250,206`, difference 74 | PASS READ / HOLD SELECTION | live SNMP v2c exact GET, five allow-listed OIDs, 2-second pacing |
| 2026-08-25 10:08 +07 | C12010S public legacy XML calibration | Web aggregate Total ต้องระบุ SNMP candidate ที่ถูกต้อง | PublicUser XML Total `250,206` ตรง KM private OID ก่อน/หลัง Web; Printer-MIB primary ไม่ตรง | PASS — REAL DEVICE WEB-CALIBRATED | live HTTP legacy XML + bracketing targeted SNMP; no admin credential/write |
| 2026-08-25 10:10 +07 | C12010S visual Web Meter confirmation | ค่าที่ผู้ใช้เห็นบน Web ต้องตรงกับ XML capture | screenshot แสดง Total `250,206`, Duplex `68,770`, Used Paper `101,319`, 2-in-1 `210`, Print Total `224,150` และรายละเอียด Print ตรง XML ทุกค่า | PASS — VISUAL MATCH | Bom-supplied Web Connection screenshot captured at 10:08:44; extracted values only retained |
| 2026-08-25 10:13 +07 | C7090 fresh targeted SNMP stability | identity/serial และ Total candidates ต้องตอบซ้ำโดยไม่ walk/write | 3/3; Printer-MIB = KM private = `219,122` | PASS — REAL DEVICE 3/3 | live SNMP v2c exact GET, five allow-listed OIDs, 2-second pacing |
| 2026-08-25 10:13 +07 | C7090 visual + public legacy XML calibration | screenshot/XML/SNMP ต้องตรงกันหรืออยู่ใน bounded live increment | screenshot `219,122`; PublicUser XML `219,122`; post-Web SNMP candidates `219,122`; detailed visible counters match XML | PASS — EXACT MATCH | Bom screenshot 10:12:32 + live HTTP XML 10:13:24 + bracketing SNMP 10:13:03–10:13:35 |
| 2026-08-25 10:17 +07 | C458 visual Web + targeted SNMP baseline | screenshot aggregate Total ต้องตรง exact SNMP candidates | screenshot Total `243,744`; Printer-MIB = KM private = `243,744`, stable 3/3 | PASS — VISUAL/SNMP | five Bom screenshots 10:16:30–10:16:56 + live exact GET 10:17:48–10:17:52 |
| 2026-08-25 10:18 +07 | C458 automated Web route discovery | แยก public/admin route โดยไม่ takeover session | HTTPS root 200; `PublicUser=false`; public counter redirects to `SYS_COU`, admin counter redirects to `ASYS_COU` login | HOLD — ADMIN SESSION REQUIRED | read-only HTTPS GET; no login/write; active browser session preserved |
| 2026-08-25 10:20 +07 | C458 TLS version matrix | connector/runtime ต้องพิสูจน์ TLS 1.1/1.2/1.3 แยกกัน | OpenSSL and scoped Python context: TLS 1.1 PASS, TLS 1.2 PASS, TLS 1.3 handshake FAIL because device does not support it | PASS — DEVICE CAPABILITY 1.1/1.2 | read-only TLS handshake + HTTP root; Production verification policy not implemented yet |
| 2026-08-25 10:32 +07 | C458 bounded Admin Web Meter read and logout | session ที่ Bom ล็อกอินต้องเปิด admin-only XML, ค่า aggregate ต้องตรง SNMP/visual และต้องออกจาก Admin หลังอ่าน | `/wcd/a_system_counter.xml` แสดง Total `243,744`; Copy `157,635` + Print `86,041` + Scan/Fax output `64 + 4` = Total; Black `171,719` + Color `72,025` = Total; Logout confirmation completed and browser returned to `/wcd/top.xml` | PASS — REAL DEVICE ADMIN XML | Chrome authenticated DOM read; password/cookie/session data not inspected or retained |
| 2026-08-25 10:48 +07 | Multi-model Meter focused implementation tests | targeted SNMP, explicit profile, legacy XML parser, bounded Admin logout, TLS scope และ reader routing ต้องผ่านโดย UI เดิมไม่เปลี่ยน | focused suite `84 passed`; session busy ไม่เพิ่ม failure/Offline; scoped Ruff และ compileall ผ่าน | PASS — LOCAL | pytest + Ruff + compileall; synthetic XML contains no production data |
| 2026-08-25 10:53 +07 | Post-implementation real-device SNMP smoke | V5.1 controls และ explicit profile ต้องคืน identity/Total โดยไม่ write | C450i `266,857`, C750i `444,193`, C12010S `250,214` using KM private OID, C458 `243,744` using Printer-MIB; profile-scoped C458 TLS handshake succeeded | PASS — 4 REAL DEVICES | live exact SNMP GET + read-only TLS handshake; no credential used |
| 2026-08-25 11:00 +07 | Legacy device/session availability smoke | read-only public XML หรือ exact SNMP ต้องคืนค่าหรือผลแยกที่ไม่ถูกตีความเป็น fault | C5070/C7090 bounded requests timed out; C12010S public XML returned `session_busy`; stopped further probes and retained earlier PASS evidence | HOLD — AVAILABILITY, NOT PRODUCT FAIL | bounded read-only requests; no retry storm, login or mutation |
| 2026-08-25 11:06 +07 | Full V5.1 regression after Meter profile implementation | DB/History/Billing/Excel/UI/Registration และ existing Meter behavior ต้องไม่ถอย | `546 passed in 30.33s`; scoped Ruff, compileall and `git diff --check` passed; one existing explicit insecure virtual-printer warning | PASS — LOCAL REGRESSION | full pytest + scoped static/compile checks |
| 2026-08-25 11:09 +07 | Internal project dashboard sync | checklist/progress จาก canonical Workbook ต้อง sync โดยไม่สร้าง workbook ซ้ำหรือ deploy Production | sync สำเร็จ 25 projects และ Codex usage snapshot; live publish ไม่ถูกอ้างหรือดำเนินการ | PASS — INTERNAL SYNC | `dashboard:quick`; local portfolio data only |
| 2026-08-25 13:15 +07 | V5.2 contract core fail-first | tests ใหม่ต้องพิสูจน์ว่า implementation ยังขาดก่อนลงมือ | collection ล้มด้วย 5 missing-module errors ตามที่คาด | FAIL-FIRST CONFIRMED | schema3/identity/outbox/offline-license/version tests |
| 2026-08-25 13:32 +07 | Local V5.2 fixture E2E | Register → vault token → Status → Meter ต้องผ่านโดยไม่มี shared key/Production call | local injected stub ผ่าน; strict allow-list, signature, fingerprint, 429/422 handling ผ่าน | PASS — LOCAL ONLY | synthetic fixture transport; no external endpoint |
| 2026-08-25 13:45 +07 | V5.2 focused contract gates | version, identity, signing, privacy, scheduler, outbox, retry, Offline License, migration และ legacy transport gate ต้องผ่าน | `57 passed in 1.88s` | PASS — LOCAL | pytest focused suite |
| 2026-08-25 13:46 +07 | Full Python regression after V5.2 core | DB/History/Billing/Excel/UI/Meter/Registration behavior ต้องไม่ถอย | `569 passed in 39.16s`; warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม | PASS — LOCAL REGRESSION | full pytest, offscreen Qt |
| 2026-08-25 13:47 +07 | Static/compile and version gate | changed Python, build metadata และ canonical contract ต้องสอดคล้อง | scoped Ruff 2 groups PASS; compileall PASS; version gate รายงาน `5.2.0` PASS | PASS | Ruff, compileall, `python -m tools.version_gate` |
| 2026-08-25 13:48 +07 | Web regression/security/build | current Web 5.2 metadata และ security behavior ต้อง build ได้ | TypeScript lint PASS; security 2/2; Next 16.3.2 production build PASS; npm audit 0 vulnerabilities | PASS — LOCAL | npm lint/test/build/audit |
| 2026-08-25 13:49 +07 | Changed-source secret/privacy scan | ห้ามมี credential/private key/token value, production IP, forbidden customer data หรือ unsafe artifact | 57 changed/untracked source files ผ่าน category-only scan; `git diff --check` ผ่าน | PASS — SANITIZED | `release_safety` + added-line privacy patterns; no secret values printed |
| 2026-08-25 13:52 +07 | Internal project dashboard sync | child workbook เดียวต้องสะท้อน milestone โดยไม่ publish/deploy | sync สำเร็จ 26 projects และ Codex usage snapshot; ไม่มี live publish | PASS — INTERNAL SYNC | `dashboard:quick` |
| 2026-08-25 14:12 +07 | V5.2 runtime + bilingual Wizard/Settings focused gates | lifecycle, cooldown, Offline no-telemetry, Notice gate, UI states/actions และ error curation ต้องผ่าน | combined contract/runtime/UI integration subset `101 passed in 8.44s` | PASS — LOCAL | injected client/runtime fixtures only; no external endpoint |
| 2026-08-25 14:13 +07 | Full Python regression after lifecycle/UX integration | DB/History/Billing/Excel/Meter/UI/Registration ต้องไม่ถอย | `585 passed in 33.09s`; warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม | PASS — LOCAL REGRESSION | full pytest, offscreen Qt |
| 2026-08-25 14:14 +07 | Static/version/Web/security gates | changed code compile, V5.2 metadata และ Web build/security ต้องผ่าน | scoped Ruff PASS; compileall/diff-check PASS; version gate `5.2.0` PASS; Web TypeScript/security 2/2/Next build/npm audit 0 ผ่าน | PASS — LOCAL | no artifact or deployment |
| 2026-08-25 14:15 +07 | Changed production-source secret/privacy scan | source ใหม่ห้ามมี credential/private key/token valueหรือ telemetry นอก allow-list | changed production source ผ่าน `release_safety`; strict contract/runtime/UI privacy tests 49 ผ่าน;ไม่มีค่าลับถูกพิมพ์ | PASS — SANITIZED | category-only result; no raw payload/secret output |
| 2026-08-25 14:18 +07 | Internal project dashboard sync | child workbook เดียวต้องสะท้อน runtime/UX milestone โดยไม่ publish/deploy | sync สำเร็จ 26 projects และ Codex usage snapshot; ไม่มี live publish | PASS — INTERNAL SYNC | `dashboard:quick` |
| 2026-08-25 14:20 +07 | Verified-learning observation | verified local fix ควรถูกส่งเข้า Knowledge API โดยไม่แต่ง evidence | API ตอบสำเร็จแต่ `observed=false`, `promoted=false`, `notePath=null`; ไม่มี learning ถูก persist และไม่ถือว่าเป็น knowledge promotion | HOLD — KNOWLEDGE BACKEND UNAVAILABLE | `POST /api/knowledge/learnings/observe`; product milestone ไม่ถูกลดระดับ |
| 2026-08-25 14:42 +07 | Shared Contract R2 fail-first compatibility | API-compliant Meter/Status/Offline License และ raw-key proof ต้องผ่าน Desktop จริง | ก่อนแก้ Meter/Status คืน `contract_invalid`; Offline License ปฏิเสธ `algorithm`; Node SPKI importer ปฏิเสธ Desktop raw key | FAIL-FIRST CONFIRMED | isolated local cross-contract test; no Host/Production call |
| 2026-08-25 14:49 +07 | API Pack R2 local simulation | revised OpenAPI/auth/hash/response/license rules และ legacy compatibility ต้องผ่าน | API contract `41/41`; serial/privacy `30/30`; syntax/OpenAPI/dry-run ผ่าน | PASS — LOCAL SIMULATION | eight-file Contract/Test pack; not PHP/HTTP/deployed proof |
| 2026-08-25 14:51 +07 | Desktop/API cross-language proof | Desktop-signed Registration ต้อง verify ด้วย Node/API และ Node/Host License ต้อง verify ด้วย Desktop | Registration proof PASS with raw key 32 bytes; Offline License proof/hash/algorithm PASS | PASS — LOCAL CROSS-LANGUAGE | synthetic ephemeral keys; no private key or token retained/logged |
| 2026-08-25 14:55 +07 | Full regression after Shared Contract R2 | DB/History/Billing/Excel/Meter/UI/Registration และ release manifest ต้องไม่ถอย | first full run caught stale manifest expectation; corrected test then `589 passed`; one existing Virtual Printer TLS warning | PASS — LOCAL REGRESSION | full offscreen pytest; focused repair `1 passed` |
| 2026-08-25 14:56 +07 | Static/Web/security gates after R2 | changed Python/Web build/security/dependency gate ต้องผ่าน | Ruff/compileall/diff-check PASS; Web TypeScript, security 2/2, Next build and npm audit 0 passed | PASS — LOCAL | no Host/Production call or customer artifact |
| 2026-08-25 15:23 +07 | Windows build metadata portability | Windows ARM64 VM build tool ต้องอ่าน V5.2 metadata ได้โดยไม่ import runtime cryptography และห้ามลด runtime dependency | แยก dependency-free `v5_2_contract_metadata.py`; regression จำลอง block `cryptography` แล้ว import builder ผ่าน; focused 36 passed; full regression `590 passed`; Ruff/version/diff-check ผ่าน | PASS — SOURCE | commit `7299b2049d2cbffb93be3abf2c366a2e5e501809`; runtime lock ไม่ถูก downgrade |
| 2026-08-25 15:35 +07 | Windows V5.2 RC build inside VM | clean source archive ต้องสร้าง Windows x64 installer พร้อม identity/evidence โดยไม่เปิด Registration/Update หรือยกระดับ VM เป็น native | EXE `111,415,182` bytes; SHA-256 `ed502ddf943ecdf7f8a5b88d016ff4f5d5b441215a183d8eeae7582ce42c2571`; version `5.2.0`; source `7299b2049d2c`; inventory `8,587` files; Registration fail-closed; Update absent; `production_go=false` | PASS — WINDOWS 11 ARM64 VM / X64-EMULATION PREFLIGHT | unsigned Authenticode `NotSigned`; not native Windows x64 proof |
| 2026-08-25 15:41 +07 | Install/first-run/restart/database smoke from actual EXE | installer ต้องติดตั้งสำเร็จ, เปิด V5.2 แบบไม่มี Terminal, ปิด/เปิดใหม่ได้ และไม่ทำให้ฐานข้อมูลเดิมเสีย | installer exit `0`; installed runtime files present; title `ตั้งค่า KOMI Report V5.2.0`; launch/restart process count `1/1`; hidden launcher `wscript.exe → pythonw.exe`; DB integrity ก่อน/หลัง restart `ok`; ปิดหน้าต่างซ่อนไป Tray และเรียกกลับได้ | PASS — VM INSTALLED SMOKE | previous UAT install path preserved as expected upgrade behavior; not native x64/customer proof |
| 2026-08-25 15:46 +07 | Final Windows delivery folder safety | ไฟล์สำหรับ Bom ต้องอยู่ชุดเดียว, checksum/manifest ตรง และไม่มี customer DB/export/log/credential/secret | checksum verified; release/tree safety PASS; focused Release/Tray suite `32 passed`; root มี EXE + README + checksum และแยก evidence ใน subfolder | PASS — UAT DELIVERY | `/Users/wongsakornu-phonram/Projects/dev/KOMI-Report-V5.2-Installer`; RELEASE HOLD remains |

## Captured Evidence — AccurioPress C5070

หลักฐานนี้เก็บเฉพาะ identity และ Meter ที่จำเป็นจากการอ่านจริงแบบ read-only; ไม่เก็บ raw XML เพราะ response มีข้อมูล configuration/contact ที่อยู่นอก Privacy boundary และไม่เก็บ credential, cookie หรือ Web session.

- Device identity: `KONICA MINOLTA AccurioPress C5070`; serial `AEEJ041000007`.
- Visual Web evidence supplied by Bom at approximately `2026-08-25 09:54:40 +07`: Total Counter `25,121`.
- Public legacy XML observation at `2026-08-25 10:00:24 +07`: `/wcd/system_counter.xml`, `LoginMode=PublicUser`, no administrator credential used.
- Fresh targeted SNMP observation at `2026-08-25 10:00:52 +07`: Printer-MIB Total `25,121`; KM private Total `25,121`.
- Session behavior: active Web session returned XML `DirectAccessError`; after Bom logged out, the bounded public flow succeeded. Treat this as `session_busy`, not unsupported/offline.

| Counter group | Field/type | Meaning | Observed |
|---|---|---|---:|
| Total | `Total` | aggregate Total Meter | 25,121 |
| Total | `DuplexTotal` | device-reported duplex counter | 7,335 |
| Total | `Document` | device-reported originals counter | 11 |
| Total | `Paper` | device-reported used-paper counter | 8,236 |
| Total | `TotalLarge` | aggregate large-size counter | 11,587 |
| Total | `PrintPageTotal` | firmware-specific print-page counter; not selected | 0 |
| Total | `Nin12in1` / `Nin14in1` / `Nin1Other` | 2-in-1 / 4-in-1 / other N-in-1 | 0 / 0 / 0 |
| Total | `Nin1TotalRate` | device-reported N-in-1 rate | 0.000 |
| Copy | `FullColorTotal` / `BwTotal` | color / black copy | 1,398 / 4,080 |
| Copy | `MonoColorTotal` / `BiColorTotal` | single-color / two-color copy | 0 / 0 |
| Copy | `Total` | all copy impressions | 5,478 |
| Copy large | `FullColorLarge` / `BwLarge` / `TotalLarge` | large-size color / black / total copy | 666 / 2,014 / 2,680 |
| Print | `FullColorTotal` / `BwTotal` | color / black print | 19,360 / 283 |
| Print | `MonoColorTotal` / `BiColorTotal` | single-color / two-color print | 0 / 0 |
| Print | `Total` | all print impressions | 19,643 |
| Print large | `FullColorLarge` / `BwLarge` / `TotalLarge` | large-size color / black / total print | 8,768 / 139 / 8,907 |
| Scan/Fax | document/large/scan-print/OCR counters | available from XML but outside Total Meter telemetry | all observed 0 |

Consistency checks:

- Copy `5,478` + Print `19,643` = aggregate Total `25,121`.
- Full Color `1,398 + 19,360` = `20,758`; Black `4,080 + 283` = `4,363`; `20,758 + 4,363 = 25,121`.
- Copy Large `2,680` + Print Large `8,907` = Total Large `11,587`.
- V5.2 normalization target remains only `model`, `serial_number`, selected slot, `total_meter`, `meter_observed_at` and `heartbeat_at`; detailed counters remain local validation evidence and are not Host telemetry.

## Captured Evidence — AccurioPress C12010S

- Device identity: `KONICA MINOLTA AccurioPress C12010S`; serial `AE95041000001`.
- Targeted SNMP observations at `2026-08-25 10:08:11–10:08:16 +07`: Printer-MIB `250,132`; KM private `250,206`; stable 3/3 but unequal.
- Public legacy XML observation at `2026-08-25 10:08:37 +07`: aggregate Total `250,206`, `LoginMode=PublicUser`.
- Fresh SNMP after Web at `2026-08-25 10:08:47 +07`: values unchanged; selected Total source is KM private OID because it matches Web.
- Bom-supplied visual Web evidence at approximately `2026-08-25 10:08:44 +07` matches XML: Total `250,206`; Duplex `68,770`; Used Paper `101,319`; 2-in-1 `210`; 4-in-1/Other `0`; Total Print Rate `0.207`.
- The screenshot also shows `Low Paper`; this is a local device-status warning, not part of aggregate Total Meter and not included in Host telemetry for this milestone.
- Aggregate consistency: Copy Total `26,056` + Print Total `224,150` = Total `250,206`.
- Additional local-only counters captured for profile evidence: Duplex `68,770`; Document `16`; Paper `101,319`; TotalLarge `110,935`; N-in-1 2-in-1 `210`; other N-in-1 `0`.
- Copy details: BW `7,383`; Full Color `18,643`; Special Color `524`; Total `26,056`; large-size Total `13,023`.
- Print details: BW `8,243`; Full Color `215,863`; Special Color `24,911`; Total `224,150`; large-size Total `110,470`.
- Special Color and large-size counters are firmware categories whose overlap/additivity is not assumed without model documentation; they are not used to calculate aggregate Total and are not Host telemetry.
- Sanitization: raw XML, credential, cookie, IP, contact/configuration fields and detailed device status are not persisted.

## Captured Evidence — AccurioPress C7090

- Device identity: `KONICA MINOLTA AccurioPress C7090`; serial `ACW3041000001`.
- Bom-supplied visual Web evidence at approximately `2026-08-25 10:12:32 +07`: Total `219,122`; Duplex `81,508`; Used Paper `126,845`; 2-in-1 `2,427`; 4-in-1 `5`; Other `0`; Total Print Rate `1.917`.
- Targeted SNMP at `2026-08-25 10:13:03–10:13:08 +07`: Printer-MIB Total = KM private Total = `219,122`, stable 3/3.
- Public legacy XML at `2026-08-25 10:13:24 +07`: aggregate Total `219,122`, `LoginMode=PublicUser`; post-Web SNMP at `10:13:35` remained `219,122`.
- Aggregate consistency: Copy Total `28,077` + Print Total `191,045` = Total `219,122`.
- Color consistency: Copy/Print Full Color `21,499 + 182,476 = 203,975`; Copy/Print Black `6,578 + 8,569 = 15,147`; `203,975 + 15,147 = 219,122`.
- Large-size consistency: Copy BW `4,054` + Copy Full Color `10,970` + Print Large Total `130,486` = aggregate TotalLarge `145,510`.
- Screenshot-visible Print details match XML: Full Color `182,476`; Black `8,569`; Total `191,045`; Large Full Color `126,969`; Large Black `3,517`; Large Total `130,486`.
- Additional local-only evidence: Document `28`; scan/fax/OCR counters all observed `0`. Detailed counters remain outside Host telemetry.
- Sanitization: screenshot values were transcribed; raw XML, screenshot copy, credential, cookie, IP and unrelated contact/configuration fields were not persisted.

## Captured Evidence — bizhub C458

- Device identity: `KONICA MINOLTA bizhub C458`; serial `A79M041012504`.
- Five Bom-supplied Web screenshots at approximately `2026-08-25 10:16:30–10:16:56 +07` show aggregate Total `243,744`.
- Targeted SNMP at `2026-08-25 10:17:48–10:17:52 +07`: Printer-MIB Total = KM private Total = `243,744`, stable 3/3.
- Authenticated Admin Web observation at `2026-08-25 10:31–10:32 +07`: `/wcd/a_system_counter.xml` identified `Model Name:bizhub C458` and returned aggregate Total `243,744`, exactly matching the earlier visual and targeted SNMP evidence.
- Session boundary: Bom entered the password directly in Chrome; the read inspected visible Meter DOM only. The bounded flow then used the device Logout confirmation and returned to `/wcd/top.xml`.
- Aggregate composition visible on Web: Copy `157,635` + Print `86,041` + Scan/Fax output Black `64` + Full Color `4` = Total `243,744`. Therefore `Total (Copy + Print) 243,676` is not the aggregate machine Total.
- Total by Color also reconciles: Black `171,719` + Color `72,025` = `243,744`.
- Additional visual evidence: Duplex `23,123`; Duplex Rate `10.542`; Originals `244,108`; Paper Counter `219,339`; Total Pages Output `242,462`; 2-in-1 `498`; 4-in-1 `2`; Other `14`; Total Print Rate `0.234`.
- Copy details: Black `143,334`; Full Color `14,211`; Single Color `85`; 2 Color `5`; Total `157,635`; Large Size `1,093`.
- Print details: Black `28,321`; Full Color `57,651`; 2 Color `69`; Total `86,041`; Large Size `3,631`.
- Scan/Fax details are local-only validation evidence: Scans `438,708`, Fax TX `139`, Fax RX `1`, Scan TX Black `156,661`, Scan TX Color `274,773`; these do not become Host telemetry.
- TLS capability: TLS 1.1 and 1.2 handshake/HTTP succeed; TLS 1.3 fails at the device. Runtime can scope legacy TLS to a custom request context; certificate pin/customer trust still requires Production implementation and tests.
- Web automation status: `PASS — ADMIN-ONLY LEGACY XML`. `PublicUser=false`, so an unauthenticated request correctly redirects to login; an authenticated bounded session reads the Meter and logs out. Session contention remains a modeled outcome, not unsupported/offline.
- Sanitization: extracted values only; raw XML/screenshots, credential, cookies/session material, IP, certificate subject/contact fields and unrelated configuration were not persisted.

## Definition of Done

- [x] Current Desktop/runtime/build metadata รายงาน `5.2.0` จาก authority เดียว และ validator ปฏิเสธ non-5.2.x
- [x] UI, config, pyproject, Web metadata, PyInstaller/Inno และ API-reported version ใน current source ตรงกัน; customer artifact builder fail-closed ก่อน external gates
- [x] V5.1 artifacts/commits/evidence ไม่ถูก rename หรือแก้เป็น V5.2 ย้อนหลัง
- [ ] Production Print profile ที่รองรับมี read-only model/OID/Web Meter evidence จากเครื่องจริง; unknown model fail-closed โดยไม่เดา
- [ ] Web transport รองรับ TLS 1.1/1.2/1.3 แบบ profile-scoped, negotiate สูงสุด, enforce trust/pin และไม่มี global TLS downgrade
- [x] Local schema-3 Registration/Status/Meter ส่งเฉพาะ allow-list และ Total Meter aggregate; Registration Data Notice ตรง payload ที่ implement
- [x] Desktop duplicate/retry/coalesce/restart/counter decrease-replacement serialization ผ่าน local tests; server-side last meter change ยังเป็น Host gate
- [ ] Host แยก no-print warning จาก client-offline และใช้ข้อความ “ควรตรวจสอบ” ไม่ฟันธงว่าเครื่องเสีย
- [ ] Quiet-hours/holiday/maintenance/mute ลด false alarm โดยไม่ทำลาย observation/history
- [ ] Dashboard เรียง severity และแสดง last heartbeat, last meter change, allowed model/serial, acknowledge/resolve พร้อม audit
- [ ] Migration/rollback และ regression DB/History/Billing/Excel ผ่าน; ไม่มี forced updater เพิ่มเข้ามา
- [ ] Current-client E2E และ real-device acceptance ผ่านตาม label; packaging Mac/Windows มี manifest/checksum/SBOM และ GO/HOLD ตามหลักฐานจริง
