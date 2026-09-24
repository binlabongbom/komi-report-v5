"""Organization form and inline name validation."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import PACKAGE_VERSION
from i18n import tr
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION
from ui.numeric_inputs import NumericSpinBox as QSpinBox
from ui.styles import setup as setup_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_TEXT2, F_LG, F_MD, F_XL
from widgets import btn, fnt


class CompanyStep(QWidget):
    """Organization inputs and local validation; external work is requested by signals."""

    primary_search_requested = pyqtSignal()
    primary_join_requested = pyqtSignal()
    primary_port_changed = pyqtSignal(int)
    primary_options_requested = pyqtSignal()
    database_path_requested = pyqtSignal()
    legacy_import_requested = pyqtSignal()
    privacy_notice_requested = pyqtSignal()

    def __init__(self, database_path: Path, *, lab_mode: bool = False, parent=None) -> None:
        super().__init__(parent)
        page = self
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.company_scroll = QScrollArea()
        self.company_scroll.setWidgetResizable(True)
        self.company_scroll.setMinimumSize(0, 0)
        self.company_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.company_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.company_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.company_scroll.setStyleSheet(setup_styles.SETUP_WIZARD_COMPANY_SCROLL)
        content = QWidget()
        content.setObjectName("company_setup_content")
        content.setStyleSheet(setup_styles.SETUP_WIZARD_CONTENT)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(14)

        intro = QLabel("ข้อมูลสำหรับเริ่มใช้งาน")
        intro.setFont(fnt(F_XL, True))
        intro.setStyleSheet(text_styles.label("#123262"))
        layout.addWidget(intro)
        description = QLabel(
            "ระบุชื่อบริษัทสำหรับแสดงในรายงานและการลงทะเบียนโปรแกรม ส่วนวันที่เริ่มใช้และ Version ระบบกำหนดให้เพื่อป้องกันข้อมูลผิด"
        )
        description.setWordWrap(True)
        description.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(description)

        self.secondary_join_card = QFrame()
        self.secondary_join_card.setObjectName("secondary_join_card")
        self.secondary_join_card.setFixedWidth(760)
        self.secondary_join_card.setStyleSheet(setup_styles.SETUP_WIZARD_SECONDARY_JOIN_CARD)
        secondary_layout = QVBoxLayout(self.secondary_join_card)
        secondary_layout.setContentsMargins(14, 11, 14, 11)
        secondary_top = QHBoxLayout()
        secondary_copy = QVBoxLayout()
        self.secondary_join_title = QLabel("มี KOMI Report เครื่องหลักอยู่แล้ว?")
        self.secondary_join_title.setFont(fnt(F_MD, True))
        self.secondary_join_status = QLabel("ค้นหาใน LAN แล้วดึงเฉพาะบริษัท เครื่องพิมพ์ ราคา และรอบบิล · ไม่คัดลอกรหัสผ่านหรือประวัติ")
        self.secondary_join_status.setWordWrap(True)
        self.secondary_join_status.setStyleSheet(text_styles.label("#52677D"))
        secondary_copy.addWidget(self.secondary_join_title)
        secondary_copy.addWidget(self.secondary_join_status)
        secondary_top.addLayout(secondary_copy, 1)
        self.secondary_join_button = btn("ค้นหาเครื่องหลัก", "outline")
        self.secondary_join_button.setAccessibleName("ค้นหา KOMI Report เครื่องหลักใน LAN")
        self.secondary_join_button.clicked.connect(self.primary_search_requested)
        secondary_top.addWidget(self.secondary_join_button)
        secondary_layout.addLayout(secondary_top)
        self.secondary_manual_row = QWidget()
        manual_primary_row = QHBoxLayout(self.secondary_manual_row)
        manual_primary_row.setContentsMargins(0, 0, 0, 0)
        manual_primary_label = QLabel(tr("หรือระบุ Primary IP", "Or enter Primary IP"))
        manual_primary_label.setStyleSheet(text_styles.label("#52677D", font_weight="650"))
        manual_primary_row.addWidget(manual_primary_label)
        self.secondary_manual_ip = QLineEdit()
        self.secondary_manual_ip.setObjectName("secondary_manual_primary_ip")
        self.secondary_manual_ip.setPlaceholderText("192.168.1.10")
        self.secondary_manual_ip.setAccessibleName(tr("Primary IP สำหรับ Sync การตั้งค่า", "Primary IP for setup sync"))
        self.secondary_manual_ip.setMaximumWidth(190)
        self.secondary_manual_ip.returnPressed.connect(self.primary_join_requested)
        manual_primary_row.addWidget(self.secondary_manual_ip)
        manual_primary_row.addWidget(QLabel("Port"))
        self.secondary_primary_port = QSpinBox()
        self.secondary_primary_port.setRange(1024, 65535)
        self.secondary_primary_port.setValue(3000)
        self.secondary_primary_port.setMaximumWidth(100)
        self.secondary_primary_port.setAccessibleName("Port ของเครื่อง Primary")
        self.secondary_primary_port.valueChanged.connect(self.primary_port_changed)
        manual_primary_row.addWidget(self.secondary_primary_port)
        self.secondary_manual_button = btn(tr("เชื่อมต่อ", "Connect"), "outline")
        self.secondary_manual_button.setAccessibleName(tr("ค้นหาเครื่องหลักตาม Primary IP", "Find Primary at this IP"))
        self.secondary_manual_button.clicked.connect(self.primary_join_requested)
        manual_primary_row.addWidget(self.secondary_manual_button)
        manual_primary_row.addStretch()
        secondary_layout.addWidget(self.secondary_manual_row)
        layout.addWidget(self.secondary_join_card, 0, Qt.AlignmentFlag.AlignHCenter)
        self.secondary_join_card.setVisible(False)

        self.company_card = QFrame()
        self.company_card.setObjectName("company_setup_card")
        self.company_card.setFixedWidth(760)
        self.company_card.setStyleSheet(setup_styles.SETUP_WIZARD_COMPANY_CARD)
        self.company_form = QFormLayout(self.company_card)
        self.company_form.setContentsMargins(24, 22, 24, 22)
        self.company_form.setHorizontalSpacing(18)
        self.company_form.setVerticalSpacing(14)
        self.company_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.company_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.company_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.company_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.company_name_input = QLineEdit()
        self.company_name_input.setObjectName("company_name_input")
        self.company_name_input.setPlaceholderText("เช่น บริษัท ตัวอย่าง จำกัด")
        self.company_name_input.setMaxLength(160)
        self.company_name_input.setMinimumHeight(44)
        self.company_name_input.setMinimumWidth(470)
        self.company_name_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.company_name_input.setFont(fnt(F_LG))
        self._company_name_normal_style = setup_styles.COMPANY_PAGE_COMPANY_NAME_NORMAL_STYLE
        self._company_name_error_style = setup_styles.COMPANY_PAGE_COMPANY_NAME_ERROR_STYLE
        self.company_name_input.setStyleSheet(self._company_name_normal_style)
        self.company_name_error = QLabel("กรุณากรอกชื่อบริษัท")
        self.company_name_error.setObjectName("company_name_error")
        self.company_name_error.setStyleSheet(
            text_styles.label("#B42318", background="transparent", border="none", font_weight="600")
        )
        self.company_name_error.setWordWrap(True)
        self.company_name_error.setVisible(False)
        self.company_name_container = QWidget()
        company_name_layout = QVBoxLayout(self.company_name_container)
        company_name_layout.setContentsMargins(0, 0, 0, 0)
        company_name_layout.setSpacing(6)
        company_name_layout.addWidget(self.company_name_input)
        self.secondary_existing_button = QPushButton(tr("มีเครื่องหลักอยู่แล้ว", "Already have a Primary"))
        self.secondary_existing_button.setObjectName("secondary_existing_button")
        self.secondary_existing_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_existing_button.setAccessibleName(
            tr(
                "เชื่อมต่อ KOMI Report เครื่องหลักที่มีอยู่",
                "Connect to an existing KOMI Report Primary",
            )
        )
        self.secondary_existing_button.setStyleSheet(setup_styles.SETUP_WIZARD_SECONDARY_EXISTING_BUTTON)
        self.secondary_existing_button.clicked.connect(self.primary_options_requested)
        company_name_layout.addWidget(
            self.secondary_existing_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        company_name_layout.addWidget(self.company_name_error)
        self.company_name_input.textChanged.connect(self._clear_company_name_error)
        self.first_started_input = QLineEdit()
        self.first_started_input.setReadOnly(True)
        self.first_started_input.setFixedSize(150, 38)
        self.version_input = QLineEdit(PACKAGE_VERSION)
        self.version_input.setReadOnly(True)
        self.version_input.setFixedSize(100, 38)
        readonly_style = setup_styles.COMPANY_PAGE_READONLY_STYLE
        self.first_started_input.setStyleSheet(readonly_style)
        self.version_input.setStyleSheet(readonly_style)

        self.database_path_container = QWidget()
        self.database_path_container.setMinimumHeight(92)
        self.database_path_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        database_layout = QVBoxLayout(self.database_path_container)
        database_layout.setContentsMargins(0, 0, 0, 0)
        database_layout.setSpacing(7)
        database_path_row = QHBoxLayout()
        database_path_row.setContentsMargins(0, 0, 0, 0)
        database_path_row.setSpacing(8)
        self.database_path_input = QLineEdit(str(database_path))
        self.database_path_input.setReadOnly(True)
        self.database_path_input.setMinimumHeight(42)
        self.database_path_input.setMinimumWidth(320)
        self.database_path_input.setStyleSheet(readonly_style)
        self.database_path_input.setToolTip(str(database_path))
        database_path_row.addWidget(self.database_path_input, 1)
        self.choose_database_path_button = btn("Browse", "outline")
        self.choose_database_path_button.clicked.connect(self.database_path_requested)
        database_path_row.addWidget(self.choose_database_path_button)
        database_layout.addLayout(database_path_row)
        database_actions = QHBoxLayout()
        database_actions.setContentsMargins(0, 0, 0, 0)
        database_actions.setSpacing(9)
        self.legacy_import_button = btn("Import", "outline")
        self.legacy_import_button.clicked.connect(self.legacy_import_requested)
        database_actions.addWidget(self.legacy_import_button)
        self.database_path_status = QLabel("")
        self.database_path_status.setWordWrap(True)
        self.database_path_status.setStyleSheet(text_styles.label("#52677D", border="none"))
        self.database_path_status.setVisible(False)
        database_actions.addStretch(1)
        database_layout.addLayout(database_actions)
        database_layout.addWidget(self.database_path_status)

        self.company_form_labels = []
        metadata_container = QWidget()
        metadata_layout = QHBoxLayout(metadata_container)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(10)
        metadata_layout.addWidget(self.first_started_input)
        version_label = QLabel("Version ที่ใช้")
        version_label.setFont(fnt(F_MD, True))
        version_label.setStyleSheet(text_styles.label("#334155", background="transparent", border="none"))
        version_label.setBuddy(self.version_input)
        metadata_layout.addSpacing(12)
        metadata_layout.addWidget(version_label)
        metadata_layout.addWidget(self.version_input)
        metadata_layout.addStretch(1)

        for label_text, field in (
            ("ชื่อบริษัท *", self.company_name_container),
            ("วันที่เริ่มใช้งาน", metadata_container),
            ("Database Path", self.database_path_container),
        ):
            label = QLabel(label_text)
            label.setMinimumWidth(145)
            label.setFont(fnt(F_MD, True))
            label.setStyleSheet(text_styles.label("#334155", background="transparent", border="none"))
            label.setBuddy(self.company_name_input if field is self.company_name_container else field)
            self.company_form_labels.append(label)
            self.company_form.addRow(label, field)
        self.company_form_labels.append(version_label)
        self.company_name_input.setAccessibleName("ชื่อบริษัท")
        self.company_name_input.setAccessibleDescription("ใช้แสดงในรายงานและระบุการติดตั้งนี้")
        layout.addWidget(self.company_card, 0, Qt.AlignmentFlag.AlignHCenter)

        privacy_card = QFrame()
        privacy_card.setObjectName("registration_privacy_card")
        privacy_card.setFixedWidth(760)
        privacy_card.setStyleSheet(setup_styles.SETUP_WIZARD_PRIVACY_CARD)
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(14, 12, 14, 12)
        privacy_layout.setSpacing(8)
        privacy_row = QHBoxLayout()
        privacy_copy = QVBoxLayout()
        privacy_title = QLabel("ประกาศข้อมูลการลงทะเบียน")
        privacy_title.setFont(fnt(F_MD, True))
        self.privacy_notice_status = QLabel()
        self.privacy_notice_status.setWordWrap(True)
        privacy_copy.addWidget(privacy_title)
        privacy_copy.addWidget(self.privacy_notice_status)
        privacy_row.addLayout(privacy_copy, 1)
        self.view_privacy_notice_button = btn("ดูข้อมูลที่ส่ง", "outline")
        self.view_privacy_notice_button.setAccessibleName("เปิดดูประกาศข้อมูลการลงทะเบียน")
        self.view_privacy_notice_button.clicked.connect(self.privacy_notice_requested)
        privacy_row.addWidget(self.view_privacy_notice_button)
        privacy_layout.addLayout(privacy_row)
        self.company_notice = QLabel(
            "<b>ขอบเขตข้อมูลที่ปลอดภัย:</b> ส่ง Serial Number, Model, สถานะเลือกใช้, "
            "Status และ Aggregate Total Meter เท่านั้น · ไม่ส่ง IP, MAC, hostname, Credential, "
            "Counter รายละเอียด, ผู้ใช้, เอกสาร หรือ Log"
        )
        self.company_notice.setWordWrap(True)
        self.company_notice.setStyleSheet(setup_styles.SETUP_WIZARD_COMPANY_NOTICE)
        privacy_layout.addWidget(self.company_notice)
        # Retained as an internal compatibility value only. The customer no longer
        # sees a checkbox; pressing Save records acknowledgement under the master
        # agreement and Online Registration is mandatory.
        self.privacy_notice_accepted = QCheckBox()
        self.privacy_notice_accepted.setChecked(False)
        self.privacy_notice_accepted.setVisible(False)
        self.privacy_notice_status.setText(
            tr(
                f"ฉบับ {REGISTRATION_NOTICE_VERSION} · ต้องลงทะเบียนก่อนเริ่มใช้งาน",
                f"Version {REGISTRATION_NOTICE_VERSION} · registration is required before use",
            )
        )
        layout.addWidget(privacy_card, 0, Qt.AlignmentFlag.AlignHCenter)
        # Keep hidden compatibility controls for older integrations while the
        # customer Wizard follows one unambiguous Online-first path.
        self.registration_mode_group = QButtonGroup(self)
        self.registration_mode_group.setExclusive(True)
        self.registration_online_mode = QRadioButton()
        self.registration_offline_mode = QRadioButton()
        self.registration_mode_group.addButton(self.registration_online_mode)
        self.registration_mode_group.addButton(self.registration_offline_mode)
        self.registration_online_mode.setChecked(True)
        self.registration_online_mode.setVisible(False)
        self.registration_offline_mode.setVisible(False)
        if lab_mode:
            lab_notice = QLabel(
                "<b>SETUP LAB</b> · หน้านี้ใช้ Wizard ตัวจริง แต่ใช้ฐานข้อมูลชั่วคราวและ "
                "Virtual Printer บน LAN ข้อมูลจะไม่ปนกับโปรแกรมที่ใช้งานอยู่"
            )
            lab_notice.setWordWrap(True)
            lab_notice.setFixedWidth(760)
            lab_notice.setStyleSheet(surfaces_styles.WARNING_BOX)
            layout.addWidget(lab_notice, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.company_scroll.setWidget(content)
        page_layout.addWidget(self.company_scroll)

    def _clear_company_name_error(self) -> None:
        if self.company_name_error.isHidden():
            return
        self.company_name_error.setVisible(False)
        self.company_name_input.setStyleSheet(self._company_name_normal_style)
        self.company_name_input.setAccessibleDescription(
            tr(
                "ใช้แสดงในรายงานและระบุการติดตั้งนี้",
                "Used in reports and to identify this installation",
            )
        )

    def _show_company_name_error(self) -> None:
        self.company_name_error.setText(tr("กรุณากรอกชื่อบริษัท", "Enter the company name to continue"))
        self.company_name_error.setVisible(True)
        self.company_name_input.setStyleSheet(self._company_name_error_style)
        self.company_name_input.setAccessibleDescription(self.company_name_error.text())
        self.company_name_input.setFocus()

    def validate(self) -> bool:
        """Normalize the organization name and show the inline error when empty."""
        name = " ".join(self.company_name_input.text().split())
        if not name:
            self._show_company_name_error()
            return False
        self.company_name_input.setText(name)
        return True
