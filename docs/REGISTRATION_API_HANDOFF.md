# KOMI Report V5.1 — Registration API handoff

เอกสารนี้ใช้ส่งงานระหว่างผู้พัฒนา KOMI Report Desktop กับผู้พัฒนา Web Hosting/API โดยไม่ต้องเดา field หรือขอบเขตข้อมูลกันเอง

## Prompt สำหรับส่งให้ผู้พัฒนา API

คัดลอกข้อความตั้งแต่บรรทัดถัดไปส่งให้ผู้พัฒนาได้เลย:

> ช่วยพัฒนา **KOMI Report V5.1 Registration API รุ่นแรก** บน Web Hosting ที่ทีมดูแล เพื่อให้เราทราบจำนวนบริษัทและจำนวน installation ที่ยังใช้งานอยู่ โดยขอเป็น service แยกจากฐานข้อมูลของ Desktop และรับข้อมูลผ่าน HTTPS เท่านั้น
>
> เป้าหมายของรอบนี้คือ Registration + Heartbeat + Private Admin Dashboard เท่านั้น ระบบ Update เป็น contract แยกและยังไม่รวม forced update ในงานนี้
>
> ### ผลลัพธ์ข้อมูลที่ต้องตรวจสอบได้
>
> ระบบต้องทำให้ทีม KOMI ที่ได้รับสิทธิ์ตรวจสอบข้อมูลต่อไปนี้ได้ โดยรับ Serial No เป็นข้อมูลอุปกรณ์สำหรับงาน Registration ตาม Registration Data Notice ที่อนุมัติ และยังคงปิดข้อมูลการใช้งาน/เครือข่ายอื่นตาม data boundary:
>
> 1. ชื่อบริษัท
> 2. `installation_id` แบบ UUID
> 3. วันที่เริ่มใช้งาน
> 4. Version ที่ใช้อยู่ เช่น `5.1.0`
> 5. ระบบปฏิบัติการ เช่น Windows/macOS
> 6. สถาปัตยกรรม เช่น x64/arm64
> 7. รุ่นเครื่องพิมพ์และจำนวนรวม เช่น `bizhub C450i × 2`
> 8. วันที่ลงทะเบียนและ `last_seen_at`
> 9. สถานะ installation ว่า registered, active, inactive, deactivated หรือ revoked
> 10. ประวัติ Heartbeat และประวัติการเปลี่ยนสถานะการลงทะเบียนภายใน retention ที่อนุมัติ
> 11. ข้อมูลรวมใน Dashboard ได้แก่จำนวนบริษัท, จำนวน installation และ Active 7/30/90 วัน
> 12. จำนวนเครื่อง Konica Minolta ที่ Desktop ค้นพบจาก IP scan ตอนลงทะเบียน และรายการ Serial No + Model + Selected + Local Slot เพื่อให้ทีมหลังบ้านตรวจได้ว่าลูกค้าพบเครื่องทั้งหมดกี่เครื่องและเลือกเครื่องใดสำหรับอ่าน Report
>
> `active` เป็นค่าที่ Server คำนวณจาก `last_seen_at` และสถานะไม่ถูก deactivated/revoked ไม่รับ boolean นี้จาก Client เพื่อป้องกันข้อมูลคลาดเคลื่อน Dashboard ต้องแสดง Active 7/30/90 วันแยกกัน; หากต้องมีสถานะเดียวให้ใช้ 30 วันเป็นค่าเริ่มต้นที่ตั้งค่าได้
>
> ### Versioning และ Request contract
>
> Desktop มี local allow-list envelope `schema_version: 2` และ automated tests สำหรับ discovery/selected device แล้ว แต่ API ที่ deploy อยู่ยังใช้ contract UUID เดิม จึงต้องแก้ OpenAPI/API/Database ให้ตรง contract นี้ก่อนเชื่อม ห้ามเปลี่ยน field เงียบ ๆ
>
> `POST /api/v1/installations/register`
>
> Headers:
>
> - `Content-Type: application/json`
> - `Idempotency-Key: <UUID ที่ไม่ซ้ำต่อ operation>`
>
> Target body สำหรับ `schema_version: 2`:
>
> ```json
> {
>   "schema_version": 2,
>   "event_type": "installation_registered",
>   "installation_id": "UUID ที่ Desktop สร้างและเก็บถาวร",
>   "company_name": "Example Company Co., Ltd.",
>   "client_first_started_at": "2026-08-20",
>   "app_version": "5.1.0",
>   "platform": "Darwin",
>   "architecture": "arm64",
>   "device_inventory": {
>     "konica_discovered_count": 5,
>     "devices": [
>       {"serial_number": "A1ABC001", "model": "bizhub C450i", "selected": true, "device_slot": 1},
>       {"serial_number": "A1ABC002", "model": "bizhub C450i", "selected": true, "device_slot": 2},
>       {"serial_number": "A1ABC003", "model": "bizhub C450i", "selected": false, "device_slot": null},
>       {"serial_number": "A1XYZ001", "model": "bizhub C750i", "selected": false, "device_slot": null},
>       {"serial_number": "A1XYZ002", "model": "bizhub C650i", "selected": false, "device_slot": null}
>     ]
>   },
>   "created_at": "2026-08-20T15:30:00+00:00"
> }
> ```
>
> `konica_discovered_count` คือจำนวน Konica Minolta ทั้งหมดที่พบจาก IP scan ตอนลงทะเบียน ไม่จำกัดที่ 3 เครื่อง ส่วน `selected=true` คือเครื่องที่ลูกค้าเลือกสำหรับอ่าน Report ซึ่งยังจำกัดสูงสุด 3 เครื่องตามความสามารถของ Desktop. `serial_number` เป็น identity ของเครื่องจริงและต้อง unique ภายใน snapshot; Dashboard สามารถแสดง Serial No เต็มแก่ role ที่อนุมัติ และใช้ Short Serial ในหน้ารวมได้
>
> การเปลี่ยนแปลงนี้เป็นข้อมูลหลังบ้านเท่านั้น ห้ามเพิ่มคำเตือน/ข้อความขาย Print Management หรือเปลี่ยน workflow ฝั่งผู้ใช้. ห้ามรับหรือเก็บ IP address, MAC address, hostname, username/password/credential, meter/counter, user/account, document name/content และ application log ใน Registration/Heartbeat. Company ต้องเป็นชื่อนิติบุคคล/หน่วยงานและห้ามกรอกชื่อบุคคล; Serial No เป็นข้อมูลอุปกรณ์. ทั้งสองรายการต้องอยู่ใน Registration Data Notice และ retention/access policy ที่ Product owner/Hosting Security อนุมัติก่อน Production
>
> Response ที่ต้องการสำหรับ register ทั้งกรณีสร้างใหม่และยิงซ้ำ:
>
> ```json
> {
>   "schema_version": 2,
>   "installation_id": "UUID เดิมจาก Desktop",
>   "registration_status": "registered",
>   "registered_at": "ISO-8601 UTC",
>   "installation_token": "scoped bearer token สำหรับ installation นี้",
>   "next_heartbeat_after_seconds": 86400
> }
> ```
>
> - การยิง request เดิมด้วย `installation_id` และ `Idempotency-Key` เดิมต้องไม่สร้าง installation ซ้ำ
> - หากยิงซ้ำหลัง timeout ต้องตอบผลเดิมได้อย่างปลอดภัย
> - `installation_token` ต้องแสดงเฉพาะตอนออก token/rotate token และเก็บฝั่ง server แบบ hash ถ้า stack รองรับ
>
> `POST /api/v1/installations/heartbeat`
>
> Headers: `Authorization: Bearer <installation_token>` และ `Idempotency-Key`
>
> Body:
>
> ```json
> {
>   "schema_version": 2,
>   "installation_id": "UUID เดิม",
>   "app_version": "5.1.0",
>   "platform": "Darwin",
>   "architecture": "arm64",
>   "device_inventory": {
>     "konica_discovered_count": 5,
>     "devices": [
>       {"serial_number": "A1ABC001", "model": "bizhub C450i", "selected": true, "device_slot": 1},
>       {"serial_number": "A1ABC002", "model": "bizhub C450i", "selected": true, "device_slot": 2},
>       {"serial_number": "A1ABC003", "model": "bizhub C450i", "selected": false, "device_slot": null},
>       {"serial_number": "A1XYZ001", "model": "bizhub C750i", "selected": false, "device_slot": null},
>       {"serial_number": "A1XYZ002", "model": "bizhub C650i", "selected": false, "device_slot": null}
>     ]
>   },
>   "occurred_at": "ISO-8601 UTC"
> }
> ```
>
> Heartbeat ต้องอัปเดต `last_seen_at`, version, platform/architecture และ device inventory snapshot โดยไม่เพิ่มแถว installation ใหม่ และต้องสร้าง heartbeat history แบบ typed fields โดยไม่เก็บ bearer token หรือ raw request body
>
> ขอเพิ่ม `GET /health` สำหรับ deployment check และ error response กลางรูปแบบนี้:
>
> ```json
> {
>   "error": {
>     "code": "VALIDATION_ERROR",
>     "message": "ข้อความที่ปลอดภัยสำหรับแสดง/บันทึก",
>     "request_id": "server request id",
>     "retryable": false
>   }
> }
> ```
>
> รองรับ HTTP status อย่างน้อย `200/201`, `400`, `401`, `409`, `422`, `429` และ `500/503` พร้อมระบุว่า client retry ได้หรือไม่ และใช้ `Retry-After` เมื่อ rate limit หรือ service unavailable
>
> ### Database และ Dashboard
>
> ขอ data model อย่างน้อย:
>
> - `installations`: installation ID แบบ unique, company name, first started, registered/last seen, current version, platform/architecture, lifecycle status และ timestamps
> - `installation_heartbeats`: installation, occurred/received at, version, platform/architecture และผลประมวลผล โดยไม่เก็บ token/raw body
> - `installation_device_snapshots`: installation/heartbeat, observed at, discovered count และ selected count
> - `installation_device_snapshot_items`: snapshot, Serial No, model, selected และ local device slot โดยไม่มี IP/MAC/hostname
> - `installation_status_history`: installation, old/new status, safe reason code, actor และ occurred at
> - `registration_idempotency`: key, request fingerprint, response/result และ expiry
> - `audit_log`: admin action สำคัญโดยไม่เก็บ bearer token หรือ request body ที่มี secret
>
> Private Admin Dashboard ต้องมี MFA/RBAC หรืออย่างน้อยอยู่หลังระบบ login ของ Hosting และแสดงแยกกันชัดเจน:
>
> - จำนวน **บริษัท** (ใน MVP ให้นับจาก normalized company name และติดป้ายว่าเป็นค่าประมาณ)
> - จำนวน **installation** ที่ไม่ซ้ำ
> - Active 7/30/90 วันจาก `last_seen_at`
> - Company, installation ID, first started, registered at, last seen, registration/lifecycle status, version, OS และ architecture
> - จำนวน Konica Minolta ที่ค้นพบล่าสุด, รุ่นที่พบแบบ aggregate และรายการ Serial No + Model + Selected + Local Slot เพื่อแยกเครื่องจริงและตรวจว่า installation ที่พบเกิน 3 เครื่องยังเลือกใช้ KOMI Report อยู่หรือไม่
> - Heartbeat timeline และ registration status history ภายใน retention ที่อนุมัติ
> - สรุปรุ่นเครื่องแบบ aggregate โดยแยก discovered/selected ให้ชัด
> - ค้นหา ดูรายละเอียด ปิดใช้งาน installation และ export CSV เฉพาะ field ที่อนุญาต
>
> อย่านับ “บริษัท” จาก installation โดยตรง เพราะบริษัทเดียวอาจติดตั้งหลาย installation ใน MVP ให้นับ normalized company name และติดป้ายว่าเป็นค่าประมาณ หากทีมจะใช้ Activation Code/Customer ID เพื่อให้ยอดแม่นยำ ให้เสนอ revision ถัดไปก่อนบังคับ Desktop
>
> ### Security, privacy และ operation
>
> - Production ใช้ HTTPS certificate ที่ถูกต้อง ห้าม Desktop ต่อ database โดยตรง
> - Validate schema แบบ allow-list, จำกัด body size, rate limit และป้องกัน token/request body หลุดใน log
> - ตรวจว่า `konica_discovered_count` เท่ากับจำนวน `devices[]`, `serial_number` ไม่ว่างและไม่ซ้ำภายใน snapshot และ `device_slot` อยู่ในช่วง 1–3 โดยไม่ซ้ำ
> - `selected=true` ต้องมี Slot; `selected=false` ต้องมี `device_slot=null`; selected count ให้ Server คำนวณจากรายการจริงและต้องอยู่ในช่วง 0–3
> - เก็บเวลาเป็น UTC, ทำ database migration ที่ย้อนกลับได้ และมี backup/restore procedure
> - ระบุ retention/deactivate/delete policy และผู้ที่มีสิทธิ์ดูข้อมูล
> - มี staging environment แยกจาก production
> - ห้ามใส่ production secret ใน Git, screenshot หรือแชต ให้ส่งผ่านช่องทาง secret ที่ทีมกำหนด
>
> ### Definition of Done และสิ่งที่ต้องส่งกลับ
>
> 1. Staging Base URL ที่เปิด `GET /health` ได้ผ่าน HTTPS
> 2. OpenAPI 3.x file (`openapi.json` หรือ `.yaml`) ที่ตรงกับระบบที่ deploy จริง
> 3. Source repository/commit hash, migration และคำสั่ง deploy/rollback
> 4. `.env.example` ที่มีเฉพาะชื่อตัวแปร และส่งค่า secret จริงผ่านช่องทางปลอดภัยแยกต่างหาก
> 5. ตัวอย่าง `curl` สำหรับ schema v2: register ครั้งแรก, register ซ้ำ, heartbeat, token ผิด, inventory ผิด schema และ rate limit พร้อม response จริงที่ตัด secret แล้ว
> 6. หลักฐาน automated test สำหรับ validation, excluded fields, Serial No/count/selected/slot constraints, idempotency, authentication, retry/rate limit และ database uniqueness
> 7. URL Private Admin Dashboard และ test account/role ผ่านช่องทางปลอดภัย
> 8. สรุป retention, backup/restore, monitoring/alert และผู้รับผิดชอบเมื่อ service ล่ม
> 9. ตาราง field ที่ server เก็บจริง รวม heartbeat/status/device snapshot retention เพื่อเทียบกับ privacy boundary ด้านบน
> 10. แจ้งข้อแตกต่างจาก contract นี้เป็นรายการก่อนส่งมอบ ห้ามเปลี่ยน field เงียบ ๆ
> 11. หลักฐาน Dashboard ว่า company/installation/Active 7/30/90, last seen, heartbeat history, discovered count และ Serial No + Model + Selected + Slot ตรงกับ staging requests รวมกรณีค้นพบมากกว่า 3 เครื่องแต่เลือกใช้ไม่เกิน 3 เครื่อง

