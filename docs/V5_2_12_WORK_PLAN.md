# KOMI Report 5.2.12 — แผนพัฒนาฉบับรวม

## สถานะและขอบเขตคำสั่งล่าสุด

อัปเดต 18 กันยายน 2569 ตามข้อสรุปกับผู้ใช้ใน task นี้

**เริ่มพัฒนาต่อแล้ว** ตามคำสั่งล่าสุด “จัดการโค๊ดตามแผนพัฒนาเลย”
ทำงานโดยตรงใน task นี้ ไม่ต้องตั้งเวลาเพื่อเดินงาน ผู้ใช้ทักเรื่องการตั้งเวลาแล้ว
เครื่องมือแจ้งว่า automation komi-5-2-12 ถูกลบไปแล้ว จึงไม่สร้างกลับหรือเปิดงานซ้ำ
คำสั่งเริ่มนี้ยกเลิกการพักพัฒนาเดิม แต่ไม่ได้อนุญาต build/เผยแพร่หรือแก้ production

เมื่อผู้ใช้สั่งเริ่ม ให้ทำรายการที่ทำต่อได้ตามลำดับ เก็บผลทดสอบและข้อจำกัดจริง
ไม่ถามซ้ำเรื่องที่ตกลงแล้ว และไม่ให้ผู้ใช้ตัดสินรายละเอียดทางเทคนิคแทน AI
ถามเพิ่มเฉพาะกรณีที่ตรวจพบว่าขาดข้อมูล/สิทธิ์จริง หรือกระทบวิธีใช้งานที่ยังไม่เคยตกลง

- ทำบน local main ใน worktree ของ task นี้ ไม่แก้ต้นฉบับ Documents/KOMI Report V5
- ไม่ดึงการแก้ไขที่ยังไม่ commit ใน Documents มาปน โดยเฉพาะนโยบายปลดล็อก registration
- ห้าม build installer/release, push, publish หรือแก้ Host/ข้อมูลลูกค้าจริง
- คู่มือและภาพหน้าจอต้องปรับให้ตรงก่อน build; การอนุมัติ build เป็นขั้นตอนภายหลัง
- คำสั่งล่าสุด: เก็บการติดตั้งและทดสอบสองเครื่อง **เครื่องนี้ (A) + VM 105 บน
  Proxmox (B)** ไปทำหลัง build ไม่เริ่มติดตั้งหรือรัน source บนคู่นี้ตอนนี้
  ไม่ต้องขอ IP/OS/สิทธิ์เข้า VM ในช่วงนี้ งานพัฒนาและทดสอบ source ด้วยข้อมูล
  จำลองยังทำต่อได้ตามเดิม ข้อนี้ไม่ใช่การอนุมัติให้เริ่ม build
- แผนนี้แทนข้อกำหนด/ข้อความ “Next” ที่ขัดกันในหลักฐานเก่าด้านล่าง
  หลักฐานเก่าเก็บไว้เป็นประวัติ ไม่ใช่คำอนุมัติให้เริ่มงานหรือรับรองว่าฟีเจอร์ใหม่เสร็จ

อ้างอิงฐานงาน: worktree C:/Users/User/.codex/worktrees/4897/KOMI Report V5
พัฒนาจาก codex/v5.2.12-registration-recovery บนฐาน
bf453738b934dcf5bea59dd8c70e191b52ba6b89 และ merge เข้า local main ด้วย 7100199
เก็บ main เดิมไว้ที่ backup/main-before-v5.2.12-20260918 ไม่เปลี่ยนต้นฉบับ Documents

## ข้อสรุปผลิตภัณฑ์ที่ยืนยันแล้ว

### คิวทดสอบหลัง build — เครื่องนี้ + Proxmox VM 105

สถานะ **WAIT BUILD** ตามคำสั่งผู้ใช้ เก็บรายการไว้สำหรับหลัง build ที่ได้รับอนุมัติ
และเชื่อมสมาชิก/HTTPS พร้อมแล้ว ไม่รายงานว่าทดสอบผ่านจากผลจำลองใน source

1. ติดตั้งแพ็กเกจรุ่นเดียวกันบน A/B ด้วยข้อมูลทดสอบและตัวตน installation แยกกัน
2. ตรวจ LAN/Firewall, การค้นพบใน Wizard, ค้นหาอีกครั้ง และกรอก IP
3. ตรวจการรับตั้งค่า ราคา และ Slot ชุดเดียวกัน พร้อมสถานะยืนยันรับ
4. อ่านพร้อมกันและอ่านด้วยมือแทรกรอบอัตโนมัติ ต้องได้ผลจากงานที่เริ่มก่อน
5. ปิด UI ให้ Agent ทำต่อ; หยุดผู้อ่านและตรวจอีกเครื่องรับช่วง
6. ปิด B ระหว่างเปลี่ยนค่า/อ่านมิเตอร์ แล้วเปิดกลับให้เติมประวัติโดยไม่เพิ่มยอดซ้ำ
7. ตัดเครือข่าย/เชื่อมกลับ/รีสตาร์ต ตรวจคิวส่งและการกลับมาใช้ผู้อ่านเดียวกัน
8. ตรวจ shortcut, การอัปเกรด และ CPU/RAM รวม process tree ของแพ็กเกจจริง

### 1. สมาชิกและ slot ร่วมกัน

- ไม่จำกัดจำนวนคอม ทุกคอมเป็น peer เท่าเทียม ไม่มี Primary ถาวร
- บริษัทใช้ slot 1–3 ชุดเดียวกัน A ตั้งค่าและทดสอบผ่านว่าแต่ละ slot เป็นเครื่องใด
  B/C/D รับชุดเดียวกัน ไม่สร้างสาม slot ส่วนตัวเพิ่มให้คอมใหม่
- เปลี่ยนเครื่องใน slot จากคอมใด มีผลทั้งระบบ พร้อมประวัติและฐานมิเตอร์เดียวกัน
- ยอดสะสมผูกกับ slot ส่วน Serial/ช่วงที่เครื่องอยู่ใน slot ระบุที่มาของมิเตอร์จริง
- ไม่เพิ่มโมดูลผู้ดูแลใหม่ ใช้ popup แจ้งว่าการตั้งค่ามีผลกับทุกคอม
- การค้นพบใน LAN ไม่ใช่การยืนยันสิทธิ์รับข้อมูล เก็บตัวตน installation ของแต่ละคอมแยกกัน
  การผูกสมาชิกเป็นงานตรวจและพัฒนาของ AI ไม่ตั้งคำถามสมมติว่า D ต้องเพิ่มเครื่องอีกชุด

### 2. ติดตั้งและค้นหาเครื่องใน LAN

- Wizard ประกาศค้นหา Agent ที่ออนไลน์ตอบกลับตรงไปยังผู้ถาม
- Broadcast มีหน้าที่ค้นหา ไม่ส่งการตั้งค่าหรือฐานข้อมูลทั้งก้อน
- หลังตรวจการเชื่อมต่อ/สิทธิ์ ใช้ HTTPS ใน LAN รับการตั้งค่าและติดต่อสมาชิกโดยตรง
- ไม่พบเครื่องตอบกลับ: มีปุ่ม “ค้นหาอีกครั้ง” และกรอก IP/ค้นหาเดิมเป็นทางเลือก
- ไม่สรุปว่าไม่มี KOMI เพียงเพราะไม่มีคำตอบ เพราะ Firewall หรือเครื่องออฟไลน์อาจเป็นเหตุ
- ทดสอบกฎ Firewall ที่จำเป็นแบบจำกัดโปรแกรม/พอร์ต/เครือข่าย ไม่ปิด Firewall ทั้งระบบ

### 3. ผู้อ่านมิเตอร์และการรับช่วง

- ปกติมีคอมรับหน้าที่อ่านหนึ่งเครื่องต่อเครื่องพิมพ์ สมาชิกอื่นรับข้อมูล
- เลือกผู้อ่านอัตโนมัติ เครื่องที่พร้อมก่อนรับหน้าที่ ใช้ลำดับที่กำหนดแน่นอนเมื่อเริ่มพร้อมกัน
  ไม่สลับผู้ที่ยังทำงานได้เพียงเพราะอีกเครื่องกลับมาออนไลน์
- ใช้รอบ/ช่วงอ่านตามหน้าตั้งค่าร่วม ไม่ต้องรักษาความตรงเวลาระดับเรียลไทม์
- ตรวจผู้อ่านเมื่อถึงรอบอ่านหรือมีคำขออ่านด้วยมือ ไม่เพิ่ม heartbeat ตรวจทุก 10 วินาที
  หรือ polling การตั้งค่าทุก 5/30 นาที
- ผู้อ่านติดต่อไม่ได้หลังลองซ้ำช่วงสั้น ๆ: ให้สมาชิกอื่นรับช่วงอย่างมีลำดับ
  ผู้อ่านดับ/ค้างระหว่างงานต้องมี timeout และกู้คำขอที่ยังรอผลได้
- ถ้า LAN แยก อาจอ่านซ้อนชั่วคราวได้ กลับมาเชื่อมกันต้องเหลือผู้อ่านเดียว
  ไม่อ้างว่ารหัสเครื่อง/timeout รับประกันการมีผู้อ่านเดียวขณะเครือข่ายแยก
- มิเตอร์สะสมของ Serial เดิม ตัวนับเดียวกัน และช่วงที่ไม่ถูก reset ใช้ค่าสูงสุดเป็นค่าปัจจุบัน
  ห้ามบวกมิเตอร์จากแต่ละคอม และไม่เลือกตามนาฬิกาคอมหรือเวลารับข้อมูลเพียงอย่างเดียว
- ค่าอ่านต่ำที่ส่งมาช้าไม่ลดค่าสูงสุด การ reset/เปลี่ยนเครื่องจริงแยกตามประวัติและ workflow ตรวจสอบ
  ไม่เอาค่าสูงสุดข้าม Serial/ฐานมิเตอร์ และไม่ใช้กฎนี้กับหมึก กระดาษ หรือค่าที่ไม่สะสม
- ถ้าทุกคอมปิด ไม่มีการอ่านจนมีคอมกลับมา ยอดสะสมตามทันได้ แต่รายละเอียดรายวันอาจขาด

### 4. “อ่านข้อมูลเดี๋ยวนี้”

- ไม่มีใครอ่านอยู่: คอมที่กดและได้สิทธิ์ก่อนอ่านเองชั่วคราว แล้วแชร์ผล
- มีคนกำลังอ่าน: รอรับผลรอบนั้น ไม่เริ่มอ่านซ้ำและไม่คืนค่าเก่าเป็นผลอ่านใหม่
- หลายคอมกดพร้อมกัน/ตรงรอบอัตโนมัติ: จัดลำดับรับสิทธิ์ ใช้ผลจากงานที่เริ่มก่อน
  ไม่ตัดสินด้วยนาฬิกาของแต่ละคอมเพียงอย่างเดียว
