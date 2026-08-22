---
project_id: komi-report-v5
project_name: KOMI Report V5.1
thread_id: 019f69b5-6709-7e53-8ebf-a35114d233d0
thread_title: Komi report V5
dashboard_visible: true
department: dev
status: blocked
progress: 86
owner: VEGA
current_phase: Production Phase 6 customer release packaging completed as RELEASE HOLD
current_task: keep the cross-platform HOLD bundle internal and close Registration/signing/native Windows gates
next_action: migrate deployed Registration allow-list/persistence/Dashboard to serial_number and rerun current-client E2E before signing/native release closure
problem: RELEASE HOLD — live current-client Registration returns HTTP 422; macOS trust and Windows Authenticode/native x64/Tray/Auto-start/LAN evidence remain incomplete
updated_at: 2026-08-22T20:38:00+07:00
---

# KOMI Report V5.1

## Current release decision — 2026-08-22

- Bom เลื่อน Production Phase 3 ระบบ Update ทั้งหมดออกจากเป้าหมาย Release สิ้นเดือนนี้ เนื่องจากเวลาไม่พอ.
- เก็บ Signed Manifest, verified download, rollout และ updater/installer automation เป็น backlog หลัง Release; ห้ามลบ design เดิมและห้ามเริ่ม implementation โดยไม่มีงานใหม่ที่อนุมัติชัดเจน.
- Release ปัจจุบันไปต่อที่ **Production Phase 4 — Native Packaging & Release Candidate** โดยใช้ Windows 10/11 x64 เป็นเป้าหมายลูกค้าหลัก, macOS เป็น Internal UAT และ Linux deferred.
- Registration/Heartbeat คงสถานะ fail-closed จน OpenAPI/Staging และ Registration Data Notice/Hosting Security gates ผ่าน; การข้าม Phase 3 ไม่ได้เปลี่ยน Phase 2 จาก Technical Pass / Production blocked เป็น Production Pass.
- Bom เลื่อน Windows code signing ออกไปก่อนเพราะเป็นโปรแกรมแจกฟรี; ถือเป็น **Deferred / ยังไม่ผ่าน** ไม่ใช่ Signed release.
  การทดสอบภายในหรือ Pilot ใช้ unsigned installer ได้เมื่อแจ้งคำเตือนและตรวจ SHA256 แต่ห้ามแสดง Publisher ว่า verified
  หรือ claim ว่า Authenticode ผ่าน.
- Release Candidate นี้ไม่มี forced/silent update, remote update command หรือ update telemetry.

## Goal

สร้าง KOMI Report V5.1 แบบ Desktop local-first พร้อม Web Edition สำหรับผู้ใช้ในแผนก ที่ตั้งค่าเครื่องพิมพ์ 1–3 เครื่องครั้งแรก แล้วอ่าน Meter
อัตโนมัติใน Background โดยใช้ SNMP ตรวจสถานะและใช้ Web Connection เป็น Meter หลัก เก็บค่าดิบครบถ้วน คำนวณ Usage ตามรอบบิล
และคิดค่าใช้จ่ายด้วย Pricelist แบบ V4.6 โดยยัง Import ไฟล์ `.txt` ได้เป็นช่องทางสำรอง

V5.1 เพิ่มการลงทะเบียนบริษัทแบบโปร่งใสและระบบตรวจ Update: หน้าเริ่มต้นเก็บชื่อบริษัท วันที่เริ่มใช้ และ Version
ก่อนส่งเฉพาะข้อมูลขั้นต่ำไป Registration Service ผ่าน HTTPS; โปรแกรมตรวจ Signed Update Manifest เพื่อแจ้งและดาวน์โหลด
Release ที่ตรงกับ OS/architecture โดยไม่ส่ง Counter, Credential, User หรือข้อมูลเอกสารออกภายนอก

## Scope

### In

- First-run Setup 4 ขั้น เริ่มด้วยชื่อบริษัท วันที่เริ่มใช้และ Version ก่อนสแกน Konica Minolta 1–3 เครื่อง
- วันที่เริ่มใช้และ Version มาจากระบบแบบ read-only; Version V5.1 ใช้ package version `5.1.0`
- Registration Client สร้าง `installation_id`, เก็บคิว local และส่งข้อมูลแบบ idempotent/retry ผ่าน HTTPS
- Update Client ตรวจ Signed Manifest แบบ client pull และเริ่ม V5.1 ด้วย Notify + Download installer
- แสดง Model, IP, Serial, SNMP/Web status และ Username/Password รายเครื่อง; เพิ่มด้วย IP เองได้เมื่อสแกนไม่พบ
- ปุ่มทดสอบทุกเครื่องพร้อมกัน และดึง Model/Serial Number อัตโนมัติเมื่อเชื่อมต่อสำเร็จ
- Pricelist 4 หมวดแยกรายเครื่อง พร้อมวันที่เริ่มมีผลและประวัติราคา
- SNMP polling, Web Connection fallback, System Tray และ Auto-start เมื่อ Login
- หน้า Import แสดงสถานะกระดาษจาก SNMP: ยืนยัน “กระดาษหมด” เฉพาะระดับถาด `0` หรือ alert ที่ระบุชัด;
  หากรุ่นเครื่องไม่เปิดเผยข้อมูล ให้แสดงว่าอ่านสถานะไม่ได้โดยไม่เดา
- เก็บ Counter ดิบทุกประเภทตามที่อ่านได้ พร้อม Daily Cache และ Daily Rollup
- Overview แสดงสถานะวันนี้, Sync ล่าสุด, Usage/Cost ระหว่างวัน และสถานะ 1–3 เครื่อง;
  Report Center แยก Usage ตามช่วงวันที่, Management สำหรับภาพรวม และ Meter สำหรับ Counter ดิบ/History
- Sync Log แสดง SNMP OID, Web counter, RAM/Daily Cache, read counts, DB rollup, Rules
  และ Timeline Scheduler 1 วันตาม Settings จริง
- Cost category 5 แบบ: A3 Color, A3 B&W, A4 Color, A4 B&W และไม่คิดเงิน
- Import `.txt`, parser, billing, history และ report behavior ที่ยังจำเป็นจาก V4.6
- Import สำเนา Database V4.6 แบบ read-only เฉพาะ Meter/Usage History; Preview ก่อนเขียน, Backup V5,
  ตัด Account/IP/Credential/Price/Settings ออก, กันข้อมูลซ้ำด้วย row fingerprint และต่อ Timeline เข้ากับ V5 ตาม Slot
- local-first; ส่งออกเฉพาะข้อมูลนิติบุคคล/Installation/อุปกรณ์ใน Registration/Heartbeat ที่ประกาศใน Registration Data Notice
- Registration schema v2 อนุญาตเฉพาะ installation ID, company, first-started date, app version, platform/architecture,
  timestamps และ device inventory จาก IP scan ที่มี Serial No + Model + Selected + Local Slot; ส่งเครื่องที่พบทั้งหมดได้เกิน 3
  แต่เลือกเครื่องอ่าน Report ได้สูงสุด 3 และยังห้ามส่ง IP, MAC, hostname, Credential, Counter, User, Document หรือ Application log
- Web Edition แบบ LAN-only ให้ผู้ใช้อื่นเปิด Reports ผ่าน IP ของเครื่องหลักได้โดยไม่ติดตั้ง Desktop
- First setup เปิด Web service เป็นค่าเริ่มต้น, สร้าง Desktop/Web Shortcut ของ OS นั้น และ Settings ปิด/เปิดภายหลังได้

### Out

- SNMP write หรือ Web Connection endpoint ที่เปลี่ยนค่าเครื่อง
- การ Sync Meter/Billing/Counter/User/Document ขึ้น Cloud หรือ Public Internet
- Remote command ที่สั่งเครื่องลูกค้าให้ติดตั้ง Update โดยตรง; Update ต้องเป็น client pull จาก manifest ที่ตรวจลายเซ็น
- Forced update โดยไม่มี release approval, rollback plan และ native UAT
- Linux production credential vault จนกว่าจะมี native backend ที่ผ่าน UAT; Phase 1 รองรับ Windows/macOS ก่อน
- การแก้ source ของ V4.6 หรือ KOMI SNMP Profiler โดยตรง
- การกำหนดตำแหน่ง UI ของ Toner ในรอบ design นี้; เตรียมข้อมูลและ component boundary ไว้ก่อน

## Design

### Product workflow

1. เปิดครั้งแรกเข้าสู่ Setup Wizard 4 ขั้นตอนก่อน Main Window
2. ผู้ใช้กรอกชื่อบริษัท; ระบบแสดงวันที่เริ่มใช้และ Version `5.1.0` แบบ read-only พร้อมรายการข้อมูลที่จะส่ง
3. เมื่อผู้ใช้กดเข้า Step เครื่องพิมพ์ ระบบจึงเริ่มสแกน LAN และแสดงเฉพาะ Konica Minolta; ผู้ใช้เลือก 1–3 เครื่องและทดสอบ SNMP/Web Connection
4. ตั้ง Cost & Billing แบบราคาเดียวทุกเครื่อง, แยกรายเครื่อง หรือยืนยัน `ตั้งค่าราคาภายหลัง` ซึ่งบันทึก 0.00 แบบไม่คิดค่าใช้จ่าย
5. ตรวจ Company, Devices, Cost, Background และขอบเขตข้อมูล local/external แบบแยกส่วนพร้อมปุ่มแก้ไข ก่อนกด `บันทึกและเปิดโปรแกรม`
6. ระบบบันทึก local transaction ก่อน แล้วสร้าง `installation_id` และรายการ Registration ใน local outbox
7. Registration Worker ส่งข้อมูลผ่าน HTTPS แบบ background; Offline ใช้งานต่อได้และ retry โดยไม่สร้างรายการซ้ำ
8. เข้า Import พร้อมข้อมูลล่าสุด; Main Window ปรับ layout ตามจำนวนเครื่องที่เลือก
9. Scheduler อ่าน SNMP ทุก 5 นาทีและทำงานตาม polling/daily/billing rules เดิมโดยไม่ส่ง Meter ออกภายนอก
10. เมื่อเปิดโปรแกรมและไม่เกินหนึ่งครั้งต่อ 24 ชั่วโมง Update Client ตรวจ Signed Manifest ตาม OS/architecture/channel
11. หากมี Update ให้แสดง Version, Release Notes และปุ่ม Download; V5.1 ยังไม่ติดตั้งเงียบหรือเขียนทับตัวเอง
12. โปรแกรมส่ง Heartbeat เฉพาะสถานะขั้นต่ำและ device inventory เพื่อให้ Dashboard แสดง last seen, Version,
    จำนวน Konica ที่พบทั้งหมด และ Serial No + Model + Selected + Local Slot; Update result เป็น contract แยก

### First-run Setup

#### Step 1 — ข้อมูลองค์กรและการลงทะเบียน

- `ชื่อบริษัท` เป็นช่องบังคับ ตัดช่องว่างหัวท้าย และจำกัดความยาวเพื่อป้องกันข้อมูลผิดรูป
- `วันที่เริ่มเปิดใช้` ระบบกำหนดเมื่อเริ่ม Setup ครั้งแรกและแสดงแบบ read-only; เก็บทั้งเวลาจากเครื่อง
  (`client_first_started_at`) และเวลาที่ Server รับ (`server_registered_at`) เพื่อ Audit
- `Version ที่ใช้` อ่านจาก package version source เดียวและแสดง `5.1.0` แบบ read-only; ผู้ใช้ห้ามกรอกเอง
- แสดงข้อความว่าโปรแกรมจะส่งชื่อบริษัท วันที่เริ่มใช้ Version, OS/architecture และรุ่นเครื่องไปยังระบบของผู้พัฒนา
- แสดง Registration Data Notice, วัตถุประสงค์, ระยะเวลาเก็บ และช่องทางขอแก้ไข/ลบข้อมูล Installation ก่อนดำเนินการ
- `Customer/Activation Code` เป็น security gate ที่แนะนำ แต่ยังไม่บังคับจนกว่าจะล็อกกระบวนการออก Code กับทีมขาย

#### Step 2 — ค้นหาและเชื่อมต่อ

- ห้ามสแกนตอนเปิด Wizard; เริ่ม Network discovery หลังผู้ใช้กรอกบริษัทและกดเข้า Step เครื่องพิมพ์แล้วเท่านั้น
- แสดงตาราง `เลือก | ชื่อรุ่น | IP | Serial Number | สถานะ | User/Password`
- Multiple Checkbox เลือกได้ 1–3 เครื่อง พร้อมตัวนับ `เลือกแล้ว n/3`; มี `สแกนอีกครั้ง` และ `เพิ่มด้วย IP เอง`
- มี `Manual setup` สำหรับกรอก IP พร้อม Password ได้สูงสุด 3 เครื่อง โดย Username เป็น `administrator`
- แสดงการ์ด `นำเข้าประวัติ V4.6…` เฉพาะเมื่อตรวจพบ Database V4.6 ที่ยืนยัน schema แล้วหรือมีประวัตินำเข้าเดิม;
  เปิดหน้าต่างเลือก Database/Preview/Backup/Import โดยไม่เพิ่มขั้นบังคับใน Wizard;
  หน้าต่างเลื่อนได้และ footer คงอยู่ในจอขั้นต่ำ 720×520
- Username กำหนดเป็น `administrator`; ไม่มี Password เริ่มต้น ผู้ใช้ต้องกรอกค่าที่ผู้ดูแลเครื่องกำหนด
- Credential อยู่ใน macOS Keychain/Windows Credential Manager ผ่าน OS vault; SQLite เก็บเฉพาะ reference/metadata
- ทดสอบเครื่องที่เลือกพร้อมกันโดยไม่ block UI และแสดง SNMP/Web Connection แยกสถานะ
- เมื่อทุกเครื่องที่เลือกผ่านการทดสอบ เปิดหน้าต่างเล็กให้ตั้งชื่อเรียกเครื่อง โดยเสนอชื่อ Model แบบย่อ เช่น `KM bizhub C450i` แล้วจึงไปหน้าราคา
- SNMP ต้องคืน identity/status และ Web Connection ต้อง Login/อ่าน Device Meter สำเร็จทุกเครื่อง จึงเปิดปุ่มถัดไป

#### Step 3 — Cost & Billing

- ตัวเลือก `ใช้ราคาเดียวกันทุกเครื่อง` เป็นค่าเริ่มต้น, `ตั้งราคาแยกรายเครื่อง` หรือ `ตั้งค่าราคาภายหลัง`
- ถ้าราคาทุกช่องเป็น `0.00` ผู้ใช้ต้องเลือก `ตั้งค่าราคาภายหลัง` อย่างชัดเจน; ระบบจึงบันทึกสถานะไม่คิดค่าใช้จ่ายและให้ตั้งจริงภายหลังจาก Settings
- ราคา 4 หมวด: A3 Color, A3 B&W, A4 Color และ A4 B&W; ราคา Print/Copy ใช้ชุดเดียวกัน
- ค่าเริ่มต้นราคา `0.00` และทุกชุดราคาต้องมีวันที่เริ่มมีผลเพื่อรักษาประวัติย้อนหลัง
- ช่องกรอกราคาแสดงตัวเลขล้วน; หน่วย `บาท/หน้า` แสดงอยู่นอกช่องเพื่อให้แก้ตัวเลขได้สะดวก
- ส่วนลดกระดาษเสียเริ่มต้น `2%`
- วันสิ้นสุดรอบบิลเลือกจาก Dropdown วันที่ `1–31` (ค่าเริ่มต้น `31`); เดือนที่ไม่มีวันที่ 31 ใช้วันสุดท้ายของเดือนแทน
- Wizard ใช้ product hierarchy: page title, section title, form/control และ body แยกบทบาทชัด; กรอบใช้เฉพาะ control ที่แก้ไขได้
- Typography ในทุก Step ยึด token เดียวกัน: page title `F_2XL`, section title `F_XL`, form/control `F_LG`, body `F_MD`; ห้ามกำหนด pixel scale เฉพาะหน้า
- Step 3 จำกัดพื้นที่ฟอร์มสูงสุด 1,280 px และจำกัดช่องราคา/รอบบิลตามงานจริง เพื่อไม่ยืดเต็มหน้าจอจนอ่านความสัมพันธ์ยาก
- ตัวเลือก Shared/Per-device ใช้ปุ่ม Segment แบบ exclusive ไม่ใช้ Radio indicator ที่ลอยจากตำแหน่งข้อความ
- ราคาจัดเป็นตาราง `ขนาดกระดาษ | สี (Color) | ขาวดำ (B&W)` โดยหัวตารางและเส้นแบ่งบางช่วยให้เห็นความสัมพันธ์ของ A4/A3 ทันที

#### Step 4 — ตรวจสอบและเริ่มใช้งาน

- สรุป Company/Start date/Version, Devices/Connection, Cost/Billing และ local/external data boundary เป็นแถวแยกส่วนในหน้าเดียว
- แต่ละส่วนมีสถานะข้อความและปุ่ม `แก้ไข`; ข้อมูลเทคนิคที่ไม่จำเป็นต่อการตัดสินใจ เช่น IP/Serial ไม่แสดงในสรุปหลัก
- แสดง Pricelist A4/A3 สี/ขาวดำพร้อมหน่วยบาท/หน้า; Shared แสดงหนึ่งชุด และ Per-device แสดงชุดราคาตามชื่อเครื่อง
- ย้อนกลับไปแก้ชื่อบริษัทได้ก่อนบันทึกจริง และแยกข้อมูล Local ออกจากข้อมูลขั้นต่ำที่จะส่งออกให้ชัดเจน
- ปุ่มสุดท้าย `บันทึกและเริ่มใช้งาน` บันทึกข้อมูล local ก่อน แล้ว enqueue Registration; อินเทอร์เน็ตล่มต้องไม่ทำให้ Setup สูญหาย

#### Defaults หลัง Setup

- วันสิ้นสุดรอบบิล: วันที่ 31 หรือวันสุดท้ายของเดือน ใช้ร่วมกันทุกเครื่อง
- ส่วนลดกระดาษเสีย: 2% ใช้ร่วมกันทุกเครื่อง
- เวลางาน: 08:00–17:00
- Peak window: 07:30–08:30 และ 16:30–17:30
- ทุกค่าแก้ภายหลังได้จาก Settings
- Web service: เปิดอัตโนมัติพร้อม Desktop เป็นค่าเริ่มต้นหลัง Setup สำเร็จ
- Desktop สร้าง Shortcut สำหรับ `KOMI Report V5.1` และ `KOMI Report Web` ที่ชี้กลับมาหา package/source ของเครื่องนั้น

### Background and System Tray

- Auto-start เมื่อผู้ใช้ Login เข้า Windows/macOS และเปิดแบบซ่อนใน System Tray
- ผู้ใช้เปิดโปรแกรมเองด้วย shortcut/double-click ให้แสดง Main Window แบบ Maximized โดยยังคง title bar และปุ่มควบคุมหน้าต่างของระบบ
- กด `X` เป็นการซ่อนลง Tray; Scheduler ยังทำงานต่อ
- Tray menu: เปิด KOMI Report แบบ Maximized, อ่านค่าทันที, สถานะเครื่องแบบย่อ และ Exit
- Exit เท่านั้นที่หยุด Scheduler จริง
- Web service ใช้ lifecycle เดียวกับ Desktop: ค่า ON เริ่ม worker หลังเปิดโปรแกรม, ค่า OFF หยุด worker และ Exit หยุด process ลูก
- Shortcut เปิดจาก Desktop ของ macOS/Windows/Linux แต่ไม่ copy source; launcher ทุกตัวเรียกโค้ดกลางชุดเดียวกัน

### Polling state machine

#### Normal state

- อ่าน SNMP Total Meter ทุก 5 นาทีตลอดเวลา
- ถ้า Total ไม่เพิ่ม: อัปเดตสถานะและ `last checked` เท่านั้น ไม่เรียก Web Connection
- ถ้า Total เพิ่ม: ตั้งสถานะ `detail pending` แล้วเรียก Web Connection เมื่อพ้น throttle
- ช่วงปกติ Web Connection throttle 15 นาที; หาก Total เพิ่มหลายครั้งให้ดึงครั้งเดียวเมื่อครบช่วง
- ช่วง Peak 07:30–08:30 และ 16:30–17:30 ลด throttle เป็น 5 นาที
- ค่า SCAN และ Toner อาจค้างเมื่อ Total ไม่เพิ่ม เป็น behavior ที่ผู้ใช้ยอมรับแล้ว

#### SNMP unavailable

- เรียก Web Connection fallback สูงสุด 5 ครั้ง ห่างกันครั้งละ 5 นาที
- ถ้าครั้งใดสำเร็จ ให้บันทึกรายละเอียดและคืนสถานะ Online โดยระบุ source เป็น Web Connection
- ถ้าไม่สำเร็จครบ 5 ครั้ง ให้เป็น Offline แต่คงค่าที่อ่านสำเร็จล่าสุดและเวลาจริงไว้
- หลัง Offline ยัง probe SNMP ทุก 5 นาที; จำกัด Web probe ซ้ำเป็นหนึ่งครั้งต่อชั่วโมงหรือเมื่อผู้ใช้กดอ่านทันที
- ไม่มี popup; ใช้ status badge และข้อความ `ข้อมูลล่าสุดเมื่อ ...`

### Daily Cache and Daily Rollup

- Daily Cache ต้อง persistent และเขียนแบบ atomic แยก `device/date`; ห้ามเก็บเฉพาะ RAM
- Snapshot เป็น Counter สะสม จึงไม่บวก Snapshot รายชั่วโมงเข้าด้วยกัน
- Cache เก็บ opening, latest, counter segments, first/last success, source, sample count และ error summary
- Cache/Database เก็บ reconciliation profile, raw source path ของแต่ละ Counter, ผลตรวจ และ `billing_safe`
  เพื่อย้อนดูได้ว่าวันนั้นใช้กฎรุ่นใดและประกอบยอดจากค่าใด
- เมื่อ Total reset/ลดลง ให้ปิด segment เดิมและเริ่ม segment ใหม่ ห้าม clamp หรือตีเป็น Usage ติดลบ
- เมื่อขึ้นวันใหม่ เขียน `DailyMeterRecord` หนึ่งรายการต่อเครื่อง โดยเก็บ raw opening/closing/delta ทุก Counter
- หลัง commit Daily Record สำเร็จจึงลบ Cache ของวันนั้น
- ถ้า Printer หรือ KOMI Report ปิดก่อนสิ้นวัน ใช้ค่าที่สำเร็จล่าสุดเป็น closing value พร้อม `incomplete=true`
  และช่วงเวลาที่ข้อมูลขาด; ห้ามประมาณค่าที่หายไป
- เมื่อเปิดโปรแกรมใหม่ ให้ finalize Cache ค้างของวันก่อนก่อนเริ่มวันใหม่
- เป้าหมายฐานข้อมูล 3 เครื่องประมาณ 1,095 Daily Records ต่อปี ไม่นับ price/config history

### Report Center

- เส้นทาง Desktop ที่ผู้ใช้เห็นคือ `Overview | Users | Printers | Usage | V4.6 History`; `Usage` รวม Timeline V4.6 → V5 ตาม Slot
  ส่วนแท็บ V4.6 เก็บ Meter snapshot/Serial ของเครื่องในแต่ละช่วงเพื่อ Audit โดยไม่คำนวณราคา
- Slot แทนจุดติดตั้งหรือแผนก ไม่ใช่ตัวเครื่องพิมพ์: เช่น `Slot 1 = แผนกบัญชี`; เปลี่ยน Serial/Model/IP ใน Slot เดิมแล้ว
  ประวัติยังต่อกัน แต่ snapshot แรกของเครื่องใหม่เป็น Baseline และห้ามคำนวณ Meter delta ข้ามเครื่อง
- Overview, Users และ Printers มีตัวเลือกช่วงรายงานที่ซิงก์กันและควบคุม KPI, กราฟ และตารางในสามแท็บนั้น; เปิด Reports แล้วอ่านยอดล่าสุดแบบไม่ block UI
- Usage แสดงประวัติทั้งหมดจาก Daily/Monthly record โดยไม่ผูกกับตัวเลือกช่วงรายงาน: เลือก D/M/Y เพื่อรายวัน/รายเดือน/รายปี, มุมมองทุกเครื่องเป็นยอดรวม และมุมมองตามเครื่องเป็น matrix หนึ่งแถวต่อช่วงเวลาโดยใช้ชื่อเครื่องเป็นหัวกลุ่ม พร้อม A3 Color, A3 B&W, A4 Color, A4 B&W, Scan, รวม และค่าใช้จ่ายโดยประมาณ; คอลัมน์วัน/เดือน/ปีถูกตรึงไว้ทางซ้ายขณะเลื่อนดูเครื่องถัดไป
- ปุ่ม `Export to Excel` อยู่ข้างปุ่มรีเฟรชข้อมูลและบันทึก Workbook เดียว 7 ชีต: Summary, Selected Period, Users, Printers, Usage Daily, Usage Monthly และ Usage Yearly; ส่งออกข้อมูล Reports และ Usage history ทั้งหมดโดยไม่ส่ง Username/Password ของเครื่อง
- **Overview** แสดงผู้ใช้ที่มีการใช้งาน, เครื่องที่มีการใช้งาน, ยอดพิมพ์/ถ่ายเอกสาร, Scan, Timeline, Color/B&W, Top users และ Top printers
- **Users** แสดงยอดรวม/เฉลี่ย/ผู้ใช้สูงสุดและตาราง User/Account; กดแถวเพื่อกรองการกระจายตามเครื่อง โดย RAM เป็น View only และไม่ใช้คำนวณค่าใช้จ่าย
- **Printers** แสดงยอด/Color/B&W/Scan/Cost, Timeline ทุกเครื่อง, ตารางเครื่อง และ Meter detail; กดเครื่องเพื่อเปลี่ยนเฉพาะ Detail
  โดยกราฟยังเปรียบเทียบทุกเครื่องพร้อมกัน เพื่อไม่ทำให้ความหมายของภาพรวมเปลี่ยนระหว่าง Desktop กับ Web
- Web Reports ใช้ช่วง `วันที่เริ่มต้น` และ `วันที่สิ้นสุด` ชุดเดียวกับ Overview/Users/Printers, โหลด User ครบทุกหน้า,
  แยกสถานะ Report API ออกจากข้อมูลระบบ และมี `Usage`/`ข้อมูลระบบ` ตามหน้าที่จริง; Sync อยู่ภายในข้อมูลระบบแบบ Support detail
- หน้า User ปกติแสดงยอดรวมชุดเดียวและเวลาข้อมูลล่าสุด ไม่แสดง Ledger/Cache/Hold เป็นสองก้อน; Raw Meter และ Billing detail คงตรวจได้จาก Printer drill-down, Billing Audit และ Sync Log
- ไม่สร้าง Print job, Workflow, Connector, Department, Simplex/Duplex หรือ Cost ราย User เมื่อ source จริงไม่มี
- ข้อมูลที่ระบบยังไม่มีจริง เช่น Simplex/Duplex, pages per job หรือ Department จะไม่สร้าง placeholder หรือคำนวณเดา; ราคาย่อย A4/A3 ใน Management แสดง `—` จนกว่าจะมี cost breakdown ที่ยืนยันได้

### Billing rules

- Usage และ Billing ใช้ Counter ระดับเครื่องจาก Web Connection เท่านั้น; SNMP ไม่ใช่แหล่งคิดเงิน
- RAM dump ใช้ตรวจ User Authentication / Account Track เท่านั้น ไม่บวกเข้ากับ Device Meter และไม่ใช้คิดเงิน
- ข้อมูลดิบทุก Counter แสดงและจัดเก็บตามชื่อ/ค่าที่อ่านมา ไม่มีการเปลี่ยนชื่อข้อมูล
- แต่ละ Counter มี cost category สำหรับคำนวณเงินเท่านั้น:
  `A3 Color`, `A3 B&W`, `A4 Color`, `A4 B&W`, `ไม่คิดเงิน`
- ค่าเริ่มต้น: ขนาดไม่เกิน A4 → A4; ใหญ่กว่า A4 → A3; B&W/Grayscale → B&W;
  color mode อื่นรวม Single Color → Color
- SCAN, Toner และรายการที่ระบุขนาดไม่ได้เริ่มต้นเป็น `ไม่คิดเงิน`
- Device Meter นับจำนวนหน้าที่พิมพ์แล้ว รวมงาน Duplex; ห้ามคูณจำนวนหน้าเพิ่มซ้ำ
- Cost category ที่บันทึกกับ Daily Record ทำให้การแก้ในอนาคตไม่เปลี่ยนประวัติเก่า
- Pricelist เป็น effective-dated history แยกรายเครื่อง; Report ที่คร่อมวันเปลี่ยนราคาแบ่งคำนวณตามวัน
- ยอดสุทธิรวมทุกเครื่องใช้ส่วนลดกระดาษเสียร่วมกัน:
  `ค่าใช้จ่ายก่อนหัก × (100 − waste_pct) ÷ 100`

### การอ่านข้อมูลและ Settings — approved simplification 2026-08-21

- ผู้ใช้ทั่วไปมีเมนูหลักเพียง `ภาพรวม`, `อุปกรณ์`, `รายงาน`, `ตั้งค่า` และ `คู่มือ`; ยุบ `บันทึกการซิงก์` ออกจาก Sidebar
  เพื่อลดภาระการตัดสินใจ โดยไม่ลบ scheduler, event history, Daily Cache, reconciliation หรือ Billing Ledger.
- หน้า Settings เป็นศูนย์รวมแบบภาษางาน: เครื่องพิมพ์และราคา, รอบบิล, การอ่านข้อมูลอัตโนมัติ,
  โปรแกรม/Database และข้อมูลสำหรับเจ้าหน้าที่. รายละเอียด SNMP/Web/RAM/Cache/DB อยู่หลังปุ่ม `ข้อมูลสำหรับเจ้าหน้าที่`.
- ผู้ใช้เห็นสรุปเวลาอ่านข้อมูลและค่าที่แนะนำก่อน; ตาราง policy แบบละเอียดซ่อนเป็นตัวเลือกขั้นสูงและต้องไม่ล้นที่ 1024×768.
- ยกเลิก password gate สำหรับ Settings และเครื่องมือขั้นสูง. การเปลี่ยนแปลงที่เสี่ยงใช้คำเตือนถาวรและ confirmation
  ที่อธิบายผลกระทบแทนรหัสผ่าน; ห้ามซ่อนข้อมูลจำเป็นจนผู้ใช้แก้ปัญหาไม่ได้.
- Empty/error state ทุกหน้าต้องมี next action ที่ชัด เช่น `อ่านข้อมูลตอนนี้`, `ลองใหม่`, `เปิดการตั้งค่า`
  หรือ `ข้อมูลสำหรับเจ้าหน้าที่`; ไม่ให้ผู้ใช้จำเส้นทางเมนูเอง.
- Visual direction คือ Corporate operational: สุภาพ ชัด ใช้งานจริง ลดกรอบซ้อน/ศัพท์เทคนิค และคงข้อมูลละเอียดไว้สำหรับ Support.
- P1 acceptance ครอบคลุม 1024×768, Thai/English, keyboard focus/activation, accessible names และ Manual ที่ตรงกับ navigation ใหม่.

## Architecture

### Product surface

- **PyQt6 Desktop** ตาม architecture ที่อนุมัติเดิม
- **Python FastAPI LAN Server** แบบ read-only ใช้ report services และ SQLite ชุดเดียวกับ Desktop
- **Next.js Web UI** เป็น HTTPS listener ที่ `0.0.0.0:3000`; proxy `/api/*` ไป Python ที่ `127.0.0.1:8766`
- ผู้ใช้ใน LAN เปิด `https://IP-เครื่องหลัก:3000`; HTTP production listener ไม่มี และ Background collector มี process หลักเดียว
- per-install certificate มี SAN สำหรับ localhost/hostname/LAN IP, regenerate เมื่อ identity เปลี่ยน และรองรับ customer certificate;
  โปรแกรมไม่ติดตั้ง Root CA หรือแก้ OS trust store เงียบ ๆ
- Login แบบ shared Access Code มี rate limit/temporary lockout, expiring signed session, auth epoch/revocation และ Secure cookie;
  เจ้าของเปลี่ยนรหัสจาก Desktop Settings เท่านั้น. Runtime เก็บเฉพาะ `scrypt` hash และ keyed lockout subject ในไฟล์ `0600`
- Python API bind loopback เท่านั้น และยังห้าม forward port ออก Public Internet
- Main thread รับผิดชอบ UI เท่านั้น; device calls ทำใน bounded worker pool สูงสุด 3 เครื่อง
- System Tray และ scheduler มี lifecycle เดียวกับ application process

### V5.1 Registration and Update architecture

#### Options considered

1. **Desktop ต่อ Hosting database โดยตรง — ไม่เลือก:** ทำเร็วแต่ต้องฝัง credential และเปิด database ต่อ Public Internet;
   ควบคุมสิทธิ์, validation, retry และ audit ยาก
2. **Dedicated Registration/Update API — เลือก:** Desktop ส่ง HTTPS ไป modular API; API เขียน relational database,
   Admin Dashboard อยู่หลัง login และ Release file อยู่ object/file storage แยกจาก database
3. **Full cloud management/SaaS — ยังไม่เลือก:** รองรับหลายผลิตภัณฑ์และ remote fleet management แต่เกินความต้องการ V5.1,
   เพิ่มค่าใช้จ่ายและความเสี่ยงด้านข้อมูลโดยยังไม่มีเหตุผลธุรกิจ

โครงสร้างที่เลือกเป็น Small-business modular service และขยายภายหลังได้:

```text
Setup Wizard 4 steps
  -> local registration profile + durable outbox
  -> HTTPS Registration API
  -> Registration DB
  -> Private Admin Dashboard

KOMI Client
  -> GET signed update manifest
  -> download OS/architecture installer from file storage/CDN
  -> verify SHA-256 + signature
  -> user-approved installer (V5.1)
  -> report success/failure event
```

API boundary รุ่นแรก:

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/installations/register` | สร้าง/อัปเดต installation แบบ idempotent และคืน scoped installation token |
| `POST /api/v1/installations/heartbeat` | อัปเดต last seen, app version, platform และ privacy-bounded device inventory ตามรอบที่จำกัด |
| `GET /api/v1/updates/check` | คืน release ที่ตรงกับ version, OS, architecture, channel และ rollout cohort |
| `POST /api/v1/updates/events` | รับ downloaded/installed/failed โดยไม่รับ log หรือ customer data เกินจำเป็น |

Server data model ขั้นต่ำ:

- `installations`: installation ID, company, first started, registered at, current version, platform/architecture,
  last seen, registration/lifecycle status และ retention state
- `installation_heartbeats` และ `installation_status_history`: typed history ตาม retention โดยไม่เก็บ token/raw body
- `installation_device_snapshots`: discovered/selected count ต่อ heartbeat snapshot
- `installation_device_snapshot_items`: Serial No, model, selected และ Local Slot;
  ไม่เก็บ IP/MAC/hostname/Credential
- `releases`: version, channel, mandatory flag, rollout percentage, release notes, published/retired timestamps
- `release_artifacts`: release, OS/architecture, download URL, size, SHA-256, signature และ signing key ID
- `update_events`: installation, release, event type, occurred at และ sanitized error code

Failure/recovery rules:

- Local save สำเร็จก่อน network call; Offline ไม่บล็อกการใช้งานและ outbox retry ด้วย exponential backoff
- Register/heartbeat ใช้ idempotency key; Server ต้อง validate schema, จำกัดขนาด/rate และไม่เชื่อ payload เพื่อเลือกไฟล์โดยตรง
- Update V5.1 เป็น Optional Notify + Download; Emergency mandatory เป็น release decision แยกและต้องมี approval
- Running Desktop ห้ามเขียนทับตัวเอง; one-click update ต้องใช้ external updater หลัง code signing/native UAT เท่านั้น
- ก่อน Database migration ต้องสร้าง SQLite-consistent backup; failure ต้องหยุดก่อนเปิดใช้งานข้อมูลและมี rollback package
- Admin Dashboard ใช้ MFA/RBAC/Audit log; publish release แยกสิทธิ์จากผู้ดูข้อมูล installation

### Modules

| Module | Responsibility |
|---|---|
| `DeviceConfigRepository` | เครื่อง 1–3 เครื่อง, credential, enabled state, Model/Serial |
| `SetupWizardV5` | Company/Start/Version → Devices/Test All → Pricelist → Review/Save โดยรักษา Slot เดิม |
| `RegistrationRepository` | เก็บ company profile, installation ID, server token, status และ timestamps ใน local database |
| `RegistrationOutbox` | คิว register/heartbeat/update event แบบ durable, idempotent และ retryable |
| `RegistrationClient` | ส่ง schema v2 ผ่าน HTTPS โดย allow-list Serial No + Model + Selected + Local Slot จากผล IP scan ทั้งหมด และห้าม serialize IP/MAC/hostname/Credential/Counter/User/Document/Log |
| `UpdateClient` | ตรวจ manifest, version/channel/OS/architecture, ดาวน์โหลดและ verify artifact ก่อนส่งต่อ installer |
| `LegacyHistoryImportDialog` | เลือกสำเนา V4.6 → Preview mapping ตาม Slot → Backup → Import Usage History เท่านั้น |
| `legacy_history_import.py` | เปิด source read-only, sanitize aggregate usage, fingerprint duplicate, atomic import และสร้าง Slot-based intervals โดยไม่ข้าม replacement boundary |
| `WebServiceManager` | start/stop/status FastAPI + Next.js worker ตามค่า Settings และหยุด process ลูกพร้อม Desktop |
| `desktop_shortcuts.py` | สร้าง `.app`, `.lnk` หรือ `.desktop` ที่ชี้ canonical launcher โดยไม่ copy source |
| `DevicePollingCoordinator` | SNMP 5 นาที, throttle, peak windows, retry/backoff |
| `LiveMeterService` | SNMP/Web Connection read-only และ canonical conversion |
| `WebCounterReconciliationService` | ตรวจสมการผลรวมภายใน Device Meter และสร้าง Needs Review พร้อมส่วนต่าง |
| `DailyCacheStore` | atomic per-device/day working state และ crash recovery |
| `DailyRollupService` | counter segments, daily delta, incomplete-day finalization |
| `SubjectDailyCacheStore` | atomic User/Account Total Counter cache และ append-only daily subject records |
| `PricingRepository` | effective-dated Pricelist และ cost category history |
| `BillingService` | current period, four price groups และ waste discount |
| `OverviewPage` | adaptive 1–3 device layout, usage/latest toggle, statuses |
| `PipelineLogStore` | bounded RAM trace สำหรับ SNMP, Web, Policy, RAM และ DB events |
| `PagePipelineLog` | Live Pipeline, Daily Cache/Database status และ Rules inspector |
| `SettingsPage` | devices, schedule, pinned counters, rates, billing and waste |
| `web_api.py` | read-only API สำหรับ Health, Devices, Reports, Sync Status และ Settings พร้อม typed schema/redaction |
| `web/` | Next.js responsive Reports UI และ API proxy |

### Web Edition LAN Release

- Reports แสดง Overview, Devices, Usage/Cost, User pivot, Trends, Sync Timeline และ Settings แบบ read-only
- Web/API ใช้ `load_usage_history()` และ `load_subject_history()` โดยตรง จึงไม่มีสูตร Billing ซ้ำ
- วันที่มี `billing_safe=false` ถูกเก็บเป็น audit evidence แต่พัก Usage/Cost ออกจาก Billing และแสดง `held_days`
- Device payload ไม่ส่ง Username/Password, ตัด credential ออกจาก error detail และไม่มี endpoint สำหรับแก้ Settings หรือสั่ง Printer
- Next.js บังคับ Login, เก็บ session ใน HttpOnly cookie และเป็นทางเข้า API เดียวจาก LAN
- ปุ่ม `รีเฟรชข้อมูล` อ่านฐานข้อมูลล่าสุดเท่านั้น ไม่ทำหน้าที่ Sync เครื่องพิมพ์
- Desktop และ Mobile 390×844 ผ่าน visual QA; Mobile ใช้ bottom navigation 7 เมนูและเผื่อพื้นที่ท้ายหน้า 124 px
- Launcher `Open KOMI Report Web.command` สร้าง/แสดง Access Code, rebuild เมื่อ source ใหม่กว่า build และเปิด API/Web production server

### Data flow

```text
SNMP status every 5 min
  ├─ total unchanged ──> status only
  ├─ total increased ──> throttle 15 min / peak 5 min ──> Web Connection
  └─ unavailable ──────> Web fallback 5 attempts × 5 min
                                                │
                                                ▼
                                    canonical raw counters
                                                │
                                     atomic Daily Cache
                                                │ day rollover
                                                ▼
                                     DailyMeterRecord + raw deltas
                                                │
                                  Usage view / Billing / History
