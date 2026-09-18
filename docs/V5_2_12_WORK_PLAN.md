# KOMI 5.2.12 — approved work and handoff

User authorized sequential autonomous implementation on 2026-09-17. Continue
completed items into the next unblocked item. Park only decisions that genuinely
need user input. Communicate in Thai. No installers, release builds, deployments,
publishing, or production Host/customer mutations until explicitly authorized.
Source tests and local previews are allowed. Update this file with evidence.

## Baseline / preserve

Work in this task's worktree, now on local branch main after the user's explicit
2026-09-18 request to merge the work into main. Development originated on
codex/v5.2.12-registration-recovery, based on
bf453738b934dcf5bea59dd8c70e191b52ba6b89 (committed 5.2.11).
Do not modify the original Documents/KOMI Report V5 checkout. Do not import its
uncommitted registration-pending unlock policy. Current recovery work is a
disabled foundation, not a working customer Hotfix. UI preview is a prototype.

## Approved requirements

1. Equal peers, no permanent Primary/Secondary. Every member collects printer
   readings, exchanges missing observations without double counting, and shares
   backups/settings. Sync at startup and every five minutes. Offline peers catch
   up. Automatic LAN joining/rejoining. Unlimited computers, one company with
   three shared printer slots. Member list with connectivity and last sync.
2. Settings changes shared across members; confirmation popup lists old/new
   values and warns all members are affected, offline members later. No new admin
   account module. Conflicts require selection. Audit machine/time/old/new;
   selective undo creates another audited change and requires confirmation.
3. Prices have an effective date. Retroactive recalculation previews dates,
   affected billing periods and differences before confirmation. Issued/closed
   reports remain immutable; create amended versions and differences.
4. Slot replacement preserves history and accumulated usage. Require a real new
   serial/meter read, show old/new confirmation, use the new meter as baseline,
   sync identical baseline to peers. Same serial with falling meter raises an
   alert shared by all peers; no silent reset or negative usage. Missing days:
   recover actual history where available, otherwise show interval usage without
   invented daily allocation. Do not automatically hold all catch-up usage.
5. Network settings redesign: name การตั้งค่าเครือข่าย, consistent controls,
   fewer nested frames, Web URL/open/copy, collapsible port, shared member
   controls instead of permanent roles. Clear save/service feedback. Audit in
   Status/history. Test actual save/cancel/restart and port conflicts.
6. Web refresh every 60 seconds plus manual refresh. Keep last successful data
   and timestamp with stale warning when offline. No false zero on initial
   failure. Passwordless reports by default, optional password, preserve prior
   locked settings. Shortcut created on installation plus recreate control;
   every computer opens its own local Web service (supersedes redirection).
7. Headless agent owns collection/sync/Host/Web; closing UI releases UI resources
   but keeps agent running. Reopen without duplicate services. Tray action to
   stop everything requires confirmation. Measure whole-process-tree CPU/RAM,
   idle/collection/sync/Web and lifecycle transitions.
8. Twelve recent months detailed. Older data summarized monthly per printer and
   user; archive originals by year, load only on explicit detail request or
   confirmed retroactive recalculation. Validate before removal, preserve audit
   and availability across peers. No uncontrolled deletion of original data.
9. Registration certificate Hotfix is installer opt-in after normal verification
   fails, initial contract registration only, bound durable idempotent retry,
   permanent closure after valid acknowledgement. Status/Meter keep normal TLS
   and queue retry. No global TLS change, no temporary/free activation policy.
10. Refactor touched monolith sections behind regression tests. Identify dead
    code before deleting. Inventory old evidence and verify commit/push/tag or
    Release plus references before removing any. Preserve Git history and useful
    regression tests. Refresh manuals/screenshots after behavior settles BEFORE
    any user-authorized build.

## Unresolved — park dependent release behavior

- Hotfix Host authentication: native Windows trust vs verified pin. No approved
  pin exists. Do not trust an unvalidated observed certificate.
- Authoritative company identity and Host company-wide three-slot enforcement;
  LAN name/discovery alone is not proof of company membership. User deferred
  investigating Host showing only one name after settings sync; inspect separate
  installation IDs rather than assuming shared identity is correct.
- Missing data across price/billing boundaries: inspect available source history;
  do not invent a daily allocation or pricing rule.
- Installer architecture/build workflow awaits explicit user decision.

## Work order / status

- [x] Persist requirements and blockers.
- [x] Capture regression baseline and inventory current edits.
- [x] Web: periodic refresh + correct stale/initial-failure behavior, local UI checks.
- [x] Merge completed development into local main; preserve old main and Documents edits.
- [ ] P1 — settings-save history, atomic application, conflict review and undo.
- [ ] P2 — Agent ownership and continuous authorized settings exchange.
- [ ] P3 — complete network settings and local Web/shortcut behavior.
- [ ] P4 — slot replacement and meter-review workflow across peers.
- [ ] P5 — missing-observation exchange and shared backup/recovery.
- [ ] P6 — effective pricing, recalculation previews and amended reports.
- [ ] P7 — annual archive, monthly summaries and large-database performance.
- [ ] P8 — integrated multi-instance QA, cleanup and updated manuals.
- [ ] H1 — inspect available Host implementation; resolve demonstrated contract/trust gaps.
- [ ] R1 — user review and explicit build decision; installer/upgrade QA WAIT BUILD.