## สิ่งที่บอมต้องนำกลับมาให้ทีม Desktop

นำข้อมูลต่อไปนี้กลับมา โดย **ไม่วาง secret จริงลงในแชต**:

1. Staging Base URL และผล `GET /health`
2. ไฟล์ OpenAPI 3.x
3. Repository URL + branch/tag/commit ที่ส่งมอบ
4. ตัวอย่าง request/response จริงที่ redact token แล้ว
5. ชื่อตัวแปร environment ที่ Desktop ต้องตั้ง เช่น `KOMI_REGISTRATION_API_URL`; ค่า token/secret ให้บอกเพียงว่าเก็บอยู่ช่องทางใด
6. วิธี bootstrap การลงทะเบียนที่ทีม API เลือก: anonymous staging, Activation Code หรือ installer bootstrap credential
7. กติกา token: อายุ, rotate/revoke และวิธีออกใหม่
8. Retry/rate-limit/error code contract
9. ภาพหรือ URL Dashboard ที่พิสูจน์ว่า company/installation/Active 7/30/90, last seen, heartbeat history, discovered count และ Serial No + Model + Selected + Slot ทำงาน
10. ผลทดสอบ, migration version และขั้นตอน rollback
11. คำยืนยันว่า OpenAPI รองรับ `schema_version: 2` หรือรายการข้อแตกต่างที่ทีม Desktop ต้องพิจารณาก่อนเชื่อม