```

### Recovery and invariants

- Network calls are read-only, timeout-bounded and never run on the UI thread
- One active poll per device; overlapping runs are coalesced
- Daily Record unique key `(device_id, local_date)` prevents duplicate rollup
- Cache deletion occurs only after database transaction succeeds
- Counter decrease creates a reset segment and visible warning
- Web Counter ที่ตรวจผลรวมแล้วไม่ตรงกันต้องแสดง `Needs Review` พร้อมค่าซ้าย/ขวาและส่วนต่างใน Import, Connection และ Log
- Reconciliation เปรียบเทียบเฉพาะ Web Connection Device Meter; ห้ามนำ SNMP หรือ RAM User/Account มารวมเทียบ
- Last known good values are never overwritten by a failed read
- Import `.txt` remains independent if live connectors are unavailable
- Slot เป็น logical identity ของประวัติ; Serial/Model/IP เป็น physical identity สำหรับ Audit และสร้าง Baseline ใหม่เมื่อเปลี่ยนเครื่อง

## คำที่ใช้ร่วมกัน

- **Registration:** การแจ้งว่าบริษัทใดเริ่มใช้ KOMI Report installation นี้ ไม่ใช่การส่ง Meter/Billing ขึ้น Cloud
- **Heartbeat:** ข้อความสถานะขนาดเล็กตามรอบเพื่ออัปเดต `last seen` และ Version; ไม่ใช่การติดตามทุกกิจกรรม
- **Update:** Client ตรวจ release ที่ Server ประกาศแล้วจึงดาวน์โหลด; ไม่ใช่ Server remote-control เครื่องลูกค้า
- **วันที่เริ่มเปิดใช้:** เวลาที่ Setup เริ่มครั้งแรกจากเครื่องลูกค้า; เก็บแยกจากเวลาที่ Server รับ Registration
- **Slot:** จุดติดตั้งหรือแผนกที่ต้องการติดตามต่อเนื่อง เช่น `Slot 1 = แผนกบัญชี`; ไม่ได้หมายถึง Serial ของเครื่อง
- **เปลี่ยนเครื่อง:** เปลี่ยน Serial/Model/IP ภายใน Slot เดิม ประวัติยังอยู่กลุ่มเดิม แต่เริ่ม Meter Baseline ใหม่และไม่หาผลต่างข้ามเครื่อง
- **V4.6 Historical:** Usage ที่คำนวณจาก Meter snapshot เดิมตามกติกา V4.6; ไม่มีค่าใช้จ่ายย้อนหลังและไม่เขียนเข้า Billing Ledger

## Progress: 72%

V5.0 foundation และ Phase 4 Technical RC automation/preflight เสร็จแล้ว; Registration production, native Windows x64,
signing และ controlled real-device acceptance ยังเป็น blocking gates ส่วน Update ถูก deferred ออกจาก Release นี้โดยชัดเจน.

### Phase 1 — Discovery and revised design ✅

- [x] ตรวจ source/tests ของ V4.6 และยืนยัน `.txt` import workflow
- [x] ตรวจ connector/schema ของ KOMI SNMP Profiler
- [x] เลือก Modular Python Desktop เป็น product surface
- [x] เก็บ requirement First-run สำหรับเครื่อง 1–3 เครื่อง
- [x] เก็บ requirement Scheduler, System Tray และ Daily Rollup
- [x] เก็บ requirement Usage, Pricelist และ Billing rules

### Phase 2 — Reusable foundation ✅

- [x] สร้าง V5 codebase จาก PyQt6 shell ของ V4.6
- [x] ย้าย live-meter services และ canonical schema จาก Profiler
- [x] คง Import, History, billing และ report foundation
- [x] รวม regression tests ของ V4.6 และ Profiler
- [x] สร้าง development source package baseline

### Phase 3 — Revised unified application ✅

- [x] เปลี่ยน Parser-first wizard เป็น SetupWizardV5
- [x] สร้าง DeviceConfigRepository และ Test All แบบ concurrent
- [x] สร้าง adaptive Overview สำหรับ 1–3 เครื่อง
- [x] สร้าง polling state machine, System Tray และ OS Auto-start
- [x] สร้าง persistent Daily Cache และ Daily Rollup
- [x] สร้าง effective-dated Pricelist และ cost-category history
- [x] สร้าง current-period Usage, latest Counter และ All Counters view
- [x] รวม `.txt` import กับ Daily/Billing report โดยไม่ทำ regression
- [x] เพิ่มหน้า Connection Inspector สำหรับดู SNMP Total, Web counter และ RAM dump แยก 3 คอลัมน์
- [x] คืนหน้า Overview ให้ใช้ `PageOverview` และ layout เดิมจาก V4.6 เป็นโครงรายงานหลัก
- [x] ปรับหน้า Import เป็น 1–3 คอลัมน์ พร้อมตาราง Scroll แสดง Web ทุก Counter และ User/Account Track ทุก field จาก RAM
- [x] ปรับ History > ค่ามิเตอร์ปัจจุบันให้รองรับ 1–3 เครื่องและอ่าน Current/Opening/Delta จาก V5 Daily Cache
- [x] ปรับ History > ย้อนหลังรายเดือนให้รวม Usage/Cost ตามรอบบิลจาก V5 Daily Records และ Cache วันนี้
- [x] เปลี่ยน History Tab 1 เป็นค่ามิเตอร์สะสม และ Tab 2 เป็นประวัติย้อนหลังแบบรายวัน/สัปดาห์/เดือน/ไตรมาส/ปีตามรอบบิล
- [x] ทำหัวตาราง History 2 ชั้น: รอบบิล | เครื่องละ Color/B&W/Cost | รวมทุกเครื่อง
- [x] เพิ่ม Web Counter Reconciliation Warning ใน Import, Connection และ Pipeline Log
- [x] เปลี่ยน History > ผู้ใช้งานเป็น V5 append-only Total Counter history ที่ไม่ผูก Billing
- [x] เปลี่ยน History เป็น Reports workspace: ภาพรวม / รายเครื่อง / ยอดใช้งานและค่าใช้จ่าย / รายผู้ใช้ / แนวโน้ม
- [x] สร้าง Reports Overview ตามรอบบิล พร้อม KPI, Top printers, Top users และสถานะข้อมูลไม่สมบูรณ์
- [x] P1: เปลี่ยน Trends ให้ใช้ `load_usage_history()` / `load_subject_history()` จาก V5 Ledger contract เท่านั้น
- [x] P1: ใช้ `(period_start, period_end)` เป็น report-period identity ใน Desktop และ Web Reports
- [x] P1: ให้ Posted Ledger/frozen snapshot เป็น canonical report driver; Daily evidence ใช้เฉพาะรายการที่ยังไม่เข้า Ledger
- [x] P1: แก้ empty/error state, Trend label overlap และ accessibility state/contrast
- [x] P2: ใช้ segmented Daily Cache delta เมื่อ Total Meter reset และปรับ Reports ให้ reflow ที่ viewport แคบ
- [x] แสดง Daily Cache วันนี้เป็นยอดระหว่างวันและค่าใช้จ่ายประมาณการ โดยไม่เขียนปะปนกับ Billing Ledger
- [x] ปรับ Overview เป็นหน้าปฏิบัติงานวันนี้ พร้อม KPI, สถานะรายเครื่อง, Sync ล่าสุด และทางลัดไป Reports/Sync Log
- [x] ปรับ Reports > แนวโน้มเป็นกราฟตามรอบบิล แทน Pie chart พร้อมแยก Posted Ledger และ Daily Cache ระหว่างวัน
- [x] เปลี่ยน Task Schedule จาก Peak ที่คำนวณตายตัว เป็นช่วงเวลา Web ที่เพิ่ม/ลบ/ตั้งชื่อ/กำหนด throttle ได้เอง
- [x] เปลี่ยน Desktop Reports เป็น Cloud-style 4 หน้า: Overview / Users / Printers / Usage พร้อมช่วงวันที่เริ่มต้น–สิ้นสุดที่ใช้ร่วมกันทุกหน้า
- [x] เพิ่ม Desktop Reports > Usage: ประวัติ D/M/Y ทุกช่วง, มุมมองทุกเครื่อง และ matrix ตามเครื่องที่ไม่ซ้ำแถววัน/เดือน พร้อมตรึงคอลัมน์เวลาเมื่อเลื่อนแนวนอน
- [x] เพิ่ม Cloud Reports > Export to Excel: Workbook 7 ชีตสำหรับข้อมูล Reports และ Usage history โดยตัด credential ออก
- [x] เพิ่ม Setup Wizard > Import Database V4.6 แบบ Usage History-only พร้อม Preview, Backup และ duplicate guard
- [x] เก็บ V4.6 History ไว้ใน Usage/Export สำหรับ Audit แต่ซ่อนแท็บแยกจาก customer-facing Reports เพื่อลดเมนูซ้ำ
- [x] รวม V4.6 → V5 ใน Usage Timeline ตาม Slot, รักษา Slot เมื่อเปลี่ยนเครื่อง และไม่คำนวณ Meter ข้าม Serial/Baseline
- [x] เปิด Web service เป็นค่าเริ่มต้นหลัง First setup พร้อม Settings toggle/status/Local-LAN URL
- [x] สร้าง Desktop/Web Shortcut สำหรับ macOS, Windows และ Linux โดยชี้ canonical source เดียว
- [x] เปลี่ยน Desktop/Web/package icon เป็นโลโก้ printer-reporting ที่ผู้ใช้ให้; Sidebar ใช้ icon compact 54 px + `KOMI REPORT`

### Phase 4 — Verification and release

- [x] Baseline regression suite 71 tests ผ่านก่อน redesign
- [x] Baseline PyQt render และ source package ผ่าน
- [x] Unit tests สำหรับ scheduler clock, throttle, retry และ offline recovery
- [x] Atomic cache/restart tests สำหรับ Daily Cache และ idempotent rollup
- [x] Billing tests สำหรับ price history, cost category และ 2% discount
- [x] Reconciliation tests สำหรับผลรวมตรงกัน, ไม่ตรงกัน และการกัน SNMP/RAM ออกจาก Billing
- [x] User/Account tests สำหรับ multi-snapshot delta, reset, baseline, append-only DB และ Coverage warning
- [x] Visual QA ที่ device count 1, 2 และ 3
- [x] Live UAT กับเครื่องจริงอย่างน้อยหนึ่งเครื่อง
- [ ] Background/Tray/Auto-start UAT บน target OS

### Phase 5 — Setup Wizard redesign

- [x] สรุป workflow 3 ขั้นตอนและ business rules กับ Bom
- [x] ทำ Interactive Mockup: Auto scan, Multiple Checkbox, required connection, Cost/Billing, Review และ First Sync
- [ ] Bom ตรวจหน้าตาและ interaction ใน `PROJECT.html`
- [ ] Implement Network discovery และ SetupWizardV5 ใหม่ใน PyQt6
- [ ] ทดสอบ discovery/credential/first sync กับ C450i และ C750i จริง

### Phase 6 — Production hardening (non-security; approved 2026-08-05)

- [x] รวม typed runtime configuration, dependency authority และ structured logging
- [x] สร้าง repository/application boundary และ versioned migration path โดยคง Billing Ledger invariant
- [x] แยก PyQt module แบบ compatibility-first ชุดแรก (common dialogs); หน้า Reports UI อยู่ใน phase หลังตาม scope
- [x] ปรับ API lifecycle, pagination/limit, worker shutdown signal และ observability ชุดแรก
- [x] เพิ่ม cross-platform support matrix และ release runbook
- [ ] แยก PyQt page modules ที่เหลือ, ลด repository-wide Ruff baseline และเพิ่ม CI release gate
- [ ] สร้าง/ทดสอบ package Linux และทำ UAT Windows/macOS/Linux บน target จริง
- [ ] รัน regression, package/static checks และบันทึก UAT ที่ยังต้องใช้ target OS/เครื่องจริง

### Phase 7 — V5.1 design and canonical source migration

- [x] เลือก Setup 4 ขั้นและกำหนด Company/Start date/Version โดยวันที่และ Version เป็น read-only
- [x] เลือก Dedicated Registration/Update API แยกจาก LAN Web Edition และ Hosting database
- [x] เลือก Update แบบ client pull, Signed Manifest และเริ่มด้วย Optional Notify + Download
- [x] คัดลอก source จาก OneDrive ไป `~/Projects/dev/komi-report-v5` และเก็บ rollback symlink/ต้นฉบับเดิม
- [x] เปลี่ยน development/package version เป็น `5.1` / `5.1.0`
- [x] ปรับ Registration API handoff เป็น target schema v2 สำหรับ Dashboard/Heartbeat history และ privacy-bounded device discovery/selection
- [ ] ยืนยัน Hosting stack, Domain/API URL, Customer/Activation Code และผู้ดูแลระบบ
- [ ] ให้ Product owner/Hosting Security อนุมัติ Registration Data Notice, Source-IP log policy, retention และ deletion workflow

### Phase 8 — V5.1 implementation and release

- [x] เพิ่ม Company profile และ Setup Wizard 4 ขั้นสำหรับ install ใหม่และ one-time onboarding สำหรับผู้ใช้เดิม
- [x] เปลี่ยน IP ตัวอย่างเป็น `192.168.1.1`–`192.168.1.255` และเพิ่ม Virtual Printer Setup Lab ที่ตอบ SNMP/Web จริง
- [x] ทำ Setup Lab แบบ Mac-first ที่ใช้พอร์ต local ไม่ต้องขอ Admin แต่ส่งเข้า discovery/test worker ชุดเดียวกับ Windows
- [x] บังคับ Light Theme ทั้ง 4 Step, ยืด Company fields, ล็อกสี Device table/Price scroll และกัน Header ชนกันใน macOS Dark Mode/Windows
- [x] เพิ่ม Registration Envelope แบบ allow-list และบันทึกซอง Pending ในเครื่องหลัง Setup โดยยังไม่ส่งออกก่อนมี API/Registration Data Notice
- [x] ปรับ local schema v2 ให้เก็บผล IP scan ทุกเครื่องด้วย Serial No/Model และทำเครื่องหมาย selected/slot สูงสุด 3 โดยไม่เปลี่ยน UI
- [ ] เพิ่ม local Registration repository/outbox พร้อม offline retry, idempotency และสถานะ Registered/Pending/Failed
- [ ] สร้าง HTTPS Registration/Heartbeat API และ Private Admin Dashboard พร้อม MFA/RBAC/Audit log
- [ ] เพิ่ม Update check, signed manifest, OS/architecture/channel mapping, release notes และ verified download
- [x] เพิ่ม test ที่ยืนยันว่า payload ส่ง Serial No ตาม contract แต่ไม่มี IP/MAC/Credential/Counter/User/Document/Log
- [ ] ทดสอบ clean install และ V5.0 → V5.1 upgrade/backup/restore บน Windows/macOS/Linux ที่รองรับจริง
- [ ] ทำ pilot rollout ก่อน stable และบันทึก install/update success/failure จากระบบจริง

### Phase 9 — Simplified Settings and P1 UX hardening

- [x] ยุบ `บันทึกการซิงก์` ออกจาก Sidebar และ route ทางลัดเดิมเข้า `ตั้งค่า > ข้อมูลสำหรับเจ้าหน้าที่`
- [x] รื้อ Settings เป็นหน้าเดียวสำหรับผู้ใช้ทั่วไป พร้อมซ่อนตารางเวลาแบบละเอียดจนกว่าจะขอเปิด
- [x] ยกเลิก password gate และใช้คำเตือน/confirmation เฉพาะการเปลี่ยนแปลงที่มีผลสูง
- [x] แก้ layout และตารางหลักให้ใช้งานได้ที่ 1024×768 โดยไม่ตัด action สำคัญ
- [x] เพิ่ม recovery action, English coverage และ keyboard/accessibility สำหรับหน้าที่เปลี่ยน
- [x] ปรับ Manual และ visual regression ให้ตรง navigation/Settings ใหม่
- [x] ผ่าน focused regression, full regression, render matrix และ native macOS smoke

### Phase 10 — Web UI parity and customer-ready flow

- [x] ใช้ช่วงวันที่เริ่มต้น/สิ้นสุดเดียวกันใน Overview, Users และ Printers โดยไม่เกิด latest-period drift
- [x] โหลด User/History ครบทุกหน้าและให้ API ย่อยล้มเหลวได้โดยไม่ทำ Reports ทั้งหน้ากลายเป็น Offline
- [x] ให้กราฟ Printers แสดงทุกเครื่องเสมอ และการเลือกแถวเปลี่ยนเฉพาะ Meter detail
- [x] เพิ่ม Usage, ย้าย Sync เข้า read-only `ข้อมูลระบบ` และคง Desktop sidebar โดยไม่เพิ่ม Web tab
- [x] ปรับ Thai/English, 1024 px, Mobile, keyboard/accessibility และ error recovery
- [x] ผ่าน TypeScript/build, API regression และ Browser QA แบบ authenticated ที่ Desktop/Mobile

### Phase 11 — Production Phase 0 release safety baseline

- [x] Inventory Git/release builders/version/data โดยไม่แตะข้อมูลจริง
- [x] Block database, CSV, log, environment, credential, output/export และ QA evidence จาก Git/Release
- [x] เพิ่ม shared fail-closed safety gate พร้อม negative-case proof
- [x] ทำ runtime/build metadata ให้ตรง `5.1.0` และ manifest มี commit/time/SHA256/artifact identity
- [x] Full source regression `399 passed`, scoped Ruff, Web typecheck และ production build ผ่าน
- [x] Pre-commit candidate scan 223 files ได้ 0 secret/data findings; export จริง 2 จุดยังอยู่และถูก ignore
- [x] สร้าง baseline commit `85e308f`, tag `v5.1.0-phase0` และยืนยัน clean-checkout artifact contents 204 files / forbidden entries 0
- [x] สร้าง/push private GitHub remote `binlabongbom/komi-report-v5`; main/tag read-back เป็น private และสิทธิ์ ADMIN

### Phase 12 — Production Phase 1 Security Baseline

- [x] สร้าง task workbook/branch และล็อก architecture/Definition of Done โดยไม่ทำให้ Phase 0 gate อ่อนลง
- [x] ปิด npm/Python production Critical/High พร้อม audit evidence จาก environment จริง
- [x] บังคับ LAN HTTPS, per-install/customer certificate lifecycle และ direct API loopback-only พร้อม live handshake
- [x] เพิ่ม Web login throttling/lockout/session expiry/revocation และ secure cookie พร้อม automated/live checks
- [x] ย้าย printer credential ไป OS vault ผ่าน rollback-safe migration โดยไม่เหลือ plaintext ใน SQLite/log
- [x] บังคับ trusted/pinned printer TLS และลบ hard-coded/default credential อย่าง backward-compatible
- [x] ผ่าน security/full regression, scans, Web build/typecheck, release safety, merge main และ push private origin

## Problem / Blocker

- Registration API artefact รอบ `komi 1.zip` เป็น `PARTIAL / ยังไม่ผ่าน`: v1 register/heartbeat จริงผ่านแล้ว
  แต่ Base URL ใน OpenAPI redirect จาก non-www ไป www, ไม่มี API source/commit/tag ในชุดส่งมอบ และยังไม่มี
  v2 device inventory/Dashboard/rollback end-to-end evidence ครบชุด
- OpenAPI/API live schema v2 ยังบังคับ random `device_instance_id` และ reject Serial No; ต้องให้ทีม API เปลี่ยนเป็น
  `serial_number` พร้อม migration/index/retention/access control ก่อน Desktop ส่ง revised envelope จริง
- Staging ใช้ host เดียวกับ production และ database instance เดียวกับ DMS (แม้แยก table); ต้องแยก environment
  หรือให้ Hosting Security อนุมัติพร้อมมาตรการ isolation, retention และ deletion ที่ตรวจสอบได้
- Registration Data Notice, Source-IP log policy, retention/deletion และสิทธิ์เข้าถึง Dashboard ยังต้องผ่าน Product owner/Hosting Security
- One-click/forced update ยังไม่อนุมัติ; V5.1 จำกัดที่ Notify + Download จนผ่าน code signing และ native upgrade UAT
- Canonical source ใหม่อยู่ใน `~/Projects/dev/komi-report-v5`; ต้นฉบับ OneDrive ยังเก็บเป็น rollback archive ห้ามแก้สองที่พร้อมกัน
- Append-only Billing Ledger และ immutable evidence พร้อมแล้ว; รายงานย้อนหลังใช้เฉพาะยอดที่ยืนยันและห้ามคำนวณทับ
- Daily Cache วันนี้คงอยู่หลังปิดโปรแกรม และ Reports แสดงเป็นยอด `ระหว่างวัน` พร้อมเครื่องหมาย `~`
  แยกจากยอดยืนยันใน Ledger อย่างชัดเจน
- Cache ที่ reconciliation ไม่ปลอดภัยยังถูก Hold; ถ้าไม่พบ Pricelist ให้แสดงจำนวนหน้าได้ แต่ค่าใช้จ่ายเป็น `—`
- Current status: source, full regression, Next production build, UI matrix และ Desktop offscreen กับ DB/Cache จริงผ่าน
- Needed next: Bom ตรวจรับหน้าจอ Desktop runtime; Production billing ยังคงต้องผ่าน controlled print/billing UAT

## Live UAT — 2026-07-20

- DMS C450i: ก่อนทดสอบ SNMP/Web Total `2,340`; หลังพิมพ์ A4 Color 1 หน้าเป็น `2,341`
- Sales C750i: SNMP/Web Total `440,954`, Web 96 device counters, Reconciliation 16/16 ผ่าน
- Sales Daily Cache: opening `440,749` → latest `440,954` → Usage `205`;
  A4 Color `161` + A4 B&W `44` = Device Total `205`
- DMS User Auth: ก่อนพิมพ์ `user:1` Total `1`; หลังพิมพ์ด้วย User `DMS` เป็น Total `2`, Usage `1`
- Web Toner UAT: Administrator GET `api/AppReqGetCustomData/_111_000_CSM000` คืน Consumable/Toner โดยตรง;
  DMS C/Y/M/K `81/81/80/63` และ Sales `7/44/27/0` ตรงกับ SNMP ครบ 8/8 ค่า
- Web Toner status: DMS `Ready/Enough`; Sales Y/M `NearEmpty`, C `NearLifeEnd`, K `Empty`;
  endpoint ไม่คืน Toner เมื่อยังไม่ Login จึงต้องใช้ Administrator session และ logout ทุกครั้ง
- Identity fix: `AppReqGetAuthCounter` คืนเฉพาะ `AuthNo=1`; ระบบอ่าน RAM Meter export แบบ UTF-16/TAB
  เพื่อ map ชื่อที่ลูกค้าเห็น `DMS` กลับเข้ากับ subject ID โดยไม่ใช้ export คิด Billing
- Sales User/Auth: Web Connection แจ้งว่าเปิด User Authentication แต่ firmware schema นี้ยังอ่าน subject rows ไม่ได้
- Controlled proof: งานจริง 1 หน้าเพิ่ม Device Total `+1`, A4 Color (Print) `+1`, User DMS `+1` และ UI แสดง
  `DMS | 1 | — | 1` ถูกต้อง

## History Tab Audit

### Tab 3 — ผู้ใช้งาน: PASS · LIVE DMS

- Source: Background Web read แยก exact `counter.user.total.total` / `counter.track.total.total` เข้าสู่
  `SubjectDailyCacheStore`; ไม่ใช้ legacy `readings` ใน V5 User tab
- Storage: ระหว่างวันเก็บ atomic opening/latest/delta/reset และข้ามวันเขียน `daily_subject_records`
  หนึ่ง append-only record ต่อ `(device, date, subject_type, subject_id)`
- Monthly aggregation: รวม incremental delta ทุก snapshot; fixture `100 → 110 → 125` ได้ `25` ถูกต้อง
- Billing boundary: UI เหลือ User/Account, Type, Device, Total Counter, Usage รอบบิล, Status และ Latest;
  ไม่มีราคา, A3/A4, Color/B&W หรือ cost calculation
- Reset: `125 → 5` เก็บ usage รวม `30`, reset event และแสดง `Needs Review` ทั้งแถวและ banner
- Identity: ใช้ `(device_slot, subject_type, subject_id)`; ถ้าไม่มี subject ID ใช้ name fallback พร้อม warning
- Coverage: User/Account ต่ำกว่า Device Meter แสดง Public/Untracked เป็นข้อมูลปกติ; ถ้าสูงกว่าจึงเป็น hard mismatch
- Evidence: schema v7, 116 tests, scoped Ruff/compileall และ offscreen visual QA ผ่าน
- Layout: หนึ่งแถวต่อ `(subject_type, subject_id)` และหนึ่งคอลัมน์ต่อเครื่องที่เปิดใช้งาน 1–3 เครื่อง;
  cell แสดง Usage รอบบิล, คอลัมน์ขวาสุดรวมทุกเครื่อง และ Tooltip เก็บ Total Counter/สถานะ/เวลาล่าสุด
- Live: DMS แสดงชื่อ `DMS`, Usage `1`, Sales `—`, รวมทุกเครื่อง `1` หลัง controlled print;
  Sales ยังไม่มี subject rows จาก firmware

## Decisions and Changes

- 2026-08-22 — Bom ยืนยัน Registration payload เป็นข้อมูลนิติบุคคล/Installation/อุปกรณ์และ API ที่เก็บบน
  `https://www.dmskm.com/` ไม่จัดเก็บ Source IP. เปลี่ยนข้อความผู้ใช้จาก Privacy Notice/Consent เป็น Registration
  Data Notice/Acknowledgement ทั้งไทยและอังกฤษ; หาก configuration เปลี่ยนให้เก็บข้อมูลบุคคลจึงค่อยเปิด privacy assessment แยก.
- 2026-08-22 — เริ่ม Production Phase 1 Security Baseline ใน task workbook
  `work/01a02733-fd41-78c3-aa89-e735a595a458/PROJECT.md` บน branch `codex/phase-1-security-baseline`.
  คง local-first modular monolith; FastAPI loopback-only, LAN Web ต้อง HTTPS, certificate ต่อ installation/customer-provided,
  credential ไป OS vault และ printer TLS verified/pinned โดย default. ห้ามแตะ Meter/Billing/Registration/Update และห้ามอ่อน Phase 0 gate.
- 2026-08-21 — Bom เปลี่ยน schema v2 ให้ใช้ `serial_number` แทน random device UUID และให้ Registration ส่ง
  Konica Minolta ทุกเครื่องที่พบจาก IP scan ตอนลงทะเบียน พร้อม Model/Selected/Local Slot. จำนวน discovered ไม่จำกัดที่ 3
  แต่ Desktop ยังคงเลือกอ่าน Report ได้สูงสุด 3 เครื่อง. เป็นข้อมูลหลังบ้านเท่านั้น ไม่เพิ่มคำเตือน/ข้อความขายสินค้า
  หรือเปลี่ยนหน้าตาแอป. Hosting ยังคงห้ามรับ IP, MAC, hostname, Credential, Counter, User, Document และ Application log;
  Company ต้องเป็นชื่อนิติบุคคล/หน่วยงานและ Serial No เป็นข้อมูลอุปกรณ์; ทั้งคู่ต้องอยู่ใน Registration Data Notice/
  retention/access policy และผ่าน Product owner/Hosting Security approval ก่อน production. หาก Hosting เก็บ Source IP
  หรือข้อมูลบุคคล ต้องเปิด privacy assessment แยก.
- 2026-08-20 — Step 3 shared-pricing ต้องแสดง `วิธีใช้ราคา → วันที่เริ่มใช้ → ตารางราคา → รอบบิล/วันตัดรอบ`
  ครบใน viewport เดียวที่ 1120×720 และขนาดขั้นต่ำ 980×620 โดย vertical scroll เป็น 0. ใช้พื้นที่แนวนอนสำหรับ
  heading/help และ billing controls, คง touch target อย่างน้อย 42–44 px, ย่อเฉพาะ spacing/padding ที่ฟุ่มเฟือย,
  และไม่ลด/ซ่อนวันตัดรอบหรือคำอธิบายสำคัญ. โหมดราคาแยกรายเครื่องยังยอมให้ scroll ตามจำนวนเครื่องได้.
- 2026-08-20 — Validation ที่แก้ไขได้ตรงหน้า เช่นชื่อบริษัทว่าง ไม่ใช้ modal: แสดง error ใต้ช่อง, เปลี่ยน border
  เป็น semantic red, focus กลับช่องกรอก และล้าง error ทันทีเมื่อผู้ใช้พิมพ์. คำเตือนอื่นของ Setup Wizard เลิกใช้
  native `QMessageBox` ซึ่งถูก global button polish บีบ layout บน macOS; ใช้ Wizard-owned alert กว้างขั้นต่ำ 500 px,
  word-wrap, selectable text, ปุ่ม action อยู่ใน layout และใช้ light palette/i18n เดียวกับ Wizard.
- 2026-08-20 — Customer First-Run UAT ต้องไม่ใช้ฐานข้อมูล production เดิม เพราะจะทำให้เครื่องและสถานะครั้งก่อน
  ปรากฏเหมือนเป็นผลค้นหารอบใหม่. เพิ่ม launcher `Open KOMI Customer First Run.command` ให้ใช้ SQLite เปล่าแบบถาวร
  แยกที่ `~/KOMI Report V5/Customer First Run UAT/KOMI_Report_V5.db` แต่ยังใช้ discovery/test production จริงบน
  SNMP 161 และ HTTPS 443. เครื่องจากฐานข้อมูลเดิมที่เปิดผ่าน Wizard แก้ให้แสดง `บันทึกไว้ · รอตรวจสอบรอบนี้` และ
  ปิดปุ่ม Next จนกว่าจะผ่าน SNMP + Web สดใน session ปัจจุบัน; ห้ามนำ cached `online` มาแสดงสีเขียว.
- 2026-08-20 — Bom ยุติการใช้ Setup Lab สำหรับ user acceptance และให้ทดสอบกับ LAN/Database จริง. ปิด process
  Virtual Printer/temporary DB แล้วเปิด `app.py` จาก source canonical ด้วยฐานข้อมูลจริง. Lab code ยังคงไว้สำหรับ automated
  regression เท่านั้น. แก้ endpoint routing ให้พอร์ตจำลอง `1161/8443` ใช้เฉพาะ `127.0.0.1`; IP LAN ที่ผู้ใช้กรอกเอง
  ใช้ production `161/443` เสมอ เพื่อไม่ให้ Lab configuration รั่วเข้าการสแกนเครื่องจริง.
- 2026-08-20 — Step 1 แสดง Database Path ที่จะใช้งานและให้เลือกตำแหน่งสร้างไฟล์ใหม่. การเลือก Path เป็น staging
  และไม่เขียนไฟล์ทันที; ตอนบันทึกจึง copy ฐานข้อมูลตั้งต้นผ่าน SQLite backup, ตรวจ integrity, ปฏิเสธการเขียนทับไฟล์เดิม,
  แล้วบันทึก path แบบ atomic ใน `runtime.toml`. ปุ่ม `นำเข้าฐานข้อมูลเดิม` อยู่ข้าง Path และเปิด safe V4.6 history import
  ซึ่งนำเข้าเฉพาะ Meter/Usage ตาม Slot. Card V4.6 เดิมถูกถอดออกจาก Device step เพื่อไม่ให้ซ้ำ.
- 2026-08-20 — Popup ที่ Setup Wizard เป็นเจ้าของทั้งหมดต้องผ่าน modal light-theme helper เดียวกัน ไม่รับ
  macOS Dark Mode แยกจากหน้าหลัก. Advanced scan, Manual setup, Credential และ Slot/naming dialog ใช้ palette,
  form control, focus state และ i18n contract เดียวกัน; native title bar ยังคงตาม OS แต่ content ต้องอ่านได้เสมอ.
- 2026-08-20 — Language selector บน Step 1 เปลี่ยนจาก native `QComboBox` เป็น segmented control `ไทย | EN`
  เพื่อไม่ให้ popup ของ macOS ลอยผิดสัดส่วนหรือแยกจากกรอบ Wizard. สถานะที่เลือกเห็นชัด ใช้ keyboard focus ได้,
  บันทึก `ui_language` เดิม และซ่อนเมื่อเข้าสู่ Step 2; เลข `1 / 4` ยังคงเป็น progress แยกกัน. หลัง review พบว่า
  รอบแรกตรวจเฉพาะ control/layout แต่ English copy ยังไม่ครบ จึงเติมคำแปลทั้ง 4 Step และเพิ่ม gate ที่ fail เมื่อ widget,
  ComboBox, table header หรือ cell ที่มองเห็นยังมีอักษรไทย (ยกเว้นปุ่มชื่อภาษา `ไทย` และข้อมูลธุรกิจของผู้ใช้).
- 2026-08-20 — Bom อนุมัติทิศทาง Setup เป็น `นำเครื่องพิมพ์เข้าระบบอย่างปลอดภัย`: การสแกน LAN เริ่มหลังผู้ใช้กดเข้า Step 2,
  Quick path เป็น action หลัก, Advanced/Manual อยู่ใต้ `ค้นหาไม่พบ?`, เลือกเครื่องด้วย Checkbox และ Next เปิดเมื่อ SNMP/Web ผ่านครบ.
  Step 3 อนุญาต `ตั้งค่าราคาภายหลัง` แบบ explicit no-charge; ราคา 0 ทั้งชุดห้ามผ่านถ้ายังไม่เลือกสถานะนี้. V4.6 Import
  แสดงเฉพาะเมื่อพบ source schema ที่ยืนยันแล้วหรือมีประวัตินำเข้า. Review เปลี่ยนจาก text wall เป็น section rows พร้อม Edit และบอกขอบเขต local/external.
- 2026-08-20 — Setup Wizard ใช้ Light Theme แบบ scoped ทั้ง 4 Step เพื่อให้ข้อความ ฟอร์ม ตาราง พื้นที่เลื่อน
  และปุ่มอ่านได้เหมือนกันบน macOS Dark Mode/Windows โดยไม่เปลี่ยนธีม Main Window. Company form ใช้
  `AllNonFixedFieldsGrow` และ field อย่างน้อย 470 px; Device table มี light palette ของตัวเอง; Price scroll/content
  บังคับพื้นขาว; Header แยก control group และยอมให้ title wrap ที่หน้าต่างขั้นต่ำเพื่อไม่ชน Language/STEP.
- 2026-08-20 — ใช้ Mac เป็น design/feedback loop หลักของ Setup Wizard เพื่อแก้และ render ได้เร็ว; Setup Lab
  บน macOS/Linux ใช้ `127.0.0.1`, SNMP `1161` และ HTTPS `8443` เพื่อไม่ต้องใช้สิทธิ์ Admin. Windows คง
  SNMP `161` / HTTPS `443` และ LAN `/24`; ทั้งสองระบบส่งค่า endpoint เข้า `NetworkDiscoveryWorker` และ
  `DeviceTestWorker` ชุดเดียวกัน จึงไม่แยก business logic หรือสร้าง mock UI คนละชุด.
- 2026-08-20 — รอบ visual แรกบน Mac พบ Company card/notice ถูก Qt บีบ, วันที่อ่านยากแบบ ISO และชื่อเครื่อง
  ซ้ำกับ Model ใน Review; แก้ width เป็น 760 px, แสดงวันที่ `dd/mm/yyyy` โดยยังเก็บ ISO และย่อชื่อเครื่องเป็น
  `KM bizhub …`. ภาพ 4 ขั้นใหม่เก็บใน `docs/setup-v51-mac-step*.png`.
- 2026-08-20 — Setup Lab ใช้ Virtual Printer แบบ protocol-level ใน Windows VM: ตอบ SNMP v2c ที่ UDP 161
  และ Web Connection-compatible HTTPS ที่ TCP 443 แล้วปล่อยให้ `NetworkDiscoveryWorker`, `SnmpTotalProbe`
  และ `MeterReader` เส้นทาง production ค้นหา/อ่านเอง; ไม่ inject demo row เข้า UI. Lab ใช้ self-signed certificate
  ชั่วคราวและ SQLite ชั่วคราวซึ่งถูกลบเมื่อปิด จึงไม่ปนกับข้อมูลผู้ใช้จริง.
- 2026-08-20 — ตัวอย่าง IP ใน Setup ใช้เครือข่ายกลาง `192.168.1.1` ถึง `192.168.1.255` และ Manual setup
  ใช้ `192.168.1.101`–`.103`; ไม่ใช้ IP `10.244.*` ของเครือข่ายลูกค้าเป็น placeholder.
