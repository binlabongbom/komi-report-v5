---
project_id: komi-report-v5-2-production-meter-monitoring
project_name: KOMI Report V5.2
thread_id: 01a03696-8cdf-7023-b5ce-58c090fd09f1
thread_title: KOMI V5.2 — Production Print & Meter Alert
dashboard_visible: true
department: dev
status: testing
progress: 96
owner: VEGA
current_phase: V5.2.1 unsigned release readiness — reviewed source and documentation gates passed; exact-source packaging in progress
current_task: Freeze the reviewed source identity, generate V5.2.1 macOS and Windows ARM64-VM unsigned candidates, and verify manifest/checksum/SBOM identity
next_action: Commit the reviewed source, build both unsigned candidates and record artifact evidence without promoting HOLD to Production GO
problem: Signing/notarization is intentionally deferred; Offline License Host public verification key and Joint Desktop-Staging E2E evidence are unavailable, while 950i/C84hc were current device-availability HOLD during the final bounded probe
updated_at: 2026-08-31T12:32:56+07:00
---

# KOMI Report V5.2 — Production Print & Meter Alert

## Goal

ยกระดับ Build ใหม่เป็น KOMI Report `5.2.1` จาก source identity เดียว และเพิ่มการส่ง Total Meter แบบ aggregate ต่อเครื่องเพื่อให้ Host แยกคำเตือน “ไม่มีการพิมพ์เกิน 1 วัน — ควรตรวจสอบ” ออกจาก “Desktop/การเชื่อมต่อขาดหาย” โดยไม่เดาว่าเครื่องเสียและไม่ขยายข้อมูลเกิน Privacy boundary ที่อนุมัติ.

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

## Progress: 96%

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
- [x] เตรียม Windows VM ให้ Codex สั่ง Start/PowerShell/Shutdown แบบ Headless ผ่าน Guest Control โดยเก็บ credential ใน macOS Keychain และไม่เปิด SSH/WinRM/Network Port
- [ ] build macOS V5.2 artifact จาก source identity เดียว
- [ ] manifest/checksum/SBOM/signing/notarization/native labels ตรงหลักฐาน
- [ ] ตัดสิน GO/HOLD โดยไม่ยกระดับ VM/synthetic/unsigned evidence

### Phase H — Main UI, Legacy Report, Advanced Settings and Customer Guide

#### H0 — Review freeze and implementation boundary

- [x] รวบรวมคอมเมนต์จากหน้าจอจริงของ Main application เป็นรายการเดียวก่อนแก้
- [x] ยืนยันรอบนี้ยังไม่แก้ Source และยังไม่ Build installer ระหว่างรับคอมเมนต์
- [x] ให้ Bom ตรวจแผนรอบนี้ว่าครบ แล้วจึงเริ่มแก้เป็นชุดเล็กที่เปิด Source ให้ลองได้

#### H1 — Existing UI repairs

- [x] หน้าอุปกรณ์: จัดปุ่ม `สถานะการอ่าน` และ `อ่านข้อมูลตอนนี้` ให้อยู่ baseline เดียวกัน แม้มีข้อความ Error ใต้ปุ่ม
- [x] Reports → Usage: กระจายความกว้างคอลัมน์ตารางเต็มพื้นที่อย่างสมดุล ไม่ให้คอลัมน์เดือนกว้างและคอลัมน์ข้อมูลด้านขวาเบียดกัน
- [x] Popup เตือนมีการแก้ไขค้าง: ลดพื้นที่ว่างและแสดงปุ่ม `ตกลง` ครบ ไม่ตัดข้อความบน macOS/Windows
- [x] Native popup: ปุ่มข้อความสั้น `OK`/`Yes`/`No` ต้องคงเป็นปุ่มข้อความ ไม่ถูกตีความเป็นปุ่มไอคอนจากขนาดชั่วคราวก่อน platform layout เสร็จ
- [x] ตารางตั้งเวลาแบบละเอียด: ขยาย `วันที่ทำงาน`, ย้ายหน่วยไปหัว `ตรวจสถานะ (นาที)`/`อ่านมิเตอร์ (นาที)`, ช่องเก็บเฉพาะตัวเลข และบีบคอลัมน์ชื่อช่วงเวลา/ลบ
- [x] Sidebar: เปลี่ยน `ยังไม่มีข้อมูล` เป็น `ยังไม่มีประวัติการอ่าน`; เมื่อมีข้อมูลให้แสดงวัน/เวลาอ่านล่าสุด โดยไม่ทำให้เข้าใจว่าไม่มีเครื่องหรือไม่มี Total Meter

#### H2 — Settings simplification and Advanced Settings

