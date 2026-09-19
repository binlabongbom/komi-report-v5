# ตรวจ QSS และ UX ของ KOMI Report 5.2.12

วันที่ 19 กันยายน 2569 · source ฐาน `64a512a` · ตรวจอย่างเดียว ยังไม่แก้หน้าตาโปรแกรม

พบ **22 กลุ่มประเด็น: P1 3 กลุ่ม, P2 16 กลุ่ม, P3 3 กลุ่ม** ครอบคลุมทั้งการอ่านข้อมูลสำคัญไม่ครบ การบอกความสามารถเกินสิ่งที่เปิดใช้ สถานะควบคุมที่ผู้ใช้แยกไม่ออก และความไม่สอดคล้องของหน้าตา

P1 = ควรแก้ก่อน build เพราะขวางการตรวจยอด/ทำให้เข้าใจผลการทำงานผิด; P2 = ควรแก้ในรอบ UX นี้; P3 = เก็บมาตรฐานหน้าตาและลดความคลาดเคลื่อนภายหลัง ระดับนี้เป็นข้อเสนอจัดลำดับ ไม่ใช่คำอนุมัติให้ build หรือขยายงาน Host

## วิธีตรวจและขอบเขต

- รัน Qt จาก source ด้วยฐานจำลองในโฟลเดอร์ชั่วคราว ไม่ใช้ข้อมูลลูกค้า ไม่เริ่ม background services และปิดการเชื่อมต่อเครือข่ายด้วย audit hook
- ใช้รายงานจำลอง 90 ผู้ใช้ / 3 เครื่องพิมพ์ / 2 วัน เพื่อดูตาราง ชื่อ และยอด; อีกชุดเป็นช่วงขาดการอ่าน 301 หน้า / 2 วัน และรายการบัญชีที่รอตรวจ/แก้ไข
- ตรวจหน้าหลักทั้ง 5 หน้า แท็บย่อยทุกแท็บ, Wizard 4 ขั้น, หน้าต่าง/แผงย่อย 19 ชนิด, แบบฟอร์มย่อยของ Wizard และหน้าตั้งค่าที่ขยายแล้ว
- เก็บ **262 ภาพสถานะ/ขนาด/ภาษา** รวมภาพซ้ำเมื่อเปลี่ยนขนาด ไม่ได้หมายถึง 262 หน้าจออิสระ เก็บภาพหลัก 24 ภาพใน Git ประมาณ 1.36 MB พร้อม manifest และผลทดลอง
- ขนาดเริ่มต้น 1024×640 และ 1440×900 ภาษาไทย; 900×600 ภาษาอังกฤษที่ Qt scale 150%; popup/Wizard ไทย–อังกฤษที่ 100% หน่วยเป็นพื้นที่ภายในหน้าต่างแบบ logical pixels
- วัดความต่างของภาพปุ่ม enabled/disabled/focus, ทดลองบันทึก Counter ว่าง และตรวจการแปลข้อความ/ข้อมูลในฐานจำลองเพิ่มเติม
- รอบที่ใช้ในรายงานทั้ง 12 ชุดจบโดยไม่มี capture error และไม่มี network attempt ข้อผิดพลาดจากการเรียก fixture ในเครื่องมือตรวจช่วงแรกแก้และรันใหม่แล้ว ไม่รวมเป็นปัญหาโปรแกรม

หลักฐาน: [manifest](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/manifest.json>), [ผลวัดปุ่มและพฤติกรรม](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/control-measurements.json>), [เครื่องมือตรวจ](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/tools/audit_ui_v5.py>)

## สิ่งที่พบและวิธีแก้

### UX-01 · P1 · ยอดเงินสรุปถูกย่อจนอ่านจำนวนจริงไม่ได้

หน้า Reports / Overview และ Printers แสดงยอด `฿8,640.00` เป็น `฿8…00` ที่หน้าต่างเล็ก และยังเป็น `฿8,….00` ที่ 1440×900 หัวการ์ดหลายช่องถูกย่อพร้อมกัน ตัวเลขเต็มอยู่ใน tooltip แต่ผู้ใช้ไม่ควรต้องไล่ชี้เมาส์เพื่ออ่านยอดสำคัญ

สาเหตุคือการจำกัดพื้นที่ตัวเลขไว้ 60% ของการ์ด และคงการ์ดหกใบในหนึ่งแถว แก้ด้วยการย้ายตัวเลขลงอีกบรรทัดหรือเรียง 3×2 เมื่อพื้นที่ไม่พอ; ไม่ย่อจำนวนเงินด้วยจุดไข่ปลา เกณฑ์ผ่าน: ยอดหลักพันถึงหลักล้านอ่านครบในขนาดหน้าต่างที่รองรับทั้งสองภาษา

