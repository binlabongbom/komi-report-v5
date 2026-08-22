# แผนที่โฟลเดอร์และไฟล์ — KOMI REPORT V5

อัปเดต: 2026-08-11

## ภาพรวมการทำงาน

```text
ตัวเปิดของแต่ละ OS
  -> runtime Python ของเครื่องนั้น (อยู่นอก OneDrive)
  -> source/app.py ใน OneDrive
  -> หน้าจอ PyQt6 (pages.py / v5_pages.py / widgets.py)
  -> services และ database.py
  -> SQLite ในโฟลเดอร์ข้อมูลผู้ใช้

Web browser
  -> Next.js ใน web/
  -> FastAPI source/web_api.py
  -> services และ database.py ชุดเดียวกับ Desktop
```

คำจำกัดความในเอกสารนี้:

- **หน้าบ้าน Desktop**: สิ่งที่ผู้ใช้เห็นในแอป PyQt6
- **หน้าบ้าน Web**: สิ่งที่ browser แสดง
- **หลังบ้าน**: กฎธุรกิจ, database, sync, SNMP, billing และ API
- **เครื่องมือพัฒนา**: ใช้ตอน test/build/diagnose ไม่ได้ทำงานทุกครั้งที่เปิดแอป
- **Generated**: สร้างใหม่ได้ ไม่ใช่ source

## โฟลเดอร์ระดับบนสุด

| โฟลเดอร์/ไฟล์ | ประเภท | ทำหน้าที่/ทำงานเมื่อไหร่ | คำแนะนำ |
|---|---|---|---|
| `source/` | Source กลาง | Desktop, API, services, test และ build | **ห้ามลบ** และต้อง sync ครบทุก OS |
| `web/` | หน้าบ้าน Web | Next.js อ่านข้อมูลจาก `source/web_api.py` | ห้ามลบถ้ายังใช้ Web Edition |
| `docs/` | เอกสาร/หลักฐาน QA | runbook, readiness review, screenshots และคู่มือนี้ | เก็บ; ย้ายภาพเก่าเข้า archive ได้ |
| `release/` | ผล build/offline package (ปัจจุบันไม่มีโฟลเดอร์นี้) | สร้างเฉพาะตอน package เพื่อส่งทดสอบ; launcher ปัจจุบันไม่เรียก | ลบได้เมื่อไม่ต้องส่ง/rollback เพราะสร้างใหม่ได้ |
| `_recovery/` | Recovery ชั่วคราว | snapshot conflict ก่อน reconcile OneDrive | เก็บจนทุก OS ผ่าน UAT แล้วค่อย archive |
| `_reconcile/` | Candidate ชั่วคราว (ปัจจุบันไม่มีแล้ว) | เคยใช้รวม conflict ก่อน promote | ไม่ต้องสร้างใหม่ถ้าไม่มี conflict |
| `PROJECT.md` | Workbook หลัก | สถานะ, blocker, test log และงานที่ต้องทำ | **ห้ามลบ**; ใช้ไฟล์เดียวเป็น canonical |
| `PRODUCT.md` | Product summary | ขอบเขตผลิตภัณฑ์ระดับย่อ | เก็บ |
| `README.md` | จุดเริ่มอ่าน | วิธีเปิดและลิงก์มายังคู่มือนี้ | เก็บ |
| `Open KOMI Report V5.command` | Launcher macOS | สร้าง/อัปเดต runtime local แล้วเรียก `source/app.py` | ตัวเปิดหลัก macOS |
| `START_KOMI_REPORT.cmd` | Launcher Windows | รองรับ path มีช่องว่าง/OneDrive และเรียก source กลาง | ตัวเปิดหลัก Windows |
| `Open KOMI Report V5 Linux.sh` | Launcher Linux | สร้าง runtime ใน XDG data แล้วเรียก source กลาง | Linux ยังต้อง native UAT |
| `Open KOMI Report Web.command` | Launcher Web macOS | เตรียม runtime local แล้วเปิด FastAPI + Next.js จาก source กลาง | ตัวเปิดหลัก Web macOS |
| `START_KOMI_REPORT_WEB.cmd` | Launcher Web Windows | รองรับ OneDrive/UNC/VirtualBox Shared Folder; runtime อยู่ LocalAppData | ผ่าน Windows 11 ARM VM UAT |
| `Open KOMI Report Web Linux.sh` | Launcher Web Linux | runtime อยู่ XDG data และเรียก Web source กลาง | script/contract ผ่าน; รอ Linux native UAT |
| `PROJECT.html`, `*.pptx`, ภาพ `komi-web-*.png` | เอกสาร/ภาพประกอบ | preview และนำเสนอ ไม่ได้ถูก import โดยแอป | ย้ายเข้า `docs/archive/` ได้หลังตรวจว่าไม่ใช้งาน |
| `.pytest_cache/`, `.ruff_cache/`, `.playwright-mcp/` | Generated | cache จาก test/lint/browser automation | ลบได้เมื่อไม่มี test รันอยู่ |