- [x] เปลี่ยน card `ช่วยเหลือและตรวจสอบปัญหา` เป็น `การตั้งค่าขั้นสูง` พร้อมคำอธิบายและปุ่มที่ตรงความหมาย
- [x] ย้าย LAN Web Report ออกจาก Settings หลักไป Advanced Settings ทั้งชุด: service, URL, copy/open, access mode, password และ test/save
- [x] เปิดสิทธิ์ LAN Web Report และเริ่ม Web service อัตโนมัติหลัง Setup สำเร็จ
- [x] เพิ่ม `อนุญาตให้เปิด Web Report โดยไม่ต้องใช้รหัส`; bypass เฉพาะหน้า Report แบบ read-only บน LAN ส่วน Settings, staff tools, mutation API และข้อมูลลับยังต้องป้องกัน
- [x] จัด Advanced Settings เป็น Database/Storage, Program operation, LAN Web Report, Log/Support และ Maintenance
- [x] Database tools รองรับดู/เปลี่ยน Path, Backup, Restore, integrity/repair และลบ/เริ่มใหม่; คำสั่งทำลายข้อมูลต้อง Backup ก่อนและยืนยันซ้ำโดยไม่ใช้ Settings password
- [x] Program tools รองรับ Auto start, background/System Tray, พฤติกรรมปิดหน้าต่าง และตำแหน่งไฟล์
- [x] Log tools รองรับเปิดโฟลเดอร์, Export support bundle, Version/OS/service status และ cleanup ตาม retention โดยไม่รวม credential/token/customer document

#### H3 — Legacy raw-counter storage, reports and Excel

- [x] ตรวจ inventory ของ Counter ที่ Modern JSON, Legacy Public XML และ Legacy Admin XML ส่งจริง โดยไม่เดาช่องที่เครื่องไม่ส่ง
- [x] เพิ่ม durable raw-counter snapshot ต่อเครื่อง/เวลา เก็บ source key + source label + cumulative value ตรงจากเครื่อง และ migration แบบ rollback-safe
- [x] คำนวณยอดใช้งานรายวันจากผลต่าง Snapshot โดยรักษาค่าดิบไว้; counter ลด/reset/replacement ต้องแยกสถานะและห้ามสร้างยอดติดลบ
- [x] เพิ่มแท็บ `Legacy` โดยไม่ Map/rename/รวมประเภท เช่น A5, FAX, Scan, Duplex หรือชื่ออื่นที่เครื่องรายงาน
- [x] มุมรายเครื่องแยกเครื่อง 1–3; มุมผู้ใช้แสดงประเภทดิบแยกตามเครื่อง; มุมรายวันแสดงทุกประเภทดิบแยกตามเครื่อง
- [x] ใช้ dynamic columns + horizontal scroll; ช่องที่ source ไม่มีให้แสดง `—` ไม่เดาเป็น `0`
- [x] เพิ่ม Excel sheets `Legacy-รายเครื่อง`, `Legacy-ผู้ใช้` และ `Legacy-รายวัน` โดยชื่อคอลัมน์ตรง source และยอดตรงกับหน้าจอ

#### H4 — Parser Mapping Inspector

- [x] เพิ่มหน้าต่างแยกสำหรับเลือก Slot/เครื่อง แล้วเปรียบเทียบ `Raw Data → Mapping → Database preview` พร้อม source และเวลาที่อ่านล่าสุด
- [x] รองรับ Read/Test, Reset, Cancel และ Save/Test; mapping ผูกตาม Serial Number พร้อม audit และย้อนกลับได้
- [x] Mapping ใหม่มีผลเฉพาะการอ่านครั้งถัดไป ไม่แก้ Raw snapshot, History, Billing Ledger หรือ Excel ย้อนหลัง
- [x] ค่า Raw ที่ไม่ได้ Map ต้องคงอยู่ใน Legacy Report และแสดง `No Mapping` โดยไม่เดาประเภท

#### H5 — Print/Copy reports and Excel

- [x] แยก Print และ Copy ใน Overview, Users, Printers, Usage และกราฟที่เกี่ยวข้อง
- [x] เพิ่มคอลัมน์ Print/Copy แยกตาม A3/A4/Other ในมุมรายเครื่อง ผู้ใช้ และรายวัน โดยข้อมูลเก่าที่แยกไม่ได้แสดง `—`
- [x] ปรับ Excel มุมรายเครื่อง/ผู้ใช้/รายวันให้ใช้ semantic เดียวกับหน้าจอ และคง Legacy exact-source sheets แยกต่างหาก
- [x] จัด Usage table เป็นหัวตารางสองชั้น `Print`/`Copy` ตามกลุ่ม A3/A4/Other และเพิ่ม `คิดรวม % กระดาษเสีย` ที่เปิดเป็นค่าเริ่มต้น; Checkbox เปลี่ยนเฉพาะค่าใช้จ่ายระหว่าง frozen net/gross ledger โดยไม่เปลี่ยนจำนวนหน้า และ Excel ใช้โหมดเดียวกับหน้าจอ

#### H6 — Verification and Bom visual acceptance

- [x] เพิ่ม focused tests สำหรับ layout state, unsaved-edit popup, Advanced Settings routing/LAN access และ Sidebar freshness wording
- [x] เพิ่ม DB migration/raw-counter/daily-delta/reset tests และเทียบ Legacy UI ↔ Excel แบบ exact totals
- [x] ยืนยัน passwordless Web Report อ่านได้เฉพาะ Report; route ที่แก้ Settings/ข้อมูลยังถูกปฏิเสธ
- [x] รัน full Python regression, scoped Ruff/compileall/diff-check, Web TypeScript/security/build และ release-safety/privacy scan
- [ ] เปิด Source ให้ Bom ไล่ตรวจทุกหน้าใน Thai/English และขนาดหน้าต่างเป้าหมายบน macOS; Windows visual acceptance ทำหลัง Source ผ่าน
- [ ] ห้ามเรียกงานเสร็จจาก automated test อย่างเดียวจน Bom ยืนยันหน้าจอจริง

