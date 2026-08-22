# KOMI Report V5 — Web Edition

หน้าเว็บรายงานสำหรับใช้งานภายในเครือข่ายเดียวกัน ใช้ Python API และฐานข้อมูลเดียวกับ
KOMI Report V5 Desktop โดยไม่มี Billing formula ชุดที่สอง

## เปิดใช้งาน

เปิดตัว Launcher ที่ระดับบนสุดของโปรเจกต์ตามระบบปฏิบัติการ:

- macOS: `Open KOMI Report Web.command`
- Windows: `START_KOMI_REPORT_WEB.cmd`
- Linux: `Open KOMI Report Web Linux.sh`

จากนั้นเปิด URL ที่แสดงใน Terminal เช่น `https://192.168.1.103:3000` จากเครื่องอื่นใน LAN
โปรแกรมสร้าง per-install certificate ที่มี SAN สำหรับ localhost/hostname/LAN IP หรือใช้ certificate ของลูกค้าได้
โดยไม่ติดตั้ง Root CA หรือแก้ OS trust store เงียบ ๆ
และใช้ข้อมูลเข้าระบบที่แสดงเฉพาะบนเครื่อง server ตอนเปิดครั้งแรก

ตัว Launcher จะคัดลอกเฉพาะ Web source ไปยัง runtime local และติดตั้ง `node_modules` ที่นั่น
เพื่อไม่ให้ dependency หรือ credential ถูก Sync ไปกับ OneDrive:

- macOS: `~/Library/Application Support/KOMI Report V5/web-runtime/`
- Windows: `%LOCALAPPDATA%\KOMI Report V5\web-runtime\`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/komi-report-v5/web-runtime/`

ไฟล์ `.env.local` อยู่ใน runtime ของแต่ละเครื่องเท่านั้น ไม่อยู่ใน `web/` และไม่ใช่ source กลาง
รหัสเข้า Web จัดการจาก Desktop Settings เท่านั้น; runtime เก็บ `scrypt` hash แบบ dotenv-safe และ session version
โดยไม่เก็บหรือแสดงรหัสจริงใน source/Log ส่วน Web UI เป็น read-only และไม่มีเมนูเปลี่ยนรหัส

- Web UI: Next.js ที่ port `3000`
- Python API: FastAPI ที่ `127.0.0.1:8766` เฉพาะภายในเครื่องหลัก
- ผู้ใช้ LAN เข้าข้อมูลผ่าน Next.js proxy หลัง Login เท่านั้น

## ฟังก์ชันที่พร้อมใช้งาน

- Reports แบบ Cloud-style 3 หน้า: Overview, Users และ Printers; Sync Status/Settings แยกเป็น System
- ช่วงรายงานหนึ่งจุดควบคุม KPI, กราฟ และตารางทุก Widget ในหน้า
- กด User หรือ Printer ในตารางเพื่อ Cross-filter กราฟและรายละเอียด โดย User/Account ไม่ใช้คำนวณค่าใช้จ่าย
- วันที่ reconciliation ไม่ผ่านถูกพักออกจาก Billing แต่ยังเก็บหลักฐานและแสดงใน Data Quality
- API เป็น read-only และไม่ส่ง Username/Password เครื่องพิมพ์ออกไป
- มี Login, temporary lockout, expiring/revocable session และ Secure cookie บน HTTPS; ยังห้ามเปิด port ออก Public Internet

## คำสั่งสำหรับนักพัฒนา

```bash
./Open\ KOMI\ Report\ Web.command
```
