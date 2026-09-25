"""Isolated five-step preview; the proposed MeterStep precedes real PricingStep.

Reads and saves are simulated. Production SetupWizardV5, enrollment and
persistence are never invoked. Launch via tools/setup_baseline_preview.py.
"""
from pathlib import Path
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from tools.previews.meter_step import MeterStep
from ui.setup.steps.pricing import PricingStep
from ui.styles.setup import SETUP_PANEL
from ui.styles.tokens import DEFAULT_FONT_NAME, F_MD


TITLE = "KOMI · ตัวอย่าง Wizard มิเตอร์เริ่มต้น"
STEPS = ("องค์กร", "เครื่องพิมพ์", "มิเตอร์เริ่มต้น", "ราคา", "ตรวจสอบ")


def label(text, kind=""):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    result.setObjectName(kind)
    return result


def button(text, callback, primary=False):
    result = QPushButton(text)
    result.setObjectName("btn_primary" if primary else "btn_outline")
    result.setAutoDefault(False)
    result.clicked.connect(callback)
    return result


def card(title, subtitle=""):
    frame = QFrame()
    frame.setObjectName("preview_card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(12)
    layout.addWidget(label(title, "section_title"))
    if subtitle:
        layout.addWidget(label(subtitle, "muted"))
    return frame, layout


class SetupBaselinePreview(QDialog):
    def __init__(self):
        super().__init__()
        self.setObjectName("setup_wizard_v5")
        self.setWindowTitle(TITLE)
        self.setStyleSheet(SETUP_PANEL + Path(__file__).with_suffix(".qss").read_text(encoding="utf-8"))
        self.setMinimumSize(850, 630)
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1120, area.width() - 50), min(790, area.height() - 50))
        self.step = 0
        self.busy = False
        self.read_complete = False
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        header = QHBoxLayout()
        self.title = label("ข้อมูลองค์กร", "page_title")
        header.addWidget(self.title, 1)
        header.addWidget(label("ตัวอย่าง · ข้อมูลจำลอง", "badge"))
        self.count = label("1 / 5", "section_title")
        header.addWidget(self.count)
        root.addLayout(header)
        root.addWidget(label("ตัวอย่างแทรกขั้นมิเตอร์ใน Wizard หลัก · ไม่มีการเชื่อมเครื่องหรือบันทึกข้อมูลจริง", "muted"))
        steps = QHBoxLayout()
        self.steps = []
        for text in STEPS:
            item = label(text, "step")
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            steps.addWidget(item, 1)
            self.steps.append(item)
        root.addLayout(steps)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self._company_page()
        self._device_page()
        self.meter = MeterStep(self)
        self.pages.addWidget(self.meter)
        self.meter.readiness_changed.connect(lambda _ready: self.sync_navigation())
        # The exact pricing component used by the main Wizard, created once.
        self.pricing = PricingStep(edit_mode=True, parent=self)
        self.pricing.set_devices(list(self.meter.devices))
        for row in [self.pricing.shared_price_row, *self.pricing.price_rows]:
            for key, field in row.items():
                field.setValue(2.0 if "color" in key else 0.2)
        self.pricing.shared_price_mode.setChecked(True)
        self.pricing.refresh_mode()
        self.pages.addWidget(self.pricing)
        self._review_page()
        footer = QHBoxLayout()
        footer.addWidget(button("ปิดตัวอย่าง", self.close))
        self.note = label("", "muted")
        footer.addWidget(self.note, 1)
        self.back = button("← ย้อนกลับ", lambda: self.go(self.step - 1))
        footer.addWidget(self.back)
        self.next = button("ถัดไป →", self.advance, True)
        footer.addWidget(self.next)
        root.addLayout(footer)
        self.go(0)

    def page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 4, 0)
        layout.setSpacing(12)
        scroll.setWidget(widget)
        self.pages.addWidget(scroll)
        return layout

    def _company_page(self):
        layout = self.page()
        panel, content = card("ข้อมูลองค์กร", "ตำแหน่งหน้าแรกของ Wizard หลัก")
        form = QFormLayout()
        self.company = QLineEdit("บริษัท ตัวอย่าง จำกัด")
        self.company.setAccessibleName("ชื่อบริษัทตัวอย่าง")
        self.company.textChanged.connect(lambda _text: self.sync_navigation())
        form.addRow("ชื่อบริษัท", self.company)
        content.addLayout(form)
        content.addWidget(label("กดถัดไปเพื่อจำลองการเลือกและตรวจเครื่องพิมพ์", "notice"))
        layout.addWidget(panel)
        layout.addStretch()

    def _device_page(self):
        layout = self.page()
        panel, content = card("เครื่องพิมพ์ที่เลือก", "ตัวอย่างนี้จำลองว่าเลือกครบ 3 เครื่องแล้ว")
        content.addWidget(label("Slot 1 · KM bizhub C450i Test    —    ใช้ฐานเดิม\n"
                                "Slot 2 · KM bizhub C750i 2222    —    ใช้ฐานเดิม\n"
                                "Slot 3 · KM bizhub C450i DMS    —    รอสร้างฐานเริ่มต้น"))
        self.test_button = button("ทดสอบการเชื่อมต่อทั้ง 3 เครื่อง (จำลอง)", self.start_read, True)
        content.addWidget(self.test_button)
        self.status = label("ยังไม่ได้ทดสอบ", "notice")
        content.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        content.addWidget(self.progress)
        layout.addWidget(panel)
        layout.addStretch()

    def _review_page(self):
        layout = self.page()
        panel, content = card("ตรวจสอบก่อนบันทึก", "หน้าสรุปท้าย Wizard หลังตั้งราคาเพียงครั้งเดียว")
        self.review = label("")
        content.addWidget(self.review)
        self.result = label("", "notice")
        content.addWidget(self.result)
        layout.addWidget(panel)
        layout.addStretch()

    def sync_navigation(self):
        if not hasattr(self, "next"):
            return
        allowed = (bool(self.company.text().strip()) if self.step == 0 else
                   self.read_complete if self.step == 1 else self.meter.ready)
        self.next.setEnabled(allowed and not self.busy)
        self.back.setEnabled(self.step > 0 and not self.busy)

    def start_read(self):
        if self.busy:
            return
        self.busy = True
        self.read_complete = False
        self.meter.reset_readings()
        self.test_button.setEnabled(False)
        self.status.setText("กำลังจำลองการตรวจ Serial และอ่าน Meter ของทั้ง 3 เครื่อง…")
        self.progress.setRange(0, 0)
        self.sync_navigation()
        QTimer.singleShot(850, self.finish_read)

    def finish_read(self):
        self.busy = False
        self.read_complete = True
        self.test_button.setEnabled(True)
        self.status.setText("ทั้ง 3 เครื่องอ่านสำเร็จ (จำลอง) · ไปตรวจมิเตอร์ก่อนตั้งราคา")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.go(2)

    def go(self, step):
        self.step = max(0, min(4, step))
        self.pages.setCurrentIndex(self.step)
        self.title.setText(("ข้อมูลองค์กร", "เครื่องพิมพ์", "มิเตอร์เริ่มต้น", "ตั้งค่าราคา", "ตรวจสอบและบันทึก")[self.step])
        self.count.setText(f"{self.step + 1} / 5")
        for index, item in enumerate(self.steps):
            item.setProperty("active", index == self.step)
            item.style().unpolish(item)
            item.style().polish(item)
        self.note.setText(("ขั้นที่ 1: กรอกชื่อบริษัท", "ขั้นที่ 2: เลือกและตรวจเครื่องพิมพ์",
                           "ขั้นที่ 3: ตรวจ Meter / Parser และยืนยันฐานเครื่องใหม่",
                           "ขั้นที่ 4: ใช้หน้าตั้งราคาจาก Wizard หลัก", "ขั้นที่ 5: ตรวจสอบก่อนทดลองบันทึก")[self.step])
        self.next.setText(("ถัดไป →", "ตรวจมิเตอร์เริ่มต้น →", "ไปหน้าราคา →",
                           "ตรวจสอบการตั้งค่า →", "ทดลองบันทึก")[self.step])
        if self.step == 4:
            selection = self.pricing.selection()
            mode = {"shared": "ใช้ราคาเดียวกันทุกเครื่อง", "per_device": "ตั้งราคาแยกรายเครื่อง", "deferred": "ตั้งค่าราคาภายหลัง"}[selection.mode]
            rates = ""
            if selection.mode != "deferred":
                selected_rates = [("ทุกเครื่อง", selection.shared)] if selection.mode == "shared" else [
                    (f"Slot {d.slot + 1}", selection.by_slot[d.slot]) for d in self.meter.devices]
                rates = "\n" + "\n".join(f"{name}: A4 Color {r.a4_color:.2f} · A4 B&W {r.a4_bw:.2f} · A3 Color {r.a3_color:.2f} · A3 B&W {r.a3_bw:.2f}"
                                         for name, r in selected_rates)
            self.review.setText(f"{self.company.text()}\n\n" + "\n".join(self.meter.summary_lines()) +
                                f"\n\nราคา: {mode}{rates}\nวันที่เริ่มใช้ราคา {selection.effective_date:%d/%m/%Y}")
            self.result.setText("ตัวอย่างเท่านั้น · การบันทึกจริงยังไม่เชื่อมต่อในชุดนี้")
        self.sync_navigation()

    def advance(self):
        if not self.next.isEnabled():
            return
        if self.step < 4:
            self.go(self.step + 1)
        else:
            self.result.setText("ทดลองสำเร็จ · ยืนยันฐานเครื่องใหม่และราคาในขั้นตอนเดียว\nไม่มีการบันทึกข้อมูลจริง")
            self.next.setEnabled(False)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(DEFAULT_FONT_NAME, F_MD))
    preview = SetupBaselinePreview()
    preview.show()
    preview.raise_()
    preview.activateWindow()
    return app.exec()