#### H7 — Customer documentation after UI freeze

- [x] หลัง Code/UI ผ่านแล้ว ใช้ไฟล์ `.doc/.docx Customer-guide` เดิมเป็น visual template หลัก
- [x] แคปภาพหน้าจอจริงจาก Final Source และเขียนคู่มือเต็ม: Wizard, Primary/Secondary, Meter, Reports, Legacy, Excel, Settings/Advanced, LAN, Offline License, Backup/Restore และ troubleshooting
- [x] เนื้อหาเดียวกันอยู่ทั้ง Word Customer Guide และหน้า `คู่มือ` ในโปรแกรม โดยใช้ชื่อปุ่ม/ลำดับงานร่วมกัน
- [x] ตรวจภาษาไทย/อังกฤษ, เลข Version `5.2.1`, ภาพจริงและลำดับขั้น; DOCX structural/text/alt-text QA ผ่าน ส่วน raster fallback บน LibreOffice ไม่ใช้เป็นหลักฐานฟอนต์ไทย

#### H8 — Build only after explicit order

- [x] ไม่ Build Mac/Windows installer ระหว่างแก้และตรวจหน้าจอ จน Bom สั่ง Build โดยตรง
- [ ] เมื่อ Bom สั่ง Build จึง freeze source identity, รัน release gates และสร้าง artifact ชุดใหม่จาก source ที่ผ่านการยอมรับแล้ว

## Problem / Blocker

- Shared Contract R2/OpenAPI/public golden vector พร้อมในชุดส่งทีม API แล้ว แต่ private Host runtime, migration, Dashboard, deployed OpenAPI และ Host public key/kid สำหรับ Offline License ยังต้องให้ทีม API apply/deploy/ส่งหลักฐานจาก separate Staging; ห้ามเรียก Production/สร้าง customer artifact ก่อน Joint Staging E2E.
- Joint Staging E2E เป็น external gate แยกจาก local focused/full gates; V5.1 API pack ใช้ได้เฉพาะ reference fixture และไม่มีสิทธิ์ทำ automatic downgrade/fallback.
- C84hc มีหลักฐาน targeted GET เดิมผ่าน แต่ไม่ตอบใน bounded final probe วันที่ `2026-08-31`; คง `HOLD — device/network unavailable` ไม่ใช่เครื่องไม่รองรับและไม่ยิง retry storm.
- C5070 ตอบ targeted GET ซ้ำ 3/3 แต่ทุก SNMP walk timeout; implementation เดิมจึงล้มเหลวแม้ Total OID ใช้งานได้.
- รอบ final bounded probe `2026-08-31` C5070 กลับมาตอบ exact Total สำเร็จด้วย targeted-only profile; สถานะ availability HOLD เดิมถูกปิดสำหรับรอบนี้โดยไม่เปลี่ยนข้อห้าม SNMP walk.
- Post-implementation smoke รอบ `2026-08-25 10:50–11:00 +07` พบ C5070/C7090 ไม่ตอบ bounded SNMP/Web request และ C12010S Web แจ้ง session busy; หยุด probe เพิ่มเพื่อไม่รบกวนรุ่นเก่า. นี่เป็น device/session availability HOLD ไม่ใช่ product regression หรือ unsupported proof.
- C368 exact Total และ supplemental Toner/Tray ผ่านเครื่องจริง; authenticated Web/TLS ยังคงใช้ explicit legacy profile และห้ามสรุปจาก C458 ว่าทุก firmware เหมือนกัน.
- C7090 ใช้ legacy XML Web Connection `system_counter.xml`; JSON connector เดิมได้ HTTP 404 แต่ XML Total ตรงกับ SNMP.
- C12010S ใช้ public legacy XML เช่นกัน แต่ Printer-MIB primary `250,132` ไม่ใช่ Web Total; KM private OID คืน `250,206` ตรง Web. ห้ามใช้ primary OID แบบ universal โดยไม่มี profile/calibration.
- รายการจาก Bom ระบุ C358 แต่เครื่องใน slot ทดสอบตอบ identity เป็น `KONICA MINOLTA bizhub C368`; ต้องใช้ identity จริงในการเลือก profileและไม่เก็บ network address ในรายงาน.
- Deployed Registration API มี schema-v2 `serial_number` gate ค้างจาก V5.1; local implementation ต้อง preserve `serial_number` และไม่ยิง/แก้ Production จนได้รับอนุมัติ.

## Decisions and Changes