- 2026-08-20 — เพิ่ม VirtualBox Shared Folder ถาวรชื่อ `komi-report-v5` ให้ VM `Window Test for KOMI`
  โดยชี้ตรงไปที่ `~/Projects/dev/komi-report-v5`, ตั้ง `readonly + auto-mount` เพื่อให้ Windows ทดสอบ Source
  ชุดเดียวกับ DEV โดยไม่เขียนย้อนเข้าต้นทาง; Share เดิม `KOMI_SOURCE` ที่ชี้ OneDrive ยังเก็บไว้ชั่วคราว.
- 2026-08-20 — เปิดรอบ V5.1 และย้าย canonical development source ออกจาก OneDrive ไป
  `~/Projects/dev/komi-report-v5` ด้วยวิธี copy → verify → switch; เก็บ symlink เดิมเป็น
  `~/Projects/dev/komi-report-v5.onedrive-link` และไม่ลบต้นฉบับ OneDrive จนกว่าจะผ่าน soak/target-OS verification.
- 2026-08-20 — Setup V5.1 ใช้ 4 ขั้น: Company registration → Devices → Cost/Billing → Review.
  ผู้ใช้กรอกเฉพาะชื่อบริษัท; วันที่เริ่มเปิดใช้และ Version `5.1.0` มาจากระบบแบบ read-only เพื่อไม่ให้ข้อมูลผิด.
- 2026-08-20 — Registration ส่งเฉพาะ installation ID, company, first-started date, app version,
  platform/architecture, device model และ timestamps ผ่าน dedicated HTTPS API แบบ retryable/idempotent.
  Serial, IP, Credential, Counter, User และข้อมูลเอกสารไม่อยู่ใน payload เริ่มต้น.
- 2026-08-20 — Update ใช้ client pull จาก Signed Manifest; V5.1 เริ่มด้วย Optional Notify + Download installer.
  One-click/mandatory update ต้องผ่าน code signing, database backup/restore, rollback และ native OS UAT ก่อน.
- 2026-08-11 — กำหนดให้ `Slot` เป็น logical identity ของจุดติดตั้ง/แผนก แทนการจับคู่ด้วย Serial. Setup Wizard รักษา Slot เดิม
  แม้ลำดับแถวเปลี่ยนและให้ยืนยันชื่อจุดติดตั้ง; Usage รวม V4.6/V5 ตาม Slot. Serial/Model/IP ยังคงเป็นหลักฐานของเครื่องในช่วงนั้น;
  เมื่อ Serial เปลี่ยนหรือ Meter ลด ระบบข้าม snapshot แรกเป็น Baseline ใหม่, ไม่คำนวณ delta ข้ามเครื่อง และ V4.6 cost แสดง `—`.
- 2026-08-10 — เพิ่ม `นำเข้าประวัติ V4.6` เป็น optional dialog ใน Step 1 และเปิดซ้ำได้โดยไม่เพิ่มจำนวน Step;
  source SQLite เปิด read-only, Preview ก่อนเขียน, Backup V5 ก่อน transaction และ import เฉพาะ aggregate Usage payload.
  ชื่อ/Serial เป็น snapshot ของประวัติเท่านั้น; Account/IP/Credential/Price/Settings/Cache/Log/Billing Ledger ไม่ถูกนำเข้า.
- 2026-08-06 — ยุบแท็บ `รายละเอียดเทคนิค` แล้ววาง Rules ต่อจากแผนเวลาใน `การทำงานอัตโนมัติ`; ห่อหน้าเป็น
  vertical scroll เพื่อให้แผน, ตารางช่วงเวลาแบบเลือกดู และกฎ Scheduler อยู่ในลำดับเดียวกันโดยไม่หายจากจอ.
- 2026-08-06 — เติมแถบเวลา 24 ชั่วโมงใน `การทำงานอัตโนมัติ` ตาม policy เดียวกับ Scheduler: แสดงช่วง Normal,
  ช่วงเริ่มงาน/เลิกงานหรือชื่อช่วงที่ตั้งเอง, Web throttle ของแต่ละช่วง และ highlight เวลาปัจจุบัน. ตาราง 7 คอลัมน์
  คงไว้เฉพาะเมื่อเลือก `แสดงตารางรายละเอียดตามช่วงเวลา` เพื่อไม่บังคับเลื่อนแนวนอนตั้งแต่เปิดแท็บ.
- 2026-08-06 — Implement redesign รอบแรกของ `บันทึกการซิงก์`: หน้าเริ่มต้นเป็นสถานะ/การทำงานต่อรายเครื่อง,
  ปุ่มอ่านข้อมูลตอนนี้ใช้ polling เดิม, พาไป Settings เพื่อแก้ Schedule, และประวัติ Log เหลือ 4 คอลัมน์พร้อม raw detail,
  Copy และ confirmation ก่อนล้าง. ไม่เปลี่ยน scheduler, cache, reconciliation หรือ billing evidence.
- 2026-08-06 — ใช้ `FrozenLeftTable` ให้หัวรอบบิลสองชั้นอยู่ในพื้นที่คงที่เหนือ body scroll และ sync แนวนอนกับข้อมูล; คอลัมน์ที่ตรึงยังเป็นวัน/เดือน/ปีเท่านั้น ไม่ตรึงชื่อหรือข้อมูลเครื่อง และไม่แตะ query, calculation หรือ Billing
- 2026-08-06 — หลังตรวจ YSoft SAFEQ Cloud `Reports Overview`, `Reports Users` และ `Reports Printers` ยกเลิก Report Center แบบ Usage/Management/Meter ใน user path และใช้ interaction model แบบ Cloud: ช่วงเวลาเดียวควบคุมทั้งหน้า, Dashboard widgets, Top ranking และกด User/Printer เพื่อ Cross-filter. Desktop กับ Web Edition ใช้โครงเดียวกัน; legacy tables/services ยังเก็บไว้สำหรับ Export/Audit และไม่เปลี่ยน Billing/RAM source boundary.
- 2026-08-05 — หลังตรวจ SafeQ จริง 3 หน้า (`Web reports`, `Management reports`, `Counter reports`) ยกเลิกแนวคิดปรับแท็บ Reports เดิม และสร้าง Report Center ใหม่: Usage ใช้ date range/filters/table/trend, Management ใช้ year/quarter/top five, Meter ใช้ raw first-and-last/daily readout/history. เก็บ Billing Ledger, Daily Cache และ RAM boundary เดิมไว้; ไม่สร้าง metric ที่ไม่มี source จริง.
- 2026-08-05 — Reports ใช้ interaction model แบบ YSoft SafeQ: เลือก `Report` ก่อน, เลือกรอบบิลในรายงาน, กด `Search` เพื่ออ่านข้อมูลใหม่ และเปิด `Advanced` เมื่อต้องการรายละเอียด Counter หรือรูปแบบสรุป; Standard แสดงยอดรวมปัจจุบันรวม Daily Cache แล้ว โดยไม่แยก Ledger/Cache เป็นสองก้อนบนหน้าปกติ. ที่มาหรือความต่างระหว่างยอดยืนยันและยอดระหว่างวันคงอยู่ใน Advanced เพื่อ Audit ได้.
- 2026-08-05 — Task Schedule ให้ผู้ใช้กำหนดเฉพาะช่วงเวลา Web Connection ได้เอง: ชื่อช่วง, เวลาเริ่ม–สิ้นสุด และ throttle; นอกช่วงใช้ Normal throttle, SNMP heartbeat และ Daily rollover ยังคงเป็นงานระบบเพื่อไม่ให้ Daily Cache/การปิดวันขาดช่วง. ไม่อนุญาตช่วงเวลาซ้อนกัน และการบันทึกจะ reload policy ของ Background process เดิม.
- 2026-08-05 — Bom อนุมัติให้ทำ Production hardening ทั้งหมดตาม review แบบ incremental โดย **ไม่ rewrite from scratch**
  และยกเว้นก้อน Security ปัจจุบันทั้งหมด: Web default login/access code/session secret, printer credential plaintext,
  login lockout/audit และ HTTPS/reverse proxy จะคง behavior เดิมตามคำสั่งผู้ใช้; ข้อยกเว้นนี้ไม่ใช่ production-security pass.
- 2026-08-05 — เลือกสถาปัตยกรรม Modular Monolith ต่อไป: เก็บ PyQt + FastAPI + SQLite + polling/ledger เดิม แล้วเพิ่ม
  application facade, repository และ migration ทีละส่วน; ห้ามย้าย billing/reconciliation logic แบบ mass rewrite.

- 2026-07-23 — ตั้ง Product Design Context สำหรับหน้าทำงานแบบ YSoft: หัวข้อเด่น/คำอธิบายรอง/ฟอร์มชัด,
  ไม่ใช้กล่องซ้อน ขอบหนา หรือ accent blue เพื่อการตกแต่ง; Step 2 จึงตัดเลขนำหัวข้อ, ขอบกลุ่ม และ coloured header bars ออก

- 2026-07-22 — Reports workspace ใช้ลำดับ `ภาพรวม | รายเครื่อง | ยอดใช้งานและค่าใช้จ่าย | รายผู้ใช้ | แนวโน้ม`;
  หน้า Overview ใช้รอบบิลเดียวกันสำหรับ KPI และตาราง Top โดย Cost แสดง Net cost หลังหักกระดาษเสีย,
  User/Account รวมจาก RAM ด้วย stable identity และแจ้งจำนวน device-day ที่ข้อมูลไม่สมบูรณ์แทนการซ่อน
- 2026-07-22 — เปลี่ยนชื่อ Sidebar และหัวหน้าจอจาก `History` เป็น `Reports` โดยคงตารางเดิมและสูตร Billing
  ทั้งหมดไว้ก่อน เพื่อไม่ให้การเปลี่ยนโครง Navigation กระทบยอดย้อนหลัง
- 2026-07-22 — สำรวจ YSoft Reports เป็น reference: Overview มี KPI/Top users/Top printers/timeline,
  Users และ Printers แยก Print & Copy/Scan พร้อม A4/A3 Color/B&W/Cost, Documents มี Summary/Details,
  Costs ผูก Pricing, Savings/ESG ใช้ environmental constants และ Scheduled reports ส่งไฟล์ตามเวลา
- 2026-07-22 — KOMI จะรับแนวคิดช่วงเวลาเดียวกันและมุม Overview/Printers/Users/Costs แต่ต้องยึด source boundary:
  Web Connection Device Meter เป็น Billing, RAM เป็น User/Account usage และ SNMP เป็นสถานะเท่านั้น;
  ยังไม่สร้าง Documents report หรือ Savings/ESG จนกว่าจะมีข้อมูล job-level และเกณฑ์คำนวณที่อนุมัติ

- 2026-07-22 — History Tab 1 ใช้ชื่อ `ค่ามิเตอร์สะสม`; Tab 2 ใช้ชื่อ `ประวัติการใช้งานย้อนหลัง`
  และแบ่งข้อมูลเป็นรายวัน, รายสัปดาห์, รายเดือน, รายไตรมาส และรายปี โดยทุกช่วงยึดวันสิ้นสุดรอบบิลที่ตั้งไว้
- 2026-07-22 — รายสัปดาห์เริ่มช่วงละ 7 วันจากวันแรกของรอบบิลและช่วงสุดท้ายอาจสั้นกว่า 7 วัน;
  รายไตรมาส/รายปีรวมจากรอบบิลที่ปิดในไตรมาส/ปีนั้น โดยไม่สร้างตารางเก็บข้อมูลซ้ำ
- 2026-07-22 — หัวตารางประวัติย้อนหลังใช้ 2 ชั้น: `รอบบิล` merge แนวตั้ง, ชื่อเครื่องและ
  `รวมทุกเครื่อง` merge ครอบ `Color | B&W | Cost`; Color/B&W รวม A3+A4 ของ Print/Copy
  และเมื่อเปิด `รายละเอียดเพิ่มเติม` ให้ขยาย A3 Color/A3 B&W/A4 Color/A4 B&W/Scan เป็นคอลัมน์
  ภายใต้ชื่อเครื่องโดยจำนวนแถวต้องไม่เปลี่ยน; Checkbox ส่วนลดใช้ข้อความ `% กระดาษเสีย`
- 2026-07-22 — กลุ่มเครื่องใน History ใช้โทนอ่อนตามสีประจำ Slot ทั้งหัวและข้อมูล; กลุ่มรวมใช้เทาอมฟ้า;
  horizontal scroll ของหัวตารางและข้อมูล sync สองทาง และย้ายชุดตัวเลือกลงอีกแถวพร้อม minimum width
  เพื่อไม่ให้ `รายละเอียดเพิ่มเติม` กับ `% กระดาษเสีย` ซ้อนกันเมื่อหน้าต่างแคบ

- 2026-07-16 — ใช้ V4.6 และ KOMI SNMP Profiler เป็น read-only source projects
- 2026-07-16 — Bom อนุมัติ Modular Python Desktop และให้เก็บ PWA/FastAPI เป็น growth path
- 2026-07-16 — Baseline V5 รวม Read Meter, Import และ regression suite ได้แล้ว แต่ Live public read ติด `Nack/raise`
- 2026-07-16 — เปลี่ยน primary workflow จาก Import-first เป็นตั้งค่าเครื่อง 1–3 เครื่องและ Auto-read Background;
  Import `.txt` เหลือเป็น fallback
- 2026-07-16 — กำหนด SNMP ทุก 5 นาที, Web on-change, normal throttle 15 นาที, peak throttle 5 นาที
  และ Web fallback 5 ครั้งห่างกัน 5 นาที
- 2026-07-16 — เลือก Daily Cache + Daily Rollup หนึ่ง record ต่อเครื่องต่อวัน เพื่อลดฐานข้อมูลโดยไม่เสีย raw counters
- 2026-07-16 — Usage เก็บ/แสดงค่าดิบ; cost category ใช้เฉพาะ Billing และรองรับ `ไม่คิดเงิน`
- 2026-07-16 — Pricelist แยกรายเครื่อง มีวันที่เริ่มมีผล; billing day และ waste discount ใช้ร่วมกันทุกเครื่อง
- 2026-07-16 — Bom อนุมัติ revised design และสั่งเริ่ม implementation
- 2026-07-16 — เพิ่ม V5 schema version 6: devices, daily meter, price history และ cost-category history
- 2026-07-16 — เพิ่ม SNMP heartbeat ใน Daily Cache เพื่อแยกวันที่ไม่มีงานพิมพ์ออกจากข้อมูลขาดช่วง
  โดยยังไม่เรียก Web เมื่อ Total Meter ไม่เพิ่มตาม requirement
- 2026-07-16 — เพิ่ม SetupWizardV5, adaptive Overview, pinned raw counters, effective billing, Tray และ Auto-start
- 2026-07-16 — เปลี่ยน release baseline เป็น `5.0.0-dev2`; source ZIP ถูกสร้างใหม่และตรวจ checksum/extracted tests แล้ว
- 2026-07-16 — Live UAT ผ่าน 2 เครื่อง: C450i และ C750i อ่าน Online, Model, Serial, Total และ Web Counter ได้ 96 ค่า/เครื่อง
- 2026-07-16 — แก้ Overview ให้รองรับ Operation Counter แบบ total/large ของ firmware จริง และอธิบาย first-read baseline
- 2026-07-16 — เพิ่ม Sidebar `Log` พร้อม Live Pipeline, Daily Cache/Database และ Rules; Live trace เก็บใน bounded RAM
  ส่วนสถานะ Cache/DB อ่านจาก persistent source จริง
- 2026-07-16 — ยืนยัน SNMP Total Meter เป็น Printer-MIB `1.3.6.1.2.1.43.10.2.1.4.1.1` บน C450i/C750i;
  เปลี่ยนจากเลือกค่าสูงสุดใต้ root เป็นเลือก primary marker row โดยตรงและแสดงผลเทียบ Web Total ใน Log
- 2026-07-16 — เปลี่ยนเป็น Auto-calibration แยกเครื่อง/รุ่น: อ่าน Standard/Private SNMP candidates แล้วเทียบกับ
  Web `counter.total.total`; จำเฉพาะ OID ที่ค่าเท่ากัน และล้าง mapping เพื่อเทียบใหม่เมื่อรุ่น/ค่าไม่ตรง
- 2026-07-16 — Checkpoint ก่อนพัก: C450i/C750i calibrate เป็น `.43.10.2.1.4.1.1`, SNMP/Web Total ตรงกัน,
  heartbeat 19 และ Web samples 14 ต่อเครื่อง; source ผ่าน 91 tests แต่ Release ZIP/Dashboard รอบ Auto-calibration ยังรอ rebuild
- 2026-07-16 — ลดความซับซ้อนหน้า debug เป็น Sidebar `Connection`: เลือกเครื่องและอ่านทันที โดยแสดง
  SNMP Total Meter, Web Connection ทุกค่า และ RAM dump ทุก field แยก 3 คอลัมน์
- 2026-07-16 — เพิ่ม Mock mode เป็นค่าเริ่มต้น ใช้ snapshot ล่าสุดจาก Daily Cache เพื่อทดสอบ UI นอกเครือข่าย
  โดยไม่ยิงเครื่อง ไม่เพิ่ม sample และไม่เขียน Database
- 2026-07-16 — ตาม direction ล่าสุด คืน Sidebar `Overview` ไปใช้ `PageOverview` ต้นฉบับของ V4.6 โดยตรง
  และกำหนดให้ workflow รับข้อมูล/อ่านเครื่องที่ต้องออกแบบต่ออยู่ในหน้า `Import` แทน
- 2026-07-16 — หน้า `Import` ใช้ device-first layout: หนึ่งคอลัมน์ต่อหนึ่งเครื่องแบบ adaptive 1–3 เครื่อง;
  แต่ละคอลัมน์แสดง Model/Serial/Total/Toner จาก SNMP, Total จาก Web และ User Auth/Account Track เมื่อมีข้อมูล
- 2026-07-16 — เก็บ Import `.txt` ของ V4.6 ไว้หลังปุ่มย่อ/ขยาย และเพิ่ม Mock UI ชั่วคราวที่ไม่เชื่อมต่อเครื่อง
  ไม่เพิ่ม sample และไม่เขียนค่า mock ลง Cache/Database
- 2026-07-16 — เปลี่ยนส่วน Web Connection จากยอดรวมอย่างเดียวเป็นตารางทุก Counter พร้อม Scrollbar แยกในแต่ละเครื่อง
- 2026-07-16 — เพิ่ม `RuntimeSnapshotStore` แบบ process-memory only แยก Web rows กับ User/Account Track rows;
  หน้า Import แสดงทุก subject field ในตาราง RAM โดยไม่เขียน working export ลงไฟล์หรือ Downloads
- 2026-07-16 — ล็อกตาราง Import ให้ทุกแถวสูง 32 px, หัวตารางสูง 36 px และคอลัมน์ตัวเลขกว้าง 84 px
  พร้อมกำหนด alignment ของข้อความ/ตัวเลขโดยตรง เพื่อให้ Web และ RAM ตรงกันทุกเครื่อง
- 2026-07-16 — ภาพจากผู้ใช้พบว่า Qt `item:alternate` บวก padding ซ้ำจนข้อความเยื้องสลับแถว;
  ปิด alternate pseudo-state แล้วใส่พื้นหลังสีสลับให้ cell โดยตรง จึงคง zebra rows โดยตำแหน่งข้อความไม่ขยับ
- 2026-07-16 — กรอบ User Authentication / Account Track ในหน้า Import แสดงเพียงหนึ่งแถวต่อ User/Account
  และ `Total Counter`; field รายละเอียดยังคงอยู่ใน Runtime RAM snapshot และหน้า Connection/Log ไม่ถูกตัดทิ้ง
- 2026-07-16 — History > ค่ามิเตอร์ปัจจุบันคง shell และแท็บอื่นของ V4.6 แต่เปลี่ยน Current Meter เป็นข้อมูล V5:
  Current จาก SNMP/Web ล่าสุด, Opening จาก Web snapshot แรกของวัน และ Today delta จาก persistent Daily Cache
- 2026-07-16 — ค่าเริ่มต้นของ History > ค่ามิเตอร์ปัจจุบันแสดงเฉพาะ `ค่าปัจจุบัน`;
  `ค่าเริ่มต้นวันนี้` และ `วันนี้เพิ่ม` ซ่อนไว้จนกว่าผู้ใช้จะเปิด Checkbox เปรียบเทียบ
- 2026-07-16 — History > ย้อนหลังรายเดือนใช้หนึ่งแถวต่อรอบบิล แสดง Usage/Cost รายเครื่องและรวมทุกเครื่อง;
  A3/A4/Scan เป็นรายละเอียดแบบเปิดภายหลัง และ Cost คำนวณตาม category/price ของแต่ละวันก่อนรวมเดือน
- 2026-07-16 — ยืนยัน SNMP ใช้ดูสถานะ/trigger เท่านั้น; Usage และ Billing ใช้ Web Connection Device Meter
- 2026-07-16 — RAM dump ใช้ดู User Authentication / Account Track เท่านั้น ไม่บวกกับ Device Meter และไม่คิดเงิน
- 2026-07-16 — Device Meter นับจำนวนหน้าของงาน Duplex แล้ว จึงห้ามคูณสองซ้ำใน Billing
- 2026-07-16 — เพิ่ม Reconciliation Warning: หากผลรวม Web Counter ไม่ตรงกัน จะแสดง `Needs Review`,
  ค่าที่นำมาเทียบและส่วนต่างในหน้า Import/Connection/Log โดยยังไม่แก้หรือเดาค่าให้อัตโนมัติ
- 2026-07-16 — History > ผู้ใช้งานถูกจัดเป็น NO-GO: ต้องตัดค่าใช้จ่าย/การประมาณ A3-A4 ออก และเปลี่ยนเป็น
  append-only User/Account Total Counter history แยกจาก Device Billing ก่อนใช้ Production
- 2026-07-16 — แก้ History > ค่ามิเตอร์ปัจจุบันให้ Total Meter ใช้ Web Connection เท่านั้น;
  `last_snmp_total` เหลือเป็นสถานะ/trigger และไม่ถูกนำมาแสดงเป็นยอดใช้งาน
- 2026-07-16 — เพิ่ม schema v7 `daily_subject_records` และ `SubjectDailyCacheStore`: User/Account เก็บเฉพาะ
  Total Counter แบบ daily append-only, รวมทุก snapshot, ใช้ subject ID เป็น identity และไม่ผูกกับ Billing
- 2026-07-16 — Coverage ของ User/Account ไม่บังคับให้เท่ากับ Device Meter; ส่วนที่ต่ำกว่าถือเป็น
  Public/Untracked/unsupported และเตือน hard mismatch เฉพาะเมื่อ User/Account sum สูงกว่า Device Meter
- 2026-07-16 — ปรับ User History เป็น Pivot Table `User | เครื่อง 1 | เครื่อง 2 | เครื่อง 3 | รวมทุกเครื่อง`;
  ไม่รวมด้วยชื่ออย่างเดียว แต่ใช้ subject type/ID เดียวกันข้ามเครื่องเพื่อป้องกัน identity collision
- 2026-07-20 — กลับเข้าเครือข่ายและยืนยัน Live UAT: SNMP/Web Total ของ C450i/C750i ตรงกัน,
  Web Reconciliation ผ่านเครื่องละ 16 จุด และ Sales Daily Cache รวม Usage 205 ตรงกับ A4 Color 161 + A4 B&W 44
- 2026-07-20 — Controlled print ที่ DMS ผ่าน: A4 Color 1 หน้าเพิ่ม Device/Cache/User อย่างละ 1;
  แก้ชื่อ User จากเลขลำดับ `1` เป็น `DMS` โดย enrich จาก RAM Meter export ที่ลูกค้าเห็น
- 2026-07-20 — หน้า Import เปลี่ยนจาก Mock/Import control เป็น `Sync now`; เพิ่มตัวเลือกซ่อน Web Counter
  ที่เป็นศูนย์โดยไม่ลบข้อมูล และ User/Auth แสดงชื่อจริงจาก RAM Meter export
- 2026-07-20 — `Sync now` อ่าน Printer-MIB Supplies พร้อม SNMP identity/total และ Web Connection ในรอบเดียว;
  คำนวณ C/Y/M/K จาก Current Level ÷ Capacity, เก็บ `snmp_toner` ใน Daily Cache และคงค่าล่าสุดเมื่ออ่านรอบใหม่ไม่ได้
- 2026-07-20 — นำ Meter Pipeline Log กลับมาเป็นหน้า `Sync Log` ใน Sidebar และเพิ่มปุ่มจากหน้า Import;
  Timeline วันนี้แสดง Daily rollover, Normal/Peak windows, SNMP/Web/RAM/DB และเวลารอบถัดไปแยกเครื่อง
- 2026-07-20 — แก้ Sync Log row origin: ปิด Qt alternate pseudo-state, กำหนด zebra background ราย cell,
  ล็อกแถว 34 px/หัวตาราง 40 px, ย่อเวลาและ Machine/IP เป็นบรรทัดเดียว และไม่ rebuild ตารางเมื่อ Event ไม่เปลี่ยน
- 2026-07-20 — เพิ่ม Diagram กฎการ Sync แบบสีแยก source: Scheduler/Sync now → SNMP → เงื่อนไข Total/throttle
  → Web billing source → RAM User/Account → Daily Cache/Daily Record พร้อม failure/offline branches
- 2026-07-20 — เพิ่ม Data Storage Overview ตาม implementation จริง แยก Process RAM, Device/User JSON Daily Cache,
  SQLite V5 tables, V4.6 import tables และ consumer boundaries พร้อมระบุ Billing Ledger gap โดยตรง
- 2026-07-20 — เพิ่ม Manual tab `ระบบ V5` เป็นหน้าแรก แสดง thumbnail และปุ่มเปิด Sync/Data Storage Diagrams แบบ Local;
  เพิ่ม HTML/PNG ทั้ง 4 ไฟล์ใน PyInstaller datas เพื่อให้ติดไปกับ Release package
- 2026-07-20 — ถอด `Read Meter` และ `Connection` ออกจาก Sidebar และไม่สร้างสองหน้าซ้ำใน Main Window;
  บริการ SNMP/Web/RAM เบื้องหลังยังทำงานผ่าน Import, Sync now, Sync Log และ Scheduler ตามเดิม
- 2026-07-21 — Bom อนุมัติ Setup Wizard แบบทีละขั้น 4 หน้า: Auto network scan และ Multiple Checkbox สูงสุด 3 เครื่อง,
  บังคับ SNMP/Web ผ่านทุกเครื่อง, Cost แบบรวมทุกเครื่องหรือแยกรายเครื่อง, waste 2%, วันสิ้นสุดรอบวันที่ 31/วันสุดท้าย,
  Review และ First Sync ก่อนเปิด Import; Interactive Mockup อยู่ที่ `PROJECT.html`
- 2026-07-21 — เมื่อเลือก `ตั้งราคาแยกรายเครื่อง` ให้แสดง Price section แยกสูงสุด 3 section ตามเครื่องที่เลือก
  แต่ละ section มี A4/A3 Color/B&W ของตัวเอง; Cost/Billing กลางตั้งเพียงครั้งเดียว
- 2026-07-21 — เลือกราคาได้เพียงหนึ่งโหมด: `ใช้ราคาเดียวกันทุกเครื่อง` แสดงเฉพาะตารางกลาง;
  `ตั้งราคาแยกรายเครื่อง` แสดงเฉพาะ 3 section รายเครื่อง โดยบังคับ `hidden` ให้ไม่ถูก CSS grid ทับ
- 2026-07-21 — นำ Cost & Billing เข้า PyQt6 Wizard จริง: Shared Price จะบันทึก PriceList เดียวกันให้ทุกเครื่องที่เลือก;
  Per-device จะบันทึกตามเครื่อง และบังคับให้ SNMP/Web ผ่านก่อนกดไปหน้า Cost
- 2026-07-21 — `billing_day` ของ V5 เปลี่ยนความหมายเป็นวันสิ้นสุดรอบบิล; รองรับ 1–31 และวันที่ไม่มีในเดือน
  ใช้วันสุดท้ายของเดือน เช่น 31 ก.พ. = 28/29 ก.พ.
- 2026-07-21 — แทน Wizard เดิม 2 ขั้นด้วย Wizard จริง 4 ขั้น: Auto network scan/เลือกเครื่องและทดสอบ,
  Cost & Billing, Review และ Start; Scan ใช้ SNMP แบบ background ใน subnet /24 ปัจจุบันและยังกรอก IP เองได้
- 2026-07-21 — หน้าสแกนใช้ตารางผลลัพธ์แทน Text Box: คลิกเลือกหลายแถวสูงสุด 3 เครื่องพร้อม badge 0/3–3/3;
  มี Quick scan, Advanced scan ระบุ IP เริ่ม/สิ้นสุด และลิงก์ตั้งค่า User/Password ต่อเครื่อง
- 2026-07-21 — ตาราง Scan บังคับ padding ของ selected/unselected row ให้เท่ากัน; ปุ่ม Test อยู่ navigation bar;
  เมื่อ Test ไม่ผ่านทั้งแถวและสถานะเป็นสีแดง พร้อม error จาก SNMP/Web
- 2026-07-21 — สีผลทดสอบมีลำดับสูงกว่าสีเลือกแถว: ผ่าน = เขียว, ไม่ผ่าน = แดง แม้แถวยังถูกเลือก;
  สีฟ้าใช้เฉพาะแถวที่เลือกก่อนมีผล Test เพื่อไม่ให้ Error/Passed ถูกซ่อน
- 2026-07-21 — Qt selection overlay ไม่ใช้เป็นสีของผลลัพธ์ เพราะทับ background ของ cell ได้;
  ตาราง Scan ใช้ delegate วาด background ที่กำหนดในข้อมูลแทน จึงเห็นฟ้า/เขียว/แดงขณะเลือกแถวได้จริง
- 2026-07-21 — สีพื้นเป็น highlight ของ “แถวที่เลือก” เท่านั้น: คลิกยกเลิกเลือกหลัง Test จะเอาสีพื้นออก
  แต่คงข้อความสถานะสีเขียว/แดงไว้ เพื่อให้ผลทดสอบยังอ่านได้
- 2026-07-21 — หน้า Pricelist ใช้ลำดับ 3 ส่วน: วิธีใช้ราคา, ตารางราคา A4/A3 × Color/B&W และรอบบิล;
  ใช้สีตามหน้าที่ของข้อมูล, ช่องไฟสม่ำเสมอ และ Scroll area รองรับราคาแยกสูงสุด 3 เครื่อง
- 2026-07-21 — Live Web Connection ของ C450i ยืนยันว่า `Device Total Large` นิยามเป็น Print Large + Copy Large:
  12,848 + 677 = 13,525; กฎเดิมบวก `counter.scan_fax.print_large` อีก 8 จึงเกิด false positive 13,533
- 2026-07-21 — สมการ Total ปกติกับ Total Large ใช้ taxonomy ไม่เหมือนกันใน C450i:
  Total ปกติต้องรวม Scan/Fax Print Total แต่ Total Large ไม่รวม Scan/Fax PrintLarge; ห้ามใช้สูตรเดียวครอบทุก aggregation
- 2026-07-22 — ใช้ reconciliation profile แบบมีเวอร์ชัน `konica.web_connection.device_meter.v2`:
  Device Total รวม Print + Copy + Scan/Fax Print Total แต่ Device Total Large รวมเฉพาะ Print/Copy Large/LongSize
- 2026-07-22 — Daily Cache schema v2 เก็บ raw Counter source path, reconciliation profile, breakdown ของสมการ
  และ `billing_safe`; เมื่อผลไม่ตรงให้เก็บ raw snapshot ต่อแต่ตั้ง POLICY เป็น `Billing evidence held for review`
- 2026-07-22 — หน้า Import แสดงจุดสถานะหลังชื่อเครื่อง: เขียวเมื่อ `online`, แดงเมื่อ Sync ไม่ผ่าน
  และเทาก่อนตรวจ; หากมีเครื่องใดไม่ผ่านหลัง `Sync now` ให้แสดงข้อความแดงเล็กใต้ปุ่มโดยไม่เปิด Popup
- 2026-07-23 — Billing ใช้ append-only Ledger แบบ fail-closed: Posting/Hold/Reversal/Replacement เก็บ frozen
  identity, รอบบิล, source hash, delta/category/price, waste, formula และ attestation; การแก้ยอดเป็น transaction เดียว
  และหน้า Billing Audit แสดง lifecycle/filter/search/detail/export โดยไม่แก้รายการเดิม
- 2026-07-23 — Daily Cache ที่เสียถูก quarantine พร้อม SHA-256 ก่อนสร้าง recovery marker และวันดังกล่าวถูก Hold;
  per-path lock กับ active-slot deferral ป้องกัน poll/finalize แข่งกันตอนข้ามวันโดยไม่ทิ้ง cache เมื่อ retry
- 2026-07-23 — Cost classification เพิ่ม approved aliases `Legal`/`Folio` เป็น A3; ชื่อที่ยังไม่มีหลักฐานจริง
  เช่น Letter/Ledger คง `no_charge` แบบ fail-closed จนกว่าจะได้ raw Web fixture จากเครื่องจริง
- 2026-07-23 — History/Reports แยก logical device identity แม้ใช้ slot เดิมหรือปิด device แล้ว; current view ใช้เฉพาะ
  identity ปัจจุบัน ส่วนยอดรวมย้อนหลังยังเก็บทุก identity พร้อม warning และ provenance จาก Ledger
- 2026-07-23 — แยกคำสั่งใน Settings ให้ชัด: “ล้างข้อมูลการใช้งาน” เก็บเครื่องพิมพ์และไม่เปิด Wizard;
  “เริ่มตั้งค่าใหม่” ลบ devices, ราคา, รอบบิล, daily evidence, Billing Ledger และ runtime cache แล้วสร้าง schema/trigger ใหม่
  เพื่อให้การเปิด Desktop ครั้งถัดไปเข้าสู่ Setup Wizard แน่นอน
- 2026-08-04 — Overview Printer Status ใช้ card แบบ responsive: ชื่อเครื่อง/Serial/IP อยู่กลุ่มเดียวที่ยืดตามพื้นที่,
  สถานะแสดงทั้งสีและข้อความ/คำอธิบาย, Toner แสดง C/Y/M/K ครบในกลุ่มขนาดจำกัด; KPI เปลี่ยนเป็น 2 คอลัมน์
  เมื่อความกว้างหน้าต่างยังไม่ถึง 1,600 px เพื่อไม่ตัดชื่อหรือตัวเลขสำคัญ

## Test Log