- การอ่านด้วยมือเพิ่มจุดประวัติ ไม่เลื่อนหรือแทนตารางรอบถัดไป
  ตัวอย่างรอบ A 10:00/10:15/10:30 และ B อ่าน 10:10:
  ถ้าสำเร็จครบและไม่ทับกัน ต้องมีข้อมูล 10:00/10:10/10:15/10:30
- ถ้างาน 10:10 ยังไม่จบเมื่อถึง 10:15 ให้ใช้ผลงานที่กำลังอ่าน ไม่สร้างการอ่านหรือจุดข้อมูลปลอม
- หลังจบรอบชั่วคราว ผู้อ่านตามตารางเดิมทำต่อ ไม่แย่งหน้าที่ถาวรเพราะกดอ่านครั้งเดียว
- กดอ่านด้วยมือได้นอกช่วงตาราง เมื่อเสร็จยังใช้ตารางเดิม
- แสดงกำลังอ่าน/สำเร็จพร้อมเวลาอ่านจริง/ล้มเหลว ถ้าอ่านไม่ได้คงข้อมูลเก่าและเวลาเดิม

### 5. ข้อมูลที่ส่งระหว่างคอม

- ผู้อ่านใช้ SNMP ตรวจมิเตอร์/สถานะภายใน ไม่ส่งข้อมูล SNMP ทุกครั้งให้สมาชิก
- ผู้อ่านอ่าน Web Connection แล้วตรวจ แปลง และบันทึกผลก่อนส่ง
- ส่งเฉพาะข้อมูลรอบที่บันทึกสำเร็จผ่าน HTTPS ใน LAN ไม่ส่ง HTML หรือไฟล์ Database ทั้งก้อน
  ไม่ต้องผ่าน Host สำหรับการแลกข้อมูลนี้
- ผู้รับบันทึกลงฐานข้อมูลของตัวเองแล้วอัปเดตหน้าจอ
- Web ยังไม่ได้อ่าน/อ่านล้มเหลว: สมาชิกคงข้อมูล Web ชุดเดิมพร้อมเวลาสำเร็จล่าสุด
  สถานะที่มีเฉพาะ SNMP จะไม่ถูกแสดงเหมือนอัปเดตใหม่บนสมาชิกอื่น
- ข้อความขออ่าน/สถานะงาน/ผลสำเร็จหรือผิดพลาดยังแลกได้ แม้ไม่ได้ส่งข้อมูล SNMP
- เก็บรายการรอส่งและการยืนยันรับ ทนการส่งซ้ำ/หลุด/รีสตาร์ต ป้องกันข้อมูลวนระหว่าง peer
  ต้องบันทึกข้อมูลกับงานรอส่งให้สัมพันธ์กัน เพื่อไม่ทำข้อมูลที่อ่านแล้วหล่นหายระหว่างส่ง

### 6. เติมประวัติและช่วงที่ไม่มีการอ่าน

- หลังเปิดเครื่อง เมื่อ Agent/เครือข่ายพร้อม ให้ขอเฉพาะประวัติที่ขาดจากสมาชิกที่ออนไลน์
  หากยังเชื่อมไม่ได้คงงานไว้แล้วทำต่อเมื่อเชื่อมได้ ไม่เริ่มซ้ำเพียงเพราะเปิดหน้าต่าง UI ใหม่
- ถ้าสมาชิกอื่นมีประวัติจริง ให้เติมโดยไม่เพิ่มยอดซ้ำ ถ้าทุกคอมขาดช่วงเดียวกันไม่สร้างข้อมูลอ่านปลอม
- ส่วนต่างมิเตอร์ที่ครอบคลุมช่วงขาด ลงใน “วันก่อนวันที่กลับมาอ่านสำเร็จ”
  ตัวอย่างศุกร์ 17:00 = 1,000, จันทร์ 08:00 = 1,300:
  ลง 300 หน้าในวันอาทิตย์ ยอดสะสมปัจจุบัน 1,300
- เก็บเวลา/ค่าต้น–ปลายจริงและช่วงที่ครอบคลุมไว้เสมอ วันที่ลงยอดเป็นกติกาบันทึก
  ไม่ใช่หลักฐานว่าพิมพ์ทั้งหมดในวันนั้น
- Remark ข้างยอดรายวัน, รายละเอียดรายการ และ Excel/PDF:
  “ยอดสะสมช่วงขาดการอ่าน: ศุกร์ 17:00–จันทร์ 08:00 ลงวันก่อนกลับมาอ่านได้
  ไม่ใช่ยอดที่ยืนยันว่าเกิดเฉพาะวันอาทิตย์”
- หน้าสรุปปัจจุบันแสดงยอดจริง ไม่ขึ้น popup ซ้ำทุกครั้ง
- ช่วงข้ามรอบบิลหรือวันเปลี่ยนราคาให้ทำเครื่องหมายตรวจสอบ ไม่ใช้วันที่ลงย้อนหลัง
  หรือค่าเฉลี่ยกราฟตัดสินอัตราราคาอัตโนมัติโดยไม่มีหลักฐาน
- ได้ประวัติจริงภายหลัง ให้ปรับการแบ่งยอดตามหลักฐานโดยยอดรวมไม่เพิ่มซ้ำ
  รายงานปิด/ออกแล้วใช้ฉบับแก้ไขและประวัติ ไม่เขียนทับฉบับเดิม

### 7. กราฟประมาณการแยกจากยอดบันทึกจริง

- กราฟยอดรายวันเฉลี่ยยอดช่วงที่ขาดเฉพาะวันที่ไม่มีข้อมูล Web เลยทั้งวันของเครื่องพิมพ์นั้น
  ตรวจจากประวัติที่รวมได้ ไม่ใช่แค่คอมหนึ่งปิด และไม่ใช้ SNMP แทนความครบของ Web
- ศุกร์และจันทร์มีข้อมูล เสาร์/อาทิตย์ไม่มี: 300 ÷ 2 = วันละ 150
  หรือ 301 ÷ 2 = วันละ 150.5; ไม่กระจายเศษเป็น 150/151
- กราฟแสดงทศนิยมไม่เกิน 2 ตำแหน่ง คำนวณด้วยค่าก่อนปัด
  ยอดรวมใช้ต้นทาง ไม่บวกค่าที่ปัดบนป้ายกราฟแล้วทำยอดรวมคลาดเคลื่อน
- ใช้สีอ่อน/ลายและคำว่า “เฉลี่ยประมาณการ” เสมอ แม้หารลงตัว ไม่มีทศนิยม
  tooltip/รายละเอียดและภาพส่งออกบอกช่วงเวลาที่เฉลี่ย
- ค่าเฉลี่ยใช้แสดงแทนยอดช่วงเดียวกัน ไม่เพิ่มแท่ง 300 ซ้ำกับ 150+150
  รายงาน/ยอดลงย้อนหลังยังใช้กติกาข้อ 6 ค่าเฉลี่ยไม่เปลี่ยนราคา/ยอดคิดเงินจริง
- ไม่มีวันที่ว่างเต็มวัน: ไม่ใช้การหารนี้ แสดงรายการช่วงเวลาพร้อม remark
- เมื่อมีประวัติจริงเพิ่ม ใช้แทนส่วนประมาณ แล้วคำนวณส่วนคงเหลือใหม่
  หากหลักฐานขัดแย้งหรือยอดคงเหลือติดลบ ต้องแจ้งตรวจสอบ ไม่สร้างค่าประมาณติดลบ
- กราฟมิเตอร์สะสมใช้จุดอ่านจริง ช่วงที่ขาดเชื่อมเส้นประ ไม่สร้างจุดอ่านปลอมรายวัน

### 8. การตั้งค่าร่วมและการเปลี่ยนเครื่องใน slot

- Sync การตั้งค่าเมื่อมีผู้ยืนยันบันทึกค่าใหม่ ไม่ตั้งรอบทุก 5/30 นาที
- Popup แสดงค่าเดิม/ใหม่และแจ้งผลต่อทุกคอม รวมเครื่องที่ออฟไลน์จะรับภายหลัง
- มีประวัติผู้เปลี่ยน/คอม/เวลา/ค่าเดิม–ใหม่ ย้อนค่าโดยสร้างรายการใหม่
  ถ้าแก้ไขขัดแย้งแสดงให้เลือก ไม่ทับเงียบหรือเลือกจากนาฬิกาอย่างเดียว
- ทุกคอมเห็น slot ชุดเดียวกัน เปลี่ยนเครื่องจากคอมใดก็ส่งการเปลี่ยนเดียวกันให้สมาชิก
- ผู้ใช้เลือก slot เดิม → เชื่อมต่อและทดสอบเครื่องใหม่ → ยืนยันเปลี่ยน
  โปรแกรมอ่าน Serial/มิเตอร์ใหม่เป็นฐาน เก็บประวัติเก่าและยอดสะสม slot
- ตัวอย่างยอด slot 2,000 เปลี่ยนเครื่องมิเตอร์ 50,000 แล้วเพิ่มเป็น 50,100:
  ยอด slot = 2,100 ทุกคอมใช้ฐานเดียวกัน รวมผู้ใช้/บัญชีที่เกี่ยวข้อง
- เครื่องเก่าถอดไปแล้วใช้ยอดล่าสุดที่มี พร้อม remark ว่าไม่ได้ยืนยันมิเตอร์สุดท้าย
  ไม่บังคับผู้ใช้กรอกยอดเองหรือเดายอดหลังการอ่านครั้งสุดท้าย
- การลดลงจริงของมิเตอร์ Serial เดิมใช้การตรวจสอบและยืนยันฐาน ส่งผลให้ทุกคอม

### 9. หน้าตั้งค่า Web และ Agent

- ใช้ชื่อ “การตั้งค่าเครือข่าย” รูปแบบเดียวกับส่วนอื่น ลดกรอบซ้อนและยุบพอร์ตขั้นสูง
- มีสมาชิก สถานะเชื่อมต่อ ผู้อ่าน/งานที่กำลังอ่าน เวลาข้อมูลสำเร็จ และสถานะส่ง/รอรับ/ขัดแย้ง
- Web refresh ทุก 60 วินาทีและปุ่ม refresh; คงข้อมูล/เวลาสำเร็จเดิมเมื่อขาดการเชื่อมต่อ
  initial failure ไม่แสดงศูนย์เหมือนข้อมูลจริง
- Shortcut เปิด Web ของคอมตัวเองพร้อมโลโก้ มีปุ่มสร้างใหม่
  เตรียมติดตั้ง shortcut ในขั้น installer ภายหลัง ไม่มี redirect ไปเครื่องหลัก
- รายงาน Web ไม่บังคับรหัสผ่านโดยค่าเริ่มต้น เลือกตั้งได้และรักษาการล็อกเดิม
- ปิด UI แล้วให้ Agent เบาทำงานต่อ เปิด UI กลับไม่สร้าง collector/Web/งานส่งซ้ำ
  ปิดจริงผ่านไอคอน tray พร้อมยืนยัน
- วัด CPU/RAM รวม process tree ทั้งว่าง อ่าน/ส่งข้อมูล และเปิด Web ไม่อ้างเฉพาะ process เล็กที่สุด

### 10. ราคา Archive ลงทะเบียน และการส่งมอบ

