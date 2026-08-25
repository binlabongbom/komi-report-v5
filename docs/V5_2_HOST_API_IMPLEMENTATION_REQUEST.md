# KOMI Report V5.2 — Host/API Implementation Request

สถานะเอกสาร: **Implementation Handoff / ไม่ใช่ Production GO**

เอกสารนี้ใช้ส่งงานให้ทีม Web Hosting/API เพื่อพัฒนา Host ของ KOMI Report V5.2 โดยไม่ต้องเดา field, ขอบเขตข้อมูล หรือหลักฐานที่ต้องส่งกลับ ทีม Desktop จะเชื่อมต่อเมื่อ Staging contract และหลักฐานด้านล่างผ่านเท่านั้น

## Parallel development + one-shot final handoff

ทีม Host/API และทีม Desktop V5.2 ต้องพัฒนา **พร้อมกันจาก Frozen Contract ชุดเดียวกัน** ไม่ใช่รอให้ทีมหนึ่งเสร็จก่อนอีกทีมจึงเริ่ม. ระหว่างพัฒนาให้ใช้ OpenAPI, JSON Schema, canonical signing specification, Golden Test Vectors และ Synthetic fixtures ชุดเดียวกันเป็น source of truth

ลำดับการทำงาน:

1. Freeze Contract draft จากเอกสารนี้ร่วมกันก่อนเริ่ม implementation
2. ทีม Host/API ทำ API, Database, Dashboard, Reference Client และ Staging
3. ทีม Desktop ทำ Registration client, installation key/vault, durable retry, Status, Meter และ Offline License verification พร้อมกัน
4. ทั้งสองทีมรัน contract tests ของตัวเองจาก fixture/checksum ชุดเดียวกันระหว่างพัฒนา
5. เมื่อทั้งสองฝั่งพร้อม ให้นำ **Desktop V5.2 build จริง** เชื่อมกับ deployed Staging และรัน Joint E2E หนึ่งรอบ
6. แก้ปัญหาที่ยังพบภายในรอบพัฒนาร่วมนี้จน Joint E2E ผ่าน
7. Freeze `/api/v1` Final และทีม Host/API ส่ง `KOMI_V5_2_HOST_API_FINAL_HANDOFF.zip` หนึ่งครั้งแบบสมบูรณ์

Final Handoff ต้องมีทั้ง Reference Client E2E และ Joint Desktop V5.2 E2E ที่ผ่านกับ deployed commit/migration/OpenAPI ชุดเดียวกัน ห้ามส่งเพียง source, claim, screenshot, mock response หรือ OpenAPI ที่ยังไม่ได้ deploy แล้วให้ทีม Desktop กลับไปค้นหา field mismatch หลังปิดรอบร่วม

## Shared Contract Rules — กฎกลางที่ทั้งสองทีมต้องใช้เหมือนกัน

เอกสารนี้และ Contract Bundle ที่สร้างจากเอกสารนี้เป็น source of truth กลาง ไม่ใช่เอกสารของทีม API หรือทีม Desktop ฝ่ายใดฝ่ายหนึ่ง ทั้งสองทีมต้องใช้ไฟล์และ checksum ชุดเดียวกัน:

```text
KOMI_V5_2_SHARED_CONTRACT/
├── CONTRACT_MANIFEST.json
├── openapi-v1.yaml
├── schemas/
├── AUTHENTICATION_SPEC.md
├── ERROR_CATALOG.md
├── RETRY_IDEMPOTENCY_RULES.md
├── PRIVACY_ALLOW_LIST.md
├── golden-test-vectors/
├── synthetic-fixtures/
└── SHA256SUMS.txt
```

กฎบังคับ:

1. ทั้ง API และ Desktop ต้องบันทึก `contract_version` และ `contract_sha256` เดียวกันในผล Build/Test
2. ชื่อ field, type, required/optional, enum, timestamp format, canonical signing bytes, token behavior, error code, retry และ idempotency ต้องอ้างไฟล์กลาง ห้ามเขียนกฎแยกกันคนละชุด
3. ระหว่างรอบพัฒนาร่วม ห้ามทีมใดเปลี่ยน Contract ฝ่ายเดียว การเปลี่ยนต้องแก้ Contract Bundle, เพิ่ม change note, สร้าง checksum ใหม่ และแจ้งให้อีกทีมรับ revision เดียวกันก่อน merge
4. Test fixtures ต้องเป็น Synthetic และใช้ชุดเดียวกันทั้งสองฝั่ง ห้ามใช้ข้อมูลลูกค้าจริง
5. API CI ต้อง validate implementation กับ OpenAPI/Schema/Golden vectors
6. Desktop CI ต้อง validate serialization, signature, response parsing, retry และ forbidden-data boundary กับ OpenAPI/Schema/Golden vectorsชุดเดียวกัน
7. Mock/Stub ใช้ระหว่างพัฒนาได้ แต่ Final acceptance ต้องยิง deployed Staging จริง
8. หลัง Freeze Final แล้ว `/api/v1` เป็น immutable external contract; ทั้งสองทีมแก้ internal implementation ได้แต่ผลลัพธ์ภายนอกต้องเหมือนเดิม
9. Breaking Change ต้องออก `/api/v2`; ห้ามแก้ `/api/v1` ให้ V5.2 ใช้งานไม่ได้

## Shared Definition of Done — ต้องผ่านพร้อมกัน

ถือว่า Host/Desktop Integration สมบูรณ์เมื่อผ่านครบทุกข้อบน `contract_sha256` เดียวกัน:

