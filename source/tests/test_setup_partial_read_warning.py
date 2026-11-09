from PyQt6.QtWidgets import QApplication

import database
from test_setup_wizard_v5 import _add_selected_device, _wizard_database
from ui.setup.wizard import SetupWizardV5


def test_partial_read_is_not_shown_as_unqualified_success(tmp_path, monkeypatch):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    wizard = None
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "Synthetic", "192.0.2.10")
        wizard._configs()
        warning = "Total Meter available; user counter response rejected"
        wizard._test_result(0, dict(online=True, web_ok=True, model="bizhub 950i",
            serial="SN-10", total=100, web_warnings=(warning,)))
        status = wizard.device_table.item(0, 4)
        assert "มีคำเตือน" in status.text()
        assert "พร้อมใช้งาน" not in status.text()
        assert warning in status.toolTip()
        messages = []
        monkeypatch.setattr(wizard, "_show_wizard_message", lambda title, message: messages.append(message))
        wizard._device_table_action(0, 4)
        assert messages == [warning]
    finally:
        if wizard is not None:
            wizard.close()
        app.processEvents()
        database.set_db_path(original_path)