- ราคาใส่วันบังคับใช้ได้ แชร์ประวัติ แสดง preview ย้อนคำนวณพร้อมผลต่างก่อนยืนยัน
  รายงานปิด/ออกแล้วเก็บเดิม สร้างฉบับแก้ไข
- เก็บรายละเอียดล่าสุด 12 เดือน สรุปเก่าเป็นรายเดือนต่อเครื่อง/ผู้ใช้
  archive ต้นฉบับรายปี เรียกรายละเอียดเมื่อผู้ใช้ขอหรือยืนยันคำนวณย้อนหลัง
  ไม่โหลดข้อมูลเก่าทั้งหมดทุกครั้งที่เปิด
- ตรวจยอด/ความครบ/อ่านคืนได้ก่อนลดรายละเอียดฐานหลัก และมีสำเนาระหว่างสมาชิก
- จำลองข้อมูล 5 ปี/100 ผู้ใช้ วัดขนาดฐาน/ดัชนี/archive เวลาเปิดและโหลดรายงานจริง
- **แนวทางลงทะเบียน/ใบรับรองตกลงแล้ว**: ตรวจ TLS ปกติก่อน
  ถ้าไม่ผ่านจึงมี Hotfix แบบเลือกใช้สำหรับลงทะเบียนครั้งแรกเท่านั้น
  เก็บ retry ที่ผูกตัวตนเดิม เมื่อได้รับคำตอบยืนยันสำเร็จแล้วปิดช่องทางพิเศษถาวร
  Status/Meter ใช้ TLS ปกติและคิว retry ไม่ปิดตรวจ TLS ทั้งระบบ ไม่ปลดล็อกฟรี/ชั่วคราว
- วิธีเชื่อถือ Host ต้องตรวจพิสูจน์ในงานพัฒนา ไม่ใช้ใบรับรองที่เพิ่งเห็นเป็น pin ที่เชื่อถือทันที
  ข้อนี้เป็นงานเทคนิค/ทดสอบ ไม่เปิดคำถามนโยบายเดิมให้ผู้ใช้ตัดสินซ้ำ
- Refactor เฉพาะส่วนที่เกี่ยวข้อง ตรวจ dead code/การอ้างอิงก่อนลบ
  หลักฐานทดสอบเก่าตรวจว่ามีบน GitHub/commit/tag/release จริงก่อนเก็บกวาด
- ปรับคู่มือ ภาพหน้าจอ และขั้นตอนทดสอบสองเครื่องให้ตรง ก่อนขออนุญาต build

### 2026-09-18 — demand-driven reader election and polling integration

- Added `ReaderElection`: verify full company/Slot/Serial/settings/epoch scope,
  keep a reachable incumbent, use stable member ordering for simultaneous starts
  and split authorities, and select on demand without another heartbeat timer.
  A failed probe has one immediate retry; selection has a time budget and can
  be cancelled. Reboot clears the old incumbent claim. Revocation, malformed
  replies and scope changes fail closed instead of becoming an offline vote.
- `ReaderAuthority` fences `ReaderJobs` after losing ownership;
  `SharedReaderCoordinator` routes manual requests to the same durable authority.
  An ambiguous request reply is retried with the same request ID against the
  same authority, never silently rerouted into a second job.
- `SharedWebRead` now connects to the existing Desktop/Agent polling worker
  through an explicitly injected authenticated provider. Scheduled non-readers
  skip printer access. A manual request joins before probing: a joined member
  skips both SNMP and Web, waits for the committed job, verifies origin/read ID/
  scope/time, imports parsed evidence, then updates normal local presentations.
  Its actual Web time is retained; no new local event is fabricated for a relay.
- The elected reader stores Web evidence and outgoing work before publication;
  the authority must commit it before completing the job. Receipt validation,
  revoked membership, corrupt results, storage failure, wait expiry and
  cancellation preserve the previous success. A retry after lost publication
  acknowledgement reuses the recorded event rather than reading again.
- **70 passed in 39.77s** across reader election/jobs/shared Web, existing manual
  scheduling/polling, Agent lifecycle/handoff and peer-history runtime. Fixtures
  use three independent temporary databases and in-process authenticated
  adapters. Tests include first-ready stickiness, power loss/restart, partition
  healing, concurrent requests, and actual 10:00/10:10/10:15/10:30 observations.
  This supersedes older notes saying no election/polling integration exists.
- Final transaction review adds an authority/scope/active-epoch recheck before
  commit; losing authority during a grant rolls back both the job and request.
  The same regression plus this race test: **71 passed in 41.77s**.
- Remaining boundaries: production has no verified member/HTTPS provider yet,
  so it does not activate this optional coordination path. Partitioned members
  may both collect until connected; an already-running SNMP-only scheduled
  probe can overlap a new manual grant before reaching the Web grant boundary.
  Expired/failed jobs are shown as failure and recovered by a subsequent request,
  not an unbounded background retry. Global reader status UI, live network QA,
  historical billing amendments and archived/report reconciliation remain open.
  No installer/release build, deployment or customer-data operation occurred.

### 2026-09-18 — atomic complete peer setup and Slot adoption

- Added `PeerSetupApplication` for an already imported and independently
  authorized settings revision. Its preview uses the existing shared-settings
  confirmation table. Printer metadata, dated prices, settings, reviewed Slot
  heads, causal settings head/event and an idempotent receipt commit together.
  `SlotEpochExchange.adopt_in_transaction` reuses the existing ancestry/conflict
  checks under that same database transaction.
- Fast-forward reuses the remote revision. Concurrent edits require an explicit
  choice and create a two-parent merge; an older incoming revision cannot revert
  a newer history. Missing epochs, printer/baseline disagreement, discarded
  existing baselines, stale settings, storage failure, revoked scope or a
  switched database all reject/roll back the complete operation.
- Local installation ID, registration mode and vault are not copied. Same
  printer/address/TLS retains its local credential reference and runtime status;
  a changed target detaches the old reference and old success/total. An old
  receipt retry never undoes subsequent settings edits.
- Tests include three Slots all-or-nothing, 2,000 + (50,100 − 50,000) = 2,100,
  failed journal/head/receipt writes, revocation during apply, concurrent merge,
  local credentials/identity, missing dependency, database switching and popup
  cancellation. Expanded setup/Slot/catch-up regression: **80 passed in 33.82s**.
  After database guards: **25 passed in 17.64s**; final preview/cancel suite:
  **13 passed in 10.43s**. These sets overlap.
- This closes the atomic repository application gap. It is not yet invoked by
  a production incoming-member workflow: a real verified Host member provider
  and HTTPS delivery still must bind a received revision to its sender/scope.
  No authorizer based on broadcast, company spelling or a local node UUID was
  introduced. Legacy caches/financial holds and Web-driven invoice amendments
  are not changed or certified by this setup transaction.

### 2026-09-18 — additional source regression and obsolete check cleanup

- Ran the other **79 source test files** independently with the network audit
  guard: **560 passed**, one failed source-text assertion (394.87 seconds).
  It incorrectly required `_subject_name_is_placeholder` to be defined inside
  `meter.py` after extraction into `subject_identity.py`. Removed that duplicate
  location check, retaining actual MeterReader placeholder/name enrichment
  behavior tests. Targeted follow-up: **7 passed in 0.83 seconds**.
- Original outputs and the follow-up are both retained in
  `docs/qa/v5.2.12/additional-source-regression.json`; the original failure has
  not been overwritten. No unresolved failure remains from these checks.
  Six build/release-related files were excluded; no release build ran.
- This complements the earlier 72-file checkpoint and the three newly added
  session/runtime/status test files. It is evidence across source checkpoints,
  not a claim of one full-suite run at the final commit or multi-PC acceptance.

### 2026-09-18 — network activity panel with durable receipt status

- Network settings now binds to the actual polling/peer-history runtime when
  the Settings page opens. It shows local active Slots, per-member catch-up
  status and last completed catch-up, outgoing Web receipt counts, pending
  current settings, and unresolved settings/active Slot reviews. It does not
  label catch-up completion as a new printer reading or settings delivery.
- The view refreshes on local runtime/settings events or explicit status check,
  not a network polling timer. Database reads run off the GUI thread, have a
  query time budget, never open Archive payloads, and preserve displayed data
  on failure. Members paginate by 100 without limiting company computers.
  No confirmed sessions means an explicit empty state, not a claim of no LAN PCs.
- Network/settings/navigation/polling/manual tests: **58 passed in 53.27s**.
  Follow-up status/runtime/navigation/manual/Agent/archive checks after query
  and style changes: **42 passed in 30.69s**. Sets overlap. Inspected native Qt
  screenshots with synthetic members/queues and refreshed the Slot baseline
  screenshot to show the current localized timestamp. Updated the source guide.
- Status query regression after enforcing SQLite read-only open: **6 passed in
  2.86s**, including missing DB creating no file and failure retaining prior data.
- Global elected-reader status still requires the actual election integration;
  the panel labels its current job list as this PC's jobs. Verified live member
  discovery/delivery is still unavailable rather than simulated in production.

### 2026-09-18 — Agent/Desktop catch-up lifetime and source regression

- The completed checkpoint regression covered **72 operational test files,
  685 passed, zero failed files**, each in a fresh pytest process (518.60 seconds
  total wall time). `docs/qa/v5.2.12/source-regression.json` records individual
  outputs. This checkpoint precedes the runtime integration below; it is not
  full-suite, real-machine, installer or Host acceptance. The reusable runner
  now lives in `tools/run_source_regression.py` and includes the two new files.
- `BackgroundPollingCoordinator`, used by Desktop and Agent, now owns
  `PeerHistoryRuntime`: startup, explicit network recovery, bounded fair session
  quanta, cancellation and worker drain before releasing handoff ownership.
  Idle/no-members state allocates no executor and sends no traffic. Archive
  maintenance defers while catch-up is working. Desktop's existing OS monitor
  wakes it; the headless Agent now has the same recovery transition monitor.
- No periodic membership/settings polling was added. A failed transfer remains
  pending until an explicit recovery/readiness event. Reconnect during a transfer
  is retained; replacing or removing a session cancels its remaining work.
  Zero-progress budget exhaustion stops rather than spinning. Transport timeout
  bounds remain the transport adapter's responsibility.
- Runtime/session/Agent/polling/archive tests: **35 passed in 15.89 seconds**.
  Expanded runtime/session/tray/setup/startup/manual/handoff tests, including
  recovery during a transfer: **53 passed in 23.73 seconds** (overlapping sets).
- Production has no verified session provider yet and therefore attaches no
  sessions. Actual member verification/HTTPS delivery, remote setup adoption,
  shared reader election and financial projection remain open. This is a wired
  lifecycle with isolated database simulations, not a claim that live LAN Sync
  works. No installer/release build, publication or production change occurred.

### 2026-09-18 — bounded authenticated-transport catch-up session

- Added `PeerHistorySession` to orchestrate the repositories: validate a received
  page, fetch/validate missing epoch ancestry parent-first, persist it, then
  atomically receive the Web page and resume cursor. Import never chooses the
  active Slot head or changes printer settings/invoices.