โค้ด: [cloud_reports.py:288](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/cloud_reports.py:288>) · [ภาพหน้าต่างใหญ่](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/reports-currency.png>) · [ภาพหน้าต่างเล็ก](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/reports-small.png>)

### UX-02 · P1 · ข้อความยืนยัน Sync ไม่ตรงขอบเขตที่เปิดใช้ในรุ่นนี้

Popup ยืนยันการตั้งค่าร่วมบอกว่า “มีผลกับคอมพิวเตอร์ทุกเครื่อง” และเครื่องออฟไลน์จะได้รับเมื่อกลับมา แต่ production membership/Sync ต่อเนื่องถูกเลื่อนไปรุ่นหน้า หน้าเครือข่ายเองก็ระบุว่ายังไม่เปิดการเชื่อมสมาชิกอัตโนมัติ ผู้ใช้จึงอาจคิดว่าตั้งค่าเสร็จแล้วทุกเครื่องจะเปลี่ยนตาม

ควรแสดงผลตามความสามารถ runtime จริง: บันทึกบนคอมนี้ / มีรายการรอส่ง / ปลายทางยืนยันรับแล้ว แยกการรับค่าตอนติดตั้งครั้งแรกออกจาก Sync สมาชิกต่อเนื่อง และใช้ข้อความตรงกันใน popup, Wizard, หน้าเครือข่าย และคู่มือ **แก้ข้อความ/การแสดงผลฝั่งโปรแกรม ไม่ทำ Host ในรอบนี้**

โค้ด: [shared_settings_confirmation.py:77](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/shared_settings_confirmation.py:77>), [network_settings.py:128](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/network_settings.py:128>) · [ภาพยืนยัน](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/shared-confirmation.png>) · [ภาพสถานะเครือข่าย](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/network-bottom.png>)

### UX-03 · P2 · ปุ่มที่กดไม่ได้ดูเหมือนปุ่มพร้อมใช้

เทียบภาพปุ่มจริงพบว่า plain, outline, danger และ warning ให้ภาพเหมือนกันเมื่อ enabled กับ disabled ส่วน primary/success แยกได้ จึงเห็นปุ่ม “ยืนยัน” ใน popup ที่ยังไม่มีหลักฐาน, ปุ่ม Archive ที่ไม่มีงาน และปุ่มเปิด Web ขณะบริการปิด ดูพร้อมใช้ หลายปุ่มยังไม่มีกรอบหรือพื้นหลัง ทำให้ดูเป็นข้อความธรรมดา

กำหนด default button style และ disabled style ครบทุก role รวม QDialogButtonBox; แยกปุ่มหลัก/รองให้ชัด และแสดงเหตุผลใกล้ปุ่มเมื่อยังทำต่อไม่ได้ สถานะการปิดใช้งานของโค้ดยังทำงานอยู่ ปัญหาที่พิสูจน์คือภาพที่แสดง ไม่ใช่ปุ่มหลุดให้ยืนยันได้

โค้ด: [config.py:284](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:284>), [billing_repricing.py:53](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/billing_repricing.py:53>) · [ภาพปุ่มยืนยันที่ disabled](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/repricing-disabled.png>)

### UX-04 · P2 · การเปิด Settings ทำให้หน้าต่างขยายเกินขนาดที่กำหนด

เริ่มที่ 1024×640 แต่เมื่อเปิด Settings / สถานะและประวัติ layout ขยายเป็น 1092×703; อังกฤษเริ่ม 900×600 ขยายเป็น 1110×703 ตารางเวลาและเครื่องมือด้านขวายังแน่น ปัญหานี้เพิ่มความเสี่ยงหลุดพื้นที่ทำงานบนจอที่ขยาย 150%

กำหนด minimum size จากเนื้อหาที่จำเป็นจริง ใช้ scroll/reflow ในสถานะและตารางเวลา และทดสอบทุกแท็บในกรอบเดิม ข้อพิสูจน์รอบนี้คือ layout minimum ใน offscreen; การหลุดขอบจอจริงต้องตรวจซ้ำกับ Windows title bar/taskbar หลัง build ไม่อ้างว่าทดสอบจอจริงแล้ว

โค้ด: [v5_pages.py:4780](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/v5_pages.py:4780>), [v5_pages.py:10760](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/v5_pages.py:10760>) · [ภาพตารางเวลา](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/schedule-expanded.png>) · ขนาดจริงทุกภาพอยู่ใน manifest

### UX-05 · P2 · ภาษาอังกฤษถูกแปลเป็นคำผสมไทย–อังกฤษ

