# Issue #19 — ผลพัฒนาและตรวจ Performance

19 กันยายน 2569 · local main ใน worktree ของ task · ฐานก่อนเริ่ม `0fca8e4`

ทำ source ตาม #30–36 แล้ว พร้อมส่งตรวจ source และหลักฐาน
ยังไม่ปิด issues แทนการตรวจรับ ไม่ push และไม่ build installer/release
Host, ข้อมูลลูกค้า และต้นฉบับ Documents ไม่เปลี่ยน

## สิ่งที่เปลี่ยนและวิธีใช้

| Issue | การทำงานหลังแก้ | วิธีตรวจ/ใช้ |
|---|---|---|
| #30 Overview | ส่งช่วงรอบบิลลง SQL ก่อนอ่าน Subject; อ่านสรุป Archive โดยไม่เปิดรายละเอียด; เตรียมผลใน worker | เปิด Overview/เปลี่ยนช่วงได้ระหว่างโหลด; ผลของช่วงหรือฐานเก่าไม่ทับผลใหม่; อ่านไม่สำเร็จมีปุ่มลองใหม่ |
| #31 Settings/Archive | นับเมื่อเปิดส่วน Archive ใน worker; เก็บผลตามฐาน/วัน/การเขียน DB; รวมขอบเขต first/latest ต่อ identity ครั้งเดียว | ระหว่างนับแสดงกำลังโหลดและปิดปุ่มจัดเก็บ; กดตรวจจำนวนใหม่ได้; error ไม่แสดงเป็น 0 |
| #31 งานที่พบต่อ | Billing Audit ไม่อ่าน coverage ทุกปีตอนสร้าง Settings; อ่านเมื่อเปิดแท็บ; ตรวจสถานะ Web เฉพาะส่วนที่เห็นและทำใน worker | เปิดแท็บตรวจรอบบิลแล้วรอผลหรือกด Refresh; ซ่อนหน้าหรือเปลี่ยนคำค้นทิ้งผลเก่า; เปิดการ์ดเครือข่ายใน Advanced แล้วสถานะยังอัปเดต |
| #32 Legacy | สร้างดัชนี/ตาราง Raw ใน worker ครั้งเดียว แทนวนสแกน Raw ทุกช่อง | กลับแท็บเดิมใช้ผลที่เตรียมแล้ว; เก็บ delta ต่อ Slot ต่อเนื่องเมื่อเปลี่ยน Serial; ค่าว่างต่างจาก 0 และยังมีเครื่องหมายรอตรวจ |
| #33 กราฟ | ตรวจต่อจากการคืน native chart ที่ทำใน #18 | สลับแท็บซ้ำและปิดหน้าแล้วตรวจ destroyed/จำนวน wrapper พร้อม RAM ของทั้งหน้าต่าง |
| #34 Web evidence | ตรวจ worker/progress/cancel/atomic replacement ที่ทำใน #18 เพิ่มด้วย 960/4,096 จุด ทั้ง Excel/PDF | ส่งออกแล้วดู progress; ยังรับคลิกระหว่างเขียน; ยกเลิกหรือเขียนไม่สำเร็จไฟล์เดิมยังอยู่ |
| #35 Reports | แชร์ immutable components ระหว่างแท็บตามฐาน/revision/ช่วง; เตรียมแถว Users/Printers/Raw ใน worker; ไม่วาดซ้ำเมื่อผลเดิมครบแล้ว | Users กับ Legacy ใช้ Raw ชุดเดียว; เปลี่ยนช่วง/ฐาน/ข้อมูลใหม่ล้าง cache; เปลี่ยนภาษา/กระดาษเสียยังวาดค่าที่ถูกต้อง |
| #36 หน้าแรก/Devices/Manual | latest_counters หยุดอ่านเมื่อพบ snapshot ของเครื่องปัจจุบัน; คู่มือสร้างภาษาที่เลือกก่อนและ decode รูปเมื่อวาด | เปิดเครื่องพิมพ์เร็วขึ้น; สลับภาษาคู่มือสร้างครั้งเดียว; รูปที่โหลดแล้วไม่ทำให้ตำแหน่งอ่านกระโดด |