## แผนลงมือฉบับปัจจุบัน — 18 กันยายน 2569

แผนนี้เป็นลำดับงานถัดไปแทนข้อความ “Next” ในบันทึกเก่าด้านล่าง งานแต่ละช่วง
ต้องมีการเชื่อมเข้าทางใช้งานจริงและผลทดสอบก่อนติ๊กเสร็จ การมี API หรือโมดูล
ที่ทดสอบแยกผ่านอย่างเดียวยังไม่ถือว่าฟีเจอร์เสร็จ ทำบน local main ใน worktree นี้
ไม่ push ไม่ build installer/release และไม่แก้ข้อมูล Host/ลูกค้าจริง

### P1 — บันทึกและใช้การตั้งค่าอย่างถูกต้อง (งานถัดไปทันที)

- ตรวจทุกจุดบันทึกใน Settings/Setup และแยกค่าที่แชร์ออกจากค่าประจำเครื่อง
  เช่น installation ID, credentials และตำแหน่งไฟล์ ห้ามคัดลอกตัวตนเครื่องทับกัน
- บันทึกการเปลี่ยนค่าและ revision ใน transaction เดียว ไม่รอเก็บ snapshot
  ตอนมีเครื่องอื่นมาขอข้อมูลเพียงอย่างเดียว
- ทำ preview ค่าเดิม/ค่าใหม่ และ popup แจ้งผลต่อทุกคอม รวมเครื่องที่ออฟไลน์
  รับค่าและเปลี่ยน journal head พร้อมกัน หรือย้อนกลับทั้งหมดหากบันทึกล้มเหลว
- ต่อหน้าจอเลือกเมื่อแก้ไขขัดแย้ง เก็บเหตุผล เครื่อง เวลา และค่าก่อน/หลัง
  ย้อนการเปลี่ยนแปลงด้วยรายการใหม่ ไม่ลบประวัติ และตรวจว่าค่าเปลี่ยนหลัง preview หรือไม่
- ผ่านเมื่อ: ยกเลิกแล้วข้อมูลไม่เปลี่ยน; จำลองบันทึกขาดกลางทางแล้วไม่มีค่า/ประวัติ
  ครึ่งชุด; แก้ชนกันไม่เขียนทับเงียบ; ส่งซ้ำไม่เกิดรายการซ้ำ; เปิดใหม่ยังมีประวัติครบ

### P2 — Agent และ sync การตั้งค่าต่อเนื่อง

- ตรวจการส่งต่องาน desktop → Agent → desktop กับบริการอ่านข้อมูลและ Web
  ให้มีผู้ทำงานชุดเดียว คืนทรัพยากรหน้าต่างเมื่อปิด และปิดทั้งหมดผ่าน tray พร้อมยืนยัน
- แนวทางที่ผู้ใช้อนุมัติเพิ่ม: ให้ Wizard ประกาศค้นหาใน LAN และให้ Agent ที่ออนไลน์
  ตอบกลับตรงไปยังผู้ถาม จากนั้นตรวจสิทธิ์และดึงค่าผ่าน HTTPS; ประกาศเฉพาะข้อมูลค้นหา
  ไม่ส่งการตั้งค่าทั้งชุดแบบ broadcast ลองซ้ำแบบจำกัดครั้ง และมีปุ่ม “ค้นหาอีกครั้ง”
  เมื่อไม่มีใครตอบ พร้อมทางกรอก IP/การค้นหาเดิมเป็น fallback ไม่สรุปว่าไม่มี KOMI
  เพียงเพราะไม่ได้รับคำตอบ เตรียมและทดสอบกฎ Firewall เฉพาะโปรแกรม/พอร์ต/เครือข่าย
  ตามนโยบายองค์กร โดยไม่ปิด Firewall หรือข้ามข้อจำกัดส่วนกลาง
- แยก discovery ออกจากการอนุญาตรับข้อมูล
  เก็บสมาชิก/การเชื่อมต่อที่ยืนยันแล้ว เพื่อกลับมาเชื่อมใหม่โดยไม่ตั้งค่าใหม่ทุกครั้ง
  ไม่ใช้ชื่อบริษัทหรือชื่อ LAN เป็นหลักฐานสิทธิ์ และไม่เพิ่มบทบาทผู้ดูแลใหม่
- ทุกคอมเป็น peer เท่าเทียม ไม่มี primary ถาวร แลกค่าตอนเริ่มและทุก 5 นาที
  แบ่งหน้าประวัติให้พ้นข้อจำกัด 256 revisions/128 KiB ได้โดยไม่ตัดข้อมูลทิ้ง
- retry เมื่อหลุดโดยไม่ทำงานซ้อน เครื่องกลับมาออนไลน์รับส่วนที่ขาด ข้อขัดแย้ง
  ใช้ขั้นตอน P1 การค้นพบ peer อย่างเดียวไม่ทำให้ค่าถูกนำมาใช้ทันที
- ผ่านเมื่อ: จำลองสอง process ฐานข้อมูลแยก ปิดสลับ/หลุด/เปิดกลับแล้วค่าตรงกัน;
  ไม่มี Agent หรือ collector ซ้ำ; Web ยังให้บริการหลังปิดหน้าต่าง;
  วัดทั้ง process tree ขณะว่าง อ่านข้อมูล sync และเปิด Web พร้อมระบุสภาพทดสอบ