เมื่อได้ครบ ให้ส่งข้อความนี้กลับมาพร้อมไฟล์ที่เกี่ยวข้อง:

> ตรวจ OpenAPI ของ KOMI Report V5.1 Registration API กับ target `schema_version: 2` ใน `docs/REGISTRATION_API_HANDOFF.md` ก่อน โดยใช้ Staging Base URL: `<URL>` และ OpenAPI file: `<path/attachment>`. API source commit: `<commit>`. Bootstrap method: `<method>`. Secret ถูกเก็บไว้ที่ `<secure location; ห้ามใส่ค่าจริงในแชต>`. หาก contract ตรงกันจึงค่อยเชื่อม Desktop ด้วย local durable outbox, offline retry/idempotency, secure token storage และ integration tests โดยไม่เปลี่ยนหน้าตา/ข้อความของแอป พร้อมเพิ่ม allow-list tests สำหรับ Serial No + Model + Selected + Local Slot และกรณีค้นพบมากกว่า 3 เครื่องแต่เลือกใช้ไม่เกิน 3 เครื่อง จากนั้นทดสอบ staging end-to-end และรายงานว่าส่วนใดผ่าน/ยังไม่ผ่าน

## Desktop Phase 2 implementation status — 2026-08-22

ส่วนนี้บันทึก contract ฝั่ง Desktop ที่ implement และทดสอบแล้ว ไม่ใช่หลักฐานว่า deployed API ตรงกัน:

- Desktop โหลด non-secret JSON policy จาก path ใน `KOMI_REGISTRATION_POLICY_FILE`; repository ไม่มี deployed URL,
  bootstrap value หรือ bearer token และจะ disabled เมื่อไม่มี policy.
- Policy root ต้องมีเฉพาะ `base_url`, `environment`, `bootstrap`, `privacy_notice`, `request_timeout_seconds`.
  Base URL ต้องเป็น HTTPS absolute URL ที่ไม่มี userinfo/query/fragment; timeout อยู่ในช่วง 1–60 วินาที.
- `bootstrap` ต้องมีเฉพาะ `mode`, `header`, `vault_ref`; Production รองรับเฉพาะ `vault_header` และอ่านค่าจริงจาก
  OS vault ตาม reference. `anonymous` ยอมรับเฉพาะ staging.
- `privacy_notice` ต้องมี version, approved flag, purpose, exact field list, retention, deletion contact, legal basis,
  access/export workflow และ approval reference/date/owner. Production sender หยุดก่อนเปิด vault/network หาก notice ไม่ครบ
  หรือผู้ใช้ยังไม่ยอมรับ version ปัจจุบัน.
- Client ส่ง exact schema-v2 body, recompute request fingerprint ก่อนใช้ Idempotency-Key, ไม่ตาม HTTP redirect และยอมรับ
  success response เฉพาะ exact typed fields ด้านบน. Error code/request ID ที่มีอักขระหรือความยาวนอก allow-list จะถูกแทนด้วย
  generic safe code ก่อนเก็บ/log/UI.
