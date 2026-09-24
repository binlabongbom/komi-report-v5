"""Review cards rendered from an explicit setup data snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from services.registration_envelope import normalize_device_models
from ui.setup.steps.pricing import PriceRates, PricingSelection
from ui.styles import setup as setup_styles
from ui.styles import text as text_styles
from ui.styles.tokens import F_LG, F_MD, F_XL
from widgets import btn, fnt


@dataclass(frozen=True, slots=True)
class ReviewDevice:
    slot: int
    name: str
    model: str
    total: float | int | None


@dataclass(frozen=True, slots=True)
class SetupReviewData:
    company_name: str
    first_started: str
    version: str
    devices: tuple[ReviewDevice, ...]
    pricing: PricingSelection
    edit_mode: bool
    offline_edition: bool
    platform: tuple[str, str]


def format_price_rates(rates: PriceRates) -> str:
    return tr(
        "A4 สี <b>{a4_color:,.2f}</b> · A4 ขาวดำ <b>{a4_bw:,.2f}</b> · "
        "A3 สี <b>{a3_color:,.2f}</b> · A3 ขาวดำ <b>{a3_bw:,.2f}</b> บาท/หน้า",
        "A4 color <b>{a4_color:,.2f}</b> · A4 B&W <b>{a4_bw:,.2f}</b> · "
        "A3 color <b>{a3_color:,.2f}</b> · A3 B&W <b>{a3_bw:,.2f}</b> THB/page",
    ).format(**rates.as_dict())


class ReviewStep(QWidget):
    """Review presentation driven by a snapshot, without reading wizard controls."""

    edit_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        page = self
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        title = QLabel("ตรวจสอบทีละส่วนก่อนบันทึก")
        title.setFont(fnt(F_XL, True))
        layout.addWidget(title)

        review_scroll = QScrollArea()
        review_scroll.setWidgetResizable(True)
        review_scroll.setFrameShape(QFrame.Shape.NoFrame)
        review_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        review_panel = QFrame()
        review_panel.setObjectName("setup_review_panel")
        review_panel.setStyleSheet(setup_styles.SETUP_WIZARD_REVIEW_PANEL)
        panel_layout = QVBoxLayout(review_panel)
        panel_layout.setContentsMargins(18, 8, 18, 8)
        panel_layout.setSpacing(0)
        self.review_sections: dict[str, QLabel] = {}
        for key, section_title, target_step in (
            ("organization", "องค์กร", 0),
            ("devices", "เครื่องพิมพ์", 1),
            ("pricing", "ราคา", 2),
            ("billing", "รอบบิล", 2),
            ("registration", "ข้อมูลลงทะเบียน", None),
        ):
            section = QFrame()
            section.setStyleSheet(setup_styles.SETUP_WIZARD_SECTION)
            section_layout = QHBoxLayout(section)
            section_layout.setContentsMargins(2, 7, 2, 7)
            copy = QVBoxLayout()
            copy.setSpacing(3)
            heading = QLabel(f"✓  {section_title}")
            heading.setFont(fnt(F_MD, True))
            heading.setStyleSheet(text_styles.label("#176B49", border="none"))
            body = QLabel("")
            # These summaries combine translated templates with customer data.
            body.setProperty("i18n_data", True)
            body.setWordWrap(True)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            body.setStyleSheet(text_styles.label("#334155", border="none"))
            copy.addWidget(heading)
            copy.addWidget(body)
            section_layout.addLayout(copy, 1)
            if target_step is None:
                self.registration_status_label = QLabel("ยังไม่ส่ง")
                self.registration_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.registration_status_label.setFixedSize(86, 32)
                self.registration_status_label.setStyleSheet(setup_styles.SETUP_WIZARD_REGISTRATION_STATUS_LABEL)
                section_layout.addWidget(self.registration_status_label, 0, Qt.AlignmentFlag.AlignTop)
            else:
                edit = btn("แก้ไข", "outline")
                edit.setFixedSize(78, 36)
                edit.setAccessibleName(f"แก้ไข{section_title}")
                edit.clicked.connect(lambda _checked=False, step=target_step: self.edit_requested.emit(step))
                section_layout.addWidget(edit, 0, Qt.AlignmentFlag.AlignTop)
            panel_layout.addWidget(section)
            self.review_sections[key] = body
        review_scroll.setWidget(review_panel)
        layout.addWidget(review_scroll, 1)

        self.review_ready_note = QLabel(
            "<b>พร้อมนำเครื่องพิมพ์เข้าระบบ</b><br>เมื่อกดบันทึก ระบบจะเก็บการตั้งค่าในเครื่องและเริ่มตรวจมิเตอร์ตามรอบที่กำหนด"
        )
        self.review_ready_note.setWordWrap(True)
        self.review_ready_note.setFont(fnt(F_LG))
        self.review_ready_note.setStyleSheet(setup_styles.SETUP_WIZARD_REVIEW_READY_NOTE)
        layout.addWidget(self.review_ready_note)

    def render(self, data: SetupReviewData) -> None:
        devices = data.devices
        shared = data.pricing.mode == "shared"
        deferred = data.pricing.mode == "deferred"
        company = escape(data.company_name.strip())
        self.review_sections["organization"].setText(
            tr(
                "<b>{company}</b> · เริ่มใช้งาน {started} · Version {version}",
                "<b>{company}</b> · Started {started} · Version {version}",
            ).format(company=company, started=escape(data.first_started), version=escape(data.version))
        )
        device_lines: list[str] = []
        for device in devices:
            meter = device.total
            meter_text = f"{meter:,.0f}" if isinstance(meter, (int, float)) else "—"
            device_lines.append(
                tr(
                    "<b>{name}</b> · {model} · พร้อมใช้งาน · Meter {meter}",
                    "<b>{name}</b> · {model} · Ready · Meter {meter}",
                ).format(
                    name=escape(device.name),
                    model=escape(device.model or tr("ไม่ทราบรุ่น", "Unknown model")),
                    meter=meter_text,
                )
            )
        self.review_sections["devices"].setText("<br>".join(device_lines))

        if deferred:
            pricing_text = tr(
                "<b>ตั้งค่าภายหลัง</b> · ขณะนี้ราคา 0.00 ทุกประเภทและยังไม่คิดค่าใช้จ่าย",
                "<b>Set up later</b> · All rates are currently 0.00; no charges are calculated",
            )
        elif shared:
            pricing_text = (
                tr("<b>ใช้ราคาเดียวกันทุกเครื่อง</b> · เริ่มใช้ ", "<b>One price list for all printers</b> · Effective ")
                + f"{data.pricing.effective_date.strftime('%d/%m/%Y')}<br>"
                f"{format_price_rates(data.pricing.shared)}"
            )
        else:
            price_lines = [
                tr("<b>ราคาแยกรายเครื่อง</b> · เริ่มใช้ ", "<b>Price list by printer</b> · Effective ")
                + f"{data.pricing.effective_date.strftime('%d/%m/%Y')}"
            ]
            for device in devices:
                price_lines.append(f"{escape(device.name)}: {format_price_rates(data.pricing.by_slot[device.slot])}")
            pricing_text = "<br>".join(price_lines)
        self.review_sections["pricing"].setText(pricing_text)

        if data.edit_mode:
            billing_text = tr(
                "รอบบิลและส่วนลดจัดการจากหน้า Settings โดยไม่เปลี่ยนตาม Wizard นี้",
                "Manage the billing cycle and discount in Settings; this wizard keeps them unchanged.",
            )
        elif deferred:
            billing_text = tr(
                "ยังไม่เริ่มคิดค่าใช้จ่าย · ตั้งราคาและรอบบิลภายหลังได้จาก Settings",
                "Billing has not started. Set prices and the billing cycle later in Settings.",
            )
        else:
            billing_text = tr(
                "ส่วนลดกระดาษเสีย {discount:g}% · สิ้นสุดรอบวันที่ {day} ของเดือน",
                "Waste-paper discount {discount:g}% · Billing ends on day {day} of each month",
            ).format(discount=data.pricing.discount, day=data.pricing.billing_day)
        self.review_sections["billing"].setText(billing_text)
        platform_name, architecture = data.platform
        if platform_name == "Darwin":
            platform_name = "macOS"
        model_rows = normalize_device_models(device.model for device in devices)
        model_text = ", ".join(f"{escape(str(row['model']))} × {row['quantity']}" for row in model_rows) or "—"
        if data.offline_edition:
            delivery_copy = (
                f"<b>{tr('Offline Installation:', 'Offline Installation:')}</b> "
                f"{tr('ใช้งานได้หลังตั้งค่าเสร็จโดยไม่ติดต่อ Host และไม่ต้องใช้ไฟล์ License', 'works after local setup without contacting the Host or importing a license file')}<br>"
            )
        else:
            delivery_copy = (
                f"<b>{tr('Online Registration:', 'Online Registration:')}</b> "
                f"{tr('ระบบจะลงทะเบียนก่อนเปิดโปรแกรม และส่ง Status กับ Aggregate Total Meter ทุก 6 ชั่วโมงโดยประมาณ', 'the app registers before opening and sends Status and aggregate Total Meter about every 6 hours')}<br>"
            )
        data_heading = (
            f"<b>{tr('ข้อมูลอยู่ภายในเครื่อง:', 'Data stays on this computer:')}</b> "
            if data.offline_edition
            else f"<b>{tr('ข้อมูลที่อนุญาตเมื่อใช้ Online:', 'Allowed data in Online mode:')}</b> "
        )
        closing_copy = (
            f"<b>{tr('การทำงาน:', 'Operation:')}</b> "
            f"{tr('อ่าน SNMP, Web Connection, สร้างรายงาน และเปิด Web Report ใน LAN ได้ตามปกติ', 'SNMP, Web Connection, reports, and LAN Web Report remain available normally')}"
            if data.offline_edition
            else f"<b>{tr('การแจ้งเตือน:', 'Alerts:')}</b> "
            f"{tr('Host อาจแจ้งว่า Desktop ขาดการเชื่อมต่อหลัง 3 วัน; ข้อความนี้ไม่ใช่หลักฐานว่าเครื่องพิมพ์เสีย', 'the Host may report Desktop connectivity loss after 3 days; this is not proof of a printer fault')}"
        )
        self.review_sections["registration"].setText(
            delivery_copy
            + data_heading
            + f"{tr('ชื่อบริษัท:', 'Company:')} {company} · Version {escape(data.version)} · "
            + f"{escape(platform_name)} / {escape(architecture)} · "
            + f"{tr('Serial Number + รุ่นเครื่อง + สถานะเลือกใช้ + Aggregate Total Meter', 'serial number + printer model + selected state + aggregate Total Meter')} "
            + f"({model_text})<br>"
            + f"<b>{tr('ไม่ส่ง:', 'Never sent:')}</b> "
            + f"{tr('IP, MAC, hostname, Credential, Counter รายละเอียด, ผู้ใช้, เอกสาร, Print Job, Raw SNMP/XML/Error หรือ Log', 'IP, MAC, hostname, credentials, detailed counters, users, documents, print jobs, raw SNMP/XML/errors, or logs')}<br>"
            + closing_copy
        )
        self.registration_status_label.setText(
            tr("พร้อมใช้แบบ Offline", "Offline ready") if data.offline_edition else tr("รอลงทะเบียน", "Pending")
        )