- Session authorization is checked before and after transport calls, so a
  revocation while receiving a page prevents its commit. Required injected
  callbacks independently authorize session, events and epoch definitions;
  there is no permissive/default production membership provider.
- Work is bounded by pages/bytes/epochs and can cancel between calls/commits.
  Page-budget exhaustion resumes after restart; transport failure retains only
  durably received progress. Dependency imports can survive an interrupted page
  and are safely reused. Excessively deep/large ancestry fails explicitly and
  requires a larger bounded transfer or a future paged ancestry protocol.
- Six source scenarios passed: A→B→C history recovery including replacement
  ancestry and 2,100 Slot total; pinned snapshot/restart; revocation; cancellation
  and transport loss; wrong-epoch response; database rollback/idempotent retry.
- The transport interface still needs the real authenticated HTTPS adapter and
  Agent startup/reconnect wake integration. These tests use local adapters over
  three independent DBs, not live Host credentials or physical computers.

### 2026-09-18 — slot baseline UI and atomic shared-settings reference

- Added a real counter-review dialog for initial/replacement/reset Web baselines.
  It shows old/new Serial, physical baseline and carried Slot totals; requires
  a reason and explicit verification. Preview/confirmation run off the GUI
  thread; new evidence or changed settings rejects a stale review.
- `SharedSlotReviewService` commits epoch/head/maxima/outbox, shared-settings
  revision/event and receipt in one transaction. Failure injection at journal,
  event or receipt leaves all unchanged. Same confirmation is idempotent.
- Shared settings document v3 carries bounded Slot-to-epoch references. Existing
  v2 documents remain readable. Wizard and ordinary price/billing edits preserve
  these references. History displays the baseline change; generic peer/undo
  paths cannot silently apply a different epoch. Host registration schema and
  SQLite schema are unchanged (this is the settings document version only).
- Slot/settings/setup/store/exchange/counter/history UI regression: **74 passed**.
  Expanded shared prices/history/pages/outbox/settings/Wizard/reader/manual read
  regression: **159 passed in 115.36 seconds**, one dependency deprecation warning.
  Updated the guide and inspected the actual synthetic replacement dialog image.
- This adds the local reviewed workflow and its shared causal reference. Remote
  full-setup/epoch adoption, authenticated delivery and legacy financial hold
  reconciliation remain distinct open work; no claim of multi-PC completion.

### 2026-09-18 — reviewed historical discounts and billing periods

- Completed the previously unstarted local recalculation option: the date-range
  dialog can explicitly apply the current discount and/or billing cutoff.
  Defaults preserve both. Previews display old/new rates, amounts and periods;
  stale settings or evidence invalidate confirmation. Manual/held entries stay
  excluded; original ledger evidence remains immutable.
- Billing-period corrections rebuild affected archived subject monthly summaries
  in the same transaction as ledger reversal/replacement and the durable receipt.
  Missing/corrupt files or summary writes abort the whole change. Prior period
  corrections survive later rebucketing; original archive files remain unchanged.
  Detail work is bounded to 32 archives/64 MiB and requires an explicit request.
- Monthly subject history reads live ledger periods and archived summaries from
  one DB snapshot, avoiding a mixture across an amendment commit. Monthly reads
  after amendment still use hot summaries without opening cold files.
- Confirmation runs off the GUI thread; dismissal waits for the commit result.
  Failed confirmation clears the preview. Updated the source manual and rendered
  the actual dialog with both options; inspected the new screenshot.
- Repricing/period amendment/archive/subject/ledger/audit UI regression:
  **63 passed in 37.54 seconds**. This completes these local correction paths;
  cross-member invoice amendments and broader Sync integration remain pending.
  No build, publication, printer access or Host/customer writes.

### 2026-09-18 — checkpoint verified after reported power outage

- HEAD remains `b00303c`; no uncommitted source edits were found. The only
  pending working-tree changes were this plan and the new Host source intake
  document. The Host review was saved, but those documents were not committed.
- Reran slot epoch store/exchange, Web evidence report and Web catch-up tests
  against the current source with offscreen Qt: **38 passed in 27.08 seconds**.
  This checks the latest affected modules, not the full suite, actual customer
  databases, or physical multi-PC operation.
- The proposed optional use of the current discount in historical repricing
  has not been implemented: current repricing still preserves the original
  discount and billing period. Resume with that explicitly reviewed option;
  do not describe it as a half-written or completed feature.
- Host backend review, authenticated peer transport/runtime integration and
  shared slot review UI remain open as documented below. No release build.

### 2026-09-18 — supplied Host License frontend reviewed

- Reviewed both supplied `screens-license.jsx` and minified `screens-license.js`
  as source only. Recorded hashes, actual API actions, evidence limits and the
  exact backend files needed in [Host source intake](V5_2_12_HOST_SOURCE_INTAKE.md).
- These files establish the dashboard/offline-license integration surface.
  `company_key` is used to scope alert rules; the server's company/installation
  binding and three-slot enforcement are not included, so it cannot yet serve
  as verified peer authorization. This is a missing implementation dependency,
  not a request for another Host login or a claim that the backend lacks it.
- Identified that offline issuance bypasses the staging URL helper, and that
  opening the KOMI tab triggers an alert POST which may send email. No browser
  navigation, API call, license issuance or production edit was performed.
- Next source needed: `register-api.php` and its includes; `/api.php`'s relevant
  KOMI handlers; their company/installation/key/slot schema and membership code.
  Keep real peer transport disabled pending that review. No build or publish.

### 2026-09-18 — restartable history catch-up repository

- Schema 28 persists per-member Web catch-up progress. A page's evidence and
  cursor commit atomically; a failed row/cursor write or authorization failure
  leaves the entire page pending. Repeated pages return the same receipt after
  durable storage; sequence-order and snapshot checks reject stale pages.
- Startup handshake pins a bounded high-water mark and resumes incomplete work.
  Later observations wait for the next explicit wake rather than extending a
  running snapshot forever. Source reset rotates its stream identity; a saved
  event anchor detects backup rollback even when the stream ID is unchanged.
  Receiver reset clears resume cursors. Replay deduplicates and never deletes
  evidence that another peer still holds.
- Source archive files are read only on the requested page, without holding a
  SQLite write lock during payload decoding. Missing/corrupt archives cannot
  advance a receiver. A missing v2 epoch blocks the entire page until its reviewed
  ancestry arrives. Imports never become outgoing echo entries.
- Three separate synthetic DBs exercise recovery from a peer's imported data,
  restart, repeat delivery, pinned snapshots, reset/backup rollback, unauthorized
  events, failed storage and missing reviewed ancestry. Catch-up/Web/epoch/
  recovery/reset/migrations regression: **50 passed**.
- This is a callable repository with required verified authorization, not an
  enabled network worker. Verified Host company provider, HTTPS endpoints and
  Agent startup/reconnect orchestration are still required. Legacy v1 events
  remain unbound unless explicitly part of imported reviewed ancestry; do not
  infer their epoch from dates. No periodic settings poll was added.

### 2026-09-18 — source UI shutdown and evidence housekeeping

- Desktop shutdown now stops pending refresh/startup timers and report loading,
  ignores late collection UI signals, and checks shutdown again before a queued
  page refresh runs. Tray/agent lifecycle regression: **29 passed**.
- Active footprint pilot exposed a Windows Qt offscreen access violation during
  interpreter teardown. UI guards alone did not resolve that harness failure.
  Disposing the benchmark-owned window through Qt's live event loop before quit
  resolved the pilot; both child processes exited cleanly with all 30 expected
  Web observations/outbox rows. Repeated measurements follow separately.
- Verified GitHub tag v5.2.10 read-only against local SHA and exact original blobs.
  Moved the August readiness review and September 4 printer UAT unchanged to
  docs/archive/pre-v5.2.12. EVIDENCE_INDEX.md separates current evidence from old
  results and records verification. Existing delivery-guide inputs stay in place
  until the new manual is finalized; no unverified historical evidence deleted.
- Active source benchmark completed three fresh Desktop and three Agent runs,
  each 3 synthetic printers x 100 users x 2 user counters x 10 rounds. All 180
  expected Web observations and outgoing rows were persisted; all six child
  processes shut down cleanly. Median peak working set: Desktop **114.43 MiB**,
  Agent **76.18 MiB** (**33.42% lower**); private bytes 73.45 vs 46.02 MiB.
  Median CPU time per three-printer round: 1.14 vs 0.92 seconds. Accelerated
  one-second requests used 72.74% vs 65.43% of one CPU core; these are NOT normal
  idle or 15-minute schedule CPU percentages. Child launches were prohibited,
  so each measured process tree had one process. Real printer transport, Host,
  Web/Node service, packaged tray and long-term leaks remain unmeasured.
  Raw samples/limits: docs/V5_2_12_ACTIVE_FOOTPRINT.json (source 4fb0812/schema 27).

### 2026-09-18 — epoch-aware evidence reports

- Web evidence inspection now groups explicitly assigned observations by reviewed
  epoch, including the reviewed reset boundary in both relevant histories.
  Legacy unbound events remain a separate group. The dialog selects the current
  reviewed epoch when present and offers previous epochs independently.
- Projection rejects cross-epoch v2 events. Reset-boundary exceptions require
  the exact validated review definition; no timestamp or Serial-only shortcut.
  Excel/PDF identifies the selected epoch. Inspection still does not post usage
  to billing or release legacy counter holds.
- Evidence/projection/billing-period regression **22 passed**, including a
  same-Serial 2,000 -> reset 50 -> 80 fixture producing 30 in the new epoch,
  explicit old-epoch selection and disabled export while recalculating.
- Regenerated and visually checked both Web evidence manual screenshots with
  the actual offscreen Qt widgets. Updated the source manual selection steps.
- Later conflict regression: receiving a competing epoch now flags both branches
  and descendants, including an already-active local head. It never switches
  head by arrival order; new local replacement/reset previews stay held.
  Evidence inspection shows stored conflict/late-parent flags even with only one
  reading and no intervals; exports retain the same flags. Store/exchange/report
  26 passed, then final evidence UI tests 8 passed. Manual conflict resolution
  and its authenticated shared-setting workflow remain to be implemented.

### 2026-09-18 — durable slot epochs and reviewed peer ancestry

- Schema 27 stores immutable slot epochs, an active head, explicit observation
  assignments, bounded per-counter maxima, review issues and a local decision
  outbox. Confirmation rechecks printer identity, latest candidate and parent
  evidence in one transaction. A stale preview cannot change the baseline.
- Parsed Web v2 declares the epoch in its content hash. Local polling pins the
  head before Web collection; journal/outbox/maximum commit together and reject
  an epoch changed during the read. Legacy/uninitialized observations remain v1;
  no epoch is guessed from time or a falling counter.
- Replacement survives restart/archive: 2,000 + (50,100 - 50,000) = 2,100.
  Partial resets preserve increases in unaffected counters. Late higher parent
  evidence holds descendants for review without rewriting frozen carried totals.
  Initializing a slot with another/unknown historical printer is blocked pending
  migration review, rather than treating a used printer's absolute as new usage.
