import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.quit_confirmation import confirm_meter_collection_exit


@pytest.mark.parametrize('quit_requested', [False, True])
def test_exit_warning_labels_default_and_actual_choice(monkeypatch, quit_requested):
    app = QApplication.instance() or QApplication([])
    def execute(dialog):
        assert dialog.defaultButton().text() == 'เปิดทำงานต่อ'
        assert dialog.escapeButton() == dialog.defaultButton()
        assert 'ไม่สามารถแยกมิเตอร์ในช่วงเวลาดังกล่าวได้' in dialog.text()
        selected = next(button for button in dialog.buttons()
                        if button.text() == ('ปิดโปรแกรม' if quit_requested else 'เปิดทำงานต่อ'))
        selected.click()
        return 0
    monkeypatch.setattr(QMessageBox, 'exec', execute)
    assert confirm_meter_collection_exit() is quit_requested
    app.processEvents()