## `source/` — ไฟล์หลัก

| ไฟล์ | ประเภท | หน้าที่ | ทำงานเมื่อไหร่ |
|---|---|---|---|
| `app.py` | ทั้งหน้าบ้าน/ตัวประกอบระบบ | entrypoint Desktop, สร้าง `QApplication`, main window, tray และ lifecycle | ทุกครั้งที่เปิด Desktop |
| `v5_pages.py` | หน้าบ้าน Desktop | หน้าหลัก V5 เช่น Overview, Import, Reports, Sync Log, Settings | เมื่อสร้างหน้าและผู้ใช้เปิดเมนู |
| `pages.py` | หน้าบ้าน Desktop | page/widget รุ่นฐานและหน้าที่ V5 ยัง reuse | ตอนสร้าง UI และเปลี่ยนหน้า |
| `widgets.py` | หน้าบ้าน Desktop | component ใช้ร่วม เช่น card, table, status และ navigation widget | ตอน render หน้าจอ |
| `ui/cloud_reports.py` | หน้าบ้าน Desktop | หน้ารายงานแบบ cloud-inspired และตาราง Usage/Trend/Users/Devices | เมื่อเปิด Reports |
| `ui/common_dialogs.py` | หน้าบ้าน Desktop | dialog มาตรฐานที่หลายหน้าใช้ร่วมกัน | เมื่อเปิด dialog/ข้อความยืนยัน |
| `live_meter_page.py` | หน้าบ้าน Desktop | หน้าสถานะ meter แบบ live รุ่นเฉพาะ | เมื่อเปิดส่วน live meter |
| `i18n.py` | หน้าบ้านร่วม | คำแปลและ label ที่แสดงใน UI | ตอนสร้าง/เปลี่ยนข้อความ UI |
| `ui_consistency.py` | หน้าบ้าน/QA | กฎตรวจความสม่ำเสมอของ widget/style | ตอน test หรือ QA UI |
| `config.py` | หลังบ้าน | configuration หลัก, path, default และ setting compatibility | import ตั้งแต่เริ่มแอป/API |
| `runtime_config.py` | หลังบ้าน | แยก source/runtime/data root และค่าที่เปลี่ยนตามเครื่อง | ตอน bootstrap config |
| `database.py` | หลังบ้าน | SQLite access, config, device, readings, summary และ schema entrypoint | ทุก flow ที่อ่าน/เขียนข้อมูล |
| `migrations.py` | หลังบ้าน | migration schema แบบเพิ่มทีละ version | ตอน init/upgrade database |
| `parser.py` | หลังบ้าน | แปลงไฟล์ meter/report ที่ import เป็นข้อมูลมาตรฐาน | เมื่อผู้ใช้ import ไฟล์ |
| `parser_profiles.py` | หลังบ้าน | profile/รูปแบบ parser สำหรับไฟล์หลายแบบ | ตอนเลือก parser ให้ไฟล์ |
| `web_api.py` | หลังบ้าน/API | FastAPI read API สำหรับ Web Edition และ route compatibility | เมื่อเปิด web API |
| `observability.py` | หลังบ้าน | logging/diagnostic context | ตอนบันทึกเหตุการณ์และ error |
| `pyproject.toml` | Config build | ชื่อ/เวอร์ชัน, Python baseline และ dependency | ตอนสร้าง runtime, lint, test, build |
| `uv.lock` | Dependency lock | ล็อก dependency ให้ทุก OS resolve ชุดเดียวกัน | ตอนสร้าง/อัปเดต runtime |
| `requirements.txt` | Dependency fallback | รายการ dependency กรณีเครื่องไม่มี `uv` | first run หรือ lock เปลี่ยน |
| `Logo.icns`, `Logo.ico`, `logo.png` | Asset | icon macOS, Windows และภาพ UI | ตอน build/แสดงโลโก้ |
| `app.spec`, `build.py` | Build | config และ script สำหรับ PyInstaller | เฉพาะตอน build release |
| `app.vbs` | Legacy launcher | ตัวช่วยเปิดแบบไม่แสดง console บน Windows รุ่นเดิม | legacy; ตรวจ shortcut ก่อน archive |
| `Open KOMI Report V5.command` | Legacy launcher | launcher เดิมที่อยู่ใต้ source | เก็บเป็น compatibility หนึ่ง release แล้วชี้ไป root launcher |
| `README.md`, `RELEASE_NOTES.txt`, `docs/LAUNCHER.md` | เอกสาร | วิธีใช้ source/release/launcher รุ่นเดิม | ไม่ทำงานตอนเปิดแอป |
| `overview-v2-preview.png` | ภาพ QA | preview UI เก่า | ย้าย docs/archive ได้ |
| `.gitignore` | Dev config | ระบุ generated files ที่ไม่ควรเข้า version control | Git/tooling เท่านั้น |

