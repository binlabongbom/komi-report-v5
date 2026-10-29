"""Pricing inputs, mode visibility and immutable draft values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_BILLING_DAY
from services.device_config import DeviceConfig
from ui.numeric_inputs import NumericDateEdit as QDateEdit
from ui.numeric_inputs import NumericDoubleSpinBox as QDoubleSpinBox
from ui.setup.appearance import style_price_calendar, style_wizard_combo
from ui.setup.controls import WizardComboBox
from ui.styles import setup as setup_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_TEXT2, F_LG, F_MD, F_XL
from widgets import fnt


@dataclass(frozen=True, slots=True)
class PriceRates:
    a4_color: float
    a4_bw: float
    a3_color: float
    a3_bw: float

    def as_dict(self) -> dict[str, float]:
        return {"a4_color": self.a4_color, "a4_bw": self.a4_bw, "a3_color": self.a3_color, "a3_bw": self.a3_bw}

    @property
    def is_zero(self) -> bool:
        return not any(self.as_dict().values())


@dataclass(frozen=True, slots=True)
class PricingSelection:
    mode: str
    effective_date: date
    shared: PriceRates
    by_slot: tuple[PriceRates, ...]
    discount: float
    billing_day: int

    def all_selected_rates_are_zero(self, selected_slots: tuple[int, ...]) -> bool:
        if self.mode == "deferred":
            return True
        rows = (self.shared,) if self.mode == "shared" else tuple(self.by_slot[slot] for slot in selected_slots)
        return all(row.is_zero for row in rows)


class PricingStep(QWidget):
    """Pricing and billing controls with local mode state and immutable draft values."""

    def __init__(self, *, edit_mode: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.edit_mode = edit_mode
        page = self
        page_layout = QVBoxLayout(page)
        # Keep the 980x620 wizard usable with taller platform font metrics;
        # reclaim whitespace rather than shrinking controls or hiding overflow.
        page_layout.setContentsMargins(0, 4, 0, 0)
        self.price_scroll = QScrollArea()
        self.price_scroll.setObjectName("wizard_price_scroll")
        self.price_scroll.setWidgetResizable(True)
        self.price_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.price_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.price_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        price_palette = QPalette(self.palette())
        price_palette.setColor(QPalette.ColorRole.Window, QColor("#F4F7FA"))
        price_palette.setColor(QPalette.ColorRole.Base, QColor("#F4F7FA"))
        price_palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
        self.price_scroll.setPalette(price_palette)
        self.price_scroll.viewport().setPalette(price_palette)
        self.price_scroll.viewport().setAutoFillBackground(True)
        self.price_scroll.setStyleSheet(setup_styles.PRICE_SCROLL)
        content = QWidget()
        content.setObjectName("wizard_price_content")
        content.setMaximumWidth(1280)
        content.setPalette(price_palette)
        content.setAutoFillBackground(True)
        content.setStyleSheet(setup_styles.SETUP_WIZARD_CONTENT_PRICE_PAGE)
        self.price_content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 2, 12, 6)
        layout.setSpacing(6)

        self.price_intro = QLabel("กำหนดราคาต่อหน้าสำหรับ A4/A3 สีและขาวดำ · ราคา 0.00 หมายถึงไม่คิดค่าใช้จ่าย")
        self.price_intro.setWordWrap(True)
        self.price_intro.setFont(fnt(F_MD))
        self.price_intro.setStyleSheet(text_styles.label(C_TEXT2, border="none", background="transparent"))

        mode_section = QFrame()
        mode_section.setObjectName("price_mode_section")
        mode_section.setStyleSheet(setup_styles.SETUP_WIZARD_MODE_SECTION)
        mode_layout = QVBoxLayout(mode_section)
        mode_layout.setContentsMargins(0, 2, 0, 2)
        mode_layout.setSpacing(6)
        mode_header = QHBoxLayout()
        mode_header.setSpacing(12)
        mode_title = QLabel("วิธีใช้ราคา")
        mode_title.setFont(fnt(F_LG, True))
        mode_title.setStyleSheet(text_styles.label("#172033", border="none", background="transparent"))
        mode_header.addWidget(mode_title)
        mode_header.addWidget(self.price_intro, 1)
        mode_layout.addLayout(mode_header)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        mode_row.addStretch()
        self.shared_price_mode = QPushButton("ใช้ราคาเดียวกันทุกเครื่อง")
        self.per_device_price_mode = QPushButton("ตั้งราคาแยกรายเครื่อง")
        self.deferred_price_mode = QPushButton("ตั้งค่าราคาภายหลัง")
        self.price_mode_group = QButtonGroup(self)
        self.price_mode_group.setExclusive(True)
        mode_style = setup_styles.PRICE_PAGE_MODE_STYLE
        for button in (
            self.shared_price_mode,
            self.per_device_price_mode,
            self.deferred_price_mode,
        ):
            button.setCheckable(True)
            button.setFont(fnt(F_MD, True))
            button.setStyleSheet(mode_style)
            button.setMinimumHeight(50)
            button.setMaximumWidth(480)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.price_mode_group.addButton(button)
        self.shared_price_mode.toggled.connect(self.refresh_mode)
        self.per_device_price_mode.toggled.connect(self.refresh_mode)
        self.deferred_price_mode.toggled.connect(self.refresh_mode)
        mode_row.addWidget(self.shared_price_mode)
        mode_row.addWidget(self.per_device_price_mode)
        mode_row.addWidget(self.deferred_price_mode)
        mode_row.addStretch()
        mode_layout.addLayout(mode_row)

        self.effective_row_widget = QWidget()
        effective_row = QHBoxLayout(self.effective_row_widget)
        effective_row.setContentsMargins(0, 2, 0, 0)
        effective_row.setSpacing(10)
        effective_label = QLabel("วันที่เริ่มใช้ราคาชุดนี้")
        effective_label.setStyleSheet(
            text_styles.label("#334155", font_weight="700", border="none", background="transparent")
        )
        effective_row.addWidget(effective_label)
        self.effective_date = QDateEdit(QDate.currentDate())
        self.effective_date.setCalendarPopup(True)
        self.effective_date.setDisplayFormat("dd/MM/yyyy")
        self.effective_date.setMinimumWidth(150)
        self.effective_date.setMaximumWidth(190)
        self.effective_date.setMinimumHeight(38)
        self.effective_date.setFont(fnt(F_MD, True))
        self.effective_date.setStyleSheet(setup_styles.SETUP_WIZARD_EFFECTIVE_DATE)
        style_price_calendar(self.effective_date.calendarWidget(), self.palette())
        effective_row.addWidget(self.effective_date)
        effective_hint = QLabel("รายการตั้งแต่วันนี้จะใช้ราคาชุดนี้")
        effective_hint.setStyleSheet(text_styles.label(C_TEXT2, border="none", background="transparent"))
        effective_row.addWidget(effective_hint)
        effective_row.addStretch()
        mode_layout.addWidget(self.effective_row_widget)
        layout.addWidget(mode_section)

        self.deferred_price_notice = QLabel(
            "<b>ยังไม่คิดค่าใช้จ่ายในขณะนี้</b><br>ระบบจะบันทึกราคา 0.00 ทุกประเภท และสามารถตั้งราคาจริงภายหลังได้จาก Settings"
        )
        self.deferred_price_notice.setWordWrap(True)
        self.deferred_price_notice.setStyleSheet(surfaces_styles.WARNING_BOX)
        self.deferred_price_notice.setVisible(False)
        layout.addWidget(self.deferred_price_notice)

        self.shared_price_box = QFrame()
        self.shared_price_box.setObjectName("shared_price_box")
        self.shared_price_box.setStyleSheet(setup_styles.SETUP_WIZARD_SHARED_PRICE_BOX)
        shared_layout = QVBoxLayout(self.shared_price_box)
        shared_layout.setContentsMargins(0, 2, 0, 4)
        shared_layout.setSpacing(5)
        shared_header = QHBoxLayout()
        shared_header.setSpacing(12)
        shared_title = QLabel("ราคาสำหรับทุกเครื่อง")
        shared_title.setFont(fnt(F_LG, True))
        shared_title.setStyleSheet(text_styles.label("#172033", border="none", background="transparent"))
        shared_header.addWidget(shared_title)
        shared_note = QLabel("หน่วย: บาทต่อหน้าที่พิมพ์ · ใส่ 0.00 สำหรับรายการที่ไม่คิดเงิน")
        shared_note.setStyleSheet(text_styles.label(C_TEXT2, border="none", background="transparent"))
        shared_header.addWidget(shared_note, 1)
        shared_layout.addLayout(shared_header)
        self.shared_price_row = self._price_inputs()
        shared_layout.addWidget(self._price_grid(self.shared_price_row))
        layout.addWidget(self.shared_price_box)

        self.per_device_price_box = QFrame()
        self.per_device_price_box.setObjectName("per_device_price_box")
        self.per_device_price_box.setStyleSheet(setup_styles.SETUP_WIZARD_PER_DEVICE_PRICE_BOX)
        device_layout = QVBoxLayout(self.per_device_price_box)
        device_layout.setContentsMargins(0, 14, 0, 12)
        device_layout.setSpacing(8)
        device_title = QLabel("ราคาแยกรายเครื่อง")
        device_title.setFont(fnt(F_XL, True))
        device_title.setStyleSheet(text_styles.label("#172033", border="none", background="transparent"))
        device_layout.addWidget(device_title)
        device_note = QLabel("กำหนด 4 ราคาของแต่ละเครื่องแยกกัน · แสดงเฉพาะเครื่องที่เลือกในขั้นแรก")
        device_note.setStyleSheet(text_styles.label(C_TEXT2, border="none", background="transparent"))
        device_layout.addWidget(device_note)
        self.price_rows: list[dict[str, QDoubleSpinBox]] = []
        self.device_price_cards: list[tuple[QFrame, QLabel]] = []
        for slot in range(3):
            card = QFrame()
            card.setObjectName(f"device_price_card_{slot}")
            card.setStyleSheet(setup_styles.device_price_card(slot))
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 14, 0, 14)
            card_layout.setSpacing(7)
            card_title = QLabel(f"เครื่อง {slot + 1}")
            card_title.setFont(fnt(F_MD, True))
            card_title.setStyleSheet(text_styles.label("#172033", border="none", background="transparent"))
            card_layout.addWidget(card_title)
            row = self._price_inputs()
            card_layout.addWidget(self._price_grid(row))
            self.price_rows.append(row)
            self.device_price_cards.append((card, card_title))
            device_layout.addWidget(card)
        layout.addWidget(self.per_device_price_box)

        self.billing_section = QFrame()
        self.billing_section.setObjectName("billing_section")
        self.billing_section.setStyleSheet(setup_styles.SETUP_WIZARD_BILLING_SECTION)
        billing_layout = QHBoxLayout(self.billing_section)
        billing_layout.setContentsMargins(0, 8, 0, 4)
        billing_layout.setSpacing(24)
        billing_copy = QVBoxLayout()
        billing_copy.setSpacing(3)
        billing_title = QLabel("รอบบิลและส่วนลด")
        billing_title.setFont(fnt(F_LG, True))
        billing_title.setStyleSheet(text_styles.label("#172033", border="none", background="transparent"))
        billing_copy.addWidget(billing_title)
        self.billing_defaults = QLabel("ค่าแนะนำ: กระดาษเสีย 2% · ตัดรอบวันที่ 31")
        self.billing_defaults.setWordWrap(True)
        self.billing_defaults.setStyleSheet(text_styles.label("#75510A", border="none", background="transparent"))
        billing_copy.addWidget(self.billing_defaults)
        billing_copy.addStretch()
        billing_layout.addLayout(billing_copy, 0)
        billing = QGridLayout()
        billing.setHorizontalSpacing(16)
        billing.setVerticalSpacing(4)
        self.waste_paper_pct = QDoubleSpinBox()
        self.waste_paper_pct.setRange(0, 100)
        from config import DEFAULT_WASTE_PCT
        self.waste_paper_pct.setValue(DEFAULT_WASTE_PCT)
        self.waste_paper_pct.setDecimals(1)
        self.waste_paper_pct.setSuffix(" %")
        from services.pricing import WASTE_QUANTITY_TOOLTIP
        self.waste_paper_pct.setToolTip(WASTE_QUANTITY_TOOLTIP)
        self.billing_end_day = WizardComboBox()
        self.billing_end_day.setProperty("i18n_items", True)
        for day in range(1, 32):
            self.billing_end_day.addItem(f"วันที่ {day} ของเดือน", day)
        billing_input_style = setup_styles.PRICE_PAGE_BILLING_INPUT_STYLE
        for spin in (self.waste_paper_pct, self.billing_end_day):
            spin.setMinimumHeight(38)
            spin.setMaximumWidth(300)
            spin.setFont(fnt(F_MD, True))
            spin.setStyleSheet(billing_input_style)
        self.waste_paper_pct.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        style_wizard_combo(self.billing_end_day, self.palette(), popup_width=260)
        waste_label = QLabel("ส่วนลดกระดาษเสีย")
        waste_label.setToolTip(WASTE_QUANTITY_TOOLTIP)
        waste_label.setStyleSheet(
            text_styles.label("#334155", font_weight="700", border="none", background="transparent")
        )
        billing_day_label = QLabel("วันสิ้นสุดรอบบิล")
        billing_day_label.setStyleSheet(
            text_styles.label("#334155", font_weight="700", border="none", background="transparent")
        )
        billing.addWidget(waste_label, 0, 0)
        billing.addWidget(billing_day_label, 0, 1)
        billing.addWidget(self.waste_paper_pct, 1, 0)
        billing.addWidget(self.billing_end_day, 1, 1)
        waste_hint = QLabel("หักเปอร์เซ็นต์นี้ออกจากยอดค่าใช้จ่ายรวม")
        waste_hint.setStyleSheet(text_styles.label(C_TEXT2, border="none", background="transparent"))
        billing_hint = QLabel("เดือนที่ไม่มีวันที่เลือก จะใช้วันสุดท้ายของเดือน")
        billing_hint.setStyleSheet(text_styles.label(C_TEXT2, border="none", background="transparent"))
        billing.addWidget(waste_hint, 2, 0)
        billing.addWidget(billing_hint, 2, 1)
        billing.setColumnStretch(0, 1)
        billing.setColumnStretch(1, 1)
        billing_layout.addLayout(billing, 1)
        layout.addWidget(self.billing_section)
        layout.addStretch()
        self.price_scroll.setWidget(content)
        page_layout.addWidget(self.price_scroll)

    @staticmethod
    def _price_inputs() -> dict[str, QDoubleSpinBox]:
        inputs: dict[str, QDoubleSpinBox] = {}
        for key in ("a4_color", "a4_bw", "a3_color", "a3_bw"):
            spin = QDoubleSpinBox()
            spin.setRange(0, 9999)
            spin.setDecimals(2)
            spin.setMinimumHeight(42)
            spin.setMinimumWidth(150)
            spin.setMaximumWidth(230)
            spin.setFont(fnt(F_LG, True))
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setStyleSheet(setup_styles.SETUP_WIZARD_SPIN)
            inputs[key] = spin
        return inputs

    @staticmethod
    def _price_cell(spin: QDoubleSpinBox) -> QWidget:
        """Keep the number field clear; the unit belongs beside it, not inside it."""
        cell = QWidget()
        cell.setObjectName("price_value_cell")
        cell.setStyleSheet(setup_styles.SETUP_WIZARD_CELL)
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(10, 4, 10, 4)
        cell_layout.setSpacing(8)
        cell_layout.addStretch()
        cell_layout.addWidget(spin)
        unit = QLabel("บาท/หน้า")
        unit.setStyleSheet(text_styles.label("#475569", font_weight="700", border="none", background="transparent"))
        unit.setMinimumWidth(66)
        cell_layout.addWidget(unit)
        cell_layout.addStretch()
        return cell

    @staticmethod
    def _price_grid(inputs: dict[str, QDoubleSpinBox]) -> QFrame:
        matrix = QFrame()
        matrix.setObjectName("price_matrix")
        matrix.setStyleSheet(setup_styles.SETUP_WIZARD_MATRIX)
        grid = QGridLayout(matrix)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
        headers = ("ขนาดกระดาษ", "สี (Color)", "ขาวดำ (B&W)")
        for column, text in enumerate(headers):
            header = QLabel(text)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setMinimumHeight(34)
            if column == 1:
                background = "#E5F5FA"
                color = "#087A96"
            elif column == 2:
                background = "#EEF1F4"
                color = "#334155"
            else:
                background = "#F1F5F9"
                color = "#334155"
            header.setStyleSheet(
                text_styles.label(color, background=background, border="none", padding="4px 8px", font_weight="800")
            )
            grid.addWidget(header, 0, column)
        for row, size in enumerate(("A4", "A3"), start=1):
            size_label = QLabel(size)
            size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            size_label.setMinimumWidth(110)
            size_label.setMinimumHeight(52)
            size_label.setStyleSheet(
                text_styles.label("#172033", background="#F8FAFC", border="none", padding="6px 10px", font_weight="800")
            )
            grid.addWidget(size_label, row, 0)
        grid.addWidget(PricingStep._price_cell(inputs["a4_color"]), 1, 1)
        grid.addWidget(PricingStep._price_cell(inputs["a4_bw"]), 1, 2)
        grid.addWidget(PricingStep._price_cell(inputs["a3_color"]), 2, 1)
        grid.addWidget(PricingStep._price_cell(inputs["a3_bw"]), 2, 2)
        grid.setColumnMinimumWidth(0, 110)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        return matrix

    def refresh_mode(self, _checked: bool = False) -> None:
        deferred = self.deferred_price_mode.isChecked()
        shared = self.shared_price_mode.isChecked() and not deferred
        per_device = self.per_device_price_mode.isChecked() and not deferred
        self.shared_price_box.setVisible(shared)
        self.per_device_price_box.setVisible(per_device)
        self.deferred_price_notice.setVisible(deferred)
        self.effective_row_widget.setVisible(not deferred)
        show_billing = not deferred and not self.edit_mode
        self.billing_section.setVisible(show_billing)
        self.billing_defaults.setVisible(show_billing)

    def set_devices(self, devices: list[DeviceConfig]) -> None:
        selected = {device.slot: device for device in devices}
        for slot, (card, title) in enumerate(self.device_price_cards):
            device = selected.get(slot)
            card.setVisible(device is not None)
            if device is not None:
                title.setText(f"{device.name} · ราคาเฉพาะเครื่อง")

    def selection(self) -> PricingSelection:
        """Read one immutable draft for validation, review and persistence."""
        mode = (
            "deferred"
            if self.deferred_price_mode.isChecked()
            else ("shared" if self.shared_price_mode.isChecked() else "per_device")
        )

        def rates(inputs):
            return PriceRates(**{key: control.value() for key, control in inputs.items()})

        return PricingSelection(
            mode=mode,
            effective_date=self.effective_date.date().toPyDate(),
            shared=rates(self.shared_price_row),
            by_slot=tuple(rates(row) for row in self.price_rows),
            discount=self.waste_paper_pct.value(),
            billing_day=int(self.billing_end_day.currentData() or DEFAULT_BILLING_DAY),
        )
