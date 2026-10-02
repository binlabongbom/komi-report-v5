# ตรวจความต่อเนื่องมิเตอร์หลังอัปเกรด 5.2.4

ทดสอบ source วันที่ 25 กันยายน 2569 ด้วยฐานข้อมูลจำลองที่สร้างจาก release 5.2.4
commit `aa8bda3` แล้วเปิดด้วย source ปัจจุบัน ไม่มีการแก้ฐานลูกค้าหรือเรียกเครื่องพิมพ์จริง.

## ผล

| กรณี | ผลที่ตรวจยืนยัน |
|---|---|
| Schema 19 → 34 | ข้อมูลเดิมทุกคอลัมน์/ทุกแถวใน 21 ตารางคงเดิม |
| Backup และฐานหลังย้าย | สำรองก่อนย้ายตรงกับต้นฉบับ, integrity ผ่าน, ไม่มี FK violation |
| เปิดโปรแกรมซ้ำ | Migration ไม่ทำซ้ำและข้อมูลเดิมไม่เปลี่ยน |
| รายงานเดิม | เครื่อง 3 เครื่อง, ราคา, บัญชี และประวัติอยู่ครบ; รายงานเดิมรวม 600 หน้า |
| ไม่มี epoch/meter head รูปแบบใหม่ | Setup เดิมผ่าน ไม่ต้องเปิด Wizard ใหม่ |
| ไม่มี LAN enrollment | Runtime ไม่ผูก shared read ไม่เรียก vault หรือเปิด listener |
| มี cache จากรุ่นเก่า ทั้ง 3 Slot | ฐาน 1,000 / ล่าสุด 1,020 / ใช้งาน 20 → อ่าน 1,030 ได้ 30 → อ่าน 1,040 ได้ 40 |
| ไม่มี cache และไม่มี Raw detail | ใช้ยอดปิดที่บันทึกไว้ 1,020 → อ่าน 1,030 ได้ 10 → อ่าน 1,040 ได้ 20 |
| Serial เก่าว่าง แต่ host ในประวัติตรงกัน | อ่านต่อได้โดยรักษาฐานจากยอดปิดเดิม |
| เครื่องในกลุ่ม LAN ไม่มีฐานที่ยืนยันแล้ว | ยังปฏิเสธ ไม่เปลี่ยนไปอ่านแบบ local เพื่อข้ามสิทธิ์ |
| Serial เปลี่ยนระหว่างอ่านแบบแชร์ | หยุดก่อนอ่าน Web และรักษา epoch เดิม |

ไม่ต้องแก้ production code เพื่อให้ standalone upgrade ผ่านกรณีเหล่านี้.
เพิ่ม regression tests ใน `source/tests/test_upgrade_baseline_routing.py` จำนวน 3 cases;
รวมกับชุด runtime config, app setup, migrations, initial baselines, peer network runtime
และ background polling จำนวน 36 cases ที่รันครั้งนี้ เป็น **39 cases ผ่าน**.
Ruff F/E9 ผ่านสำหรับไฟล์ทดสอบใหม่และเครื่องมือซ้อมอัปเกรด.

## ทำซ้ำและหลักฐาน

ใช้ `.venv/Scripts/python.exe tools/audit_legacy_upgrade.py` จาก repository root.
เครื่องมืออาศัย fixture/release checkout ใน
`outputs/upgrade-v5.2.4-name-fix-2026-09-25/` และสร้าง runtime แยกใหม่ทุกครั้ง.
ใช้ Probe/Reader จำลองกับ `BackgroundPollingCoordinator` จริง ไม่เรียก LAN หรือเครื่องพิมพ์.

หลักฐานรอบสุดท้ายหลังรวม Wizard จริงอยู่ที่ `outputs/upgrade-v5.2.4-continuity-20260925-092433/`:

- `result.json`: ย้ายข้อมูล, เทียบ 21 ตาราง, backup, integrity, เปิดซ้ำและรายงาน.
- `continuity-result.json`: เปิด workspace และอ่านต่อโดยรักษา cache เดิมครบ 3 Slot.
- `closed-history-result.json`: ไม่มี cache/Raw detail และ Serial เก่าว่างแต่ host ตรง.

## ขอบเขต

ผลนี้เป็นการทดสอบ source และฐานจำลอง ไม่ใช่การรันตัวติดตั้งทับจริง.
ไม่ครอบคลุมประวัติที่ไม่มีข้อมูลระบุเครื่องเหลือเลย.
รวมขั้นมิเตอร์เข้า production Wizard แล้ว และรันทดสอบอัปเกรดข้างต้นซ้ำผ่าน.
รายละเอียดการสร้างฐานสำหรับเครื่องใหม่แยกอยู่ใน
[ผลพัฒนา Wizard](SETUP_METER_IMPLEMENTATION_2026_09_25.md).

ตัวติดตั้งปัจจุบันใช้ AppId เดิม/UsePreviousAppDir และเก็บข้อมูลผู้ใช้นอกโฟลเดอร์โปรแกรม;
ตัวสร้าง payload ปฏิเสธฐาน `KOMI_Report_V5.db` ในชุดติดตั้ง. ข้อนี้ตรวจจาก source
ไม่ได้ถือเป็นหลักฐานว่าผ่านการรัน installer upgrade แล้ว.