### P3 — หน้าการตั้งค่าเครือข่ายและ Web

- เติมสมาชิก สถานะการเชื่อมต่อ เวลาสำเร็จล่าสุด และเหตุที่ sync ยังไม่สำเร็จ
  ใช้ชื่อ “การตั้งค่าเครือข่าย” และรูปแบบเดียวกับหน้าตั้งค่าอื่น ยุบพอร์ตในส่วนขั้นสูง
- ต่อปุ่มเปิด/คัดลอก Web URL และสร้าง shortcut ใหม่ให้เปิดบริการของคอมเครื่องนั้น
  ตรวจโลโก้และรหัสผ่านแบบเลือกได้ โดยรักษาการล็อกเดิมของผู้ใช้
- บันทึก/ยกเลิก/เริ่มบริการใหม่ต้องแสดงผลจริง รวมกรณีพอร์ตชนหรือเปิดบริการไม่ได้
- ผ่านเมื่อ: ตรวจหน้าจอจาก source ในธีมจริง ไม่มีข้อความหรือปุ่มถูกตัด;
  เปิด shortcut ได้หลังปิด UI; รีเฟรช 60 วินาทียังทำงาน และ outage ไม่แสดงศูนย์หลอก
- ส่งภาพและขั้นตอนให้ผู้ใช้ตรวจได้ในช่วงนี้ งานส่วนอื่นทำต่อได้ระหว่างรอความเห็น

### P4 — เปลี่ยนเครื่องพิมพ์ใน slot ให้ครบ

- ผูก Serial กับค่าที่อ่านได้จากรอบตรวจเครื่องจริง แสดงเครื่องเก่า/ใหม่และ baseline
  ก่อนยืนยัน รองรับเปลี่ยนหลายครั้งในวันเดียว ข้ามวัน และข้อมูลรายผู้ใช้
- เก็บประวัติเป็นช่วงตามเครื่องที่อยู่ใน slot และคงยอดสะสมของ slot
  ใช้ decision ID/baseline เดียวกันเมื่อส่งให้ peer; ห้ามแต่ละคอมตั้งฐานคนละค่า
- มิเตอร์ลดลงใน Serial เดิมใช้ขั้นตอนตรวจสอบ ส่งสถานะและผลยืนยันให้ทุกคอม
  วันที่ยังตรวจยอดไม่ได้ต้องแสดงสถานะชัดเจนก่อนนำไปคิดเงิน
- ผ่านเมื่อ: ยอดเดิม 200 + เปลี่ยนเป็นเครื่องมิเตอร์ 9000 + พิมพ์อีก 10 = 210;
  ทุก peer ได้ผลเดียวกัน แม้กลับมาออนไลน์ทีหลัง; เก็บที่มารายผู้ใช้และประวัติเครื่องเก่าครบ

### P5 — เติมข้อมูลที่ขาดและสำรองระหว่างเครื่อง

- ออกแบบข้อมูลการอ่านให้มีที่มา Serial/ช่วงที่อยู่ใน slot และเวลาสังเกตจริง
  เก็บข้อมูลต้นทางแยกจากยอดที่คำนวณ ห้ามบวก delta ของแต่ละคอมเข้าด้วยกันตรง ๆ
- แลกเฉพาะข้อมูลที่ขาดด้วย cursor/checkpoint ป้องกันการรับซ้ำและการอ่านช่วงทับกัน
  ค่าคนละชุดที่อ้างถึงการอ่านเดียวกันต้องตรวจสอบ ไม่เลือกตามเวลารับเพียงอย่างเดียว
- กู้ประวัติจริงจากเครื่องพิมพ์เมื่อมี หากมีเพียงยอดข้ามหลายวันให้แสดงยอดของช่วงนั้น
  ไม่เฉลี่ยสร้างยอดรายวันเอง และไม่พักยอด catch-up ทุกกรณีโดยอัตโนมัติ
- ทำชุดสำรองที่มี manifest/hash ตรวจความครบก่อนประกาศว่าสำเร็จ แยกความเสียหาย
  ออกจากการลบที่ผู้ใช้ตั้งใจ และทดสอบกู้คืนในฐานข้อมูลจำลอง
- ผ่านเมื่อ: สองเครื่องมีข้อมูลคนละช่วงแล้วรวมได้ครบ; ส่งซ้ำ/ส่งสลับลำดับยอดไม่เพิ่ม;
  หยุดระหว่างโอนแล้วเริ่มต่อได้; กู้ชุดสำรองแล้วรายการและยอดตรวจสอบตรงกัน

### P6 — ราคาและรายงานย้อนหลัง

- เก็บประวัติราคาพร้อมวันบังคับใช้และแชร์ผ่านระบบเดียวกัน แสดงช่วงวันที่ รอบบิล
  และยอดต่างก่อนยืนยันคำนวณใหม่
- รายงานออกแล้วเก็บฉบับเดิม สร้างฉบับแก้ไขพร้อมเหตุผลและความต่าง
  กรณีข้อมูลไม่พอแบ่งยอดข้ามช่วงราคา ให้แสดงข้อจำกัด ไม่เดาหลักคิดเงิน
