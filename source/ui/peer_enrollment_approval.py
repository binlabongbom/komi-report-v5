"""Information about persistent joining; no approval action is required."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
from i18n import tr


class EnrollmentApprovalDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('รายละเอียดการเข้าร่วมกลุ่ม', 'About joining a group'))
        self.setMinimumSize(520,220)
        layout = QVBoxLayout(self)
        self.message = QLabel(tr(
            'เปิดรับสมาชิกไว้ตลอดโดยอัตโนมัติ ไม่ต้องกดเปิดรับซ้ำที่เครื่องนี้ เครื่องใหม่เลือกกลุ่มและบันทึกใน Wizard ได้ สมาชิกจะ Sync การตั้งค่าและประวัติการใช้งานต่อเนื่อง\n\nเมื่อเข้าร่วมครั้งแรก ระบบสร้างฐานมิเตอร์เริ่มต้นจากผลอ่าน Web ที่ถูกต้องครบทุก Slot ให้อัตโนมัติ หาก Serial เปลี่ยน มิเตอร์ลดลง หรือข้อมูลขัดแย้ง จึงต้องตรวจฐานที่หน้าตรวจสอบมิเตอร์',
            'Joining stays open automatically. No repeated approval is needed on this computer. New computers select the group and save in the Wizard; members continue syncing settings and usage.\n\nOn first enrollment, initial meter baselines are created automatically from consistent Web readings for every Slot. A changed serial, falling counter, or conflicting evidence requires Meter Review.'))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr('ปิด','Close'))
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