| Time | Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| 2026-08-22 09:41 +07 | Production Phase 1 delivery | Security baseline ต้องผ่านครบ, fast-forward เข้า main, push private origin และคง Phase 0 gate | implementation `13c9488` fast-forward/push สำเร็จ; final durable close record อยู่ใน commit ถัดไป; Dashboard publish ส่งกลับ main threadและไม่แก้ portfolio-site | PASS — PHASE 1 COMPLETE | `work/01a02733-fd41-78c3-aa89-e735a595a458/PROJECT.md`, `git merge --ff-only`, `git push origin main`, final clean/read-back |
| 2026-08-22 09:39 +07 | Production Phase 1 Security Baseline pre-merge | LAN/auth/vault/printer TLS/dependency gates ต้องผ่านโดยไม่แตะข้อมูลจริงหรือ Meter/Billing semantics | Live TLS 1.3 + LAN SAN/HTTP block/API loopback/auth lifecycle ผ่าน; OS vault migration/pin tests ผ่าน; npm/pip audit 0; Python 410, Web security 2, build/typecheck, focused Ruff, release 8, tracked candidates 230/0 และ releasable set 210/0 ผ่าน | PASS — PRE-MERGE; รอ commit/main/push/clean | `work/01a02733-fd41-78c3-aa89-e735a595a458/PROJECT.md`, `source/tools/security_live_check.py` |
| 2026-08-22 08:49 +07 | Production Phase 0 clean-checkout/tag/private remote | Artifact ต้อง build จาก clean clone, ชี้กลับ commit, SHA256 ตรง, ไม่มี forbidden content และ private remote ต้องไม่ชนชื่อ | Commit `85e308f`, tag `v5.1.0-phase0`; clean clone source artifact 204 files, source `clean`, SHA256 `a15776f0…`, forbidden entries 0; private GitHub `binlabongbom/komi-report-v5` main/tag push และ read-back สำเร็จ | PASS — PHASE 0 COMPLETE; Phase 1 ยังไม่เริ่ม | `work/01a0271d-8f64-79a2-89f7-5129dc34c6dd/PROJECT.md`, `release/MANIFEST.json` (local ignored artifact), Git/GitHub read-back |
| 2026-08-22 08:47 +07 | Production Phase 0 pre-commit gate | ห้าม track/package DB/CSV/log/env/credential/output/customer evidence; version ต้องตรงและ behavior ไม่ถอย | Shared gate reject negative CSV/output/token cases; candidate scan 223 files = 0 findings; export จริง 2 จุดอยู่ ignored; focused 8/full 399 tests, scoped Ruff, Web typecheck/Next build ผ่าน | PASS — PRE-COMMIT; รอ commit/clean clone/tag/remote | `.gitignore`, `source/tools/release_safety.py`, `source/tools/build_local_release.py`, `source/tests/test_release_builder.py`, `work/01a0271d-8f64-79a2-89f7-5129dc34c6dd/PROJECT.md` |
| 2026-08-20 22:32 +07 | Wizard native-control polish + Registration Envelope Preview | Slot dropdown, ราคา, calendar และปุ่ม Review ต้องไม่หลุด Dark Mode/ถูกตัด; Step 4 ต้องแสดงข้อมูลที่จะส่งและสิ่งที่ห้ามส่งก่อนบันทึก | เพิ่ม painted chevron/light popup สำหรับ ComboBox, ซ่อน spin steppers, บังคับ light Calendar, ลดปุ่ม Edit เป็น 78×36 และแทน action ของ Registration ด้วยสถานะ `ยังไม่ส่ง`. เพิ่ม allow-listed envelope: installation ID, company, first started, version, OS/architecture, model+quantity; หลัง Save เก็บ pending envelope ใน local config และไม่มี network call. Regression `368 passed + 1 isolated cancellation passed`, compileall/scoped Ruff ผ่าน; offscreen visual ตรวจ Price/Calendar/Slot popup/Review ผ่าน และ Review ที่ 1120×720 มี scroll maximum `0`. Restart Customer First Run จาก source ล่าสุด PID `44231`, DB integrity `ok`, devices `0` | PASS — SOURCE/PRIVACY UNIT/OFFSCREEN VISUAL + CLEAN REAL PROCESS; รอ Bom ตรวจ interaction บน macOS live, Hosting/API/Privacy ยังไม่ผ่าน | `source/v5_pages.py`, `source/services/registration_envelope.py`, `source/i18n.py`, `source/tests/test_registration_envelope.py`, `source/tests/test_setup_wizard_v5.py`, `/tmp/komi-v51-polish-price.png`, `/tmp/komi-v51-polish-calendar.png`, `/tmp/komi-v51-polish-slots-2.png`, `/tmp/komi-v51-combo-popup.png`, `/tmp/komi-v51-registration-review.png` |
| 2026-08-20 21:49 +07 | Compact Step 3 shared-pricing layout | ที่ 1120×720 และ 980×620 ต้องเห็น Price Matrix, ส่วนลดกระดาษเสีย, วันสิ้นสุดรอบบิล, hints และ footer ครบโดยไม่เลื่อน | รวม heading/help เป็นแถวเดียว, mode 44 px, compact matrix, billing เป็น horizontal band. Render จริงได้ scroll maximum `0`; 1120×720 billing bottom/viewport `427/533`, 980×620 `411/433`. Focused `26 passed`, full `360 passed`, compileall ผ่าน, Impeccable layout detector `[]`. Restart clean real UAT PID `40108`, DB integrity `ok`, devices/setup `0/0` | PASS — TWO-SIZE OFFSCREEN VISUAL + SOURCE REGRESSION + CLEAN REAL PROCESS; รอ Bom live acceptance | `source/v5_pages.py`, `source/i18n.py`, `source/tests/test_setup_wizard_v5.py`, `/tmp/komi-wizard-price-compact-1120x720.png`, `/tmp/komi-wizard-price-compact-980x620.png` |
| 2026-08-20 21:44 +07 | Repair clipped company validation/modal alerts | ชื่อบริษัทว่างต้องบอกจุดผิดโดยไม่บังฟอร์ม; alert อื่นต้องไม่ตัดข้อความหรือปุ่มบน macOS/Windows/Linux และ i18n ต้องคง | เปลี่ยน company validation เป็น inline error/recovery; เพิ่ม owned alert 500–680 px พร้อม word-wrap/action geometry. Offscreen visual 1120×720 และ alert 500×154 อ่านครบ/ปุ่มอยู่ในกรอบ; focused `25 passed`, full `359 passed`, compileall ผ่าน. Impeccable detector พบ warning เดิม 4 จุดนอก Wizard diff. Restart clean real UAT เป็น PID `39558`, DB integrity `ok`, devices/company `0/0` | PASS — SOURCE/OFFSCREEN VISUAL + CLEAN REAL PROCESS; รอ Bom ยืนยัน live interaction | `source/v5_pages.py`, `source/i18n.py`, `source/tests/test_setup_wizard_v5.py`, `/tmp/komi-wizard-inline-error.png`, `/tmp/komi-wizard-owned-alert.png` |
| 2026-08-20 21:38 +07 | Customer First-Run real UAT + cached-status correction | ลูกค้าใหม่ต้องเริ่มจาก 0 เครื่อง; ไม่มี Virtual Printer/ข้อมูลเดิม; เครื่องที่เคยบันทึกห้ามขึ้นเขียวก่อนตรวจสด | `_load_existing` แยก historical status เป็น Saved/Pending และ Ready gate ต้องผ่าน SNMP+Web รอบปัจจุบัน. เพิ่ม persistent clean-db launcher; เปิด real `app.py` PID `38858`, SQLite integrity `ok`, devices `0`. Focused `25 passed`, full regression `357 passed`, compileall ผ่าน; Ruff scoped ยังรายงาน baseline เดิม 17 จุดนอก diff | PASS — CLEAN REAL-DB PROCESS + SOURCE REGRESSION; รอ Bom เดิน flow และยืนยัน visual/live scan | `Open KOMI Customer First Run.command`, `source/v5_pages.py`, `source/i18n.py`, `source/tests/test_setup_wizard_v5.py`, `~/KOMI Report V5/Customer First Run UAT/KOMI_Report_V5.db` |
| 2026-08-20 21:30 +07 | Switch from Lab to real LAN/database UAT | Advanced range 10.244.116.1–254 ต้องใช้ SNMP 161 ไม่ใช่ Lab 1161; ปิด Virtual Printer และเปิด Wizard กับ DB จริงโดยมี rollback | พิสูจน์ `.107:1161` timeout แต่ `.107:161` อ่าน C450i/Serial/Meter ได้ และ Web 443 connect. แก้ hybrid port routing + regression; full suite `356 passed`, compileall/scoped Ruff ผ่าน. ทำ SQLite backup `KOMI_Report_V5.before-real-setup-20260820-2126.db`, ปิด Lab และเปิด real `app.py` PID `37418`. Worker ตัวเดียวกับ Wizard สแกน `10.244.116.1–254` บน 161 พบ Konica Minolta จริง 13 เครื่อง รวม `.6`, `.8`, `.107` | PASS — LIVE REAL LAN/REAL DB READ + SOURCE REGRESSION; รอ Bom เลือกสูงสุด 3 เครื่องและกด SNMP/Web test | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py`, `~/KOMI Report V5/KOMI_Report_V5.db`, `~/KOMI Report V5/KOMI_Report_V5.before-real-setup-20260820-2126.db` |
| 2026-08-20 21:21 +07 | First-run Database Path + single V4.6 import entry | Step 1 ต้องเห็น/เลือก Path สร้าง Database และมีปุ่มนำเข้าฐานข้อมูลเดิม; Step Device ห้ามมี V4.6 card ซ้ำ; ห้าม overwrite ไฟล์เดิม | เพิ่ม read-only Path + Save chooser + Import existing บน Company card, scroll fallback ที่ 980×620, SQLite backup/integrity gate, atomic `runtime.toml` persistence และ Lab no-write behavior. ย้าย V4.6 import มา Step 1 จุดเดียวและคง boundary เฉพาะ Meter/Usage. Focused `43 passed`, full regression `355 passed`, compileall/scoped Ruff ผ่าน; visual 1120×720 ตรวจ Company และ Device แล้ว | PASS — SOURCE/OFFSCREEN/VISUAL; รอ Bom ตรวจรับ macOS live และ production restart path UAT | `source/database.py`, `source/runtime_config.py`, `source/v5_pages.py`, `source/i18n.py`, `source/tests/test_database.py`, `source/tests/test_runtime_config.py`, `source/tests/test_setup_wizard_v5.py`, `source/tests/test_legacy_history_import.py`, `docs/setup-v51-company-database-path-th.png`, `docs/setup-v51-device-without-v46-card.png` |
| 2026-08-20 21:12 +07 | Wizard modal Dark Mode repair | Advanced/Manual/Credential/Slot dialog ต้องไม่เป็นพื้นดำจนข้อความอ่านไม่ได้ และ English ต้องไม่เหลือข้อความไทย/placeholder ไทย | เพิ่ม `_prepare_wizard_dialog` บังคับ light palette/QSS, input/focus state, apply language และ translate placeholder ให้ popup ทั้ง 4. Regression จับ dialog ทุกตัวผ่าน patched exec แล้วยืนยัน Window `#F4F7FA` และไม่มี Thai glyph ใน English; dark-palette visual ของ Advanced scan ผ่าน. Focused `23 passed`, full regression `352 passed`, compileall/scoped Ruff ผ่าน | PASS — SOURCE/OFFSCREEN/DARK-PALETTE VISUAL; รอ Bom ตรวจรับ macOS live | `source/v5_pages.py`, `source/i18n.py`, `source/tests/test_setup_wizard_v5.py`, `docs/setup-v51-modal-advanced-light.png` |
| 2026-08-20 21:05 +07 | Setup Wizard bilingual completion | สลับ English แล้วข้อความ UI ทั้ง 4 Step ต้องเป็น English จริง; ปุ่ม `ไทย` และข้อมูลบริษัทภาษาไทยเป็นข้อยกเว้นที่ตั้งใจ | เติม static/dynamic translation ของ Company, discovery/status/table, pricing/day selector และ Review. เพิ่ม regression เดิน Step 1→4 แล้วสแกน visible QLabel/button/group/combo/table หา Thai glyph; ได้ 0 รายการทุก Step. Visual English 1120×720 ตรวจครบ 4 หน้า; focused `22 passed`, full regression `351 passed`, compileall/scoped Ruff ผ่าน | PASS — SOURCE/OFFSCREEN/VISUAL; รอ Bom ตรวจรับ macOS live | `source/i18n.py`, `source/tests/test_setup_wizard_v5.py`, `docs/setup-v51-en-step1.png`–`step4.png` |
| 2026-08-20 20:58 +07 | Step 1 language control polish | ตัวเลือกภาษาต้องไม่ใช้ native popup ที่ดูหลุดจาก Wizard, ไม่ชน `1 / 4`, สลับภาษา/จำค่าได้ และปรากฏเฉพาะ Step 1 | แทน `QComboBox` ด้วย exclusive segmented `ไทย / EN`, เพิ่ม hover/checked/focus/accessibility, คง label สั้นไม่ถูก i18n แปลง และทดสอบซ่อน/แสดงเมื่อ Next/Back. Render ไทยและ English ที่ 980×620 ผ่าน; focused `21 passed`, full regression `350 passed`, compileall/scoped Ruff ผ่าน. Impeccable detector เหลือ warning เดิม 4 จุดนอก Setup Wizard | PASS — SOURCE/OFFSCREEN/VISUAL; รอ Bom ตรวจรับบน macOS live | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py`, `docs/setup-v51-language-toggle-th.png`, `docs/setup-v51-language-toggle-en.png` |
| 2026-08-20 20:47 +07 | Safe printer onboarding redesign | ห้ามสแกนก่อนผู้ใช้เข้า Step เครื่องพิมพ์; Quick path เด่น; V4.6 แสดงเมื่อยืนยัน source; ราคา 0 ต้อง defer ชัด; Review ตรวจแก้ทีละส่วนและ UI 980×620 ไม่ซ้อน | ย้าย scan trigger หลัง CTA Step 1, เพิ่ม scope/cancel/progressive fallback, Checkbox + Ready gate, conservative V4.6 schema detection, deferred pricing config, zero-price guard, review sections + Edit/local-external copy, focus/accessibility labels และ named progress rail. Visual 4 หน้าแก้ header/table artifact แล้ว; focused 28 และ full regression `349 passed`; compileall/scoped Ruff ผ่าน. เปิด Setup Lab จาก source ล่าสุด PID `29595`; SNMP `127.0.0.1:1161` และ HTTPS `127.0.0.1:8443` listen | PASS — SOURCE/OFFSCREEN/VISUAL + MAC PROCESS; รอ Bom เดิน flow live และ Windows/Linux native UAT | `source/v5_pages.py`, `source/services/legacy_history_import.py`, `source/i18n.py`, `source/tests/test_setup_wizard_v5.py`, `source/tests/test_legacy_history_import.py`, `docs/setup-v51-safe-step1.png`–`step4.png`, `Open KOMI Setup Lab.command` |
| 2026-08-20 20:10 +07 | Setup Wizard 4-Step macOS Dark Mode repair | Company, Device, Price และ Review ต้องเป็น Light Theme ทั้งหมด; table/scroll/header ห้ามรับสีดำหรือชนกันที่ขนาดขั้นต่ำ | เพิ่ม scoped palette/QSS, explicit Company labels, `AllNonFixedFieldsGrow`, light Device table/Price viewport และ responsive header control group. Dark-palette render ตรวจครบ 4 หน้า; รอบแรก full suite พบ test contract เรื่อง spacing ใน selector 1 จุดและแก้โดยคง contract เดิม จากนั้น full regression `345 passed`, scoped Ruff/compileall ผ่าน. เปิด Setup Lab ใหม่ PID `26941`; SNMP `127.0.0.1:1161` และ HTTPS `127.0.0.1:8443` listen | PASS — 4-PAGE DARK PALETTE/OFFSCREEN + MAC PROCESS; รอ Bom visual acceptance บนหน้าจอจริง | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py`, `docs/setup-v51-dark-check-step1.png`–`step4.png`, `Open KOMI Setup Lab.command` |
| 2026-08-20 19:50 +07 | Mac-first Setup Wizard + cross-platform Lab | Mac ต้องเปิด Lab โดยไม่ใช้ Admin/Firewall, production worker ต้องอ่าน Virtual Printer จริง และ UI 4 ขั้นใช้ code เดียวกับ Windows | เพิ่ม Mac launcher และ OS-specific Lab endpoints; external client อ่าน `KOMI-DEMO-001`, Total `125,430` ผ่าน SNMP `1161` และ Web `8443`; production discovery/test worker เดิน Company → Device → Price → Review ครบ. แก้ Company layout/date/device name จาก visual รอบแรก. Full regression `344 passed`, scoped Ruff/compileall ผ่าน | PASS — MAC PROCESS/REAL PROTOCOL/OFFSCREEN UI; รอ Bom visual acceptance และ Windows native gate ภายหลัง | `Open KOMI Setup Lab.command`, `source/tools/setup_lab.py`, `source/v5_pages.py`, `docs/setup-v51-mac-step1-company.png`, `docs/setup-v51-mac-step2-device.png`, `docs/setup-v51-mac-step3-price.png`, `docs/setup-v51-mac-step4-review.png` |
| 2026-08-20 13:05 +07 | Company Wizard + Virtual Printer Setup Lab | First-run ต้องมี Company/date/version, ตัวอย่าง IP เป็น 192.168.1.x และ Lab ต้องตอบ protocol จริงโดยไม่ inject UI/แก้ DB จริง | เพิ่ม Step 1 Company, one-time onboarding gate, SNMP v2c UDP 161 + Web Connection-compatible HTTPS 443, ephemeral TLS/temp SQLite และ Windows launcher. Real-client test อ่าน Model/Serial/Total และ Web counters ผ่าน; full regression `343 passed`, scoped Ruff และ compileall ผ่าน. Windows VM เปิด Wizard STEP 1/4 จริงแล้ว; การพิสูจน์ Quick Scan → Test → Next รอ Bom อนุญาต Firewall prompt สำหรับ Python | PASS — SOURCE/AUTOMATED; WINDOWS LAN LIVE PENDING FIREWALL APPROVAL | `source/v5_pages.py`, `source/tools/virtual_printer.py`, `source/tools/setup_lab.py`, `START_KOMI_SETUP_LAB.cmd`, `source/tests/test_virtual_printer.py` |
| 2026-08-20 12:35 +07 | Map DEV source เข้า Windows VM | VM ต้องเห็น Share ถาวรจาก Local DEV โดยไม่พึ่ง OneDrive และ Guest Additions พร้อมทำ Auto-mount | เพิ่ม machine mapping `komi-report-v5` → `/Users/wongsakornu-phonram/Projects/dev/komi-report-v5` แบบ readonly/auto-mount ผ่าน VBoxManage ขณะ VM ปิด; Cold Boot สำเร็จ, VM state `running`, Guest Additions 7.2.14 run level 2 และ `VBoxSF.sys` active. Windows File Explorer เปิดไดรฟ์ `X:` และเห็น `source`, `web`, Launchers และเอกสารครบจาก Local DEV. Share เดิมยังไม่ถูกลบ | PASS — HOST MAPPING / VM BOOT / WINDOWS UI | `Window Test for KOMI`, `X:`, `\\VBOXSVR\komi-report-v5`, VirtualBox 7.2.14 |
| 2026-08-20 12:30 +07 | V5.1 design + ย้าย canonical source ออกจาก OneDrive | `~/Projects/dev/komi-report-v5` ต้องเป็น directory จริง, ต้นฉบับเดิมกู้คืนได้, Version เป็น 5.1.0 และ baseline เดิมไม่ถอย | Copy source/docs/web 550 files โดยไม่เอา release/recovery/cache; เก็บ `komi-report-v5.onedrive-link`; checksum dry-run ของไฟล์ที่ไม่แก้ไม่มีความต่าง; launcher doctor จาก path ใหม่แสดง 5.1.0; compileall, shell syntax และ full pytest `340 passed`. Web mirror รอบแรกอ้าง path ผิดจึงยังรายงาน 5.2; แก้เป็น absolute DEV path แล้วตรวจ `5.1.0`, TypeScript และ Next production build ผ่าน. Dashboard sync/build/private deployment version 66 สำเร็จ; browser verification หยุดที่ Sign in with ChatGPT จึงยังไม่อ้างว่าเห็นข้อความ V5.1 บนหน้า live | PASS — DEV PATH/SOURCE/OFFSCREEN/WEB BUILD; Registration/Hosting/Update client และ native upgrade UAT ยังไม่ทำ | `~/Projects/dev/komi-report-v5`, `PROJECT.html`, `source/config.py`, `source/pyproject.toml`, `source/tests/`, `web/` |
| 2026-08-11 11:12 +07 | V4.6 → V5 Slot continuity | ประวัติต้องต่อใน Usage/กราฟตามจุดติดตั้งแม้เปลี่ยน Serial; ห้ามคำนวณ Meter ข้ามเครื่องและห้ามคิด Cost ย้อนหลัง | เพิ่ม immutable legacy interval ตาม Slot, replacement/reset baseline, overlap cutoff ก่อน V5, Slot-preserving Wizard/mapping copy และ Timeline/ตารางรวม D/M/Y. Focused `22 passed`, full `334 passed`, scoped Ruff/compileall ผ่าน; visual 1440×900 เห็น 01/2025→08/2026, เดือน replacement ไม่สร้าง usage และ Cost V4.6 เป็น `—` | PASS — SOURCE/OFFSCREEN; รอสำเนา V4.6 ลูกค้าจริงและ Windows native UAT | `source/services/legacy_history_import.py`, `source/ui/cloud_reports.py`, `source/v5_pages.py`, `source/tests/test_legacy_history_import.py`, `source/tests/test_setup_wizard_v5.py`, `/tmp/komi-v46-slot-timeline.png`, `/tmp/komi-v46-slot-history.png` |
| 2026-08-11 09:47 +07 | First-run Web service, Settings toggle, cross-OS Shortcut และโลโก้ใหม่ | Setup ครั้งแรกเปิด Web service; ผู้ใช้ปิด/เปิดได้ภายหลัง; Shortcut ทุก OS เรียก source กลาง; Sidebar/Web/package ใช้โลโก้ใหม่โดยไม่ล้น | เพิ่ม parent-bound Web worker, status/Local-LAN URL, 2 Shortcut ต่อ OS, PNG/ICO/ICNS/Web icon ชุดเดียว และ V4.6 History tab. Visual render Settings 1100×900 และ Sidebar compact icon 54 px + `KOMI REPORT` ที่ 1440×900 ผ่าน; full `331 passed`; Web build + `tsc --noEmit` ผ่าน. Web Shortcut ตรวจ service เดิมก่อนจึงไม่เปิด server ซ้ำ. macOS `.app` รุ่นแรกถูก System Policy กัน OneDrive จึงแก้ให้ส่ง canonical launcher เข้า Terminal; เปิดจริงสำเร็จ, Desktop PID 66881, Web/API listen 3000/8766 และ HTTP login/health = 200 | PASS — MAC LIVE + SOURCE/VISUAL/WEB BUILD; Windows/Linux native shortcut+service UAT ยังรอ | `source/services/web_service.py`, `source/services/desktop_shortcuts.py`, `source/tools/web_service_worker.py`, `source/tools/run_web_servers.py`, `source/app.py`, `source/v5_pages.py`, `source/logo.png`, `web/app/icon.png`, `/tmp/komi-compact-sidebar-check.png`, `/tmp/komi-web-settings-check.png` |
| 2026-08-10 12:05 +07 | Setup Wizard > Import Database V4.6 | เลือกสำเนา V4.6 แล้ว Preview/Backup/Import เฉพาะ Usage History; ห้ามนำเข้า account, IP, credential, ราคา, settings หรือ Billing Ledger และนำเข้าซ้ำไม่เกิดแถวซ้ำ | เพิ่ม optional card/dialog, source read-only, sanitize usage payload, schema v9 provenance/fingerprint และ atomic import. Synthetic V4.6 ยืนยัน source hash คงเดิม, 2 valid/1 rejected, import 2, รอบสอง duplicate 2, price/device/ledger 0; render Wizard 980×620 และ dialog 860×620 footer อยู่ในจอ. Focused 15 ผ่าน, full `322 passed`, scoped Ruff และ compileall ผ่าน | PASS — SOURCE/OFFSCREEN; รอ Preview ด้วยสำเนา V4.6 จริงและผู้ใช้ตรวจ Desktop UI | `source/services/legacy_history_import.py`, `source/v5_pages.py`, `source/migrations.py`, `source/tests/test_legacy_history_import.py`, `/tmp/komi-v46-wizard-entry.png`, `/tmp/komi-v46-history-import.png` |
| 2026-08-06 13:03 +07 | Report Overview summary cards | การ์ดด้านบนของ Reports ต้องอ่านแบบเดียวกับหน้า Overview แต่ยอดยังยึดช่วงรายงานที่เลือก | แทน 4 KPI แนวตั้งด้วยการ์ด 6 ใบแบบ 3×2: พิมพ์สี/พิมพ์ขาวดำ/ยอดใช้งานรวม/สำเนาสี/สำเนาขาวดำ/ค่าใช้จ่ายรวม; การ์ดประเภทงานแสดง A3/A4 จาก counter จริงและเป็น `—` เมื่อ source ไม่แยก Print/Copy, ไม่เดายอด. Render synthetic 1500px ตรวจ layout; focused `20 passed`, full `307 passed, 1 warning`, scoped Ruff และ compile ผ่าน | PASS — SOURCE/OFFSCREEN; Desktop runtime กับข้อมูลจริงรอ Bom ตรวจ | `source/ui/cloud_reports.py`, `source/tests/test_cloud_reports_ui.py`, `source/tests/test_history_v5_current.py`, `/tmp/komi-report-overview-cards.png` |
| 2026-08-06 11:25 +07 | รวม Rules ไว้ใต้การทำงานอัตโนมัติ | ไม่ต้องสลับแท็บเพื่ออ่าน Rules และต้องเลื่อนต่อจากแผนเวลาได้ | ลด tab เหลือ 4, ย้าย Rules พร้อมคำอธิบายต่อจาก time band และห่อแท็บด้วย vertical scroll; render ตรวจ Rules อยู่ใต้แผนเวลา. Focused `14 passed`, full `307 passed, 1 warning` | PASS — SOURCE/OFFSCREEN; รอ Bom ตรวจ Desktop runtime | `source/v5_pages.py`, `source/tests/test_sync_log_page.py`, `/tmp/komi-sync-technical-below-schedule.png` |
| 2026-08-06 11:18 +07 | Sync schedule 24-hour band | แท็บการทำงานอัตโนมัติต้องเห็นช่วงเวลาปกติ/เริ่มงาน/เลิกงานและ Web throttle โดยไม่เริ่มจากตารางกว้าง | เพิ่ม time band ตาม policy จริง, highlight ช่วงปัจจุบัน, ปุ่มไป Settings และ toggle สำหรับตาราง 7 คอลัมน์; render 1024px เห็น 00:00–24:00 ครบ. Focused `14 passed`, full `307 passed, 1 warning` | PASS — SOURCE/OFFSCREEN; รอ Bom ตรวจ Desktop runtime/Settings และ Scheduler จริง | `source/v5_pages.py`, `source/tests/test_sync_log_page.py`, `/tmp/komi-sync-schedule-band.png` |
| 2026-08-06 10:29 +07 | Sync Log status-first redesign | เปิดหน้าแล้วเห็นสถานะและสิ่งที่ต้องทำรายเครื่องก่อน Log; ประวัติอ่านง่าย, ล้างต้องยืนยัน, ไม่แตะ collector/Billing | เพิ่ม tab สถานะรายเครื่อง, ปุ่มอ่านข้อมูลตอนนี้/ไป Settings, แปล error ที่พบบ่อยเป็นไทย, compact Live Log 4 คอลัมน์ + raw detail/Copy/confirmation; render 1024px เห็น 3 เครื่องเต็มแถว. Regression `307 passed, 1 warning`, compile ผ่าน; scoped Ruff ยังมี baseline เดิม 138 findings และแก้ warning ใหม่แล้ว | PASS — SOURCE/OFFSCREEN; รอ Bom ตรวจ Desktop runtime และ Sync กับเครื่องจริง | `source/v5_pages.py`, `source/app.py`, `source/tests/test_sync_log_page.py`, `/tmp/komi-sync-status-redesign.png` |
| 2026-08-06 08:45 +07 | Sticky header in Usage matrix ตามเครื่อง | เลื่อนตารางลงแล้วหัววัน/เดือน/ปีอยู่บนสุด และเลื่อนซ้าย/ขวาแล้วหัวกลุ่มเครื่องตรงกับข้อมูล โดยไม่ตรึงข้อมูลเครื่อง | แยก header/body เป็น geometry คนละส่วนใน `FrozenLeftTable`, ล็อก header 70 px และ sync horizontal scroll; regression ยืนยัน vertical header position, horizontal sync และคอลัมน์ frozen เป็น period label เท่านั้น. Focused History `18 passed`, focused Cloud Usage `2 passed`, full `304 passed, 1 warning`, compileall ผ่าน | PASS — SOURCE/OFFSCREEN; รอ Bom ลอง Desktop runtime | `source/widgets.py`, `source/tests/test_history_v5_current.py`, `source/tests/test_cloud_reports_ui.py` |
| 2026-08-06 +07 | Usage context controls and grouped periods | ช่วงรายงานอยู่เฉพาะแท็บที่ถูกจำกัดรอบ; Usage ดูประวัติทั้งหมดด้วย D/M/Y, ตารางเต็มพื้นที่ และรวมวัน/เดือน/ปีซ้ำในมุมตามเครื่อง | ย้าย period selector เข้า Overview/Users/Printers (sync กัน 3 ตัว); Usage ไม่มี selector นี้, เพิ่ม D/M/Y ด้านขวาบนและใช้ daily history สำหรับ D, monthly history สำหรับ M/Y. ตาราง Usage fill พื้นที่ tab และใช้ `QTableWidget.setSpan()` รวม period cell ที่ติดกันในตามเครื่อง. Render global QSS ตรวจ M/D และ merged period; scoped Ruff และ full pytest `303 passed, 1 warning` | PASS — SOURCE/OFFSCREEN; Desktop process restarted, รอ Bom ตรวจข้อมูลจริง | `source/ui/cloud_reports.py`, `source/v5_pages.py`, `source/tests/test_cloud_reports_ui.py`, `/tmp/komi-usage-m-filter.png`, `/tmp/komi-usage-m-printer-merged.png`, `/tmp/komi-usage-d-printer-merged.png` |
| 2026-08-06 +07 | Usage tab รายเดือน | เพิ่มมุม Usage ที่อ่านเดือนก่อนแล้วเห็นประเภทการใช้งานรวมทุกเครื่อง หรือแยกรายเครื่อง โดยไม่เปลี่ยน Billing/source | เพิ่ม tab `Usage` พร้อม sub-tabs `ทุกเครื่อง` (เดือน, A3/A4 Color/B&W, Scan, รวม) และ `ตามเครื่อง` (เดือน + เครื่อง + ประเภทการใช้งาน). ใช้ monthly history เดิมทั้งช่วง ไม่สร้าง metric งานพิมพ์ที่ไม่มี source; ตารางปรับสูงตามจำนวนแถวและมีเพดาน 390px. Render synthetic หลายเดือน/สองเครื่องตรวจทั้งสองมุม; scoped Ruff และ full pytest `303 passed, 1 warning` | PASS — SOURCE/OFFSCREEN; Desktop process restarted, รอ Bom ตรวจ data จริง | `source/ui/cloud_reports.py`, `source/v5_pages.py`, `source/tests/test_cloud_reports_ui.py`, `source/tests/test_history_v5_current.py`, `/tmp/komi-usage-monthly-compact.png`, `/tmp/komi-usage-by-printer-compact.png` |
| 2026-08-06 +07 | Reports alternating-row indent | ทุกแถวของตาราง Reports ต้องเริ่ม text edge เดียวกันบน macOS | Reproduce ด้วย global QSS ของแอปแล้วพบเฉพาะ alternate row มี left inset แม้ชื่อใน DB ไม่มี whitespace; ปิด zebra striping เฉพาะตาราง Cloud Reports. Render 3 แถวภายใต้ global QSS แล้ว text ตรงแนวทุกแถว; focused tests `19 passed`, Ruff ผ่าน | PASS — SOURCE/OFFSCREEN; Desktop process restarted เพื่อโหลด patch, รอ Bom มองภาพจริง | `source/ui/cloud_reports.py`, `source/tests/test_cloud_reports_ui.py`, `/tmp/komi-reports-table-final.png` |
| 2026-08-06 +07 | Reports table header/cell edge alignment | หัวคอลัมน์ข้อความและข้อมูลต้องเริ่มที่ขอบเดียวกัน ไม่ดูเยื้องสลับระหว่างแถว | พบ `QHeaderView` มี inset ซ้ายเพิ่มจาก Qt style แม้ cell ถูกจัดแนวแล้ว; กำหนด padding ซ้ายของ header เป็น 1px และ cell เป็น 10px, trim whitespace ของค่าที่นำมาแสดง. Render ตาราง 3 แถวตรวจว่าชื่อเครื่องเริ่มแนวเดียวกับหัวคอลัมน์; focused tests `19 passed`, Ruff ผ่าน | PASS — SOURCE/OFFSCREEN; รอ Bom refresh/restart Desktop เพื่อตรวจหน้าจอจริง | `source/ui/cloud_reports.py`, `source/tests/test_cloud_reports_ui.py`, `/tmp/komi-reports-table-alignment-v2.png` |
| 2026-08-06 +07 | Reports Desktop scroll and visual consistency | Reports ต้องเลื่อนลงได้เมื่อพื้นที่จอไม่พอ, การ์ดขาวไม่มีพื้นเทาหลังข้อความ, และหัว/ข้อมูลตารางจัดแนวตามชนิดคอลัมน์อย่างสม่ำเสมอ | ห่อ `CloudReportsWidget` ด้วย vertical `QScrollArea`, ลดความสูงกราฟ/ตารางและตัด layout stretch ที่ทำให้กล่องใหญ่เกิน, บังคับ QLabel ใน Reports ให้ transparent และกำหนด text column ชิดซ้าย/numeric column ชิดขวาทั้ง header และ cell. Render ที่ viewport 1024×720 ยืนยัน content 966px และ scrollbar มีช่วงเลื่อน 246px; scoped Ruff ผ่าน; full pytest `303 passed, 1 warning` | PASS — SOURCE/OFFSCREEN; รอ Bom ตรวจบนหน้าจอ Desktop และข้อมูลจริง | `source/ui/cloud_reports.py`, `source/v5_pages.py`, `source/tests/test_cloud_reports_ui.py`, `source/tests/test_history_v5_current.py`, `/tmp/komi-reports-scroll.png` |
| 2026-08-06 +07 | Cloud-style Reports Desktop + Web | แทน Report design เดิมด้วย Overview/Users/Printers, ใช้ช่วงเวลาเดียว, แสดงยอดรวมชุดเดียว และ Cross-filter โดยไม่เปลี่ยน Billing logic | เพิ่ม `CloudReportsWidget` สำหรับ Desktop และ Cloud report views สำหรับ Next.js; Overview มี KPI/Timeline/Top, Users และ Printers กดแถวเพื่อกรองกราฟ, Printer มี Meter detail; Web navigation เหลือ Reports 3 หน้าและ System แยกต่างหาก. Synthetic visual 1440×900 ตรวจครบ 3 หน้า; focused `34 passed`, full suite `302 passed, 1 warning`, scoped Ruff ผ่าน และ Next production build ผ่าน | PASS — SOURCE/OFFSCREEN/BUILD; รอ Desktop/Web runtime UAT กับข้อมูลจริงของ Bom | `source/ui/cloud_reports.py`, `source/v5_pages.py`, `source/tests/test_cloud_reports_ui.py`, `web/app/cloud-report-views.tsx`, `web/app/page.tsx`, `web/app/globals.css` |
| 2026-08-05 +07 | Report Center 3 หน้า | รื้อ Reports เดิมให้คล้าย SafeQ จริงและแยกหน้าที่ Usage/Management/Meter โดยไม่สร้างข้อมูลเดา | ซ่อน History workspace เดิมจาก user path และสร้าง Usage report (date range, Summary/Per device/Per user, Advanced, Metric tabs, Table/Trend), Management report (Year/Q1–Q4, 2 trends, Printed pages, Top 5) และ Meter report (First-and-last/Daily, raw counter table, history). Management ไม่ใส่ Simplex/Duplex/Department และไม่แบ่งราคาย่อยเมื่อ source ยังไม่ยืนยัน. เพิ่ม UI regression; full pytest `301 passed`, compileall ผ่าน | PASS — SOURCE/OFFSCREEN; visual/runtime และ live billing acceptance ยังรอ Bom | `source/v5_pages.py`, `source/tests/test_history_v5_current.py` |
| 2026-08-05 +07 | Reports UI YSoft-style | หน้า Reports ต้องเริ่มจากเลือกรายงาน, ค้นหา, เปิด Advanced เมื่อจำเป็น และ Standard ไม่ทำให้ผู้ใช้กังวลกับยอด 2 ก้อน | เพิ่ม `Standard / Per device / Usage & cost / Per user / Trend`, ปุ่ม `Search` และ `Advanced`; Advanced เชื่อมกับรายละเอียด Counter และ granularity ของตารางเดิมจริง. Standard รวมยอด Posted Ledger กับ Daily Cache เป็นยอดปัจจุบันเดียว; รายละเอียดแยกแหล่งข้อมูลคงแสดงเฉพาะเมื่อเปิด Advanced. Tests `37 passed`, compileall ผ่าน | PASS — SOURCE/OFFSCREEN; รอ Bom ตรวจ visual/runtime และยังไม่มี live billing acceptance | `source/v5_pages.py`, `source/tests/test_history_v5_current.py`, `source/tests/test_history_v5_users.py`, `source/tests/test_reporting_facade.py` |
| 2026-08-05 +07 | User-managed Task Schedule | ผู้ใช้ต้องเพิ่ม/ลบช่วงเวลา Web ได้เอง และ Timeline/Background ต้องใช้กฎเดียวกัน | เพิ่ม Settings table สำหรับชื่อช่วง, เวลาเริ่ม/สิ้นสุด, Web throttle, เพิ่ม/ลบ; config `sync_schedule_windows` แบบ JSON มี validation กันเวลาซ้อน; Polling, Desktop Sync Timeline และ Web API อ่าน policy ชุดเดียวกัน; focused `15 passed`, related regression `16 passed`, compileall ผ่าน | PASS — SOURCE/OFFSCREEN; ยังไม่ได้บันทึก Settings ลง runtime DB หรือปล่อยให้ Scheduler ทำงานตามช่วงใหม่บนเครื่องจริง | `source/services/polling.py`, `sync_schedule.py`, `background_polling.py`, `v5_pages.py`, `tests/test_polling.py`, `test_sync_schedule.py`, `test_settings_v5.py` |
| 2026-08-05 +07 | Production hardening foundation (non-security) | ปรับ config/logging/migration/API/worker/UI structure/release guidance โดยไม่เปลี่ยน security exception หรือ Billing invariant | เพิ่ม `runtime_config`, JSON structured logging, migration v8+backup, `ReportReadService`, `/api/v1` alias/pagination/request ID, polling duration/shutdown state และแยก common dialogs; full regression ผ่าน 289 tests, compileall และ Web TypeScript ผ่าน | PASS — FOUNDATION/SOURCE; งาน split page, Ruff baseline/CI และ target-OS UAT ยังเปิดอยู่ | `source/tests/test_runtime_config.py`, `test_migrations.py`, `test_reporting_facade.py`, `test_web_api.py`, `docs/SUPPORT_MATRIX.md`, `docs/RELEASE_RUNBOOK.md` |
| 2026-08-05 +07 | Import paper-tray status | หน้า Import ต้องบอกกระดาษหมดโดยไม่เดาค่าจาก SNMP ที่ไม่ครบ, จัด Tray1/3/5 แถวบนและ Tray2/4 แถวล่างให้ตำแหน่งตรงกัน, Bypass แยกแถว และซ่อนถาดที่ไม่มี โดยไม่กระทบ Billing | เพิ่ม Printer-MIB input tray/alert probe, เก็บเป็น `snmp_paper` แยกจาก Counter; UI map ชื่อ vendor/ดัชนีถาดเป็น Tray1–5/Bypass และสร้างเฉพาะที่รายงานจริงเป็นกล่องสูง 20 px: เทา=ปกติ, ส้ม=หมด, ไม่มีข้อความสถานะในกล่อง และ mouse hover จึงแสดง “กระดาษหมด”; กล่องหมึกสูง 20 px เช่นกัน; ใช้ตาราง 2 คอลัมน์เมื่อไม่มี Tray5 เพื่อให้ `1/3` และ `2/4` ตรงแนว, Bypass เป็นกล่องเต็มแถวของตัวเอง; `295 passed`, compileall และ scoped Ruff ผ่าน | PASS — SOURCE/SYNTHETIC UI; รอทดสอบกับเครื่องจริงที่มีถาดหมดเพื่อยืนยัน MIB ของรุ่น | `source/services/snmp_probe.py`, `source/services/daily_cache.py`, `source/tests/test_snmp_probe_v5.py`, `test_import_v5_layout.py` |
| 2026-08-05 +07 | Overview KPI reflow | หน้า Overview ต้องไม่ขยาย KPI เป็น 2 คอลัมน์ × 3 แถวบน Desktop | เปลี่ยน KPI ทั้ง 6 ใบเป็น 3 คอลัมน์ × 2 แถวที่ความกว้างตั้งแต่ 720 px; responsive ลดเป็น 2/1 คอลัมน์เฉพาะหน้าจอแคบ; full regression `295 passed` | PASS — SOURCE/SYNTHETIC UI; รอ visual UAT บนจอผู้ใช้ | `source/pages.py`, `source/tests/test_overview_v5_ui.py` |
| 2026-08-05 +07 | Overview compact KPI card | Card KPI ต้องใช้พื้นที่เท่าที่จำเป็น โดย title/detail อยู่ชิดกันและตัวเลขรวมอยู่กึ่งกลางด้านขวา | กำหนด card สูง 88 px พร้อมช่องว่างบน/ล่าง 20 px; จัด title และ A3/A4 detail เป็น 2 บรรทัดทางซ้าย, total เป็นแนวตั้งกึ่งกลางทางขวา; label A3/A4 สีเทาและตัวเลขสีดำ; ล็อกลำดับ 3×2 เป็น พิมพ์สี/พิมพ์ขาวดำ/ยอดใช้งานรวม และ สำเนาสี/สำเนาขาวดำ/ค่าใช้จ่ายรวม; เพิ่ม UI regression test; full regression `296 passed`, scoped Ruff และ compileall ผ่าน | PASS — SOURCE/SYNTHETIC UI; รอ visual UAT บนจอผู้ใช้ | `source/pages.py`, `source/tests/test_overview_v5_ui.py` |
| 2026-08-05 +07 | Overview KPI value/background | ตัวเลขค่ารวมต้องเด่นขึ้น, ไม่มีพื้นเทาด้านซ้าย; ระยะซ้าย/ขวา 20 px และบน/ล่าง 5 px | พบ `QWidget` กลุ่มข้อความซ้ายรับพื้น `C_BG` จาก global QSS; กำหนด background เป็น transparent เฉพาะกลุ่มนี้ และคืน font ค่ารวมเป็น `F_2XL` หลัง responsive reflow เพื่อไม่ให้ถูกลดเป็น `F_XL`; ลด card เหลือ 56 px และกำหนด padding ซ้าย/ขวา 20 px, บน/ล่าง 5 px; เพิ่ม test ตรวจสีพื้นและ regression; full regression `296 passed`, compileall และ scoped Ruff ผ่าน | PASS — SOURCE/SYNTHETIC UI; รอ visual UAT บนจอผู้ใช้ | `source/pages.py`, `source/config.py`, `source/tests/test_overview_v5_ui.py` |
| 2026-08-05 +07 | Overview billing-quality banner | ไม่แสดงแถบ “ยอดระหว่างวัน / Hold / ข้อมูลไม่สมบูรณ์” ใต้ KPI บน Overview | นำ widget และ render logic ของ billing-quality banner ออกจาก Overview V2 เท่านั้น; ไม่แก้ Daily Cache, Billing Ledger, Reports หรือ Sync Log; เพิ่ม test ยืนยันว่าไม่มี widget นี้ในหน้า; full regression `295 passed` | PASS — SOURCE/SYNTHETIC UI; รอ visual UAT บนจอผู้ใช้ | `source/pages.py`, `source/tests/test_overview_v5_ui.py` |
| 2026-08-05 +07 | Overview toner background | พื้นหลังในกลุ่มหัวข้อ/แถบ Toner ต้องเป็นสีเดียวกับ printer card ไม่เป็นเทา | พบ `overview_toner_group` รับพื้น `C_BG` จาก global QSS; กำหนด widget เป็น styled transparent และเพิ่ม test ตรวจ pixel จากภาพ printer card; full regression `295 passed`, compileall และ scoped Ruff ผ่าน | PASS — SOURCE/SYNTHETIC UI; รอ visual UAT บนจอผู้ใช้ | `source/pages.py`, `source/config.py`, `source/tests/test_overview_v5_ui.py` |
| 2026-08-05 +07 | Sidebar device label | เมนูหน้าสถานะเครื่องต้องใช้ชื่อ อุปกรณ์/Devices แทน นำเข้า/Import โดยไม่เปลี่ยน workflow นำเข้าไฟล์ | เปลี่ยนเฉพาะ Sidebar label และ i18n ไทย/อังกฤษ; ปุ่ม/กระบวนการ Import file และชื่อ class เดิมคงอยู่; เพิ่ม test sidebar และภาษา; full regression `295 passed`, compileall และ scoped Ruff ผ่าน | PASS — SOURCE/SYNTHETIC UI; รอ visual UAT บนจอผู้ใช้ | `source/app.py`, `source/i18n.py`, `source/tests/test_sidebar_navigation.py`, `source/tests/test_i18n.py` |
| 2026-08-05 +07 | Production Readiness architecture review | ตรวจความพร้อม production ของ Desktop, API, SQLite, Web LAN, security, package และ cross-platform โดยไม่ rewrite source | Python tests `279 passed`, compileall และ Web TypeScript ผ่าน; Ruff พบ 900 findings; พบ Critical คือ default Web LAN credential/session secret และ Device credential plaintext; Windows/macOS/Linux UAT และ live billing acceptance ยังแยกเป็นงานค้าง | NO-GO — internal pilot only after Critical/High closure | `docs/PRODUCTION_READINESS_REVIEW_2026-08-05.md` |
| 2026-08-03 14:54 +07 | External Web Runtime | OneDrive ต้องไม่เก็บ `node_modules` แต่ผู้ใช้ยังเปิด Web Edition จาก Launcher เดิมได้ | ติดตั้ง Next.js/React ที่ `~/Library/Application Support/KOMI Report V5/web-runtime`; Launcher sync เฉพาะ Web source ไป Runtime, ติดตั้ง dependency ครั้งแรก, rebuild เมื่อ source เปลี่ยน และเปิด server จาก Runtime; ลบ `web/node_modules` ใน OneDriveแล้ว ขนาดโปรเจกต์เหลือประมาณ 440 MB | PASS — LOCAL RUNTIME | TypeScript lint และ Next production build ผ่าน; `/login` ตอบ HTTP 200; launcher syntax ผ่าน; release builder `4 passed` |
| 2026-08-03 14:38 +07 | OneDrive project cleanup | ลดไฟล์ซ้ำและ generated output โดยไม่กระทบ source, runtime ปัจจุบัน, เอกสาร QA หรือ Release ZIP ที่ใช้ส่งมอบ | ลบ `source/build`, `source/dist`, Windows test kit รุ่นเก่า, โฟลเดอร์ Windows Portable ที่แตกซ้ำกับ ZIP, Web `.next`, Python/Test/Ruff cache และ metadata ของ macOS; ขนาดโปรเจกต์ลดจากประมาณ 1.4 GB เหลือ 756 MB; เก็บ `.venv`, `web/node_modules`, source package, macOS ZIP และ Windows Portable ZIP; Background process ยังทำงาน | PASS — LOCAL CLEANUP | release builder `4 passed`; `py_compile` ผ่าน; Web TypeScript lint ผ่าน; Windows/macOS ZIP ยังอยู่ครบ |
| 2026-07-30 14:29 +07 | Windows Portable package with bundled Python | เครื่อง Windows ต้องเปิดชุดทดสอบได้โดยไม่ติดตั้ง Python/pip และไม่ใช้อินเทอร์เน็ต โดยไม่มีข้อมูลจริงจากเครื่องพัฒนาติดไป | แพ็ก official CPython 3.11.9 embeddable x64 และ Windows dependencies 24 packages ไว้ใน `runtime`; launcher เรียก `runtime\pythonw.exe` โดยตรงและปิด bytecode cache; ZIP 5,047 entries ผ่าน integrity, AST 54 ไฟล์ผ่าน, PE ตรวจเป็น Windows x86-64, unsafe-content scan ผ่าน, checksum ต้นฉบับ/Manifest/SSD ตรงกัน; full pytest `268 passed`; เปลี่ยนชื่อชุดเก่าที่ต้องติดตั้ง Python เป็น `_OLD_Windows_Requires_Python` | PASS — PORTABLE PACKAGE VERIFIED; รอ WINDOWS RUNTIME UAT | `/Volumes/KINGSTON/KOMI Report V5 Windows Portable - 2026-07-30/`, SHA-256 `d19296ef41c6f0d2554df17ef9cdbe3e484fac69516c91067da0fee3144c3bbd`, `source/tools/package_windows_test_kit.py` |
| 2026-07-30 14:17 +07 | Windows x64 transfer package | SSD ต้องมีชุด Windows ที่เริ่มด้วยข้อมูลใหม่ ติดตั้ง dependency แบบ Offline ได้ และไม่ปะปนกับชุด macOS | สร้าง Source Test Kit สำหรับ Windows 10/11 + Python 3.11 x64 พร้อม `SETUP_AND_START.cmd`, launcher ปกติ/Debug และ wheelhouse 24 ไฟล์; full pytest `268 passed`; Offline dependency dry-run resolve ครบ; AST parse 54 ไฟล์; ZIP 92 entries ผ่าน integrity/unsafe-content scan; checksum ต้นฉบับและ SSD ตรงกัน; ชุด macOS เดิมใน SSD เปลี่ยนชื่อเป็น `_OLD_macOS_DO_NOT_USE` | PASS — PACKAGE VERIFIED; รอ WINDOWS RUNTIME UAT | `/Volumes/KINGSTON/KOMI Report V5 Windows Test - 2026-07-30/`, SHA-256 `8afd3ec7d502e6dcf8aec88c275ea6d59be144571d93c3edcce5c14b7640a413`, `source/tools/package_windows_test_kit.py` |
| 2026-07-30 13:38 +07 | System Overview HTML Slide Deck | ต้องอธิบายโครงสร้างระบบ หลักการทำงาน และหน้าที่ของ Overview, Import, Reports, Sync Log, Settings และ Manual | ปรับเป็น 9 slides ขนาด 1920×1080 พร้อม System architecture, Poll-to-Ledger flow, ภาพ UI จริงของทุกหน้าหลัก, Presenter Notes, Keyboard navigation, Fullscreen และ Print-to-PDF; HyperFrames lint ไม่มี error, validate contrast ผ่านทุกจุด และ inspect ไม่พบ layout issue | PASS — LOCAL HTML; รอ Bom ตรวจรับเนื้อหา | `docs/executive-summary-deck/index.html`, `docs/executive-summary-deck/assets/page-*.png` |
| 2026-07-30 09:20 +07 | macOS transfer package | ชุดทดสอบสำหรับ Mac เครื่องอื่นต้องเปิดจากข้อมูลใหม่ ไม่มี DB/Log/credential เดิม และไม่ทำให้ลายเซ็นแอปเสียหลังเปิด | Full pytest `267 passed`, compileall และ PyInstaller arm64 clean build ผ่าน; เพิ่ม runtime hook ห้ามเขียน bytecode ใน `.app`; archive checksum/unsafe-content scan/codesign ผ่าน; แตก ZIP แล้วเปิดด้วย HOME จำลอง 6 วินาทีได้, สร้าง DB เฉพาะ HOME จำลอง, ไม่มี runtime `.pyc` หรือ embedded DB/Log และ codesign ยังผ่าน; คัดลอกลง KINGSTON แล้วตรวจ checksum ซ้ำผ่าน | PASS — LOCAL APPLE SILICON PACKAGE | `/Volumes/KINGSTON/KOMI Report V5 Test - 2026-07-30/`, SHA-256 `c4a32d1f262d0d659c1e1c10b3cc851dc2f340f9f042b55351dfae271a06707e`, `source/runtime_hooks/no_bytecode.py` |
| 2026-07-27 16:58 +07 | Trends provisional type breakdown | มุมประเภทงานต้องแยก Print/Copy สี/ขาวดำของ Daily Cache ระหว่างวัน โดยยังต่างจาก Ledger | เพิ่ม provisional Print/Copy breakdown จาก counter groups; วาดด้วยสีประเภทเดิมแบบจางและขอบเส้นประ; remainder ที่จัดประเภทไม่ได้แยกต่างหาก; API contract และ Web type รองรับ field ใหม่; focused `27 passed`, full pytest `267 passed`, compileall, Next production build และ UI matrix 9/9 ผ่านโดย network attempts 0 | PASS — SOURCE/SYNTHETIC UI; รอ Desktop Daily Cache จริง | `source/services/monthly_history.py`, `source/v5_pages.py`, `source/web_api.py`, `web/app/dashboard-types.ts`, `source/tests/test_monthly_history.py`, `source/tests/test_history_v5_current.py`, `source/tests/test_web_api.py`, `docs/qa/v5-1440-3dev-reports-trend.png` |
| 2026-07-27 16:48 +07 | Reports Trends redesign | แท็บแนวโน้มต้องเห็นการเปลี่ยนตามรอบบิล ไม่ใช้ Pie ว่าง, ช่วงปีต้องเลือก period-end ถูก และยอดวันนี้ต้องไม่ปะปน Ledger | ใช้ chart surface เดียวกันทุกมุมมอง; รายเครื่อง/ประเภทงานแสดงตามรอบบิล, ผู้ใช้เป็น breakdown ในช่วงที่เลือก; Daily Cache เป็น cap สีเขียวโปร่งเส้นประ `~`; empty state อธิบายสาเหตุ; ปุ่ม/คำเรียกเป็นภาษาใช้งาน; focused `15 passed`, full pytest `267 passed`, compileall และ UI matrix 9/9 ผ่านโดย network attempts 0 | PASS — SOURCE/SYNTHETIC UI; รอ Desktop DB จริง | `source/pages.py`, `source/v5_pages.py`, `source/tests/test_history_v5_current.py`, `source/tests/render_ui_matrix_v5.py`, `docs/qa/v5-1440-3dev-reports-trend.png` |
| 2026-07-27 16:29 +07 | Overview operational redesign | หน้าแรกต้องตอบว่าวันนี้ใช้ไปเท่าไร เครื่องใดมีปัญหา ข้อมูลล่าสุดเมื่อไร และแยกยอดประมาณการจาก Billing Ledger | เปลี่ยนหน้าเป็น KPI ยอดระหว่างวัน, System status, Printer 1–3 แถว, Last sync, Hold/Offline action, ปุ่ม Reports/Sync Log/อ่านทันที; ตัด Pie chart และตาราง User ว่าง, ซ่อนกราฟเมื่อไม่มีข้อมูล; DB/Cache จริงแสดง Online 3/3, `~118 หน้า`, `~187.18 บาท`; full pytest `265 passed`, compileall และ UI matrix 9/9 ผ่านโดย network attempts 0 | PASS — SOURCE/REAL READ-ONLY UI; รอ Bom ตรวจรับ runtime | `source/services/summary_service.py`, `source/pages.py`, `source/config.py`, `source/app.py`, `source/tests/test_summary_service.py`, `source/tests/test_overview_v5_ui.py`, `docs/qa/overview-operational-live.png`, `docs/qa/overview-operational-compact.png` |
| 2026-07-27 16:10 +07 | Reports Daily Cache provisional display | ปิด/เปิดโปรแกรมแล้วต้องเห็นยอดวันนี้จาก persistent Daily Cache โดยไม่ปลอมเป็นยอดยืนยันหรือเขียนเข้า Billing Ledger | แยก confirmed/provisional ใน service/API/Desktop/Web; Cache ปลอดภัยแสดง `~` และค่าใช้จ่ายประมาณการ, Cache ไม่ปลอดภัยคง Hold, ไม่มีราคาแสดง Cost `—`; DB/Cache จริงได้ Sales C450i `+75 / ~81.83`, Sales C750i `+40 / ~98.00`, DMS `+0`; full pytest `263 passed`, compileall, Next production build และ UI matrix 9/9 ผ่านโดย network attempts 0 | PASS — SOURCE/REAL READ-ONLY UI; รอ Bom ตรวจรับ runtime | `source/services/monthly_history.py`, `source/v5_pages.py`, `source/web_api.py`, `web/app/report-views.tsx`, `source/tests/test_monthly_history.py`, `source/tests/test_history_v5_current.py`, `source/tests/test_web_api.py`, `docs/qa/reports-provisional-live.png` |
| 2026-07-23 16:29 +07 | Reports P1/P2 hardening | Trends/Overview/Usage ใช้ Posted Ledger, period แยก start+end, daily source เปลี่ยน/ลบแล้วรายงานไม่เปลี่ยน, reset ไม่ถูกซ่อน, empty/error ไม่แสดง 0 เป็นยอดยืนยัน และ UI 1–3 เครื่องไม่ล้น | เพิ่ม regression สำหรับ Ledger canonical, exact period, reset, empty/error และ Trend; Python `256 passed`, compileall ผ่าน, Next production build ผ่าน, synthetic UI matrix 9/9 viewport/device ผ่านและ network attempts 0; Ruff focused ยังพบ baseline เดิม 561 รายการ | PASS — SOURCE/LOCAL SYNTHETIC; รอ runtime DB/เครื่องจริง | `source/services/monthly_history.py`, `source/v5_pages.py`, `source/web_api.py`, `web/app/page.tsx`, `source/tests/test_monthly_history.py`, `source/tests/test_history_v5_current.py`, `source/tests/test_web_api.py`, `docs/qa/v5-1024-3dev-reports-trend.png` |
| 2026-07-23 16:07 +07 | Independent Reports review | Agent แยกตรวจ correctness และ usability ต้องหาจุดที่ test เดิมไม่ครอบคลุม โดยไม่แตะ DB/เครื่องจริง | พบ P1 หลัก: Trend ใช้ V4 readings, period identity start-only, Reports ขึ้นกับ mutable daily row, empty/error semantics, Trend overlap และ accessibility; correctness 67 tests, UX 11 tests, visual 45/45 render ผ่านแต่ release verdict FAIL | REVIEW FAIL — fix before Production | `.impeccable/critique/2026-07-23T09-07-20Z__source-v5-pages-py-pagehistoryv5.md`, `/tmp/komi-reports-ux-b/` |
| 2026-07-23 15:46 +07 | Main Window maximized | หลังจบ Wizard, เปิดโปรแกรมปกติ หรือเรียกกลับจาก Tray ต้องเข้าสู่หน้าหลักเต็มพื้นที่ใช้งาน โดยไม่ซ่อน title bar | รวมเส้นทางแสดง Main Window ให้เรียก `showMaximized()` เดียวกัน; focused 5 และ full pytest `249 passed`, compileall ผ่าน | PASS — local/offscreen | `source/app.py`, `source/tests/test_tray_lifecycle.py` |
| 2026-07-23 15:22 +07 | Merge Wizard review/start | หน้าเริ่มใช้งานที่ไม่มี decision ใหม่ต้องรวมกับหน้าตรวจสอบ และปุ่มสุดท้ายต้องบันทึกจริง | ลด stack 4→3 หน้า; Step 3 รวมสรุป, Pricelist, ข้อความพร้อมใช้งาน และ CTA `บันทึกและเริ่มใช้งาน`; Back กลับ Step 2 ถูกต้อง; focused 9/full pytest `249 passed`, compileall, HTML JS/structure และ offscreen visual ผ่าน | PASS — local/offscreen | `/tmp/komi-v5-wizard-three-steps.png`, `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py`, `PROJECT.html` |
| 2026-07-23 15:04 +07 | Step 3 Pricelist review | ก่อนเริ่มใช้งานต้องเห็นตัวเลขราคา 4 ประเภทจริง และราคาแยกรายเครื่องต้องไม่ปะปนกัน | เพิ่ม A4/A3 สี/ขาวดำพร้อมหน่วยบาท/หน้า; Shared แสดงหนึ่งบรรทัด, Per-device แสดงตามชื่อเครื่อง; focused 9/full pytest `249 passed`, compileall และ offscreen visual ผ่าน | PASS — local/offscreen | `/tmp/komi-v5-review-with-pricelist.png`, `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-23 15:00 +07 | Step 3 review readability | ส่วนสรุปกลางหน้าต้องอ่านได้ชัดและยังแยกหัวข้อกับรายละเอียดได้ | ขยายหัวข้อย่อยและเนื้อหาสรุปเป็น `F_XL`, เพิ่ม padding 22 px และความสูงขั้นต่ำ 220 px; focused 9/full pytest `249 passed`, compileall และ offscreen visual ผ่าน | PASS — local/offscreen | `/tmp/komi-v5-review-summary-large.png`, `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-23 13:26 +07 | Step 2 mode control + price matrix | จุดเลือกต้องไม่ลอยผิดตำแหน่ง และ Color/B&W ต้องแยกเป็นคอลัมน์ชัดเจน | เปลี่ยน Radio card เป็น exclusive checkable Segment; จัดตาราง `ขนาดกระดาษ / สี (Color) / ขาวดำ (B&W)` พร้อม divider 1 px; focused 9/full pytest `249 passed`, compileall และ offscreen visual ผ่าน | PASS — local/offscreen | `/tmp/komi-v5-price-matrix.png`, `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-23 13:35 +07 | Step 2 compact layout | ฟอร์มต้องไม่ยืดเต็มจอกว้าง ช่องกรอกต้องสัมพันธ์กับข้อมูล และคำอธิบายบนสุดต้องไม่ยุบ | จำกัด content 1,280 px, ราคา 180–260 px, รอบบิล 300 px, mode 480 px และเปลี่ยน intro เป็นข้อความธรรมดา; focused 9/full pytest `249 passed`, compileall และ offscreen visual ผ่าน | PASS — local/offscreen | `/tmp/komi-v5-price-compact.png`, `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-23 13:20 +07 | Wizard typography consistency | Step 2 ต้องใช้ scale เดียวกับ Step 1 ไม่ให้หัวข้อ/คำอธิบาย/control กระโดดคนละขนาด | ตัด `font-size` เฉพาะหน้าออกและยึด `F_2XL/F_XL/F_LG/F_MD` ตาม role; focused 9 และ full pytest `249 passed`, compileall ผ่าน | PASS — local/offscreen | `source/v5_pages.py`, Impeccable typeset review |
| 2026-07-23 13:05 +07 | Step 2 product hierarchy polish | หัวข้อ/คำอธิบาย/control ต้องมีลำดับชัด และไม่ใช้กล่องซ้อนหรือขอบหนา | เพิ่ม `PRODUCT.md`; Step 2 ตัดเลขนำหัวข้อ, outer card borders, coloured headers และ side stripes ออก; รอบถัดไป normalize typography ให้ใช้ token กลาง | PASS — local/offscreen | Impeccable product register, `source/v5_pages.py`, focused 9/full pytest `249 passed`, compileall |
| 2026-07-23 12:10 +07 | Setup Wizard Pricelist readability | ช่องกรอกราคาต้องเป็นตัวเลขล้วน อ่านง่ายขึ้น และวันสิ้นสุดรอบบิลต้องเลือกจากรายการ 1–31 | เพิ่มขนาด font/ช่องกรอกและ spacing; ย้าย `บาท/หน้า` ไว้นอก QDoubleSpinBox; เปลี่ยนวันรอบบิลเป็น Dropdown `วันที่ 1–31 ของเดือน`; focused 9 และ full pytest `249 passed`, compileall ผ่าน | PASS — local/offscreen | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-23 11:45 +07 | Setup Wizard Manual setup + naming | Step 1 ต้องเพิ่ม IP เองได้ 1–3 เครื่อง, ใช้ credential เริ่มต้น, ทดสอบแล้วตั้งชื่อจาก Model แบบย่อก่อนเข้าหน้าราคา | เพิ่ม Manual setup popup, validate IPv4, preselect entries, เปลี่ยนปุ่มเป็น `ทดสอบการเชื่อมต่อ`, และ popup ตั้งชื่อ `KM bizhub …`; focused 8 และ full pytest `248 passed`, compileall ผ่าน | PASS — local/offscreen | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-23 09:00 +07 | Factory reset first-run state | Reset แบบเริ่มตั้งค่าใหม่ต้องล้าง device/cache และบังคับ Wizard ในการเปิดครั้งถัดไป โดย data reset เดิมต้องเก็บ device ไว้ | เพิ่ม `factory_reset_v5`; ลบ state ทั้งหมดอย่างมีเจตนา, สร้าง append-only trigger กลับ, และยืนยัน `setup_complete=False`; focused 12 และ full pytest `246 passed`, compileall ผ่าน | PASS — local/temp DB | `database.py`, `pages.py`, `tests/test_device_config.py` |
| 2026-07-23 02:24 +07 | Final local regression | Billing/Cache/History/Settings/Tray/Web ต้องไม่ทำ regression | Full pytest `244 passed`; compileall ผ่าน; scoped Ruff ของไฟล์ V5 ที่เปลี่ยนผ่าน; Web TypeScript lint และ Next production build ผ่าน | PASS | temp HOME/temp DB, `source/`, `web/` |
| 2026-07-23 02:24 +07 | Calculation red-team | สูตรเงิน รอบบิล การจัดหมวด และการแก้ยอดต้องไม่ mismatch | รอบบิล 5,844 กรณี, classification 166, price rounding 999,901, waste 1,001, manual adjustment 2,003,001 คู่, money fuzz 240 postings/960 components และ Legal/Folio E2E ผ่านทั้งหมด | PASS | `source/tests/test_paper_size_billing.py`, independent Decimal oracle |
| 2026-07-23 02:24 +07 | UI final matrix | 1–3 เครื่องต้องอ่านง่ายที่ 1024/1280/1440 และห้ามยิง network | 9 matrices × 6 pages = 54 checks, network attempts 0; เพิ่มภาพ Billing Audit ที่เห็น lifecycle/filter/table ครบ | PASS | `docs/qa/`, `source/tests/render_ui_matrix_v5.py` |
| 2026-07-23 02:24 +07 | macOS local bundle | `.app` ต้องเปิด Background ได้ กัน process ซ้ำ และไม่แก้ LaunchAgent ระหว่าง smoke | PyInstaller arm64 build, Info.plist/codesign ad-hoc verify, process อยู่หลัง 5 วินาที, second instance ออก 0 และ archive ที่แตกใหม่เปิดได้ | PASS — LOCAL ONLY | `release/KOMI_Report_V5_macOS_arm64_Local.zip`, SHA-256 `8e8747ccbd4149c9b337829f2a6f9c571f64ea8d8bfb325da94f70d2aea7779a` |
| 2026-07-23 02:31 +07 | Extracted source package | Source ZIP ต้องไม่มี DB/secret/build cache และทดสอบได้หลังแตกไฟล์ | 176 files; checksum ผ่าน; ไม่พบ `.env`, DB, key, `.venv`, node_modules, `.next`, dist/build; full pytest จากไฟล์แตกใหม่ `244 passed` | PASS — LOCAL ONLY | `release/KOMI_Report_V5_Dev_Source.zip`, `release/MANIFEST.json` |
| 2026-07-23 01:10 +07 | Overnight local billing hardening | Ledger ต้อง fail-closed, append-only และไม่เปลี่ยนข้อมูลจริงเดิม | เพิ่ม `billing_ledger` additive schema/triggers, immutable posting/hold/reversal/replacement, integer cents, stable idempotency, source-hash, identity/price/category/waste/billing-day snapshots, pending repair และ Local Billing Audit; daily source conflict เปลี่ยนเป็น DO NOTHING | PASS (local temp DB) | `151 passed`, `python3 -m compileall -q .`, `source/tests/test_billing_ledger.py` |
| 2026-07-23 01:10 +07 | Settings/tray/autostart local safety | Settings อ่านง่ายและ Local test ไม่แก้ LaunchAgent โดยอัตโนมัติ | เพิ่ม Fleet/Audit hierarchy, schedule preview จาก work time/interval, QTimeEdit, lock legacy tab, single-instance `QLockFile`; app start ไม่เขียน autostart | PARTIAL PASS | Offscreen component smoke; explicit Settings save ยังเป็น OS action จึงไม่ทดลองจริง |
| 2026-07-23 01:10 +07 | Full quality gate | Regression ต้องไม่พัง | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` = 151 passed; compileall passed | PASS | Ruff ทั้ง repoยังพบ baseline 837 issues (imports/star imports/legacy style), ไม่ได้ auto-format เพื่อลด scope |
| 2026-07-16 13:56 +07 | Inspect V4.6 | พบ parser/services/tests ที่ reuse ได้ | พบ PyQt6, parser profiles, import/summary services และ SQLite tests | PASS | `dev/komi-reader-v4.6/source` |
| 2026-07-16 13:56 +07 | Inspect SNMP Profiler | พบ live-meter boundary และ schema | พบ modular read-only connectors และ `komi.meter.reading.v1` | PASS | `dev/komi-snmp-profiler/src` |
| 2026-07-16 14:14 +07 | Baseline unified suite | V4.6, Profiler และ V5 integration ผ่านร่วมกัน | 71 tests passed | PASS | `pytest -q` |
| 2026-07-16 14:15 +07 | Baseline desktop smoke | MainWindow เปิดและมี Read Meter navigation | PyQt offscreen smoke passed | PASS | temporary SQLite database |
| 2026-07-16 14:18 +07 | Live public Meter UAT | อ่าน C450i แบบ read-only | Device ตอบ `Nack/raise` ก่อน Counter API | BLOCKED | `10.244.116.107` |
| 2026-07-16 16:40 +07 | Requirements review | Workflow ใหม่ต้องครบและไม่เหลือ material ambiguity | สรุป First-run, polling, rollup, usage และ billing design แล้ว | PASS | Current Codex task + `PROJECT.html` |
| 2026-07-16 16:58 +07 | V5 core suite | Device/pricing/cache/polling/billing ต้องไม่ทำให้ regression เดิมพัง | 84 tests passed | PASS | `pytest -q` |
| 2026-07-16 16:59 +07 | Scoped quality gate | V5 modules ใหม่ไม่มี lint/compile error | Ruff และ compileall ผ่าน | PASS | `services`, `v5_pages.py`, `live_meter_page.py` |
| 2026-07-16 17:00 +07 | UI smoke/visual QA | MainWindow ปรับ layout ตาม 2 เครื่องและ Setup render ครบ | Overview/Setup offscreen smoke ผ่าน | PASS | `/tmp/komi-v5-overview-smoke.png`, `/tmp/komi-v5-first-setup.png` |
| 2026-07-16 17:01 +07 | Extracted development package | ZIP/checksum และ tests หลังแตกไฟล์ต้องผ่าน | ZIP 461 KB, checksum OK, 84 tests passed | PASS | `release/KOMI_Report_V5_Dev_Source.zip` |
| 2026-07-16 17:03 +07 | Live Administrator UAT | Test All อ่าน SNMP/Web แบบ read-only | SNMP timeout และ Web URLError | BLOCKED | `10.244.116.107` |
| 2026-07-16 16:34 +07 | Live UAT สองเครื่อง | อ่าน SNMP identity/total และ Web Counter | C450i/C750i Online, Model/Serial/Total และ 96 counters ต่อเครื่อง | PASS | local DB + atomic runtime cache |
| 2026-07-16 16:41 +07 | Overview counter fix | 11 กลุ่มแสดงค่าจาก firmware จริงและ baseline ไม่เป็นขีด | ตัวแปลง total/large ให้ผลตรง cache จริง; 86 tests, Ruff, compileall ผ่าน | PASS | `services/usage.py`, `tests/test_usage.py` |
| 2026-07-16 16:42 +07 | Rebuilt development package | Package หลังแก้ต้องผ่าน regression เมื่อแตก ZIP | 86 tests passed และ checksum สร้างใหม่ | PASS | `release/KOMI_Report_V5_Dev_Source.zip` |
| 2026-07-16 16:52 +07 | Pipeline Log suite | SNMP/Web/RAM/Policy events และ bounded store ต้องไม่ทำ regression | 88 tests passed; scoped Ruff และ compileall ผ่าน | PASS | `services/pipeline_log.py`, `v5_pages.py` |
| 2026-07-16 16:53 +07 | Log UI + live cache smoke | หน้า Log render และอ่านสถานะ Cache/DB ของ 2 เครื่องจริง | UI 3 tabs ผ่าน; SNMP reads 16, Web saves 11, วันนี้ยังพัก Cache | PASS | `/tmp/komi-v5-log-live.png`, `/tmp/komi-v5-log-cache.png` |
| 2026-07-16 16:57 +07 | SNMP Total Meter verification | OID ที่เลือกต้องตรง Web Total และไม่เลือก marker อื่นเมื่อมีหลายแถว | C450i 2,340 และ C750i 440,749 ตรง Web; 90 tests ผ่าน | PASS | `prtMarkerLifeCount.1.1`, `tests/test_snmp_probe_v5.py` |
| 2026-07-16 17:01 +07 | Model-aware OID auto-calibration | เทียบ SNMP candidates กับ Web Total และจำ mapping แยกเครื่อง/รุ่น | Standard + KM Private candidates ตรง Web ทั้ง 2 เครื่อง; mapping persisted; 91 tests ผ่าน | PASS | settings `snmp_total_oid_*`, live cache |
| 2026-07-16 17:36 +07 | Connection Inspector mock smoke | แสดง SNMP/Web/RAM แยก 3 คอลัมน์ได้โดยไม่เชื่อมต่อเครื่องหรือเขียนข้อมูล | DMS mock: SNMP Total 2,340, Web 96 ค่า, RAM 295 fields; sample count คงเดิม; 92 tests ผ่าน | PASS | `/tmp/komi-v5-connection-mock.png`, `tests/test_connection_inspector.py` |
| 2026-07-16 17:42 +07 | V4.6 Overview restoration | หน้าแรกต้องใช้โครง Overview เดิมและไม่มีปุ่มอ่าน Meter ปะปนในรายงาน | `PageOverview` render ครบ 4 Stat cards, 2 Pie charts, 12-month chart และ Top users; 92 tests/compileall ผ่าน | PASS | `/tmp/komi-v5-overview-v46.png`, `app.py`, `pages.py` |
| 2026-07-16 18:04 +07 | Import device-column mock | หน้า Import ต้องปรับเป็น 1–3 คอลัมน์และแยก SNMP/Web/User ตามเครื่อง โดยยังเปิด Import V4.6 ได้ | Mock 2 เครื่อง render ครบ; toggle Mock/legacy ผ่าน; tests ครอบคลุม 1/2/3 เครื่อง; 95 tests ผ่าน | PASS | `/tmp/komi-v5-import-device-columns.png`, `tests/test_import_v5_layout.py` |
| 2026-07-16 20:12 +07 | Import full-value scroll boxes | Web และ User/Account Track ต้องแสดงทุกค่าในกล่อง Scroll อิสระต่อเครื่อง | DMS Web 96 rows/scroll max 92; RAM mock 15 rows/scroll max 10; runtime split tests และ 97 tests ผ่าน | PASS | `/tmp/komi-v5-import-scroll-boxes.png`, `services/runtime_snapshots.py` |
| 2026-07-16 20:19 +07 | Import table alignment | แถว/หัวตาราง/คอลัมน์ตัวเลขของ Web และ RAM ต้องตรงกันทุกเครื่อง | 2 เครื่อง render ด้วย row 32 px และ value 84 px เท่ากัน; 97 tests, Ruff, compileall และ diff check ผ่าน | PASS | `/tmp/komi-v5-import-aligned-tables.png`, `tests/test_import_v5_layout.py` |
| 2026-07-16 20:21 +07 | Alternate-row text origin | ข้อความทุกแถวต้องเริ่มตำแหน่งเดียวกันโดยยังมีสีสลับแถว | เปลี่ยน zebra background เป็นราย cell; ภาพ 2 เครื่องไม่มีแถวเว้นแถวเยื้อง; 97 tests และ quality checks ผ่าน | PASS | `/tmp/komi-v5-import-row-origin-fixed.png`, user screenshot, `tests/test_import_v5_layout.py` |
| 2026-07-16 20:28 +07 | User Total-only Import view | กรอบ User/Auth ต้องเหลือชื่อ User/Account และ Total Counter หนึ่งแถวต่อรายการ | Mock 2 เครื่องแสดง 3 rows × 2 columns; field อื่นยังอยู่ใน RAM; 97 tests, Ruff, compileall และ diff check ผ่าน | PASS | `/tmp/komi-v5-import-user-totals-only.png`, `tests/test_import_v5_layout.py` |
| 2026-07-16 20:36 +07 | History Current Meter V5 | Current Meter ต้องปรับตาม 1–3 เครื่องและใช้ SNMP/Web/Daily Cache โดยไม่กระทบแท็บ History อื่น | Cache จริง 2 เครื่องแสดง 16 rows × 7 columns; adaptive test และ MainWindow smoke ผ่าน; 98 tests ผ่าน | PASS | `/tmp/komi-v5-history-current.png`, `tests/test_history_v5_current.py` |
| 2026-07-16 20:54 +07 | Current Meter comparison default | หน้าเปิดครั้งแรกต้องเห็นเฉพาะค่าปัจจุบัน และเปิด comparison ได้ภายหลัง | Default ซ่อน Opening/Today delta ครบทุกเครื่อง; Checkbox เปิดกลับได้; 98 tests และ quality checks ผ่าน | PASS | `/tmp/komi-v5-history-current-default-only.png`, `tests/test_history_v5_current.py` |
| 2026-07-16 21:01 +07 | History Monthly V5 | รายเดือนต้องรวม Daily Record/Cache ตามรอบบิล รองรับ effective price และปรับ 1–3 เครื่อง | Default แสดง Usage/Cost รายเครื่อง+รวม; detail เปิด A3/A4/Scan; billing range/effective-price tests ผ่าน; 101 tests ผ่าน | PASS | `/tmp/komi-v5-history-monthly.png`, `services/monthly_history.py`, `tests/test_monthly_history.py` |
| 2026-07-16 21:50 +07 | Web Counter Reconciliation | ผลรวมที่ไม่ตรงต้องเตือนพร้อมค่าซ้าย/ขวาและส่วนต่าง โดยไม่รวม SNMP/RAM | Mock mismatch แสดง Needs Review ใน Import/Connection/Log; cache จริง C450i/C750i ผ่านเครื่องละ 16 checks; 106 tests ผ่าน | PASS | `services/reconciliation.py`, `tests/test_reconciliation.py` |
| 2026-07-16 21:55 +07 | History Users mismatch audit | ตรวจ source, monthly delta, identity, reset, estimation และ billing boundary | พบ P1 monthly overwrite: fixture ควรได้ 25 แต่ UI แสดง 15; พบ RAM cost/current-price และ A3/A4 estimation; สถานะ NO-GO | FAIL | `pages.py::_refresh_users`, offscreen fixture |
| 2026-07-16 22:01 +07 | Current Meter source boundary | Total Meter ใน History ต้องใช้ Web Connection แม้ SNMP diagnostic มีค่าอื่น | Fixture Web 1,100 / SNMP 9,999,999 แสดง 1,100; full suite 107 tests, Ruff, compileall ผ่าน | PASS | `v5_pages.py::_current_values`, `tests/test_history_v5_current.py` |
| 2026-07-16 22:20 +07 | History Users V5 repair | แก้ 4 comments: monthly overwrite, RAM billing, A3/A4 estimation และ hidden reset | Delta 25 ถูกต้อง; reset แสดง Needs Review; UI 7 คอลัมน์ไม่มี cost/A3/A4; schema v7 append-only; 115 tests ผ่าน | PASS | `/tmp/komi-v5-history-users-safe.png`, `services/subject_history.py`, `tests/test_history_v5_users.py` |
| 2026-07-16 22:33 +07 | History Users pivot | หนึ่ง User ต้องอยู่หนึ่งแถวและกระจาย Usage ตามเครื่อง 1–3 | alice แสดง 10 / 20 / 30 / รวม 60; bob แสดง — / 5 / — / รวม 5; adaptive columns และ tooltip ผ่าน; 116 tests | PASS | `/tmp/komi-v5-history-users-pivot.png`, `tests/test_history_v5_users.py` |
| 2026-07-20 08:16 +07 | Live SNMP/Web/Cache UAT | เครื่องจริงต้องคืน Total ตรงกันและ Cache รวม delta โดยไม่ใช้ SNMP คิด Usage | DMS 2,340 = 2,340; Sales 440,954 = 440,954; Reconciliation 16/16 ทั้งคู่; Sales delta 205 = A4 Color 161 + A4 B&W 44 | PASS | C450i/C750i read-only response + `runtime-cache/device-1..2/2026-07-20.json` |
| 2026-07-20 08:35 +07 | DMS controlled print + identity repair | งาน 1 หน้าต้องเพิ่ม Device, A4 Color Print และ User DMS อย่างละ 1 พร้อมแสดงชื่อจริง | Total 2,340→2,341; A4 Color Print +1; AuthNo 1 Total 1→2; History UI `DMS | 1 | — | 1`; 118 tests ผ่าน | PASS | Live C450i, RAM export 8×70 UTF-16/TAB, History UI, `test_meter_reader.py` |
| 2026-07-20 08:53 +07 | Sync now + live Toner pipeline | ปุ่มเดียวต้องอ่าน SNMP Toner และ Web Connection พร้อมกันและนำค่าจริงขึ้นหน้า Import | DMS C/Y/M/K = 81/81/80/63%, Web Total 2,341; Sales = 7/44/27/0%, Web Total 440,955; cache เก็บครบทั้ง 2 เครื่อง; full suite 124 tests และ Ruff/compileall ผ่าน | PASS | Printer-MIB `.43.11.1.1.6/.8/.9`, live C450i/C750i, `runtime-cache` |
| 2026-07-20 14:17 +07 | Sync Log + daily task timeline | ต้องดู Log SNMP/Web/RAM และเห็นว่าแต่ละช่วงของวัน Scheduler ทำอะไรตาม Settings จริง | เพิ่ม Sidebar/Import entry, 4 tabs, Timeline 7 ช่วง; 08:00/17:00 เป็น Peak, 12:00 เป็น Normal; MainWindow navigation, full suite 128 tests, Ruff, compileall และ visual smoke ผ่าน | PASS | `/tmp/komi-v5-sync-log.png`, `services/sync_schedule.py`, `tests/test_sync_log_page.py` |
| 2026-07-20 14:23 +07 | Sync Log table alignment | ข้อความทุกแถวต้องเริ่มแนวเดียวกันและตารางไม่ refresh ซ้ำเมื่อไม่มี Event ใหม่ | 14-row visual fixture ตรงแนว; alternating=false, row=34 px, refresh identity คงเดิม; full suite 128 tests, Ruff และ compileall ผ่าน | PASS | User screenshot, `/tmp/komi-v5-sync-log-aligned.png`, `tests/test_sync_log_page.py` |
| 2026-07-20 14:30 +07 | Sync rule diagram | ต้องอธิบายกฎทั้งหมดได้โดยเห็นเส้นทางและเงื่อนไขในภาพเดียว | HTML flowchart render ผ่าน Chrome 1600×2250; PNG แสดง Trigger, success/failure, throttle, source boundary และ daily rollup ครบ | PASS | `docs/sync-rule-flowchart.html`, `docs/sync-rule-flowchart.png` |
| 2026-07-20 14:38 +07 | Data storage overview | ต้องเห็นว่า RAM/Cache/Database เก็บอะไร อยู่รอดหรือไม่ และรายงานใดใช้ตารางใด | HTML/PNG 1600×2200 render ผ่าน; ตรวจชื่อ 5 ตารางหลักตรง schema และแสดง current upsert/immutable gap | PASS | `docs/data-storage-overview.html`, `docs/data-storage-overview.png`, `database.py` |
| 2026-07-20 14:48 +07 | Manual V5 diagrams | Diagram ทั้งสองต้องเปิดจาก Manual และติดไปกับตัวโปรแกรมแบบ Offline | Manual แท็บแรก render ภาพย่อ 2 ใบ; ปุ่ม HTML enabled; PyInstaller datas ครบ 4 assets; full suite 129 tests ผ่าน | PASS | `/tmp/komi-v5-manual-diagrams.png`, `tests/test_manual_diagrams.py`, `app.spec` |
| 2026-07-20 16:29 +07 | Sidebar cleanup | ต้องไม่เห็น Read Meter/Connection และเมนูที่เหลือต้องเปิดตรงหน้า | Sidebar เหลือ Overview, Import, History, Sync Log, Settings, Manual; stack 6 หน้าเท่ากับปุ่ม; focused check, offscreen MainWindow smoke, compile และ scoped Ruff ผ่าน | PASS | `/tmp/komi-v5-sidebar-cleanup.png`, `tests/test_sidebar_navigation.py`, `app.py` |
| 2026-07-20 16:29 +07 | Full regression rerun | ชุดทดสอบเดิมต้องผ่านทั้งหมด | 129 ผ่าน; 1 profiler test ติด environment เพราะ `pysnmp` ที่ติดตั้งไม่มี `bulk_walk_cmd`; ไม่เกี่ยวกับ Sidebar และ focused/UI smoke ผ่าน | ENV BLOCKED | `tests/profiler/test_snmp_client.py::test_cancelled_scan_stops_before_sending_walk` |
| 2026-07-20 16:42 +07 | Live Web Connection Toner cross-check | Web Connection ต้องคืน CMYK จากแหล่งของตัวเองและใช้ตรวจ SNMP ได้ | DMS Web=SNMP C81/Y81/M80/K63; Sales Web=SNMP C7/Y44/M27/K0; ตรง 8/8 ค่า พร้อม LevelState; unauthenticated response ไม่มี Toner | PASS | C450i/C750i `api/AppReqGetCustomData/_111_000_CSM000`, Administrator read-only session |
| 2026-07-21 08:20 +07 | Setup Wizard interactive mockup | แบบต้องครอบคลุม 4 ขั้นและกดเปลี่ยน state ได้โดยยังไม่แตะเครื่อง/DB จริง | HTML มี Auto scan, 2 เครื่องจริงเป็นตัวอย่าง, required SNMP/Web, shared/per-device Cost, Billing 31, Review และ First Sync; HTML parser, JS syntax, required-content และ diff checks ผ่าน; Browser automation ไม่อนุญาตเปิด `file://` จึงรอ Bom ตรวจ visual ในแท็บ | PROTOTYPE PASS | `PROJECT.html` |
| 2026-07-21 08:39 +07 | Per-device Price sections | เลือกแยกราคาแล้วต้องเห็นชุดราคาของแต่ละเครื่อง ไม่ใช่เพียงเครื่องแรก | เพิ่ม DMS, Sales และเครื่องที่ 3 เป็น 3 Price sections พร้อม A4/A3 Color/B&W; shared mode ซ่อน sections เหล่านี้; JS syntax/required IDs/card count และ diff check ผ่าน | PROTOTYPE PASS | `PROJECT.html` |
| 2026-07-21 08:45 +07 | Exclusive Price mode | เลือกราคาเดียวต้องไม่เห็นรายเครื่อง และเลือกแยกราคาต้องไม่เห็นตารางกลาง | เพิ่ม CSS rule สำหรับ `hidden` เพื่อไม่ให้ `.device-price-sections { display:grid }` ทับ attribute; ตรวจ static toggle wiring และ diff ผ่าน | PROTOTYPE PASS | `PROJECT.html` |
| 2026-07-21 08:57 +07 | Cost & Billing ใน Wizard จริง | Shared/Per-device ต้องแสดงทีละโหมด บันทึกราคาถูกเครื่อง และรอบบิล 31 ต้องไม่พังในเดือนสั้น | Qt offscreen ตรวจ Shared persistence ทั้ง 2 เครื่อง, Per-device 2/3 บาทไม่ทับกัน, visibility exclusive และ edge case 31 ก.ค./ก.พ./Leap day ผ่าน; compile/diff ผ่าน | PASS | `source/v5_pages.py`, `source/services/billing_periods.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-21 09:48 +07 | Fresh database startup crash | ฐานข้อมูลว่างต้องเปิด First Setup ได้โดยไม่ crash | Log ระบุ `NoneType.deleteLater` ใน Import refresh; เก็บ widget ไว้ก่อน `setParent()` แล้วค่อย `deleteLater()`; Qt offscreen refresh จาก repository ว่างและ compile/diff ผ่าน; เปิดโปรแกรมใหม่แล้วไม่มี exception เพิ่มใน log | PASS | `source/v5_pages.py`, `source/tests/test_import_v5_layout.py`, `~/KOMI Report V5/logs/app-20260721.log` |
| 2026-07-21 09:55 +07 | Wizard 4 ขั้นจริง | First Setup ต้องไม่เรียกหน้าต่าง 2 ขั้นแบบเดิม และต้องส่งผ่านจากเลือกเครื่องไป Cost/Review/Start ได้ | เพิ่ม NetworkDiscoveryWorker และ 4 pages ใน SetupWizardV5; Qt offscreen เดิน 1→2→3→4 พร้อม 2 เครื่องที่ผ่าน connection, source contract/compile/diff ผ่าน; restart app แล้ว | PASS | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-21 10:09 +07 | Scan table interaction | เลือกเครื่องต้องเป็น Multi-select table ไม่เกิน 3 เครื่อง พร้อม Quick/Advanced scan และ credential link | Qt offscreen ตรวจเพิ่มผลสแกน 3 แถว, badge 3/3, สร้าง DeviceConfig พร้อม default credential และเดินต่อถึง Cost/Review/Start; compile/diff ผ่าน; restart app แล้ว | PASS | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-21 10:20 +07 | Scan table stability and failed-test feedback | เลือกแถวแล้วข้อความต้องไม่เยื้อง, Test อยู่บรรทัด navigation, เครื่องที่ทดสอบไม่ผ่านต้องแดง | กัน Qt clicked(bool) ส่งเข้า Quick scan, CSS lock padding ทั้งสอง state, ย้าย Test button และ render failed rows/status สีแดง; Qt offscreen/compile/diff ผ่าน; restart app แล้ว | PASS | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-21 10:31 +07 | Scan result color priority | แถวที่เลือกต้องไม่ทับผล Test สีเขียว/แดงด้วยสีฟ้า | ปิด Qt selected background แล้วกำหนด background รายผล: ก่อน Test = ฟ้า, ผ่าน = เขียว, ไม่ผ่าน = แดง; Qt offscreen จำลองเลือกแถวและเปลี่ยน fail→pass, compile/diff ผ่าน | PASS | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-21 10:45 +07 | Selected-row colour rendering | สีฟ้า/เขียว/แดงต้องยังเห็นขณะแถว selected | ใช้ `SetupDeviceStatusDelegate` เอา Qt selection overlay ออกจากการ paint แต่คง state เลือกไว้; render table จริงใน Qt offscreen เห็นแถว selected pre-test สีฟ้า, passed สีเขียว, failed สีแดง และปุ่มตั้งค่ารับพื้นหลังเดียวกัน; compile/diff ผ่าน | PASS | `/tmp/komi-v5-setup-color-priority.png`, `source/v5_pages.py` |
| 2026-07-21 10:51 +07 | Deselect after Test | ยกเลิกเลือกแล้วต้องเอา highlight พื้นออก แต่ไม่ซ่อนผล Test | Background ของ pass/fail ใช้เมื่อ selected เท่านั้น; Qt offscreen ตรวจ `clearSelection()` แล้ว badge 0/3, ไม่มี background และข้อความผ่านยังเขียว; compile/diff ผ่าน | PASS | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| 2026-07-21 11:04 +07 | Pricelist visual hierarchy | ราคา 4 ประเภท, โหมดราคา และรอบบิลต้องแยกส่วนและอ่านความสัมพันธ์ได้ทันที | จัดหน้าเป็น 3 numbered sections, radio card, matrix A4/A3 × Color/B&W, billing two-column card และ scroll สำหรับรายเครื่อง; render shared/per-device จริง, 6 Setup Wizard checks, compile/diff ผ่าน | PASS | `/tmp/komi-v5-price-redesign.png`, `/tmp/komi-v5-price-per-device-redesign.png`, `source/v5_pages.py` |
| 2026-07-21 11:32 +07 | Live Large reconciliation diagnosis | อธิบายส่วนต่าง -8 จาก Counter ดิบให้ครบและหาสมการที่ตรง | Admin read-only ได้ 96 counters: Print Large 12,848 + Copy Large 677 = Device Total Large 13,525; Scan/Fax PrintLarge 8 คือก้อนที่กฎเดิมบวกเกิน; Total ปกติ 227,599 + 33,617 + Fax 151 = 261,367 ยังตรง | ROOT CAUSE VERIFIED | Web Connection `AppReqGetCounterInfo/_Total`, `source/services/reconciliation.py`, Data Analytics report `สาเหตุยอด Large ไม่ตรงกัน` |
| 2026-07-22 14:28 +07 | Large reconciliation v2 + audit evidence | ห้ามบวก Scan/Fax ซ้ำใน Total Large และ Daily DB ต้องตรวจย้อนหลังกฎ/ที่มาของ Counter ได้ | Fixture จาก C450i ยืนยัน Print Large 12,848 + Copy Large 677 = 13,525; 5 reconciliation, 2 polling และ 4 daily-cache checks ผ่าน; compileall/diff ผ่าน; `source_json` เก็บ profile/source/billing_safe ครบ | PASS | `source/services/reconciliation.py`, `source/services/daily_cache.py`, `source/tests/test_reconciliation.py`, `source/tests/test_daily_cache.py` |
| 2026-07-22 14:28 +07 | Live regression read | อ่าน C450i ซ้ำหลังแก้เพื่อยืนยัน UI จริง | Web Connection หยุดที่ TLS handshake timeout/URLError ก่อนคืน Counter จึงยังไม่มี live snapshot ใหม่และไม่ได้ยิงซ้ำรัว | LIVE BLOCKED | C450i Administrator read-only attempt |
| 2026-07-22 14:39 +07 | Import Sync connection feedback | Sync ล้มเหลวต้องมีข้อความแดงใต้ปุ่มและจุดสถานะแยกรายเครื่อง โดยข้อความต้องหายเมื่อรอบถัดไปผ่าน | Qt offscreen แสดง DMS online จุดเขียว, Sales offline จุดแดง, ข้อความเครือข่ายและ tooltip error; เปลี่ยนทั้งคู่เป็น online แล้วข้อความหาย; compileall/diff ผ่าน | PASS | `/tmp/komi-v5-sync-offline-status.png`, `source/v5_pages.py`, `source/tests/test_import_v5_layout.py` |
| 2026-07-22 14:56 +07 | History billing-aligned period views | Tab 1/2 ต้องเปลี่ยนชื่อและ Tab 2 ต้องสลับรายวัน/สัปดาห์/เดือน/ไตรมาส/ปีโดยยอดไม่ซ้ำ | ตรวจช่วงรอบบิลวันที่ 25 ครบ 5 แบบ; fixture รายสัปดาห์แบ่ง 26/06–02/07 และ 03/07–09/07 ถูกต้อง; DB จริงเปิดครบ 5 แบบและ Usage รวมคงที่ 4; Qt visual, compileall และ diff check ผ่าน | PASS | `/tmp/komi-v5-history-period-views.png`, `source/services/monthly_history.py`, `source/v5_pages.py` |
| 2026-07-22 15:09 +07 | History merged device headers | รอบบิลต้องครอบ 2 แถวและชื่อเครื่องต้องครอบ Color/B&W/Cost โดยไม่เยื้องเมื่อมี 1–3 เครื่อง | Qt ตรวจ span/ค่า Color+B&W+Cost สำหรับ 1, 2, 3 เครื่อง; detail rows 6 แถว; 3-device horizontal scroll ขยับ header/body พร้อมกัน; visual, compileall และ diff check ผ่าน | PASS | `/tmp/komi-v5-history-merged-header.png`, `/tmp/komi-v5-history-merged-header-3-devices.png`, `source/widgets.py`, `source/v5_pages.py` |
| 2026-07-22 15:54 +07 | History detail columns | เช็ก `รายละเอียดเพิ่มเติม` แล้วต้องเพิ่ม A3/A4/Scan เป็นคอลัมน์ ไม่เพิ่มแถว และย่อข้อความ Checkbox | Qt 1–3 เครื่องสลับ 3→8 คอลัมน์ต่อกลุ่มและกลับเป็น 3 ได้; DB จริงคง 1 แถวแต่คอลัมน์เปลี่ยน 10→25; visual, compileall และ diff check ผ่าน | PASS | `/tmp/komi-v5-history-detail-columns.png`, `source/v5_pages.py`, `source/tests/test_history_v5_current.py` |
| 2026-07-22 16:05 +07 | History tones/scroll/control spacing | ต้องแยกเครื่องด้วยสี หัวกับข้อมูลห้ามเลื่อนแยก และ Checkbox ห้ามซ้อนกัน | 3 เครื่องได้โทนฟ้า/แดง/เขียวต่างกัน; header/body scroll range เท่ากันและ sync สองทาง; หน้าต่าง 1000 px และ DB จริงตรวจ geometry ไม่ทับ; visual, compileall, diff ผ่าน | PASS | `/tmp/komi-v5-history-fixed-tones-scroll-controls.png`, `source/widgets.py`, `source/v5_pages.py` |
| 2026-07-22 16:49 +07 | Reports rename + YSoft benchmark | Sidebar/หัวหน้าต้องเปลี่ยน History เป็น Reports โดยไม่กระทบแท็บและ Billing เดิม | Sidebar เหลือ Reports แทน History; Qt เปิด PageHistoryV5 และยืนยันแท็บค่ามิเตอร์สะสม/ประวัติย้อนหลังเดิม; compileall และ diff check ผ่าน; แอปจริงเหลือ 1 instance | PASS | `source/app.py`, `source/pages.py`, `source/tests/test_sidebar_navigation.py`, YSoft Reports live read-only review |
| 2026-07-22 17:12 +07 | Reports workspace + Overview | เปิด Reports แล้วต้องเห็นภาพรวมรอบบิลก่อน พร้อมยอดจาก source ที่ถูกต้องและไปต่อยังรายเครื่อง/ค่าใช้จ่าย/ผู้ใช้/แนวโน้มได้ | Qt DB จริงแสดง 5 tabs, Usage 7, Color 4, B&W 3, Scan 6, 2 เครื่องและ incomplete warning; fixture ยืนยัน Usage 150, Cost 303.80, User DMS รวมข้ามเครื่อง 10; compileall/diff ผ่าน | PASS | `/tmp/komi-v5-reports-overview-final.png`, `source/v5_pages.py`, `source/tests/test_history_v5_current.py` |
| 2026-07-22 17:24 +07 | Web Edition Phase 1 | ผู้ใช้ใน LAN ต้องเปิด Reports ผ่าน IP ได้ โดย Web ใช้ DB/Billing service เดียวกับ Desktop และไม่เผย credential | FastAPI/Next production build ผ่าน; `192.168.1.103:3000` ตอบ 200 และอ่าน DB จริง Usage 7, Color 4, B&W 3, Scan 6, incomplete 2 วัน; API/History/Subject tests 10 ผ่าน, TypeScript ผ่าน, Desktop 1440×900 และ Mobile 390×844 ไม่มี horizontal overflow; เมนูสลับ state ได้ | PASS | `source/web_api.py`, `web/`, `docs/web-edition-desktop.png`, `docs/web-edition-mobile-viewport.png` |
| 2026-07-22 18:22 +07 | Multi-agent Web Edition QA | Overview Preview, API, source boundary, Launcher และ Responsive ต้องสะท้อนสภาพจริงโดยไม่ยิง Printer/แก้ DB | 3 Agents + direct QA: full Python suite 145 ผ่าน; Backend focused 14 ผ่าน; 6 API endpoints/5 granularities/concurrency/credential boundary/Launcher/LAN ผ่าน; Overview และ console ผ่าน แต่ 6 เมนูยังเป็น Placeholder, Mobile bottom nav เสี่ยงทับท้ายหน้า และ Billing ยังไม่บังคับ `billing_safe` | CONDITIONAL PASS / PRODUCTION NO-GO | `source/web_api.py`, `source/services/monthly_history.py`, `web/app/page.tsx`, Browser DOM/console QA |
| 2026-07-22 18:40 +07 | Web Edition QA closure | ต้องปิดทุก P1/P2 จาก multi-agent QA, ใช้งานทุกเมนู, ป้องกัน LAN access และไม่เปลี่ยน Billing ที่ไม่ปลอดภัยเป็นยอดเงินจริง | `billing_safe=false` ถูกพักออกจาก Usage/Cost ทั้ง Daily DB และ current cache; Login/API loopback/redaction/typed schema ผ่าน; 7 มุมมองใช้ข้อมูลจริง; Python 149 tests, Ruff, TypeScript, Next production build และ concurrent API 160/160 ผ่าน; Browser ตรวจทุกเมนู, Login, Desktop/Mobile 390 px ไม่มี overflow และ console 0 error | PASS — TRUSTED LAN GO | `source/services/monthly_history.py`, `source/web_api.py`, `web/`, `Open KOMI Report Web.command`, Browser runtime QA |
| 2026-07-27 08:10 +07 | macOS 27 System Tray crash guard | Auto-start background app ต้องไม่ abort เมื่อเปิดเมนูจาก Status Item | Crash report ระบุ AppKit abort ใน `NSStatusItem → QMenu`; macOS 27+ จึงไม่สร้าง tray context menu และใช้คลิกไอคอนเพื่อเปิดหน้าหลักแทน; restart LaunchAgent แล้ว process อยู่รอดและเข้า event loop; focused tests 14 passed + compileall ผ่าน | PASS — menu interaction live UAT ยังรอ | `source/app.py`, `tests/test_tray_lifecycle.py`, `~/Library/Logs/DiagnosticReports/Python-2026-07-27-080732.ips` |
| 2026-07-27 09:13 +07 | Reports Overview usability refinement | คงหน้า Overview แบบสรุปยอด แต่ลดข้อมูล Debug, ไม่แสดง 0 เมื่อรอบมี Hold, อ่านสถานะและรายละเอียดค่าใช้จ่ายได้ชัด | ซ่อน source badges/technical period banner; เปลี่ยน Printer และ User / Account; Hold เป็นลิงก์รายละเอียด; User ใช้ RAM `latest_total`; Usage ตัด Scan; Checkbox แสดง Gross/ส่วนลด/Net; full pytest `259 passed`, compileall ผ่าน และ synthetic UI 1–3 เครื่อง 9/9 viewport ผ่านโดย network attempts 0 | PASS — SOURCE/SYNTHETIC; รอ DB จริง | `source/v5_pages.py`, `source/pages.py`, `source/tests/test_history_v5_current.py`, `source/tests/test_history_v5_users.py`, `docs/qa/v5-1024-3dev-reports.png` |
| 2026-07-27 13:58 +07 | Reports current-meter usability refinement | Total Meter ต้องเห็นก่อน, ตาราง 1–3 เครื่องอ่านง่าย และ Checkbox ต้องไม่หายเมื่อไม่เลือก | เปลี่ยนแท็บเป็นค่ามิเตอร์รายเครื่อง; grouped header แยกชื่อเครื่องกับปัจจุบัน/ต้นวัน/+วันนี้; ตัวเลขสีดำและหัวเครื่องใช้สีอ่อน; เพิ่มตัวกรอง Counter ศูนย์ default off; Checkbox มี minimum width และคงอยู่ทุก state; ซ่อนข้อความ source เชิงเทคนิค; full pytest `259 passed` และ synthetic UI 1–3 เครื่อง 9/9 viewport ผ่านโดย network attempts 0 | PASS — SOURCE/SYNTHETIC; รอ DB จริง | `source/v5_pages.py`, `source/widgets.py`, `source/pages.py`, `source/tests/test_history_v5_current.py`, `docs/qa/v5-1024-3dev-reports-devices.png` |
| 2026-07-27 14:13 +07 | Reports current-meter table geometry | ชื่อแถวกับค่าต้องตรงกันเมื่อมี scrollbar, แยกกลุ่มเครื่องชัด, +วันนี้เป็นสีเขียว และขอบตารางไม่โค้งขาดตอน | บังคับ row height ฝั่ง frozen/value ให้เท่ากันทุกครั้งที่เติมข้อมูล; เพิ่ม regression เลื่อน scrollbar แล้วตรวจ rowAt; วาดเส้นแบ่งเครื่อง 2 px; +วันนี้ใช้สีเขียว; table/header/item ใช้มุม 0 px; focused `12 passed` และ synthetic UI 1–3 เครื่อง 9/9 viewport ผ่านโดย network attempts 0 | PASS — SOURCE/SYNTHETIC; รอ DB จริง | `source/widgets.py`, `source/v5_pages.py`, `source/tests/test_history_v5_current.py`, `source/tests/render_ui_matrix_v5.py`, `docs/qa/v5-1440-3dev-reports-devices.png` |
| 2026-07-27 15:43 +07 | Reports checkbox visibility on macOS | Checkbox ต้องเห็นกรอบเมื่อไม่เลือกและเห็นเครื่องหมายถูกเมื่อเลือก ไม่ขึ้นกับ native Qt/macOS style | เพิ่ม `VisibleCheckBox` วาดกรอบ/พื้น/เครื่องหมายถูกเองและใช้กับรายละเอียดวันนี้กับตัวกรอง Counter ศูนย์; ภาพ 3 เครื่องเห็น checked/unchecked พร้อมกัน; full pytest `259 passed`, compileall และ synthetic UI 1–3 เครื่อง 9/9 viewport ผ่านโดย network attempts 0 | PASS — SOURCE/SYNTHETIC; รอ Desktop DB จริง | `source/widgets.py`, `source/v5_pages.py`, `source/tests/test_history_v5_current.py`, `docs/qa/v5-1440-3dev-reports-devices.png` |
| 2026-08-04 16:58 +07 | Overview Printer Status responsive/UI clarity | Card สถานะต้องไม่ตัดชื่อรุ่นหรือ Toner, ต้องบอกสถานะด้วยข้อความ, และ KPI ต้องไม่ล้นที่หน้าต่างแคบ | ลดชื่อเครื่องเป็นระดับ section, จัด Serial/IP ใต้ชื่อ, แสดง `Online/ไม่เชื่อมต่อ/ข้อมูลล่าช้า/กำลัง Sync/รอตรวจสอบ` พร้อมคำอธิบาย, รวม Toner C/Y/M/K ในกลุ่มยืดได้; KPI ใช้ 2 คอลัมน์ก่อนจอ ultra-wide; full pytest `279 passed`, compileall ผ่าน และ synthetic UI matrix 1–3 เครื่อง × 1024/1280/1440 ผ่าน 9/9 โดย network attempts 0 | PASS — SOURCE/SYNTHETIC; แอป Desktop ถูกรีสตาร์ตก่อนตรวจภาพจริง | `source/pages.py`, `source/tests/test_overview_v5_ui.py`, `source/tests/render_ui_matrix_v5.py`, `docs/qa/v5-1024-3dev-overview.png` |

## Web UI hardening and Desktop parity — 2026-08-06

### Progress

- [x] ทำให้ Web timeline ใช้ช่วงรายงานเดียวกับ KPI และตารางจริง
- [x] ทำให้การเลือก Printer กรองกราฟและ Meter detail ตามข้อความบน Web และตามความหมายเดียวกับ Desktop
- [x] เอาปุ่ม Widget menu ที่ยังทำงานไม่ได้ออก, อธิบาย empty state ของ RAM, และขยาย mobile navigation target เป็น 74 × 44 px
- [x] ไม่แสดง access code บน Login/README หรือทุกครั้งที่เปิด launcher; ค่าเดิมยังทำงานได้และจะแสดงเฉพาะ local first-run setup
- [x] เพิ่ม favicon เพื่อไม่ให้ browser console มี 404
- [x] ตรวจ API, Desktop Cloud Reports regression, Next build และ browser flow จริง

### จุดผิดพลาดที่จับได้และผลแก้

- **รอบรายงานไม่ตรงกัน:** Web ส่งช่วงวันที่ให้ Overview/Users แต่ History ไม่ได้รับช่วงเดียวกัน จึงเกิด KPI ของ ก.ค. แต่กราฟของ ส.ค. แก้ API `/api/reports/history` ให้รับ `period_start/period_end` และ Web ขอข้อมูลรายวันในช่วงเดียวกัน. มี regression test ครอบทั้ง period และ device identity.
- **ข้อความ Printer filter เกินจริง:** Web บอกว่ากรอง Widget ทั้งหน้า แต่จริง ๆ Desktop ออกแบบให้กรองกราฟและ Meter detail. Web จึงเปลี่ยนข้อความให้ตรง Desktop และเพิ่ม API device filter เพื่อให้ timeline เปลี่ยนตามเครื่องจริง.
- **Mobile tap target เล็ก:** grid กว้างแต่ปุ่มมีเฉพาะความกว้าง icon. กำหนด button เต็ม cell 74 × 44 px ที่ viewport 390 px.
- **UI ที่เหมือนทำงานแต่ไม่ทำงาน:** ปุ่ม `•••` ไม่มี action จึงนำออกจนกว่าจะมี Export/Widget option จริง.

### ขอบเขตที่ต่างจาก Desktop โดยตั้งใจ (ไม่ใช่ข้อมูลผิด)

- Desktop Cloud Reports มีแท็บ `Usage`, date-range/granularity, Usage matrix ตามเครื่อง และ Export Excel; Web เป็น LAN read-only viewer จึงมี Overview, Users, Printers, Sync Status และ Settings เท่านั้น.
- Desktop เปิด Billing Audit/แก้ Settings ใน local app; Web แสดง Settings read-only และไม่มี Billing Audit เพื่อไม่เปิด workflow ที่แก้/ตรวจหลักฐานเชิงลึกผ่าน LAN.
- ทั้งสองใช้ `ReportReadService`, usage history, subject history และ Billing source เดียวกัน; User/Account เป็นข้อมูลวิเคราะห์ ไม่ถูกนำไปคิดค่าใช้จ่าย.

### Test Log — 2026-08-06 19:36 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| API period/device history filter | timeline ต้องรับเฉพาะรอบและ Printer ที่เลือก | เพิ่ม test และ `tests/test_web_api.py tests/test_cloud_reports_ui.py` ผ่าน 14 tests | PASS | `source/web_api.py`, `source/tests/test_web_api.py` |
| Desktop/API regression | Web API change ต้องไม่กระทบ Desktop Reports/Billing tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` ผ่าน 308 tests, 1 third-party deprecation warning | PASS | `source/tests/` |
| Web production build | TypeScript/Next build ต้องผ่านและ runtime sync source ล่าสุด | Launcher build ผ่าน; route `/icon.svg` ถูกสร้าง | PASS | `Open KOMI Report Web.command`, `web/` |
| Browser report flow | เปลี่ยน period ต้องเปลี่ยน KPI/timeline; เลือก Printer ต้องเรียก device-scoped history | API 200 พร้อม `period_start/end` และ `device_identity`; timeline เปลี่ยนตาม filter; console 0 error | PASS — local live API/browser | `web/app/page.tsx`, `web/app/cloud-report-views.tsx` |
| Mobile + Login | tap target ต้องไม่น้อยกว่า 44 px และ Login ห้ามเผย access code | 390 px: ปุ่มละ 74 × 44 px; Login แสดงข้อความติดต่อผู้ดูแล | PASS — browser | `web/app/globals.css`, `web/app/login/page.tsx` |
| Knowledge learning capture | ส่งบทเรียนที่มีหลักฐานผ่าน API | request แรกใช้ field ผิด จึงตอบ `400 ปัญหาว่าง`; ตรวจ contract แล้วส่ง `input/reply` สำเร็จและ promoted เป็น wiki learning | PASS after repair | `POST /api/knowledge/learnings/observe` |

