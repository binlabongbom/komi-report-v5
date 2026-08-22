# KOMI Report V5.1.0 — Support, Recovery and Rollback

เอกสารนี้ใช้กับ Release Candidate Windows 10/11 x64 เท่านั้น. ต้องบันทึกผลจริงแยกเป็น Automated, VM,
Native x64, Real-device และ Signed; ห้ามใช้ VM/ภาพ offscreen แทน native acceptance.

## Release identity ก่อนติดตั้ง

ตรวจไฟล์ sidecar ในโฟลเดอร์เดียวกับ installer:

- `RC_MANIFEST.json`: version, source commit, build environment, signing state และ artifact identity
- `CHECKSUMS.sha256`: SHA256 ของ installer
- `FILE_INVENTORY.json`: path/size/SHA256 ของทุกไฟล์ใน payload
- `SBOM.cdx.json`: Python และ Web production dependencies จาก lockfiles

ถ้า `source_state` ไม่ใช่ `clean`, `signing` ไม่ใช่ `verified`, build environment ไม่ใช่ Windows x64 target
หรือ checksum ไม่ตรง ให้หยุดเป็น `RC blocked`; ห้ามติดป้าย Production GO.

## ตำแหน่งข้อมูลที่ installer ไม่ลบ

- Database เริ่มต้น: `%USERPROFILE%\KOMI Report V5\KOMI_Report_V5.db`
- Database path ที่ผู้ใช้เลือก: ดูค่าจริงแบบ read-only ใน Settings หรือ `%USERPROFILE%\KOMI Report V5\runtime.toml`
- Log: `%USERPROFILE%\KOMI Report V5\logs\`
- LAN Web runtime/certificate/local secret: `%LOCALAPPDATA%\KOMI Report V5\web-runtime\`
- Printer/Registration secret: Windows Credential Manager/OS vault; SQLite เก็บเพียง reference

Uninstall ลบเฉพาะ program files ใต้ `%LOCALAPPDATA%\Programs\KOMI Report V5`. การลบ Database, Web security
material หรือ OS-vault entry ต้องเป็น support action แยกหลัง backup และได้รับอนุญาตชัดเจน.

## Backup และ integrity ก่อน upgrade

1. Exit จาก System Tray และตรวจ Task Manager ว่า KOMI Report หยุดแล้ว.
2. สร้างโฟลเดอร์ backup นอก program/data directory เช่น removable drive ที่ควบคุมสิทธิ์ได้.
3. เปิด Command Prompt ที่ installation directory แล้วรัน โดยแทน path ให้ตรง Settings:

```bat
runtime\python.exe source\tools\db_recovery.py inspect --database "%USERPROFILE%\KOMI Report V5\KOMI_Report_V5.db"
runtime\python.exe source\tools\db_recovery.py backup --database "%USERPROFILE%\KOMI Report V5\KOMI_Report_V5.db" --output "D:\KOMI-Backup\KOMI_Report_V5-before-5.1.0.db"
runtime\python.exe source\tools\db_recovery.py inspect --database "D:\KOMI-Backup\KOMI_Report_V5-before-5.1.0.db"
```

เก็บ SHA256, `user_version`, `integrity=ok` และ `critical_counts` ของ `devices`, price tables, history,
`daily_meter_records` และ `billing_ledger`. ห้ามคัดลอก `.db` ตรง ๆ ขณะแอปทำงาน เพราะ committed WAL อาจตกหล่น.

## Clean install / first run / restart checklist

| Check | Expected | Evidence |
|---|---|---|
| Installer identity/checksum/signature | ตรง sidecars และ Authenticode Valid | command output/screenshot |
| Clean install | ลงแบบ per-userโดยไม่ใช้ customer data | installer log |
| First run | Wizard เปิด, สร้าง DB ใหม่, ไม่มี Registration network เมื่อไม่มี approved policy | screen + network/log evidence |
| OS vault | Password ไม่อยู่ใน SQLite/log และอ่านกลับหลัง restart ได้ | redacted vault/DB check |
| Restart | Desktop เปิด DB เดิมและไม่สร้างฐานใหม่ | DB path + counts |
| Tray/Exit | ปิดหน้าต่างแล้วยัง background; Exit จาก Tray จึงหยุด | Task Manager + UI |
| Auto-start | Login ใหม่แล้วเปิด minimized/background ตาม Settings | Task Manager + startup state |
| LAN Web HTTPS | Local + LAN URL เป็น HTTPS, login/session/lockout ทำงาน, API ยัง loopback | browser/network evidence |

## Upgrade acceptance

1. บันทึกก่อน upgrade: DB SHA/counts, Devices 1–3, Prices/effective dates, History period, Billing Ledger rows/status.
2. ติดตั้ง RC ทับ stable AppId/installation directory เดิม; ห้ามลบ `%USERPROFILE%\KOMI Report V5`.
3. เปิดครั้งแรกและรอ migration จบ; ถ้า migration เกิดขึ้นต้องพบ verified `pre-v*` backup.
4. รัน `inspect` หลัง upgrade แล้วเปรียบเทียบ critical counts กับ backup.
5. เปิด Devices, Prices, Reports/History, Billing Audit และ Export ด้วยช่วงวันเดิม; totals ต้องไม่เปลี่ยน.
6. Restart Windows แล้วทำซ้ำ DB path, Tray/Auto-start, OS vault และ LAN Web HTTPS.

## Restore และ rollback

ใช้ restore เมื่อแอปปิดสนิทและมี backup `integrity=ok` เท่านั้น. คำสั่งสร้าง rollback backup ของ DB ปัจจุบันก่อน
replace และตรวจ integrity หลัง restore:

```bat
runtime\python.exe source\tools\db_recovery.py restore --backup "D:\KOMI-Backup\KOMI_Report_V5-before-5.1.0.db" --database "%USERPROFILE%\KOMI Report V5\KOMI_Report_V5.db" --confirm-offline-restore
```

ผ่านเมื่อ `critical_counts_match_backup=true`, `integrity=ok`, app เปิดได้ และ Devices/Prices/History/Billing Ledger
ตรงกับ backup. หากต้อง rollback program ให้ถอน RC, ติดตั้ง previous signed installer ที่อนุมัติ และ restore เฉพาะ DB
ที่ schema ของ previous version รองรับ; newer schema ถูกปฏิเสธแบบ fail-closed ห้ามลด `user_version` ด้วยมือ.

## Uninstall / reinstall

1. Backup + inspect ก่อน uninstall.
2. Uninstall แล้วตรวจว่า program directory หาย แต่ Database/backups และ OS-vault data ยังอยู่.
3. Reinstall RC จาก artifact/checksum เดิม.
4. เปิดแล้วต้องเลือก/อ่าน DB เดิม, OS vault กลับมา, Web certificate/login state ยังอยู่ และ critical counts เท่าเดิม.
5. Cleanup ข้อมูลจริงทำได้หลัง user/customer authorization และ backup retention decision เท่านั้น.

## Controlled real-device Meter/Billing/Report/Excel acceptance

ทำเฉพาะเครื่องพิมพ์/test period ที่ได้รับอนุญาต. ถ้าหลักฐานไม่ครบให้ `Hold` มูลค่า 0.

| Field | Required evidence |
|---|---|
| Device | model, serial, slot และ authorized test window |
| Raw opening/closing | raw counter + source/provenance + timestamp |
| Expected delta | opening/closing difference ตาม counter family; Large Size ห้ามบวกซ้ำเมื่อเป็น subset |
| Reconciliation | `A = D + E`/exclusive-size rules และ completeness/safety state |
| Posted ledger | append-only row, source hash, price snapshot, gross/discount/net หรือ Hold reason |
| Reports/Excel | selected period/device totals ตรง posted ledger; ไม่มี credential/customer field เกิน scope |

ผ่านเมื่อ raw delta = reconciled usage = posted ledger usage = Report/Excel totals และค่าใช้จ่ายคำนวณจาก price snapshot
เดียวกัน. ห้ามแก้ customer record, meter หรือ ledger นอก controlled correction/reversal workflow.

## Release decision

- Automated/VM ผ่าน แต่ native x64, signing หรือ real-device ขาด: `Technical/RC blocked`
- Native x64 ผ่านแต่ signing ขาด: `RC blocked — unsigned`
- Signing ผ่านแต่ controlled billing proof ขาด: package gate ผ่านได้ แต่ `Production GO` ยัง blocked
- Registration/OpenAPI/Privacy/DPO/Legal ขาด: Registration/Heartbeat ต้อง disabled/fail-closed; Phase 2 ยังไม่ Production Pass
- Phase 3 Update: deferred และต้องไม่มี runtime path ใน Release นี้