- ผ่านเมื่อ: ราคาเก่า/ใหม่ใช้ถูกวัน; คำนวณซ้ำได้ผลเดิม; ยกเลิก preview ไม่แก้ข้อมูล;
  รายงานเดิมไม่ถูกเขียนทับ และทุก peer อ้างฉบับรายงานเดียวกัน

### P7 — Archive และประสิทธิภาพ

- เก็บรายละเอียดล่าสุด 12 เดือน สรุปข้อมูลเก่าเป็นรายเดือนต่อเครื่อง/ผู้ใช้
  จัด archive รายปีพร้อม manifest/hash และเก็บประวัติการแก้ไข
- ตรวจยอด จำนวนรายการ และอ่านคืนได้ก่อนลดรายละเอียดในฐานหลัก
  โหลดรายละเอียดเฉพาะผู้ใช้ขอหรือยืนยันคำนวณย้อนหลัง พร้อมระบุตำแหน่งสำเนาบน peer
- ผ่านเมื่อ: ยอดก่อน/หลังตรงกัน; archive ขาดหรือเสียไม่ทำให้ต้นฉบับหาย;
  วัดเวลาเปิดรายงานรายเดือนและเรียกรายละเอียดกับข้อมูล 5 ปี/100 ผู้ใช้
  บันทึกตัวเลขจริงโดยไม่ตั้งเป้า RAM/ความเร็วที่ยังไม่ได้พิสูจน์

### P8 — ทดสอบรวม เก็บกวาด และคู่มือ

- ทดสอบ source หลาย instance แบบ end-to-end: เริ่มใช้ใหม่, ออฟไลน์,
  แก้พร้อมกัน, เปลี่ยนเครื่อง, เปลี่ยนราคา, archive, กู้ข้อมูล, ปิด/เปิด Agent
- ตรวจโค้ดไม่ได้ใช้จากจุดเรียกและการทดสอบ แยกส่วนที่แตะจากไฟล์ใหญ่
  ตรวจ commit/remote/tag และการอ้างอิงก่อนลบหลักฐานเก่า ไม่ถือว่าอยู่บน GitHub แล้วโดยเดา
- เขียนคู่มือจากพฤติกรรมที่ทำเสร็จ พร้อมภาพจริง การตั้งค่าเครือข่าย การปิด Agent
  ข้อขัดแย้ง การเปลี่ยนเครื่อง ราคา และเรียก archive; ต้องเสร็จก่อนขอ build
- ผ่านเมื่อ: รายการทดสอบมีผลและข้อจำกัดชัดเจน ไม่มีฟีเจอร์ที่ยังเป็นเพียงแกนภายใน
  ถูกทำเครื่องหมายว่าเสร็จ และคู่มือตรงกับหน้าจอที่ส่งให้ตรวจ

### H1 — ตรวจ Host โดยไม่ขวางงานที่ทำต่อได้

- ใช้บัญชี in-app ที่ผู้ใช้ล็อกอินไว้ตรวจแบบอ่านอย่างเดียว และตรวจ source/contract
  ที่เข้าถึงได้ แยกข้อเท็จจริงจากหน้าจอออกจากพฤติกรรม backend ที่ยังไม่ได้พิสูจน์
- หากไม่มีโค้ด backend ให้แจ้ง path/repository หรือ API contract ที่ต้องใช้จริง
  ไม่ถามให้ผู้ใช้ออกแบบเทคนิคแทน และไม่ถือว่า UI ที่ไม่แสดงรหัสแปลว่าไม่มีรหัสในฐานข้อมูล
- ตรวจการผูกบริษัท/installation/สาม slot และ TLS แยกจากการค้นหา LAN
  ถ้าต้องเปลี่ยน Host ให้เตรียม patch/ผลทดสอบให้ตรวจ แล้วขออนุญาตก่อนแก้ production
- ปิดหัวข้อนี้เมื่อมีหลักฐานวิธีบังคับสิทธิ์และวิธีเชื่อถือใบรับรองที่ใช้ได้จริง
  หรือบันทึกข้อที่ขาดแบบเจาะจง; ทำ P1–P8 ที่ไม่ขึ้นต่อข้อขาดนั้นต่อไป

### ผู้รับผิดชอบและจุดรอผู้ใช้

| ผู้ทำ | สิ่งที่ต้องทำ |
|---|---|
| AI | ลงมือ P1–P8, ตรวจ H1 เท่าที่เข้าถึงได้, ทดสอบ source, บันทึกหลักฐาน/ข้อจำกัด และ commit ในเครื่อง |
| ผู้ใช้ | ตรวจหน้าตา/ขั้นตอนเมื่อมีตัวอย่างพร้อม; ให้สิทธิ์ Host เพิ่มเฉพาะส่วนที่ตรวจแล้วขาดจริง |
| ผู้ใช้ + AI | ตรวจบนคอมสองเครื่องและเครื่องพิมพ์จริง เมื่อมีชุดทดสอบพร้อม; AI เตรียมขั้นตอนและเก็บผล |
| ผู้ใช้ | ตัดสินใจแนวทาง build/installer และอนุญาต build ภายหลัง ไม่รวมอยู่ในแผนลงมือปัจจุบัน |

