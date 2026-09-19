# KOMI Report 5.2.12 — ตรวจ Performance ก่อน build

ตรวจ 19 กันยายน 2569 ต่อจาก QSS/UX audit บน source `59544e6` (โค้ดโปรแกรมเท่ากับ
`64a512a`) รอบนี้เพิ่มเครื่องมือวัดและบันทึกผล **ยังไม่ได้แก้โค้ดโปรแกรมหรือ build**

**พบงานเร่งด่วน 5 กลุ่ม (P1) และงานปรับเพิ่มเติม 2 กลุ่ม (P2)** การส่งออก Excel
หน้า Reports ที่แก้แล้วไม่ได้ครอบคลุมหน้าหลัก, Settings, Legacy และ Export หลักฐาน Web
จึงยังไม่ควรใช้ผล Export เดิมรับรอง performance ของทั้งโปรแกรม

## วิธีวัดและขอบเขต

- Windows, Python 3.14.7, PyQt/Qt 6.11.0; CPU ที่ Windows รายงานเป็น Xeon E5-2630 v3
  สองรายการ รวม 8 logical processors; RAM 19.63 GiB ใช้ interpreter ของโครงการเดิม
- Qt offscreen 1440×900; ใช้ฟอนต์โครงการ ปรับเฉพาะขนาดจอจำลองที่ Qt รายงานเป็น 800×800
  ไม่เปลี่ยนโค้ดโหลดข้อมูลหรือ layout; ไม่ใช่การวัด GPU/การลากหน้าต่าง Windows จริง
- ใช้สำเนาฐานจำลองจาก benchmark เดิม ตรวจ Serial `FIXTURE-0..2` และ IP `192.0.2.10..12`
  ก่อนคัดลอก ต้นฉบับเปิด read-only; migration ทำเฉพาะสำเนาชั่วคราว (ตรวจ PRAGMA ได้ schema 30)
- ฐาน **ยังไม่ Archive**: 100 ผู้ใช้ชุดเดียวกัน × 3 เครื่อง, 1,826 วัน, Subject 547,800 แถว,
  Raw 547,800 แถว, daily Meter/Ledger อย่างละ 5,478 แถว; Raw มี Total ต่อผู้ใช้หนึ่งตัว
  ขนาดต้นฉบับ 415.32 MiB ไม่ใช่ข้อมูล Web ทุก Counter ทุก 15 นาทีตลอด 5 ปี
- วัด MainWindow จริง, navigation 5 หน้า, Reports 5 แท็บทั้งเดือนล่าสุดและช่วง
  18 ก.ย. 2025–17 ก.ย. 2026; สลับแท็บช่วงปีซ้ำ 5 รอบ รวม 41 ขั้นการวัด
- ใช้ Qt timer 10 ms วัดช่วงห่างระหว่าง callbacks; ช่องว่างยาวหมายถึง event loop
  ไม่ได้ให้บริการตามปกติ รวมผลของ Python/GIL และการวาด ไม่ใช่เพียงเวลา SQL
  เวลาจนพร้อมไม่รวมการเตรียม fixture/import modules; ไม่ใช่เวลา cold boot ของตัวติดตั้ง
- แต่ละชุดรันทีละ process ไม่มี benchmark อื่นในรอบนี้รันแข่งกัน เป็นการวัดเครื่องนี้
  ไม่ใช่ SLA/ค่าเฉลี่ยหลายเครื่อง; ไม่รับรองว่าตัวเลขนี้จะเหมือนเครื่องลูกค้า
- ไม่เริ่ม Host, real printer, Web service หรือ background services ของ MainWindow;
  hook บล็อก network/process launch ก่อนทำงาน ชุด UI พบ `socket.connect` ที่ถูกสกัด
  159 ครั้ง (Settings มีการตรวจสถานะ Web เป็นระยะ) ไม่มี connection สำเร็จ;
  ชุด query/evidence/chart ไม่มี attempt จึงไม่ใช้ผลนี้อ้างเวลา timeout ของเครือข่ายจริง

หลักฐานทั้งหมดอยู่ที่ [qa/v5.2.12/performance-audit](../qa/v5.2.12/performance-audit/README.md)
และทำซ้ำได้ด้วย [tools/audit_performance_v5.py](../tools/audit_performance_v5.py)