## `source/services/` — หลังบ้านของโปรแกรม

| ไฟล์ | หน้าที่ | ถูกเรียกเมื่อ |
|---|---|---|
| `autostart.py` | จัดการการเปิดอัตโนมัติตาม OS | เปิด/ปิด Autostart ใน Settings |
| `web_service.py` | จัดการ start/stop/status ของ FastAPI + Next.js worker | หลังเปิด Desktop เมื่อ toggle เป็น ON และเมื่อผู้ใช้บันทึก Settings |
| `desktop_shortcuts.py` | สร้าง Shortcut Desktop/Web แบบ `.app`, `.lnk`, `.desktop` โดยชี้ source กลาง | หลัง First setup หรือกดสร้างใหม่ใน Settings |
| `legacy_history_import.py` | Preview/Backup/Import เฉพาะ Meter/Usage History จากสำเนา Database V4.6 | เมื่อผู้ใช้เปิด Import Database จาก Wizard |
| `background_polling.py` | worker เก็บข้อมูลเครื่องพิมพ์เบื้องหลัง | scheduler เริ่มงานหรือถึงรอบ poll |
| `polling.py` | กฎรอบ polling, retry และผลสถานะ | sync/manual/background poll |
| `sync_schedule.py` | ตารางเวลาและการตัดสินใจว่างานใดถึงเวลา | background scheduler/Settings |
| `snmp_probe.py` | ตรวจการเชื่อมต่อและข้อมูล SNMP ระดับ service | test connection และ poll |
| `daily_cache.py` | เก็บ opening/closing/delta รายวันก่อน rollup | เมื่อมี meter sample และปิดวัน |
| `billing_ledger.py` | ledger ค่าใช้จ่ายแบบ append-only/audit | ตอนยืนยัน billing event |
| `billing_periods.py` | คำนวณรอบบิล/cutoff | Reports และ billing calculation |
| `billing_v5.py` | กฎราคา/ค่าใช้จ่าย V5 | หน้า Billing/Reports |
| `pricing.py` | price list และประวัติราคา | คำนวณค่าใช้จ่าย/แก้ราคา |
| `usage.py` | สรุป usage/delta ตามเครื่องและช่วงเวลา | Reports > Usage |
| `monthly_history.py` | ประวัติรายเดือน | History/Reports |
| `subject_history.py` | ประวัติ user/account/subject | Reports > Users/Accounts |
| `device_config.py` | model/repository รายการเครื่อง | Settings, Overview และ poll |
| `live_meter_service.py` | orchestration อ่าน meter สด | manual/live collection |
| `reconciliation.py` | เทียบ source/field และประเมิน billing safety | หลังเก็บ meter ก่อนบันทึก/คิดเงิน |
| `import_service.py` | orchestration import และ validation | ผู้ใช้ import ไฟล์ |
| `import_worker.py` | ทำ import ใน worker ไม่ให้ UI ค้าง | ระหว่าง import |
| `summary_service.py` | สรุป KPI/overview | Overview และ report summary |
| `reporting_facade.py` | facade รวม query สำหรับรายงาน | Desktop Reports และ API |
| `report_scope.py` | filter ขอบเขตวัน/เครื่อง/subject | ก่อน query report |
| `report_excel_export.py` | สร้าง Excel export | เมื่อกด Export |
| `pipeline_log.py` | log เหตุการณ์ใน data pipeline | collect/import/cache/reconcile |
| `runtime_snapshots.py` | snapshot diagnostic/runtime state | troubleshoot และ support export |
| `instance_guard.py` | ป้องกันเปิด Desktop ซ้ำหลาย instance | ตอนเริ่มแอป |
| `__init__.py` | package marker | ตอน import package |