## OneDrive canonical source reconciliation และ launcher 3 OS — 2026-08-09

### ผลลัพธ์

- กู้ source รุ่น 2026-08-05–07 จาก OneDrive conflict copy แล้ว promote กลับเป็นชื่อ canonical ตามลำดับ dependency
- เก็บ recovery สองชั้นไว้ใต้ `_recovery/2026-08-09-onedrive-live-reconcile/`; ชุด v2 ตรวจ ZIP, SHA-256,
  37 canonical/candidate pairs และยืนยันไม่มีไฟล์ 0 byte ก่อน promote
- ย้าย authored conflict ต้นฉบับ 37 ไฟล์เข้า recovery quarantine โดยไม่ลบ; test discovery ใต้ `source/tests/` เหลือชื่อ canonical
- แก้ nested f-string ใน `pages.py` ให้ parse บน Python 3.11 ซึ่งเป็น baseline เดียวกับ Windows runtime เดิม
- เติม `httpx2` ใน dev dependency ตาม contract ของ Starlette TestClient รุ่นที่ lockfile resolve
- เพิ่ม launcher ระดับ root สำหรับ macOS, Windows และ Linux ทุกตัว resolve project root จากตำแหน่ง launcher แล้วเรียก
  `source/app.py` โดยตรง; runtime/dependency อยู่ local ต่อ OS และไม่เรียก source ใน `release/`