ตัวอย่างที่รันได้จริง: `ช่วงที่แสดงอยู่` → `ช่วงที่Showingอยู่`, `ช่วงที่เลือก 31 วัน` → `ช่วงที่Select 31 days` และข้อความ progress มี `เปอร์เซ็นต์Showing...` พบใน Export, Legacy, เครือข่าย และ popup ใหม่หลายตัว ข้อความที่เปลี่ยนจาก timer บางส่วนกลับเป็นไทยอีก

ใช้คำแปลเป็นประโยค/ข้อความที่มีตัวแปร แทนการ replace คำสั้นทั่วทั้งข้อความ เพิ่มคำแปลให้ครบทั้งข้อความเริ่มต้น สถานะรอ ยกเลิก สำเร็จ และผิดพลาด

โค้ด: [i18n.py:865](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/i18n.py:865>), [report_export.py:73](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/report_export.py:73>) · [ภาพ Export ภาษาอังกฤษ](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/export-english.png>)

### UX-06 · P2 · ตัวแปลภาษาแตะข้อมูลชื่อที่ผู้ใช้กรอกด้วย

apply_language แปลทุกเซลล์ของ QTableWidget และทุก item ของ ComboBox โดยไม่แยก label ออกจากข้อมูล ทดลองเซลล์ `บริษัท แสดงผล จำกัด` แล้วแสดงเป็น `บริษัท Showingผล จำกัด` เมื่อเลือกอังกฤษ เป็นการเปลี่ยนข้อความบนจอ ยังไม่ได้พิสูจน์ว่ามีการเขียนชื่อใหม่นี้กลับฐาน

แปลเฉพาะหัวตาราง/label/status ที่กำหนดไว้ ชื่อบริษัท ผู้ใช้ เครื่องพิมพ์ Serial และ raw counter ต้องคงต้นฉบับ เพิ่ม regression ที่มีชื่อไทยซึ่งตรงกับคำใน dictionary

โค้ด: [i18n.py:1007](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/i18n.py:1007>), [i18n.py:1044](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/i18n.py:1044>) · ผลก่อน/หลังใน control-measurements.json

### UX-07 · P2 · แท็บตรวจมิเตอร์ภาษาอังกฤษกลายเป็น Automation

Settings > Status and history มีแท็บ `Automation` แต่เนื้อหาเป็น Review falling counters ทำให้สับสนกับ Automation ที่เป็นแท็บหลักอยู่แล้ว ข้อความต้นทางของแท็บถูกจำตาม index; เมื่อย้ายแท็บ timeline ออก index เดิมถูกใช้กับแท็บใหม่

ผูกคำแปลกับตัว widget/tab identity และล้างหรือย้าย cache เมื่อเปลี่ยนลำดับแท็บ เกณฑ์ผ่าน: ไทยเป็น “ตรวจสอบมิเตอร์” และอังกฤษเป็น “Meter review” หลังเปิดหน้าและสลับภาษาไปกลับ

โค้ด: [i18n.py:1000](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/i18n.py:1000>), [v5_pages.py:12857](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/v5_pages.py:12857>) · [ภาพแท็บผิดชื่อ](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/meter-review-english.png>)

### UX-08 · P2 · ใช้คีย์บอร์ดแล้วไม่รู้ว่าโฟกัสอยู่เมนูไหน

ปุ่ม Sidebar รับ Tab focus จริง แต่ภาพก่อน/หลัง focus เหมือนกันทุกพิกเซลในการทดลอง กฎ `#nav { border:none }` กับการไม่ใส่ focus effect ให้ nav ทำให้กฎ focus ทั่วไปไม่ช่วย

เพิ่ม `#nav:focus` ที่แยกจาก active/hover ชัดเจน และตรวจ Tab → Enter/Space ทั้งห้าเมนู รวมปุ่ม icon/calendar ต้องมีชื่อที่โปรแกรมอ่านหน้าจออ่านได้

โค้ด: [config.py:311](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:311>), [ui_consistency.py:80](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui_consistency.py:80>) · ผล `nav.has_focus=true`, `normal_focused_identical=true` ในผลวัด

### UX-09 · P2 · หน้าเลือก Counter ว่าง แต่บันทึกแล้วล้างค่าที่เคยเลือก

เมื่อไม่มี latest counters ตารางไม่มีแถวแต่ปุ่มบันทึกยังใช้ได้ ทดลองตั้งค่าเดิม `["counter.total.total"]` แล้วบันทึกหน้าว่าง ได้ `[]` ปัญหานี้เกิดกับ preference การแสดง Overview ไม่ใช่การลบประวัติมิเตอร์

แสดง “ยังไม่มี Counter ให้อ่าน/เลือก” ปิดการบันทึกจนโหลดรายการได้ หรือรวมรายการเดิมไว้พร้อมป้าย “ยังไม่มีค่าล่าสุด” การล้างทั้งหมดควรเป็นการกระทำที่ผู้ใช้เลือกเอง