| Gate | API/Host | Desktop V5.2 | Joint result |
| --- | --- | --- | --- |
| Contract | OpenAPI/Schema validation PASS | Serializer/Parser validation PASS | SHA-256 ตรงกัน |
| Authentication | Register/issue/rotate/revoke PASS | Key generation/vault/signature PASS | Registration จริง PASS |
| Registration | Serial allow-list/idempotency PASS | Durable outbox/replay PASS | ไม่มี HTTP 422 mismatch |
| Status | last-seen/offline policy PASS | Heartbeat/retry/restart PASS | Dashboard Online/Offline ตรง |
| Meter | persistence/alert rules PASS | Aggregate Total Meter send PASS | Meter/read-back/alert transition ตรง |
| Privacy | forbidden fields reject/not persist PASS | forbidden fields never send PASS | Sanitized evidence PASS |
| Offline License | sign/audit/expiry PASS | verify/bind/expiry PASS | Request → License → Activate PASS |
| Failure handling | 401/403/409/422/429/503 PASS | terminal/retry/Retry-After PASS | Recovery E2E PASS |

Final acceptance ต้องรายงานพร้อมกันว่า:

```text
api_contract_tests: PASS
desktop_contract_tests: PASS
joint_desktop_staging_e2e: PASS
contract_sha256_match: PASS
known_contract_deviations: none
integration_acceptance: PASS
```

ถ้าข้อใดข้อหนึ่งไม่ผ่าน ให้ถือว่าทั้งสองฝั่งยังไม่เสร็จและต้องแก้ภายในรอบพัฒนาร่วมก่อน Final Handoff ห้ามประกาศว่างานสมบูรณ์จากผลของทีมใดทีมหนึ่งเพียงทีมเดียว

คำว่า `integration_acceptance: PASS` ครอบคลุม Registration, Status, Meter, Alert, Dashboard read-back และ Offline License ตามเอกสารนี้ ไม่ได้แปลว่า Code signing, notarization, native Windows x64 UAT หรือระบบ Update ที่ถูกเลื่อนไว้ผ่านแล้ว

## Shared telemetry schedule — รอบส่งข้อมูลกลาง

ทั้งสองทีมต้องใช้ค่าตั้งต้นเดียวกัน:

| Policy | ค่า V5.2 |
| --- | ---: |
| Status heartbeat interval | 21,600 วินาที (6 ชั่วโมง) |
| Total Meter interval | 21,600 วินาที (6 ชั่วโมง) |
| Host client-offline threshold | 259,200 วินาที (72 ชั่วโมง/3 วัน) |
| No-print threshold | 86,400 วินาที (24 ชั่วโมง) |
| Normal requests per Installation | ไม่เกิน 8 requests/วัน: Status 4 + Meter 4 |

กฎร่วม:

- Desktop ส่ง Status และ Meter ทันทีหลังเปิดโปรแกรมหรืออินเทอร์เน็ตกลับมา เฉพาะเมื่อไม่มี successful observation ภายใน 15 นาทีล่าสุด เพื่อป้องกัน restart storm
- รอบปกติมี jitter แบบสุ่ม `±10%` เพื่อไม่ให้ทุก Installation ส่งพร้อมกัน
- Host อาจตอบ `next_status_after_seconds` และ `next_meter_after_seconds` แต่ Desktop ต้อง clamp ให้อยู่ในช่วง 3,600–43,200 วินาที และใช้ค่า 21,600 วินาทีเมื่อ response ไม่ถูกต้อง
- Alert `client_offline` ใช้เวลา 72 ชั่วโมงนับจาก Status heartbeat ที่ Host รับสำเร็จล่าสุด ไม่ใช่นับจากเวลาใน Client
- Alert `no_print_activity` ใช้เวลา 24 ชั่วโมงเฉพาะเมื่อ Status ยัง Online และ Meter observation มีสถานะ `ok`; หาก Client Offline หรือ Meter unavailable ให้ suppress no-print
- ลูกค้า Offline License ไม่ส่ง Telemetry และ Dashboard ต้องแสดง `Telemetry unavailable — offline license` ไม่สร้าง Offline/no-print alert
- รอบและ threshold เป็น typed policy ที่ versioned ใน Shared Contract ห้ามแต่ละทีม hard-code คนละค่า

หลัง Joint E2E และ Final Handoff:

- ทีม Desktop จะรับผิดชอบการ integrate และแก้ Desktop ต่อจาก Contract ที่ถูก freeze แล้ว
- ทีม Desktop จะไม่ขอให้ทีม Host เปลี่ยนชื่อ field หรือสร้าง Contract ชุดเดิมใหม่
- ทีม Host สามารถพัฒนาระบบภายใน, Database และ Dashboard ต่อได้โดยอิสระ ตราบใดที่ยังรักษา `/api/v1` ที่ส่งมอบให้ Backward Compatible
- ห้ามลบ/เปลี่ยนชื่อ required field, เปลี่ยน type/meaning, เปลี่ยน auth/signing rule หรือเปลี่ยน error semantics ของ `/api/v1` แบบ Breaking Change
- การเพิ่ม field ใน `/api/v1` ทำได้เฉพาะ optional additive field ที่ Client เดิมไม่จำเป็นต้องรู้
- หากต้องมี Breaking Change ให้สร้าง `/api/v2` และคง `/api/v1` ให้ V5.2 ใช้งานตามระยะ Support ที่ประกาศ ห้ามเปลี่ยน `/api/v1` เงียบ ๆ

ข้อจำกัดนี้เป็นเงื่อนไขที่จำเป็นต่อการให้ Desktop และ Host แก้ไขงานแยกกันได้ หาก Host เปลี่ยน Contract ที่ Freeze แล้วโดยไม่รักษา Backward Compatibility จะไม่มี Client ใดรับประกันการทำงานต่อได้

## Prompt สำหรับส่งให้ทีม Host/API

คัดลอกข้อความในส่วนนี้ส่งให้ทีมได้เลย

