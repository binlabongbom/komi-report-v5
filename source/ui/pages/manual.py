"""Manual UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import stat
from pathlib import Path

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from i18n import ENGLISH, get_language
from ui.styles import legacy as legacy_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_TEXT, C_TEXT2, F_2XL, F_LG, F_SM, F_XL
from widgets import fnt


class _ManualDocumentImage(QLabel):
    """Responsive screenshot shared by the in-app guide and Customer Guide."""

    def __init__(self, pixmap: QPixmap | Path, parent=None):
        super().__init__(parent)
        from PyQt6.QtGui import QImageReader
        self._image_path = pixmap if isinstance(pixmap, Path) else None
        size = QImageReader(str(pixmap)).size() if self._image_path else pixmap.size()
        self._source_width = size.width()
        self._aspect_ratio = (
            size.height() / size.width() if size.width() > 0 else 0.75
        )
        if self._image_path is None:
            self.setPixmap(pixmap)
        self.setScaledContents(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.setMinimumWidth(0)
        self.setStyleSheet(surfaces_styles.WHITE_BORDERLESS)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(120, round(max(1, width) * self._aspect_ratio))

    def sizeHint(self):
        width = min(900, max(640, self._source_width))
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event):
        # Scroll-area clipping means only pictures reaching the viewport are
        # decoded. Header dimensions reserve identical geometry before load.
        if self._image_path is not None:
            path, self._image_path = self._image_path, None
            self.setPixmap(QPixmap(str(path)))
        super().paintEvent(event)

    def minimumSizeHint(self):
        return QSize(240, self.heightForWidth(240))


class PageManual(QWidget):
    """
    คู่มือใช้งาน KOMI Report V5.2 สำหรับผู้ใช้ทั่วไปและเจ้าหน้าที่ดูแลระบบ
    โดยยึดพฤติกรรมของหน้าจอจริงเป็นหลัก
    """
    FONT_SCALE = 0.80

    @classmethod
    def _manual_point_size(cls, size: int) -> int:
        """ลด typography เฉพาะหน้าคู่มือ โดยไม่กระทบหน้าอื่นของโปรแกรม"""
        return max(8, round(size * cls.FONT_SCALE))

    @classmethod
    def _manual_font(cls, size: int, bold: bool = False) -> QFont:
        return fnt(cls._manual_point_size(size), bold=bold)

    def __init__(self, parent=None, *, lazy: bool = False):
        super().__init__(parent)
        self._lazy = lazy
        self._thai_manual_next = 0
        # องค์ประกอบที่ไม่ได้กำหนดฟอนต์เฉพาะ จะ inherit ขนาดคู่มือที่ลดแล้ว
        self.setFont(self._manual_font(F_LG))
        self._build()

    # ── helper: สร้าง section header ────────────────────────
    def _sec(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(self._manual_font(F_2XL))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            legacy_styles.manual_sec()
        )
        return lbl

    # ── helper: สร้าง step badge + ข้อความ ──────────────────
    def _step(self, num: int, text: str) -> QWidget:
        row = QWidget()
        row.setStyleSheet(legacy_styles.MANUAL_STEP)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(10)

        badge = QLabel(str(num))
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            legacy_styles.manual_badge(self._manual_point_size(F_LG))
        )

        desc = QLabel(text)
        desc.setFont(self._manual_font(F_XL))
        desc.setWordWrap(True)
        desc.setStyleSheet(text_styles.label(C_TEXT, background='transparent', border='0'))

        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(desc, 1)
        row.setLayout(lay)
        return row

    # ── helper: สร้าง card พื้นขาว ────────────────────────
    def _card(self, title: str, body_widgets: list) -> QFrame:
        card = QFrame()
        card.setObjectName("manual_document_block")
        card.setStyleSheet(
            legacy_styles.MANUAL_CARD
        )
        vl = QVBoxLayout()
        vl.setContentsMargins(8, 8, 8, 12)
        vl.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setFont(self._manual_font(F_2XL))
            t.setWordWrap(True)
            t.setStyleSheet(
                legacy_styles.manual_card_title()
            )
            vl.addWidget(t)
        for w in body_widgets:
            vl.addWidget(w)
        card.setLayout(vl)
        return card

    # ── helper: ข้อความธรรมดา ────────────────────────────
    def _txt(self, text: str, bold=False, color=None) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(self._manual_font(F_XL))
        lbl.setWordWrap(True)
        c = color or C_TEXT
        lbl.setStyleSheet(
            legacy_styles.manual_txt(c, 'font-weight:bold;' if bold else '')
        )
        return lbl

    # ── helper: ข้อความหมายเหตุ/tip (สีรอง) ─────────────
    def _tip(self, text: str) -> QLabel:
        lbl = QLabel(f"💡  {text}")
        lbl.setFont(self._manual_font(F_LG))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            legacy_styles.manual_tip()
        )
        return lbl

    def _guide_screenshot(self, index: int, caption: str, *, english=False) -> QWidget:
        from ui.manual_screens import manual_screen_path
        image_path = self._manual_asset(manual_screen_path(index, english=english))
        pixmap = (
            image_path
            if self._manual_asset_available(image_path)
            else QPixmap()
        )

        block = QWidget()
        block.setStyleSheet(surfaces_styles.WHITE_BORDERLESS)
        layout = QVBoxLayout(block)
        layout.setContentsMargins(8, 6, 8, 16)
        layout.setSpacing(5)
        image = _ManualDocumentImage(pixmap)
        image.setObjectName(
            f"manual_doc_image_{'en_' if english else ''}{index:02d}"
        )
        if isinstance(pixmap, QPixmap) and pixmap.isNull():
            image.setText(
                "Screenshot is not available" if english else "ไม่พบภาพประกอบคู่มือ"
            )
        layout.addWidget(image)
        label = QLabel(caption)
        label.setFont(self._manual_font(F_SM))
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            legacy_styles.manual_guide_screenshot()
        )
        layout.addWidget(label)
        return block

    def _insert_customer_guide_screenshots(self, *, only_english=None, only_index=None) -> None:
        groups = (
            ((1, 2, 3, 4), ("ตั้งค่าบริษัทและฐานข้อมูล", "ค้นหาและเลือกเครื่องพิมพ์", "ตั้งราคาและรอบบิล", "ตรวจสอบก่อนเริ่มใช้งาน")),
            ((5, 6), ("ภาพรวมการใช้งาน", "ข้อมูลรายเครื่อง")),
            ((7, 8, 9), ("รายงานภาพรวม", "รายงาน Usage", "รายงาน Legacy")),
            ((10, 11, 12), ("การตั้งค่าหลัก", "สถานะการตั้งค่าเครือข่าย · ข้อมูลจำลอง", "เครื่องมือขั้นสูงและ Parser Mapping")),
            ((13,), ("คู่มือฉบับย่อในโปรแกรม",)),
        )
        english_captions = (
            ("Company and Database setup", "Discover and select printers", "Prices and billing cycle", "Review before first use"),
            ("Operational overview", "Per-device information"),
            ("Report overview", "Usage report", "Legacy report"),
            ("Main Settings", "Network activity · synthetic example", "Advanced tools and Parser Mapping"),
            ("In-app quick guide",),
        )
        for sections, captions, english in (
            (self._thai_manual_sections, tuple(group[1] for group in groups), False),
            (self._english_manual_sections, english_captions, True),
        ):
            if not sections or (only_english is not None and english != only_english):
                continue
            for section_index, (section, (indexes, _thai_captions), section_captions) in enumerate(zip(
                sections, groups, captions,
            )):
                if only_index is not None and section_index != only_index:
                    continue
                layout = section.layout()
                insert_at = max(1, layout.count() - 1)
                for index, caption in zip(indexes, section_captions, strict=True):
                    layout.insertWidget(
                        insert_at,
                        self._guide_screenshot(index, caption, english=english),
                    )
                    insert_at += 1

    @staticmethod
    def _manual_asset(filename: str) -> Path:
        candidates = (
            Path(__file__).resolve().parents[2] / "docs" / filename,
            Path(__file__).resolve().parents[3] / "docs" / filename,
        )
        return next((path for path in candidates if path.exists()), candidates[-1])

    @staticmethod
    def _manual_asset_available(path: Path) -> bool:
        """Reject unresolved OneDrive placeholders before Qt blocks on them."""
        try:
            flags = getattr(path.stat(), "st_flags", 0)
        except OSError:
            return False
        return path.is_file() and not (flags & getattr(stat, "SF_DATALESS", 0))

    def _diagram_card(self, title: str, summary: str, image_name: str, html_name: str) -> QFrame:
        image_path = self._manual_asset(image_name)
        html_path = self._manual_asset(html_name)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumWidth(0)
        preview.setMinimumHeight(280)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview.setStyleSheet(legacy_styles.manual_preview())
        pixmap = QPixmap(str(image_path)) if self._manual_asset_available(image_path) else QPixmap()
        if pixmap.isNull():
            preview.setText("ไม่พบภาพคู่มือ")
        else:
            preview.setPixmap(
                pixmap.scaled(
                    560,
                    390,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        open_path = html_path if self._manual_asset_available(html_path) else image_path
        open_button = QPushButton("เปิด Diagram แบบเต็ม")
        open_button.setEnabled(self._manual_asset_available(open_path))
        open_button.setStyleSheet(
            legacy_styles.manual_open_button()
        )
        open_button.clicked.connect(
            lambda _checked=False, path=open_path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        )
        if html_name == "sync-rule-flowchart.html":
            self.manual_sync_button = open_button
        else:
            self.manual_storage_button = open_button
        return self._card(title, [self._txt(summary), preview, open_button])

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(10)

        # ── Header ──────────────────────────────────────────
        header = QHBoxLayout()
        self.manual_title = QLabel("📖  คู่มือการใช้งาน")
        self.manual_title.setFont(self._manual_font(F_2XL))
        self.manual_title.setStyleSheet(text_styles.label(C_TEXT, font_weight='bold'))
        self.manual_subtitle = QLabel("KOMI Report 5.2.12 — ติดตั้ง อ่านมิเตอร์ และออกรายงาน")
        self.manual_subtitle.setFont(self._manual_font(F_LG))
        self.manual_subtitle.setStyleSheet(text_styles.label(C_TEXT2))
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(self.manual_title)
        title_col.addWidget(self.manual_subtitle)
        header.addLayout(title_col)
        header.addStretch()
        self.manual_toc_combo = QComboBox()
        self.manual_toc_combo.setObjectName("manual_toc_combo")
        self.manual_toc_combo.setMinimumWidth(210)
        self.manual_toc_combo.setFont(self._manual_font(F_LG))
        self.manual_toc_combo.setAccessibleName("สารบัญหน้านี้")
        self.manual_toc_combo.currentIndexChanged.connect(
            self._scroll_to_manual_section
        )
        header.addWidget(self.manual_toc_combo)
        outer.addLayout(header)
        outer.addSpacing(2)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(18)

        self.manual_scroll = QScrollArea()
        self.manual_scroll.setObjectName("manual_single_page_scroll")
        self.manual_scroll.setWidgetResizable(True)
        self.manual_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.manual_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.manual_scroll.setStyleSheet(
            legacy_styles.MANUAL_MANUAL_SCROLL
        )

        self.manual_content = QWidget()
        self.manual_content.setObjectName("manual_word_content")
        self.manual_content.setStyleSheet(
            legacy_styles.MANUAL_MANUAL_CONTENT
        )
        content_layout = QVBoxLayout(self.manual_content)
        content_layout.setContentsMargins(12, 0, 12, 32)
        content_layout.setSpacing(30)

        self._thai_manual_sections = []
        self._english_manual_sections = []
        self._manual_content_layout = content_layout
        content_layout.addStretch()
        self._ensure_manual_language(get_language() == ENGLISH)
        self.manual_scroll.setWidget(self.manual_content)
        self.manual_scroll.verticalScrollBar().valueChanged.connect(
            self._update_manual_toc_highlight
        )
        body.addWidget(self.manual_scroll, 1)

        self.manual_toc_frame = QFrame()
        self.manual_toc_frame.setObjectName("manual_toc_frame")
        self.manual_toc_frame.setFixedWidth(224)
        self.manual_toc_frame.setStyleSheet(
            legacy_styles.manual_contents()
        )
        toc_layout = QVBoxLayout(self.manual_toc_frame)
        toc_layout.setContentsMargins(12, 14, 12, 14)
        toc_layout.setSpacing(5)
        self.manual_toc_title = QLabel("สารบัญหน้านี้")
        self.manual_toc_title.setFont(self._manual_font(F_LG, bold=True))
        self.manual_toc_title.setStyleSheet(text_styles.label(C_TEXT, padding='4px 6px 8px 6px'))
        toc_layout.addWidget(self.manual_toc_title)
        self.manual_toc_buttons: list[QPushButton] = []
        for index in range(5):
            button = QPushButton()
            button.setFont(self._manual_font(F_LG))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(self._manual_toc_button_style(active=False))
            button.clicked.connect(
                lambda _checked=False, section_index=index: self._scroll_to_manual_section(
                    section_index
                )
            )
            self.manual_toc_buttons.append(button)
            toc_layout.addWidget(button)
        toc_layout.addStretch()
        body.addWidget(self.manual_toc_frame, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(body, 1)

        self._apply_i18n_visibility(get_language())
        self._update_manual_responsive_layout(self.width())

    def _ensure_manual_language(self, english):
        """Construct only the requested language, once, on the GUI thread."""
        name = '_english_manual_sections' if english else '_thai_manual_sections'
        if getattr(self, name):
            return
        if not english and self._lazy:
            sections = [self._tab_firstrun()]
            self._thai_manual_next = 1
        else:
            sections = self._build_english_manual_sections() if english else [
                self._tab_firstrun(), self._tab_workflow(), self._tab_history(),
                self._tab_settings(), self._tab_v5_system(),
            ]
        setattr(self, name, sections)
        self._insert_customer_guide_screenshots(only_english=english)
        self._insert_updated_guide(only_english=english)
        for section in sections:
            section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            self._manual_content_layout.insertWidget(max(0, self._manual_content_layout.count()-1), section)
        if not english and self._lazy:
            QTimer.singleShot(30, self._append_next_thai_section)

    def _append_next_thai_section(self) -> None:
        builders = (self._tab_firstrun, self._tab_workflow, self._tab_history,
                    self._tab_settings, self._tab_v5_system)
        index = self._thai_manual_next
        if not 1 <= index < len(builders):
            return
        section = builders[index]()
        self._thai_manual_sections.append(section)
        self._insert_customer_guide_screenshots(only_english=False, only_index=index)
        self._insert_updated_guide(only_english=False, only_index=index)
        section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._manual_content_layout.insertWidget(max(0, self._manual_content_layout.count()-1), section)
        section.setVisible(self._manual_language != ENGLISH)
        self._thai_manual_next += 1
        if self._thai_manual_next < len(builders):
            QTimer.singleShot(30, self._append_next_thai_section)

    def _insert_updated_guide(self, *, only_english=None, only_index=None):
        for sections, english in ((self._thai_manual_sections, False), (self._english_manual_sections, True)):
            if not sections or (only_english is not None and english != only_english):
                continue
            guide = self._manual_asset('customer-guide/KOMI_Report_5.2.12_Source_Guide.pdf')
            button = QPushButton('Open updated illustrated guide (Thai PDF)' if english else 'เปิดคู่มือฉบับปรับปรุงพร้อมภาพ (PDF)')
            button.setEnabled(self._manual_asset_available(guide))
            button.clicked.connect(lambda _=False, path=guide: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            if len(sections) > 0 and only_index in (None, 0):
                sections[0].layout().insertWidget(1, self._card('Updated guide' if english else 'คู่มือหน้าจอที่ปรับปรุง', [
                self._txt('Network settings, Slot baselines, revised reports and Archive. Check the Network settings page for current member connection status.' if english else
                    'รวมการตั้งค่าเครือข่าย ฐาน Slot รายงานฉบับแก้ไข และ Archive ตรวจสถานะสมาชิกที่เชื่อมต่อได้ในหน้าการตั้งค่าเครือข่าย'), button]))
            if len(sections) > 3 and only_index in (None, 3):
                sections[3].layout().insertWidget(1, self._card('Network settings and shared changes' if english else 'การตั้งค่าเครือข่ายและค่าร่วมกัน', [
                self._txt('Settings > Advanced > Network settings shows actual work and durable receipt queues. A completed send is not proof that the peer saved it.' if english else
                    'ตั้งค่า > ขั้นสูง > การตั้งค่าเครือข่าย แสดงงานที่กำลังทำและคิวรอยืนยันรับ การส่งข้อความสำเร็จยังไม่ใช่หลักฐานว่าปลายทางบันทึกแล้ว'),
                self._txt('Configuration history is retained locally. Continuous synchronization and shared reading require verified membership; copying initial setup alone does not establish it.' if english else
                    'ประวัติการตั้งค่าเก็บไว้ในคอมนี้ การ Sync ต่อเนื่องและผู้อ่านร่วมต้องเชื่อมสมาชิกที่ยืนยันแล้ว การรับค่าติดตั้งครั้งเดียวยังไม่ใช่การเชื่อมสมาชิก'),
                self._txt('Each computer keeps its own identity and shares the same three printer Slots. Replacing a used printer starts from its reviewed meter baseline.' if english else
                    'แต่ละคอมมีตัวตนของตนเองและใช้ Slot เครื่องพิมพ์สามช่องชุดเดียวกัน เมื่อเปลี่ยนเป็นเครื่องมือสอง ยอดจะนับต่อจากฐานที่ตรวจยืนยันแล้ว')]))
            if len(sections) > 2 and only_index in (None, 2):
                sections[2].layout().insertWidget(1, self._card('Missing history and revised reports' if english else 'ช่วงขาดข้อมูลและรายงานฉบับแก้ไข', [
                self._txt('Users, Raw, Usage and Excel include received Web history. Tables allocate gap totals to the day before readings resume, with a remark and no invented reading time. Unposted usage is provisional; closed accounts retain their originals.' if english else
                    'Users, Raw, Usage และ Excel รวมประวัติ Web ที่รับมาแล้ว ตารางลงยอดช่วงขาดวันก่อนกลับมาอ่าน พร้อมหมายเหตุและไม่สร้างเวลาอ่านปลอม ยอดที่ยังไม่ลงบัญชีเป็นยอดชั่วคราว บัญชีปิดแล้วเก็บต้นฉบับไว้'),
                self._txt('A 301-page gap over two entirely missing days is shown as an estimated 150.5 pages per day. The graph never determines invoice amounts.' if english else
                    'ช่วงขาด 301 หน้าในสองวันที่ไม่มีข้อมูลทั้งวัน กราฟแสดงเฉลี่ยประมาณการวันละ 150.5 หน้า ไม่ใช้ค่าเฉลี่ยกราฟคิดเงิน'),
                self._txt('Review Web evidence before confirming revised allocation. Originals remain intact and delivery awaits verified receipts. Old user/Raw details are not rewritten by this action.' if english else
                    'ตรวจหลักฐาน Web ก่อนยืนยันฉบับแก้ไขการแบ่งยอด ระบบเก็บต้นฉบับและคิวรอรับไว้ การยืนยันนี้ไม่เขียนทับรายละเอียดผู้ใช้หรือ Raw เก่า'),
                self._txt('Use Review details for Web-derived user/Raw amendments. Review historical amounts in Billing Audit to approve held money; original meter warnings remain.' if english else
                    'ใช้ตรวจแก้รายละเอียดเพื่อออกฉบับผู้ใช้/Raw จากหลักฐาน Web ส่วนตรวจและแก้ยอดในหน้ารอบบิลใช้อนุมัติเงินที่พักไว้ โดยเก็บคำเตือนมิเตอร์เดิม'),
                self._txt('Details older than twelve months can be archived. Monthly summaries remain available; older files open only when requested.' if english else
                    'รายละเอียดเกิน 12 เดือนเก็บเป็น Archive ได้ สรุปรายเดือนยังเรียกดูได้ และเปิดไฟล์เก่าเฉพาะเมื่อขอดูรายละเอียด'),
                self._txt('In Archive settings, use Fill reports from archived history to index older evidence on request. Stop after this batch preserves completed work; retry resumes without duplicate usage. Refresh reports afterward. Original evidence and closed totals are preserved.' if english else
                    'ในหน้าจัดเก็บประวัติ กดเติมรายงานจากประวัติที่จัดเก็บแล้วเพื่ออ่านหลักฐานเก่าเมื่อสั่ง หยุดหลังจบชุดนี้ได้ และทำต่อโดยไม่เพิ่มยอดซ้ำ จากนั้นรีเฟรชรายงาน หลักฐานและยอดปิดแล้วคงเดิม')]))

    def _apply_i18n_visibility(self, language: str) -> None:
        self._manual_language = language
        english = language == "en"
        for section in (self._thai_manual_sections if english else self._english_manual_sections):
            section.hide()
        self._ensure_manual_language(english)
        for section in self._thai_manual_sections:
            section.setVisible(not english)
        for section in self._english_manual_sections:
            section.setVisible(english)
        self.manual_title.setText("📖  User manual" if english else "📖  คู่มือการใช้งาน")
        self.manual_subtitle.setText(
            "KOMI Report V5.2 — setup, meters and reports"
            if english
            else "KOMI Report 5.2.12 — ติดตั้ง อ่านมิเตอร์ และออกรายงาน"
        )
        self.manual_toc_title.setText("On this page" if english else "สารบัญหน้านี้")
        self.manual_toc_combo.setAccessibleName(
            "On this page" if english else "สารบัญหน้านี้"
        )
        labels = (
            ("Getting started", "Daily workflow", "Reports", "Settings", "System V5.2")
            if english
            else ("เริ่มต้นใช้งาน", "วิธีทำงาน", "รายงาน", "ตั้งค่า", "ระบบ V5.2")
        )
        self.manual_toc_combo.blockSignals(True)
        self.manual_toc_combo.clear()
        self.manual_toc_combo.addItems(labels)
        self.manual_toc_combo.blockSignals(False)
        for button, label in zip(self.manual_toc_buttons, labels, strict=True):
            button.setText(label)
            button.setAccessibleName(label)
        self.manual_scroll.verticalScrollBar().setValue(0)
        self._set_manual_toc_active(0)

    def _active_manual_sections(self) -> list[QWidget]:
        return (
            self._english_manual_sections
            if self._manual_language == ENGLISH
            else self._thai_manual_sections
        )

    def _scroll_to_manual_section(self, index: int) -> None:
        if self._lazy and self._manual_language != ENGLISH:
            while index >= len(self._thai_manual_sections) and self._thai_manual_next < 5:
                self._append_next_thai_section()
        sections = self._active_manual_sections()
        if not (0 <= index < len(sections)):
            return
        section = sections[index]
        top = section.mapTo(self.manual_content, QPoint(0, 0)).y()
        self.manual_scroll.verticalScrollBar().setValue(max(0, top - 8))
        self._set_manual_toc_active(index)

    def _set_manual_toc_active(self, index: int) -> None:
        for button_index, button in enumerate(self.manual_toc_buttons):
            active = button_index == index
            button.setChecked(active)
            button.setStyleSheet(self._manual_toc_button_style(active=active))
        self.manual_toc_combo.blockSignals(True)
        self.manual_toc_combo.setCurrentIndex(index)
        self.manual_toc_combo.blockSignals(False)

    @staticmethod
    def _manual_toc_button_style(*, active: bool) -> str:
        return legacy_styles.manual_toc_button(active=active)

    def _update_manual_toc_highlight(self, value: int) -> None:
        sections = self._active_manual_sections()
        if not sections:
            return
        probe = value + 72
        active = 0
        for index, section in enumerate(sections):
            if section.mapTo(self.manual_content, QPoint(0, 0)).y() <= probe:
                active = index
            else:
                break
        self._set_manual_toc_active(active)

    def _update_manual_responsive_layout(self, width: int) -> None:
        show_right_toc = width >= 980
        self.manual_toc_frame.setVisible(show_right_toc)
        self.manual_toc_combo.setVisible(not show_right_toc)

    def _english_manual_section(
        self,
        title: str,
        cards: list[tuple[str, list[QWidget]]],
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(14)
        layout.addWidget(self._sec(title))
        for card_title, widgets in cards:
            layout.addWidget(self._card(card_title, widgets))
        layout.addStretch()
        return page

    def _build_english_manual_sections(self) -> list[QWidget]:
        return [
            self._english_manual_section("Getting started", [
                ("First computer setup", [
                    self._step(1, "Enter the company name. Start date and Version are filled automatically."),
                    self._step(2, "Keep the Database path, select Browse, or use Import for an existing database."),
                    self._step(3, "Discover or add printers manually, then select and verify up to three devices."),
                    self._step(4, "Set A4/A3 Color and B&W prices, billing-cycle end day and waste-paper discount."),
                    self._step(5, "Review and save. Online Registration completes before the main window opens."),
                    self._tip("If Online Registration cannot connect, the Wizard offers the Offline License flow."),
                ]),
                ("Additional computer setup", [
                    self._txt("An additional desktop can review the company configuration offered by an authorized computer on the same LAN.", bold=True),
                    self._txt("The initial setup copy is separate from continuous shared work. Each computer retains its own registration identity."),
                ]),
            ]),
            self._english_manual_section("Daily workflow", [
                ("Reading printer data", [
                    self._step(1, "Read SNMP identity and Total Meter first."),
                    self._step(2, "Select the compatible Web Connection method automatically and request an Administrator password only when required."),
                    self._step(3, "Store daily Print and Copy data together with the original Legacy counter labels."),
                    self._step(4, "Close the daily record and calculate confirmed usage and cost."),
                    self._tip("A dash means the printer did not provide the value; it does not mean zero."),
                ]),
                ("Device information", [
                    self._txt("Each device card shows model, serial number, Total Meter, available toner, paper-tray status and raw counters."),
                    self._txt("Closing the window may keep KOMI Report running in System Tray. Choose Exit to stop the application completely."),
                ]),
            ]),
            self._english_manual_section("Reports", [
                ("Normalized reports", [
                    self._txt("Overview, Users, Printers and Usage keep Print and Copy separate.", bold=True),
                    self._txt("The opening Meter row is a reference baseline only and is never included in usage or cost."),
                    self._txt("The waste-paper checkbox switches net/gross cost without changing page counts."),
                ]),
                ("Legacy and Excel", [
                    self._txt("Legacy preserves exact printer counter labels such as A5, Large Size or FAX instead of forcing them into A3/A4."),
                    self._txt("Excel exports six sheets: three normalized views and three Legacy views for printer, user and daily data."),
                    self._txt("Use Export Excel in the Reports header, then choose dates and a destination. A popup shows stage progress, percent, completed users and elapsed time while export runs in the background. Web evidence Excel/PDF exports also run in the background; select a remarks row and use Read full remarks to inspect all evidence. Cancel, Escape or closing the popup requests cancellation; it stays visible until the worker stops. Duplicate requests stay disabled until completion. Cancellation or failure preserves an existing destination file."),
                ]),
            ]),
            self._english_manual_section("Settings", [
                ("Everyday settings", [
                    self._txt("Manage printers and prices, billing, automatic readings and Registration status from the main Settings page."),
                ]),
                ("Advanced Settings", [
                    self._txt("Advanced Settings expands on the same page. It includes Database path, backup/restore/integrity, Auto-start, logs, maintenance, LAN Web Report and Parser Mapping.", bold=True),
                    self._tip("Back up the Database before Restore, changing its path or starting a new Database."),
                ]),
                ("LAN Web Report", [
                    self._txt("LAN Web Report starts automatically. Read-only access may be allowed without a password; staff and edit functions remain protected."),
                ]),
            ]),
            self._english_manual_section("System V5.2", [
                ("Registration and background operation", [
                    self._step(1, "Online Registration is the normal first-run mode."),
                    self._step(2, "Status and aggregate Total Meter are scheduled approximately every six hours."),
                    self._step(3, "The Host marks a missing Desktop connection only after three days; this is not a printer-failure claim."),
                    self._step(4, "Offline License stops Registration, Status and Meter telemetry without deleting local reports."),
                ]),
                ("Computers and recovery", [
                    self._txt("Primary and Secondary desktops can run together and continue serving the same read-only Web Report on the LAN."),
                    self._txt("Back up the Database before restore, reset or moving the data path."),
                ]),
            ]),
        ]

    def _tab_v5_system(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(14)
        layout.addWidget(self._sec("การทำงานเบื้องหลังของ KOMI Report V5.2"))
        layout.addWidget(
            self._txt(
                "โปรแกรมเก็บฐานข้อมูลและรายงานไว้ในเครือข่ายลูกค้า ส่วนการลงทะเบียนส่งเฉพาะข้อมูลที่ระบุในประกาศ "
                "หัวข้อนี้อธิบายการอ่านเครื่อง การทำงานร่วมกัน และการลงทะเบียน Online/Offline"
            )
        )
        layout.addWidget(self._card("คอมพิวเตอร์ร่วมกันและ Web Report", [
            self._step(1, "คอมเครื่องแรกตั้งค่าเครื่องพิมพ์ ราคา รอบบิล และฐานข้อมูล"),
            self._step(2, "คอมเพิ่มเติมตรวจและรับชุดค่าบริษัทที่ได้รับสิทธิ์มาใช้ โดยคงตัวตนการลงทะเบียนของตนเอง"),
            self._step(3, "รับค่าติดตั้งครั้งแรกเพื่อใช้ Slot ชุดเดียวกัน การเปลี่ยนค่าภายหลังยังไม่ส่งต่ออัตโนมัติ · Web Report เปิดดูผ่านเครื่องที่ยังออนไลน์"),
            self._step(4, "เมื่อปิดหน้าต่าง Agent ทำงานต่อที่ System Tray; ใช้เมนูออกจาก Agent เมื่อต้องการหยุดจริง"),
            self._tip("ก่อนรับค่าติดตั้งครั้งแรก ให้ตรวจชื่อบริษัท รายการเครื่อง ราคา และรอบบิลบนหน้าสรุปทุกครั้ง"),
        ]))
        layout.addWidget(self._card("การลงทะเบียนและสถานะ", [
            self._step(1, "Online Registration เป็นวิธีปกติ และทำงานก่อนเปิดหน้าหลักครั้งแรก"),
            self._step(2, "เมื่อลงทะเบียนแล้ว โปรแกรมส่งสถานะโดยประมาณทุก 6 ชั่วโมง พร้อม Total Meter รวมของเครื่องที่เลือก"),
            self._step(3, "Host จะแจ้งการขาดการเชื่อมต่อเมื่อไม่ได้รับข้อมูลเกิน 3 วัน โดยไม่สรุปว่าเครื่องพิมพ์เสีย"),
            self._step(4, "กรณีไม่มี Internet ให้ส่งออก .komirequest และนำเข้า .komilicense ที่ได้รับจากผู้ดูแล"),
            self._tip("Offline License ปิดการส่ง Registration, Status และ Meter แต่ไม่ลบฐานข้อมูลหรือรายงานในเครื่อง"),
        ]))
        self._manual_diagram_cards = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._manual_diagram_cards.setSpacing(14)
        self._manual_diagram_cards.addWidget(
            self._diagram_card(
                "1. กฎการอ่านข้อมูลอัตโนมัติ",
                "ดูเส้นทาง Scheduler และการอ่านข้อมูล ตั้งแต่ SNMP, Web throttle, RAM ไปจนถึง Daily Record",
                "sync-rule-flowchart.png",
                "sync-rule-flowchart.html",
            )
        )
        self._manual_diagram_cards.addWidget(
            self._diagram_card(
                "2. การเก็บข้อมูล",
                "ดูความต่างระหว่าง RAM ชั่วคราว, JSON Daily Cache, SQLite และข้อมูลที่ History/Billing ใช้",
                "data-storage-overview.png",
                "data-storage-overview.html",
            )
        )
        layout.addLayout(self._manual_diagram_cards)
        layout.addWidget(
            self._tip(
                "Diagram เป็นไฟล์ Local ภายในโปรแกรม เปิดดูได้โดยไม่ต้องเชื่อมต่อ Internet "
                "และไม่ส่งข้อมูลเครื่องพิมพ์ออกภายนอก"
            )
        )
        layout.addStretch()
        return page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "manual_toc_frame"):
            self._update_manual_responsive_layout(event.size().width())
        if not hasattr(self, "_manual_diagram_cards"):
            return
        direction = (
            QBoxLayout.Direction.LeftToRight
            if event.size().width() >= 1160
            else QBoxLayout.Direction.TopToBottom
        )
        if self._manual_diagram_cards.direction() != direction:
            self._manual_diagram_cards.setDirection(direction)
            self.updateGeometry()

    # ══════════════════════════════════════════════════════
    # TAB 0 — ภาพรวมการทำงานของโปรแกรม
    # ══════════════════════════════════════════════════════
    def _tab_workflow(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("การใช้งานประจำวัน"))

        # ─ วงจรการทำงานหลัก ──────────────────────────────
        lay.addWidget(self._card("วงจรการอ่านข้อมูล", [
            self._txt(
                "KOMI Report V5.2 อ่านข้อมูลจากเครื่อง Konica Minolta ที่เลือกไว้สูงสุด 3 เครื่อง "
                "ตามตารางเวลา หรือสั่งอ่านทันทีจากหน้าอุปกรณ์"
            ),
            self._step(1, "ตรวจสถานะและ Total Meter ผ่าน SNMP ก่อน"),
            self._step(2, "อ่าน Web Connection ด้วยวิธีที่รุ่นนั้นรองรับโดยอัตโนมัติ และขอรหัส Administrator เฉพาะเมื่อจำเป็น"),
            self._step(3, "เก็บข้อมูลรายวัน แยก Print และ Copy พร้อมชื่อ Counter ต้นทางสำหรับ Legacy"),
            self._step(4, "ปิด Daily Record แล้วสร้างยอดใช้งานและค่าใช้จ่ายของวันนั้น"),
            self._step(5, "แสดงผลในภาพรวม รายงาน และ Excel โดยใช้ช่วงวันที่เดียวกัน"),
        ]))

        # ─ โครงสร้างข้อมูล ───────────────────────────────
        lay.addWidget(self._card("ข้อมูลที่เห็นในหน้าอุปกรณ์", [
            self._txt("• Model, Serial Number และ Total Meter ล่าสุด"),
            self._txt("• ระดับหมึก C / M / Y / K เมื่อรุ่นนั้นส่งค่า"),
            self._txt("• ถาดกระดาษ ขนาด/ชนิดกระดาษ และสถานะ Ready, Near Empty หรือ Empty"),
            self._txt("• Counter รายละเอียดจากเครื่อง และ User Authentication / Account Track เมื่อเปิดใช้งาน"),
            self._tip("เครื่องแต่ละรุ่นอาจส่งข้อมูลไม่เท่ากัน เครื่องหมาย — หมายถึงรุ่นนั้นไม่ส่งค่าหรือยังอ่านไม่ได้ ไม่ใช่ค่า 0"),
        ]))

        # ─ การคำนวณค่าใช้จ่าย ────────────────────────────
        lay.addWidget(self._card("การคำนวณรายงาน", [
            self._txt("ยอดใช้งาน = Meter ปลายงวด − Meter ต้นงวด โดยแยก Print/Copy และประเภทกระดาษ", bold=True),
            self._txt("แถว Meter เริ่มต้นมีไว้เป็นหลักฐานฐานเริ่มต้น ไม่รวมเป็นยอดใช้งานและไม่คิดค่าใช้จ่าย"),
            self._txt("ค่าใช้จ่ายก่อนส่วนลด = จำนวนหน้า × ราคาต่อหน้า"),
            self._txt("ค่าใช้จ่ายสุทธิ = ค่าใช้จ่ายก่อนส่วนลด × (1 − % กระดาษเสีย / 100)"),
            self._tip("เปิดหรือปิด checkbox คิดรวม % กระดาษเสียในหน้า Reports ได้ โดยจำนวนหน้าไม่เปลี่ยน"),
        ]))

        # ─ ความสัมพันธ์ระหว่าง Parser กับการนำเข้า ──────
        lay.addWidget(self._card("Legacy และ Parser Mapping", [
            self._txt(
                "Legacy แสดงชื่อ Counter ตรงตามที่เครื่องส่ง เช่น A5, Large Size หรือ FAX โดยไม่บังคับแปลงเป็น A3/A4",
                bold=True,
            ),
            self._step(1, "เปิด Settings → การตั้งค่าขั้นสูง → ตรวจสอบ Parser Mapping"),
            self._step(2, "เลือก Slot แล้วตรวจ Raw Data เทียบกับช่อง Database"),
            self._step(3, "แก้ Mapping เฉพาะรายการที่ผิด แล้วบันทึกกลับ"),
            self._tip("ถ้าไม่แน่ใจให้เก็บเป็น No Mapping เพื่อไม่ให้ยอดถูกรวมผิดประเภท"),
        ]))

        # ─ วันตัดรอบบิล ──────────────────────────────────
        lay.addWidget(self._card("ปิดโปรแกรมให้ถูกวิธี", [
            self._txt("ค่าเริ่มต้นเมื่อกดปิดหน้าต่าง โปรแกรมยังทำงานต่อใน System Tray เพื่ออ่านข้อมูลตามเวลา", bold=True),
            self._step(1, "ต้องการเปิดหน้าต่างอีกครั้ง ให้คลิกไอคอน KOMI Report ใน System Tray"),
            self._step(2, "ต้องการหยุดโปรแกรมจริง ให้เลือก Exit / ออกจากโปรแกรมจากเมนู System Tray"),
            self._step(3, "ปรับพฤติกรรมนี้ได้ใน Settings → การตั้งค่าขั้นสูง → โปรแกรม Log และการบำรุงรักษา"),
            self._tip("ก่อน Backup, Restore หรือลบ Database ควร Exit โปรแกรมให้หยุดสนิท"),
        ]))

        lay.addStretch()
        return page

    # ══════════════════════════════════════════════════════
    # TAB 1 — เริ่มต้นใช้งาน / Parser Setup
    # ══════════════════════════════════════════════════════
    def _tab_firstrun(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("เริ่มต้นใช้งาน KOMI Report V5.2"))

        lay.addWidget(self._card("คอมเครื่องแรก — ตั้งค่าครั้งแรก", [
            self._step(1, "กรอกชื่อบริษัท วันที่เริ่มใช้งานและ Version จะแสดงให้อัตโนมัติ"),
            self._step(2, "ตรวจ Database Path ใช้ [Browse] เมื่อต้องการเปลี่ยนตำแหน่ง หรือ [Import] เมื่อต้องการนำฐานข้อมูลเดิมมาใช้"),
            self._step(3, "อ่านประกาศข้อมูลการลงทะเบียน แล้วกดค้นหาเครื่องพิมพ์ใน LAN หรือกำหนดช่วง IP/เพิ่ม IP ด้วยตนเอง"),
            self._step(4, "เลือกไม่เกิน 3 เครื่อง ตรวจ Model, Serial และการเชื่อมต่อให้ผ่าน จากนั้นกำหนด Slot และชื่อจุดติดตั้ง"),
            self._step(5, "ตั้งราคา A4/A3 สีและขาวดำ วันตัดรอบบิล และเปอร์เซ็นต์กระดาษเสีย แล้วตรวจสอบก่อนบันทึก"),
            self._tip("ระหว่างสแกนจะแสดงความคืบหน้า กด Enter ในหน้ากำหนดช่วง IP เพื่อเริ่มสแกนได้"),
        ]))

        lay.addWidget(self._card("คอมเพิ่มเติม — รับค่าบริษัท", [
            self._step(1, "เมื่อพบคอมที่ตอบกลับใน LAN โปรแกรมแสดงข้อเสนอให้นำการตั้งค่ามาตรวจ"),
            self._step(2, "ตรวจชื่อบริษัท Slot เครื่องพิมพ์ ราคา รอบบิล และสิทธิ์เข้าร่วมก่อนรับค่า"),
            self._step(3, "ถ้าไม่พบคอมที่ต้องการ ให้กดค้นหาอีกครั้ง หรือกรอก IP ของคอมที่ให้บริการ"),
            self._tip("การรับค่าเริ่มต้นไม่คัดลอกตัวตนของอีกคอม ตรวจสถานะการเชื่อมสมาชิกและคิว Sync ในการตั้งค่าเครือข่าย"),
        ]))

        lay.addWidget(self._card("ลงทะเบียนก่อนเปิดโปรแกรม", [
            self._step(1, "หลังคลิก [บันทึกและเปิดโปรแกรม] ระบบจะลงทะเบียน Online และแสดงสถานะรอผล"),
            self._step(2, "เมื่อลงทะเบียนสำเร็จจะแสดงเครื่องหมายถูก แล้วเปิดหน้าหลักอัตโนมัติ"),
            self._step(3, "ถ้าเชื่อมต่อ Host ไม่ได้ ให้เลือก [ลงทะเบียน Offline] เพื่อส่งออก Request และนำเข้า License ที่ได้รับ"),
            self._tip("Offline License จะหยุดการส่ง Registration, Status และ Meter แต่ข้อมูลรายงานในเครื่องยังทำงานตามปกติ"),
        ]))

        lay.addWidget(self._card("ตรวจผลครั้งแรก", [
            self._step(1, "เปิดเมนูอุปกรณ์ แล้วกด [อ่านข้อมูลตอนนี้]"),
            self._step(2, "ตรวจชื่อรุ่น, Serial, Total Meter, หมึก, ถาดกระดาษ และ Counter จากเครื่องจริง"),
            self._step(3, "ถ้าข้อมูลไม่อัปเดต ให้เปิด Settings → สถานะและประวัติ"),
            self._tip("สถานะ Online เพียงอย่างเดียวไม่ยืนยันว่าข้อมูล Meter ครบ ต้องตรวจ Total Meter และเวลาอ่านล่าสุดด้วย"),
        ]))

        lay.addStretch()
        return page

    # ══════════════════════════════════════════════════════
    # TAB 1 — วิธีดาวน์โหลดไฟล์ TXT จากเครื่อง Konica Minolta
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # TAB 2 — วิธีนำเข้าไฟล์ (Import)
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # TAB 3 — หน้า Overview
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # TAB 4 — หน้า History
    # ══════════════════════════════════════════════════════
    def _tab_history(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("หน้า Reports — การใช้งานและค่าใช้จ่าย"))

        lay.addWidget(self._card("เลือกช่วงรายงาน", [
            self._txt("เลือกวันที่เริ่มต้นและวันที่สิ้นสุดจากคนละช่อง แล้วใช้ช่วงเดียวกันกับทุกแท็บ", bold=True),
            self._step(1, "Overview สรุป Print สี/ขาวดำ, Copy สี/ขาวดำ, ยอดรวม และค่าใช้จ่าย"),
            self._step(2, "Users แสดงผู้ใช้หรือ Account แยกตามเครื่องและประเภทงานที่เครื่องส่งมา"),
            self._step(3, "Printers แสดงกราฟทุกเครื่องพร้อมกัน; การเลือกแถวเปลี่ยนเฉพาะรายละเอียด Meter"),
            self._step(4, "Usage และ Legacy ใช้มุมมอง D / M / Y และดูรวมทุกเครื่องหรือแยกตามเครื่อง"),
        ]))

        lay.addWidget(self._card("Usage — รายงานมาตรฐาน", [
            self._txt("หัวตารางแบ่ง Print และ Copy อย่างชัดเจน แล้วแยก A3/A4 สี ขาวดำ และ Other", bold=True),
            self._step(1, "แถวแรกสุดเป็น Meter เริ่มต้น ใช้เป็นฐานอ้างอิงเท่านั้น"),
            self._step(2, "Meter เริ่มต้นไม่รวมในยอดใช้งาน ยอดรวม หรือค่าใช้จ่าย"),
            self._step(3, "checkbox [คิดรวม % กระดาษเสีย] เปิดไว้เป็นค่าเริ่มต้น ปิดได้เพื่อดูค่าใช้จ่ายก่อนส่วนลด"),
            self._tip("ตารางกว้างและเลื่อนซ้าย–ขวาได้เพื่อรักษาชื่อคอลัมน์ Print/Copy ให้ครบ"),
        ]))

        lay.addWidget(self._card("Legacy — ข้อมูลตรงจากเครื่อง", [
            self._txt("แสดงชื่อ Counter ตามที่เครื่องส่งจริง เช่น A5, Large Size, FAX หรือชื่อเฉพาะรุ่น โดยไม่บังคับ Map เป็น A3/A4", bold=True),
            self._step(1, "เลือกทุกเครื่องเพื่อเปรียบเทียบ Counter ต้นทางของ Slot 1–3"),
            self._step(2, "เลือกตามเครื่องหรือผู้ใช้เพื่อดูว่ารายการนั้นเกิดจากเครื่องใด"),
            self._step(3, "ถ้าชื่อหรือ Mapping ผิด ให้เปิด Settings → การตั้งค่าขั้นสูง → Parser Mapping"),
            self._tip("No Mapping หมายถึงเก็บข้อมูลต้นทางไว้ แต่ไม่รวมเข้าหมวดมาตรฐานที่อาจทำให้ยอดผิด"),
        ]))

        lay.addWidget(self._card("หลักฐาน Web / หมายเหตุ", [
            self._txt("เลือกแถวแล้วกด [อ่านหมายเหตุเต็ม] หรือดับเบิลคลิกเพื่ออ่านข้อความทั้งหมด Excel และ PDF ส่งออกเบื้องหลังพร้อมแถบความคืบหน้าและปุ่มยกเลิก ไฟล์เดิมจะยังอยู่เมื่อยกเลิกหรือส่งออกไม่สำเร็จ"),
        ]))
        lay.addWidget(self._card("ส่งออก Excel", [
            self._step(1, "กด [ส่งออก Excel] ที่หัวหน้า Reports แล้วเลือกช่วงวันที่และตำแหน่งบันทึก"),
            self._step(2, "ไฟล์มี 6 ชีท: รายเครื่อง, ผู้ใช้, รายวัน และ Legacy ของทั้งสามมุมมอง"),
            self._step(3, "ชีทมาตรฐานแยก Print/Copy; ชีท Legacy คงชื่อประเภทจากเครื่องไว้ตรงๆ"),
            self._step(4, "popup แสดงแถบความคืบหน้า เปอร์เซ็นต์ตามขั้นตอน จำนวนผู้ใช้และเวลาที่ใช้ ระหว่างรอยังใช้หน้าจอได้ กดยกเลิก/กากบาท/Escape แล้วรอจนงานหยุด งานที่ไม่สำเร็จไม่เขียนทับไฟล์เดิม"),
            self._tip("ตรวจชื่อบริษัท ช่วงวันที่ และวันเวลาส่งออกที่หัวเอกสารก่อนนำไปใช้งาน"),
        ]))

        lay.addStretch()
        return page

    # ══════════════════════════════════════════════════════
    # TAB 5 — หน้า Settings
    # ══════════════════════════════════════════════════════
    def _tab_settings(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(14)

        lay.addWidget(self._sec("หน้า Settings — ตั้งค่าโปรแกรม"))

        lay.addWidget(self._card("การตั้งค่าที่ใช้ประจำ", [
            self._step(1, "เครื่องพิมพ์และราคา — เพิ่มหรือเปลี่ยนเครื่อง 1–3 เครื่อง และแก้ราคาต่อหน้า"),
            self._step(2, "รอบบิล — วันสิ้นสุดรอบบิลและเปอร์เซ็นต์กระดาษเสีย"),
            self._step(3, "การอ่านข้อมูลอัตโนมัติ — เปิดพร้อมระบบและตารางเวลาที่แนะนำ"),
            self._step(4, "การลงทะเบียน — ดูสถานะล่าสุด ลองส่งอีกครั้ง หรือใช้ Offline License"),
            self._tip("หน้า Settings ไม่มีรหัสผ่าน แต่คำสั่งที่ลบหรือเขียนทับข้อมูลยังต้องยืนยัน"),
        ]))

        lay.addWidget(self._card("การตั้งค่าขั้นสูง — แสดงในหน้าเดิม", [
            self._txt("กด [เปิดการตั้งค่าขั้นสูง] แล้วข้อมูลทั้งหมดจะขยายในหน้า Settings เดิม ไม่เปิดหน้าต่างใหม่", bold=True),
            self._step(1, "ฐานข้อมูล: ดู/เปลี่ยน Path, Backup, Restore, ตรวจความสมบูรณ์ และเริ่มฐานข้อมูลใหม่"),
            self._step(2, "โปรแกรม: Auto-start, ทำงานใน System Tray และพฤติกรรมเมื่อปิดหน้าต่าง"),
            self._step(3, "Log: เปิดโฟลเดอร์ ส่งออกชุด Support และกำหนดระยะเวลาเก็บ"),
            self._step(4, "บำรุงรักษา: ล้าง Cache/ไฟล์ชั่วคราว หรือคืนค่าการตั้งค่าโดยไม่ลบฐานข้อมูล"),
            self._tip("Backup ก่อน Restore เปลี่ยน Path หรือลบ Database ทุกครั้ง"),
        ]))

        lay.addWidget(self._card("รายงานผ่าน LAN", [
            self._step(1, "Web Report บน LAN เปิดให้อัตโนมัติและแสดง URL สำหรับเครื่องอื่น"),
            self._step(2, "เลือกอนุญาตให้เปิดรายงานแบบอ่านอย่างเดียวโดยไม่ใช้รหัสได้"),
            self._step(3, "กดเปิดหน้า Web หรือคัดลอกที่อยู่ LAN แล้วทดสอบจากเครื่องอื่นในเครือข่ายเดียวกัน"),
            self._tip("สิทธิ์เจ้าหน้าที่และการแก้ไขยังคงต้องยืนยันตัวตน แม้เปิดรายงานทั่วไปโดยไม่ใช้รหัส"),
        ]))

        lay.addWidget(self._card("Parser Mapping", [
            self._step(1, "เปิดหน้าต่าง Parser Mapping จากการตั้งค่าขั้นสูง"),
            self._step(2, "เลือก Slot แล้วเปรียบเทียบ Raw Data กับหมวด Database"),
            self._step(3, "แก้เฉพาะรายการที่ Map ผิด แล้วบันทึกแยกตาม Serial Number"),
            self._tip("รายการที่ไม่แน่ใจควรเป็น No Mapping เพื่อป้องกันการรวมยอดผิด"),
        ]))

        lay.addStretch()
        return page

    def refresh(self):
        """ไม่ต้องโหลดข้อมูลเพิ่มเติม — เนื้อหาคงที่"""
        pass

    def minimumSizeHint(self) -> QSize:
        """Allow the manual to reflow inside the desktop minimum viewport."""
        hint = super().minimumSizeHint()
        return QSize(min(760, hint.width()), hint.height())