โค้ด: [common_dialogs.py:37](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/common_dialogs.py:37>), [common_dialogs.py:54](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/common_dialogs.py:54>) · [ภาพรายการว่าง](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/pinned-empty.png>)

### UX-10 · P2 · ตารางใช้พื้นที่ผิดสัดส่วนและหมายเหตุอ่านยาก

All Counters ให้ชื่อ Counter กว้างเพียง 100 px แต่ช่องตัวเลขกินพื้นที่ที่เหลือ ชื่อ `counter.total.total` จึงเหลือ `counter...` ทั้งที่หน้าต่างยังว่างมาก ตาราง Slot/แก้ราคา/ฉบับแก้ไขก่อนโหลดมีหัวคอลัมน์ถูกตัด ส่วนตารางหมายเหตุ Web ที่ 900×600 ย่อข้อความหลายบรรทัดเป็น `...`

ให้ชื่อ/คำอธิบายใช้พื้นที่ยืดหยุ่นและตัวเลขพอดีกับค่า แสดง empty state ก่อนโหลด พร้อมอ่านหมายเหตุเต็มผ่านแผงรายละเอียด/ขยายแถว ไม่บังคับพึ่ง tooltip อย่างเดียว **ตาราง Slot และฉบับแก้ไขมี resizeColumnsToContents หลังโหลดอยู่แล้ว** จึงไม่สรุปว่าหัวตารางยังถูกตัดทุกสถานะ

โค้ด: [common_dialogs.py:22](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/common_dialogs.py:22>), [slot_baseline_review.py:50](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/slot_baseline_review.py:50>), [web_evidence_report.py:337](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/web_evidence_report.py:337>) · [Counter](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/counters.png>) · [หมายเหตุ](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/web-evidence-remarks.png>)

### UX-11 · P1 · หน้าตรวจรอบบิลมีรายการ แต่พื้นที่ตารางเหลือเพียงหัวตาราง

ในกรอบเริ่มต้น 1024×640 ซึ่ง layout ขยายไปถึง 1092×703 แล้ว หน้าตรวจรอบบิลยังมีหัวข้อสามชั้น คำอธิบายสองกล่อง ช่องค้นหา และแถวปุ่ม จนตารางเหลือความสูงแทบเฉพาะ header ทั้งที่แสดง “4 จาก 4 รายการ” ผู้ใช้ตรวจเลือกยอดเพื่อแก้ไขไม่ได้สะดวก

ลดหัวข้อซ้ำของ wrapper กับ PageBillingAudit ให้เหลือหัวข้อเดียว สรุปสถานะให้สั้น และให้พื้นที่ตารางมาก่อนคำอธิบายที่ขยายอ่านได้ เกณฑ์ผ่าน: หน้าต่างเล็กที่รองรับต้องเห็นรายการและยอดอย่างน้อยหลายแถวพร้อมปุ่มที่ใช้กับแถวที่เลือก

โค้ด: [v5_pages.py:12457](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/v5_pages.py:12457>), [v5_pages.py:12934](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/v5_pages.py:12934>) · [ภาพตารางที่ไม่มีพื้นที่แสดงแถว](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/billing-audit.png>)

### UX-12 · P2 · หน้าตัดสินใจด้านยอดเงินเต็มไปด้วยศัพท์ภายใน

พบ `Ledger append-only`, `Reversal`, `Replacement`, `missing_or_unsafe_attestation`, hash/idempotency key และ JSON อยู่ในหน้าหลักของการตรวจยอด วันที่ปะปน ISO กับ dd/MM และค่ามิเตอร์บาง popup เป็น 20000 แทน 20,000 ผู้ใช้ต้องแปลโครงสร้างโปรแกรมก่อนตัดสินใจ

แสดงสรุปภาษาผู้ใช้ก่อน: เครื่อง/Slot, วัน, ยอดเดิม→ใหม่, เหตุผลที่รอตรวจ, ผลที่จะเกิดหลังยืนยัน เก็บ JSON/hash ใน “รายละเอียดสำหรับเจ้าหน้าที่” ที่เปิดดูและคัดลอกได้ ใช้ formatter วัน เวลา ตัวเลข และเงินบาทร่วมกัน

โค้ด: [v5_pages.py:12438](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/v5_pages.py:12438>), [billing_manual_review.py:14](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/billing_manual_review.py:14>), [counter_review.py:19](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/counter_review.py:19>) · [ภาพรายละเอียดบัญชี](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/billing-detail.png>)

### UX-13 · P2 · กราฟมีข้อมูล แต่ชื่อและค่าที่จำเป็นอ่านไม่ออก

