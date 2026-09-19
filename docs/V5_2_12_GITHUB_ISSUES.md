# GitHub issues — UX และ Performance 5.2.12

เปิดวันที่ 19 กันยายน 2569 ตามคำสั่งผู้ใช้ ใน repository `binlabongbom/komi-report-v5`
รวม **19 issues: 2 งานรวม + 17 งานย่อย** อ่านกลับจาก GitHub ตรวจ title/body/state ครบ 19/19 แล้ว
สถานะ ณ เปิดงานเป็น Open ทั้งหมด ยังไม่ได้เริ่มแก้หรือปิดรับงานจากการเปิด issues ครั้งนี้

## งานรวมที่ใช้ติดตาม

- [#18 — UX / UI / QSS](https://github.com/binlabongbom/komi-report-v5/issues/18): ครอบคลุม UX-01–22
- [#19 — Performance](https://github.com/binlabongbom/komi-report-v5/issues/19): ครอบคลุม PERF P1-01–05 / P2-06–07

งาน UX ที่แก้ร่วมกันรวมเป็น 10 issues; Performance มี 7 issues
UX-21 และ PERF P1-05 ใช้ [#34](https://github.com/binlabongbom/komi-report-v5/issues/34) ร่วมกัน ไม่สร้างงานซ้ำ

## แผนผังงานย่อย

| Issue | ลำดับ | เรื่อง | รหัสผลตรวจ |
|---|---|---|---|
| [#20](https://github.com/binlabongbom/komi-report-v5/issues/20) | P1 | แสดงยอดเงินและตัวเลขสำคัญให้ครบใน Reports | UX-01 |
| [#21](https://github.com/binlabongbom/komi-report-v5/issues/21) | P1 | ข้อความยืนยันการตั้งค่าและเครือข่ายต้องตรงความสามารถ Sync ที่เปิดใช้ | UX-02 |
| [#22](https://github.com/binlabongbom/komi-report-v5/issues/22) | P1 | คืนพื้นที่ตารางตรวจรอบบิลให้เลือกและตรวจยอดได้บนจอเล็ก | UX-11 |
| [#23](https://github.com/binlabongbom/komi-report-v5/issues/23) | P2 | รวมมาตรฐาน QSS สำหรับปุ่ม ฟอนต์ ช่องวันที่ พื้นหลัง และ keyboard focus | UX-03, UX-08, UX-16, UX-17, UX-18, UX-19, UX-22 |
| [#24](https://github.com/binlabongbom/komi-report-v5/issues/24) | P2 | แก้การแปลเป็นประโยค ป้องกันชื่อข้อมูลถูกแปล และผูกชื่อแท็บกับ identity | UX-05, UX-06, UX-07 |
| [#25](https://github.com/binlabongbom/komi-report-v5/issues/25) | P2 | ปรับ Settings และตารางให้พอดีหน้าต่าง พร้อมอ่านชื่อและหมายเหตุเต็ม | UX-04, UX-10 |
| [#26](https://github.com/binlabongbom/komi-report-v5/issues/26) | P2 | ห้ามบันทึกหน้าเลือก Counter ว่างทับค่าที่เคยเลือก | UX-09 |
| [#27](https://github.com/binlabongbom/komi-report-v5/issues/27) | P2 | ทำหน้าตรวจยอดและฟอร์มยืนยันให้อ่านรู้เรื่อง พร้อมป้ายช่องกรอกถาวร | UX-12, UX-15 |
| [#28](https://github.com/binlabongbom/komi-report-v5/issues/28) | P2 | ทำกราฟให้อ่านแยกคนได้ และแยกไม่มีข้อมูลออกจากยอดศูนย์ | UX-13, UX-14 |
| [#29](https://github.com/binlabongbom/komi-report-v5/issues/29) | P2 | ปรับภาพและขั้นตอนคู่มือในแอป/PDF ให้ตรง UI และข้อจำกัดรุ่น 5.2.12 | UX-20 |
| [#30](https://github.com/binlabongbom/komi-report-v5/issues/30) | P1 | หยุด Overview โหลดประวัติทั้ง 5 ปีบน UI thread | PERF P1-01 |
| [#31](https://github.com/binlabongbom/komi-report-v5/issues/31) | P1 | ย้ายการนับ Archive ออกจากการเปิด Settings บน UI thread | PERF P1-02 |
| [#32](https://github.com/binlabongbom/komi-report-v5/issues/32) | P1 | ทำ index Raw ครั้งเดียวก่อนแสดง Legacy แทนสแกนซ้ำทุกช่อง | PERF P1-03 |
| [#33](https://github.com/binlabongbom/komi-report-v5/issues/33) | P1 | จัดการอายุกราฟที่ถูกแทนเพื่อหยุดการสะสม native chart objects | PERF P1-04 |
| [#34](https://github.com/binlabongbom/komi-report-v5/issues/34) | P1 | ส่งออกหลักฐาน Web Excel/PDF ในงานเบื้องหลังพร้อม progress และยกเลิก | PERF P1-05 + UX-21 (งานเดียว ไม่ทำซ้ำ) |
| [#35](https://github.com/binlabongbom/komi-report-v5/issues/35) | P2 | ลดเวลารอ Reports ปีและข้อมูล Raw ซ้ำระหว่างแท็บ | PERF P2-06 |
| [#36](https://github.com/binlabongbom/komi-report-v5/issues/36) | P2 | ลดงานสร้างหน้าครั้งแรกของ MainWindow Devices และ Manual | PERF P2-07 |

## วิธีทำงานและตรวจรับ

1. เปิด issue รวม เลือกงาน P1 ก่อน สั่งงานด้วยหมายเลข เช่น “ทำ #30 แล้วตรวจตามเกณฑ์ใน issue”
2. อ่าน “ปัญหาและผลที่พบ”, “หลังแก้จะทำงานอย่างไร” และ “ผู้ใช้จะใช้งานอย่างไร” เพื่อยืนยันขอบเขต
3. ผู้ทำระบุว่ากำลังทำ/ติดอะไรใน issue และเชื่อม commit/PR; ไม่ถือว่าการเปิด PR แปลว่าตรวจผ่าน
4. รัน checklist ใน “ตรวจสอบอย่างไร / เกณฑ์รับงาน” พร้อมแนบผลก่อน–หลัง
   UX ใช้ภาพ/ภาษา/ขนาดจริง/keyboard/empty-error states; Performance ใช้ fixture เดิม,
   UI responsiveness, เวลาโหลด, RAM และความถูกต้องของยอด/ไฟล์
5. ผู้ตรวจทดลอง flow ใน source ที่ตรง commit ตรวจหลักฐานและข้อจำกัดที่ยังไม่ได้ทดสอบ
   หากไม่ผ่านให้บันทึกขั้นตอนและผลจริงใน issue เดิม
6. ปิดงานย่อยเมื่อแก้และตรวจรับผ่าน พร้อมลิงก์หลักฐาน แล้วอัปเดตรายการในงานรวม
   Closed ไม่ได้หมายถึงอนุมัติ build/release

ยังไม่มี automation/การมอบหมายผู้อื่นอัตโนมัติหรือ GitHub Project เพิ่มขึ้น
P1/P2 อยู่ในชื่อและเนื้อหาเพื่อเรียงความสำคัญ ไม่ได้เพิ่ม label หรือ milestone ใหม่

## ขอบเขตและหลักฐาน

- คัดผลตรวจที่สำคัญ พฤติกรรมหลังแก้ วิธีใช้งาน และเกณฑ์รับงานลงทุก issue แล้ว
- ตรวจ GitHub API แล้วไม่พบ audit commit `4e2bd3a` ณ ตอนเปิดงาน จึงอ้าง source paths
  และผลวัดเป็นข้อความ ไม่ทำลิงก์ไฟล์/ภาพที่ remote ยังไม่มี เมื่อมีคำสั่งนำ source ขึ้น remote
  ภายหลังให้เพิ่ม permalink ใน issue เดิม
- แผนเดิม: [UX audit](V5_2_12_UI_UX_AUDIT.md),
  [Performance audit](V5_2_12_PERFORMANCE_AUDIT.md),
  [แผนพัฒนารวม](V5_2_12_WORK_PLAN.md)
- รอบนี้เป็นการสร้าง issues และอัปเดตเอกสาร ไม่แก้โค้ดโปรแกรม ไม่ push source,
  ไม่ build/publish โปรแกรม ไม่เปลี่ยน Host หรือข้อมูลลูกค้า
- การติดตั้งเครื่อง A + Proxmox VM105 ยังคงทดสอบหลัง build ตามข้อสรุปเดิม