ไม่หยุดรอคำตอบสำหรับงานที่อนุมัติแล้ว เมื่อรายการหนึ่งติดข้อมูลให้บันทึกสาเหตุ
แล้วทำรายการที่ไม่ขึ้นต่อกันต่อ อัปเดต checkbox เฉพาะเมื่อเกณฑ์ของช่วงนั้นผ่าน
การ build, ติดตั้ง/อัปเกรดจาก installer และเผยแพร่เป็น R1 ที่ยังไม่อนุญาต

## Existing evidence (not release approval)

### 2026-09-18 — approved discovery design and Wizard retry

- User approved announce/respond discovery as the primary installation path and
  explicitly requested a retry button after no response. P2 above now records
  this approach, direct HTTPS settings transfer, bounded retries, manual/IP-scan
  fallback and scoped firewall testing. UDP transport is still to be implemented.
- Wizard now keeps its discovery card visible after an empty/error result with
  “ค้นหาอีกครั้ง” (Search again), using the existing asynchronous discovery entry
  point. The manual-IP fallback remains available. A successful retry returns to
  Import settings; stale error tooltips clear on a fresh attempt/completion.
- **59 Wizard source tests passed**, including empty-result visibility, repeat
  retry after failure and transition to found results. Synthetic offscreen view
  checked at 1120x720; shortened the status copy after initial render clipping.
  Final image: `Temp/komi-wizard-retry-c_xqo7cq/retry-final.png`. No live LAN scan,
  Host requests, firewall changes or build. The retry button currently uses the
  existing IP discovery; this is not evidence that broadcast is implemented.

### 2026-09-18 — authenticated Host UI inspection (read only)

- User supplied an already authenticated in-app browser session. Inspected the
  KOMI Report section and one previously discussed test-named installation in
  the live list; only navigation/read actions were performed. No registration,
  license issuance, disable/revoke, export, or production data changes.
- UI explicitly describes company count as an estimate from normalized names.
  List/detail are installation-based and show selected printer slots, masked
  serials, meter observations and heartbeat history. The staging view showed
  no installations at inspection time.
- No authoritative company/group key was exposed in the inspected detail.
  Local `v5_2_contract.py` uses installation_id + company_name and per-payload
  slot validation. These observations do not prove the Host database lacks a
  company key or prove an exploitable company-limit bypass. Host server code and
  its enforcement have not been inspected. Continue local sync implementation;
  do not treat this uncertainty as a reason to wait on unrelated work.

### 2026-09-18 — LAN discovery audit and causal settings history

- User instructed continuing after discussion of differing LAN announcements.
  Inspection found bounded IP scanning plus HTTPS discovery/setup fetch in
  `secondary_setup.py`, not UDP settings broadcasts or periodic peer replication.
  Existing v1 setup is a one-time authorized snapshot import without ancestry.
  No demonstrated cross-company exploit was found; do not present hypothetical
  company risks as a blocker to this implementation work.
- Schema 20 adds durable settings revision/state tables. New
  `peer_settings_history.py` records normalized shared snapshots with parent
  revisions, random persistent local actor ID, timestamp and reason. It excludes
  local installation ID and snapshot generation time from shared values. This
  actor ID is not a company identity or authorization credential.
- Import validates hashes, allowed fields, ancestry and bounded packet size in
  one transaction. It classifies same revision, incoming/local newer, same values,
  conflicting branches and unrelated histories without sorting by clock time.
  Receive never changes local settings or local head. Explicit journal resolution
  retains both parents and rejects a stale local head.
- Added typed `/api/v2/peer/settings-history` and a client fetch method using the
  existing certificate pin/one-use claim token flow; Web proxy forwards the exact
  endpoint, with authorization still enforced by Python. v1 remains compatible.
  No settings POST/apply endpoint or relaxed authorization was introduced.
- **56 Python tests passed** across history, migrations, secondary setup,
  authorization and Web API; **6 Web security tests passed** on a temporary copy
  using existing dependencies. Direct Web test attempt initially lacked the
  worktree's Next dependency; temporary dependency setup fixed the harness.
  Synthetic separate SQLite journals cover offline edits, duplicate deliveries,
  diverging edits, clock skew, stale resolution, malformed history rollback,
  restart persistence and endpoint token replay rejection. No printer/Host calls.
- Still unfinished: capture each settings save transaction, atomic application
  of chosen values together with journal head, conflict preview/choice UI, startup
  and five-minute exchange, durable peer membership, history paging beyond
  256 revisions/128 KiB, and data/backup sync. `resolve` currently changes journal
  state only and must not be wired as an app-setting apply action on its own.
  Export observes current settings, not every intermediate save. This is a tested
  protocol/history foundation, not completed continuous sync.
- Next: integrate settings-save auditing and transactional application before
  wiring conflict UI and automatic exchange. No user answer is needed for this
  next implementation step. No build, publish or Documents/customer mutations.

### 2026-09-18 — user-authorized merge into local main

- User clarified that the new work should be merged into the main branch because
  the old main is outdated. Kept the development branch and created
  `backup/main-before-v5.2.12-20260918` at the prior main tip `facc677`.
- Merged the development history through `fd1dfa6` without source conflicts.
  Removed main's obsolete `tmp-v528-hotfix-patcher.yml`: its sole purpose was
  committing and pushing V5.2.8 metadata into an old hotfix branch. Its history
  remains available; this merge does not authorize any push or release.