> ช่วยพัฒนา **KOMI Report V5.2 Host/API** บนระบบ Hosting ที่ทีมดูแล โดยแบ่งงานออกเป็น 2 ส่วน:
>
> 1. Online Registration, Status และ Total Meter สำหรับลูกค้าที่มีอินเทอร์เน็ต
> 2. Offline License Generator สำหรับลูกค้าที่ไม่มีอินเทอร์เน็ต
>
> Database, Billing, User, Document และ Print Job ของลูกค้าต้องอยู่ภายในเครื่องลูกค้า ไม่อัปโหลดขึ้น Host ระบบ Update, forced update, remote desktop และคำสั่งควบคุมเครื่องลูกค้าไม่อยู่ในขอบเขตนี้
>
> ลูกค้าต้องไม่กรอกหรือขอ API Key เอง และห้ามฝัง Shared/Master API Key ไว้ในไฟล์ `.exe`, `.app`, source code หรือ installer. Desktop ต้องลงทะเบียนอัตโนมัติครั้งแรก แล้ว Host ออก Credential เฉพาะ Installation กลับมาให้เก็บใน Windows Credential Manager หรือ macOS Keychain
>
> ### Blocker ที่ต้องแก้ก่อน
>
> Canonical Production base URL ปัจจุบันคือ `https://www.dmskm.com` แต่ current Desktop schema-v2 request เคยได้รับ `HTTP 422 VALIDATION_ERROR` เพราะ deployed privacy allow-list ไม่รับ `device_inventory.devices[].serial_number`.
>
> ต้อง migrate allow-list, persistence, OpenAPI และ Dashboard ให้ใช้ `serial_number` ตาม Desktop contract ห้ามแก้ Desktop ย้อนกลับไปใช้ `device_instance_id`. ห้ามถือว่า Health หรือหน้า Dashboard ที่เปิดได้เป็นหลักฐานว่า contract ตรงกัน
>
> ### ข้อมูลจาก Online Desktop ไป Host มี 3 ประเภทเท่านั้น
>
> 1. Registration
> 2. Status heartbeat
> 3. Aggregate Total Meter observation
>
> Host อาจตอบสถานะ, token, retry policy และรอบส่งครั้งถัดไปใน response แต่ห้ามส่ง arbitrary command, shell command, file-access command, update command หรือคำสั่งควบคุม Desktop

## 0. Authentication architecture — ห้ามฝัง Shared API Key

Target flow:

1. เมื่อเปิดครั้งแรก Desktop สร้าง Ed25519 key pair ภายในเครื่อง
2. Private key เก็บใน Windows Credential Manager หรือ macOS Keychain และห้าม export
3. Desktop ส่งเฉพาะ Public key พร้อม Registration payload และลายเซ็นของ request
4. Host ตรวจ schema, request signature, Serial policy, duplicate/idempotency และ rate limit
5. Host ออก Installation Token ที่ใช้ได้เฉพาะ Installation นั้น
6. Desktop เก็บ Token ใน OS vault และใช้กับ Status/Meter API
7. Host ต้อง rotate/revoke Token ได้ โดยไม่เปลี่ยน Installation ID หรือให้ลูกค้ากรอก Key

ค่าที่ฝังใน Desktop ได้มีเพียงค่าที่ **ไม่ใช่ Secret**:

- Canonical API Base URL
- Public `client_id` เช่น `komi-report-desktop`
- Host public verification key / `kid` สำหรับตรวจ response หรือ Offline License
- Schema/version identifiers

ห้ามฝังหรือส่งกลับมาให้ทีม Desktop/Codex:

- Master API Key
- Dashboard/Admin token
- Database password
- Token-signing secret/private key
- Offline License signing private key
- Shared bootstrap secret ที่ใช้เหมือนกันทุก Installation

ข้อจำกัดที่ต้องระบุอย่างตรงไปตรงมา: client-generated key pair ยืนยันความต่อเนื่องและผูก Token กับ Installation ได้ แต่ไม่สามารถพิสูจน์ว่า executable มาจากผู้ผลิตเพียงอย่างเดียว หากต้องป้องกันบุคคลภายนอกเลียนแบบ client ให้ใช้ Host approval policy, signed installer/attestation หรือ deployment control เพิ่มเติม ห้ามแก้ด้วยการฝัง Shared Secret ใน Desktop

## 1. Registration contract

Endpoint ที่แนะนำ:

`POST /api/v1/installations/register`

Headers:

- `Content-Type: application/json`
- `Idempotency-Key: <UUID ต่อ operation>`
- ไม่ใช้ Shared/Master API Key
- Initial request ใช้ public `client_id` และ proof-of-possession signature ตาม specification ที่ทีม Host ต้องส่งกลับ

Target body:

```json
{
  "schema_version": 3,
  "event_type": "installation_registered",
  "client_id": "komi-report-desktop",
  "installation_id": "b4c851b7-9533-4ea6-999a-d85ecf5af078",
  "installation_public_key": "base64url-ed25519-public-key",
  "proof_algorithm": "Ed25519",
  "company_name": "Example Company Co., Ltd.",
  "client_first_started_at": "2026-08-25",
  "app_version": "5.2.0",
  "platform": "Windows",
  "architecture": "x64",
  "device_inventory": {
    "konica_discovered_count": 6,
    "devices": [
      {"serial_number": "SYNTH-001", "model": "bizhub C450i", "selected": true, "device_slot": 1},
      {"serial_number": "SYNTH-002", "model": "bizhub C750i", "selected": true, "device_slot": 2},
      {"serial_number": "SYNTH-003", "model": "AccurioPress C7090", "selected": true, "device_slot": 3},
      {"serial_number": "SYNTH-004", "model": "bizhub C458", "selected": false, "device_slot": null},
      {"serial_number": "SYNTH-005", "model": "bizhub C368", "selected": false, "device_slot": null},
      {"serial_number": "SYNTH-006", "model": "bizhub C300i", "selected": false, "device_slot": null}
    ]
  },
  "created_at": "2026-08-25T03:00:00Z",
  "request_signature": "base64url-signature-over-canonical-request"
}
```

Validation:

- `installation_id` unique และคงเดิมตลอดอายุ Installation
- `installation_public_key` ผูกกับ Installation และการเปลี่ยน key ต้องผ่าน recovery/rotation flow ที่มี Audit Log
- ตรวจ `request_signature` จาก canonical request bytes ตาม test vector ที่ประกาศร่วมกับ OpenAPI
- `konica_discovered_count` ต้องเท่ากับจำนวน `devices[]`
- `serial_number` ต้องไม่ว่างและไม่ซ้ำใน snapshot
- `selected=true` ได้สูงสุด 3 เครื่องและต้องมี Slot 1–3 ที่ไม่ซ้ำ
- `selected=false` ต้องมี `device_slot=null`
- Server คำนวณจำนวน discovered/selected เอง ห้ามเชื่อค่ารวมโดยไม่ตรวจรายการ
- Request ที่มี IP, MAC, hostname, credential, user, document, job, detailed counter หรือ application log ต้องถูกปฏิเสธ

Target response:

```json
{
  "schema_version": 3,
  "installation_id": "b4c851b7-9533-4ea6-999a-d85ecf5af078",
  "registration_status": "registered",
  "registered_at": "2026-08-25T03:00:01Z",
  "installation_token": "returned-only-on-issue-or-rotation-and-never-logged",
  "token_type": "Bearer",
  "expires_in": 2592000,
  "next_status_after_seconds": 21600,
  "next_meter_after_seconds": 21600
}
```

Register ซ้ำด้วย operation/fingerprint เดิมต้องคืนผลเดิมและไม่สร้าง Installation/Token ซ้ำ

ทีม Host ต้องกำหนดและทดสอบ policy สำหรับ Serial ที่ถูก Registration จาก Installation อื่น เช่น first-claim, pending approval, replacement หรือ conflict. ห้ามย้าย ownership เงียบ ๆ และห้ามให้ Duplicate Registration สร้างสิทธิ์ซ้ำโดยไม่มี Audit Log

## 2. Status heartbeat contract

Endpoint ที่แนะนำ:

`POST /api/v1/installations/status`

Headers:

- `Authorization: Bearer <installation token>`
- `Idempotency-Key: <UUID ต่อ operation>`

Target body:

```json
{
  "schema_version": 3,
  "event_type": "installation_status",
  "installation_id": "b4c851b7-9533-4ea6-999a-d85ecf5af078",
  "app_version": "5.2.0",
  "platform": "Windows",
  "architecture": "x64",
  "occurred_at": "2026-08-25T03:02:00Z"
}
```

กติกา:

- Client ไม่ส่ง boolean `online` หรือ `offline`
- Server ถือว่ารับ request สำเร็จคือ Online observation และคำนวณ Offline จาก `last_seen_at`
- Desktop ส่งรอบปกติทุก 21,600 วินาที พร้อม jitter `±10%`
- Offline threshold ค่า V5.2 คือ 259,200 วินาที (72 ชั่วโมง/3 วัน) และต้องเป็น versioned policy เดียวกันทั้ง API/Dashboard
- เก็บ typed fields เท่านั้น ห้ามเก็บ raw request body หรือ bearer token
- Response แจ้ง `next_status_after_seconds` และ optional rotated token ตาม token lifecycle ที่ประกาศใน OpenAPI
- Host ใช้เวลาที่รับ request สำเร็จเป็น `last_seen_at`; `occurred_at` จาก Client ใช้เป็น observation metadata และต้องตรวจ clock-skew
- หากมี unsent Status ค้างอยู่ Desktop เก็บเพียง observation ล่าสุด ไม่สะสม Heartbeat เก่าทุก 6 ชั่วโมง
- การแทน pending observation ต้องสร้าง Idempotency-Key/fingerprint ใหม่แบบ atomic; ห้ามใช้ key เดิมกับ body ที่เปลี่ยน

Target response:

```json
{
  "schema_version": 3,
  "installation_id": "b4c851b7-9533-4ea6-999a-d85ecf5af078",
  "received_at": "2026-08-25T03:02:01Z",
  "next_status_after_seconds": 21600
}
```

## 3. Aggregate Total Meter contract

Endpoint ที่แนะนำ:

`POST /api/v1/installations/meter-observations`

Headers:

- `Authorization: Bearer <installation token>`
- `Idempotency-Key: <UUID ต่อ operation>`

Target body:

```json
{
  "schema_version": 3,
  "event_type": "meter_observed",
  "installation_id": "b4c851b7-9533-4ea6-999a-d85ecf5af078",
  "observations": [
    {
      "serial_number": "SYNTH-001",
      "model": "bizhub C450i",
      "device_slot": 1,
      "total_meter": 266857,
      "meter_observed_at": "2026-08-25T03:00:00Z",
      "meter_status": "ok"
    }
  ],
  "sent_at": "2026-08-25T03:00:10Z"
}
```

กติกา:

- รับเฉพาะ selected Serial/Slot ที่อยู่ใน Registration ล่าสุด
- Desktop ส่ง Meter ของ selected devices สูงสุด 3 เครื่องรวมใน request เดียวทุก 21,600 วินาที พร้อม jitter `±10%`
- `total_meter` เป็น aggregate non-negative integer; ห้ามรับ detailed color/B&W/copy/print/user/job counters ใน contract นี้
- `meter_status` ใช้ allow-list เช่น `ok` หรือ `unavailable`; ห้ามส่ง raw SNMP/Web error หรือ raw XML
- Meter ซ้ำด้วย idempotency key/fingerprint เดิมต้องไม่สร้าง sample ซ้ำ
- Counter ลดลงต้องสร้าง reset/replacement candidate ไม่ถือว่าเป็น printing activity และไม่คำนวณ delta ติดลบ
- Server เป็น authority ของ `last_meter_changed_at`
- แม้ Total Meter ไม่เปลี่ยน Desktop ยังส่ง observation ล่าสุด เพื่อให้ Host แยก “อ่าน Meter ได้แต่ไม่มีงานพิมพ์” ออกจาก `meter_unavailable`
- หากมี unsent Meter ค้างอยู่ Desktop เก็บเฉพาะ observation ล่าสุดต่อ selected Serial และส่งรวมเป็น batch เดียว ไม่สะสมทุก snapshot เก่า
- การแทน pending Meter batch ต้องสร้าง Idempotency-Key/fingerprint ใหม่แบบ atomic

