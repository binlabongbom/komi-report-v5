# KOMI REPORT V5.1 — เริ่มที่นี่

พัฒนาจาก Cloud โดยไม่ใช้ Mac: [`docs/CLOUD_DEVELOPMENT.md`](docs/CLOUD_DEVELOPMENT.md)
มี setup แยก, tests ด้วยข้อมูลจำลอง และแนวทาง Windows installer candidate ผ่าน GitHub Actions

Canonical development source อยู่ที่ `~/Projects/dev/komi-report-v5` และไม่อยู่ใน OneDrive
แต่ละระบบเก็บ Python, dependency, build และ runtime ไว้เฉพาะเครื่องนั้น ไม่ sync ข้ามระบบ

## เปิดโปรแกรม

- macOS: ดับเบิลคลิก `Open KOMI Report V5.command`
- Setup Lab บน macOS: ดับเบิลคลิก `Open KOMI Setup Lab.command`
- Windows: ดับเบิลคลิก `START_KOMI_REPORT.cmd`
- Linux: รัน `./Open KOMI Report V5 Linux.sh`
- Web บน macOS: ดับเบิลคลิก `Open KOMI Report Web.command`
- Web บน Windows: ดับเบิลคลิก `START_KOMI_REPORT_WEB.cmd`
- Setup Lab บน Windows VM: ดับเบิลคลิก `START_KOMI_SETUP_LAB.cmd`
- Web บน Linux: รัน `./Open KOMI Report Web Linux.sh`

ตัวเปิดแต่ละระบบ resolve ตำแหน่งโปรเจกต์จากไฟล์ตัวเอง แล้วเรียก source ในโฟลเดอร์เดียวกันโดยตรง
การส่งให้เครื่องอื่นต้องใช้ Release package ที่สร้างและตรวจสำหรับ OS นั้น ห้ามใช้ OneDrive เป็นตัว Update ลูกค้า

Setup Lab เปิด Wizard จริงพร้อม Virtual Printer ที่ตอบ SNMP และ Web Connection เพื่อทดสอบ Quick Scan,
Test และ Next โดยใช้ฐานข้อมูลชั่วคราว ไม่แก้ข้อมูลใช้งานจริง. Mac ใช้ `127.0.0.1:1161/8443`
เพื่อไม่ต้องขอสิทธิ์ระบบ; Windows VM ใช้พอร์ตเครื่องจริง `161/443` และอาจขออนุญาต Firewall ครั้งแรก

อ่านหน้าที่ของทุกส่วนและคำแนะนำการลบได้ที่ [`docs/FILE_AND_FOLDER_GUIDE.md`](docs/FILE_AND_FOLDER_GUIDE.md)

> ต้นฉบับ OneDrive เดิมเป็น rollback archive ชั่วคราวระหว่างย้ายระบบเท่านั้น
> อย่าแก้พร้อมกับ canonical source ใหม่นี้ และอย่าลบจนกว่า V5.1 จะผ่านการตรวจจาก path ใหม่