- This task continues on main in the same worktree. Documents checkout and its
  uncommitted changes are preserved. Open feature work and no-build restrictions
  above still apply; merging is not a declaration of release readiness.
- Merge verification: **47 source tests passed** across replacement, daily cache,
  counter review engine/UI and billing ledger. No unresolved merge entries;
  merged source matches the tested development branch except removal of surplus
  trailing blank lines in an existing TLS test. This plan was updated as well.
  Whitespace validation passed after that formatting cleanup.

### 2026-09-18 continuation — same-day slot replacement foundation

- Daily cache now quarantines newer Web observations from a conflicting serial
  without adding their absolute counters to the old printer's usage. Candidate
  host must match the current device; negative/nonfinite or older values cannot
  replace the candidate. Finalization preserves unconfirmed candidate evidence.
- Extracted `services/slot_replacement.py` with explicit preview/confirm APIs.
  Requires different known serials, matching host/counter mapping/schema, an
  unchanged preview revision, actor/reason and valid confirmation time. Closed
  days reject changes. No UI or automatic caller invokes confirmation yet.
- Confirmation retains old segment evidence and accumulated daily usage, uses
  the observed replacement meter as the next baseline, and audits the decision.
  Mixed-printer days remain held for billing even if later reconciliation passes.
  No finalized history is rewritten or company authorization inferred.
- **44 source tests passed**: slot replacement, daily cache, counter review and
  billing ledger. Synthetic example: old usage 20, used meter 9000 then 9015
  yields 35, not 9035; a second replacement 500 then 503 yields 38. Next-day
  increments resume from the latest baseline. Stale/changed identity, mapping,
  finalized-day rejection and preserved unconfirmed evidence covered.
- Still unfinished: bind serial/meter to one verified live probe, subject/user
  counter transitions, cross-day pending replacement, UI confirmation, shared
  peer decisions and amended reports. Current APIs use repository identity and
  are a local same-day foundation, not a completed replacement workflow.
- User requested morning status during this chunk. No build, publish, real
  printer/Host calls or customer database writes were performed.

### 2026-09-18 continuation — counter review UI

- Added Meter review under Settings / Status and history, in an extracted
  `ui/counter_review.py` panel. Today's pending counters open a nonblocking
  preview showing printer, serial, counter label, old/new observation and
  preserved usage. Confirmation requires a reason and explicit serial/meter
  verification; Cancel is the default action.
- Confirmation records the computer name and reason through the existing
  revision-checked API. Changed observations reject the open preview; reopening
  reads the new baseline. Cancel leaves cache bytes unchanged. A successful
  confirmation removes the pending row but does not release held billing.
- Source tests: **47 passed** across counter review engine/UI, pipeline log,
  settings navigation and settings V5. Updated navigation coverage for the new
  fourth status tab. `git diff --check` passed.
- Rendered the actual dialog offscreen against a temporary synthetic database:
  `Temp/komi-counter-review-final-ccanocz9/dialog.png`. This checks text/layout,
  not native desktop interaction or full application theme acceptance.
- Scope is explicitly local in the dialog. Peer replication of confirmation,
  different-serial slot replacement, amended reports and shared audit remain
  unfinished. No installer/release build, publish or production Host activity.
- Next unblocked work: inspect different-serial slot replacement and preserve
  cumulative usage with a reviewed baseline. Company/Host enforcement stays
  parked until authoritative identity is provided.

### 2026-09-18 continuation — explicit baseline resolution engine

- Added preview/confirm APIs to DailyCacheStore for an unresolved counter. A
  preview includes printer identity, old counter, observed new baseline/time,
  preserved usage and a revision digest. Confirmation requires the same revision,
  matching known serial, a current Web observation, actor/reason and valid time.
  Heartbeat-only carried values cannot be confirmed as a new baseline.
- Confirmation atomically appends an audit record (ID, actor, reason, serial,
  before/baseline/observed/resolved times, preserved delta) with clearing the
  pending marker. It does not add the absolute baseline to usage. New increments
  resume from the reviewed observation. Repeated confirmation cannot apply twice;
  a later counter drop creates a new review.
- Finalized days and changed observations/identity reject stale confirmation
  without altering cache or persisted daily records. Resolution-day billing stays
  held for review; no historical recalculation or pricing allocation is invented.
  Audit travels into daily source JSON on finalization.
- Counter review/cache/billing suite: **34 passed**. All synthetic data and
  temporary databases, no Host activity.
- Still pending: confirmation dialog wiring, peer replication of decisions,
  slot replacement (different serial), and amended-report release of held periods.
  APIs are not invoked automatically and do not imply a completed user workflow.

### 2026-09-18 continuation — falling meter safeguard

- Moved to slot/meter work while native Tray verification remains outstanding.
  Found daily cache treated a falling counter as a zero reset and added its new
  absolute value to usage (100→7 added 7). Removed that automatic interpretation.
- Counter drops now retain the known accumulated delta and observed raw values,
  record a per-counter review marker and warning in the pipeline log, and stop
  accumulating that counter until an explicit resolution exists. Catching back
  up above the former value does not silently clear review. Other counters are
  not rewritten. Existing billing reset hold is retained.