- Register token และ optional heartbeat rotation token ถูกเขียน OS vault ก่อน mark outbox success; SQLite เก็บเพียง stable
  token reference. Vault unavailable หรือ local commit failure จะ fail-closed/rollback token write.
- HTTP `401/403` เป็น terminal `token_rejected`; `408/425/429/500/502/503/504` retry ตาม typed response/default policy
  และ `Retry-After` นับจากเวลารับ response. Unexpected worker failure ถูกคืนเป็น durable retry โดยไม่รอ restart.
- Outbox operation ใหม่ supersede inventory เก่าที่ยังไม่สำเร็จ, duplicate fingerprint reuse operation/idempotency key เดิม,
  attempt history เก็บสูงสุด 50 รายการต่อ operation และเมื่อ lifecycle ใหม่สำเร็จจะ prune completed/superseded payload เก่า
  เพื่อลด local Serial No retention.
- Factory Reset ลบ registration attempts/outbox/profile และ scoped token; หาก vault ใช้งานไม่ได้จะไม่ลบ local state ครึ่งเดียว.
- Registration Data Notice ไทย/อังกฤษอยู่ที่ `docs/REGISTRATION_DATA_NOTICE.md` และข้อความที่แอปแสดงอยู่ที่
  `source/services/registration_data_notice.py`. Payload ออกแบบเป็นข้อมูลนิติบุคคล/Installation/อุปกรณ์ ไม่ใช่ข้อมูลบุคคล;
  ระบบหลังบ้าน/พื้นที่จัดเก็บคือ `https://www.dmskm.com/` ในประเทศไทย และเจ้าของระบบยืนยันว่า API/Application log
  ไม่จัดเก็บ Source IP, Raw request body หรือ Token. การยืนยันนี้ปิด data-boundary question แต่ไม่ใช่ OpenAPI/Staging E2E proof.

### Evidence gap ที่ยังบล็อก Production

ณ วันที่ 2026-08-22 ยังไม่มี OpenAPI/deployed staging artefact, verified environment, bootstrap lifecycle,
token rotate/revoke/error contract หรือ approved Registration Data Notice/Hosting Security retention/access/deletion evidence อยู่ใน
nested repository นี้ จึงยังไม่ทำ live Registration request, staging E2E, Dashboard read-back หรือ cleanup และสถานะยังเป็น
**Technical Pass / Production blocked**.

## หมายเหตุเรื่อง Update

อย่ารวมไฟล์อัปเดตหรือคำสั่งบังคับ update ใน Registration response รุ่นแรก รอบ Update ต้องมี contract แยกสำหรับ signed manifest, SHA-256/signature, OS/architecture artifact, rollout cohort, rollback และ native UAT ก่อนเปิด one-click update
