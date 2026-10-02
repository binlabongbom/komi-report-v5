# Dead code review — 24 September 2026

ตรวจ working tree ปัจจุบัน รวมงาน UI และ Preview ที่ยังไม่ได้ commit รอบนี้เป็นการตรวจ ไม่ได้ลบหรือแก้ source ของแอป

## วิธีตรวจและขอบเขต

- อ่าน AST ของ Python 471 ไฟล์ใน `source` และ `tools` รวม tests เพื่อค้นหาชื่อที่ไม่ถูกอ้างอิง และตรวจซ้ำด้วยการค้นหาทั้ง repository ส่วน source/tool/web/workflow
- Ruff: `F401,F811,F841` ทั้งแบบปกติและ `--ignore-noqa`
- Web: TypeScript `--noEmit --incremental false --noUnusedLocals --noUnusedParameters` และตรวจ entry points/imports ของ Next.js
- ทดลอง Qt แบบ offscreen ด้วยข้อมูลจำลอง 2 users, 3 วัน, 3 เครื่อง แยกจากฐานข้อมูลจริง
- Static analysis ไม่พิสูจน์ว่าโค้ดทั้งหมดไม่มีผู้เรียก: framework callbacks, dynamic lookup, compatibility API และโค้ดเรียกผ่านชื่อข้อความต้องตรวจด้วยคน

## สิ่งที่ควรแก้ก่อน: งานที่ยังทำแต่ไม่แสดงผล

| จุด | หลักฐาน | แนวทาง |
| --- | --- | --- |
| การ์ด Users ที่ถูกถอดจากหน้าจอ | `source/ui/cloud_reports.py:964` ยังสร้าง 6 cards แล้ว `hide()` ที่บรรทัด 986; `_render_users` บรรทัด 2000 ยังคำนวณและตั้งค่า; responsive layout ยังปรับการ์ดด้วย | ตัดการสร้าง/คำนวณ/จัด layout ของการ์ด Users โดยเก็บการ render ตารางและกราฟไว้ |
| การเลือกแถวเครื่องยังวาดกราฟใหม่โดยไม่เปลี่ยนข้อมูล | `_select_printer_row` ที่บรรทัด 2931 เรียก `_render_printers`; ตัว render ใช้ทุกเครื่อง ไม่ใช้ `_selected_printer` เพื่อกรอง และ Meter detail ถูกถอดไปแล้ว | เก็บการเลือกแถวตาม UX ที่ต้องการ แต่เลิกสั่งสร้างตาราง/กราฟทั้งหมดซ้ำเพื่อการเลือกแถว |

ผลทดลอง: มีการ์ด Users 6 ใบ, มองเห็น 0 ใบ แต่มีค่าที่คำนวณแล้วครบทั้ง 6 ใบ เช่น usage=144 และ count=2 การเลือกเครื่องหนึ่งครั้งเรียก render กราฟ 1 รอบ โดยค่าของกราฟทั้งสองเหมือนก่อนเลือกทุกค่า

นี่เป็นหลักฐานว่ามีงานส่วนเกิน แต่ยังไม่ได้วัดเวลาที่ประหยัดได้หลังลบ จึงไม่อ้างว่าจะทำให้แอปเร็วขึ้นเป็นจำนวนวินาทีหรือเปอร์เซ็นต์

Tests บางตัวผูกกับการ์ดที่ซ่อนอยู่ เช่น `test_report_custom_period.py:105` และ `test_cloud_reports_staged.py` ควรเปลี่ยนไปตรวจตาราง/ข้อมูลที่ผู้ใช้เห็นเมื่อลบการ์ด ไม่ควรเก็บ UI ที่เลิกใช้เพียงเพื่อให้ test เก่าผ่าน

## 9 symbol ที่ตรวจแล้วไม่พบผู้เรียกหรือผู้อ่านใน repository

| ไฟล์:บรรทัด | Symbol | รายละเอียด |
| --- | --- | --- |
| `source/ui/cloud_reports.py:2780` | `_multi_line_chart` | กราฟเส้นเก่าประมาณ 50 บรรทัด ไม่มี call site; เมื่อลบแล้ว `QLineSeries` import ในไฟล์นี้จะไม่จำเป็น |
| `source/ui/cloud_reports.py:2943` | `_clear_printer_filter` | ไม่มีปุ่ม/signal/call site เรียก |
| `source/ui/cloud_reports.py:60` | `CYAN` | ค่าสีที่ไม่มีการใช้งาน |
| `source/ui/cloud_reports.py:67` | `COPY_COLORS` | ชุดสีเก่าที่ไม่มีการใช้งาน |
| `source/app.py:730` | `_open_schedule_settings` | ไม่มี navigation/signal เรียก |
| `source/widgets.py:1055` | `info_row` | helper layout ที่ไม่มีผู้เรียก |
| `source/parser_profiles.py:207` | `replace_registry_block` | helper แก้ registry ในข้อความที่ไม่มีผู้เรียก |
| `source/database.py:1319` | `get_latest_read_date` | helper V4.5 ที่ไม่มีผู้เรียก |
| `source/services/report_excel_export.py:70` | `DEVICE_SUBHEADERS` | header แบบเก่า; exporter ปัจจุบันใช้ `OPERATION_DEVICE_SUBHEADERS` |