## P1-01: หน้าหลักโหลดประวัติผู้ใช้ทุกปีก่อนกรอง ทำให้ UI ค้างและ RAM พุ่ง

- `MainWindow._refresh_all()` → `PageOverviewV2.refresh()` → `build_overview_summary()`
  ใช้ **57.22 วินาทีบน UI thread**; process peak working set **1,234.13 MiB**
  หลังจบลดเหลือประมาณ 134 MiB จึงไม่ใช่ RAM ค้าง 1.2 GiB ตลอดเวลา
- วัด service แยกอีกครั้งได้ 52.72 วินาที โดย `load_subject_history()` กิน 50.60 วินาที
  คืน 18,300 กลุ่มรายเดือนก่อนค่อยเลือกช่วงที่ต้องแสดง
- ต้นเหตุ: `source/services/summary_service.py:433` เรียกโดยไม่ส่งช่วงวัน;
  `source/services/subject_history.py:625` fetchall และสร้างหลายชุดข้อมูลใน RAM
  ทั้งที่หน้าจอเลือกเพียงเดือนเดียว เส้นทาง Reports ใหม่กรอง SQL แล้ว แต่ Overview ยังไม่ได้ใช้
- ผลกระทบ: เปิดหน้าหลัก/เปลี่ยนช่วง/รับผลอ่านใหม่แล้วรีเฟรช อาจหยุดตอบสนองซ้ำ
  Archive จะลดจำนวนแถว แต่ไม่แก้การทำงานหนักบน UI thread และช่วงก่อน Archive เสร็จ
- แนวแก้: ส่งช่วงที่เลือกลง query, ใช้สรุปรายเดือนสำหรับช่วงเก่า, โหลด/รวมผลใน worker,
  ทิ้งผลรุ่นเก่าหากเปลี่ยนช่วง และเก็บ snapshot ตาม data revision
- ตรวจหลังแก้: ยอด/Top users/ราคา/ฉบับแก้ไขตรงเดิม ทั้ง hot/archive; หน้าจอยังกดเปลี่ยนหน้าได้
  และไม่มีการ materialize ประวัติผู้ใช้ทั้ง 5 ปีเพื่อแสดงเดือนเดียว

## P1-02: เปิด Settings แล้วนับ Archive แบบเต็มฐานบน UI thread

- เปิด Settings ครั้งแรก **33.03 วินาที**, ช่วง timer เงียบยาวสุด **32.76 วินาที**
- `PageSettingsV5` สร้าง `ArchiveSettingsPanel` แม้ยังไม่ได้เปิดส่วนขั้นสูง;
  constructor เรียก `refresh()` → `HistoryArchive.stats()` แบบ synchronous
  (`source/v5_pages.py:12846`, `source/ui/archive_settings.py:41`)
- `ReportDetailArchive.stats()` นับทุกแถวที่เก่าพร้อม correlated EXISTS ตรวจฐานแรก/ล่าสุด
  (`source/services/report_detail_archive.py:77`); วัด stats แยกได้ **14.01 วินาที**
  เป็นส่วนหนึ่งของเวลาหน้า Settings ไม่ใช่หลักฐานว่าทั้ง 33 วินาทีมาจากคำสั่งเดียว
- แนวแก้: เปิด panel ก่อน, โหลด metadata ใน worker เฉพาะเมื่อเรียกดู, cache จำนวนตาม revision;
  ตรวจ query plan/index และแยกการนับเพื่อแสดงออกจากการตรวจความปลอดภัยก่อน Archive จริง
- ตรวจหลังแก้: เลื่อน/สลับ Settings ได้ระหว่างนับ; ข้อมูล pending ไม่แสดงเป็นศูนย์เทียม;
  เงื่อนไขเก็บฐานแรก/ล่าสุดและความปลอดภัยของ Archive ต้องเหมือนเดิม

## P1-03: Legacy คำนวณ Raw ซ้ำทุกช่องบน UI thread แม้ข้อมูลอยู่ใน cache