## `source/komi_snmp_profiler/` — ตัวเชื่อมเครื่องพิมพ์

| ไฟล์ | หน้าที่ |
|---|---|
| `models.py` | data model กลางของ meter, counter, auth และ confidence |
| `snmp_client.py` | ติดต่อ SNMP กับอุปกรณ์ |
| `connectors.py` | connector Web/SNMP และการเลือกช่องทาง |
| `meter.py` | อ่าน/ประกอบ meter reading |
| `km_counter_profile.py` | mapping counter ของ Konica Minolta |
| `oid_dictionary.py` | dictionary OID และความหมาย |
| `table_decoder.py` | ถอด SNMP table เป็น record |
| `counter_analyzer.py` | วิเคราะห์ counter ที่ค้นพบ |
| `calibration.py` | เก็บ/ใช้ผล calibration |
| `print_calibration.py` | workflow calibration ที่เกี่ยวกับงานพิมพ์ |
| `system_print.py` | adapter สั่งพิมพ์ตาม OS; Linux ต้องทดสอบแยก |
| `credential_store.py` | อ่าน/เก็บ credential ตาม policy ของเครื่อง |
| `service.py` | orchestration profiler ระดับ service |
| `exporter.py`, `meter_export.py` | export ผล profiler/meter |
| `cli.py`, `app.py` | command-line/แอป profiler สำหรับช่างและการวิเคราะห์ |
| `__init__.py` | package marker |

Profiler เป็น backend/support tool ไม่ใช่หน้าจอรายงานหลัก แต่ service ของแอปนำ model และตัวอ่าน meter บางส่วนไปใช้

## `source/tools/` — เครื่องมือพัฒนาและ support

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `launch_doctor.py` | ยืนยัน Python, path source กลาง และสร้าง Source ID ก่อนเปิดแอป |
| `init_web_access.py` | สร้าง/อ่าน login และ session secret ใน local Web runtime; รองรับ migrate ค่าเดิมโดยไม่เก็บ secret ใน OneDrive |
| `prepare_web_runtime.py` | mirror เฉพาะ Web source ไป runtime local, ติดตั้ง dependency และ build เมื่อ source เปลี่ยน |
| `run_web_servers.py` | เปิด FastAPI/Next.js, รอ port พร้อม, เปิด browser และหยุด process ลูกเมื่อปิด launcher |
| `web_service_worker.py` | เตรียม Web runtime แล้วรัน server เป็น process ลูกของ Desktop โดยไม่เปิด browser ซ้ำ | เมื่อ `WebServiceManager` เริ่ม service |
| `build_local_release.py` | build release ในเครื่อง |
| `package_macos_release.py` | package macOS |
| `package_windows_test_kit.py` | package ชุดทดสอบ Windows รุ่นเดิม |
| `check_parser.py` | ตรวจ parser กับไฟล์ตัวอย่าง |
| `setup_parser_profiles.py`, `default_profiles.json` | เตรียม parser profile เริ่มต้น |
| `benchmark_summary.py` | benchmark summary query |
| `generate_diagram.py` | สร้าง diagram เอกสาร |
| `preview_colors.py` | preview สี UI |
| `CustomHistory.py` | utility ประวัติแบบ custom/legacy; ตรวจ import ก่อน archive |
| `PARSER_SETUP_README.md` | คู่มือ parser tool |
| `__init__.py` | package marker |

## `web/` — หน้าบ้าน Web

| ไฟล์/โฟลเดอร์ | หน้าที่ |
|---|---|
| `app/page.tsx` | dashboard page หลัก |
| `app/login/page.tsx` | หน้า login |
| `app/layout.tsx` | layout/root metadata |
| `app/icon.png` | favicon/Web app icon จาก master logo เดียวกับ Desktop |
| `app/globals.css`, `app/status.css` | style หลักและ status |
| `app/report-views.tsx` | report components |
| `app/cloud-report-views.tsx` | report view แบบ cloud-inspired |
| `app/dashboard-types.ts` | TypeScript types ของ dashboard/API |
| `app/auth/session/route.ts` | route จัดการ session |
| `lib/session.ts` | helper session/auth |
| `proxy.ts` | request proxy/middleware layer |
| `package.json`, `package-lock.json` | Node dependency และ lock |
| `next.config.ts`, `tsconfig.json`, `next-env.d.ts` | Next.js/TypeScript config |
| `.env.local` | secret/runtime config | ไม่อยู่ใน source; สร้างใน local Web runtime ของแต่ละ OS |
| `.next/` | Generated build/cache | ลบได้; สร้างใหม่ด้วย Next.js |
| `README.md` | วิธีใช้ Web Edition |