ห้ามลบ `CATEGORY_FIELDS` ตาม `DEVICE_SUBHEADERS` เพราะยังใช้คำนวณใน exporter หลายจุด และห้ามลบ `QLineSeries` จากไฟล์อื่นที่ยังใช้กราฟเส้น

## กลุ่มใหญ่ที่ควรเก็บกวาดแยกต่างหาก

| จุด | ผลตรวจ | ข้อจำกัดก่อนลบ |
| --- | --- | --- |
| `source/v5_pages.py:7736`, `7890`, `7907`, `8143` | `_refresh_usage_report`, `_set_usage_display_mode`, `_set_management_period`, `_refresh_meter_report` ไม่พบผู้เรียก; `usage_summary_table` และ `meter_table` ไม่มีจุดสร้างใน source ปัจจุบัน | ไล่ helper ที่ใช้ร่วมกับ export/audit ก่อนลบทั้งกลุ่ม |
| `source/v5_pages.py:5989` | `PageConnectionInspector` ไม่มีจุดสร้างใน repository | ยืนยันขอบเขตเครื่องมือวินิจฉัย/ทางเข้าแบบเก่าก่อนถอดทั้ง class |
| `source/live_meter_page.py:52` | `PageLiveMeter` ไม่มีจุดสร้างใน repository | ไม่ควรลบทั้ง module จนตรวจ helper ที่อาจถูก import แยก |
| `source/pages.py:4365` | `PageIndividual` ไม่มีจุดสร้างใน repository | แยกออกจากคลาส Legacy อื่นในไฟล์เดียวกัน |

`PageHistoryV5` ยังมีทาง `staged=False` ที่สร้าง Legacy UI และซ่อนไว้ โดยมี export/reconciliation/Billing Audit พึ่งพาอยู่ ตาม `_build_report_center` บรรทัด 7211 เป็นต้นไป จึงไม่จัดว่า Legacy ทั้งหมดเป็น dead code

## ผลเครื่องมือตรวจ

- Ruff แบบปกติ: 137 diagnostics = F401 57, F811 64, F841 16; อยู่ใน tests 113 และ tools 24; แอป runtime 0 สำหรับกฎที่เลือก
- เมื่อไม่สนใจ `noqa`: พบ import จาก parser 7 รายการใน `database.py:28–35` เพิ่มเติม ต้องตรวจ compatibility/re-export ก่อนลบ ไม่ใช่หลักฐานว่าลบได้ทั้งหมด
- ตัวอย่าง false positive ใน tests: fixture ที่ import ให้ pytest ค้นพบ, fixture parameter ที่ชื่อเหมือน import และตัวแปร `app` ที่ถืออายุ `QApplication`
- AST: 47 definitions และ 38 constants ที่ไม่มี reference ตาม heuristic; จำนวนนี้เป็น candidate ไม่ใช่จำนวน dead code ที่ยืนยันแล้ว
- ไม่พบ syntax error ใน 471 ไฟล์ และไม่พบ statement หลัง return/raise/break/continue ใน block เดียวกันตามการตรวจแบบตรงไปตรงมา ไม่ใช่การพิสูจน์ทุกเส้นทางควบคุม
- Web TypeScript: ผ่านการตรวจ unused local/parameter; ตรวจ Next.js page/layout/route/proxy เป็น framework entry points ไม่ถือว่าไม่มีผู้เรียกเพียงเพราะไม่มี import
- ไม่ลบ Qt overrides เช่น `wheelEvent`, `expandingDirections`, HTTP handlers เช่น `do_POST` หรือ FastAPI routes ที่ framework เรียก

## หลักฐานที่บันทึกไว้

- `outputs/dead-code-ruff-20260924.json`
- `outputs/dead-code-ruff-unsuppressed-20260924.json`
- `outputs/dead-code-ast-20260924.json`
- `outputs/dead-code-web-20260924.txt` — ว่างเพราะ compiler ผ่านโดยไม่มี diagnostic
- `outputs/dead-code-runtime-20260924.json`

ลำดับที่แนะนำ: ลบงานคำนวณ/วาด UI ที่ไม่มีผลกับหน้าจอก่อน จากนั้น 9 symbol ที่ไม่มี reference แล้วจึงเก็บ Legacy เป็นกลุ่มพร้อม regression ของ import/export/audit ไม่ควรใช้ autofix ลบทุกคำเตือน
