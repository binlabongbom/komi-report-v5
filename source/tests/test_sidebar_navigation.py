from app import SIDEBAR_NAV_ITEMS


def test_sidebar_contains_only_active_v5_workflows() -> None:
    labels = [label for _icon, label in SIDEBAR_NAV_ITEMS]

    assert labels == [
        "ภาพรวม",
        "อุปกรณ์",
        "รายงาน",
        "ตั้งค่า",
    ]
    assert "บันทึกการซิงก์" not in labels
    assert "Read Meter" not in labels
    assert "Connection" not in labels