`LatestRead` ตรึงฐานแบบ read-only, ใช้ generation/DB guard และ SQLite progress handler
เพื่อยกเลิก query ที่ยังอ่านอยู่ การสร้าง QWidget/กราฟ/ตารางยังอยู่ GUI thread
เมื่อออกจริงหยุด workers; การซ่อนลง tray ไม่เท่ากับออกโปรแกรม

## ผลก่อน–หลังบน fixture เดียวกัน

เครื่องพัฒนา Windows เดิม, Python 3.14.7, PyQt/Qt compile version 6.11.0,
offscreen 1440×900 ฟอนต์/QSS/ภาพจริง; 100 ผู้ใช้ชุดเดียว × 3 เครื่อง × 1,826 วัน
Subject และ Raw อย่างละ 547,800 แถว; Raw มี Total/user/day หนึ่งตัว
ช่วงปี 18 ก.ย. 2025–17 ก.ย. 2026 มี Raw 109,500 แถว ฐานใหญ่ยังไม่ Archive
ต้นฉบับ fixture เปิด read-only และ migrate เฉพาะสำเนาชั่วคราว

วัดก่อนจาก source `0fca8e4` และหลังจาก source งานนี้ทีละโปรเซส
ตัวเลขหลักมาจาก `before-ui.json` / `after-ui.json` ซึ่งจบสำเร็จและล้างสำเนาได้
เป็นรอบวัดบนเครื่องนี้ ไม่ใช่ SLA หรือค่าเฉลี่ยของเครื่องลูกค้า

| เส้นทาง | ก่อน (วินาที) | หลัง (วินาที) | UI gap สูงสุดหลัง |
|---|---:|---:|---:|
| MainWindow construct/show | 5.740 | 1.310 | 1,310 ms |
| Overview initial refresh | 51.054 | 1.951 | 110 ms |
| เปิด Devices ครั้งแรกพร้อม refresh | 4.040 | 0.218 | 218 ms |
| เปิด Reports ครั้งแรก | 4.264 | 4.349 | 514 ms |
| เปิด Settings ครั้งแรก | 25.714 | 2.869 | 2,860 ms |
| เปิด Manual ครั้งแรก | 3.815 | 2.444 | 2,413 ms |
| Users ช่วงปี | 21.060 | 18.226 | 601 ms |
| Reports Overview ช่วงปี | 12.484 | 2.975 | 384 ms |
| Printers ช่วงปี | 3.598 | 0.546 | 174 ms |
| Usage ช่วงปี | 3.547 | 1.123 | 441 ms |
| Legacy ช่วงปี | 29.497 | 1.842 | 115 ms |

- สลับครบ 5 แท็บช่วงปีซ้ำ 5 รอบหลังโหลด: 0.128–0.150 วินาที/ครั้ง,
  gap สูงสุด 54.7 ms; Legacy เดิมกลับแท็บแล้วยังใช้ประมาณ 21.8 วินาที
- Archive metadata ครั้งแรก 6.496 วินาทีใน worker/gap 14.3 ms;
  กลับมาใช้ cache 0.0044 วินาที ไม่รวมเวลาจัดเก็บจริง
- Whole-audit peak working set ก่อน 1,228.99 → หลัง 402.53 MiB
  ช่วง warm 5 รอบ หลังแก้ working set 331.16→331.06 MiB,
  private bytes 292.11→291.93 MiB; ไม่ใช่ผล soak หลายชั่วโมง
- Users/Legacy อ้าง Raw snapshot object เดียวกันจริง และ test ยืนยันอ่าน Raw ครั้งเดียว
- Native chart ปกติหลังปิด: destroyed **22/22**, live wrappers **0**
  ไม่ใช้ diagnostic control ที่ยืดอายุ wrapper มาแทนผล source
- ก่อน/หลัง UI harness สกัด network attempts 162/6 ครั้งก่อนเชื่อมต่อ
  ผลนี้ไม่ใช้รับรอง real-network timeout; ทดสอบ visibility ของการ์ดเครือข่ายซ้ำหลังเก็บ benchmark

ยังมีข้อยกเว้นจากเป้าหมาย gap <100 ms: การสร้างหน้าครั้งแรกและตาราง/กราฟบางชุด
ใช้เวลาตามตาราง ไม่ได้อ้างว่าทุกหน้าเปิดทันทีหรือ Reports ทุกเส้นทางเร็วขึ้น