- SlotEpochExchange requires an explicit authorization callback. Bounded import
  checks exact parent proof/carry and commits evidence/definition atomically.
  Import never changes settings or active heads. Explicit compare-and-swap
  adoption checks ancestry, branches, identity and locally newer parent evidence.
  Imported decisions/events do not enter outgoing echo queues.
- Three isolated databases simulate ordered ancestry, restart-safe maxima,
  duplicate delivery, reset boundaries, forged carry, missing parent, failed
  commit, divergent branches and higher receiver evidence. This is source-level
  simulation, not authenticated HTTPS or installation on three physical PCs.
- Validation: epoch/Web/archive/polling/manual/reset/recovery regression 66
  passed; expanded run 77 passed and 2 new fixture/diagnostic-order failures.
  Both corrected; final store/exchange tests 19 passed. Counts overlap and are
  not a claim that the entire application's test suite passed.
- Remaining: verified Host membership adapter and transport; startup catch-up;
  epoch review UI integrated with shared settings and legacy cache/billing holds;
  explicit historical migration/amendment. Do not enable peer suppression or
  claim the full shared replacement workflow complete from these primitives.
- Reader grants now require the active persisted epoch, not only the caller's
  scope string. Completion requires a committed Web observation assigned to the
  same epoch; an unbound result or reset racing a stale scope provider cannot
  complete the job. Three-database reader simulation now uses real replicated
  epochs. Reader/store/exchange regression: **30 passed**. Portable backup of
  archived epoch maxima was separately verified with the 2,100-page result.

### 2026-09-18 — reviewed slot continuity reducer and billing-day consistency

- `slot_meter_continuity.py` computes a virtual slot meter separately from the
  physical printer meter, using explicitly assigned reviewed epochs. The stored
  carry is exact (integer/rational amounts), derives from parent evidence, and
  never adds a used printer's initial absolute meter to slot usage.
- Examples verified across days and reordered/duplicate peer inputs:
  **2,000 + (50,100 - 50,000) = 2,100**; a third printer at 9,000 then 9,050
  continues to 2,150. Same-serial reset is a separate explicit decision; a raw
  decrease by itself does not reset a baseline or add the next absolute value.
- Definitions preserve parent evidence and stable user/counter IDs. Missing old
  counters retain their previous total with a review flag; counters without a
  reviewed baseline and changed normalization mappings cannot silently carry.
  Late old-printer evidence does not rewrite a confirmed carry: verification
  demands an amendment. The maximum keeps its own observation timestamp.
- Continuity/projection/local-replacement source regression: **29 passed (9.19s)**.
  This is the deterministic review/reducer layer only. Durable epoch storage,
  journal binding, atomic settings/slot confirmation, shared delivery and UI
  are still to be connected; no new production replacement path is enabled yet.
- Found and fixed a legacy billing-day mismatch while connecting these views:
  regular reports defaulted missing/invalid configuration to day 25, while
  setup export and Web evidence used day 31. A common parser preserves legacy
  report semantics; new setup still explicitly saves its selected default 31.
  Report archive, setup export, standard reports and Web gap boundary flags now
  use the same effective value. Combined setup/shared-price/archive/Web evidence
  source regression: **84 passed (36.20s)**, including missing/empty/invalid and
  explicitly configured day 31. Existing immutable billing periods stay frozen.

### 2026-09-18 — durable reader grants and joined-request simulation

- Schema 26 and `ReaderJobs` provide first-accepted-request ordering at one
  already authorized coordinator. A manual requester owns the temporary job;
  overlapping manual/scheduled requests join the same job and never create an
  extra Web point. Retrying a lost grant response returns the original job.
- Bounded leases use the coordinator's monotonic clock, never client wall clocks.
  Authority restart fences the old instance and expires old in-flight grants;
  old/late readers cannot complete a replacement job. Explicit Web failure frees
  the next request without fabricating a successful reading.
- A result becomes complete only if its parsed Web observation is already in the
  coordinator journal with the matching job, reader origin, slot and serial.
  Failed request persistence rolls back its new grant; resets respect all FKs.
- Injected verified member/current-scope providers must agree on company, shared
  settings revision, physical serial and reviewed counter epoch. There is no
  default broadcast/name-based authorization and no production endpoint enabled.
- Three independent A/B/C SQLite databases simulate B receiving the first manual
  grant, C joining, B recording Web, A importing durably before completion, then
  C receiving the same event twice and reopening without duplicate history.
  This is data/service simulation with explicit fixture trust, not real HTTPS,
  Host membership, authority election, UI wiring or physical multi-PC proof.
- Reader/Web/backup source regression: **33 passed (13.46s)** before the final
  old-authority fence regression; final reader/migration/reset run:
  **17 passed (9.00s)**, including fencing a surviving obsolete coordinator.
- Next P2 work still includes verified membership transport, authority selection,
  durable event workers/startup catch-up and complete runtime integration. Do not
  suppress local collection on other PCs until those paths are working together.

### 2026-09-18 — verified daily detail archives and hot monthly summaries

- Schema 25 stores immutable compressed yearly chunks for old daily subject/raw
  evidence. Before pruning, every row is decoded/compared, the file is hashed and
  published, then source rows are rechecked in the same transaction as catalog,
  billing-period summaries and pruning. Failure leaves original evidence intact.
- First raw counter baselines, latest subject/raw anchors and unresolved review
  evidence remain hot. Collection needs no archive IO. Existing daily device
  evidence and financial ledger are not pruned; dated-price correction still
  uses the original evidence.
- Monthly subject reports read hot summaries plus recent daily rows. Explicit
  custom ranges and Raw detail requests restore only matching date chunks.
  Summary grouping preserves each day's frozen ledger period, and legacy rows
  use the same billing-day fallback as current reports. Missing/corrupt detail
  files raise errors when requested, never successful empty reports.
- Hot day guards reject silent re-creation/updates of archived history. A future
  evidence amendment workflow must explicitly account for both archived and
  current rows; this does not claim cross-peer backfill/amendments are complete.
- Idle runtime alternates Web and daily chunks, retaining bounded worker drain.
  Advanced settings and the source manual/screenshots now describe both archives.
  Backup/restore copies and verifies both referenced archive families before DB
  publication; resets clear catalogs/rollups but retain immutable disk copies.
- Combined archive/report/source/UI regression: **57 passed (36.33s)**; expanded
  corruption/stale-source/frozen-period/snapshot/exports/layout/batch-repricing
  regression: **58 passed (65.87s)**. Runtime/Agent/manual collection lifecycle:
  **46 passed (22.58s)**. Counts overlap; not a whole-suite claim.
- Completed archival benchmark on a new COPY of the synthetic five-year,
  100-user/three-printer fixture: **876,300 rows**, **224 files**, **430.024s**.
  Independent row compression initially used 422,047,744 bytes; bounded blocks
  now share repeated fields and use **25,554,944 bytes (24.37 MiB)**. Per-block
  decoding remains size-bounded with a digest and exact pre-prune comparison.
- Final checksum/report tests after block compression: **18 passed (18.87s)**.
  Benchmark verified **6,573,600 pages**, exact old canonical/custom/raw results,
  and SQLite quick_check. Old month **50.48ms**, custom week **230.37ms**, raw
  week **318.47ms**, all subject months **9,245.03ms** (single warm runs, with
  other source work on the machine; not real-printer/cold-start measurements).
- Main DB file **479,129,600 bytes**, including **351,895,552 reusable bytes**;
  no automatic VACUUM. Active DB pages plus archives are about **145.71 MiB**,
  but actual file occupancy stays about **481.30 MiB** until explicit compaction.
  Original fixture file was 435,490,816 bytes. Evidence: `docs/qa/v5.2.12/five-year-archive.json`.
- No customer DB, Host writes, installer/release build or publication.

## สถานะสิ่งที่มีอยู่จริง

| ส่วน | สถานะ source ล่าสุด (ไม่ใช่การอนุมัติ release) |
|---|---|
| แผนเดิมและ merge เข้า local main | ทำแล้ว; รอบนี้ปรับแผนตามข้อสรุปใหม่ |
| Web refresh/ข้อมูลค้าง/initial failure | มีโค้ดและ source tests แล้ว ต้อง regression กับระบบใหม่ |
| หน้าตั้งค่าเครือข่าย | มีหน้าสถานะ runtime/คิวรอ ACK/ข้อขัดแย้งแล้ว; สมาชิกจริงและผู้อ่านร่วมยังรอ adapter/election |
| Wizard ค้นหาซ้ำ | มี UDP discovery และ HTTPS probe พร้อมค้นซ้ำ/manual IP; ผ่าน fixture/loopback ยังรอ Firewall/สองคอมจริง |
| ประวัติการตั้งค่า | Setup/ราคา save พร้อม revision แบบ atomic; มีหน้าประวัติ/เลือกค่าขัดแย้ง/undo ราคา รอบบิล ส่วนลด ตาราง; การส่งอัตโนมัติและ apply การเปลี่ยนเครื่องร่วมยังไม่ครบ |
| Agent/handoff/tray | มี source lifecycle/tests และวัดงานจำลอง 3 เครื่อง 100 ผู้ใช้แล้ว ยังต้องรวมผู้อ่านร่วมและตรวจเครื่องจริง/บริการ Web ทั้ง process tree |
| เปลี่ยนเครื่อง/มิเตอร์ลด | มี epoch ข้ามวัน/store/exchange จำลอง 3 DB และหน้าตรวจฐานที่บันทึกพร้อมประวัติร่วมแล้ว; เหลือ remote adoption และเชื่อม legacy cache/ยอดรอตรวจ |
| ผู้อ่านร่วม/อ่านด้วยมือ/ส่งผล Web | มี journal/คิว/ACK Web, manual local ไม่เลื่อนตาราง และ durable grants/join จำลอง A/B/C แยกฐาน; authority election/สมาชิก/HTTPS delivery และ runtime ร่วมยังไม่ครบ |
| ยอดลงวันก่อนหน้า/remark/กราฟเฉลี่ย | มี engine และหน้าตรวจหลักฐานพร้อมกราฟทศนิยม/Excel/PDF; ยังไม่เชื่อมการแก้ ledger/ฉบับเรียกเก็บเดิม |
| คำนวณราคา/ส่วนลด/รอบบิลย้อนหลัง | มี preview และการแก้ไขแบบ atomic บนคอมเดียว รวมปรับสรุปรายเดือน Archive; เหลือการกระจายฉบับแก้ไขให้สมาชิก |
| Hotfix ลงทะเบียน | มี foundation ที่ยังปิดใช้งาน ไม่ใช่ Hotfix ลูกค้าที่พร้อมติดตั้ง |
| Archive/benchmark/คู่มือใหม่ | Archive ผล Web และ daily subject/raw แยกปี พร้อมสรุปรายเดือน/backup/restore; ผ่าน source regressions และวัดหลัง archive 876,300 แถว/24.37 MiB ยอดตรง; คู่มือ source มีแล้ว ยังเหลือฉบับส่งมอบ |