## `source/tests/` — หลักฐานอัตโนมัติ

ไฟล์ `test_*.py` ไม่ทำงานตอนผู้ใช้เปิดโปรแกรม แต่ใช้พิสูจน์แต่ละส่วน:

- `test_database`, `test_migrations`, `test_runtime_config`: database/schema/config
- `test_polling`, `test_sync_schedule`, `test_background_polling`, `test_snmp_probe_v5`: sync และ collection
- `test_daily_cache`, `test_billing_*`, `test_pricing`, `test_usage`, `test_*history`: meter/billing/history
- `test_import_*`, `test_parser_profiles`: import/parser
- `test_reporting_facade`, `test_summary_service`, `test_report_excel_export`: reports/export
- `test_overview_v5_ui`, `test_cloud_reports_ui`, `test_settings_v5`, `test_sidebar_navigation`, `test_sync_log_page`, `test_i18n`: Desktop UI
- `test_web_api`: FastAPI contract
- `test_autostart`, `test_instance_guard`, `test_tray_lifecycle`, `test_app_setup`: app lifecycle/OS integration
- `test_web_service`, `test_desktop_shortcuts`: Web lifecycle และ Shortcut canonical-source contract ของ macOS/Windows/Linux
- `render_ui_matrix_v5.py`, `test_manual_diagrams.py`: visual/manual QA support
- `conftest.py`: fixture และ test bootstrap
- `profiler/`: test data/case เฉพาะ SNMP profiler

ห้ามลบ test เพียงเพราะผู้ใช้ไม่เห็น เพราะเป็นตาข่ายป้องกันการแก้แล้วทำส่วนอื่นเสีย

## ไฟล์ที่ลบหรือย้ายได้หลัง verification

### ลบได้และสร้างใหม่ได้

- `__pycache__/`, `*.pyc`
- `.pytest_cache/`, `.ruff_cache/`
- `web/.next/`
- `.DS_Store`
- cache ของ Playwright

### ย้ายเข้า archive ได้

- release รุ่นเก่า เมื่อมี manifest/hash และ release ล่าสุดเปิดได้แล้ว
- screenshot QA รุ่นเก่าที่มีภาพใหม่แทน
- preview/presentation ระดับ root ที่ไม่ได้ถูกอ้างในเอกสาร
- launcher legacy หลัง Mac/Windows/Linux ผ่านอย่างน้อยหนึ่งรอบใช้งานจริง

### ห้ามลบตอนนี้

- `_recovery/2026-08-09-onedrive-live-reconcile/`
- database/ไฟล์ข้อมูลภายใต้โฟลเดอร์ผู้ใช้

สถานะปัจจุบัน: conflict copy นอก `_recovery` เท่ากับ 0, `source/.venv`, `web/.env.local`,
`release/` และ `_reconcile/` ไม่มีอยู่แล้ว; runtime และ credential ถูกแยกออกจาก OneDrive สำเร็จ

## กติกาให้ทุก OS เปิดโค้ดเดียวกัน

1. แก้โค้ดเฉพาะ canonical `source/` ใน OneDrive
2. ห้ามแก้ source ที่อยู่ใน `release/`, `.app` หรือ portable ZIP
3. รอ OneDrive sync เสร็จก่อนสลับเครื่อง
4. แต่ละเครื่องเลือก `source/` เป็น **Always keep on this device**
5. เปิดด้วย launcher ระดับ root ของ OS นั้น
6. เปรียบเทียบ `Source ID` ที่ launcher/doctor แสดง หากเหมือนกันคือไฟล์หลักเหมือนกัน
7. Python/dependency อยู่ local ต่อ OS; `pyproject.toml` และ `uv.lock` ใน OneDriveเป็น authority เดียว

Windows VM ที่ไม่มี OneDrive ใช้ Shared Folder ชี้ root โปรเจกต์ได้ โดย launcher รองรับ UNC path;
หลักฐานวันที่ 2026-08-09 ได้ Desktop/Web Source ID ตรงกับ Mac, เปิด Desktop, Login Web และโหลด Overview สำเร็จ

ข้อจำกัดการพิสูจน์: การผ่านบน macOS ไม่ได้แปลว่า Windows/Linux ผ่าน ต้องทำ native UAT แยกแต่ละระบบ