## 3.1 Retry, backoff และ queue coalescing

- `429/503` ใช้ `Retry-After` จาก Host และเพิ่ม jitter
- Network/5xx ที่ไม่มี `Retry-After` ใช้ลำดับประมาณ 15 นาที → 1 ชั่วโมง → 6 ชั่วโมง และ cap ที่ 6 ชั่วโมง
- `400/401/403/409/422` ต้องใช้ terminal/recovery behavior ตาม Error Catalog; ห้าม retry storm
- Outbox เก็บได้สูงสุดหนึ่ง pending Status และหนึ่ง pending Meter batch ต่อ Installation
- Event ที่กำลังส่งอยู่ห้ามถูกแก้กลาง request; observation ใหม่แทนได้เฉพาะ pending item ที่ยังไม่ in-flight
- Process restart ต้อง recover pending item ล่าสุดพร้อม fingerprint/idempotency ที่ตรงกัน
- ส่งสำเร็จแล้วลบ pending item แบบ durable ห้าม replay ซ้ำหลัง restart

## 4. Alert rules

Host ต้องแยกอย่างน้อย:

- `client_offline`: ไม่ได้รับ Status heartbeat สำเร็จเกิน 259,200 วินาที (72 ชั่วโมง/3 วัน)
- `no_print_activity`: Status heartbeat ยังมา แต่ Total Meter ของ selected device ไม่เพิ่มเกิน 24 ชั่วโมง หลังหัก maintenance/quiet/holiday policy ที่อนุมัติ
- `meter_unavailable`: Client ยัง Online แต่ไม่มี Total Meter ที่เชื่อถือได้ตาม threshold

Priority:

1. `client_offline`
2. `meter_unavailable`
3. `no_print_activity`

เมื่อ Client Offline ต้อง suppress `no_print_activity` ที่ซ้อนกัน ห้ามสรุปว่าเครื่องพิมพ์เสีย ข้อความผู้ใช้ให้ใช้ “ควรตรวจสอบ”

Alert ต้องรองรับ `new`, `acknowledged`, `resolved`, `muted` พร้อม actor/time/audit reason และต้อง resolve อย่างปลอดภัยเมื่อ Meter เพิ่มหรือสถานะกลับมาปกติ

## 5. Offline License Generator

ลูกค้า Offline จะไม่เรียก Registration/Status/Meter API. Host ใช้สำหรับเจ้าหน้าที่สร้าง Signed License จากไฟล์ Request เท่านั้น

### Offline request ที่ Desktop สร้าง

นามสกุลไฟล์: `.komirequest`

Target fields:

```json
{
  "request_version": 1,
  "request_id": "bd378348-52fb-4a8a-a834-1103640adf06",
  "company_name": "Example Offline Company Co., Ltd.",
  "installation_id": "391dcf7d-31c5-4b5e-b91a-601b7d71cc30",
  "installation_public_key": "base64-public-key",
  "app_version": "5.2.0",
  "platform": "Windows",
  "architecture": "x64",
  "selected_devices": [
    {"serial_number": "SYNTH-OFF-001", "model": "bizhub C450i", "device_slot": 1}
  ],
  "created_at": "2026-08-25T03:00:00Z",
  "request_signature": "signature-created-by-installation-private-key"
}
```

Host UI ต้อง:

1. Upload `.komirequest`
2. Validate schema/signature/duplicate request
3. แสดง Company, Installation และ Serial จาก Request แบบ read-only ไม่ให้เจ้าหน้าที่พิมพ์ Serial เอง
4. ให้เลือกวันเริ่มและวันหมดอายุ โดยอายุไม่เกิน 5 ปี
5. กดสร้าง `.komilicense`
6. บันทึกผู้สร้าง เวลา เหตุผล และ request/license fingerprint ใน Audit Log
7. ดาวน์โหลด License เพื่อส่งให้ลูกค้าทางช่องทางภายนอก

### Signed Offline License

License ต้องผูกกับ:

- `license_id` และ `license_version`
- `request_id`
- Company/Installation ID
- hash ของ Installation Public Key
- Serial/Model/Slot จาก Request
- `max_desktop_installations: 1`
- `max_selected_printers: 3`
- `issued_at`, `valid_from`, `expires_at` โดยไม่เกิน 5 ปี
- signing `key_id` (`kid`)
- signature ของ Host

แนะนำ Ed25519 + canonical JSON/JWS หรือรูปแบบ signed envelope ที่มี test vector ชัดเจน. Host signing private key ต้องอยู่ใน secret manager/OS vault และห้ามอยู่ใน Git, log, screenshot, artifact หรือแชต. ส่งให้ทีม Desktop เฉพาะ public verification key + `kid`.

การคัดลอก License ไป Desktop อื่นต้องใช้ไม่ได้ เพราะ Installation อื่นไม่มี private key คู่กับ public-key hash ใน License. การยกเลิก License ก่อนหมดอายุไม่สามารถบังคับกับเครื่องที่ Offline ตลอดเวลาได้; Dashboard ต้องแสดงข้อจำกัดนี้อย่างตรงไปตรงมา

## 6. Database และ Private Host Dashboard

Data model อย่างน้อย:

- `companies`
- `installations`
- `installation_tokens` หรือ hashed token references
- `installation_device_snapshots` และ items
- `status_heartbeats`
- `meter_observations`
- `device_meter_state`
- `alerts` และ `alert_history`
- `registration_idempotency`
- `offline_license_requests`
- `offline_licenses`
- `audit_log`

Dashboard ต้องแสดง:

- บริษัท, Installation, Version, OS/Architecture
- Last seen และ Online/Offline ที่ Server คำนวณ
- Discovered/Selected devices และ Serial/Model/Slot
- Total Meter ล่าสุดและ `last_meter_changed_at`
- Alert ตาม priority พร้อม acknowledge/resolve/mute
- Offline License: บริษัท, Installation, Serial, อายุ License, ผู้สร้าง, สถานะใกล้หมดอายุ/หมดอายุ
- Offline License ต้องแสดง `Telemetry unavailable — offline license` ไม่ตีความเป็น Client Offline
- Search/filter/export เฉพาะ field ที่อนุญาต

Dashboard ต้องอยู่หลัง MFA/RBAC หรือระบบ Login ที่เทียบเท่า และทุก action สำคัญต้องมี Audit Log

## 7. Security, privacy และ operation

- Production/Staging ใช้ HTTPS certificate ถูกต้อง
- Desktop ห้ามต่อ Hosting database โดยตรง
- Validate request ด้วย strict allow-list และจำกัด body/batch size
- Rate limit และ `Retry-After`
- Token ต่อ Installation เก็บ Server แบบ hash และ rotate/revoke ได้
- Initial Registration เป็น public-client flow พร้อม proof-of-possession; ไม่มี Shared API Key ใน Desktop
- Server-side signing secret/private key อยู่ใน Hosting secret manager เท่านั้น
- Error response มี typed code, safe message, request ID และ retryable flag
- ห้าม persist Source IP ใน application data/log policy ของ KOMI
- ห้ามเก็บ raw body, token, credential, IP/MAC/hostname, user, document, job, detailed counter หรือ application log
- Meter/Serial ที่เพิ่มใน V5.2 ต้องปรากฏใน Registration Data Notice และ retention/access/delete policy
- Migration ต้อง rollback-safe และมี backup/restore drill
- Staging แยกจาก Production
- Canonical Base URL ต้องตรงและ Client ไม่ควรถูกบังคับผ่าน redirect
- ระบบ Update ไม่อยู่ใน contract นี้