ห้ามนำจำนวน tests ในบันทึกเก่ามาอ้างว่าฟีเจอร์ที่เพิ่งตกลงผ่านแล้ว
ผลวัด Agent เดิมเป็น fixture งานว่าง ไม่ใช่ผลรวมภายใต้ workload จริง

## ลำดับพัฒนาเมื่อผู้ใช้สั่งเริ่ม

รหัส P เดิมคงไว้เพื่ออ้างอิงหลักฐาน; ใช้ลำดับในตารางนี้เป็นลำดับทำงาน
พัฒนาพื้นฐานและเชื่อมเส้นทางใช้งานให้ครบก่อนเปิดให้คอมอื่นหยุดอ่าน
ไม่เปิดโหมดผู้อ่านเดียวทั้งระบบขณะที่การส่งผล Web ยังไม่พร้อม

| ลำดับ | งาน | เกณฑ์หลักก่อนถือว่าเสร็จ |
|---|---|---|
| 1 — P1 | การตั้งค่าร่วม/slot, เก็บ revision ทุก save, atomic apply, popup conflict/undo | ค่าและประวัติสำเร็จพร้อมกันหรือ rollback ทั้งหมด; cancel/stale preview ไม่เขียนทับ; ตัวตนคอมไม่ถูกคัดลอก |
| 2 — P2a | Discovery, การเชื่อมต่อสมาชิกที่ยืนยันแล้ว, HTTPS, คิวส่ง/ยืนยันรับ/ส่งต่อเมื่อกลับมา | Wizard ค้นหา/ค้นหาซ้ำ/manual IP; ส่งซ้ำไม่เกิดผลซ้ำ; ไม่ส่งข้อมูลให้แค่ผู้ตอบ broadcast; ข้ามข้อจำกัดประวัติ 256 revisions/128 KiB ด้วย paging |
| 3 — P2b | ผู้อ่านตามรอบ/รับช่วง/คำขออ่านด้วยมือ และส่งผล Web ที่บันทึกแล้ว | จำลอง A/B/C แยกฐาน: หนึ่งงานเมื่อประสานกันได้, ตารางไม่เลื่อน, ส่งหลัง commit, ไฟดับ/เน็ตแยกแล้วกลับมารวมโดยยอดไม่เพิ่ม |
| 4 — P4 | เปลี่ยนเครื่องใน slot/ฐานเดียวกัน/ประวัติผู้ใช้/มิเตอร์ reset | 2,000 + (50,100 − 50,000) = 2,100 ทุกคอม; รองรับข้ามวันและเครื่องกลับมาออนไลน์ทีหลัง |
| 5 — P5 | เติมประวัติ, ลงยอดวันก่อนหน้า, remark, กราฟเฉลี่ย และกู้สำเนา | รับซ้ำ/สลับลำดับไม่เพิ่มยอด; ตัวอย่างศุกร์–จันทร์ตรงทุกมุมมอง; เติมจริงแทนประมาณไม่ทำยอดซ้ำ |
| 6 — P6 | วันบังคับใช้ราคา/preview คำนวณใหม่/ฉบับแก้ไข | ใช้วัน/รุ่นราคาถูกต้อง; ช่วงข้อมูลขาดข้ามขอบเขตมี flag; ฉบับออกแล้วไม่ถูกเขียนทับ |
| 7 — P2c/P3 | Agent เบาและ UI การตั้งค่าเครือข่าย/Web/shortcut | ปิด–เปิด UI ไม่มีบริการซ้ำ; full stop ใช้ได้; สถานะหน้าจอตรงข้อมูลจริง; แสดงรูปที่ผู้ใช้เปิดดูได้ |
| 8 — P7 | Archive รายปี/สรุปรายเดือน/benchmark 5 ปี 100 ผู้ใช้ | ยอดก่อน–หลังตรง; archive เสียไม่ลบต้นฉบับ; บันทึกขนาดและเวลา query/load จริง |
| 9 — P9/H1 | ลงทะเบียน/ใบรับรองและตรวจการเชื่อมต่อ Host ตามข้อสรุป | ทำ source/fixture tests เส้นทางปกติ–recovery–retry–ปิดถาวร; ยืนยันขอบเขต TLS; ไม่แก้ production |
| 10 — P8 | ทดสอบรวม เก็บกวาดโค้ด/หลักฐาน และคู่มือ | ผ่านชุดสถานการณ์ด้านล่าง; เอกสารตรงกับพฤติกรรมที่ทำแล้วจริง ไม่ติ๊ก foundation ว่า feature เสร็จ |
| ภายหลัง — R1 | ผู้ใช้ตรวจและตัดสินใจ build/installer | ยังไม่อนุญาต; ค่อยทดสอบติดตั้งจริง/อัปเกรด/สร้าง shortcut จาก installer เมื่อได้รับอนุญาต |

P9/H1 ที่ตรวจ source/fixture ได้อาจทำสลับระหว่างช่วงอื่นได้เมื่อเริ่มพัฒนาแล้ว
หากงานใดขาดสิทธิ์จริง ให้บันทึกหลักฐานและพักเฉพาะส่วนนั้น ไม่หยุดงานที่ไม่ขึ้นต่อกัน

## ชุดทดสอบยอมรับ

- [ ] คอม A ตั้งค่า 3 slot; B/C/D รับตรงกันโดยไม่คัดลอก installation ID
- [ ] ค้นหา LAN เจอ/ไม่เจอ/ค้นซ้ำ/manual IP, Firewall บล็อกและพอร์ตชน แสดงเหตุถูกต้อง
- [ ] A อ่านตามตาราง, B/C รับ Web ที่บันทึกแล้ว; SNMP อย่างเดียวไม่ทำให้ Web ของสมาชิกดูใหม่
- [ ] A ไฟดับ/หลับ/ตัวอ่านค้าง/อ่านสำเร็จแต่ดับก่อนส่ง: รับช่วง/ส่งค้างต่อได้ ไม่อ้างว่าสำเนามีครบก่อนยืนยันรับ
- [ ] รอบ 10:00/10:15/10:30 + อ่านมือ 10:10 ได้สี่จุดจริง; รอบทับงานให้ใช้ผลเดียว
- [ ] B/C กดพร้อมกัน, กดตรงกับรอบ A, อ่านนอกช่วง, ผู้อ่านชั่วคราวดับ ไม่ล็อกงานตลอดไป
- [ ] LAN แยกและกลับมา, นาฬิกาคอมต่างกัน, ข้อมูลเก่ามาทีหลัง: ใช้ max ใน Serial/ตัวนับ/ช่วงฐานเดียวกัน
- [ ] การอ่านซ้อน/ส่งซ้ำไม่บวกมิเตอร์หรือ delta ของแต่ละคอม; สถานะหมึกไม่ใช้กฎ max
- [ ] เปลี่ยน slot จาก D แล้ว A/B/C เห็นตรงกัน, เครื่องเก่าถอดไปแล้วมี remark, มิเตอร์ใหม่ไม่กระโดด
- [ ] Save/cancel/ล้มเหลวกลาง transaction, ส่งตั้งค่าไม่ถึง, แก้พร้อมกัน, undo, restart แล้วประวัติครบ
- [ ] เติมประวัติเฉพาะส่วนขาดหลังเปิดเครื่อง, ส่งลำดับสลับ/ขาดกลางทางแล้วทำต่อได้
- [ ] ศุกร์ 1,000 → จันทร์ 1,300: ledger วันอาทิตย์ 300 + remark; กราฟเสาร์/อาทิตย์ 150/150 ไม่ซ้ำ
- [ ] 301 ÷ 2 = 150.5/150.5; ทศนิยมซ้ำปัดเฉพาะการแสดง, ไม่มีวันว่างเต็มวันไม่หาร, ตรวจแยกแต่ละเครื่อง
- [ ] เติมข้อมูลจริงภายหลัง เปลี่ยนส่วนประมาณให้ถูกต้อง ยอดรวมเดิมครบ และ issued report ใช้ฉบับแก้ไข
- [ ] Remark/ค่าเฉลี่ยแสดงบนจอและ Excel/PDF; กราฟสะสมยังเป็นจุดอ่านจริง
- [ ] ราคา effective date, ช่วงข้ามเดือน/รอบบิล/วันเปลี่ยนราคา, preview/cancel/recalculate ไม่เปลี่ยนฉบับเก่า
- [ ] Agent เปิด–ปิด–รับช่วง UI/tray ไม่มี collector/Web ซ้ำ; วัดทั้ง process tree ภายใต้ workload ที่ระบุ
- [ ] Web refresh 60 วินาที/refresh มือ, outage คงข้อมูลเดิม, initial failure ไม่แสดงศูนย์หลอก
- [ ] Shortcut local Web/โลโก้/สร้างใหม่/optional password; installer-specific checks ระบุ WAIT BUILD
- [ ] Archive ครบ/เสีย/หาย, backup restore, เปิดรายเดือนและเรียกข้อมูลเก่าเมื่อขอ, benchmark 5 ปี/100 ผู้ใช้
- [ ] Registration ปกติ, certificate failure, opt-in recovery ขอบเขตแรกเท่านั้น, retry idempotent และปิดถาวรหลัง ack
- [ ] ตรวจ dead code และหลักฐานเก่าก่อนลบ; คู่มือ/ภาพจริงครบก่อนขอ build

## งานตรวจของ AI และจุดรอผู้ใช้จริง

- ตอนนี้ไม่มีคำถามเชิงวิธีใช้งานค้างจากข้อ 1–5 ของการสนทนา
  สิ่งที่ตกลงแล้วคือข้อกำหนดพัฒนา ไม่ใช่ฟีเจอร์ที่เสร็จหรือข้อรับรอง Host
- ตรวจ Host โดยใช้สิทธิ์ in-app ที่มีแบบอ่านอย่างเดียว; UI ที่ไม่แสดง company key
  ไม่พิสูจน์ว่า backend ไม่มี และการ login เว็บไซต์ไม่เท่ากับมี source backend
- การลงทะเบียนแสดงชื่อเดียวหลัง sync: ตรวจตัวตน installation และ payload จริง
  ก่อนสรุปว่าเกิดการคัดลอก ID หรือ backend รวมรายการ
- นโยบายสาม slot ร่วมกันตกลงแล้ว; ตรวจให้การตั้งค่า/สมาชิก/contract ทำงานตามนั้น
  ไม่เปิดคำถามกลุ่มส่วนตัวของ D อีก และไม่ละเลยการตรวจสิทธิ์แลกข้อมูล
- แนวทาง Hotfix ตกลงแล้ว แต่ trust path ต้องมีหลักฐานและ tests
  ไม่มี pin ที่ยืนยันแล้วในหลักฐานปัจจุบัน ไม่เดา/เชื่อ observed certificate ทันที
- ถ้าขาด source/API/สิทธิ์ที่จำเป็นจริง ให้ระบุสิ่งที่ตรวจและสิ่งที่ขาดเฉพาะเจาะจง
  ไม่แจ้งว่า “รอ Host” ลอย ๆ หรือขอสิทธิ์ซ้ำก่อนตรวจ
