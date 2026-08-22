import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel

from pages import PageManual


def test_manual_contains_offline_sync_and_storage_diagrams():
    app = QApplication.instance() or QApplication([])
    page = PageManual()

    labels = [page.tabs.tabText(index) for index in range(page.tabs.count())]
    assert labels == [
        "เริ่มต้น",
        "วิธีทำงาน",
        "รายงาน",
        "ตั้งค่า",
        "ระบบ V5",
    ]
    assert page.tabs.currentIndex() == 0
    assert page.manual_sync_button.isEnabled()
    assert page.manual_storage_button.isEnabled()
    assert page.tabs.tabBar().expanding()
    assert not page.tabs.tabBar().usesScrollButtons()
    assert page.tabs.tabBar().elideMode() == Qt.TextElideMode.ElideNone
    assert page._manual_asset_available(page._manual_asset("sync-rule-flowchart.png"))
    assert page._manual_asset_available(page._manual_asset("data-storage-overview.png"))
    page.close()
    app.processEvents()


def test_manual_reflows_at_desktop_minimum_and_uses_v5_billing_copy():
    app = QApplication.instance() or QApplication([])
    page = PageManual()
    page.resize(794, 4000)
    page.show()
    app.processEvents()

    all_text = "\n".join(label.text() for label in page.findChildren(QLabel))
    assert page.width() == 794
    assert page.minimumSizeHint().width() <= 794
    assert "Overview แยกยอดยืนยันแล้วจากยอดระหว่างวัน" in all_text
    assert "Stat Cards (4 ใบ)" not in all_text
    assert "Checkbox [รายละเอียดวันนี้]" not in all_text
    assert "ค่าใช้จ่ายสุทธิ = ค่าใช้จ่ายก่อนส่วนลด × (1 − ส่วนลดกระดาษเสีย / 100)" in all_text
    assert "บวกค่ากระดาษเสีย" not in all_text
    assert "ต้องยืนยันรหัสผ่าน" not in all_text
    page.close()
    app.processEvents()
