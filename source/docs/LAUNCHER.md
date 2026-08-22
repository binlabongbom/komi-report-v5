# KOMI Report V5 Launcher

เลือกวิธีเปิดตามงาน:

- `KOMI Report V5.1.0.app` — Local macOS bundle ที่สร้างไว้ใน `dist/` หรือ `release/`; ดับเบิลคลิกใช้งานปกติ
- `Open KOMI Report V5.command` — เปิด Desktop จาก source และเห็นข้อความช่วยวิเคราะห์ใน Terminal
- `python app.py` — เปิดโดยตรงจาก virtual environment สำหรับนักพัฒนา
- `Open KOMI Report Web.command` — เปิด Web Edition ภายใน Trusted LAN; ไม่ใช่ตัวเก็บ Meter process ที่สอง

Source launcher จะมองหา `.venv/bin/python` ก่อน แล้วจึง fallback ไป `python3` ของระบบ

หากยังไม่ได้ติดตั้ง dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

พฤติกรรม Desktop:

- เปิดเองตามปกติจะแสดงหน้าต่างหลัก
- เปิดด้วย `--background` จะย่อไว้ใน System Tray
- กดปิดหน้าต่างเป็นการซ่อน; ใช้ `Exit` จาก Tray เมื่อต้องการหยุด Scheduler
- ระบบป้องกันการเปิด process ซ้ำ และการเปิดครั้งที่สองจะเรียกหน้าต่างเดิมกลับมา

macOS `.app` ใน Development Release เป็น unsigned local build สำหรับ Apple Silicon และยังไม่ได้ notarize
จึงไม่ควรนำไปแจกภายนอกองค์กรจนกว่าจะผ่านขั้นตอน signing/release distribution