- Review evidence persists in daily source JSON and carries forward for the
  same device identity across restart/day rollover, direct Web fallback without
  SNMP heartbeat, and intervening offline-only days. This does not change the
  separate missing-interval pricing policy or invent daily usage.
- Cache/billing/polling/report regression: **46 passed**. After adding offline-day
  carry-forward coverage, daily cache suite: **19 passed**. Temporary DB only.
- NOT complete: explicit reviewed baseline resolution + audit, confirmation UI,
  shared peer resolution, new-serial slot replacement and retained slot totals.
  This safeguard must not be presented as a completed replacement workflow.
  Historical finalized rows are unchanged; no automatic historical correction.

### 2026-09-18 continuation — idle footprint and cancellation state

- Handoff now explicitly records ready/cancelled state. An unready or cancelled
  request cannot commit, and late timer events cannot revive a cancelled request.
  Handoff/tray/lifecycle regressions: **23 passed**.
- Added reproducible Windows experiment `tools/measure_idle_runtime.py`; raw
  results: `docs/V5_2_12_IDLE_FOOTPRINT.json`. Six fresh subprocesses (3 per
  mode), each with its own temporary database. Real MainWindow construction,
  offscreen show/refresh/close versus constructed BackgroundAgent + AgentTray.
  Workers not started, Web disabled, no printers configured. Python network and
  child-process launch attempts blocked by audit hook inside each sample.
- Median interpreter working set after 5 seconds idle: desktop **95.85 MiB**,
  Agent + Tray **67.63 MiB**, approximately **29.4% lower**. Observed idle CPU
  sample: desktop 0%, agent 0–0.31% of one core. Short samples/Windows counters;
  do not interpret zero as no CPU use. This excludes Web/Node, interpreter
  launcher overhead, active collection/sync and loaded customer history. It is
  NOT a whole-process-tree or production workload benchmark.
- First harness attempts failed during close because its network audit hook
  raised RuntimeError where network callers handle OSError. Corrected the
  fixture to raise OSError (still denies connection); all six final samples
  then closed cleanly. No confirmed product crash from that harness failure.
- Remaining: complete GUI→Agent→GUI lifecycle with active synthetic reads and
  local Web fixture, OS tray verification and whole-tree resource sampling.
  Source feature still pending full validation; no build or Host/customer edits.

### 2026-09-18 continuation — source desktop-to-agent handoff

- Source desktop close now prepares an independent `--tray --handoff` agent
  while keeping the current window and collectors alive. A private temporary
  rendezvous carries ready/commit/cancel. Only a live, ready child is committed;
  the child cannot start collection until the desktop lock is released after
  old workers drain. Closing UI then exits the large desktop process.
- Failure before readiness keeps the current UI/services. Unsaved draft approval
  is deferred until readiness, and the draft is not discarded before commit.
  Reopening the window or choosing explicit full-stop cancels an uncommitted
  handoff. Duplicate close attempts reuse the pending request.
- Packaged/frozen close behavior and autostart are unchanged pending packaging
  verification; default agent launch is still headless unless `--tray` is passed.
  This is a source implementation, not installer/release validation.
- Real subprocess tests run the actual child main with offscreen tray availability
  substituted and collection start replaced by a marker. They prove no start
  before commit or while the desktop lock remains held, cancellation without
  collection, and child cleanup. No real printer or Host calls are made.
- Handoff/agent/tray/setup/startup suite: **43 passed**. After adding draft and
  reopen regressions, tray lifecycle alone: **13 passed**. Native OS tray display,
  complete real GUI close/reopen, process-tree RAM/CPU and Web continuity still
  need verification. Do not mark the entire Agent feature complete yet.
- Next: measure and verify this source lifecycle in an isolated environment;
  retain the no-build restriction and avoid customer DB/Host traffic. Then move
  into remaining peer/slot/archive work, parking authoritative Host decisions.

### 2026-09-18 continuation — worker cancellation prerequisite

- While tracing UI-to-agent handoff, found two existing shutdown hazards:
  cancelling queued futures invokes completion callbacks immediately, removing
  entries from the dictionary being iterated; queued timer/network/status events
  could submit to a shut-down executor or try to resume a stopped collector.
- Polling pause/stop now iterate a snapshot. Stop serializes with submissions
  using the existing rollover lock, then releases locks before draining workers.
  Scheduled/manual reads and direct submissions no-op after shutdown.
- Registration runtime ignores late timer/retry/network/config/completion events
  after stop; desktop and agent ignore late collection-gate changes on shutdown.
- Lifecycle/polling/registration/tray suite: **49 passed**. Added the matching
  pause cancellation regression and reran lifecycle: **9 passed**. The tests use
  real queued futures with a blocked synthetic worker, no printer/Host calls.
- Desktop-close handoff is still NOT wired. Safe integration needs child tray
  readiness before parent stops, failure recovery that retains the existing UI,
  and ownership transfer only after worker drain. Continue this next; do not
  mark lightweight-agent feature complete from these prerequisite fixes.

### 2026-09-18 continuation — isolated Agent tray

- Added `ui/agent_tray.py` and opt-in source `background_agent.py --tray`.
  This mode uses QApplication for a tray only; default remains QCoreApplication.
  No desktop, report pages or chart imports. Tray offers open and confirmed stop;
  opening leaves agent running until the desktop acquires its lock and requests
  takeover. Failed launches keep collection running and allow retry. Repeated
  clicks are throttled. Child gets the same database path and no Windows console.
