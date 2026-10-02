# KOMI Report Documentation Images

โฟลเดอร์นี้ใช้เก็บ screenshot จาก build จริงสำหรับ README, Customer Guide และ GitHub Release

## Required screenshots

| File | Screen | Capture guideline |
|---|---|---|
| `dashboard-overview.png` | ภาพรวม | ใช้ข้อมูล demo ไม่มีข้อมูลลูกค้าจริง และให้เห็น summary cards + chart |
| `device-page.png` | อุปกรณ์ | ให้เห็น 1–3 device cards, meter และสถานะ โดยปิด/เปลี่ยน Serial Number ที่เป็นของจริง |
| `report-overview.png` | Reports / Overview | ให้เห็น date range, summary และ graph |
| `report-usage.png` | Reports / Usage | ให้เห็น D/M/Y และตาราง usage |
| `settings-main.png` | Settings | แสดง settings หลักโดยไม่เผย credential/path ส่วนตัว |
| `first-run-wizard.png` | First-run Wizard | ใช้ demo company / private IP ตัวอย่างเท่านั้น |
| `excel-export.png` | Excel export | แสดง workbook ตัวอย่างโดยไม่มีข้อมูลลูกค้าจริง |

## Rules

- Capture จาก release build จริงเท่านั้น ไม่ใช้ mock UI แทนหน้าจอจริง
- ห้ามมีชื่อบริษัทลูกค้า, public IP, credential, registration token หรือข้อมูลส่วนบุคคล
- แนะนำขนาด 1440–1920 px wide และ crop เฉพาะ application window
- ใช้ PNG เพื่อให้ text ใน UI อ่านง่าย
- หาก UI เปลี่ยนอย่างมีนัยสำคัญ ให้ update screenshot พร้อม release

## Suggested placement

README:

```markdown
![KOMI Report Dashboard](docs/images/dashboard-overview.png)
```

Customer Guide:

```markdown
![Device page](images/device-page.png)
```

GitHub Release สามารถอ้างรูปจาก repository ด้วย URL ของ raw/blob ที่ตรงกับ release tag เพื่อให้ภาพไม่เปลี่ยนตาม `main`