## Query, profile และ Export แยก

- `after-queries.json` วัด service แบบ synchronous เพื่อแยกต้นทุนอ่าน/รวมข้อมูล:
  Subject 30/365 วัน 0.787/10.603 วินาที; Raw 0.858/8.444 วินาที;
  monthly 5 ปี 0.369 วินาที; Archive stats 5.472 วินาที
  ห้ามนำ heartbeat gap ของ query mode มาอ้างว่า production UI ค้าง
- Overview summary แยก 2.803 วินาที โดย Subject ที่กรองเดือนแล้ว 0.555 วินาที
  คืน 300 กลุ่ม เทียบ audit เดิมที่คืน 18,300 กลุ่มทั้งประวัติก่อนกรอง
  มี SQL trace test ตรวจ date boundary และทดสอบยอดเดิม hot/archive/amendments
- cProfile พบ MainWindow เดิม fetchall 2.896 วินาทีเพื่อใช้เพียงค่าล่าสุด;
  Manual decode ภาพใน `_guide_screenshot` 0.752 วินาทีและ layout/addWidget เป็นงานหลัก
  จึงแก้การอ่านเกินจำเป็น/โหลดภาพก่อน ไม่เปลี่ยน QSS จากการนับคำสั่งเพียงอย่างเดียว
- ระหว่างแก้พบ Billing Audit coverage อีก 8.8 วินาทีใน Settings จึงเปลี่ยนเป็น lazy worker
  และพบ Archive JOIN แผนกลางอ่าน slot/serial ซ้ำทุกผู้ใช้จนใช้ 111 วินาที
  แก้ด้วย materialized bounds + CROSS JOIN ให้ scan รายละเอียดครั้งเดียว;
  `after-ui-interim.json` เก็บเป็นหลักฐานกลาง ไม่ใช่ผลสุดท้าย
- `navigation-profile-fixture-after.json` ระบุ QSS/layout/font/images ตามเวลาจริง;
  `navigation-phases.json` แยก import/setup, copy, migration, constructor,
  first paint และ navigation cold/warm ภายใต้ cProfile
  คำว่า cold หมายถึงโปรเซสใหม่ ไม่ได้ล้าง OS disk/font caches
  baseline profile ของ Devices เดิมไม่ได้ mark dirty จึงใช้ UI audit เทียบเส้นทางนี้
  profile ที่ชื่อไม่มี fixture ใช้ฐานว่าง และ before ชุดฐานว่างไม่มีภาพคู่มือครบ

**Export Reports ปีจากฐานจริงของ fixture ผ่าน controller** รวมอ่าน DB และเขียน Excel
69.691 วินาที; มี heartbeat 5,816 ครั้ง/คลิกจำลอง 5,820 ครั้ง, gap สูงสุด 240 ms
อ่าน/เตรียมข้อมูลถึงเริ่ม writer ที่ 19.055 วินาที; เตรียมรายงาน/เขียนจนสำเร็จอีกราว 50.6 วินาที
ตรวจครบ 6 sheets, ผู้ใช้ 100 คน และยอดทุกคน `(10 + i % 5) × 365 × 3` ตรง
เป็น hot fixture; เส้นทางอ่าน Archive ทดสอบ end-to-end ด้วย fixture เล็กแยกใน
`test_report_export_job.py` ทั้งก่อนและหลัง archive ไม่อ้างว่า benchmark ใหญ่รวม cold Archive
ผลเก่า 90 คน/8 counters/797,160 Raw writer 60.101 วินาทีเป็นคนละชุด ห้ามบวกหรือเทียบตรง ๆ

| Web evidence | เวลา | gap สูงสุด |
|---|---:|---:|
| Excel 960 จุด | 2.050 s | 31 ms |
| Excel 4,096 จุด | 3.128 s | 58 ms |
| PDF 960 จุด | 2.022 s | 315 ms |
| PDF 4,096 จุด | 5.794 s | 117 ms |