- 2026-08-31 — Bom กำหนด release target ใหม่เป็น `5.2.1` และยอมรับตัวติดตั้ง Windows/macOS แบบ Unsigned. การไม่ Signed ต้องแสดงเป็น accepted distribution risk และอาจถูก Smart App Control/Gatekeeper บล็อก; ห้ามรายงาน signing/notarization ว่า PASS.
- 2026-08-31 — ก่อน freeze/Build 5.2.1 ต้องตรวจ dirty source ทั้งหมด, full regression/Web/release safety/dependency gates และทำ bounded read-only acceptance ทุกโมเดลที่มี authority โดยอ่าน Identity/Total ก่อน แล้วค่อย Web/Toner/Tray/User Authentication/Account Track ตาม capability; ห้าม write, retry storm หรือวน credential.
- 2026-08-31 — Supersede policy เดิมเฉพาะ C7090/C12010S: หลังมีหลักฐาน Toner/Paper Tray จริง ให้ใช้ exact Total เป็น primary และ Printer-MIB walk เป็น `SUPPLEMENTAL`; optional status ล้มเหลวต้องไม่ทำให้ Total หรือสถานะเครื่องกลายเป็น Offline. C5070 ยังคง `TARGETED_ONLY` เพราะ walk timeout ซ้ำจากเครื่องจริง.
- 2026-08-31 — RAM ในหน้าตรวจสอบหมายถึง User Authentication/Account Track process-memory snapshot ไม่ใช่ RAM hardware. Modern/legacy parser ต้องแยก `disabled`, `enabled-but-empty`, schema unreadable และ firmware ไม่เปิดเผยข้อมูล; ห้ามเหมารวมทุกกรณีเป็น “ไม่พบข้อมูล” หรือ “ปิดใช้งาน”.
- 2026-08-26 — Bom สั่ง freeze การแก้ Main application ระหว่างส่ง screenshot/comment; ต้องสรุปแผนรอบเดียวให้ตรวจครบก่อนเริ่ม Source change และยังไม่ Build installer จนได้รับคำสั่งใหม่.
- 2026-08-26 — Legacy Report ใช้ source counter names/values ตรงจากแต่ละเครื่องโดยไม่ Map/rename/รวมประเภท; เก็บ raw snapshot แล้วคำนวณ daily delta, แยกเครื่อง 1–3/ผู้ใช้/รายวัน และ Export เป็นสาม Legacy sheets.
- 2026-08-26 — Settings หลักต้องเหลืองานทั่วไป; Database/Backup/Auto start/Log/Maintenance และ LAN Web Report ย้ายเข้า Advanced Settings. LAN เปิดอัตโนมัติ และ passwordless mode เปิดได้เฉพาะ read-only Web Report ไม่รวม Settings/staff/mutation API.
- 2026-08-26 — Customer Guide ทำหลัง Code/UI freeze เท่านั้น โดยใช้ `.doc/.docx Customer-guide` เดิมเป็น visual template, ใช้ภาพหน้าจอจริง และรักษาเนื้อหา Word กับหน้า Guide ในโปรแกรมให้ตรงกัน.
- 2026-08-26 — Main UI review implementation ใช้ Source-first acceptance: แก้ Devices/Usage/popup/schedule/sidebar, รวม LAN และเครื่องมือระบบไว้ Advanced Settings, เพิ่ม exact-source Legacy report/Excel และเปิดให้ Bom ตรวจจริงก่อน Build.
- 2026-08-26 — Database Path/Restore เป็น staged next-start operation: ตรวจ SQLite และคัดลอกอย่างปลอดภัยก่อนบันทึก Path; ฐานข้อมูล active ไม่ถูกเขียนทับกลางการทำงาน. คำสั่งลบ/reset ทำ automatic backup และยืนยันสองครั้งโดยไม่ใช้ Settings password.
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
- 2026-08-25 — Initial profile registry ใช้หลักฐาน ณ เวลานั้น: C5070/C7090/C12010S เริ่มจาก targeted-only SNMP + public legacy XML; C458 ใช้ targeted-only SNMP + admin legacy XML + TLS 1.1 legacy compatibility แบบ scoped. นโยบาย C7090/C12010S ถูกปรับเป็น supplemental ภายหลังเมื่อมีหลักฐาน Toner/Paper Tray เพิ่มในวันที่ 2026-08-31.
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
- 2026-08-26 — Bom เลือกให้ Secondary Sync จาก Primary บน trusted LAN โดยไม่กรอกรหัส: ผู้ใช้ยังต้องกด `Sync จากเครื่องหลัก`, client pin certificate แบบ TOFU และรับเฉพาะ setup allow-list; Web Report/API อื่นยังคงต้อง Login และ Password/Token/History/Log ไม่ถูกเปิดเผย.

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
| 2026-08-31 10:44 +07 | Optional Toner/Paper Tray + RAM/legacy compatibility | อ่าน supply/tray เพิ่มโดยไม่กระทบ exact Total และอธิบาย User/Account Track ตามหลักฐานจริง | focused `55 passed`, related UI/background `84 passed`, full Python `640 passed`; Ruff, compileall และ diff-check ผ่าน. Live C7090 Total `220,150`, Toner C/Y/M/K `91/71/28/64`, 5 trays; C12010S Total `252,400`, Toner `96/92/13/87`, 4 trays. C5070 bounded read ไม่ตอบและถูกหยุดอย่างปลอดภัย | PASS WITH C5070 AVAILABILITY HOLD | LOCAL REGRESSION + READ-ONLY REAL DEVICE; no credential/write/raw XML/Host telemetry |
| 2026-08-31 12:30 +07 | V5.2.1 final source gates + bounded 12-model exact Total matrix | ตรวจ correctness/security/release identity ครบและอ่าน Identity/Total เครื่องจริงแบบหนึ่ง request ต่อเครื่องโดยไม่ retry storm | focused `172 passed`; full Python `692 passed` (warning เดียวเป็น explicit Virtual Printer TLS fixture); Web lint/security `4/4`/Next production build/npm audit 0; Python lock audits 0 known vulnerabilities; version gate `5.2.1`, compileall, diff-check, release-safety tracked `290/0` และ changed/untracked `129/0` ผ่าน. Fresh Total PASS: C450i, C750i, C300i, C3350i, C751i, C458, C368, C7090, C5070 และ C12010S; 950i/C84hc ไม่ตอบใน bounded current probe | PASS 10 / AVAILABILITY HOLD 2 | LOCAL FULL REGRESSION + READ-ONLY REAL DEVICE; no write/login/Production call; HOLD ไม่เท่ากับ unsupported |
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
| 2026-08-25 16:06 +07 | Dedicated VM automation identity and secret storage | ต้องสั่ง Guest Control ได้โดยไม่มี secret ใน script/source และไม่เพิ่ม network listener | สร้าง local admin `KOMIAutomation`; credential เก็บใน macOS Keychain service `com.bigbom.komi.window-test-vm`; one-time credential file ถูกนำออก; SSH/WinRM/port ใหม่ไม่มี | PASS — LOCAL CONTROL PLANE | setup marker sanitized; no secret value retained or printed |
| 2026-08-25 16:25 +07 | End-to-end headless VM control | Start จาก poweroff ต้องเป็น Headless, Guest Control ต้องอ่าน identity/share และรัน PowerShell ได้ แล้ว Windows ต้องปิดเป็น poweroff | `SessionName=headless`; Guest Additions run level 3; identity `WINDOWKOMI`/ARM64; project share ready; `HEADLESS_FINAL_RUN_PASS`; graceful shutdown ลงท้าย `VMState=poweroff` | PASS — WINDOWS 11 ARM64 VM HEADLESS PREFLIGHT | helper `/Users/wongsakornu-phonram/Projects/dev/KOMI-Report-V5.2-Installer/VM Control/komi-vmctl.sh`; not native x64 evidence |
| 2026-08-25 16:26 +07 | Headless helper safety | Script/evidence ต้องไม่มี credential residue, syntax error หรือ forbidden release data | `zsh -n` PASS; macOS Keychain reference PASS; `/tmp/komi-vm-password.*` empty; release/tree safety PASS; helper mode `700`; final VM poweroff | PASS — SANITIZED | `Technical Evidence/WINDOWS_VM_HEADLESS_FINAL.json` |
| 2026-08-25 17:19 +07 | Bounded live V5.2 Staging smoke | ใช้ current Desktop schema/signature/client parser ส่ง Synthetic เท่านั้นไป Staging; ห้ามแตะ Production หรือพิมพ์ token/private key | `KOMI-STAGING-UAT-20260825T101924Z`; Register `201`, same-operation replay `201`, Status `200`, Meter 3 observations `200`; all client results success; installation `718943ea-75f9-4878-8fce-5bbb4ec20f95` | PASS — LIVE STAGING API / DASHBOARD READ-BACK PENDING | exact Staging root `/api/staging/v1`; one-off transport rewrite required because current client hardcodes `/api/v1`; no Production request |
| 2026-08-25 17:23 +07 | Bom-authorized bounded V5.2 Production Host smoke + Dashboard read-back | ส่งข้อมูล Synthetic ชื่อชัดเจน 1 installation ไป Production Host เพื่อพิสูจน์ Register/Idempotency/Status/Meter โดยไม่ใช้ข้อมูลลูกค้าและไม่แสดง token/private key | `KOMI-PRODUCTION-UAT-20260825T102316Z`; Register `201`, same-operation replay `201`, Status `200`, Meter 3 observations `200`; Dashboard แสดง V5.2.0/Windows x86_64, discovered 4/selected 3, Slot 1–3 และ Total 125,000/250,000/375,000 `ok`; installation `e7e25ba0-f900-4cb5-a829-54b3edf9d483` | PASS — LIVE PRODUCTION HOST API + DASHBOARD READ-BACK | explicitly authorized by Bom while Host is pre-production; Synthetic record intentionally retained; UI displays UTC and the synthetic status timestamp predates registration receipt by one second because the bounded harness reused its pre-register timestamp; this is not exact-installed-client proof |
| 2026-08-26 17:42 +07 | Main UI/Legacy/Advanced source implementation gate | ทุกจุดจาก screenshot review ต้องทำงานร่วมกันได้โดยไม่ Build installer และไม่ทำให้ DB/History/Billing/Registration/Web security ถอย | focused UI/settings/migration/raw-counter/Excel tests ผ่าน; Portable import gateพบ missing `tools/db_recovery.py` แล้วแก้ allow-list/test; full Python `621 passed`; Web TypeScript lint และ security `3/3`; scoped new-code Ruff, compileall และ diff-check ผ่าน | PASS — LOCAL SOURCE / VISUAL ACCEPTANCE PENDING | warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม; ไม่มี installer/customer artifact ถูกสร้าง |
| 2026-08-26 17:45 +07 | เปิด Main application จาก Source ล่าสุด | ต้องใช้ฐานข้อมูล review แยก, migrate แบบมี backup และเปิดหน้าต่างโดยไม่ Build | Source `5.2.0` เปิด event loop สำเร็จ; review DB ถูกสำรองก่อน migration v16; Web service ใช้ external review service ที่ทำงานอยู่ | PASS — LIVE LOCAL SOURCE | `/tmp/komi-main-review.nU56Ew`; รอ Bom ตรวจหน้าจอจริงและยังไม่อ้าง Build/installer acceptance |
| 2026-08-26 19:05 +07 | Final source regression หลังเพิ่ม Advanced/Parser/Print-Copy/Legacy | Source ต้องผ่าน regression, crash-safe report lifecycle, semantic Excel/Web และ static checks โดยไม่ Build installer | Python `623 passed`; แก้ PyQt deferred-widget lifecycle ที่พบจาก full-suite; Web TypeScript PASS, security `3/3`, npm production audit `0`; focused Ruff/compileall/diff-check PASS | PASS — LOCAL SOURCE / VISUAL ACCEPTANCE PENDING | broad legacy Ruff ยังมี baseline findings จึงอ้างเฉพาะ scoped changed/new code; warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม |
| 2026-08-26 19:16 +07 | Native popup short-text button geometry | ปุ่ม `OK`/`Yes`/`No` ต้องไม่ถูกบีบเป็นไอคอนจาก current width ชั่วคราวของ native QMessageBox | focused regression พิสูจน์ fail ก่อนแก้และ pass หลังแก้; UI/Settings `26 passed`; full Python `624 passed`; scoped Ruff/compileall/diff-check PASS | PASS — LOCAL SOURCE / VISUAL RECHECK PENDING | แก้กฎกลางให้ใช้ explicit maximum-width constraint เท่านั้น; warning เดียวเป็น Virtual Printer TLS fixture เดิม |
| 2026-08-26 19:41 +07 | Usage grouped header + waste-paper cost mode | หน้าจอและ Excel ต้องจัด Print/Copy เป็นกลุ่มเดียวกัน และ Checkbox default-on ต้องสลับเฉพาะ frozen net/gross cost โดยไม่คำนวณประวัติใหม่หรือเปลี่ยนจำนวนหน้า | focused Report/Excel/History `28 passed`; full Python `625 passed`; scoped Ruff/compileall/diff-check PASS; เปิด Source จริงและตรวจเห็น grouped header กับ Checkbox default-on | PASS — LIVE LOCAL SOURCE / BOM VISUAL REVIEW | warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม; ยังไม่ Build installer |
| 2026-08-26 20:09 +07 | Legacy Admin XML supplemental Toner/Paper profile | C458/C368 ต้องคง exact Total GET เป็นหลัก แต่เก็บ Printer-MIB Toner/Tray แบบ optional และ failure ต้องไม่ทำ Total/Online ถอย | C458 Total `27,496`, Toner C/Y/M/K `72/79/78/59`, Tray levels `500/50/500/500/0`; C368 Total `201,926`, Toner `56/55/73/61`, Tray levels `50/50/0`; focused `56 passed`, full Python `626 passed`, Ruff/compileall/diff-check PASS; source-app manual refresh `20:16 +07` จบ `device_read` ครบ 3/3 slots และหน้าอุปกรณ์แสดง Toner/Tray จริง | PASS — TWO REAL DEVICES / LOCAL REGRESSION + UI READ-BACK | read-only SNMP; Web screenshot ของ C458 ยืนยัน Bypass Empty, Tray 2 Near Empty และ Tray อื่น Ready ตรงกับ level; ไม่มี credential/cookie/raw XML ถูกเก็บ และยังไม่ Build installer |
| 2026-08-26 20:31 +07 | Usage opening-meter reference row | ตาราง Usage ทั้ง `ทุกเครื่อง` และ `ตามเครื่อง` ต้องเริ่มด้วย Meter ครั้งแรกที่บันทึก แต่ห้ามนำไปคิด usage, cost, chart, KPI หรือ % กระดาษเสีย และต้องไม่สืบทอด baseline ข้าม Serial เมื่อเปลี่ยนเครื่องใน Slot เดิม | แถว `Meter เริ่มต้น` แสดงเฉพาะคอลัมน์รวม; Print/Copy/Scan/Cost เป็น `—`; V4.6 snapshot แรกเป็น baseline-only; full Python `629 passed`; focused `22 passed`; scoped Ruff/compileall/diff-check PASS; เปิด widget จาก source และอ่านเห็น baseline รวม `247,062` โดยยอด period/กราฟยังคงมาจาก usage จริงเท่านั้น | PASS — LOCAL SOURCE / VISUAL REVIEW | ฐานข้อมูล review/fixture เท่านั้น; ไม่ Build installer, ไม่เรียก Host/Production และไม่เปลี่ยน Billing Ledger |

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
- Supplemental status verification at `2026-08-26 20:06–20:09 +07`: standard Printer-MIB returned Toner C/Y/M/K `72/79/78/59` and five input trays with levels `500/50/500/500/0`. Bom's Web view independently showed Bypass `Empty`, Tray 2 `Near Empty`, and Tray 1/3/4 `Ready`, matching the conservative level mapping. The profile now keeps exact Total as primary and treats Toner/Paper failure as optional, never as a device-offline decision.
- Sanitization: extracted values only; raw XML/screenshots, credential, cookies/session material, IP, certificate subject/contact fields and unrelated configuration were not persisted.

