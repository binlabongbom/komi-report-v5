# KOMI Report V5

Desktop-first application ที่รวม Report workflow จาก KOMI Reader V4.6 กับ live Meter collector จาก
KOMI SNMP Profiler ในโปรแกรม PyQt6 เดียวกัน

## V5 workflow

- เปิดครั้งแรกตั้งค่าเครื่อง 1–3 เครื่อง แล้วทดสอบพร้อมกัน
- ดึง Model/Serial Number ด้วย SNMP และอ่าน Counter ละเอียดผ่าน Web Connection
- `Overview` — โครงหน้า V4.6 ที่อ่าน Usage/Cost จาก Posted Billing Ledger ของ V5
- `Import` — หน้ารับข้อมูลสดรายเครื่อง: SNMP status/toner, Web Device Meter และ RAM User/Account
- `Reports` — ดูค่ามิเตอร์สะสม ประวัติย้อนหลัง ค่าใช้จ่าย และ user/account usage
- `Sync Log` — ดู SNMP OID, Web Counter, RAM/Daily Cache, จำนวนครั้งที่อ่าน, Daily Rollup และ polling rules
- `Settings` — เครื่อง, Password, Pricelist, วันตัดรอบ, ส่วนลด, Schedule, Counter ที่ pin และ Backup
- `Manual` — กฎ Sync, แหล่งข้อมูล และวิธีตรวจ Billing Audit

## Background schedule

- SNMP Total Meter ทุก 5 นาที
- Total เพิ่มจึงเรียก Web Connection โดยปกติไม่ถี่กว่า 15 นาที
- ช่วง 07:30–08:30 และ 16:30–17:30 ลด Web throttle เป็น 5 นาที
- SNMP ไม่ตอบให้ลอง Web สูงสุด 5 ครั้ง ห่างครั้งละ 5 นาที ก่อนเป็น Offline
- กดปิดหน้าต่างแล้วโปรแกรมยังทำงานใน System Tray; Exit จาก Tray จึงหยุดจริง
- Auto-start เมื่อ Login และเปิดแบบย่อใน Tray

Full Counter พักใน atomic Daily Cache และรวมเป็น Daily Record หนึ่งรายการต่อเครื่องต่อวัน
จึงไม่บันทึก Snapshot ซ้ำทุก 5–15 นาที แต่ยังตรวจได้ว่า Online/Offline และข้อมูลล่าสุดเมื่อใด

Daily Record ใหม่จะถูกตีความเพียงครั้งเดียวเข้า append-only Billing Ledger พร้อม snapshot ของราคา,
หมวดค่าใช้จ่าย, ส่วนลด, รอบบิล, identity และ source hash. รายการไม่ปลอดภัย/ไม่มี Web success จะเป็น
`Hold` มูลค่า 0 และไม่ถูกปะปนในยอด Usage/Cost; การแก้ไขใช้ reversal/replacement เท่านั้น

ข้อมูลจาก Web Connection ถูก normalize เป็น report shape เดียวกันก่อนบันทึกลง SQLite จึงใช้
Overview, Reports และ billing pipeline ร่วมกันได้ โดย live reading เก็บ `counter_evidence`, source path,
confidence, auth state และ canonical schema `komi.meter.reading.v1` ไว้ตรวจย้อนหลัง

## Read-only policy

- ไม่มี SNMP write
- Web Connection Meter Reader ใช้เฉพาะ read allowlist และ logout/clear session เมื่อจบ
- Username หน้า Setup กำหนดเป็น `administrator`; ไม่มี Password เริ่มต้นและต้องกรอกค่าที่ผู้ดูแลเครื่องกำหนด
- Credential ถูกจำไว้ใน local database โดยตั้งใจ และไม่ถูกเขียนลง log/export
- Printer credential อยู่ใน macOS Keychain/Windows Credential Manager ผ่าน OS vault; SQLite เก็บเฉพาะ reference
- Web Connection ตรวจ trusted TLS หรือ SHA-256 certificate pin โดย default; insecure Lab compatibility ต้องระบุชัด
- Private OID ที่ไม่มีหลักฐานจะไม่ถูกเดาความหมาย

## Setup

ต้องใช้ Python 3.11 ขึ้นไป

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
python app.py
```

บน macOS สามารถดับเบิลคลิก `Open KOMI Report V5.command`

Database ของ Local/Desktop ใช้ path ที่แสดงใน Settings แบบ read-only; การย้าย Database path ยังไม่รองรับ
เพื่อป้องกันการเปิดคนละฐานโดยไม่รู้ตัว

## Verify

```bash
python -m pytest -q
python -m ruff check services v5_pages.py pages.py app.py web_api.py
python -m compileall -q app.py v5_pages.py services
```

## Local release

จากโฟลเดอร์ `source/`:

```bash
python -m PyInstaller --noconfirm --clean app.spec
python tools/build_local_release.py
```

On Windows, PyInstaller creates `dist/KOMI Report V5.1.0/` with the launchable
`KOMI Report V5.1.0.exe` inside it. Keep the folder together when deploying;
this avoids the long per-launch extraction delay of a one-file executable.

บน macOS จะได้ unsigned local bundle ใน `dist/KOMI Report V5.1.0.app`; source ZIP/checksum/manifest
จะอยู่ใน `../release/`. ขั้นตอนนี้ไม่ publish, sign หรือ notarize ออกภายนอก

## Source lineage

- Report shell/parser/database: `dev/komi-reader-v4.6/source`
- Device services/connectors: `dev/komi-snmp-profiler/src/komi_snmp_profiler`
- V5 source projects remain unchanged and serve as read-only references after the initial import