- ผู้ใช้ตรวจหน้าตาและวิธีใช้งานเมื่อมีตัวอย่างที่เปิดดูได้; เครื่องพิมพ์จริง/สองคอมจริง
  ใช้ขั้นตอนทดสอบที่ AI เตรียม โดยแยกจาก simulation และ installer QA
- ผู้ใช้สั่งเริ่มพัฒนาแล้ว ไม่รอคำยืนยันซ้ำ; build/เผยแพร่ยังต้องอนุมัติแยกภายหลัง

## Existing evidence (not release approval)

### 2026-09-18 — atomic range repricing and source manual draft

- Added a date/slot-range repricing review with before/after totals and explicit
  skipped held/manual/unpriced entries. Confirmation recalculates the preview,
  rejects stale data, and appends all reversals/replacements plus a batch receipt
  in one transaction. Repeated identical confirmations return the same result;
  a failure on the second replacement rolls back the complete batch.
- The single-entry and batch paths now use the same transaction-owned posting
  function. Original postings, discount, meter evidence and billing periods stay
  immutable. This does not yet recalculate historical discount/period changes or
  distribute shared corrections to peers.
- Service tests: **23 passed in 13.07s**. Combined audit/dialog/exports/responsive/
  layout regression: **51 passed in 46.12s** before the final remarks-column
  width adjustment. Synthetic offscreen images generated with the application's
  stylesheet and inspected; source manual draft documents actual limitations.
- Draft: `docs/CUSTOMER_GUIDE_V5_2_12_DRAFT.md`, with four source screenshots in
  `docs/customer-guide/assets-v5.2.12-source`. Not final installer documentation;
  keep updating it as the remaining workflows are completed.

### 2026-09-18 — dated-price choices, manual read cadence and canonical report performance

- Shared settings review now applies dated price schedules atomically with the
  chosen history head, retains both parents on conflicts, and supports undo per
  changed price/date while preserving unrelated later edits. Also covers pricing
  mode and legacy working hours. Printer/company changes still require their
  setup/replacement workflow; this is not a company authorization bypass.
- History changes now notify runtime policy and refresh settings; previously a
  successful undo could leave the old scheduler running until a later reload.
  Source price/history/setup/repricing suite: **58 passed in 21.55s**.
- Manual collection no longer moves the scheduled SNMP/Web clocks. An in-flight
  SNMP round can be promoted to Web; requests arriving after the skip decision
  trigger one subsequent real read. Requests during Web share the active read.
  Scheduled overlap consumes that round without manufacturing another point.
- Web success/cache dates use the actual observation timestamp, including a
  midnight crossing; the scheduled round retains a separate cadence anchor.
  Tests verify 10:00/10:10/10:15/10:30, overlapping requests, boundary race and
  shutdown: **38 passed in 11.36s**. This is local collection coordination; peer
  election/grants/transport are still pending, not certified by these tests.
- Canonical billing-period reports now restrict subject SQL to that period
  while preserving frozen ledger periods. Previously only custom ranges were
  bounded, so normal report navigation could still scan all five years.
  On the existing synthetic 5-year/100-user/3-printer DB: August query median
  **467.39 ms**, 300 result groups, exact **111,600 pages**; three runs, alongside
  source tests. Source/history/snapshot/startup suite: **38 passed in 7.57s**.

### 2026-09-18 — evidence-based gap inspection and idle archival

- Added deterministic single-serial/counter/epoch interval projection using
  maximum cumulative values, never sums of peer counters. Duplicate/reordered
  deliveries converge. Lower values and ambiguous clock/schema evidence require
  review; no reset is inferred. Price/billing boundary intervals are flagged.
- Friday 1,000 to Monday 1,301 allocates 301 to Sunday; daily chart replaces
  that allocation with two clearly estimated bars of 150.5. Exact fractions
  remain unrounded internally. Late Saturday evidence replaces estimates without
  adding usage; days with any Web evidence are excluded from whole-day gaps.
- Meter review now opens an on-demand Web evidence dialog: bounded date/data
  reads including archived details, daily estimates, actual cumulative points
  with dashed gaps, interval remarks, and Excel/PDF evidence exports. Loading is
  in a worker; empty/error results cannot masquerade as a fresh zero report.
- This is a usable evidence inspection/report, NOT integration into the main
  billing ledger/issued reports or proof of cross-PC synchronization. Reviewed
  shared epochs, corrections to existing daily allocations and monetary report
  amendment integration remain. The dialog explicitly states that boundary.
- Inspection/projection/export/meter-review/Web-journal tests: **42 passed in
  13.29s**. Actual offscreen Qt dialog rendered and inspected using synthetic
  Friday/Monday data; no printer/Host access. Excel includes decimal values and
  remarks; PDF generated via Qt. No release build.
- Runtime now archives one bounded verified chunk at a time after startup when
  no printer work is active, continuing on later idle turns. It stops checking
  once complete for the day, backs off after errors, logs failure visibly, and
  drains with runtime shutdown before releasing handoff ownership. No network
  polling or eager reading of old archive files is introduced.
- Maintenance/polling/Agent/tray/handoff source tests: **31 passed in 17.93s**.

### 2026-09-18 — verified individual Web archives and portable recovery

- Schema 24 adds immutable compressed yearly Web observation chunks and their
  catalog. Bounded maintenance verifies every payload and file before atomically
  replacing hot payloads with references. IDs, sequence cursors and pending
  deliveries stay intact; old details load only when requested. Recent queries
  and startup metadata do not open old files. Missing/corrupt files fail visibly.
- Advanced settings can start/cancel maintenance between atomic batches (20s
  job budget). This is manual maintenance, not yet automatic Agent maintenance.
- Backup, staged restore and first-run DB copy now copy and checksum exactly
  the catalog-referenced immutable files before publishing the destination DB.
  Conflicting/missing/corrupt archives abort without replacing either original.
  A portable backup consists of the DB and its adjacent archives folder.
- Usage/factory reset clears catalog references; physical archive files remain
  like old backups. Failed transactions may leave unreferenced verified files.
  No automatic deletion or VACUUM; free DB pages are reusable, not guaranteed
  immediate filesystem shrinkage. Full daily subject/raw monthly rollups remain.
- Archive/service/UI/backup/restore/migrations/reset/layout source tests:
  **68 passed in 18.41s**, synthetic temporary databases only. No build/publish.

### 2026-09-18 — broad regression triage and source fixes

- A monolithic Qt test run stalled after roughly a quarter of the suite; stopped
  only its verified pytest processes. A separate per-file audit covered 124
  top-level files. Eleven files initially failed or aborted, including stale
  synchronous-UI/version assertions and a missing offscreen environment in that
  audit runner. A standalone import-layout run passed all 19 cases.
- Fixed real numeric-name issues: leading-zero subject IDs can use an
  unambiguous export alias without changing the ID/counter; Unicode digit-like
  names no longer crash reports and are preserved. Ambiguous aliases are not
  guessed. Shared the lightweight name helper between collection and reporting.
- Compact reports now apply the common tab theme's compact geometry so tabs
  remain visible. Updated older tests for deferred pages, staged report jobs,
  the meter-review tab, Thai schedule labels and desktop-owned Windows Web launch.
- Version gate now recognizes the existing Online installer name and normalizes
  CRLF before comparing the unchanged shared-contract SHA. Verified the LF hash
  equals the existing contract identity; no contract/API policy was rewritten.
- After fixes: affected UI/schedule/metadata group had 70 passes plus one
  Unicode-name expectation mismatch; preserved intentional Unicode names, then
  reran that full Mac/name/history/release-fixture group: **55 passed**. Nested
  profiler, repricing and summary tests: **111 passed**. Counts overlap; these
  are not a claim that one monolithic full-suite process completed.
- Inspected rendered baseline/repricing dialogs from synthetic Qt fixtures;
  corrected the remaining untranslated Cancel label. Release-builder tests use
  mocked temporary fixtures; no installer/release build, push or Host changes.

### 2026-09-18 — reviewed dated-price recalculation

- Billing Audit can preview a selected verified posting against the price
  effective on its usage date, then confirm a correction with a reason. The
  service preserves original meter/category/discount/period evidence and appends
  an exact reversal plus recalculated replacement in one transaction.
- Preview detects changed prices or superseded entries. Repeated confirmation
  is idempotent; manual adjustments/holds cannot be relabelled as verified
  automatic usage. Original issued evidence is never updated or deleted.
- Targeted billing/audit/monthly source tests: **31 passed** in 10.57 seconds,
  including actual page/dialog flow, cancellation, stale preview, failing insert
  rollback, successive corrections and future-price exclusion.
- This handles local price correction. Shared corrections, retrospective
  billing-period/discount changes and archive-backed recalculation remain open.

### 2026-09-18 — five-year benchmark and bounded subject queries

- Wrote an isolated 5-year fixture: 100 users on 3 printers, 547,800 subject
  and 547,800 raw rows, plus 5,478 daily/ledger rows each. Daily database is
  435,470,336 bytes. No customer database or printer/Host access.
- A selected 30-day subject report previously decoded all five years before
  filtering: median 40,300 ms. Pushing date bounds into SQL reduced this to
  523 ms on the same database; 300 groups and 108,000 pages remain correct.
  Affected history/report regressions: **39 passed** in 14.85 seconds.
- Measured one 100-user Web payload and separately estimated retained rounds
  at 5/15/30/60-minute intervals; this is not five years of physically written
  Web events. Full assumptions and measurements: `docs/qa/v5.2.12/FIVE_YEAR_BENCHMARK.md`.
  Archive itself and post-archive validation remain open.

### 2026-09-18 — durable individual Web observations

- Schema 23 stores immutable parsed Web rounds, local provenance/read IDs,
  outgoing work and per-member ACKs. The collector commits the observation and
  queue together before updating live Web snapshots. SNMP-only or failed Web
  does not create an event; a journal failure cannot publish a fresh snapshot.
  Missing Serial remains local-only with a visible diagnostic; no anonymous
  observation is offered for sharing.
- Every actual round is retained, including manual rounds between scheduled
  readings. Exact replay deduplicates; conflicting payloads for one read ID
  reject. Bounded, high-water-pinned pages support replay and arrivals during
  transfer without skipping records. Incoming authorized batches commit
  atomically, reject a wrong slot/Serial or altered hash, and create no echo
  queue. Receipts survive restart and are independent per recipient.
- Source regression: **63 passed** in 19.99 seconds, clean exit, including
  collector persistence failure, two independent databases, reversed/duplicate
  imports, byte limits, reset, migration, device and daily-cache checks.
- This is the evidence/outbox layer. Actual authenticated transport, baseline
  epoch reconciliation, catch-up projection into reports and reader arbitration
  remain open. Incoming history does not yet modify usage or live Web status.

### 2026-09-18 — reviewed subject and exact-counter baselines

- Fixed User/Account and Raw Counter accumulation after a falling counter:
  preserve pre-drop usage, retain subsequent observations, and hold further
  usage until explicit serial-bound baseline review. Holds survive restart and
  day rollover; a larger subsequent value alone cannot clear them.