## Captured Evidence — bizhub C368 Supplemental Status

- Device identity: `KONICA MINOLTA bizhub C368`; exact Total `201,926` remained available while optional status tables were collected.
- Read-only Printer-MIB evidence at `2026-08-26 20:08 +07`: Toner C/Y/M/K `56/55/73/61`; Tray 1 `50/500`, Tray 2 `50/500`, Bypass `0/150`.
- The same `LEGACY_XML_ADMIN + SUPPLEMENTAL` policy is shared with C458. Future confirmed Legacy Admin profiles inherit supplemental status by default unless device evidence requires a targeted-only exception.
- No Web login, write, credential, cookie, raw XML or Host telemetry was used for this supplemental verification.

## Definition of Done

### Secondary Desktop Wizard — 2026-08-26

- [x] First-run ค้นหา Primary ใน active LAN แบบ background และมีปุ่มค้นหาซ้ำ; ถ้าไม่พบยังตั้งค่า Primary ตาม Wizard เดิมได้
- [x] Discovery เปิดเผยเฉพาะ contract, readiness, company, printer count และ version; ไม่เปิดเผย Serial/IP printer/credential/token/history/log
- [x] Setup snapshot ดึงได้โดยไม่กรอกรหัสหลังผู้ใช้กด Sync; ยังคง certificate TOFU pin, exact allow-list และปฏิเสธ extra field ส่วน Web Report/API อื่นยังต้อง Login
- [x] Secondary ดึงเฉพาะบริษัท, selected printer/Slot/IP/model/serial/TLS pin, ราคาและรอบบิลลง Wizard memory; ยังไม่เขียนฐานข้อมูลจนผู้ใช้กดบันทึก
- [x] หลัง Sync ต้องทดสอบ SNMP + Web จาก Secondary จริงอีกครั้ง; ผ่านครบจึงข้ามไปหน้า Review, ไม่ผ่านกลับ Step 2 ให้แก้สิทธิ์เฉพาะเครื่อง
- [x] Save สร้าง installation ID ของ Secondary แยกและเก็บ role/Primary peer metadata ในฐานข้อมูล local โดยไม่แก้ Host payload เดิม; Web UI ยังคงเปิดจาก Desktop แต่ละเครื่อง
- [ ] Continuous history/database synchronization และ Primary-heartbeat/Secondary-takeover runtime ยังเป็น work unit ถัดไป; milestone นี้ไม่อ้างว่า failover เสร็จ
- [ ] ทดสอบ Source แบบสองเครื่องจริงใน LAN หลังบอมตรวจ UX แล้ว; ยังไม่ Build installer ตามคำสั่ง