## Error contract

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Safe message",
    "request_id": "server-request-id",
    "retryable": false
  }
}
```

รองรับอย่างน้อย `200/201`, `400`, `401/403`, `409`, `422`, `429`, `500/503`. ใช้ `Retry-After` สำหรับ `429/503` และประกาศ terminal/retryable behavior ใน OpenAPI

## Acceptance tests ที่ทีม Host ต้องผ่าน

### No-return-until-pass gate

ทีม Host/API เป็นเจ้าของการแก้, deploy Staging และทดสอบซ้ำจนผ่านกับ **Frozen KOMI Report V5.2 Contract** ผ่าน Reference Client/Golden Test Vectors ระหว่างที่ทีม Desktop พัฒนา Client พร้อมกัน ห้ามส่งงานกลับมาในสถานะ “ทำ API เสร็จแล้ว แต่ Contract test ยังไม่ผ่าน” หรือให้ทีม Desktop กลับมาเดาชื่อ field เพื่อชดเชย API ที่ไม่ตรงเอกสาร.

หากพบ `HTTP 422`, field/allow-list ไม่ตรง, migration ไม่ครบ, token ใช้ไม่ได้, Dashboard read-back ไม่ตรง, Meter/Alert ผิด หรือ Offline License verify ไม่ผ่าน ให้ทีม Host:

1. เก็บงานไว้สถานะ `IN PROGRESS` หรือ `HOLD — HOST OWNER`
2. แก้ API/Database/Dashboard/Signing implementation ที่ฝั่ง Host
3. Deploy Staging revision ใหม่
4. รัน Frozen Contract Reference Client E2E ซ้ำตั้งแต่ต้น
5. ส่งมอบได้เมื่อผลสุดท้ายเป็น PASS เท่านั้น

ห้ามใช้ adapter ชั่วคราว, rename field เงียบ ๆ, fallback ไป `device_instance_id`, mock response, manual database edit หรือ Production request แทน Staging proof. หากเป็น blocker ที่ต้องใช้สิทธิ์/Secret/ค่าใช้จ่าย/การตัดสินใจจาก Bom จริง ให้รายงาน blocker นั้นโดยระบุว่า **ยังไม่ส่งมอบ**; bug หรือ contract mismatch ทั่วไปไม่ใช่เหตุผลให้คืนงานก่อนแก้เสร็จ.

Final handoff ต้องมี `acceptance_decision: PASS`, `known_contract_deviations: none` และหลักฐาน Reference Client E2E ที่อ้าง deployed commit/migration/OpenAPI ชุดเดียวกัน หากไม่มีสามรายการนี้ให้ถือว่างานยังอยู่ฝั่ง Host/API.

ก่อน Freeze Final Handoff ต้องมี `joint_desktop_v5_2_e2e: PASS` จาก Desktop V5.2 build จริงด้วย หาก Reference Client ผ่านแต่ Desktop จริงไม่ผ่าน ให้ทั้งสองทีมเทียบ request/signature/response กับ Golden Test Vector และแก้ owner ที่ผิด Contract ภายในรอบพัฒนาร่วม ห้ามปิดงานโดยโยนปัญหาให้อีกฝั่งหลัง Final Handoff

การทดสอบ Final Handoff ต้องใช้ Reference Client ที่แนบ source/config/instructions ครบและเรียก deployed Staging revision ที่ระบุใน Manifest จริง Reference Client ต้องใช้ OpenAPI, canonical signing, auth/token และ payload เดียวกับ Contract นี้ ไม่ใช่ request เฉพาะกิจที่เขียนให้ผ่านเพียง endpoint เดียว ห้ามใช้ manual database edit หรือ screenshot แทน E2E. Postman ใช้เป็นหลักฐานเสริมได้ แต่ไม่แทน automated Reference Client suite

### Online API

- ตรวจ binary/source/config ว่าไม่มี Shared/Master API Key ฝังอยู่
- First-run สร้าง Installation key pair และ Register ได้โดยลูกค้าไม่กรอก Key
- Signature ที่ถูกต้องผ่าน; body/signature/public key ที่ถูกแก้ไขถูกปฏิเสธ
- Installation Token ผูกกับ Installation และ rotate/revoke/recovery ได้
- Reference Client ส่ง `serial_number` ตาม Frozen Contract แล้ว Register ผ่านและไม่ตอบ 422 จาก allow-list เดิม
- 4–6 discovered / 3 selected ผ่าน; 4 selected ถูกปฏิเสธ
- Serial/Slot ซ้ำถูกปฏิเสธ
- Forbidden field ถูกปฏิเสธและไม่ถูก persist/log
- Register/Status/Meter replay แบบ idempotent ไม่สร้างแถวซ้ำ
- Token ผิด/หมดอายุ/revoked ถูกปฏิเสธ
- Rate limit และ `Retry-After` ทำงาน
- Missing heartbeat เปลี่ยนเป็น `client_offline`
- Heartbeat ปกติ 4 ครั้ง/วัน และ Meter batch ปกติ 4 ครั้ง/วัน; ไม่เกิดการสะสม request เก่าเมื่อ Offline
- Heartbeat ยังมาแต่ Meter ไม่เปลี่ยนเกิน 24 ชั่วโมงสร้าง `no_print_activity`
- Offline suppress no-print ที่ซ้อนกัน
- App restart/network recovery ภายใน 15 นาทีไม่สร้าง request storm
- Jitter และ clamp ของ interval ทำงานตาม Shared telemetry schedule
- Retry-After/Backoff ไม่สร้าง duplicate row และ process restart recover เฉพาะ pending observation ล่าสุด
- Meter เพิ่มแล้ว resolve alert
- Counter ลดลงไม่สร้าง delta ติดลบหรือ false activity
- Dashboard read-back ตรงกับ request typed fields

### Offline License

- Request signature ถูกต้องจึง import ได้
- Request ที่แก้ไข/ลายเซ็นผิด/ซ้ำถูกปฏิเสธอย่างถูกต้อง
- Serial/Model/Slot auto-fill และ read-only
- กำหนดอายุเกิน 5 ปีไม่ได้
- License signature verify ผ่านด้วย public test key
- License ที่ถูกแก้ไข verify ไม่ผ่าน
- License subject ผูกกับ Installation Public Key hash
- License/Request fingerprint และ Audit Log ตรงกัน
- Signing private key ไม่ปรากฏใน source/log/artifact/screenshot/test fixture

## Definition of Done — สิ่งที่ทีม Host/API ต้องส่งกลับ

1. **Staging Base URL** และผล `GET /health` ผ่าน HTTPS โดยไม่ redirect
2. **OpenAPI 3.x** ที่ตรงกับระบบ Staging ที่ deploy จริง ครบ Registration, Status, Meter และ Error contract
3. **Source repository + branch/tag/commit hash** ที่ใช้ deploy
4. **Database migration version**, schema diff และ rollback procedure
5. **`.env.example`** ที่มีเฉพาะชื่อตัวแปร; Secret จริงส่งผ่านช่องทางปลอดภัยแยกต่างหาก
6. **Authentication/token lifecycle specification**: canonical signing bytes, algorithm, public-client Registration, proof verification, อายุ token, rotate, revoke, recovery และ vault/secret reference โดยไม่ส่งค่าจริงในแชต
7. **Sanitized request/response evidence**: register ครั้งแรก/ซ้ำ, status, meter, bad/revoked token, validation failure, rate limit และ Retry-After
8. **Automated test report** สำหรับ validation, idempotency, auth, privacy boundary, alerts, license signature และ database uniqueness
9. **Private Dashboard URL + role/test account delivery method** ผ่านช่องทางปลอดภัย
10. **Dashboard screenshots/read-back evidence** ของ company/installation/devices/status/meter/alerts/offline license โดยใช้ข้อมูล Synthetic เท่านั้น
11. **Offline License test package**: synthetic `.komirequest`, `.komilicense`, public verification key, `kid`, canonicalization/signature specification และ test vectors; ห้ามส่ง private signing key
12. **Retention matrix** ของ Registration, Status, Meter, Alert, Offline License และ Audit Log
13. **Backup/restore/monitoring/runbook** พร้อมผู้รับผิดชอบและวิธี rollback deployment
14. **Known gaps/deviations** จากเอกสารนี้เป็นรายการ ห้ามเปลี่ยน field เงียบ ๆ
15. **Deployment evidence**: environment, deployed commit, migration applied, UTC time และ sanitized smoke result
16. **Frozen Contract Reference Client acceptance report** ที่ยืนยัน Register → idempotent replay → Status → Meter → Dashboard read-back → Alert transition ครบ โดย `HTTP 422`/contract mismatch เป็นศูนย์
17. **Final acceptance statement**: `acceptance_decision: PASS` และ `known_contract_deviations: none`; หากระบุ HOLD/partial/deviation ให้ถือว่ายังไม่ส่งมอบ
18. **Authentication test vectors**: canonical Registration bytes, installation public key, valid signature, invalid/tampered signature และ expected response โดยใช้ Synthetic key เท่านั้น
19. **Secret-scan evidence**: ยืนยันว่า Desktop/source/installer/OpenAPI/test fixture ไม่มี Shared/Master API Key, private signing key, database credential หรือ real token
20. **Frozen Contract identity**: API version, OpenAPI SHA-256, schema bundle SHA-256, deployed commit, migration version และวันเริ่ม Backward Compatibility support
21. **Compatibility policy**: หนังสือยืนยันว่า `/api/v1` จะไม่เกิด Breaking Change; งานใหม่ที่ไม่ Compatible จะใช้ `/api/v2`
22. **Joint Desktop V5.2 E2E report**: Desktop build identity, API deployed commit, OpenAPI SHA-256, migration version และผล Register/Replay/Status/Meter/Dashboard/Alert ครบในชุดเดียวกัน

## ชุดไฟล์ที่ต้องส่งกลับครั้งเดียว

ให้ส่งเป็นไฟล์เดียวชื่อ:

`KOMI_V5_2_HOST_API_FINAL_HANDOFF.zip`

ภายในต้องมีอย่างน้อย:

```text
KOMI_V5_2_HOST_API_FINAL_HANDOFF/
├── HANDOFF_MANIFEST.json
├── ACCEPTANCE_RESULT.md
├── openapi/
│   ├── openapi-v1.yaml
│   ├── schemas/
│   └── OPENAPI_SHA256.txt
├── authentication/
│   ├── AUTHENTICATION_SPEC.md
│   ├── public-client-config.json
│   ├── public-verification-keys.json
│   └── test-vectors/
├── examples/
│   ├── registration/
│   ├── status/
│   ├── meter/
│   └── errors/
├── reference-client/
│   ├── README.md
│   ├── source/
│   ├── non-secret-config.example
│   └── run-reference-e2e
├── migrations/
│   ├── MIGRATION_REPORT.md
│   └── ROLLBACK_PROCEDURE.md
├── tests/
│   ├── REFERENCE_CLIENT_E2E_REPORT.md
│   ├── JOINT_DESKTOP_V5_2_E2E_REPORT.md
│   ├── AUTOMATED_TEST_REPORT.md
│   ├── SECURITY_PRIVACY_REPORT.md
│   └── sanitized-evidence/
├── dashboard/
│   ├── DASHBOARD_READBACK_REPORT.md
│   └── sanitized-screenshots/
├── offline-license/
│   ├── OFFLINE_LICENSE_SPEC.md
│   ├── synthetic.komirequest
│   ├── synthetic.komilicense
│   └── test-vectors/
├── operations/
│   ├── RETENTION_MATRIX.md
│   ├── BACKUP_RESTORE_RUNBOOK.md
│   ├── MONITORING_RUNBOOK.md
│   └── COMPATIBILITY_POLICY.md
└── SHA256SUMS.txt
```

`HANDOFF_MANIFEST.json` ต้องระบุอย่างน้อย:

```json
{
  "product": "KOMI Report",
  "desktop_version": "5.2.0",
  "api_contract_version": "v1",
  "environment": "staging",
  "canonical_base_url": "https://example.invalid",
  "deployed_commit": "commit-hash",
  "database_migration": "migration-version",
  "openapi_sha256": "sha256",
  "checksums_file_sha256": "sha256-of-SHA256SUMS.txt",
  "reference_client_e2e": "PASS",
  "joint_desktop_v5_2_e2e": "PASS",
  "acceptance_decision": "PASS",
  "known_contract_deviations": [],
  "shared_api_key_embedded_in_desktop": false,
  "backward_compatible_v1": true
}
```

หากรายการใดไม่ครบ, ค่าไม่ตรงกัน, E2E ไม่ผ่าน, Manifest ไม่ใช่ PASS หรือ checksum ไม่ตรง ให้ถือว่ายังไม่ใช่ Final Handoff และทีม Host/API ต้องแก้ให้ครบก่อนส่งไฟล์ออกมา ไม่ส่งงานที่ไม่สมบูรณ์ให้ Bom หรือทีม Desktop รับไปไล่แก้ต่อ

ห้ามส่ง secret, bearer token, private signing key, raw customer payload หรือข้อมูลลูกค้าจริงผ่านแชต

## ข้อความตอบกลับที่ทีม Host ใช้ส่งมอบ

ให้ทีม Host ส่งข้อความรูปแบบนี้กลับมา พร้อมแนบไฟล์ที่ระบุ:

```text
KOMI Report V5.2 Host/API handoff