- เพิ่ม `source/tools/launch_doctor.py` เพื่อแสดง canonical path, version และ Source ID ที่เปรียบเทียบข้ามเครื่องได้
- เพิ่ม `README.md` และ `docs/FILE_AND_FOLDER_GUIDE.md` อธิบายโฟลเดอร์/ไฟล์, Frontend/Backend, lifecycle และ cleanup policy
- เพิ่ม Web launcher สำหรับ macOS/Windows/Linux; Web source อยู่ใน OneDrive แต่ build, `node_modules` และ `.env.local`
  อยู่ local ต่อเครื่อง รวมถึงย้าย credential เดิมออกจาก `web/.env.local` แบบ recoverable
- Windows 11 ARM VM ใช้ VirtualBox Shared Folder `\\vboxsvr\KOMI_SOURCE` แทน OneDrive และเปิด source ชุดเดียวกับ Mac;
  Guest Additions 7.2.14, Python runtime local 3.11.15 และ Node.js ARM64 runtime local

### Test Log — 2026-08-09

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Recovery v2 integrity | rollback/candidate ต้องอ่านได้และห้ามมีไฟล์ 0 byte | 37 pairs, ZIP `681,462` bytes, `unzip -t` ผ่าน, SHA-256 `08ee58ff4e3a5dfe4479e0f28e28d3eb27ca26520dd09e3f9ddd638c96b53f2b` | PASS | `_recovery/2026-08-09-onedrive-live-reconcile/v2-pre-promotion/` |
| Python 3.11 compatibility | source canonical ทุกไฟล์ต้อง compile บน baseline | ตรวจ 139 Python files, error 0 | PASS | local Python 3.11.15 runtime |
| Reconciled candidate suite | source ใหม่ต้องผ่านก่อน promote | 312 tests ผ่านบน candidate overlay | PASS | `_reconcile/candidate-overlay/source`, `pytest -q` |
| Canonical suite หลัง launcher/Web/shutdown hardening | source กลางต้องผ่าน regression หลังเพิ่ม launcher และ local runtime | 319 tests ผ่านใน 30.91s; compileall และ shell syntax macOS/Linux ผ่าน | PASS | `source/tests/`, `launch_doctor.py` |
| Shared-source launcher contract | launcher ทุก OS ต้องชี้ source กลางและไม่ชี้ `.venv`/`release` | contract tests 2/2 ผ่าน | PASS — static cross-platform | `tests/test_shared_source_launchers.py` |
| macOS launcher doctor | ต้องสร้าง runtime นอก OneDriveและอ่าน canonical source | runtime Python 3.11.15 สร้างใน Application Support, doctor ผ่านและ Source ID ตรง | PASS | `Open KOMI Report V5.command doctor` |
| macOS Desktop smoke | launcher ต้องเข้า Qt event loop จาก canonical app.py | process ใช้ local runtime + canonical `source/app.py`, import ผ่านและเข้า event loop; ปิดหลัง smoke | PASS — local macOS | `Open KOMI Report V5.command desktop` |
| OneDrive propagation | source/workbook/launcher หลักต้อง upload ก่อนสลับไปเครื่องอื่น | ตรวจ key files 13 รายการเป็น `isUploaded=1` และ conflict นอก `_recovery` เท่ากับ 0 | PASS — cloud file-provider state | `fileproviderctl evaluate` |
| Windows Desktop launcher | ต้องรองรับ UNC Shared Folder, สร้าง runtime ใน LocalAppData และเปิด UI จริง | Windows 11 ARM VM เปิด Setup UI จาก `\\vboxsvr\KOMI_SOURCE`; Python 3.11.15; Desktop Source ID `0b883062d8db692f30c550c09c045092f7a5a8dd69ad73a1d7765c2dc6d6faac` ตรง Mac | PASS — WINDOWS ARM VM / SHARED FOLDER | `START_KOMI_REPORT.cmd`, VirtualBox Guest Additions 7.2.14 |
| Setup shutdown ระหว่าง scan | ปิด Wizard ระหว่าง Quick scan ต้องไม่ทำลาย QThread/worker | UAT รอบแรกพบ `QThread: Destroyed while thread is still running`; เพิ่ม interruption/cancel/wait แล้วทดสอบซ้ำ ปิดกลับ prompt โดยไม่มี traceback | PASS AFTER FIX | `source/v5_pages.py`, `source/tests/test_setup_wizard_v5.py` |
| Web local runtime + credential | source อยู่ OneDrive แต่ build/dependency/secret ห้าม sync | Web source ถูก mirror ไป Application Support/LocalAppData; legacy env อยู่ recovery; `web/.env.local` ไม่มี; test credential/runtime/launcher ผ่าน | PASS | `source/tools/init_web_access.py`, `prepare_web_runtime.py`, `run_web_servers.py` |
| Windows Web launcher | ต้อง build/start/login จาก UNC source เดียวกับ Mac | Turbopack ใช้ไม่ได้บน win32/arm64 จึงกำหนด Webpack; build ผ่านด้วย WASM fallback, Login/Overview ผ่าน, API หลักตอบ 200; Web Source ID `44478e84700d0a169e282235cee492e00cfab015c3f18bf041e40799b68c8e4b` ตรง Mac | PASS — WINDOWS ARM VM / LOCALHOST | `START_KOMI_REPORT_WEB.cmd`, `web/package.json` |
| Web dependency audit | dependency ต้องไม่มี risk ที่ถูกซ่อน | `npm audit` รายงาน 4 high vulnerabilities; ยังไม่ auto-fix เพราะต้องทดสอบ compatibility ก่อน | OPEN — TRUSTED LAN ONLY | local Web runtime `npm ci` |
| Linux launcher | ต้องสร้าง XDG runtime และเปิด PyQt6 ได้ | shell syntax และ contract พร้อม แต่ยังไม่รันบน Linux จริง | PENDING NATIVE UAT | `Open KOMI Report V5 Linux.sh` |
| Windows UAT learning capture | ส่งวิธีแก้ shutdown/ARM Web build พร้อมหลักฐานเข้า local knowledge API | API ตอบ `observed=true` แต่ `verified=false, promoted=false`; เก็บเป็น candidate ไม่อ้างว่าเป็นความรู้ถาวร | OBSERVED / NOT PROMOTED | signature `03d873828ea7c006` |
| Knowledge learning capture | ส่งวิธีแก้ที่มี objective evidence เข้า local knowledge API | API ตอบ 200 แต่คืน `observed=false, verified=false, promoted=false`; ไม่สร้างหลักฐานแทนเอง | NOT CAPTURED | `POST /api/knowledge/learnings/observe` |