- macOS 27 keeps the existing native status-menu workaround via a small
  asynchronously opened dialog. macOS behavior is source-only, not device-tested.
- Tray/lifecycle regression: 21 passed; added fresh-process import boundary test
  and reran tray file: 6 passed. No real OS tray clicks, collection or Host calls.
- Not wired into desktop close or autostart yet. `--tray` fails explicitly when
  the OS tray is unavailable, instead of leaving an agent without visible stop
  controls. Next wire and verify desktop-close handoff with launch-failure
  recovery and in-flight worker drain; keep explicit full-stop separate. Then
  resource measurements. No claimed RAM savings yet; no build or deployment.

### 2026-09-18 continuation — shutdown safety

- System Tray stop now requires explicit confirmation (Cancel is the default),
  preserves the separate unsaved-settings check, and ignores duplicate exit
  actions once shutdown starts. Cancel leaves all workers and Web running.
- Desktop now drains polling/registration workers before releasing its instance
  lock, closing the reverse takeover race as well as the agent-to-desktop race.
- Agent IPC reads split stop commands asynchronously instead of blocking Qt;
  unknown commands return an error and cannot stop the agent. Named-pipe server
  access is restricted to the current OS user.
- Lifecycle/tray/setup/startup source tests: **30 passed**, including split pipe
  delivery, unknown command rejection, stop cancellation, unsaved draft refusal,
  and duplicate stop actions. Tests use isolated databases and local IPC.
- Remaining Agent work is substantial: closing UI still hides the large desktop
  process; no memory reduction is claimed. Next implement an independently owned
  tray/runtime and a verified desktop-close handoff (or disposable UI client),
  preserve setup/settings operations, then measure total process tree CPU/RAM.
  The existing agent has QCoreApplication only and no tray; simply exiting the
  GUI and spawning it would remove the user's tray stop control. Do not ship
  that incomplete shortcut. Do not enable production services for measurements.

### 2026-09-17 overnight implementation

- Web source: 60-second refresh, 20-second request timeout, complete-snapshot
  updates, preserved old data/time on partial or full API failure. Initial
  failure shows an unavailable message instead of zero usage. Date selector
  recovers after initial outage. TypeScript `tsc --noEmit --incremental false`
  passed on a temporary copy with existing dependencies (no release build).
- Isolated local API/browser fixture: auto-refresh changed 175 to 225 pages,
  350 to 450 THB without clicking, exactly one minute apart. Stopping the fixture
  retained 225/450 and the old successful timestamp with a stale warning.
  Reload during outage showed unavailable, no zero summary cards. Restart
  recovered data, date range and removed warnings. Fixture uses synthetic
  readers; not a real printer or two-machine end-to-end test.
- Web API/report snapshot/registration recovery: 36 tests passed.
- Extracted network controls into `source/ui/network_settings.py`; simplified
  three sections, collapsed port, visible disabled open/copy actions. Existing
  save/password/port/cancel bindings preserved. Settings/navigation: 36 tests
  passed after the changes. Rendered actual widget at 1080x1000 in offscreen Qt;
  `Temp/komi-lan-settings-qa/lan-settings.png`. Full application theme/mobile
  review and final peer member UI remain; current share control is setup-only.
- Agent handoff safety: desktop acquires its lock before requesting stop; agent
  publishes ownership while holding desktop exclusion; takeover waits for agent
  lock release, fails closed on timeout. Agent drains running polling/Host
  workers before releasing lock. Lifecycle/polling/runtime/instance suite:
  36 passed; the lifecycle file then passed all 4 tests including two added
  real-worker drain checks.
  This fixes takeover overlap; it does NOT yet implement persistent agent
  ownership with an independent tray and disposable UI.
- Continuation automation `komi-5-2-12` resumes this thread every 30 minutes.
  Preserve it while work remains; pause it when all unblocked work is complete.
- Additional startup/tray/setup regression: 21 passed. Certificate/registration
  foundation: 19 passed, still disabled pending trusted transport choice.
- Saved local commits: `3f48800` web refresh, `4262bd2` network controls,
  `4573d40` agent takeover safety. No push, installer or production changes.

Next: finish Agent ownership/lifecycle design and source tests; keep the real
desktop/customer DB untouched. Then peer/settings/slot work, archive and manuals.
Do not erase this distinction between foundational fixes and completed features.

- Earlier recovery/runtime/setup/TLS run: 108 passing, then added recovery tests
  passed 11 (see conversation); must recheck after changes.
- Web/report source tests: 32 passing. Browser on isolated API fixture confirmed
  manual refresh 120→175 pages, 240→350 THB; initial implementation rendered zero
  after API failure and had no auto-refresh. Actual customer printers not tested.
- Capacity fixture: outputs/capacity-5-years/result.json and simulate.py.
  Synthetic DB in Temp/komi-capacity-04538ad9: 1,826 days, 3 printers, 100 users
  on each daily, 2 raw counters per user, 30 device counters, 1,818,696 rows,
  1,127,170,048 bytes after checkpoint, quick_check ok. Size experiment only;
  repeated daily templates do not prove financial correctness or real workload
  performance. Do not commit the large synthetic database.
