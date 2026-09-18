"""Use the existing asynchronous review flow for one detail counter."""
from PyQt6.QtWidgets import QTableWidgetItem
from services.report_detail_amendment import ReportDetailAmendment
from ui.billing_web_amendment import BillingWebAmendmentDialog


class ReportDetailAmendmentDialog(BillingWebAmendmentDialog):
    def __init__(self, scope, parent=None, *, database_path=None, service=None):
        super().__init__(scope, parent, database_path=database_path,
                         service=service or ReportDetailAmendment(database_path=database_path))
        self.setWindowTitle('ตรวจแก้รายละเอียดผู้ใช้ / Raw Counter')
        self.description.setText('ตัวนับที่เลือก: ' + scope[-1].field + ' · ' + (scope[-1].subject_id or 'เครื่องพิมพ์') +
            '\nคำนวณรายละเอียดจากผล Web ในฐาน Slot นี้ พร้อมฉบับแก้ไขและหมายเหตุ '
            'เก็บต้นฉบับในฐานข้อมูลและ Archive ไว้ ยอดเงินตรวจแก้แยกผ่านหน้าการแบ่งยอดหรือรอบบิล '
            'ฉบับแก้ไขจะเข้าคิวส่งให้สมาชิกที่ยืนยันสิทธิ์แล้ว')
        self.load_button.setText('ตรวจรายละเอียดกับหลักฐาน')
        self.table.setHorizontalHeaderLabels(['วันที่', 'รายละเอียด', 'ยอดเดิม', 'ยอดใหม่', 'หมายเหตุ'])
        self.reason.setPlaceholderText('เหตุผลที่แก้รายละเอียด')

    def show_preview(self, result):
        self.status.setText(f"เปลี่ยน {len(result['changed'])} รายการ · เวลาและมิเตอร์จริงเก็บตามหลักฐาน · วันที่จัดสรรอาจไม่มีจุดอ่านจริง")
        self.table.setRowCount(len(result['changed']))
        for index, item in enumerate(result['changed']):
            values = (item['day'], 'ผู้ใช้/บัญชี' if item['kind'] == 'subject' else 'Raw Counter',
                      'ไม่มีข้อมูล' if item['before'] is None else f"{item['before']:,.0f}", f"{item['after']:,.0f}",
                      'ฉบับแก้ไขจากหลักฐาน Web · เก็บต้นฉบับไว้')
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
