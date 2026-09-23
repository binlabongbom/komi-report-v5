import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QFrame, QLabel
from PyQt6.QtTest import QTest

from pages import PageManual


def test_deferred_manual_shows_first_section_then_completes_document():
    app = QApplication.instance() or QApplication([])
    page = PageManual(lazy=True)
    assert len(page._thai_manual_sections) == 1
    page.show()
    for _ in range(30):
        if len(page._thai_manual_sections) == 5:
            break
        QTest.qWait(100)
    assert len(page._thai_manual_sections) == 5
    assert page.findChild(QLabel, 'manual_doc_image_13') is not None
    page.close()
    app.processEvents()


def test_deferred_manual_builds_thai_after_switching_from_english():
    from i18n import get_language, set_language
    app = QApplication.instance() or QApplication([])
    previous = get_language()
    page = None
    try:
        set_language('en')
        page = PageManual(lazy=True)
        page._apply_i18n_visibility('th')
        assert len(page._thai_manual_sections) == 1
        for _ in range(30):
            if len(page._thai_manual_sections) == 5:
                break
            QTest.qWait(100)
        assert len(page._thai_manual_sections) == 5
    finally:
        if page is not None:
            page.close()
            app.processEvents()
        set_language(previous)


def test_manual_constructs_selected_language_only_and_reuses_it():
    from i18n import get_language, set_language
    previous = get_language()
    set_language('en')
    page = None
    try:
        page = PageManual()
        assert len(page._english_manual_sections) == 5
        assert not page._thai_manual_sections
        english = tuple(page._english_manual_sections)
        page._apply_i18n_visibility('th')
        assert len(page._thai_manual_sections) == 5
        thai = tuple(page._thai_manual_sections)
        page._apply_i18n_visibility('en')
        page._apply_i18n_visibility('th')
        assert tuple(page._english_manual_sections) == english
        assert tuple(page._thai_manual_sections) == thai
    finally:
        if page is not None:
            page.close()
        set_language(previous)


def test_manual_is_one_continuous_page_with_clickable_right_toc():
    app = QApplication.instance() or QApplication([])
    page = PageManual()
    page.resize(1200, 760)
    page.show()
    app.processEvents()

    assert page.manual_scroll.verticalScrollBar().maximum() > 0
    assert page.manual_toc_frame.isVisible()
    assert not page.manual_toc_combo.isVisible()
    assert [button.text() for button in page.manual_toc_buttons] == [
        "เริ่มต้นใช้งาน",
        "วิธีทำงาน",
        "รายงาน",
        "ตั้งค่า",
        "ระบบ V5.2",
    ]
    assert len(page._thai_manual_sections) == 5
    assert all(section.isVisible() for section in page._thai_manual_sections)
    assert not any(section.isVisible() for section in page._english_manual_sections)

    page._scroll_to_manual_section(3)
    app.processEvents()
    assert page.manual_scroll.verticalScrollBar().value() > 0
    assert page.manual_toc_buttons[3].isChecked()

    page._apply_i18n_visibility("en")
    app.processEvents()
    assert [button.text() for button in page.manual_toc_buttons] == [
        "Getting started",
        "Daily workflow",
        "Reports",
        "Settings",
        "System V5.2",
    ]
    assert not any(section.isVisible() for section in page._thai_manual_sections)
    assert all(section.isVisible() for section in page._english_manual_sections)
    assert page.manual_sync_button.isEnabled()
    assert page.manual_storage_button.isEnabled()
    assert page._manual_asset_available(page._manual_asset("sync-rule-flowchart.png"))
    assert page._manual_asset_available(page._manual_asset("data-storage-overview.png"))
    page.close()
    app.processEvents()


def test_manual_reflows_at_desktop_minimum_and_uses_v52_report_copy():
    app = QApplication.instance() or QApplication([])
    page = PageManual()
    page.resize(794, 4000)
    page.show()
    app.processEvents()

    all_text = "\n".join(label.text() for label in page.findChildren(QLabel))
    assert page.width() == 794
    assert page.minimumSizeHint().width() <= 794
    assert not page.manual_toc_frame.isVisible()
    assert page.manual_toc_combo.isVisible()
    assert "หัวตารางแบ่ง Print และ Copy อย่างชัดเจน" in all_text
    assert "Meter เริ่มต้นไม่รวมในยอดใช้งาน" in all_text
    assert "ไฟล์มี 6 ชีท" in all_text
    assert "การตั้งค่าขั้นสูง — แสดงในหน้าเดิม" in all_text
    assert "Stat Cards (4 ใบ)" not in all_text
    assert "Checkbox [รายละเอียดวันนี้]" not in all_text
    assert "ค่าใช้จ่ายสุทธิ = ค่าใช้จ่ายก่อนส่วนลด × (1 − % กระดาษเสีย / 100)" in all_text
    assert "บวกค่ากระดาษเสีย" not in all_text
    assert "ต้องยืนยันรหัสผ่าน" not in all_text
    assert '150.5' in all_text
    assert 'รายละเอียดเกิน 12 เดือน' in all_text
    assert 'คิวรอยืนยันรับ' in all_text
    page.close()
    app.processEvents()


def test_manual_uses_customer_guide_document_style_and_shared_screenshots():
    app = QApplication.instance() or QApplication([])
    page = PageManual()
    page.resize(1200, 760)
    page.show()
    app.processEvents()

    assert "background:#FFFFFF" in page.manual_content.styleSheet()
    images = [
        page.findChild(QLabel, f"manual_doc_image_{index:02d}")
        for index in range(1, 14)
    ]
    assert all(image is not None for image in images)
    assert any(image._image_path is not None for image in images), "Offscreen pictures should remain undecoded"
    for image in images:
        before = image.sizeHint()
        image.grab()  # forces the same paint path as scrolling into view
        assert image.pixmap() is not None and not image.pixmap().isNull()
        assert image.sizeHint() == before, "Loading a picture must not move the document"
    assert all(image.hasHeightForWidth() for image in images)

    document_blocks = page.findChildren(QFrame, "manual_document_block")
    assert document_blocks
    assert all("border:0" in block.styleSheet() for block in document_blocks)
    assert all("QFrame {" not in block.styleSheet() for block in document_blocks)
    page.close()
    app.processEvents()