ทุกชุดใช้ worker/controller, มี timer/คลิกระหว่างเขียน และจบ exit 0
PDF 62/264 หน้า ตรวจข้อความทุกหน้าไม่ว่าง ภาพหน้าแรก/กลาง/ท้ายอ่านได้
การแบ่งงาน PDF ชุดละ 48 แถวยังทำให้บางหน้ามีพื้นที่ว่างมาก เช่นหน้ากลางตัวอย่าง
ไม่มีการตัดข้อมูลเพื่อทำให้เร็ว; เวลา initialize font ครั้งแรกยังเป็นข้อยกเว้น gap

Agent/Desktop idle และ active ใช้เครื่องมือเดิมตรวจซ้ำ: idle Agent 69.08 MiB,
Desktop 99.25 MiB; active Agent 72.03 MiB, Desktop 106.66 MiB;
collector 3 รอบ × 3 เครื่อง × 100 คน × 2 fields ได้ events/outbox 9/9 ทั้งคู่และ exit 0
idle ตัวอย่างละ 5 วินาที และ active หนึ่ง run ไม่ใช่หลักฐาน Web/Host/Chromium หรือ soak จริง

## ผลทดสอบและคู่มือ

**281 กรณีผ่าน เมื่อรวมผลล่าสุดต่อกรณี** ตาม `qa/v5.2.12/issue-19/tests.json`
รอบรวม 255 กรณีเดิมได้ 245 passed/10 failed; แก้แล้วตรวจซ้ำ 84 passed
และ Web evidence/SQL boundary/คู่มืออีก 37 passed (นับซ้ำครั้งเดียว)

ข้อที่แก้จาก regression ได้แก่ list ว่างของ UI ที่เดิมเป็น tuple,
fixture ต้องรอผล async และเปิดการ์ดเครือข่ายที่ถูกย้ายไป Advanced จริง,
mock การออกโปรแกรมต้องตรวจ shutdown ของ reader ใหม่ และ expectation layout เก่าที่ขัด
responsive grid ใน #18 ปรับตามพฤติกรรม #18 โดยคงตรวจไม่ทับ/ไม่ล้น/อ่านยอดครบ
ไม่ลด workload หรือยกเลิกเกณฑ์ตรวจยอดเพื่อให้ผ่าน

ครอบคลุมราคา/Slot/Serial/ช่วงว่าง/ฉบับแก้ไข/Archive เสีย/rollback,
เปลี่ยนช่วงหรือฐานระหว่างโหลด, ยกเลิก SQL/Export, ปิดหน้าหรือออกจริง,
cancel/disk-full/permission/locked-file ด้วย fault injection, แยก 0 จากข้อมูลขาด,
ภาษาและขนาดหน้าจอ รวมการสร้างคู่มือภาษา EN ก่อนและสลับกลับโดยไม่สร้างซ้ำ

อัปเดตคู่มือ Markdown และ PDF 24 หน้า พร้อมภาพ Archive ใหม่
จับภาพ loading/ready/error ของ Archive, Overview retry, คู่มือ ทั้ง TH/EN
ตรวจ PDF ทุกหน้าไม่ว่างและตรวจภาพหน้าที่เปลี่ยน 9–11

## หลักฐานและการตรวจต่อ

- หลักฐาน: [qa/v5.2.12/issue-19/README.md](../qa/v5.2.12/issue-19/README.md)
- คู่มือ: [CUSTOMER_GUIDE_V5_2_12_DRAFT.md](CUSTOMER_GUIDE_V5_2_12_DRAFT.md)
  และ [PDF](customer-guide/KOMI_Report_5.2.12_Source_Guide.pdf)
- เปิด source ที่ตรง commit แล้วลองเปลี่ยนช่วง/แท็บระหว่างโหลด, ลอง Refresh counts,
  Export/Cancel และสลับภาษาคู่มือ; เทียบยอดกับหลักฐาน JSON/XML
- Source/offscreen ยังไม่แทน packaged cold startup, Windows DPI/taskbar/installer,
  เครื่องพิมพ์/เครือข่ายจริง หรือ long soak; A + Proxmox VM105 ยังคงหลัง build
- ไม่เปิด membership ที่เลื่อนรุ่นหน้า และไม่ขอแก้ Host เพื่อให้การทดสอบนี้ผ่าน