Environment: <staging>
Base URL: <canonical HTTPS URL>
Health result: <status/time>
OpenAPI file: <attachment/path>
Source repository/branch/commit: <repo / branch / commit>
Database migration: <version>
Bootstrap method: <method; no secret value>
Public client ID: <non-secret client identifier>
Installation proof algorithm: <algorithm/canonicalization spec>
Token lifecycle: <issue/expiry/rotate/revoke>
Offline signing algorithm/kid: <algorithm / public key reference>
Dashboard URL and role delivery: <URL / secure channel>
Automated tests: <summary and report attachment>
Synthetic E2E evidence: <attachment>
Retention/backup/rollback runbook: <attachment>
Known deviations: <none or numbered list>
Reference Client E2E: <PASS with evidence attachment>
Joint Desktop V5.2 E2E: <PASS with build/API/OpenAPI identity>
Acceptance decision: <PASS only for final handoff>
Frozen API contract: </api/v1 + OpenAPI SHA-256>
Backward compatibility commitment: <confirmed>
Final handoff ZIP: <filename / SHA-256>

Secret location/reference: <secure location only; do not paste values>
Shared/Master API Key embedded in Desktop: no
Production deployed: no
Production action requested: no
```

ทีม Host ต้องรัน Frozen Contract Reference Client E2E และ Offline License verification ระหว่างที่ทีม Desktop พัฒนา V5.2 Client พร้อมกัน จากนั้นทั้งสองทีมต้องรัน Joint Desktop V5.2 E2E กับ Staging จนผ่านก่อน Final Handoff. หลังรับ Final PASS ทีม Desktop จะตรวจ checksum และยึด Frozen Contract ต่อโดยไม่ย้อนกลับไปขอทีม Host เปลี่ยน field หรือสร้าง handoff ใหม่ ห้ามใช้ Production แทน Staging และห้ามประกาศ PASS จากเอกสารหรือ screenshot เพียงอย่างเดียว

หลังทีม Desktop รับและตรวจ `KOMI_V5_2_HOST_API_FINAL_HANDOFF.zip` ผ่านแล้ว การพัฒนา Desktop ต่อจากนั้นต้องยึด Frozen `/api/v1` Contract และจัดการ Compatibility ภายใน Desktop เอง ส่วนทีม Host แก้ implementation ภายในได้โดยไม่ต้องประสาน Desktop ตราบใดที่ผลลัพธ์ภายนอกยังตรง Frozen Contract. หากทีม Host ต้องเปลี่ยน Contract ภายนอก ให้ทำเป็น API versionใหม่และไม่กระทบ V5.2
