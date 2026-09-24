"""Section drafts and callbacks work without constructing the Fleet coordinator."""

from datetime import time, timedelta

import pytest
from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QApplication, QFrame, QVBoxLayout

import database
from services.polling import ScheduleWindow
from ui.settings.sections.billing import BillingSection
from ui.settings.sections.network import NetworkSection
from ui.settings.sections.schedule import ScheduleSection


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    frame = QFrame()
    QVBoxLayout(frame)
    yield frame
    frame.close()
    app.processEvents()


def billing(editor):
    return BillingSection(editor, on_save=lambda: None, on_cancel=lambda: None, on_dirty=lambda: None)


def window(start=8, end=9, *, weekdays=frozenset({0}), label="Morning"):
    return ScheduleWindow(
        start=time(start),
        end=time(end),
        label=label,
        web_interval=timedelta(minutes=15),
        snmp_interval=timedelta(minutes=5),
        weekdays=weekdays,
    )


def test_billing_rejected_commit_preserves_draft_and_database(editor):
    section = billing(editor)
    database.set_cfg("billing_day", "31")
    section.billing_day.setValue(17)
    captured = []
    assert not section.save(lambda values: captured.append(values) or False)
    assert captured[0]["billing_day"] == 17
    assert section.billing_day.value() == 17
    assert database.get_cfg("billing_day") == "31"


def test_billing_does_not_report_success_when_storage_did_not_change(editor):
    section = billing(editor)
    database.set_cfg("billing_day", "31")
    section.billing_day.setValue(17)
    assert not section.save(lambda _values: True)
    assert "ไม่สำเร็จ" in section.billing_save_status.text()


def test_billing_preserves_new_draft_when_confirmation_changes_controls(editor):
    section = billing(editor)
    section.billing_day.setValue(17)

    def commit(values):
        for key, value in values.items():
            database.set_cfg(key, str(value))
        section.billing_day.setValue(18)
        return True

    assert not section.save(commit)
    assert section.billing_day.value() == 18
    assert database.get_cfg("billing_day") == "17"


@pytest.mark.parametrize("invalid", ["end_before_start", "no_weekday"])
def test_schedule_invalid_drafts_are_rejected_by_the_section(editor, invalid):
    section = ScheduleSection(editor, on_save=lambda: None, on_cancel=lambda: None, on_dirty=lambda: None)
    section.replace_windows((window(),))
    _name, clock, weekdays, _snmp, _web = section.row_controls[0]
    if invalid == "end_before_start":
        clock.end.setTime(QTime(7, 0))
    else:
        weekdays.boxes[0].setChecked(False)
    with pytest.raises(ValueError):
        section.values()


def test_schedule_overlap_is_only_rejected_on_shared_days(editor):
    section = ScheduleSection(editor, on_save=lambda: None, on_cancel=lambda: None, on_dirty=lambda: None)
    section.replace_windows((window(8, 10), window(9, 11, weekdays=frozenset({1}))))
    assert len(section.values()) == 2
    section.row_controls[1][2].boxes[0].setChecked(True)
    with pytest.raises(ValueError, match="ซ้อนกัน"):
        section.values()


def test_schedule_cache_preserves_widgets_and_invalidates_after_a_draft_change(editor):
    changes = []
    section = ScheduleSection(
        editor, on_save=lambda: None, on_cancel=lambda: None, on_dirty=lambda: changes.append(True)
    )
    stored = (window(), window(10, 11, label="Later"))
    section.replace_windows(stored)
    original = tuple(section.row_controls)
    section.replace_windows(stored)
    assert tuple(section.row_controls) == original
    original[0][0].setText("Edited")
    assert changes
    section.replace_windows(stored)
    assert section.row_controls[0][0] is not original[0][0]
    assert section.values() == stored
    retained = section.row_controls[1]
    section.remove_window(section.row_controls[0])
    assert section.row_controls == [retained]


def test_network_controls_dispatch_explicit_callbacks_without_mutating_the_parent(editor):
    calls = []
    section = NetworkSection(
        editor.layout(),
        parent=editor,
        on_open=lambda: calls.append("open"),
        on_copy=lambda: calls.append("copy"),
        on_change_code=lambda: calls.append("code"),
        on_authorize=lambda: calls.append("authorize"),
        on_peer_refresh=lambda: None,
        subscribe_changes=lambda callback: None,
        on_save=lambda: calls.append("save"),
        on_cancel=lambda: calls.append("cancel"),
        on_dirty=lambda: calls.append("dirty"),
    )
    assert not hasattr(editor, "web_port")
    section.open_web_button.click()
    section.copy_web_button.click()
    section.web_port.setValue(3012)
    section.web_save_button.setEnabled(True)
    section.web_save_button.click()
    assert calls == ["open", "copy", "dirty", "save"]
    assert section.web_port.parent() is section.web_advanced_panel
