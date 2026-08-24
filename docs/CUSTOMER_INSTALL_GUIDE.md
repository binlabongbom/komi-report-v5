# KOMI Report V5.1.0 — Install, Uninstall and Recovery Guide

## ก่อนติดตั้ง

1. อ่าน `CUSTOMER_RELEASE_MANIFEST.json` และยืนยัน `version=5.1.0`, source commit และ release decision.
2. ตรวจ SHA256 ของ artifact กับ `CHECKSUMS.sha256`.
3. ตรวจ signing state ตาม OS. ถ้า manifest เป็น `HOLD` ให้ใช้เฉพาะ authorized internal verification; ห้ามปล่อยลูกค้า.
4. ถ้ามี V5 เดิม ให้ Exit จาก System Tray แล้ว backup Database ด้วยขั้นตอนใน `RELEASE_SUPPORT_AND_RECOVERY.md`.
5. บันทึก DB path, `integrity=ok`, schema version และ critical counts ก่อน install/upgrade.

## macOS

1. เปิด DMG แล้วลาก `KOMI Report V5.1.0.app` ไป Applications หรือแตก ZIP ไปยังโฟลเดอร์ Applications ที่ควบคุมได้.
2. ตรวจ app identity ด้วย `codesign -dvvv --entitlements :-` และ `spctl -a -vv` โดยเทียบกับ manifest.
3. เปิดแอป, จบ First-run Setup ด้วยข้อมูลที่ได้รับอนุญาต, ตรวจ Settings และเปิด LAN Web HTTPS จากอุปกรณ์ใน LAN.
   Production policy อยู่ในแอปแล้ว; เมื่อรับทราบประกาศ โปรแกรมจะย้าย limited bootstrap identifier เข้า macOS Keychain
   และส่ง Registration เบื้องหลัง. หาก API ใช้ไม่ได้ โปรแกรมหลักยังเปิดและเก็บคิว retry ในเครื่อง.
4. กดปิดหน้าต่างเพื่อยืนยัน Tray/background และเลือก Exit เพื่อยืนยัน graceful shutdown.
5. ค่าเริ่มต้นของ Database/log อยู่ใต้ `~/KOMI Report V5/`; Web runtime/security material อยู่ใต้
   `~/Library/Application Support/KOMI Report V5/`. Path ที่ผู้ใช้เลือกจริงให้ตรวจจาก Settings/runtime config.

หาก Gatekeeper ปฏิเสธเพราะ artifact เป็น ad-hoc/ไม่ notarized ให้หยุด customer installation; ห้าม bypass warning เพื่อสร้าง
หลักฐาน Production. ใช้ signed/notarized artifact ที่ manifest ตรงเท่านั้น.

## Windows

1. ตรวจ Authenticode และ SHA256 ของ `KOMI_Report_V5_1_0_Windows_x64_Installer.exe`.
2. เปิด installer แบบ per-user. Program files อยู่ `%LOCALAPPDATA%\Programs\KOMI Report V5`.
3. เปิด KOMI Report V5, ตรวจ First-run, Database path, Settings, Tray, Auto-start หลัง login และ LAN Web HTTPS.
   Production policy อยู่ในแอปแล้ว; limited bootstrap identifier จะถูกย้ายเข้า Windows Credential Manager อัตโนมัติ
   ตอนเปิดครั้งแรก โดยไม่มีช่องให้ลูกค้ากรอกรหัส API.
   Shortcut สำหรับลูกค้าใช้ hidden launcher จึงไม่ควรมี Command Prompt/Terminal ปรากฏใน flow ปกติ;
   installer จะย้าย Desktop shortcut เดิมที่ยังชี้ `.cmd` ให้ใช้ hidden launcher ด้วย ส่วน `START_DEBUG.cmd`
   มีไว้ให้ Support เปิดเองเมื่อจำเป็นเท่านั้น.
4. Restart Windows แล้วตรวจว่าแอปอ่าน Database เดิม, OS vault และ Web security state เดิม.
5. Windows user data ค่าเริ่มต้นอยู่ `%USERPROFILE%\KOMI Report V5`; Web runtime/security material อยู่
   `%LOCALAPPDATA%\KOMI Report V5\web-runtime`.

ถ้า Authenticode เป็น `NotSigned`/Unknown Publisher ให้หยุด customer release; checksum ที่ตรงพิสูจน์ file integrity แต่ไม่แทน
Publisher identity.

## Uninstall / reinstall

1. Exit แอปและ backup/inspect Database.
2. Uninstall แล้วตรวจว่า program directory หาย แต่ user Database/backups และ OS-vault/Web security state ยังอยู่.
3. Reinstall artifact/hash เดิมและตรวจ DB path, critical counts, Settings, Tray/Auto-start และ LAN Web ซ้ำ.
4. การลบ user data/secret เป็น support action แยก ต้องมี backup และคำอนุญาตชัดเจน.

## Restore / rollback

Restore ทำเมื่อแอปปิดสนิทและ backup มี `integrity=ok` เท่านั้น. เครื่องมือจะสร้าง rollback backup ก่อน replace และต้องได้
`critical_counts_match_backup=true`. หาก rollback program version ให้ใช้ previous approved artifact/source/hash และ restore
เฉพาะ schema ที่รุ่นก่อนรองรับ; ห้ามลด schema version ด้วยมือ.