Verification:

| เวลา | Gate | ผล | Evidence level |
|---|---|---|---|
| 2026-08-26 15:25 +07 | Secondary contract/Web/Wizard focused regression | `69 passed` | LOCAL SOURCE |
| 2026-08-26 15:26 +07 | Full Python regression | `617 passed`; warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม | LOCAL REGRESSION |
| 2026-08-26 15:27 +07 | Web security/TypeScript/Next production build | security `2/2`, TypeScript PASS, Next 16.3.2 build PASS | LOCAL WEB BUILD |
| 2026-08-26 15:27 +07 | Static/diff checks | targeted Ruff/compileall และ `git diff --check` PASS | LOCAL STATIC |
| 2026-08-26 15:31 +07 | Primary Web → Secondary LAN contract E2E | discovery → certificate pin → Web login → allow-listed snapshot ผ่านด้วย Primary/Secondary DB ชั่วคราวแยกกัน | LOCAL LAN E2E; no printer/Host/Production |
| 2026-08-26 15:41 +07 | Passwordless Secondary setup handoff | `GET /peer/setup-snapshot` ผ่านโดยไม่มี Session/Cookie, certificate pin และ allow-list ยังทำงาน; protected `/api/v1/health` ยังตอบ `401`; Wizard ข้ามหน้ารหัสและเริ่มตรวจ printer สด | LOCAL SOURCE/LAN LOOPBACK; no installer/Host/Production |
| 2026-08-26 15:44 +07 | Bom Secondary Wizard acceptance | Bom ทดสอบ Secondary flow แบบไม่กรอกรหัสแล้วตอบ `ผ่าน` | USER ACCEPTANCE — SOURCE REVIEW; no installer claim |
| 2026-08-26 15:45 +07 | Full regression after passwordless Sync | Python `618 passed`, warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture เดิม; focused strict checks, compileall และ diff-check ผ่าน | LOCAL REGRESSION |
| 2026-08-26 15:45 +07 | Verified learning capture | ส่งผลที่มี automated evidence และ Bom acceptance เข้า Knowledge backend; endpoint ตอบสำเร็จแต่ `observed=false`, `verified=false`, `promoted=false`, `notePath=null` จึงไม่อ้างว่าบันทึกความรู้ถาวร | KNOWLEDGE BACKEND HOLD |
| 2026-08-26 15:45 +07 | Internal Dashboard sync | canonical workbook และ usage snapshot sync สำเร็จ 27 projects; ไม่ได้อ้าง live publish | INTERNAL SYNC |
| 2026-08-26 20:30 +07 | V5.2 source UX/button/documentation release-review gate | Visual matrix ไทย/English ครบ 18 แบบ: 1–3 เครื่อง × 1024×768, 1280×800, 1440×900 ไม่พบข้อความ/ปุ่ม/กรอบถูกตัดและไม่เรียก network; focused Wizard/Secondary/Settings/LAN/Reports/Legacy/Parser/Excel/i18n `155 passed`; Python ทุก test file แบบ fresh process ครบ 95 files / `631 passed`; one-process run พบ native PyQt accumulated-lifetime crash จึงไม่ใช้เป็นหลักฐานผ่าน; scoped Ruff, compileall, version gate 5.2.0, diff-check, release builder `9 passed`, Web lint/security `3/3`/Next build/npm audit 0 ผ่าน; Customer Guide Word 17 หน้า render และตรวจภาพครบทุกหน้า | LOCAL SOURCE REVIEW — ยังไม่ Build EXE/installer และไม่เรียก Host/Production |
| 2026-08-26 22:35 +07 | In-app Guide single-page redesign | เปลี่ยนคู่มือในโปรแกรมเป็นหน้า scroll ต่อเนื่อง 5 ส่วน ไทย/English โดยยึด Customer Guide เป็นแม่แบบ: พื้นขาวแบบเอกสาร, ตัดกรอบการ์ดซ้อน, ใช้หัวข้อ/เส้นคั่น/กล่องหมายเหตุแบบ Word และภาพหน้าจอร่วมชุดเดียวกับ Customer Guide ครบ 13 ภาพ; จอปกติแสดงสารบัญคงที่ด้านขวาพร้อม click-to-scroll/scroll highlight และ 1024px ยุบเป็น dropdown โดยไม่มี horizontal scroll; visual matrix ไทย/English 18 แบบผ่าน, focused manual/i18n/app/UI `14 passed`, Python fresh-process regression 95 files / `632 passed`, critical Ruff, compileall, version gate 5.2.0 และ diff-check ผ่าน; เปิด source Guide ด้วย isolated temporary DB และปิด network ค้างไว้ให้ Bom ตรวจ | LOCAL SOURCE REVIEW — คู่มือในโปรแกรมเป็นฉบับย่อ; Customer Guide Word ยังคงเป็นฉบับเต็ม; ยังไม่ Build EXE/installer |
| 2026-08-26 22:47 +07 | In-app Guide typography review | ลดขนาดตัวอักษรทุกระดับเฉพาะหน้า Guide ลง 20% รวมหัวข้อ, เนื้อหา, step badge, caption, หมายเหตุ, สารบัญขวาและ responsive combo โดยไม่กระทบหน้าอื่น; focused Manual `3 passed`, diff-check ผ่าน และเปิด Source Guide ชุดใหม่ค้างไว้ให้ Bom ตรวจ | LOCAL SOURCE REVIEW — minimal focused check ตามคำสั่ง; ยังไม่ Build EXE/installer |
| 2026-08-26 23:56 +07 | V5.2 macOS/Windows installation candidate packaging | ปรับ Diagram คู่มือให้ตรง runtime V5.2 และ `test_manual_diagrams.py` ผ่าน; full Python `636 passed`, Web lint/security `3/3`/Next build/npm audit 0 และ packaged Web integration ผ่าน. macOS arm64 DMG SHA-256 `fc317c982a8640587209951ed811a2bbd0908842bd90ffe26c02ebc0da1a6b47`, ZIP `6c003a4dd9df0b2c66c428edee79b7265236206ce2e7b1eaaf2bb628c8a2413e`; app smoke/DB/codesign strict ad-hoc ผ่าน แต่ไม่ notarized. Windows x64 RC สร้างใน Windows 11 ARM64 VM ผ่าน x64 emulation, exit 0, SHA-256 `693c18761fe9d021ac83043b663c2de717af37d99fde389219a4336322238036`, manifest/SBOM/inventory/checksum ครบ; Guest Control ยัง login ไม่ผ่านจึงใช้ GUI PowerShell โดยไม่ปิด Smart App Control | INSTALLATION CANDIDATE — Windows unsigned/build environment เป็น ARM64 VM preflight และ macOS ไม่มี Developer ID/notarization; `production_go=false`, ไม่อ้าง native Windows x64 UAT หรือ Production GO |
| 2026-08-31 13:10 +07 | V5.2.1 final reviewed-source gate before unsigned packaging | ปิด P1 local-first registration retry, multi-interface/Manual Primary discovery, Excel formula injection และ exact-source archive identity; targeted `181 passed`; full Python `714 passed`; version gate `5.2.1`; Web lint/security `4/4`/Next build/npm audit 0; Python lock audit 0; critical Ruff/compileall/diff-check ผ่าน; tracked 321/0 และ staged 129/0 safety findings | PASS — EXACT STAGED SOURCE / PACKAGING NOT YET BUILT |

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