Top users ย่อชื่อหลายคนจนเป็น `User...` เหมือนกัน; กราฟ Timeline ในหน้าต่างเล็กย่อเลขแกน Y เป็น `...`; Usage ที่มีข้อมูลเพียงเดือนเดียวแสดงเป็นจุดเล็กและจุด Print/Copy ทับกัน แม้ตารางมีข้อมูล ไม่พบการต่อ hover ของ bar series เพื่อช่วยอ่านชื่อ/ยอดเต็ม

ใช้แท่งแนวนอนหรือชื่อสั้นที่แยกคนได้ พร้อม tooltip ชื่อเต็มและจำนวน ตรวจพื้นที่เลขแกนตามขนาดจริง และใช้แท่ง/marker พร้อมค่าเมื่อมีจุดเดียว ไม่เปลี่ยนสูตรยอดจากการแก้กราฟ

โค้ด: [cloud_reports.py:2920](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/cloud_reports.py:2920>), [cloud_reports.py:2958](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/cloud_reports.py:2958>) · [กราฟผู้ใช้](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/reports-users.png>) · [เดือนเดียว](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/reports-usage.png>)

### UX-14 · P2 · “ไม่มีข้อมูล” กับ “ยอดเป็นศูนย์” ยังสื่อไม่ชัด

เมื่อส่งชุดรายงานว่างและไม่มีเวลาอ่านล่าสุด การ์ดประเภทงานเป็น `—` แต่ยอดรวมเป็น `0` และค่าใช้จ่ายเป็น `฿0.00` ผู้ใช้จึงอาจเข้าใจว่าอ่านครบแล้วและไม่มีการใช้ ส่วน Web evidence ก่อนโหลดมี ComboBox ว่างสองช่องและพื้นที่กราฟว่างโดยยังไม่มีคำแนะนำขั้นถัดไปชัดเจน

แยกสถานะยังไม่เคยอ่าน / ไม่มีรายการในช่วงนี้ / อ่านได้และเป็นศูนย์ / กำลังโหลด / อ่านไม่สำเร็จ ให้ชัด ใช้ `—` เมื่อยังสรุปไม่ได้ พร้อมปุ่มเลือกช่วงหรืออ่านข้อมูล กรณีอ่านผิดพลาดปัจจุบันมีข้อความว่าแสดงข้อมูลเดิมอยู่แล้ว ควรรักษาพฤติกรรมนี้

โค้ด: [cloud_reports.py:2117](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/cloud_reports.py:2117>), [web_evidence_report.py:89](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/web_evidence_report.py:89>) · [ไม่มีข้อมูล](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/reports-empty.png>) · [อ่านผิดพลาดและเก็บข้อมูลเดิม](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/reports-error.png>)

### UX-15 · P2 · ช่องเหตุผลพึ่ง placeholder และฟอร์มบางส่วนไม่มีป้ายคงที่

ช่องเหตุผลใน popup แก้ราคา/แก้เงิน/แบ่งยอดหายคำอธิบายเมื่อเริ่มพิมพ์ ขณะที่ช่องเลือก Counter/ช่วงฐานใน Web evidence ไม่มี label ที่ผู้ใช้เห็นตลอด ช่องบังคับหลายแห่งต้องเดาจากปุ่มที่กดไม่ได้

มี label คงที่ ระบุ “จำเป็น” และตัวอย่างสั้นแยกจากค่าที่กรอก ผูก label กับ input และแสดงสิ่งที่ยังขาดใกล้ปุ่มยืนยัน ไม่กล่าวว่าไม่มี accessible name ทุกช่อง เพราะ CounterReview ตั้งไว้แล้ว

โค้ด: [billing_manual_review.py:55](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/billing_manual_review.py:55>), [billing_web_amendment.py:40](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/billing_web_amendment.py:40>), [web_evidence_report.py:89](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/web_evidence_report.py:89>)

### UX-16 · P2 · หน่วยขนาดฟอนต์ไม่เป็นระบบ

ปุ่ม Primary ใช้ 12 pt แต่ Outline/Danger/Warning ใช้ 12 px; ข้อความทั่วไป 11 pt ขณะที่ Checkbox และแท็บใช้ px หัวการ์ดรายงานแบบ compact ลงถึง 11 px ทำให้ตัวหนังสือที่สำคัญพอ ๆ กันมีขนาดต่างกันมาก และชื่อสรุปอ่านยากบนจอเล็ก

กำหนด typography tokens ชุดเดียวสำหรับหัวข้อ เนื้อหา คำอธิบาย ปุ่ม และตาราง ใช้หน่วยเดียวใน QSS พร้อมทดสอบภาษาไทยที่ 100/125/150% ลด density ด้วย layout ก่อนลดขนาดตัวอักษรสำคัญ

โค้ด: [config.py:411](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:411>), [config.py:422](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:422>), [cloud_reports.py:787](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/cloud_reports.py:787>)