- เปิด Legacy ช่วงปี: **33.79 วินาที**, UI เงียบสูงสุด **21.46 วินาที**
- สลับกลับแบบข้อมูล cache ครบแล้ว 5 ครั้งยังใช้ **18.32–22.88 วินาที/ครั้ง**
  จึงยืนยันได้ว่าการปรับ SQL อย่างเดียวไม่เพียงพอ
- `source/ui/cloud_reports.py:1809` วนผู้ใช้ × คอลัมน์ แล้วสแกน `subject_rows` ทั้งหมด
  ในแต่ละช่อง; ชุดนี้มี Raw 109,500 แถวและหนึ่ง Counter ต่อผู้ใช้เท่านั้น
  การเพิ่ม Counter จริงจะเพิ่มงานอีก แต่ยังไม่ใช้ตัวเลขคูณคาดการณ์เป็นผลวัด
- แนวแก้: ทำ index/aggregate ครั้งเดียวตาม subject, slot, serial, field, source_path;
  เตรียม row model ใน worker แล้วอัปเดตเฉพาะตารางที่เห็น ใช้ cache ตาม revision
- ตรวจหลังแก้: ค่าฐาน/มิเตอร์สะสม/ช่วงเปลี่ยน Serial/ช่องไม่มีข้อมูลต้องตรงเดิม;
  กลับแท็บ cache แล้วไม่คำนวณทุกแถวซ้ำและ UI ยังตอบสนอง

## P1-04: กราฟเก่ามีเส้นทางไม่คืน native object หลังเปลี่ยนกราฟ

- ทดสอบสลับ Reports ช่วงปี 5 รอบ: working set เพิ่มจาก 576.3 เป็น **607.2 MiB**;
  จำนวน cache keys/ช่วงวันไม่เพิ่ม อาการนี้เพียงอย่างเดียวยังแยก allocator cache กับ leak ไม่ได้
- จึงทดสอบ lifecycle แยกด้วยข้อมูล 90 ผู้ใช้/3 เครื่อง/2 วัน: แทนกราฟ Overview 10 ครั้ง
  จับ `destroyed` ของกราฟ 22 ตัว โดย callback เก็บเพียงเลข pointer และ weak reference
  หลัง GC/deferred delete/ปิด widget พบ destroyed **2/22**
- ชุดควบคุมเฉพาะ harness เก็บ Python wrapper ของกราฟเดิมไว้ระหว่าง `setChart()`
  พบ destroyed **22/22**; SIP รายงานกราฟเดิมกลับเป็น Python-owned หลังแทนที่
  การวัด ownership เปลี่ยนอายุ wrapper จึงแยกผลควบคุมไว้ ไม่อ้างเป็นผล source ปกติ
