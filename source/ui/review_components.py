"""Small review form components, keeping evidence behind the decision summary."""
from datetime import date
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QToolButton, QPlainTextEdit, QPushButton, QApplication
from i18n import tr


def field_label(layout, field, thai="เหตุผล / หลักฐาน (จำเป็น)", english="Reason / evidence (required)"):
    label = QLabel(tr(thai, english))
    label.setBuddy(field)
    label.setWordWrap(True)
    field.setAccessibleName(label.text())
    layout.addWidget(label)
    return label


def display_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def hold_reason_text(code):
    reasons = {
        "missing_web_success": ("ยังไม่มีผลอ่าน Web ที่สำเร็จ", "No successful Web reading"),
        "missing_or_unsafe_attestation": ("หลักฐานมิเตอร์ยังไม่ผ่านการตรวจ", "Meter evidence has not passed validation"),
        "incomplete_day": ("ข้อมูลของวันนี้ยังไม่ครบ", "The day's readings are incomplete"),
        "device_identity_conflict": ("ข้อมูลยืนยันเครื่องพิมพ์ไม่ตรงกัน", "Printer identities do not match"),
        "counter_reset_or_out_of_order": ("มิเตอร์ลดลงหรือเวลาอ่านไม่เรียงกัน", "Meter decreased or readings are out of order"),
        "unsafe_attestation_seen_during_day": ("พบผลอ่านที่ต้องตรวจสอบในระหว่างวัน", "A reading during this day needs review"),
        "missing_category_snapshot": ("ยังไม่มีหมวดมิเตอร์ที่ใช้คิดราคา", "Pricing counter categories are unavailable"),
    }
    return tr(*reasons[code]) if code in reasons else (code or "—")


def labeled_control(field, thai, english):
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    field_label(layout, field, thai, english)
    layout.addWidget(field)
    return host


class TechnicalDetails(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(tr("รายละเอียดทางเทคนิค", "Technical details"))
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.toggle)
        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        proof = QPlainTextEdit(text)
        proof.setReadOnly(True)
        proof.setObjectName("reviewTechnicalDetails")
        proof.setMaximumHeight(150)
        body.addWidget(proof)
        copy = QPushButton(tr("คัดลอกหลักฐาน", "Copy evidence"))
        copy.clicked.connect(self.copy_evidence)
        body.addWidget(copy, 0, Qt.AlignmentFlag.AlignRight)
        self.content.hide()
        self.toggle.toggled.connect(self.set_expanded)
        layout.addWidget(self.content)

    def copy_evidence(self):
        QApplication.clipboard().setText(self.text)

    def set_expanded(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


def technical_details(text, parent=None):
    return TechnicalDetails(text, parent)