### UX-17 · P3 · ช่องวันที่ใช้คนละหน้าตากับช่องกรอกอื่น

Global input QSS ครอบคลุม QTimeEdit แต่ไม่ครอบคลุม QDateEdit จึงเห็นช่องวันที่ Export และ Web evidence แบบเทา native ข้างช่องกรอกสีขาว/ขอบมน ส่วน Reports มี date style และปุ่มปฏิทินของตัวเอง

รวม date/time/input styles และสถานะ focus/disabled ให้เป็นชุดเดียว โดยคงรูปแบบตัวเลขวันที่ที่ตั้งใจใช้และการเลือกปฏิทินได้ด้วยคีย์บอร์ด

โค้ด: [config.py:384](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:384>), [cloud_reports.py:504](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/cloud_reports.py:504>)

### UX-18 · P2 · ปุ่มงานเสี่ยงใช้สีเหมือนปุ่มทั่วไป

Danger, Success และ Warning ใช้พื้นเทา/ข้อความกรมท่าแทบชุดเดียวกัน ปุ่มล้าง/รีเซ็ตใน Settings ขั้นสูงจึงไม่มีสัญญาณแยกจากงานทั่วไป แม้มี popup ยืนยันอยู่แล้ว

ใช้ destructive role เฉพาะการลบ/รีเซ็ตจริง พร้อมชื่อการกระทำที่ระบุสิ่งที่ได้รับผล ปุ่มบันทึกใช้ Primary และปุ่มรองใช้ Outline ไม่ใช้สีเพียงอย่างเดียวเพื่ออธิบายผล และรักษาค่าเริ่มต้นของการยืนยันเป็น Cancel/No

โค้ด: [config.py:433](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:433>), [config.py:448](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:448>)

### UX-19 · P3 · พื้นหลังเทารั่วเข้าไปใน Checkbox และฟอร์มสีขาว

Global selector `QMainWindow, QWidget` ลง background ให้ลูกทุกชนิดด้วย จึงเห็นแถบเทายาวหลัง Checkbox ในการตั้งค่าเครือข่าย/วันทำงาน และบาง container ทั้งที่ card รอบนอกสีขาว ความสูง/ขอบของ nested cards กับ popup จึงดูมาจากคนละชุด

กำหนดพื้นหลังเฉพาะหน้าต่าง/พื้นผิวที่มี role ส่วน label/checkbox/container ที่ต้องโปร่งใสให้โปร่งใส รวม spacing และรัศมีกรอบใน token เดียว ลด card ซ้อน card โดยใช้หัวข้อและเส้นแบ่ง

โค้ด: [config.py:243](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:243>), [network_settings.py:20](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/network_settings.py:20>) · [ภาพแถบพื้นหลัง](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/network-settings.png>)

### UX-20 · P2 · คู่มือในแอปยังแทรกภาพหน้าตาเก่าปนกับคำอธิบายใหม่

มีปุ่มคู่มือ PDF ฉบับปรับปรุงและข้อความใหม่แล้ว แต่ `_guide_screenshot` ยังใช้ภาพจาก assets-v5.2 หลายรายการ โดยเปลี่ยนเฉพาะภาพหมายเลข 11 เป็นชุดใหม่ ภาพหน้าคู่มือเองยังแสดงเมนู/แท็บเก่าและอยู่ทั้งในคู่มือไทย–อังกฤษ จึงทำตามภาพแล้วอาจไม่พบตำแหน่งเดียวกัน

หลังแก้ UI ให้ถ่ายภาพจาก source ปัจจุบันตามขั้นตอนใช้งานจริง เปลี่ยนภาพที่ต่างจากรุ่นนี้ และใช้ภาพชุดเดียวกับ PDF/คู่มือในแอป ตรวจชื่อเมนูและข้อจำกัด Sync อีกครั้ง ไม่เหมารวมว่าคู่มือทุกส่วนยังเก่า

โค้ด: [pages.py:6455](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/pages.py:6455>), [pages.py:6506](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/pages.py:6506>) · [ภาพเก่าที่ฝังอยู่](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/qa/v5.2.12/ui-ux-audit/manual-old-image.png>)

### UX-21 · P2 · Export ในหน้าหลักฐาน Web ยังทำงานบน UI thread

ปุ่ม Excel/PDF ของ WebEvidenceDialog เรียกสร้างไฟล์โดยตรงหลังเลือก path และมีสถานะเมื่อเสร็จ/ล้มเหลว แต่ไม่มี worker หรือ progress แบบ Export ของ Reports ที่แก้แล้ว จึงมีความเสี่ยงหน้าจอไม่ตอบสนองเมื่อช่วงข้อมูลยาว **เป็นผลตรวจเส้นทางโค้ด ยังไม่ได้วัดเวลาค้างของ export นี้** และไม่หักล้างผล benchmark Reports เดิม