- Source แทนกราฟโดยตรง 7 จุดใน `source/ui/cloud_reports.py` เช่นบรรทัด 2189/2276/2432/2725
  ไม่มีขั้นเก็บและลบกราฟเก่า ซึ่งตรงกับเงื่อนไขที่ Qt ระบุว่าผู้เรียกต้องจัดการกราฟที่ถูกแทน
  [Qt QChartView::setChart](https://doc.qt.io/qt-6/qchartview-qtcharts.html#setChart)
- แนวแก้: helper จัดอายุกราฟเดิมทุกจุด เช่นเก็บ old ก่อนแทนแล้ว `deleteLater()`
  ตามตัวอย่างใน `WebEvidenceDialog._replace_chart`; ตรวจจุดอื่นนอก Reports เพิ่ม
- ตรวจหลังแก้: native chart destroyed ครบหลังปิด และ RAM เข้าสู่ระดับคงที่ในการสลับซ้ำ
  ไม่สรุปว่า RAM ที่เพิ่มทั้งหมด 30.9 MiB มาจากกราฟเพียงอย่างเดียว

## P1-05: Export หลักฐาน Web ยังทำงานบน UI thread

หน้า Web evidence มีขอบเขตไม่เกิน 4,096 events/32 MiB; ทดสอบเฉพาะ projection หนึ่ง Counter
32 จุด/วัน ไม่ได้ใช้ข้อมูล 1 ปี × 32 จุด/วันที่เกินขอบเขตหน้าจอ

| งาน | จำนวนจุด | เวลางาน / UI gap โดยประมาณ |
|---|---:|---:|
| แสดงตาราง/กราฟ 30 วัน | 960 | 0.46 วินาที |
| Excel 30 วัน | 960 | 1.67 วินาที |
| แสดงตาราง/กราฟ 128 วัน | 4,096 | 1.58 วินาที |
| Excel 128 วัน | 4,096 | 2.85 วินาที |
| PDF 128 วัน | 4,096 | **18.90 วินาที** |

`source/ui/web_evidence_report.py:349` เรียก writer จาก handler โดยตรง;
PDF สร้าง HTML ทุกแถว/จัดหน้า/พิมพ์ใน callback เดียว ไม่มี progress/cancel
ผล Excel ตรวจจำนวนแถวถูกต้อง; PDF ตรวจ header/ไฟล์ไม่ว่าง ไม่ใช่การรับรองหน้ากระดาษทุกหน้า

แนวแก้: ใช้งาน worker/progress/cancel/atomic file แบบ Reports โดยเลือกวิธีจัดหน้า PDF
ที่ใช้ได้ใน worker อย่างถูกต้อง ห้ามส่ง widget GUI ข้าม thread; แบ่งการ render ตารางยาว
และตรวจทั้งยกเลิก/ไฟล์ถูกเปิดอยู่/เขียนไม่สำเร็จโดยไฟล์เดิมไม่เสียหาย

## P2-06: Reports โหลดปีได้ แต่ยังรอนานและเก็บ Raw ซ้ำตามแท็บ

| หน้าหรือแท็บ | จนข้อมูลพร้อม | UI gap สูงสุด |
|---|---:|---:|
| Reports เปิดครั้งแรก/เดือนล่าสุด | 4.29 วินาที | 0.63 วินาที |
| Users เดือนล่าสุด | 3.94 วินาที | 0.62 วินาที |
| Users 1 ปี | **18.81 วินาที** | 1.06 วินาที |
| Overview ใน Reports 1 ปี | 13.50 วินาที | 0.94 วินาที |
| Printers 1 ปี | 3.67 วินาที | 0.41 วินาที |
| Usage 1 ปี | 3.42 วินาที | 0.64 วินาที |

Queries แยก: สรุปเครื่องทุกเดือนใน 5 ปี 0.30 วินาที; Subject/Raw 30 วัน 0.66/1.18 วินาที;
Subject/Raw 365 วัน **7.53/9.74 วินาที** โดยคืน 300 กลุ่ม/109,500 Raw แถว
timer gap ในไฟล์ queries เป็นผลการเรียก service ตรงเพื่อวัดเวลา **ไม่ใช่** หลักฐานว่า
Reports เรียก query เหล่านี้บน UI thread — หน้า Reports ใช้ worker จริง

Cache ของ Users และ Legacy ต่างเก็บ 109,500 Raw records ของช่วงเดียวกัน;
การรวม user rows/วาดตาราง/กราฟยังอยู่ใน UI. แนวแก้: share immutable snapshot ตาม DB/revision/ช่วง,
สร้าง model ใน worker, ไม่วาดแท็บเดิมซ้ำหาก revision ไม่เปลี่ยน และอ่านรายละเอียดเท่าที่ใช้
ต้องรักษายอด/ฐาน Serial/Archive/ฉบับแก้ไขทั้งหมด

## P2-07: การสร้างหน้าครั้งแรกยังเป็นก้อนใหญ่

สร้างและ show MainWindow 5.21 วินาที (ก่อน refresh หนัก); เปิด Devices 3.74 วินาที;
Manual 3.99 วินาทีโดย event loop เงียบเกือบทั้งช่วง MainWindow มี deferred pages แล้ว
แต่เลื่อน constructor ไป event turn ถัดไปไม่ได้ทำให้ตัว constructor ไม่บล็อก

ควรแยกโหลดข้อมูล/รูปตามส่วนที่เห็น เก็บผลคำนวณและแบ่งการสร้าง widget ที่ไม่จำเป็นทันที
ยังไม่มี profile แยกว่ากี่มิลลิวินาทีเป็น QSS, font, image decoding หรือ layout
จึง **ไม่สรุปว่าจำนวน QSS เป็นสาเหตุหลัก** จากผลนี้

## สิ่งที่ผ่านและข้อจำกัดของหลักฐานเดิม

- วัด footprint ใหม่หนึ่งรอบ/โหมด: Desktop idle **99.62 MiB**, Agent idle **70.70 MiB**
  ในหน้าต่างวัด 5 วินาที CPU 0.00%/0.31% ของหนึ่ง core; เป็นช่วงสั้น/ฐานว่าง/ไม่มี Web service
- จำลอง collector 3 เครื่อง × 100 ผู้ใช้ × 2 counters × 3 รอบ ทุก 1 วินาที:
  Desktop peak 109.95 MiB, Agent 74.06 MiB; Web events/outbox ครบ 9/9 ทั้งคู่ ปิดสะอาด
  CPU ใน stress นี้ประมาณหนึ่ง core เพราะเร่งรอบอ่าน **ไม่ใช่** CPU ตอนใช้งานตามตารางปกติ
- ผล Reports Excel เดิม 90 ผู้ใช้/3 เครื่อง/365 วัน/797,160 Raw rows:
  60.101 วินาที, timer/clicks 3,758, gap 135 ms; ยังเป็นหลักฐานที่ใช้ได้กับ writer/controller
  แต่เริ่มจากข้อมูลใน RAM **ไม่รวม DB/Archive read** และคนละ fixture กับ audit รอบนี้
  จึงไม่เอา 60 วินาทีไปบวกกับ query รอบนี้แล้วอ้างเป็นเวลา Export จริงทั้งหมด
- ผล Archive 5 ปีเดิมมีแล้ว (`docs/qa/v5.2.12/five-year-archive.json`):
  initial archive 430.024 วินาที, 224 files; ไม่ได้รันซ้ำรอบนี้ ไฟล์ benchmark รุ่นแรกที่บอก
  “ยังต้องพัฒนา Archive” เป็นประวัติเก่า ไม่ใช่สถานะปัจจุบัน
- ยังไม่ได้วัด packaged cold start, production Host/Web/Chromium รวมทุก process,
  real printer/network, 8–24 ชั่วโมง soak, และ A + VM105. การติดตั้งสองเครื่องคงไว้หลัง build
- ชุด UI วัดครบ 41 ขั้น ไม่มี report error; network attempts ถูก hook บล็อกตามขอบเขตข้างต้น
  แต่จบ exit 1 ตอน harness
  ลบฐานชั่วคราวเพราะ connection ที่เครื่องมือเปิดเองยังไม่ close; ไม่ใช่โปรแกรม crash
  แก้ harness ให้ใช้ closing แล้ว ชุด query/evidence/chart จบสะอาด และเก็บกวาดไฟล์ UI หลังจบ process
  ไม่อ้างว่า rerun UI ทั้งชุดหลังแก้ cleanup แล้ว

## ลำดับงานที่เพิ่มในแผน

1. แก้ Overview query + background snapshot และ Settings archive stats
2. แก้ Legacy indexing/model worker และคืนกราฟเดิมทุกจุด
3. ย้าย Web evidence export ไปงานเบื้องหลังพร้อม progress/cancel
4. ลดข้อมูลซ้ำ/เวลารอใน Reports และการสร้าง Devices/Manual ครั้งแรก
5. วัดซ้ำด้วย fixture เดิม ตรวจผลตัวเลขและการตอบสนองพร้อมกัน แล้วอัปเดตคู่มือ/สถานะก่อน build

เกณฑ์ทางวิศวกรรมที่เสนอ: งานหนักต้องยังเปลี่ยนหน้า/ยกเลิกได้; เล็ง gap ส่วนใหญ่ต่ำกว่า 100 ms
และไม่มีช่วงค้างยาวระดับวินาทีในเส้นทางที่แก้; cached tab ไม่ทำ aggregation ทั้งประวัติซ้ำ;
native charts คืนครบ/RAM ไม่โตต่อเนื่อง การกำหนดเพดานเวลาโหลดรวมควรอิงผลหลังแก้บนเครื่องทดสอบ
โดยไม่ลดความครบของหลักฐาน มิเตอร์ หรือความถูกต้องทางบัญชี