- Added subject/raw entries to the review panel with reason, verification,
  stale-preview rejection and atomic audit. Resume only increases after the
  reviewed observation. Affected reports remain marked for review; confirmation
  does not amend past reports or invent missing usage.
- Schema 22 stores raw holds and audit. Legacy reset rows retain original
  totals and are flagged rather than rewritten. Raw screen/Excel label holds.
- Source regression: **91 passed** in 48.95 seconds, clean exit: migration,
  daily/subject/raw history, slot replacement, review UI and Excel. Initial UI
  label failure (missing translation import) was fixed before the passing run.
- These are local workflows. Shared baseline decisions, cross-peer replacement
  and historical amended-report workflows remain open. No installer/build.

### 2026-09-18 — durable settings events and Host source lookup

- Added additive schema 21 for settings events and per-member receipts/retries.
  Local revision append and accepted incoming fast-forward enqueue inside the
  same transaction as settings/head changes. A queue-write failure rolls back
  the setting, journal and head. Importing unreviewed history alone never queues
  it as an applied setting.
- Pending delivery coalesces to the active head, which carries previous edits
  as ancestors. Reading a pending item or restarting cannot acknowledge it.
  A verified complete-head ACK covers its queued ancestors for that member only;
  an old ACK cannot hide a newer edit, and a late failure cannot erase an ACK.
  Retry state survives restart, with bounded backoff and reconnect override.
- Upgrade queues an existing current head. Usage reset preserves delivery state;
  factory reset removes events and receipts before deleting revision history.
  Source tests: **77 passed** in 28.22 seconds with one Starlette/AnyIO warning,
  clean exit. This is a tested persistence layer, not an enabled delivery worker.
- Rechecked Host access through the existing logged-in in-app session, read-only.
  The previous tab had closed; a temporary tab confirmed login and License UI
  still work, then was closed without signing out. The UI continues to describe
  company counts as estimated from normalized names. No production records were
  edited or exported, no licenses were issued, and no Host calls were fabricated.
- Available saved projects and this repository expose no separate Host backend
  source. Asked for its repository/folder so company-to-installation authority
  and trust handling can be verified. This is not a request to approve an
  already-agreed product policy, and is not evidence that the backend lacks the
  capability. Park production membership integration pending that source;
  continue independent source work. No blanket request for Host credentials.
- Additional code audit found subject/raw counter paths still add a decreased
  absolute counter as usage; include these in the P4 reset/baseline workflow,
  not just device totals, before claiming replacement/reset behavior complete.

### 2026-09-18 — atomic Setup, dated prices, history review and bounded LAN discovery

- Latest instruction: implement all remaining authorized work in sequence. Work
  remains in this task on local main; no automation, build, release or production
  changes are authorized by this instruction.
- Wizard now reviews and commits device configuration, price updates, settings,
  registration inventory (edit mode), config audit and causal history together.
  Repository callbacks share its SQLite transaction; failures also compensate
  credential-vault writes. Registration activation remains a separate subsequent
  step; registration failure does not discard the saved configuration or unlock
  the application. Cancel and concurrent-edit rejection preserve the draft.
- Shared document format 2 keeps all effective-dated prices, including future
  dates and historical prices for disabled slots. It excludes computer identity,
  credentials and current-day price projections. Merely crossing midnight or a
  price effective date cannot generate a shared edit. Legacy journal documents
  remain readable; applying old/incompatible setup documents is not automatic.
- Network settings exposes read-only history, previous/new values, reviewed undo
  for billing/discount/schedule, and local/incoming conflict choice for supported
  fields. Undo appends a new revision; conflict choices retain both parents.
  Partially received pages cannot appear as an actionable incoming head.
  Printer/price/company application still requires its dedicated workflow;
  this UI does not bypass slot replacement or retrospective billing review.
- Added bounded ancestor-first history pages with immutable-head cursors,
  per-page byte/count limits, hash/ancestry validation, restart/resend support,
  and no automatic application. One approved claim can read the same pinned
  history for five minutes; its hash is bound to requester IP and installation.
  It cannot authorize another head or the setup endpoint; closing pairing
  revokes it. A lost first reply can be retried without consuming new approval.
  Individual revisions larger than 128 KiB still fail explicitly; chunking a
  single large document remains needed before claiming unlimited history size.
- Added UDP discovery on port 37852: nonce-correlated, size/rate bounded replies
  contain only an HTTPS port. Replies do not authenticate company membership.
  Wizard verifies targets through the existing HTTPS discovery path and falls
  back to IP discovery/manual IP. API lifecycle owns the responder, advertises
  the configured public HTTPS port and stops its thread on shutdown. Listener
  failure does not stop Web. Interface scope is refreshed when requests arrive.
  This listener currently follows Web-service lifecycle; separating peer sync
  availability from the report enable switch remains part of P2/P3 integration.
- Tests used synthetic databases, in-memory credentials, loopback UDP, fake
  HTTPS/Host transports and offscreen Qt. No real LAN advertisements, customer
  printer calls, Host writes or Windows Firewall changes were performed.
- Combined regression: **239 passed** in 150.87 seconds, one Starlette/AnyIO
  deprecation warning, clean exit. Web security suite: **7 passed**, clean exit,
  using an isolated temporary fixture and read-only existing dependencies.
  After conflict UI/incomplete-page gating, affected tests: **91 passed** in
  60.31 seconds (counts overlap). After final strict document validation and
  UI price-diff refinements: **76 passed** in 28.98 seconds, same warning and
  clean exit. These counts overlap; they are not additive.
- Source-rendered price review/history inspected in
  `Temp/komi-shared-setup-review-t67bhav9`; inspection led to friendly action/date
  labels, previous/new details and displaying only changed effective-price rows.
- Remaining P1/P2 integration: apply full approved peer setup/slot decisions and
  price history safely, durable authenticated membership and event outbox/ACK,
  reconnect delivery and UI reload after applied settings. Shared reader/manual
  coordination and Web observation delivery remain pending and are not enabled
  by discovery alone. P4–P9/H1 and final manuals/real-machine QA remain open.

### 2026-09-18 — resumed P1: reviewed billing and schedule transactions

- User explicitly resumed development; work continues directly in this task.
  The prior heartbeat was briefly reactivated, then the user questioned scheduling.
  The attempt to pause it reported that the automation had been deleted. Do not
  recreate it. This does not cancel the user's instruction to develop the code.
- Added SharedSettingsService for billing_day, waste_paper_pct and reading
  schedule. Previews are read-only, bound to the database path, causal head and
  complete shared snapshot. Save writes the changed values, config audit and
  history revision in one SQLite transaction; cache readers cannot observe a
  partial commit. Legacy pre-edit values are captured as a baseline when needed.
- Connected the actual fleet billing/schedule Save buttons to a shared-settings
  confirmation dialog with old/new values, all-computers/offline notice and
  Cancel default. Cancellation keeps the draft. A concurrent edit rejects the
  stale preview and leaves the newer values intact. Missing persisted defaults
  are checked consistently so a successful save does not leave the form dirty.
- Added transaction-scoped snapshot reads using the existing setup allowlist;
  neither cached reads nor a separate repository connection can describe a
  different commit. Installation IDs and credentials stay out of shared history.
  The v2 history endpoint now authorizes separately and observes current database
  values under the history write lock. It cannot append a stale snapshot captured
  before a concurrent settings save and make that save appear to be undone.
- Added reviewed peer-choice and selective-undo service paths for these fields.
  Existing incoming revisions fast-forward without generating another edit;
  explicit conflict resolution retains both parents. Device/organization/price
  changes are rejected here and must use their own workflows. This service is
  not yet a network delivery loop or the user-facing conflict/undo screen.
- Usage-data reset preserves the shared settings journal; factory reset clears
  both revision and state tables so the next installation cannot retain the old
  company's history or journal identity.
- Source tests exercise injected failure during field writes, revision append
  and incoming-head update; two separate databases with offline conflicting edits;
  duplicate delivery/convergence; stale cache/database switch; selective undo;
  identity preservation; UI Cancel and stale confirmation. The original combined
  test attempt was interrupted after fixture failures; corrected the missing
  configured defaults and a save-verification default mismatch, then reran.
- Inspected synthetic source-rendered dialogs with the application stylesheet.
  Widened schedule columns and resized wrapped rows; billing and schedule renders
  are in Temp/komi-shared-review-rsd_9zs3/{billing-final,schedule-final}.png.
  Render helpers exited cleanly. No live printers or Host calls were used.
- Ruff is not installed in the existing Python environment; no dependency was
  installed just for this optional check. Whitespace checked with git diff --check.
- Final combined source suite: **107 passed**, with one dependency deprecation
  warning (Starlette/AnyIO), and a clean process exit. After the final endpoint
  snapshot-race fix, the affected shared-settings/history/Web API suite was rerun:
  **44 passed**, same warning, clean exit. Counts overlap; do not add them.
- P1 remains in progress: next wire Setup/device/price saves to a complete atomic
  history contract (including effective-dated prices), then expose conflict/undo
  review in the UI. P2 durable authorized membership/outbox/event delivery and all
  shared-reader, catch-up and chart changes remain pending. No release build.

### 2026-09-18 — consolidated design and explicit development pause

- Updated this plan only, incorporating the complete subsequent discussion:
  temporary reader/manual-read coalescing, schedule-based failover checks,
  Web-only persisted observation exchange, maximum cumulative meter within its
  identity/baseline, previous-day catch-up booking with remarks, decimal chart
  estimates over completely missing Web days, and one shared three-slot mapping.
- Replaced superseded requirements that all computers independently collect or
  that forbid the newly approved chart estimate/accounting placement. Preserved
  actual observations and clearly separated estimates from measured daily usage.
- Registration recovery policy is settled; remaining trust/contract verification
  is implementation evidence, not a repeated product-policy question.
- Development and automation remain paused at the user's request. No source code,
  runtime configuration, Host/customer data, build or deployment changed.
- Historical source test counts below were not rerun for this documentation edit
  and do not validate the newly agreed features.


### 2026-09-18 — user revised sync triggers

- Missing-data catch-up runs after computer startup / Agent readiness. Shared
  settings propagate when a member sends a newly committed settings revision.
  This supersedes the original five-minute cadence and the suggested thirty-minute
  fallback. Undelivered work persists across offline/restart and retries without
  adding an idle settings poll; ordinary printer collection is separate.
- Updated approved requirements, P2/P5 implementation steps and acceptance checks.
  Source inspection found the settings-history/one-time setup foundation, but no
  continuous settings replication timer to disable yet. The existing five-minute
  pairing approval window is an authorization lifetime, not a sync interval.
- Documentation-only change; event delivery and startup catch-up remain pending
  implementation. No runtime tests or builds were run for this plan revision.

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
- The final standalone render helper produced the PNG but did not exit during
  the follow-up waits and was interrupted. Do not count that helper as a clean
  shutdown test; the 59-test Wizard suite did exit successfully. Investigate the
  helper shutdown separately if it recurs in lifecycle QA.

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
  of chosen values together with journal head, conflict preview/choice UI,
  automatic exchange (cadence superseded by the revised sync triggers above),
  durable peer membership, history paging beyond
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