ใช้ export controller ที่ทำงานเบื้องหลังและรายงานความคืบหน้า/ยกเลิกอย่างปลอดภัย แล้ววัดกับข้อมูลยาวแยกจาก Reports ก่อนอ้างว่า export ทุกจุดไม่ค้าง

โค้ด: [web_evidence_report.py:349](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/web_evidence_report.py:349>)

### UX-22 · P3 · QSS กระจายหลายจุด ทำให้แก้หน้าหนึ่งแล้วหน้าอื่นไม่ตาม

นับใน config/app/pages/v5_pages/widgets และ source/ui พบ call site `setStyleSheet` 484 จุดใน 11 ไฟล์ และ literal สีแบบหกหลัก 264 ค่า ตัวเลขนี้รวมโค้ดเก่าและ branch ของสถานะ ไม่ใช่ 484 stylesheet ที่ใช้พร้อมกันหรือ 264 สีที่เห็นจริงทุกหน้า Global accent, Reports, Wizard และ Parser ใช้สีน้ำเงินคนละค่า

มีระบบกลางบางส่วนแล้ว ได้แก่ build_qss, ButtonSystem, PageHeading และ PageTabs แต่ popup ใหม่หลายตัวสร้าง QPushButton ตรงและมี style ของตัวเอง ควรจัด theme tokens + component roles ให้หน้าปัจจุบันใช้ร่วมกันก่อน แล้วทยอยลด style เฉพาะหน้า ไม่จำเป็นต้องรื้อทุกคลาสเก่าพร้อมกัน

โค้ด: [config.py:69](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/config.py:69>), [ui_consistency.py:25](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui_consistency.py:25>), [page_tabs.py:10](<C:/Users/User/.codex/worktrees/4897/KOMI Report V5/source/ui/page_tabs.py:10>)

## ครอบคลุมหน้าจอใดบ้าง

| ส่วน | ที่ตรวจ | ประเด็นที่เกี่ยวข้อง |
|---|---|---|
| Sidebar / shell | 5 เมนู, เปลี่ยนภาษา, resize, keyboard focus | 04–08, 16, 19, 22 |
| Overview | KPI, printer cards, toner, usage graph, scroll | ระบบฟอนต์/ปุ่มร่วม; ไม่ใช้สถานะ online ของ fixture ตัดสินพฤติกรรมเครื่องจริง |
| Devices | การ์ด 3 เครื่อง, Counter tables, ปุ่มอ่าน/สถานะ | 03, 10, 16 |
| Reports Overview | ข้อมูลปกติ/กำลังโหลด/ผิดพลาด/ว่าง, ช่วงวันที่ | 01, 05, 13–14, 16–17 |
| Reports Users / Printers | 90 ผู้ใช้, เลือกแท็บ, ตารางกว้าง, ข้อมูลเครื่อง | 01, 10, 13, 16 |
| Reports Usage / Legacy | ทุกแท็บย่อย, กราฟเดือนเดียว, ตาราง raw | 05–06, 10, 13 |
| Export | เลือกวันที่, progress popup; อ่านโค้ดสถานะยกเลิก | 03, 05, 15–17; ไม่รัน benchmark 1 ปีซ้ำในงานตรวจ QSS |
| Settings ทั่วไป | เครื่อง/ราคา, ลงทะเบียน, auto-start, รอบบิล | 03–04, 15–16 |
| Automation | Timeline, ขยายตารางเวลา, scroll ถึงปุ่มบันทึก | 04, 16, 19 |
| สถานะและประวัติ | สถานะอ่าน, log, cache, ตรวจมิเตอร์ | 03–04, 07, 10, 12 |
| เครือข่าย | ขยายการตั้งค่า, พอร์ต, รหัส, pairing, สถานะสมาชิก, footer | 02–05, 15–16, 19 |
| ขั้นสูง | Database/backup/log/reset, Archive, config history | 03, 10, 18–19; ตรวจ destructive handlers โดยไม่กดลบ |
| Billing audit | populated ledger 4 รายการ, detail, manual/reprice/batch | 03–04, 10–12, 15–16 |
| Web evidence / ฉบับแก้ไข | หน้าว่างและโหลด fixture จริง, กราฟทุกแท็บ, remarks, before/after | 03, 05, 10, 12, 14–15, 21 |
| Slot / Counter / shared history | หน้าว่าง, ค่าฐานจำลอง, confirmation, รายการ Counter | 02–03, 08–10, 12, 15 |
| Parser Mapping / Legacy import | หน้าจอเปิดเริ่มต้น, ตาราง, ปุ่ม disabled | 03, 05, 10 |
| Wizard | 4 ขั้น, secondary manual/not found/retry, ราคา, review; credentials, scan range, manual IP, ชื่อ Slot, privacy | 02, 05, 15–17; ขั้นชื่อ Slot อธิบายการใช้ Slot เดิมได้ชัดอยู่แล้ว |
| Manual | 5 หมวด ไทย–อังกฤษ, ภาพประกอบและปุ่ม PDF | 20 |
| Tray / registration error / OS dialogs | ตรวจ source ของข้อความ, default Cancel, handler | ไม่อ้างการทดสอบคลิก System Tray/Host/OS file picker จริง |