## Production readiness stabilization — 2026-08-11

### ผลลัพธ์

- Database startup ปฏิเสธ schema จากรุ่นที่ใหม่กว่าโดยไม่ downgrade/เขียนทับ, ตรวจ schema drift และ rollback DDL ทั้ง transaction เมื่อ migration ล้มเหลว
- V4.6 database preview/import สร้าง SQLite-consistent snapshot ก่อนอ่านและ hash จึงรวม committed WAL โดยไม่แตะ source จริง
- Web กัน stale async Printer result, รองรับ keyboard/focus/ARIA, reset scroll เมื่อเปลี่ยนหน้า, Login network error กู้ state กลับได้ และถอน retired `status.css` ออกจาก build graph
- Desktop Overview คำนวณ responsive columns จากความกว้าง page จริง และลด KPI padding เพื่อไม่ตัดข้อมูลที่ 1024 px
- Windows portable รวม `i18n`, migrations, observability, runtime config, UI consistency และ `ui/`; build test smoke-import `app`/`web_api` และ dependency ถูกล็อกแยกสำหรับ Windows x64 + Python 3.11 พร้อม hashes
- Source ID ครอบคลุม runtime/services/ui/tools/Web authored source; generated Next files และ retired CSS ไม่ถูกนับเป็น source
- ย้าย generated `web/node_modules` ออกจาก OneDrive ไป Trash และเก็บ `.next` ที่ค้างไว้ใน recovery; Web runtime ที่ใช้งานยังอยู่ OS-local ครบ
- กู้ OneDrive `dataless` canonical Web files จาก OS-local mirror ที่ build ผ่านและเก็บ placeholder เดิมแบบ non-destructive; Manual ใช้ PNG แทนเมื่อ HTML ยังเป็น placeholder เพื่อไม่ให้ Qt ค้าง

### Test Log — 2026-08-11

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Full Python regression | การแก้ DB/UI/package ต้องไม่ทำให้ workflow เดิมถอยหลัง | `339 passed`; targeted release/launcher หลัง OneDrive repair `8 passed`; compileall และ scoped Ruff ผ่าน | PASS | `source/tests/` |
| Database migration safety | future schema ต้องคงข้อมูล/version เดิม; failure ต้อง rollback DDL | regression ยืนยัน schema 99/data ไม่เปลี่ยน และ index/version กลับสภาพเดิมเมื่อ migration fail | PASS — synthetic DB | `source/database.py`, `source/migrations.py` |
| V4.6 WAL provenance | preview/hash ต้องเห็น committed row ใน WAL และเปลี่ยนเมื่อ source เปลี่ยน | snapshot preview เห็น row และ fingerprint เปลี่ยนตรงตาม committed content | PASS — synthetic WAL | `source/services/legacy_history_import.py` |
| Desktop visual matrix | Overview/Reports ต้องไม่ clip ที่ 1–3 เครื่องและ 1024/1280/1440 | 9/9 viewports ผ่าน, network attempts 0 | PASS — synthetic/offscreen | `/tmp/komi-ui-qa-after/` |
| Web production/browser | TypeScript/build, Printer race/keyboard, mobile scroll/overflow, Login failure ต้องผ่าน | OS-local `npm run lint` + Next production build ผ่าน; browser desktop/mobile และ network failure มี console error 0 | PASS — synthetic DB/local runtime | `web/`, local Web runtime |
| Release artifact | source archive ต้องไม่มี runtime data/secret/generated dependency | ZIP/manifest/checksum ผ่าน; จำนวนไฟล์และ SHA-256 บันทึกจาก artifact สุดท้ายใน manifest โดยตรง | PASS — local-only dev source | `release/KOMI_Report_V5_Dev_Source.zip`, `release/MANIFEST.json` |
| Windows x64 portable artifact | package ต้องรวม CPython/dependency/source ครบ ไม่มี DB/log/credential และทำซ้ำได้ | CPython 3.11.9 x64, hashed target lock, 25 wheels, 5,101 files, ZIP integrity ผ่าน; ยังรอเปิดจริงบน native Windows x64 | PASS BUILD / PENDING NATIVE UAT | `release/windows-portable/`, `source/requirements-windows-x64.lock.txt` |
| Live billing readiness | ต้องมี posting จากวันที่ source ครบก่อน customer acceptance | read-only DB: schema 9, integrity `ok`, daily records 24, ledger `hold` 24 (`incomplete_day` 14, `missing_web_success` 10), posting 0, legacy import 0 | OPEN — รอ live device/billing proof | OS-local active DB |
| Cross-platform acceptance | native Windows x64, Linux และ signed/notarized macOS ต้องรัน Source ID เดียวกัน | source/launcher/static package contract ผ่าน; native acceptance ยังไม่ครบ | PENDING NATIVE UAT | `docs/SUPPORT_MATRIX.md`, launch doctor |
| OneDrive source residency | canonical source ต้องอ่านได้โดยไม่ timeout และ generated dependency ต้องอยู่ OS-local | กู้ essential files จน dataless scan เหลือเฉพาะ excluded historical/generated assets; `Always Keep on This Device` ถูกเรียกผ่าน Finder แต่ `isKeepDownloaded=0` ยังไม่ยืนยัน pin | PASS RECOVERY / PENDING ONEDRIVE PIN | canonical source + `_recovery/2026-08-11-dataless-web/` |
| Security Critical | เว้นจากรอบแก้ตามคำสั่ง Bom | ไม่มีการ rotate/purge/permission/encryption/dependency security fix | EXCEPTION — unchanged | audit 2026-08-11 |

## Checkpoint — 2026-07-16 17:37 +07

- แอปถูกเปิดใหม่ด้วยหน้า Sidebar `Connection` และ Mock mode เป็นค่าเริ่มต้น
- Mock data ใช้ Daily Cache ล่าสุดแบบ read-only; ไม่ยิง SNMP/Web และไม่เขียน Cache/Database
- DMS mock แสดง SNMP Total `2,340`, Web `96` ค่า และ RAM `295` fields
- Source state ผ่าน `92 tests`, scoped Ruff และ compileall; Live UAT รอเมื่อกลับเข้าเครือข่าย
- Overview ใช้ layout เดิมของ V4.6 แล้ว; งานออกแบบรับข้อมูลรอบถัดไปย้ายไปหน้า Import
- Import Mock แสดง 2 คอลัมน์ตามเครื่องที่ตั้งค่า; Web 96 ค่าและ RAM 15 ค่าอยู่ในกล่อง Scroll แยกกัน
- งานค้างเมื่อกลับมา: ทดสอบเครื่องรุ่นอื่นที่ candidate OID ต่างออกไป, ตรวจการยกเลิก mapping เมื่อ Model/ค่าเปลี่ยน,
  ทดสอบ Usage delta/Tray/Auto-start และ rebuild `release/KOMI_Report_V5_Dev_Source.zip` พร้อม publish Dashboard

## macOS Wizard crash, window และ cancellation stabilization — 2026-08-20 22:18 +07

### ผลลัพธ์

- ยืนยัน crash จริงจาก macOS DiagnosticReports เป็น `EXC_BREAKPOINT / SIGTRAP` ใน
  `NSAccessibility ... accessibilityHitTest` ขณะใช้ PyQt 6.7.1 / Qt 6.7.1 บน macOS 27.0
- เปลี่ยน Setup Wizard และ child dialogs จาก nested `QDialog.exec()` เป็น asynchronous
  `QDialog.open()` เพื่อให้ใช้ event loop หลักเพียงชั้นเดียว
- ยกระดับ dependency authority ทั้ง `pyproject.toml`, `requirements.txt`, `uv.lock` และ lock สำหรับ
  Windows x64 จาก PyQt 6.7 เป็น PyQt 6.11.0 / Qt 6.11.1; launcher macOS sync runtime ใหม่อัตโนมัติ
- เปิด Customer First Run UAT ผ่าน `launchctl` เพื่อไม่ผูกอายุ process กับ terminal และคงฐานข้อมูลลูกค้าทดลองแยก
- แยก First-run Wizard ออกจาก maximized MainWindow เพื่อไม่ให้ macOS แสดงเป็น sheet ซ้อนหน้าต่างเต็มจอ;
  จำกัดขนาดเริ่มต้นไม่เกิน 90% ของ available screen และจัดกึ่งกลาง
- เพิ่ม cooperative cancellation ใน Network Discovery: GUI ส่ง cancel flag ตรงถึง worker, ตรวจทุก 50 ms,
  ยกเลิก futures ที่ยังไม่เริ่ม และไม่รอ SNMP timeout ของงานที่กำลังทำอยู่ก่อนคืน control

### Test Log — 2026-08-20 22:10 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Wizard/startup/settings regression | first-run, child dialogs และ Settings ต้องไม่เปิด nested event loop | focused tests ผ่าน `42 passed` | PASS | `source/tests/test_app_setup.py`, `source/tests/test_setup_wizard_v5.py`, `source/tests/test_settings_v5.py` |
| Full Python regression | Qt/layout/cancel changes ต้องไม่ทำให้ workflow เดิมถอยหลัง | `367 passed`; compileall ผ่าน | PASS | `source/tests/` |
| Dependency lock parity | macOS/Linux source lock และ Windows x64 lock ต้อง resolve Qt รุ่นเดียวกัน | PyQt `6.11.0`, Qt/Charts Qt `6.11.1`; Windows wheel resolve ผ่านพร้อม hashes | PASS — STATIC CROSS-PLATFORM | `source/pyproject.toml`, `source/requirements*.txt`, `source/uv.lock` |
| First-run window composition | Wizard ต้องเป็นหน้าต่างเดียว พอดี available screen และไม่ลอยใน maximized parent | parentless application-modal window, 800×520 minimum, 1120×720 cap, initial size 90% screen | PASS — AUTOMATED GEOMETRY | `source/app.py`, `source/v5_pages.py`, `test_setup_wizard_uses_a_centered_screen_bounded_window` |
| Discovery cancellation latency | Cancel ต้องคืน UI โดยไม่รอ probe timeout | slow-probe test คืน worker <250 ms และคืนปุ่ม/สถานะ <500 ms | PASS — SYNTHETIC BLOCKED PROBE | `NetworkDiscoveryWorker.cancel`, `test_network_discovery_cancel_*` |
| Native macOS customer-first-run soak | ต้องเกินช่วง crash เดิม 1–3 นาทีและไม่มี DiagnosticReport ใหม่ | PID `41599` อยู่ใน main Qt event loopเกิน 4 นาที, CPU idle, process sample รอ event ปกติ; crash report ล่าสุดยังเป็นเวลา 22:01 ก่อน runtime ใหม่ | PASS — 4-MINUTE MACOS SOAK | macOS process sample + `~/Library/Logs/DiagnosticReports/` |
| Automated Accessibility reader | อ่าน AX tree หลัง soak ต้องตอบกลับ | Computer Use reader timeout แม้ process sample แสดง main event loop idle และไม่มี crash | INCONCLUSIVE — USER INTERACTION STILL REQUIRED | Computer Use `timeoutReached`; `/tmp/komi-v51-uat-2.sample.txt` |

## Desktop Reports date range และ all-printer comparison — 2026-08-21 07:59 +07

### ผลลัพธ์

- เปลี่ยนตัวเลือกช่วงรายงานแบบ Dropdown เดียวเป็น `วันที่เริ่มต้น` และ `วันที่สิ้นสุด` แยกสองช่อง พร้อม Calendar สีอ่อนและ sync ค่าเดียวกันระหว่าง Overview / Users / Printers
- ช่วงวันที่กำหนดเองอ่าน Daily Usage จริง; รอบบิลมาตรฐานยังรักษา Posted/Provisional Ledger เดิม
- ซ่อนแท็บ `V4.6 History` จาก Reports หลัก โดยข้อมูลนำเข้าเดิมยังคงใช้ใน Usage timeline และ Export/Audit
- กราฟ Printers แสดงทุกเครื่องพร้อมกันด้วยสี/legend แยกเครื่อง; การคลิกแถวเปลี่ยนเฉพาะ Meter detail และไม่กรองกราฟ
- ปรับสัดส่วนกราฟและย่อชื่อใน legend เฉพาะพื้นที่กราฟ เพื่อให้ 3 เครื่องอ่านได้ที่ 1024×768 โดยตารางยังแสดงชื่อเต็ม

### Test Log — 2026-08-21 07:59 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Reports focused regression | tabs, date sync, imported history และ printer detail ต้องคง behavior ที่ตั้งใจ | `29 passed` | PASS | `source/tests/test_cloud_reports_ui.py`, `source/tests/test_legacy_history_import.py`, `source/tests/test_history_v5_current.py` |
| Full Python regression | การแก้ช่วงวันที่และกราฟต้องไม่ทำให้ workflow เดิมถอยหลัง | `370 passed` | PASS | `source/tests/` |
| Static checks | ไฟล์ Reports ที่เปลี่ยนต้อง compile และไม่เพิ่ม lint issue | compileall ผ่าน; scoped Ruff ของ `cloud_reports.py` และ tests ผ่าน; `v5_pages.py` ยังมี baseline Ruff เดิมนอกส่วนแก้ | PASS — SCOPED | `source/ui/cloud_reports.py`, `source/v5_pages.py` |
| Impeccable detector | Reports surface ใหม่ต้องไม่เพิ่ม AI-style UI antipattern | `cloud_reports.py` ไม่พบ warning; detector พบ accent-border baseline เดิม 4 จุดใน `v5_pages.py` ที่อยู่นอก Reports change | PASS — CHANGED SURFACE / BASELINE OPEN | Impeccable detector JSON, `source/ui/cloud_reports.py`, `source/v5_pages.py` |
| Visual polish | หน้า Overview/Printers ต้องไม่ล้นและต้องเห็นกราฟ 3 เครื่องพร้อมกัน | 1024×768 และ 1440×900 ผ่าน; date fields แยกชัด, V4.6 tab ไม่แสดง, legend 3 เครื่องอ่านได้ | PASS — SYNTHETIC/OFFSCREEN | `/tmp/komi-reports-date-range-1024.png`, `/tmp/komi-reports-printers-all-1024.png`, `/tmp/komi-reports-date-range.png`, `/tmp/komi-reports-printers-all.png` |
| Native macOS relaunch | UAT ต้องโหลด source ล่าสุดและคง process หลัง restart | LaunchAgent `com.komi.uat.v515` state running, PID `47795`, V5.1.0 / Python 3.11.15 และ shared source path ถูกต้อง; log ไม่มี traceback | PASS — MACOS PROCESS | `/tmp/komi-v51-uat-registration.log` |
| Verified learning capture | วิธีแก้ที่มีหลักฐานผ่านต้องถูกส่งเข้า Knowledge backend | API ตอบ `observed=true`, `verified=true`, `promoted=true` | PASS | `wiki/learnings/มีปัญหา-desktop-reports-ช่วงวันที่รวมกล่องเดียว-แท็บ-v-d2cbe1db.md` |

## Simplified Settings, P1 UX และ Registration API handoff — 2026-08-21 10:01 +07

### ผลลัพธ์

- Sidebar สำหรับผู้ใช้ทั่วไปเหลือ 5 ส่วน: Overview, Devices, Reports, Settings และ Manual; สถานะ/ประวัติการอ่านย้ายเข้า Settings
- Settings เป็นหน้าเดียวภาษางาน แยกเครื่อง/ราคา, รอบบิล, การอ่านอัตโนมัติ, Web/Database และข้อมูลสำหรับเจ้าหน้าที่; ไม่มี password gate
- งานเสี่ยงยังมีคำเตือนและ confirmation; ตารางตั้งเวลาแบบละเอียดซ่อนไว้จนผู้ใช้เลือกเปิด
- Reports ใช้ช่วงวันเริ่มต้น/สิ้นสุดแยกช่อง, มี recovery action เมื่อ Users ว่าง และกราฟ Printers เปรียบเทียบทุกเครื่องพร้อมกัน
- Manual ไทยเริ่มจาก `เริ่มต้น` และอธิบาย UI ปัจจุบัน; English Manual มีโครงสร้างและขอบเขตข้อมูลตรงกัน
- จัดทำ `DESIGN.md` เป็น design system และ `docs/REGISTRATION_API_HANDOFF.md` เป็น Prompt/contract สำหรับทีม Web Hosting/API

### Test Log — 2026-08-21 10:01 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Full Python regression | Navigation, Settings, Reports, i18n และ cancellation ไม่ถอยหลัง | `374 passed in 23.59s` | PASS | `source/tests/` |
| Discovery cancellation | กดยกเลิกแล้ว UI กลับทันทีโดยไม่รอ probe timeout | 2 tests ผ่านใน `0.70s`; wall time `0.96s` | PASS — SYNTHETIC SLOW PROBE | `source/tests/test_setup_wizard_v5.py` |
| Thai visual matrix | 1–3 เครื่อง × 1024/1280/1440 ต้องไม่ล้นและ action สำคัญยังเห็น | 9/9 ผ่าน, network attempts 0 | PASS — SYNTHETIC/OFFSCREEN | `.impeccable/review/th-final/` |
| English visual/accessibility matrix | ไม่มี Thai ที่มองเห็นหรือค้างใน accessible name/description/tooltip | 9/9 ผ่าน, network attempts 0 | PASS — SYNTHETIC/OFFSCREEN | `.impeccable/review/en-final/` |
| Reports per-tab evidence | ต้องจับภาพแท็บ Cloud Reports จริง ไม่ใช่ legacy tab ที่ซ่อน | Overview, Users, Printers, Usage แยกภาพครบที่ 1024/1440 | PASS — VISUAL | `.impeccable/review/*-final/v5-*-reports-*.png` |
| Native macOS smoke | เปิด app ด้วย temp DB/log แล้วจบโดยไม่มี traceback หรือ font-family warning | exit 0; สร้าง SQLite และ JSONL log ใน temp root | PASS — NATIVE PROCESS SMOKE | `source/app.py --smoke-test` |
| Scoped static checks | ไฟล์ใหม่/แก้ต้อง compile และไม่เพิ่ม Ruff finding | compileall ผ่าน; Ruff `All checks passed!` | PASS | changed UI/tests |
| Verified learning capture | วิธีแก้ที่มีหลักฐานผ่านต้องส่งเข้า Knowledge backend | `observed=true`, `verified=true`, `promoted=true` | PASS | `wiki/learnings/komi-report-v5-1-มีปัญหาเมนู-sync-และ-settings-เชิงเทค-3537b321.md` |
| Real-device acceptance | ลูกค้าจำลองต้องค้นหา/อ่านเครื่องจริง, ใช้ keyboard และบันทึก workflow จบ | ยังไม่ได้ทำรอบนี้ | PENDING NATIVE UAT | macOS LAN + Windows VM |

## Web UI parity, simplified System และ live service rollout — 2026-08-21 12:39 +07

### ผลลัพธ์

- Web Reports ใช้ `วันที่เริ่มต้น` / `วันที่สิ้นสุด` ชุดเดียวกันใน Overview, Users และ Printers; API รองรับช่วงข้ามรอบบิลจาก Daily Usage โดยไม่ดึงรอบล่าสุดมาปน
- Overview แยก Print/Copy Color/B&W และคง Scan แยกจากยอดพิมพ์; User/History โหลดครบทุก pagination และ report ย่อยที่ล้มเหลวมีปุ่มลองใหม่โดยไม่ปิดทั้งหน้า
- Printers เปรียบเทียบทุกเครื่องในกราฟเสมอ; การเลือกแถวเปลี่ยนเฉพาะ Meter detail ตามข้อความที่แสดง
- เมนู Web เหลือ Overview, Users, Printers, Usage และ `ข้อมูลระบบ`; ไม่มี Sync tab แยก และรายละเอียด Sync/Automation ถูกยุบใต้ส่วน Support แบบ read-only
- Login และทุกหน้าหลักสลับไทย/อังกฤษได้ต่อเนื่อง; timeline ฝั่ง Support ไม่มีข้อความไทยหลงใน English mode
- Desktop Settings คง Web service ไว้ในกลุ่ม `รายงานผ่านเว็บและ Database` ไม่มี Web UI tab เพิ่ม; เปิด service อัตโนมัติเมื่อเปิดแอปถ้า checkbox อนุญาตไว้
- Sync source เข้า machine-local Web runtime, build stamp ตรง source และ restart macOS app/service แล้ว; Production ports `3000/8766` พร้อมและ API รายงาน Online `2/2`

### Test Log — 2026-08-21 12:39 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Focused report API regression | custom range, User range และ period propagation ต้องไม่ drift | `26 passed in 0.71s` | PASS | `source/tests/test_web_api.py`, `source/tests/test_reporting_facade.py`, `source/tests/test_subject_history.py` |
| Full Python regression | Web API/Settings/service lifecycle และ Desktop เดิมต้องไม่ถอยหลัง | `376 passed in 21.99s` | PASS | `source/tests/` |
| Web static and production build | TypeScript และ Next production bundle ต้องผ่าน | `tsc --noEmit` และ `next build --webpack` ผ่าน | PASS | `web/`, machine-local `web-runtime` |
| Authenticated browser flow | Login → Overview → Users → Printers → Usage → System, TH/EN และ recovery ต้องใช้งานได้ | ทุกหน้าเปิดได้, no console warning/error; Login จำภาษา; Support English ไม่มี Thai | PASS — ISOLATED UAT WITH COPIED DB | `http://127.0.0.1:3100`, `/tmp/komi-web-v51-after-desktop.png` |
| Printer interaction | เลือกเครื่องแล้วเปลี่ยนเฉพาะรายละเอียด ไม่เปลี่ยนกราฟ | chart markup ก่อน/หลังตรงกัน และ Meter detail เปลี่ยนเป็นเครื่องที่เลือก | PASS — BROWSER | `CloudPrinters` |
| Responsive visual | 1024 px ต้องเห็นชื่อเมนู; Mobile ต้องมี bottom navigation และ action ไม่ถูกตัด | 1024×768 และ 390×844 ผ่าน; ตารางเทคนิคเลื่อนภายใน | PASS — BROWSER VISUAL | `/tmp/komi-web-v51-after-desktop.png`, `/tmp/komi-web-v51-after-mobile.png` |
| Live service rollout | แอปจริงต้อง start Web service อัตโนมัติและเสิร์ฟ build ล่าสุด | app PID `69506`, worker PID `69518`, Login HTTP 200, API health OK และ Online 2/2 | PASS — MACOS LIVE SERVICE | `http://127.0.0.1:3000/login`, build hash `359403a28ccf10b05f15fbe34253c2688c5da58cfe9b25a1f05f1522316d6787` |
| Verified learning capture | วิธีแก้ที่ผ่านหลักฐานต้องบันทึกเข้า Knowledge backend | `observed=true`, `verified=true`, `promoted=true` | PASS | `wiki/learnings/มีปัญหา-komi-report-v5-1-web-ui-ใช้ช่วงวันไม่ตรงกันและ-f4f6004e.md` |

### ขอบเขตหลักฐาน

- Browser QA แบบ authenticated ใช้ UAT runtime และสำเนาฐานข้อมูลเพื่อไม่เปลี่ยนข้อมูลจริง; service production ตรวจยืนยัน build/login/health หลัง restart แต่ไม่ได้กรอกรหัสจริงแทนผู้ใช้
- การยอมรับจากผู้ใช้จริง, Windows native UAT และการเปิด Web นอก Trusted LAN ยังเป็นงานแยก; HTTPS/reverse proxy ยังเป็น blocker ก่อนเปิดภายนอก

## Registration API handoff schema v2 — 2026-08-21 13:19 +07

### ผลลัพธ์

- Handoff ครอบคลุมข้อมูล 12 กลุ่มที่ต้องตรวจได้ รวม company/installation/version/OS, registration/last seen,
  lifecycle/heartbeat history, Dashboard aggregate และ device discovery/selection
- Device visibility เปลี่ยนเป็น Serial No + Model + Selected + Local Slot เพื่อให้หลังบ้านระบุเครื่องจริงที่พบและเครื่องที่เลือกใช้
- Contract ระบุ target `schema_version: 2`; Desktop local envelope/tests ปรับแล้ว แต่ API live/OpenAPI ยังเป็น UUID contract เดิม
- Update/forced update ยังคงเป็น contract แยกและไม่ได้รวมใน handoff นี้

### Test Log — 2026-08-21 13:19 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Handoff contract review | ข้อมูล 12 กลุ่มครบ, schema version ชัด และแยก found/selected ได้ | schema v2 ใช้ Serial No/model/selected/slot, found มากกว่า 3 ได้แต่ selected ไม่เกิน 3 และห้าม network/usage fields | PASS — REVISED DOCUMENT | `docs/REGISTRATION_API_HANDOFF.md` |
| Desktop envelope | ส่งผล IP scan ทั้งหมดพร้อม Serial No และ selected/slot โดย UI คงเดิม | focused contract/wizard tests ผ่าน; API live ยังไม่รองรับ revised field | PASS — LOCAL / E2E PENDING | `source/services/registration_envelope.py`, `source/v5_pages.py`, focused pytest |
| API/staging verification | OpenAPI, deployed schema, Dashboard และ E2E ต้องตรง handoff | ยังไม่มี artefact จากทีม API | PENDING — EXTERNAL DEPENDENCY | Staging URL/OpenAPI/commit/Dashboard evidence |

## Web Users name search — 2026-08-21 13:26 +07

### ผลลัพธ์

- หน้า Web `ผู้ใช้งาน / Users` มีช่องค้นหาชื่อแบบทันที ครอบคลุมทั้ง User และ Account Track
  จากข้อมูลทุก pagination ที่โหลดไว้แล้ว โดยไม่เรียก API ซ้ำทุกตัวอักษร
- ผลค้นหากรองรายชื่อ, กราฟผู้ใช้งาน และการกระจายตามเครื่องพร้อมกัน; KPI ด้านบนยังคงเป็นยอดรวมของ
  ช่วงวันที่ เพื่อไม่ให้ความหมายของรายงานเปลี่ยนขณะพิมพ์ค้นหา
- แสดงจำนวน `พบ x จาก y รายการ`, มีปุ่มล้างคำค้น, กด Escape เพื่อล้างได้ และมี no-result state
  ที่บอกคำค้นชัดเจนทั้งไทย/อังกฤษ
- Mobile reflow วาง label, input, จำนวนผล และปุ่มล้างเป็นลำดับอ่านง่าย โดยไม่เกิด horizontal overflow

### Test Log — 2026-08-21 13:26 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Web static and production build | TypeScript และ Next production bundle ต้องผ่าน | `tsc --noEmit` และ `next build --webpack` ผ่าน | PASS | `web/app/cloud-report-views.tsx`, `web/app/globals.css` |
| Search interaction | อังกฤษ/ไทย, ไม่พบข้อมูล, ล้างคำค้น และ Escape ต้องกรองผลถูก | `somchai`, `บัญชี`, no-match และ `nicha` ได้จำนวน/แถว/กราฟตรงกัน | PASS — ISOLATED BROWSER UAT | synthetic User/Account data บน `127.0.0.1:3100` |
| Responsive visual | Search ต้องอ่านง่ายที่ Desktop และ Mobile 390 px โดยไม่ล้นแนวนอน | Desktop จัด 1 แถว; Mobile จัดกลุ่ม 2 แถว; `scrollWidth=clientWidth=375` ใน viewport ภายใน | PASS — BROWSER VISUAL | Browser screenshots; console logs `[]` |
| Live service rollout | machine-local runtime ต้องใช้ source ล่าสุดและ service จริงกลับมา Online | source/build stamp ตรง `fb58eebef7cd94d522f507248f13091fb2d01005bf36807cd2ad6aa91bf5d3a6`; Login HTTP 200; health OK `2/2` | PASS — MACOS LIVE SERVICE | `http://127.0.0.1:3000/login`, ports `3000/8766` |
| Verified learning capture | วิธีแก้ที่มีหลักฐานผ่านต้องส่งเข้า Knowledge backend | API ตอบ 200 แต่คืน `observed=false, verified=false, promoted=false`; ไม่แต่งหลักฐานหรือ promote เอง | NOT CAPTURED | `POST /api/knowledge/learnings/observe` |

### ขอบเขตหลักฐาน

- Interaction ใช้ fixture ชื่อสมมติและ API ชั่วคราวซึ่งลบ/ปิดหลังทดสอบ; ไม่แก้ฐานข้อมูลจริงและไม่ส่งข้อมูลออกภายนอก
- Production runtime ยืนยัน build/login/health แล้ว แต่ฐานข้อมูลจริงในช่วงปัจจุบันยังไม่มี User/Account row จึงใช้ isolated UAT พิสูจน์การกรอง

## Registration API artefact review — 2026-08-21 17:37 +07

### ผลลัพธ์

- `komi 1.zip` เปิดตรวจแบบ read-only ได้อย่างปลอดภัย: ไม่มี path traversal/symlink และไม่พบ secret value
  ใน archive; ชุดส่งมอบมี OpenAPI, field/deploy/migration notes, curl examples และ local contract test แต่ไม่มี
  API/dashboard implementation source หรือ Git commit/tag ให้ตรวจเทียบ manifest
- OpenAPI รองรับ `schema_version: 2`, register/heartbeat และ privacy-bounded device inventory ตาม target contract
  แต่ response/error schemas ยังไม่ strict, status `413` ไม่อยู่ใน operation contract และ staging ยังใช้ host/database
  instance ร่วมกับ production
- Live health ผ่านเฉพาะ canonical `https://www.dmskm.com/api/v1/health` (`status=ok`, API `1.0.0`,
  schema `1/2`, database `ok`); URL non-www ใน OpenAPI และ curl examples ตอบ `301` ขณะที่ script ไม่ follow redirect
- Dashboard หลังทดสอบแสดง installation จริงเป็น Active พร้อมวันเริ่มใช้/ลงทะเบียน/last seen, Version `5.1.0`,
  Darwin/arm64, schema v1, เครื่องที่พบ 2 รุ่น, heartbeat 1 รายการ และ lifecycle จาก first registration ไป first heartbeat
- Device rows แสดง Short Device ID และ Model แล้ว แต่ v1 ไม่มี selected/slot จึงแสดง `เลือกใช้ 0` และช่อง Slot เป็น `—`;
  aggregate Active 7/30/90, CSV, RBAC/MFA และ rollback ยังไม่ได้ตรวจจากหลักฐานนี้
- ตามคำสั่งผู้ใช้ให้ใช้ key เดิม: เก็บ bootstrap key แบบ machine-local ใน macOS Keychain และใช้ส่ง header
  โดยไม่บันทึกค่าจริงลง repository, SQLite หรือ log; installation token ที่ server ออกให้เก็บใน Keychain เช่นกัน
- ใช้ pending envelope ของ `Customer First Run UAT` ส่ง `schema_version: 1` จริงไป canonical www endpoint:
  register ได้ HTTP `201` และ heartbeat ได้ HTTP `200`; payload ผ่าน v1 allow-list และไม่ส่ง field ต้องห้าม
- ไม่ได้แก้ Desktop/WEB UI; การทดสอบนี้ยืนยัน transport/credential/server path จริง แต่ยังไม่ใช่ durable Desktop integration

### Test Log — 2026-08-21 17:37 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Archive safety and secret scan | Archive อ่านได้ ไม่มี unsafe entry หรือ secret จริง | 18 entries, ไม่มี traversal/symlink และไม่พบ 64-hex secret literal | PASS — STATIC | `komi 1.zip` SHA-256 `b00169d8e126016217652aac14439a828288b66987090417839698cb5d4b4ca3` |
| OpenAPI contract review | v2 ตรง handoff, canonical URL ใช้งานตรง และ schema/error strict | v2 fields ตรงหลัก แต่ URL redirect, response/error ไม่ strict และ operation ขาด `413` | PARTIAL | `openapi.json`, `FIELDS.md`, `HANDOFF-RESPONSE.md` ใน archive |
| Live health | API และ database ตอบบน Base URL ที่ประกาศ | non-www `301`; www `200` พร้อม `status=ok`, schema `1/2`, database `ok` | PARTIAL — URL MISMATCH | read-only `GET /health`; ไม่มี credential |
| Source provenance | มี source commit/tag และไฟล์ implementation ตรง manifest | มี build ID/hash note แต่ไม่มี source files หรือ Git provenance ใน archive | FAIL | `RELEASE-MANIFEST.md` และ archive file list |
| Dashboard evidence | มี installation, heartbeat, lifecycle และ device rows ตรง response จริง | แสดง Active installation, registered/last seen, v5.1.0, Darwin/arm64, 2 devices, heartbeat และ lifecycle ครบ; selected/slot ยังว่างเพราะ schema v1 | PASS — LIVE V1 / PARTIAL V2 | `Screenshot 2569-08-21 at 17.43.44.png` |
| Live register | ใช้ installation จริง, bootstrap header และ privacy allow-list แล้ว server สร้างรายการ | canonical www ตอบ HTTP `201`; token ไม่แสดงและเก็บใน macOS Keychain | PASS — LIVE V1 | `Customer First Run UAT` pending envelope; local registration status `registered` |
| Live heartbeat | ใช้ installation token ที่ server ออกและอัปเดต last seen สำเร็จ | canonical www ตอบ HTTP `200`, status `ok`; token ไม่อยู่ใน SQLite/log | PASS — LIVE V1 | local `registration_last_seen_at`; macOS Keychain installation token |
| Full staging acceptance | idempotent replay, invalid token, v2 inventory, deactivate, rate limit, migration/rollback และ Dashboard ผ่าน | register/heartbeat v1 ผ่าน 2 เส้นทางหลัก; case ที่เหลือยังไม่ได้รัน | PARTIAL — EXTERNAL/ADMIN EVIDENCE | revised artefact, Dashboard refresh และ acceptance evidence |

## Registration schema v2 Serial inventory — 2026-08-21 18:04 +07

### ผลลัพธ์

- เปลี่ยน identity ของเครื่องใน target schema v2 จาก random UUID เป็น `serial_number` เพื่อให้ทีมหลังบ้านระบุเครื่องจริง
- Pending registration envelope เก็บเครื่อง Konica Minolta ทุกเครื่องที่พบจาก IP scan ใน setup session พร้อม Model;
  เครื่องที่ลูกค้าเลือกอ่าน Report มี `selected=true` และ Slot 1–3 ส่วนเครื่องที่พบแต่ไม่เลือกมี Slot `null`
- จำนวนเครื่องที่พบไม่จำกัดที่ 3 แต่ selected ยังคงสูงสุด 3 ตามขอบเขตผลิตภัณฑ์; ไม่มีคำเตือนขายสินค้า,
  ข้อความใหม่ หรือการเปลี่ยนหน้าตา/workflow ฝั่งผู้ใช้
- Privacy allow-list ยอมรับ Serial No ตาม business decision ใหม่ แต่ยัง reject IP/MAC/hostname/credential/counter/user/document/log
- API live/OpenAPI ปัจจุบันยังใช้ `device_instance_id` UUID และ reject Serial No จึงยังไม่ส่ง revised v2 จริงจนทีม API deploy migration/contract ใหม่

### Test Log — 2026-08-21 18:04 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Focused registration/wizard | found มากกว่า 3 ได้, selected ไม่เกิน 3, Serial/slot rules และ pending envelope ถูกต้อง | `36 passed in 4.62s` | PASS | `source/tests/test_registration_envelope.py`, `source/tests/test_setup_wizard_v5.py` |
| Full Desktop regression | การเปลี่ยน envelope ไม่กระทบ workflow เดิม | `380 passed in 21.39s` | PASS | `source/tests` |
| Static checks | Source compile และไฟล์ registration ใหม่ผ่าน lint | compileall ผ่าน; scoped Ruff ผ่าน | PASS | `source/services/registration_envelope.py`, `source/tests/test_registration_envelope.py` |
| UI scope guard | ไม่มีข้อความ Print Management/ติดต่อฝ่ายขายหรือ UI behavior ใหม่ | source scan ไม่พบข้อความดังกล่าว; เปลี่ยนเฉพาะ inventory data path | PASS — NO UI CHANGE | `source/v5_pages.py` |
| Handoff examples | JSON ตัวอย่าง register/heartbeat/error parse ได้ | `4` JSON blocks parse ผ่าน | PASS | `docs/REGISTRATION_API_HANDOFF.md` |
| Live v2 E2E | API/DB/Dashboard รับ Serial No และแสดง found/selected/slot ตรง request | API live contract ยังเป็น UUID และ reject Serial | PENDING — TEAM API | revised OpenAPI, migration/source commit และ Dashboard evidence |

## Desktop-managed LAN Web access — 2026-08-21 19:04 +07

### ผลลัพธ์

- Desktop เป็นจุดดูแลระบบ: `Settings > รายงานผ่านเว็บและ Database > ตั้ง/เปลี่ยนรหัส Web`; Web UI คงเป็น
  read-only report viewer และไม่อนุญาตให้เปลี่ยนรหัสจาก browser
- New install เริ่มแบบ locked จนเจ้าของตั้งรหัสจาก Desktop. Installation เดิมย้ายรหัสเดิมจาก plaintext เป็น
  `scrypt` hash โดยไม่บังคับให้ลูกค้าเปลี่ยนรหัสทันที แม้รหัสเก่าจะสั้นกว่ากฎใหม่
- การตั้งรหัสใหม่บังคับ 12–128 ตัวอักษร, ยืนยันซ้ำ, ปฏิเสธ newline/ช่องว่างหัวท้าย, ไม่แสดงรหัสเดิม และไม่เขียนรหัสลง log
- เมื่อเปลี่ยนรหัส ระบบ rotate auth epoch และ restart Web worker ที่ Desktop เป็นเจ้าของ; cookie และรหัสเดิมใช้ต่อไม่ได้
- หน้า Settings และ dialog แสดงไทย/อังกฤษครบที่ 1024×768 โดย action/status ไม่ล้น และบอกผลกระทบว่าเครื่อง LAN ทุกเครื่องต้อง Login ใหม่

