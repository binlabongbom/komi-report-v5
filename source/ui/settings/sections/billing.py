"""Billing settings controls, serialization, and save verification."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
)

from database import get_cfg
from i18n import tr
from ui.numeric_inputs import NumericDoubleSpinBox as QDoubleSpinBox
from ui.numeric_inputs import NumericSpinBox as QSpinBox
from ui.settings.sections.common import editor_actions, field
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles


class BillingSection:
    """Billing controls and draft verification, independent of page navigation."""

    def __init__(
        self,
        editor: QFrame,
        *,
        on_save: Callable[[], None],
        on_cancel: Callable[[], None],
        on_dirty: Callable[[], None],
    ) -> None:
        billing_body = editor.layout()
        billing_grid = QGridLayout()
        billing_grid.setHorizontalSpacing(24)
        billing_grid.setVerticalSpacing(10)
        billing_grid.setColumnStretch(0, 1)
        billing_grid.setColumnStretch(1, 1)
        self.billing_day = QSpinBox()
        self.billing_day.setRange(1, 31)
        self.billing_day.setSuffix(" ของเดือน")
        self.billing_day.setAccessibleName("วันสิ้นสุดรอบบิล")
        self.waste = QDoubleSpinBox()
        self.waste.setRange(0, 100)
        self.waste.setDecimals(1)
        self.waste.setSuffix(" %")
        self.waste.setAccessibleName("ส่วนลดกระดาษเสีย")
        billing_grid.addWidget(
            field("วันสิ้นสุดรอบบิล", self.billing_day, "ถ้าเดือนไม่มีวันที่เลือก ระบบใช้วันสุดท้ายของเดือน"),
            0,
            0,
        )
        billing_grid.addWidget(
            field("ส่วนลดกระดาษเสีย", self.waste, "หักออกจากยอดค่าใช้จ่ายก่อนสรุปรอบบิล"),
            0,
            1,
        )
        billing_body.addLayout(billing_grid)
        billing_impact = QLabel("การเปลี่ยนแปลงมีผลกับรายการใหม่เท่านั้น และไม่แก้ยอดย้อนหลัง")
        billing_impact.setWordWrap(True)
        billing_impact.setStyleSheet(settings_styles.FLEET_SETTINGS_BILLING_IMPACT)
        billing_body.addWidget(billing_impact)
        (
            self.billing_save_status,
            billing_actions,
            self.billing_save_button,
        ) = editor_actions(
            "บันทึกรอบบิลและตรวจสอบ",
            on_save,
            on_cancel,
        )
        billing_body.addLayout(billing_actions)

        for control in (self.billing_day, self.waste):
            control.valueChanged.connect(lambda _value: on_dirty())

    def values(self) -> dict[str, int | float]:
        return {"billing_day": self.billing_day.value(), "waste_paper_pct": round(self.waste.value(), 1)}

    def save(self, commit: Callable[[dict], bool]) -> bool:
        """Review/commit through the owner, then verify persisted values."""
        expected = self.values()
        if not commit(expected):
            return False
        stored = {
            "billing_day": int(get_cfg("billing_day", "31") or 31),
            "waste_paper_pct": float(get_cfg("waste_paper_pct", "2") or 2),
        }
        if stored != self.values():
            self.billing_save_status.setText(tr("บันทึกรอบบิลไม่สำเร็จ", "Could not save billing settings"))
            self.billing_save_status.setStyleSheet(text_styles.label("#B42318", font_weight="700", border="none"))
            return False
        return True
