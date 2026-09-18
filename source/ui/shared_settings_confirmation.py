"""User-facing review for settings shared with the other computers."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from i18n import tr
from services.sync_schedule import load_schedule_windows


def _display(key, value):
    if key == "sync_schedule_windows":
        if not value:
            return tr("ใช้ตารางเดิมของระบบ", "Use the legacy system schedule")
        windows = load_schedule_windows(value)
        if windows == ():
            return tr("ปิดการอ่านอัตโนมัติ", "Automatic reading disabled")
        days = [tr(th, en) for th, en in zip(
            ("จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."),
            ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        )]
        return "\n".join(
            f"{window.label}: {window.start:%H:%M}–{window.end:%H:%M} "
            f"({', '.join(days[day] for day in sorted(window.weekdays))})\n"
            + tr("SNMP ทุก ", "SNMP every ")
            + (str(int(window.snmp_interval.total_seconds() // 60)) if window.snmp_interval else tr("รอบเดิม", "existing interval"))
            + tr(" นาที · Web ทุก ", " min · Web every ")
            + str(int(window.web_interval.total_seconds() // 60)) + tr(" นาที", " min")
            for window in windows or ()
        )
    return f"{value:g}%" if key == "waste_paper_pct" else str(value)


class SharedSettingsConfirmation(QDialog):
    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ยืนยันการตั้งค่าร่วม", "Confirm shared settings"))
        if "sync_schedule_windows" in preview.changes:
            self.resize(980, 620)
        else:
            self.resize(740, 300)
        layout = QVBoxLayout(self)
        notice = QLabel(tr(
            "การตั้งค่านี้มีผลกับคอมพิวเตอร์ทุกเครื่องในระบบ\n"
            "เครื่องที่ออฟไลน์จะรับเมื่อกลับมาเชื่อมต่อ และจะมีการบันทึกประวัติการเปลี่ยนแปลง",
            "These settings apply to every computer in the system.\n"
            "Offline computers receive them after reconnecting. This change will be recorded.",
        ))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        labels = {
            "billing_day": tr("วันตัดรอบบิล", "Billing day"),
            "waste_paper_pct": tr("ส่วนลดกระดาษเสีย", "Waste discount"),
            "sync_schedule_windows": tr("ตารางอ่านข้อมูล", "Reading schedule"),
        }
        self.table = QTableWidget(len(preview.changes), 3)
        self.table.setHorizontalHeaderLabels([
            tr("รายการ", "Setting"), tr("ค่าเดิม", "Previous"), tr("ค่าใหม่", "New"),
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().sectionResized.connect(self.table.resizeRowsToContents)
        for row, (key, (old, new)) in enumerate(preview.changes.items()):
            for column, text in enumerate((labels[key], _display(key, old), _display(key, new))):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("ยืนยันบันทึก", "Confirm save"))
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText(tr("ยกเลิก", "Cancel"))
        cancel.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)


def confirm_shared_settings(parent, preview):
    return SharedSettingsConfirmation(preview, parent).exec() == QDialog.DialogCode.Accepted
