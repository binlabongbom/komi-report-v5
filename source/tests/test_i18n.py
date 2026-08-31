from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from i18n import ENGLISH, THAI, apply_language, set_language, tr, translate_text


def test_translates_and_restores_widget_tree():
    _app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    label = QLabel("ยอดใช้งานรวม")
    combo = QComboBox()
    combo.addItems(["ภาพรวม", "อุปกรณ์"])
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "แนวโน้ม")
    table = QTableWidget(1, 1)
    table.setHorizontalHeaderLabels(("สถานะ",))
    table.setItem(0, 0, QTableWidgetItem("ระหว่างวัน"))
    billing_day = QSpinBox()
    billing_day.setSuffix(" ของเดือน")
    company = QLineEdit()
    company.setPlaceholderText("เช่น บริษัท ตัวอย่าง จำกัด")
    label.setAccessibleName("ภาพรวมการใช้งานและสถานะเครื่องพิมพ์")
    label.setAccessibleDescription("ดูสถานะและประวัติการอ่านข้อมูล")
    label.setToolTip("เลือกข้อมูลที่แสดงในรายงาน")
    for widget in (label, combo, tabs, table, billing_day, company):
        layout.addWidget(widget)

    set_language(ENGLISH)
    apply_language(root)
    assert label.text() == "Total usage"
    assert combo.itemText(0) == "Overview"
    assert combo.itemText(1) == "Devices"
    assert tabs.tabText(0) == "Trends"
    assert table.horizontalHeaderItem(0).text() == "Status"
    assert table.item(0, 0).text() == "Provisional"
    assert billing_day.suffix() == " of the month"
    assert company.placeholderText() == "e.g. Example Company Limited"
    assert label.accessibleName() == "Usage and printer status overview"
    assert label.accessibleDescription() == "View reading status and history"
    assert label.toolTip() == "Choose report data"

    set_language(THAI)
    apply_language(root)
    assert label.text() == "ยอดใช้งานรวม"
    assert combo.itemText(0) == "ภาพรวม"
    assert combo.itemText(1) == "อุปกรณ์"
    assert tabs.tabText(0) == "แนวโน้ม"
    assert table.horizontalHeaderItem(0).text() == "สถานะ"
    assert table.item(0, 0).text() == "ระหว่างวัน"
    assert billing_day.suffix() == " ของเดือน"
    assert company.placeholderText() == "เช่น บริษัท ตัวอย่าง จำกัด"
    assert label.accessibleName() == "ภาพรวมการใช้งานและสถานะเครื่องพิมพ์"
    assert label.accessibleDescription() == "ดูสถานะและประวัติการอ่านข้อมูล"
    assert label.toolTip() == "เลือกข้อมูลที่แสดงในรายงาน"
    root.close()


def test_tr_selects_active_language():
    set_language(THAI)
    assert tr("บันทึก", "Save") == "บันทึก"
    set_language(ENGLISH)
    assert tr("บันทึก", "Save") == "Save"


def test_import_dynamic_messages_are_fully_english():
    set_language(ENGLISH)
    samples = {
        "ปริมาณการใช้งาน": "Usage",
        "ซ่อน Counter ที่มีค่าเป็น 0 (41 รายการ)": "Hide zero-value counters (41 items)",
        "ตรวจผลรวม 16 จุด · ตรงกันทั้งหมด": "Validate totals 16 checks · all matched",
        "User Authentication / Account Track (RAM · ดูอย่างเดียว)": "User Authentication / Account Track (RAM · read-only)",
        "ไม่พบ User Authentication / Account Track ที่เปิดใช้งาน": "No enabled User Authentication / Account Track data",
        "ยืนยันแล้ว 3,000 · วันนี้ +0": "Posted 3,000 · Now +0",
        "ตอนนี้อยู่ในช่วง Normal · SNMP ทุก 5 นาที": "Current schedule window: Normal · SNMP every 5 minutes",
        "กำลังเริ่มต้นการอ่าน 1 เครื่อง": "Starting readings for 1 printers",
        "รอ Scheduler เริ่มรอบแรก หรือกดอ่านข้อมูลตอนนี้": "Waiting for the first scheduler cycle, or select Read now",
        "Meter เริ่มต้น": "Opening meter",
        "ค่า Meter ครั้งแรกที่บันทึกไว้ ใช้เป็นข้อมูลอ้างอิงเท่านั้น ไม่รวมในยอดใช้งาน กราฟ หรือค่าใช้จ่าย": "The first recorded meter is for reference only and is excluded from usage, charts, and cost.",
    }
    for source, expected in samples.items():
        assert translate_text(source) == expected
    set_language(THAI)