### Test Log — 2026-08-21 19:04 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Credential unit/service/UI | hash, validation, migration, restart และ Desktop dialog ทำงานโดยไม่เก็บ plaintext | focused `21 passed`; scoped Ruff ผ่าน | PASS | `source/services/web_access.py`, `source/services/web_service.py`, `source/tests/test_init_web_access.py`, `source/tests/test_settings_v5.py` |
| Full Desktop regression | feature ใหม่ไม่ทำ workflow เดิมถอย | `387 passed in 25.72s` | PASS | `source/tests` |
| Web compile/build | Node verifier และ session contract ต้อง compile/build production ได้ | `tsc --noEmit` และ `next build --webpack` ผ่าน | PASS | `web/lib/access-credential.ts`, `web/lib/session.ts`, `web/app/auth/session/route.ts` |
| Auth/session UAT | รหัสผิดถูกปฏิเสธ, รหัสถูกเข้าได้ และเปลี่ยนรหัสแล้ว cookie/rหัสเดิมหมดอายุ | ก่อนเปลี่ยน `401/200`; หลังเปลี่ยน old cookie `307`, old code `401`, new code/cookie `200/200` | PASS — ISOLATED LIVE HTTP | temporary Next production runtime บน `127.0.0.1:3100` |
| Existing-install migration | รหัสเดิมต้องยังใช้ได้และ plaintext key ต้องหาย | dry-run จากสำเนา credential จริง: configured, legacy login preserved, plaintext removed, dotenv-safe hash ครบ `True` | PASS — SAFE COPY | machine-local credential copy; ไม่แสดงค่ารหัส |
| Thai/English 1024px visual | Settings และ dialog ต้องอ่านครบ ไม่ล้น และไม่เหลือภาษาไทยใน EN mode | offscreen visual ไทย/อังกฤษผ่าน; EN visible Thai `[]` | PASS — OFFSCREEN VISUAL | `/tmp/komi-web-settings-1024.png`, `/tmp/komi-web-access-dialog.png`, `/tmp/komi-web-settings-en-1024.png`, `/tmp/komi-web-access-dialog-en.png` |
| macOS live rollout | source/build ตรง, env ปลอดภัย, Desktop หนึ่ง process และ Web/API กลับมา Online | build stamp ตรง source, `.env.local` mode `0600`, plaintext absent, Desktop `1`, ports `3000/8766`, Login page/API health `200`, anonymous root `307` | PASS — MACOS LIVE SERVICE | machine-local runtime และ process tree PID `84254` |
| Verified learning capture | ส่งวิธีแก้ dotenv-safe hash และ backward-compatible migration เข้า Knowledge backend | API ตอบ 200 แต่คืน `observed=false, verified=false, promoted=false`; ไม่สร้างหรือ promote หลักฐานเอง | NOT CAPTURED | `POST /api/knowledge/learnings/observe` |

### ขอบเขตหลักฐาน

- ไม่เปลี่ยนรหัสจริงแทนผู้ใช้ จึงไม่ส่งรหัสจริงผ่าน command/log. การคงรหัสเดิมพิสูจน์ด้วย dry-run จากสำเนา credential
  ก่อน migration และการเปลี่ยนรหัส/session พิสูจน์ด้วย isolated production runtime
- LAN Web ยังเป็น Trusted-LAN HTTP; ต้องมี HTTPS/reverse proxy ก่อนเปิดให้เข้าจากอินเทอร์เน็ต

## Desktop Reports Excel Export แบบเลือกช่วงเวลา — 2026-08-21 19:43 +07

### ผลลัพธ์

- ปุ่ม Export ใน Desktop Reports เปิด dialog ให้เลือก `วันที่เริ่มต้น` และ `วันที่สิ้นสุด` ก่อนเลือกตำแหน่งบันทึกไฟล์
  พร้อมทางลัดช่วงที่กำลังแสดง, เดือนปัจจุบัน และข้อมูลทั้งหมด; ช่วงวันไม่ถูกต้องหรือไม่มีข้อมูลจะไม่สร้างไฟล์เปล่า
- Workbook มี 3 ชีตเท่านั้น: `การใช้งานรายเครื่อง`, `มุมมองผู้ใช้` และ `มุมมองรายวัน`
- มุมรายเครื่องใช้ 1 เครื่องต่อแถว; มุมผู้ใช้ใช้ 1 ผู้ใช้ต่อแถว; มุมรายวันใช้ 1 วันที่ต่อแถว โดยกลุ่มคอลัมน์ของแต่ละ
  เครื่องพิมพ์วางแนวนอน แม้ตารางกว้าง เพื่อไม่ให้ชื่อหรือวันที่ซ้ำหลายแถวและลดโอกาสอ่านผิด
- ค่าใช้จ่ายรายวันแยกตามประเภทกระดาษจาก Usage และราคาที่มีผลในวันนั้น แล้วตรวจยอดรวมกลับกับค่าใช้จ่ายสุทธิเดิม;
  ถ้าไม่มีฐานราคา ระบบระบุยอดที่จัดสรรไม่ได้แทนการเดา
- Source ปัจจุบันของ User/Account มีเพียงยอดรวมต่อผู้ใช้และเครื่อง ยังไม่มี A3/A4/สี/ขาวดำหรือค่าใช้จ่ายระดับผู้ใช้
  จึงแสดงยอดรวมจริงและเว้นช่อง category/cost ว่าง พร้อมข้อความอธิบายจนกว่าจะมี source รองรับ
- Export ไม่ใส่ IP address, Serial Number, username, password หรือ credential ลง workbook

### Test Log — 2026-08-21 19:43 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Export dialog + 3-sheet focused regression | เลือกช่วงวันได้, 1 เครื่อง/ผู้ใช้/วันต่อแถว และกรองข้อมูลตามช่วงจริง | `4 passed in 0.82s`; scoped Ruff และ `py_compile` ผ่าน | PASS | `source/tests/test_report_excel_export.py`, `source/tests/test_history_v5_current.py` |
| Segmented Python regression | Feature ใหม่ไม่ทำ Desktop/Web API behavior เดิมถอย | Desktop/Qt ชุดใหญ่ `376 passed`; Web API แยก process `13 passed` รวม `389 passed` | PASS — SEGMENTED | `source/tests/` |
| One-process full regression | ทุก test รันใน Python process เดียวจนจบ | ผ่านถึง 92% แล้ว native segfault ระหว่าง FastAPI OpenAPI test หลัง Qt-heavy suite; test เดียวกันแยก process ผ่าน 13/13 | ยังไม่ผ่าน — PROCESS STABILITY | pytest native stack และ `source/tests/test_web_api.py` |
| Real Database workbook | สร้างไฟล์จาก DB จริง, เปิดอ่านได้, 3 ชีตตรงแบบ และไม่รั่วข้อมูลเครือข่าย/credential | 23 daily records, 3 devices; artifact-tool เปิด/เรนเดอร์ครบ, formula errors `0`, privacy regex `0`; `unzip -t` ผ่าน | PASS — REAL DB / VISUAL | `outputs/019f69b5-6709-7e53-8ebf-a35114d233d0/KOMI_Reports_20260801_20260831.xlsx` |

### ขอบเขตหลักฐาน

- ไฟล์ทดสอบจาก DB จริงยังไม่มี User/Account history ในช่วงที่เลือก จึงพิสูจน์ empty state ของชีตผู้ใช้จาก DB จริง;
  โครงสร้างหลายผู้ใช้/หลายเครื่องและตำแหน่งยอดรวมพิสูจน์ด้วย focused fixture
- Full regression แบบ process เดียวยังถือว่า `ยังไม่ผ่าน` จนกว่าจะแยกหรือแก้ native lifecycle ระหว่าง Qt กับ FastAPI OpenAPI;
  ขณะนี้ไม่มีหลักฐานว่า segfault เกิดในเส้นทาง Export ที่ผู้ใช้กดจริง

## Settings Compact Task Sheet สำหรับผู้ใช้ทั่วไป — 2026-08-21 20:59 +07

### ผลลัพธ์

- หน้า Settings เป็น Compact Task Sheet และบอกตั้งแต่ first viewport ว่า ถ้าระบบทำงานปกติผู้ใช้ไม่จำเป็นต้องเปลี่ยนค่า;
  แต่ละแถวแสดงค่าปัจจุบันกับ action ตามงานจริง: `เปลี่ยน`, `แก้ไข`, `จัดเวลา`, `จัดการ` และ `แก้ปัญหา`
- เปิด editor ได้ครั้งละหนึ่งส่วนเท่านั้น และไม่มี Global Save; รอบบิล, ตารางเวลา และ LAN บันทึก/ตรวจสอบแยกกัน
  เพื่อไม่ให้การแก้เรื่องหนึ่งพาค่าอีกเรื่องเปลี่ยนตาม
- Draft ไม่ถูก background refresh เขียนทับ; การสลับ task บังคับให้บันทึกหรือยกเลิกก่อน, การออกจาก Settings มีคำเตือน
  ว่าจะเก็บ draft ไว้ และการออกจากโปรแกรมต้องยืนยันละทิ้ง draft
- รอบบิลแสดงผลกระทบชัดว่าใช้กับรายการใหม่และไม่เขียนยอดย้อนหลัง; Edit-mode Setup Wizard เปลี่ยนเฉพาะเครื่องพิมพ์
  และราคา จึงไม่เขียนทับรอบบิลที่ Settings เป็นเจ้าของ
- ตารางเวลา default ถือเป็นค่าแนะนำที่ระบบใช้งานจริง ไม่แสดงเป็นงานค้างบันทึก; เมื่อผู้ใช้บันทึก ระบบอ่าน config กลับ
  และตรวจ OS Auto-start ก่อนแสดงผลว่า verified
- แยก `รายงานจากเครื่องอื่นใน LAN` ออกจาก Database อย่างชัดเจน โดยอธิบายว่าเครื่องหลักใช้ Desktop ตามปกติ
  และแสดงเฉพาะ LAN URL ที่เครื่องอื่นต้องใช้; ถ้าพบเพียง loopback จะบอกว่าไม่พบ LAN address แทนการแสดง
  `127.0.0.1` แบบชวนให้เข้าใจผิด
- หาก Config ตั้งให้ Web เปิดแต่ service หยุด หน้า collapsed แสดง `ต้องแก้ไข` และ editor เปิด
  `บันทึกและตรวจสอบ LAN` ให้ retry ได้โดยไม่ต้องเดาว่าต้องเอาติ๊กออกแล้วติ๊กใหม่; ปุ่ม Open/Copy ซ่อนจน service พร้อม
- การเปลี่ยนรหัส Web ยังเป็น immediate action ที่มีป้าย `มีผลทันที` และแยกจาก draft ของ LAN อย่างชัดเจน
- รายชื่อเครื่องพิมพ์บนหน้าหลักแสดงเฉพาะชื่อและรุ่น; IP/Serial ย้ายไป tooltip สำหรับเจ้าหน้าที่ เพื่อลดข้อมูลเทคนิค
  ที่ผู้ใช้ทั่วไปไม่ต้องตัดสินใจ
- Help เริ่มจากอาการ `ข้อมูลไม่อัปเดต`, `ยอดไม่ตรง` และ `เปิด Web ไม่ได้`; Database path, Shortcut,
  สถานะการอ่าน, Billing Audit และเครื่องมือขั้นสูงซ่อนใต้ `ข้อมูลสำหรับเจ้าหน้าที่` โดยไม่มี password gate
- ภาษาไทย/อังกฤษใช้โครงสร้างและ action เดียวกัน; รหัสเข้า Web ยังคงตั้งหรือเปลี่ยนจาก Desktop เท่านั้นตามขอบเขตเดิม

### Test Log — 2026-08-21 20:59 +07

| Action | Expected | Actual | Result | Evidence |
|---|---|---|---|---|
| Settings + navigation focused regression | one-editor, separate save, storage verify, LAN retry, dirty refresh/nav/exit guard และ Wizard ownership ทำงานตาม contract | `25 passed in 3.76s`; scoped Ruff และ `py_compile` ผ่าน | PASS | `source/tests/test_settings_v5.py`, `source/tests/test_ui_consistency.py`, `source/tests/test_tray_lifecycle.py` |
| Segmented regression | UI change ไม่ทำ Desktop/Web API behavior เดิมถอย | Desktop/Qt `382 passed in 26.08s`; Web API แยก process `13 passed in 0.44s`; รวม `395 passed` | PASS — SEGMENTED | `source/tests/` |
| Thai visual/accessibility matrix | 1–3 เครื่อง × 1024/1280/1440 และ Settings 6 สถานะต้องไม่ล้น/ตัดข้อความ | 9/9 viewports ผ่าน, network attempts `0`; Settings-specific clip detector ผ่าน | PASS — SYNTHETIC/OFFSCREEN | `/tmp/komi-settings-task-sheet-th-accept.FVTzrP/` |
| English visual/accessibility matrix | โครงสร้างตรงไทย, ไม่มี Thai ใน visible/accessibility metadata และ action ไม่ถูกตัด | 9/9 viewports ผ่าน, network attempts `0`; Settings-specific clip/language detector ผ่าน | PASS — SYNTHETIC/OFFSCREEN | `/tmp/komi-settings-task-sheet-en-accept.OwVvGg/` |
| Independent UX acceptance | ตรวจ hierarchy, state/recovery, context labels, draft safety และภาพ 1024px ไทย/อังกฤษ | รอบแรกพบ default-schedule contradiction และ LAN dead end; แก้แล้วตรวจซ้ำไม่เหลือ blocker/required fix | PASS — UX CHALLENGER | `source/v5_pages.py`, `source/app.py`, ภาพ QA 12 สถานะ |

### ขอบเขตหลักฐาน

- ภาพ QA ใช้ฐานข้อมูลชั่วคราวและปิด network จริง จึงพิสูจน์ layout, state จำลอง, ภาษา และ interaction guard;
  process Desktop ที่เปิดอยู่ต้องปิด/เปิดใหม่เพื่อโหลด source ล่าสุด และยังต้องทำ native user acceptance ด้วยข้อมูลจริง
- Visual runner ปิด global clipping assertion เพราะมี baseline เดิมใน Overview ที่อยู่นอก Settings แต่ยังเปิด
  Settings-specific clipping, horizontal overflow, Thai/English metadata และ network-attempt assertions ครบ
- Advanced schedule ยังมี horizontal scroll ภายในตารางที่ 1024px แต่ซ่อนหลัง action สำหรับเจ้าหน้าที่และไม่อยู่ใน workflow ผู้ใช้ทั่วไป

## Production Phase 2 — Registration & Privacy — 2026-08-22

### Outcome

- Technical Pass: เพิ่ม additive schema 12 สำหรับ profile/outbox/attempt history, typed repository/client, strict schema-v2 allow-list,
  request fingerprint/idempotency, stale-operation supersede, retry/backoff+jitter/Retry-After และ restart recovery โดยไม่เปลี่ยน Billing tables/semantics.
- Setup commit local ก่อน registration enqueue; outbox/network failure ไม่ย้อน device/pricing/settings และไม่ขวางการเปิดแอป.
- Registration worker ใช้ executor แยกจาก printer polling, heartbeat cadence มาจาก typed response และเก็บ scoped token ใน OS vault เท่านั้น.
- Production sender fail-closed เมื่อ policy artefact หาย/invalid, Registration Data Notice ยังไม่อนุมัติ หรือ acknowledgement ไม่ตรง version.
- Settings แสดงสถานะไทย/อังกฤษแบบ `registered`, `pending`, `offline retry`, `action required`, มี Manual Retry,
  Registration Data Notice viewer และ acknowledgement เวอร์ชันปัจจุบัน โดยไม่เพิ่มเมนูซับซ้อน.
- เพิ่ม Registration Data Notice ไทย/อังกฤษ `DRAFT-2026-08-22` ตาม payload จริง และแสดงจาก Setup/Settings เมื่อยังไม่มี
  approved policy. ระบุว่า Company ต้องเป็นชื่อนิติบุคคล/หน่วยงาน, ข้อมูลที่ส่ง/ไม่ส่ง, Purpose, ความสมัครใจ,
  ผู้เข้าถึง, retention proposal, security และ Source-IP log caveat โดยยังไม่เปิด Production sender.
- Factory Reset ลบ registration state และ scoped token แบบ fail-closed เมื่อ vault ใช้งานไม่ได้; log/SQLite ไม่เก็บ token,
  raw payload หรือ serial list ใน observability.
- ไม่เริ่ม Update/manifest/download (Production Phase 3).

### Evidence

| Gate | Actual | Result |
|---|---|---|
| Focused Phase 2 regression + independent final review | `156 passed in 16.60s`; scoped Ruff/diff check ผ่าน; ไม่พบ actionable P1/P2 | PASS |
| Full Python regression | `497 passed, 1 warning in 47.52s`; warning เป็น explicit virtual-printer TLS compatibility fixture | PASS |
| Web security/lint/build/audit | security `2 passed`; TypeScript lint/build ผ่าน; npm vulnerabilities `0` | PASS |
| Python dependency audit | `No known vulnerabilities found` | PASS |
| Phase 0 release safety | release builder `8 passed`; secret/allow-list gate ผ่าน | PASS |
| Phase 1 live security preservation | TLS 1.3, HTTPS/auth/session/lockout/revocation และ Web build/audit ผ่าน | PASS |
| Focused UI/accessibility | Setup/Settings tests ผ่าน; Thai Settings render 1024×760 ตรวจแล้วไม่ clip และ state disabled ชัด | PASS — SYNTHETIC/OFFSCREEN |
| Independent review | ปิด findings เรื่อง stale outbox, worker wedge, redirect credentials, error sanitization, fingerprint, reset/vault, ack และ retention | PASS — CODE/TEST |
| Registration Data Notice | ไทย/อังกฤษตรง schema-v2/non-personal boundary; Registration/UI `138 passed`; full Desktop `499 passed` | PASS — DRAFT |
| Staging first register/replay/offline/restart/heartbeat/auth/rate limit/invalid payload/Dashboard/cleanup | ไม่พบ verified staging/OpenAPI artefact ใน nested repo; ไม่ยิง production แทน | BLOCKED — SAFE |
| Branch delivery | implementation commit `1e27ec6`; Phase 2 branch fast-forward เข้า `main` และ push private origin หลัง code gates | PASS |

Task evidence แบบละเอียดอยู่ใน canonical thread workbook เดิมที่
`work/01a02760-f602-7d70-9eea-05cc8685dd8c/PROJECT.md`; ไม่มีการสร้าง PROJECT v2/final ซ้ำ.

### Production blocker / unlock conditions

- Payload ฝั่งแอปเป็นข้อมูลนิติบุคคล/Installation/อุปกรณ์ ไม่ใช่ข้อมูลบุคคลเมื่อ Company ห้ามเป็นชื่อบุคคล.
- Data Notice พร้อมที่ `docs/REGISTRATION_DATA_NOTICE.md`; Hosting คือ `https://www.dmskm.com/` ในประเทศไทย และ
  Bom ยืนยันว่า API/Application log ไม่จัดเก็บ Source IP/Raw body/Token. ยังต้องพิสูจน์ OpenAPI/Staging, retention,
  access/deletion และ Dashboard read-back จากระบบที่ deploy จริง.
- ยังไม่มี OpenAPI schema v2 + verified deployed staging environment artefact ที่บันทึก bootstrap flow,
  installation-token rotate/revoke และ typed error contract โดยไม่เปิดเผย secret.
- เมื่อได้รับ artefact ทั้งสองกลุ่ม ให้ติดตั้ง non-secret runtime policy + vault bootstrap reference แล้วรัน synthetic
  `KOMI-UAT-<unique>` บน staging เท่านั้น: first register, idempotent replay, offline→restart→retry, heartbeat,
  bad/revoked token, Retry-After, forbidden payload, >3 discovered/≤3 selected, Dashboard read-back และ cleanup/deactivate.
- จนกว่าจะครบเงื่อนไขนี้ สถานะคือ **Technical Pass / Production blocked** และห้าม claim Production Pass.

### Dashboard publish handoff

- Nested repo อัปเดต canonical project/workbook แล้ว; main thread ต้อง publish Dashboard จาก Projects root ตาม workflow กลาง.
- Phase 2 ไม่แก้ `portfolio-site` และไม่แก้ API project อื่นตาม scope ที่อนุมัติ.

## Production Phase 3 — Update Delivery — DEFERRED 2026-08-22

- Bom เลื่อน signed update manifest, release check, verified download, staged rollout และ updater automation ไปทำภายหลัง เพื่อให้ทันเป้าหมาย Release สิ้นเดือน.
- งานนี้ไม่ถูกยกเลิก: architecture/options, security boundary, prerequisites, test/UAT gates และ rollback plan ยังคงเป็น backlog ที่ต้องเปิด task ใหม่ก่อน implementation.
- Current release ห้ามมี forced/silent update, remote update command, arbitrary script, update event telemetry หรือ private signing key ใน client/hosting/repository.
- การเลื่อน Phase 3 ไม่อนุญาตให้ลด Phase 0 release safety, Phase 1 security baseline หรือ Phase 2 privacy boundary.

## Production Phase 4 — Native Packaging & Release Candidate — APPROVED 2026-08-22

### Technical RC result — 2026-08-22

- สร้าง Windows x64 installer จาก source commit `0bc1c5d9c168a6ff535725050c5a901f868541e2` สำเร็จ: identity `komi-report-v5-windows-x64-rc-5.1.0-0bc1c5d9c168`, SHA256 `875e5ca1b2d0134213aca8210308e4a41d7920d7e86e7b1162cf3001207debc1`, file inventory 8,570 รายการ, CycloneDX SBOM และ checksum evidence ครบ.
- Phase 0 packaged-payload scan ผ่าน; artifact ไม่มี forbidden DB/CSV/log/env/credential/customer evidence, Registration ไม่มี policy artifact และ Update runtime path ไม่มีอยู่ตาม Phase 3 deferred.
- Windows 11 ARM64 VM ผ่าน clean install, installed smoke, first-run visual, synthetic backup/integrity/restore/rollback, uninstall preservation และ reinstall แต่หลักฐานถูกล็อกเป็น `windows-arm64-vm-preflight`, `production_go=false`; ห้ามใช้แทน Windows x64 native UAT.
- macOS arm64 Internal UAT ผ่าน bundle launch และ first-run จาก isolated DB; artifact SHA256 `ab6e7003d63dd381acd73dcf5df091e8d36f980774ef9f8570476ad8dc08bd0f`, signing เป็น ad-hoc และยังไม่ notarized จึงห้าม customer Production.
- Final regression ผ่าน: Python `513 passed` (warning เดียวเป็น explicit Virtual Printer TLS compatibility fixture), Web type/security/standalone production build ผ่าน และ Python/npm dependency audit พบ 0 known vulnerabilities.
- **Release decision: Technical RC / Production GO blocked.** Bom เลื่อน native Windows 10/11 x64 UAT ไปหลัง Release โดยไม่ claim ว่าผ่าน; controlled real-device Meter/Billing/Report/Excel ผ่านสำหรับ authorized Slot 1 แล้ว. Phase 4 ยังขาด production code signing ส่วน Registration/Heartbeat ยังคง fail-closed และ Phase 2 ไม่ใช่ Production Pass.

### Historical native-host access attempt — 2026-08-22

- Codex cross-host handoff ไป `BTHL0564` ล้มเหลวแบบ fail-safe ด้วยข้อความ `No matching saved project was found on BTHL0564.` และ read-only SSH preflight ไป host alias เดียวกัน timeout ที่ port 22; ไม่มี installation หรือ remote mutation เกิดขึ้น.
- เดิมเงื่อนไขปลดล็อกคือ `BTHL0564` ต้องมี private project `komi-report-v5` พร้อม branch `codex/phase-4-native-release-candidate` เป็น saved Codex project หรือมี working authorized SSH/remote path ที่เข้าถึง repository/Windows environment ได้.
- ต่อมา Bom เลื่อน Windows 10/11 native UAT ไปหลัง Release จึงไม่ใช้ BTHL0564 เป็น current Phase 4 gate แล้ว; เก็บผลล้มเหลวนี้เป็น historical evidence และยังห้าม claim native x64 pass.

### Real-device acceptance and Windows UAT deferral — 2026-08-22

- Bom เลื่อน Windows 10 x64 และ Windows 11 x64 native UAT ไปหลัง Release; รายการนี้ไม่ใช่หลักฐานที่ผ่านและห้ามใช้ claim customer compatibility.
- Controlled scope คือ Slot 1 `10.244.116.6` เท่านั้น: SNMP และ fingerprint-pinned Administrator Web Connection ให้ Total ตรงกัน `266,488`; baseline จริง `2026-08-11` ถึง `2026-08-22` มี Total delta `2,260`.
- Production pricing functions คำนวณ real delta ได้ gross `3,542.80` และ net หลัง waste 2% `3,471.94`, ตรงสูตรอิสระ. Isolated Report/Excel จาก real history สร้างครบ 3 sheets, 9 วันที่ไม่ซ้ำ, totals ตรง canonical Hold/fail-closed และไม่พบ IP/Serial/Credential ใน workbook.
- Slot 2 `10.244.116.8` ไม่ตอบ SNMP/HTTP/HTTPS หลังตรวจซ้ำ จึงอยู่นอก acceptance scope รอบนี้. ไม่มีการส่งงานพิมพ์ แก้ค่าหน้าเครื่อง หรือแก้ฐานข้อมูลต้นฉบับ.
- Phase 4 blocker ที่เหลือคือ approved Windows production code signing และ Authenticode verification; Product Production GO ยังขึ้นกับ Registration/Privacy gates ของ Phase 2 แยกต่างหาก.

### Objective

สร้าง Windows 10/11 x64 Release Candidate จาก source `5.1.0` ที่ผ่าน Phase 0–2 ให้ติดตั้ง เปิดใช้งาน อัปเกรด สำรอง/กู้คืน และถอนติดตั้งได้บนเครื่องจริง โดยคง Meter/Billing/Report semantics และ Registration fail-closed; macOS เป็น Internal UAT และ Linux deferred.

### Scope in

- แยก task workbook/thread/branch ของ Phase 4 และยืนยัน baseline commit, version, dependency locks และ release gates ก่อนแก้ package.
- สร้าง Windows x64 package/installer จาก canonical source พร้อม artifact identity, SHA256, source commit และรายการไฟล์.
- Native clean install, first-run Setup, Desktop launch, Tray, Auto-start, OS vault, LAN Web HTTPS และ restart UAT บน Windows 10/11 x64.
- ทดสอบ upgrade จาก V5.0/V5.1 data ที่อนุญาตผ่านสำเนา, SQLite backup/integrity, restore/rollback และเปิดข้อมูลเดิมได้.
- Controlled real-device Meter/Billing/Report/Excel acceptance โดยห้ามแก้ข้อมูลลูกค้านอก test scope และห้าม claim จาก Lab/offscreen แทน native proof.
- ตรวจ release artifact ด้วย Phase 0 safety gate, dependency/security regression, secret/data scan, SBOM/checksum และ support/recovery guide.
- macOS arm64 Internal UAT สำหรับ bundle launch, tray, printer read และ restore; ห้าม claim customer Production จน signing/notarization ผ่าน.

### Scope out

- Production Phase 3 update manifest/download/updater ทุกชนิด.
- เปิด Production Registration/Heartbeat ก่อน OpenAPI/Staging และ Registration Data Notice/Hosting Security gates ผ่าน.
- Forced/silent update, remote command, Linux production package และการเปลี่ยน Meter/Billing calculation.
- ส่ง DB, log, credential, counter, user หรือเอกสารออกภายนอก.

### Definition of Done

- Windows 10/11 x64 native UAT ถูก Deferred หลัง Release ตามคำสั่ง Bom; ต้องคง backlog และห้าม claim ว่าผ่าน.
- Upgrade + backup + integrity check + restore/rollback ผ่านโดย Devices, Prices, History และ Billing Ledger ไม่สูญหายหรือเปลี่ยนความหมาย.
- Controlled printer/billing acceptance สำหรับ authorized Slot 1 มี SNMP/Web raw meter provenance, expected delta, production Billing projection และ fail-closed Report/Export totals ตรงกัน; unsafe canonical ledger ยังคง Hold.
- Release artifact ไม่มี DB/CSV/log/env/credential/customer evidence, มี SHA256/SBOM/source commit และ build identity ที่ตรวจย้อนกลับได้.
- Full Python/Web/security/release-safety regression ผ่าน; repository/private origin clean และ support/recovery runbook ใช้งานได้.
- Registration ยังคง fail-closed และ Update ไม่มีอยู่ใน artifact/runtime path ของ Release นี้.
- ถ้า code signing หรือ Windows native evidence ยังไม่ครบ ให้รายงาน RC blocked ตามจริงและห้าม claim Production GO.

## Production Phase 5 — Pilot Release & Go-Live Readiness — HOLD 2026-08-22

- Integration branch `codex/phase-5-pilot-go-live` เริ่มจาก Phase 4 latest `ab529ec` และรวม Phase 2 Data Notice
  `e2a90e5`; source ที่ผ่าน gate ล่าสุดคือ `be48735` และ decision workbook ถูก push ที่ `f9334e7`;
  `main`/`origin/main` ยังอยู่ `6248ef2` และยังไม่ merge.
- Integrated regression ผ่าน: Python `518 passed`, Registration focused `141 passed`, Pilot/release focused `29 passed`,
  Web type/security/build, live TLS/auth และ Python/npm dependency audit ผ่าน.
- unsigned Windows artifact ผ่าน ARM VM preflight: SHA256 `39807a0645…`, source commit `be48735`,
  `unverified-blocked` / Authenticode `NotSigned`, `production_go=false`; ไม่ใช่ native Windows x64 UAT.
- unsigned Pilot bundle SHA256 `36c2853ff0…` มี source commit/checksum/manifest/SBOM, Publisher warning,
  support/pilot/rollback guides, Registration fail-closed และไม่มี Phase 3 Update runtime.
- isolated recovery และ Windows ARM VM install/backup/restore/uninstall/reinstall ผ่านโดยรักษา
  Devices/Prices/History/Billing Ledger; controlled-printer evidenceใช้ authorized Phase 4 Slot 1 ของวันเดียวกัน
  เพราะ diff ไม่แตะ Meter/Billing/Report/Excel และไม่ได้ยิงเครื่องจริงซ้ำ.
- Registration E2E เป็น **HOLD — SAFE**: ไม่พบ deployed OpenAPI v2, verified staging base URL, bootstrap/token lifecycle,
  retention execution และ Dashboard role/read-back artefact จึงไม่เปิด vaultและไม่ยิง production แทน.
- คำตัดสินคือ **PILOT HOLD** จนได้รับ non-secret OpenAPI 3.x, staging environment/base URL proof,
  bootstrap method/vault reference, token rotate/revoke/error contract, retention/access/deletion และ Dashboard role artefact
  แล้วรัน synthetic E2E/read-back/cleanup สำเร็จ. Phase 3 Update, signing, native Windows x64 และ Linux ยัง Deferred ไม่ใช่ Passed.
- Final Phase 5 correction: API/connection/vault reference และ authenticated Dashboard เป็น live; backend-compatible synthetic
  lifecycle/read-back/deactivate ผ่าน แต่ current Desktop schema v2 ส่ง `serial_number` แล้ว live canonical endpoint
  `https://www.dmskm.com` ตอบ HTTP 422 เพราะ deployed allow-list/persistence/Dashboard ยังใช้ `device_instance_id`.
  Approved source gate คง `be48735cc43703f2f7f172d08562ae895da77793`; docs close `1c6bf94`; decision ยัง `PILOT HOLD`.

## Production Phase 6 — Customer Release Packaging — RELEASE HOLD 2026-08-22

- Dedicated branch/worktree `codex/phase-6-customer-release-packaging` สร้างโดยไม่ checkout/แก้ canonical Phase 5 worktree.
- macOS arm64 customer-behavior app/ZIP/DMG สร้างจาก artifact source `c9c45a67f1e024bd81a5153e7faac881a72ec2ed`:
  ZIP SHA256 `a5b7ba77ed3d5d97faa24fd08ce0e7deb3d4f1f68807d20fe37de0c35c554f84`, DMG SHA256
  `a6dd4c2aaa3c9cb4f02c3c5cd4edb6d5119301f45097cdfec687a0fba6c12f1f`; bundle smoke/DB/graceful exit
  ผ่าน แต่ signing เป็น ad-hoc, ไม่มี Team ID/notarization และ Gatekeeper rejected.
- Windows installer สร้างด้วย Inno Setup ภายใน Windows 11 Pro ARM64 VM จาก clean checkout commit เดียวกัน;
  SHA256 `852b9d8de1f5e05f474f53578542e169fe629877636a139a2f05e44f2f4d7663`, Product 5.1.0,
  Authenticode `NotSigned`. Clean install/first-run/restart/uninstall/reinstall/data preservation/backup/restore-on-copy ผ่าน;
  เป็น ARM64 VM/x64 emulation preflight และ Tray/Auto-start/LAN Web exact-installer UAT ยังไม่ผ่านหลักฐาน.
- Shared internal HOLD bundle `KOMI_Report_V5_1_0_Customer_Release_HOLD.zip` ขนาด 204,797,504 bytes,
  SHA256 `db191ff601b8460dae20619354cff12ba2fb71710912cf5a2f03f6ad613efc8e`; manifest ระบุ approved Phase 5 gate,
  artifact source, assembly commit `881eccb3102a20cacaf03bce03953c1a39515e62`, canonical Registration endpoint,
  checksum/inventory/CycloneDX SBOM และ `production_go=false`; final zip safety/secret scanพบ 0 finding.
- Full exact-source verification ผ่าน: Python `522 passed`, Web type/lint/Next production build/npm audit 0,
  dependency locks/audits และ live TLS/auth/security checks ผ่าน. Phase 3 Update runtime, Lab/demo/Virtual Printer auto-injection,
  mock endpoint, DB/CSV/log/env/credential/customer evidence ไม่อยู่ใน release payload.
- คำตัดสินคือ **RELEASE HOLD**. Unlock ต้อง migrate deployed schema-v2 allow-list/persistence/Dashboard จาก
  `device_instance_id` ไป `serial_number` แล้ว rerun current-client live E2E; จากนั้นปิด Developer ID/notarization,
  Windows Authenticode, native Windows x64 และ Tray/Auto-start/LAN Web gates. ห้ามแก้ Desktop ย้อนกลับและห้ามปล่อย bundle นี้ให้ลูกค้า.

## Definition of Done

### V5.1 Registration and Update

- [x] Canonical source เป็น real directory ที่ `~/Projects/dev/komi-report-v5` และมี rollback link กลับ OneDrive
- [x] Development/UI/package version ถูกกำหนดเป็น `5.1` / `5.1.0`
- [x] First-run แสดง Company, read-only start date/version ใน Setup 4 ขั้น และบันทึก local โดยยังไม่ส่งข้อมูลออก
- [x] Registration Data Notice ไทย/อังกฤษตรง Registration schema-v2 แสดงใน Setup/Settings และติดป้ายยังไม่อนุมัติ
- [ ] Registration Data Notice ฉบับอนุมัติแสดงก่อน Registration API ส่งข้อมูลออก
- [x] ผู้ใช้ V5.0 เดิมได้รับ one-time onboarding โดยไม่ล้าง Devices/Price/History/Billing Ledger
- [ ] Registration offline ใช้งานต่อได้, retry ได้, ไม่สร้างรายการซ้ำ และแสดง Registered/Pending/Failed
- [x] Automated payload test ยืนยันว่า Serial No + Model + Selected + Slot ครบ และไม่มี IP/MAC/Credential/Counter/User/Document/Log
- [ ] Dashboard แสดง Company/installation, version/OS, registered/last seen, lifecycle/heartbeat history,
  Active 7/30/90, discovered Konica count/models และ Serial No + Model + Selected + Local Slot หลัง MFA/RBAC
- [ ] **DEFERRED หลัง Release:** Update check เลือก signed artifact ถูก OS/architecture/channel และ reject checksum/signature ที่ไม่ตรง
- [ ] V5.0 → V5.1 upgrade สร้าง DB backup, migrate, restore/rollback และเปิดข้อมูลเดิมได้ครบ
- [ ] Clean-install/upgrade UAT ผ่านบน target OS จริง; local/offscreen/package check ไม่นับแทน native UAT
- [ ] Hosting security, Registration Data Notice และผู้มีสิทธิ์ publish อนุมัติก่อน Production rollout; Windows signing deferred และต้องติดป้าย unsigned ตามจริง

### V5.0 functional baseline retained

- [x] First launch ตั้งค่าเครื่อง 1–3 เครื่องและ Test All โดย UI ไม่ค้าง
- [x] Model/Serial เติมอัตโนมัติเมื่อเครื่องเชื่อมต่อสำเร็จ
- [x] โปรแกรม Auto-start แบบ Tray และ polling ทำงานตาม normal/peak/fallback rules (local/temp verification; Live LaunchAgent UAT อยู่ในรายการตรวจรับ)
- [x] Daily Cache สร้าง Daily Record แบบ append-only พร้อม immutable evidence และตรวจซ้ำแบบ idempotent
- [x] Overview แสดง current-period Usage จาก Web Connection และอ้างกลับถึง Daily Record/Ledger ได้
- [x] Connection Inspector แสดง SNMP Status, Web Connection Device Meter และ RAM User/Account พร้อม Mock/Live mode
- [x] Pricelist history, cost category และ waste discount ถูกล็อกใน Append-only Billing Ledger
- [x] Import `.txt` แบบ V4.6 ยังทำงานและเข้าสู่ Report workflow เดียวกัน
- [x] Import สำเนา Database V4.6 เฉพาะ Usage History แบบ read-only preview, backup, atomic write และกันข้อมูลซ้ำ
- [x] Usage/กราฟรวม V4.6 → V5 ตาม Slot, เปลี่ยนเครื่องใน Slot เดิมได้โดยไม่คำนวณ Meter ข้าม Baseline และไม่คิด Cost ย้อนหลัง
- [x] ทุก Billing record เก็บ raw source/evidence และตรวจย้อนหลังโดยไม่คำนวณทับประวัติเดิม
- [x] Web Counter ที่ผลรวมไม่ตรงแสดง Needs Review ใน Import, Connection และ Log
- [x] History > ผู้ใช้งานใช้ append-only User/Account Total Counter และไม่คำนวณค่าใช้จ่าย
- [x] Desktop และ Web Reports ใช้ Overview / Users / Printers, ช่วงเวลาเดียว และ Cross-filter โดยไม่เปิดเผย Cache/Ledger เป็นสองยอด
- [x] Web Edition เปิดผ่าน LAN IP ได้, ใช้ฐานข้อมูลเดียวกับ Desktop และไม่ส่ง credential ผ่าน API
- [x] Web Edition มี Login, จัดการรหัสจาก Desktop เท่านั้น, เก็บ hash/ตัด session เก่า และปิด Python API ดิบจาก LAN
- [x] Web Edition ใช้ HTTPS-only LAN listener พร้อม per-install/customer certificate และไม่ expose direct API/HTTP บน LAN
- [x] Live UAT ผ่านอย่างน้อยหนึ่งเครื่องโดย credential ไม่ปรากฏใน log/export
- [ ] Bom ทดลอง workflow หลักและยอมรับผลลัพธ์
