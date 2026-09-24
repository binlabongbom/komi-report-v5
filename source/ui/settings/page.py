"""Page UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from i18n import apply_language, tr
from ui.components.notices import show_compact_information
from ui.page_tabs import PageHeading
from ui.page_tabs import PageTabs as QTabWidget
from ui.pages.activity import PagePipelineLog
from ui.settings.billing_audit import PageBillingAudit
from ui.settings.fleet import PageFleetSettings
from ui.styles import settings as settings_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles.tokens import F_2XL
from widgets import btn, fnt


class PageSettingsV5(QWidget):
    changed = pyqtSignal()
    sync_requested = pyqtSignal()
    parser_read_requested = pyqtSignal(int)

    def __init__(
        self,
        legacy_settings: QWidget,
        parent=None,
        *,
        registration_runtime=None,
        offline_license_public_keys: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.stack = QStackedWidget()
        self.fleet_content = PageFleetSettings(
            registration_runtime=registration_runtime,
            offline_license_public_keys=offline_license_public_keys,
        )
        self.activity = PagePipelineLog()
        self.activity.page_title.hide()
        self.activity.page_note.hide()
        self.audit = PageBillingAudit(embedded=True)
        self.legacy_content = legacy_settings
        embed_mode = getattr(self.legacy_content, "set_v5_embed_mode", None)
        if callable(embed_mode):
            embed_mode()
        self._activity_host = self.activity
        self._audit_host = self._detail_page(
            "ตรวจสอบรอบบิล",
            "",
            self.audit,
        )
        self.legacy = self.legacy_content
        support_layout = self.fleet_content.support_task_editor.layout()

        def hide_existing(item) -> None:
            widget = item.widget()
            if widget is not None:
                widget.hide()
            child_layout = item.layout()
            if child_layout is not None:
                for child_index in range(child_layout.count()):
                    hide_existing(child_layout.itemAt(child_index))

        for item_index in range(support_layout.count()):
            hide_existing(support_layout.itemAt(item_index))

        advanced_notice = QLabel(
            "จัดการ Database, Backup, Log และ Parser Mapping · "
            "รายการที่ลบหรือรีเซ็ตข้อมูลจะสำรองข้อมูลและขอยืนยันก่อนเสมอ"
        )
        advanced_notice.setWordWrap(True)
        advanced_notice.setStyleSheet(
            surfaces_styles.WARNING_NOTICE
        )
        support_layout.addWidget(advanced_notice)
        # Auto-start is an everyday program preference, so keep it in General
        # beside printer/registration/billing settings.  The registered command
        # starts the lightweight background agent without constructing the GUI.
        self.fleet_content.autostart_program_card.setParent(self.fleet_content)
        self.fleet_content.layout().insertWidget(
            3, self.fleet_content.autostart_program_card
        )
        self.legacy_content.setParent(self.fleet_content.support_task_editor)
        support_layout.addWidget(self.legacy_content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack)
        self.fleet_content.changed.connect(self.changed)
        self.fleet_content.activity_requested.connect(self.show_activity)
        self.fleet_content.billing_audit_requested.connect(self.show_audit)
        self.fleet_content.advanced_tools_requested.connect(self.show_advanced)
        self.activity.sync_requested.connect(self.sync_requested)
        self.activity.settings_requested.connect(self.show_schedule)
        if hasattr(self.legacy_content, "changed"):
            self.legacy_content.changed.connect(self.changed)
        if hasattr(self.legacy_content, "parser_read_requested"):
            self.legacy_content.parser_read_requested.connect(self.parser_read_requested)
        self._build_section_tabs(layout)
        self._logical_pages = [self.fleet, self.activity, self.audit, self.legacy]

    def _build_section_tabs(self, layout: QVBoxLayout) -> None:
        """Reuse the existing forms and handlers inside one page-tab shell."""
        content = self.fleet_content
        content.layout().itemAt(0).widget().hide()
        content.layout().setContentsMargins(14, 14, 14, 18)
        self.section_tabs = QTabWidget()
        self.section_tabs.setAccessibleName(tr("หมวดการตั้งค่า", "Settings sections"))
        self._section_index = 0

        def section(card: QWidget) -> QScrollArea:
            host = QWidget()
            body = QVBoxLayout(host)
            body.setContentsMargins(14, 14, 14, 18)
            body.setSpacing(12)
            body.addWidget(card)
            body.addStretch()
            return self._scroll_page(host)

        # Moving cards removes their old layout items without duplicating state.
        schedule_card = content.schedule_task_editor.parentWidget()
        support_card = content.support_task_editor.parentWidget()
        self.schedule_page = section(schedule_card)
        self.network_page = section(content.web_program_card)
        self.advanced_page = section(support_card)
        from ui.error_list import ErrorListPanel
        self.error_list_page = ErrorListPanel()
        from ui.archive_settings import ArchiveSettingsPanel
        self.archive_settings = ArchiveSettingsPanel()
        self.advanced_page.widget().layout().insertWidget(1, self.archive_settings)
        self._legacy_host = self.advanced_page
        for key in ("billing", "schedule", "web", "support"):
            content._task_buttons[key].hide()
            editor = content._task_editors[key]
            editor.setStyleSheet(settings_styles.transparent_editor(editor.objectName()))
            editor.layout().setContentsMargins(0, 8, 0, 0)

        # The plan and its editor now share Automation. Keep the other three
        # activity tabs as status/history views, with no second Automation tab.
        self.activity.tabs.removeTab(self.activity.tabs.indexOf(self.activity.timeline_scroll))
        timeline = self.activity.timeline_scroll.takeWidget()
        timeline.layout().setContentsMargins(0, 0, 0, 0)
        self.schedule_page.widget().layout().insertWidget(0, timeline)
        from ui.reader_members import ReaderMembersPanel
        self.reader_members = ReaderMembersPanel()
        self.schedule_page.widget().layout().insertWidget(0, self.reader_members)
        self.activity.layout().setContentsMargins(12, 12, 12, 12)

        # Attach each subtree only after its final parent is known. Building
        # the legacy stack first polished all forms, then reparented/polished
        # them again while the user waited on the first Settings visit.
        self.fleet = self._scroll_page(content)
        self._unmounted_sections = {}
        for index, (page, title) in enumerate((
            (self.fleet, "ทั่วไป"), (self.schedule_page, "การทำงานอัตโนมัติ"),
            (self.activity, "สถานะและประวัติ"), (self.network_page, "การตั้งค่าเครือข่าย"),
            (self.advanced_page, "ขั้นสูง"), (self.error_list_page, "Error list"),
        )):
            if index == 0:
                self.section_tabs.addTab(page, title)
                continue
            # Mount only the selected subtree into the styled main window.
            # Hidden forms keep their state, but do not all incur stylesheet
            # polish/layout in the first General navigation callback.
            host = QWidget()
            QVBoxLayout(host).setContentsMargins(0, 0, 0, 0)
            page.hide()
            self.destroyed.connect(page.deleteLater)
            self._unmounted_sections[index] = page
            self.section_tabs.addTab(host, title)
        self.activity.timeline_scroll.deleteLater()
        self.stack.addWidget(self.section_tabs)
        self.stack.addWidget(self._audit_host)
        self.stack.setCurrentWidget(self.section_tabs)

        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        self.heading = PageHeading("ตั้งค่า", "จัดการเครื่องพิมพ์ รอบบิล การอ่านข้อมูล และการทำงานของโปรแกรม")
        layout.insertWidget(0, self.heading)
        content._section_editor = "billing"
        content._set_active_editor("billing", force=True)
        self.section_tabs.currentChanged.connect(self._section_changed)
        content.changed.connect(self._refresh_schedule_preview)
        apply_language(self)

    def _section_changed(self, index: int) -> None:
        content = self.fleet_content
        target = {0: "billing", 1: "schedule", 2: None, 3: "web", 4: "support", 5: None}[index]
        # Do not let navigation or a refresh discard edits, including the
        # Auto-start form nested in Advanced Settings.
        if index != self._section_index and content.has_unsaved_changes():
            self.section_tabs.blockSignals(True)
            self.section_tabs.setCurrentIndex(self._section_index)
            self.section_tabs.blockSignals(False)
            show_compact_information(
                self, tr("ยังไม่ได้บันทึก", "Unsaved changes"),
                tr("กรุณาบันทึกหรือยกเลิกการแก้ไขก่อนเปลี่ยนแท็บ", "Save or cancel your changes before switching tabs."),
            )
            return
        content._section_editor = target
        page = self._unmounted_sections.pop(index, None)
        if page is not None:
            self.section_tabs.widget(index).layout().addWidget(page)
            page.show()
        content._set_active_editor(target, force=True)
        self._section_index = index
        if index == 1:
            self.activity.refresh_timeline()
        elif index == 2:
            self.activity.refresh()
        apply_language(self)

    def _select_section(self, index: int) -> bool:
        self.section_tabs.setCurrentIndex(index)
        if self.section_tabs.currentIndex() != index:
            return False
        self.stack.setCurrentWidget(self.section_tabs)
        return True

    def _refresh_schedule_preview(self) -> None:
        if self._section_index == 1:
            self.activity.refresh_timeline()

    def show_schedule(self) -> None:
        if not self._select_section(1):
            return
        self.fleet_content.advanced_schedule_button.setChecked(True)
        QTimer.singleShot(0, lambda: self.schedule_page.ensureWidgetVisible(
            self.fleet_content.schedule_editor, 0, 16,
        ))

    def show_reader_members(self) -> None:
        if self._select_section(1):
            self.reader_members.schedule_refresh()
            QTimer.singleShot(0, lambda: self.schedule_page.verticalScrollBar().setValue(0))

    @staticmethod
    def _scroll_page(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _detail_page(
        self,
        title: str,
        description: str,
        content: QWidget,
        *,
        warning: bool = False,
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top = QHBoxLayout()
        back = btn("← กลับไปการตั้งค่า", "outline")
        back.setAccessibleName("กลับไปหน้าการตั้งค่าหลัก")
        back.clicked.connect(self.show_main)
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        heading = QLabel(title)
        heading.setFont(fnt(F_2XL, True))
        heading.setStyleSheet(text_styles.label('#102A43', border='none'))
        detail = QLabel(description)
        detail.setVisible(bool(description))
        detail.setWordWrap(True)
        detail.setStyleSheet(
            settings_styles.detail_warning(bool(warning))
        )
        copy.addWidget(heading)
        copy.addWidget(detail)
        top.addLayout(copy, 1)
        layout.addLayout(top)
        layout.addWidget(content, 1)
        return page

    def ensure_unlocked(self) -> bool:
        self.fleet_content.refresh_from_config()
        return True

    def has_unsaved_changes(self) -> bool:
        return self.fleet_content.has_unsaved_changes()

    def discard_unsaved_changes(self) -> None:
        self.fleet_content.discard_unsaved_changes()

    def show_main(self) -> None:
        if not self._select_section(0):
            return
        self.fleet_content.refresh_from_config()
        self.fleet_content._set_active_editor("billing", force=True)
        apply_language(self)

    def show_activity(self) -> None:
        self._select_section(2)

    def show_audit(self) -> None:
        if not self._select_section(0):
            return
        self.stack.setCurrentWidget(self._audit_host)
        self.audit.refresh()
        apply_language(self._audit_host)

    def show_advanced(self) -> None:
        if not self._select_section(4):
            return
        self.fleet_content._set_active_editor("support", force=True)
        refresh = getattr(self.legacy_content, "_refresh_ui", None)
        if callable(refresh):
            refresh()
        apply_language(self)

    def refresh(self) -> None:
        current = self.currentWidget()
        if current is self.activity:
            self.activity.refresh()
        elif current is self.audit:
            self.audit.refresh()
        else:
            self.fleet_content.refresh_from_config()

    @property
    def _authenticated(self):
        return True

    @_authenticated.setter
    def _authenticated(self, value):
        if hasattr(self.legacy_content, "_authenticated"):
            self.legacy_content._authenticated = True
        show_protected = getattr(self.legacy_content, "_set_protected_visible", None)
        if callable(show_protected):
            show_protected(True)

    def setCurrentWidget(self, widget: QWidget) -> None:
        if widget is self.legacy:
            self.show_advanced()
            return
        if widget is self.activity:
            self.show_activity()
        elif widget is self.audit:
            self.show_audit()
        else:
            self.show_main()

    def currentWidget(self) -> QWidget:
        if self.stack.currentWidget() is self._audit_host:
            return self.audit
        if self.section_tabs.currentIndex() == 2:
            return self.activity
        return self.fleet

    def widget(self, index: int) -> QWidget:
        return self._logical_pages[index]

    def count(self) -> int:
        return len(self._logical_pages)