## สิ่งที่ทำได้ดีและควรรักษา

- หน้า Reports มีปุ่มส่งออกหลักจุดเดียวแล้ว มี progress และยกเลิกแยกจาก GUI
- หน้ารายงานผิดพลาดแจ้งว่ากำลังแสดงข้อมูลเดิม และมีปุ่มลองอีกครั้ง
- กราฟหลักฐานช่วงขาดการอ่านจำลองแสดง 150.5 + 150.5 และมีคำว่าเป็นค่าประมาณ ไม่ใช่การยืนยันยอดรายวัน
- การแบ่งยอดมี preview เดิม→ใหม่ และต้องระบุเหตุผล; ฐาน Slot มีขั้นตรวจ Serial และ checkbox ยืนยัน
- Wizard มีปุ่มค้นหาอีกครั้งเมื่อไม่พบเครื่อง และมีคำอธิบาย Slot/ราคา 0.00; ขั้นตอนหลักยังเลื่อนดูเนื้อหาและเข้าถึงปุ่มท้ายได้
- แบบฟอร์ม Settings มีการป้องกันเปลี่ยนแท็บทิ้งค่าที่ยังไม่บันทึก และงานเสี่ยงหลายจุดตั้ง Cancel/No เป็นค่าเริ่มต้น

## ลำดับงานที่เสนอ

1. แก้ UX-01, 02, 11 ก่อน: ตัวเลขเงิน, ข้อความความสามารถจริง, ตารางตรวจยอดต้องใช้งานได้
2. ทำฐาน component/QSS ร่วมพร้อมแก้ UX-03, 08, 16–19, 22 โดยทดสอบ popup และหน้าตั้งค่าที่ได้รับผลทันที
3. แก้ UX-05–07, 09: คำแปลครบข้อความ, ห้ามแปลข้อมูลผู้ใช้, tab identity และเก็บ Counter preference
4. ปรับ responsive layout, ตาราง/กราฟ, empty state และฟอร์มตาม UX-04, 10, 12–15
5. ตรวจ/แก้ worker ของ Web evidence export ตาม UX-21 แล้ววัดความตอบสนองด้วย fixture ยาว
6. ถ่ายภาพและปรับคู่มือ UX-20 หลัง UI นิ่ง รันทวน matrix ไทย–อังกฤษและ keyboard; จึงกลับมาตรวจความพร้อม build ตามขอบเขตเดิม

เกณฑ์ตรวจร่วม: ไม่มีตัวเลขสำคัญถูกย่อ, บอกได้ว่าปุ่มไหนใช้ได้, keyboard focus มองเห็น, ชื่อข้อมูลไม่ถูกแปล, ไม่มีข้อความสัญญา Sync ที่ยังไม่เปิดใช้ และ UI/คู่มือเรียกเมนูตรงกัน

## ข้อจำกัดที่ยังต้องตรวจบนเครื่องจริง

Qt offscreen ใช้ฟอนต์ Windows ที่ลงทะเบียนให้ตรงแอป แต่ไม่ใช่การเปิดโปรแกรมบนจอ Windows จริง มีการข้ามตัวจำกัดขนาดจอ offscreen 800×800 เพื่อทดสอบ logical layout จึงไม่รวม title bar/taskbar การย้ายจอ และการเปลี่ยน DPI ระหว่างจอ ไอคอน emoji ที่เป็นสี่เหลี่ยมในบางภาพอาจมาจาก fallback font ของ offscreen จึงไม่นับเป็น defect ยืนยันในรายงานนี้

Wizard ใช้ edit mode/ข้อมูลจำลองเพื่อไม่เริ่มลงทะเบียนจริง ไม่ตรวจ Host, ใบรับรอง production, two-PC installation, screen reader หรือ dialog ทุก error branch บน OS จริง คลาสเก่าที่ไม่มีจุดเรียกในหน้าปัจจุบัน เช่น PageConnectionInspector ไม่ถูกนับว่าเป็นหน้าผู้ใช้ที่ขาดการทดสอบ

รอบนี้ไม่ build, ไม่ publish, ไม่แก้ Host/ฐานลูกค้า และไม่แก้ source ของ UI มีเฉพาะเครื่องมือตรวจ หลักฐาน รายงาน และรายการงานในแผน
