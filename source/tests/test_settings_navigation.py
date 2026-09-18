"""Exercise the shared tab shell and the forms it hosts."""

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QAbstractButton

import database
import v5_pages
from i18n import apply_language, set_language
from pages import PageSettings
from test_settings_v5 import _WebServiceDouble
from ui.cloud_reports import CloudReportsWidget
from ui.page_tabs import PageTabs
from v5_pages import PageSettingsV5


@pytest.fixture
def settings(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    set_language("th")
    monkeypatch.setattr(v5_pages, "web_service_manager", lambda: _WebServiceDouble(tmp_path))
    monkeypatch.setattr(v5_pages, "configure_autostart", lambda *a, **kw: tmp_path / "autostart")
    monkeypatch.setattr(v5_pages, "confirm_shared_settings", lambda *_: True)
    from services.device_config import DeviceConfig, DeviceConfigRepository
    database.set_cfg("company_name", "Synthetic settings company")
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Synthetic Printer", "192.0.2.10")])
    page = PageSettingsV5(PageSettings())
    page.resize(824, 768)
    page.show()
    app.processEvents()
    yield page
    page.close()
    app.processEvents()
    set_language("th")


@pytest.mark.parametrize("language", ["th", "en"])
def test_sections_use_one_tab_shell_and_share_the_schedule(settings, language):
    set_language(language)
    apply_language(settings)
    expected = ["ทั่วไป", "การทำงานอัตโนมัติ", "สถานะและประวัติ", "ขั้นสูง"] if language == "th" else [
        "General", "Automation", "Status and history", "Advanced",
    ]
    assert [settings.section_tabs.tabText(i) for i in range(4)] == expected
    assert isinstance(settings.section_tabs, PageTabs)
    assert settings.section_tabs.tabBar().tabRect(0).left() == 0
    assert settings.fleet_content.billing_editor.isVisibleTo(settings)
    settings.section_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    assert settings.activity.timeline_page.isVisibleTo(settings)
    assert settings.fleet_content.schedule_task_editor.isVisibleTo(settings)
    assert settings.activity.tabs.count() == 4
    assert not settings.fleet_content.billing_editor.isVisibleTo(settings)
    settings.section_tabs.setCurrentIndex(2)
    assert settings.activity.isVisibleTo(settings)
    settings.activity.tabs.setCurrentWidget(settings.activity.counter_reviews)
    assert settings.activity.counter_reviews.isVisibleTo(settings)
    settings.section_tabs.setCurrentIndex(3)
    assert settings.fleet_content.support_task_editor.isVisibleTo(settings)


def test_schedule_shortcut_opens_editor_in_the_same_settings_window(settings):
    settings.show_activity()
    button = next(button for button in settings.activity.findChildren(QAbstractButton)
                  if button.text() == "ตั้งเวลาอ่านข้อมูล" and button.isVisibleTo(settings))
    button.click()
    QApplication.processEvents()
    assert settings.section_tabs.currentIndex() == 1
    assert settings.fleet_content.schedule_editor.isVisibleTo(settings)
    assert settings.schedule_page.verticalScrollBar().value() > 0


def test_tab_switch_preserves_unsaved_values_then_save_keeps_form_open(settings, monkeypatch):
    notices = []
    monkeypatch.setattr(v5_pages, "show_compact_information", lambda *args: notices.append(args))
    field = settings.fleet_content.billing_day
    field.setValue(17)
    settings.section_tabs.setCurrentIndex(1)
    assert notices
    assert settings.section_tabs.currentIndex() == 0
    assert field.value() == 17
    settings.fleet_content.billing_save_button.click()
    assert database.get_cfg("billing_day") == "17"
    assert settings.fleet_content.billing_editor.isVisibleTo(settings)
    settings.section_tabs.setCurrentIndex(1)
    assert settings.section_tabs.currentIndex() == 1
    settings.fleet_content._schedule_row_controls[0][0].setText("Edited window")
    settings.fleet_content._cancel_section("schedule")
    assert settings.fleet_content.schedule_task_editor.isVisibleTo(settings)
    assert settings.fleet_content._schedule_row_controls[0][0].text() != "Edited window"


def test_embedded_plan_still_refreshes_when_status_tab_is_hidden(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(settings.activity, "refresh_timeline", lambda: calls.append(True))
    settings.section_tabs.setCurrentIndex(1)
    calls.clear()
    assert not settings.activity.isVisible()
    settings.activity._refresh_if_visible()
    assert calls == [True]


@pytest.mark.parametrize("width", [824, 1080, 1205])
def test_settings_and_report_tabs_start_at_the_left_edge(settings, width):
    settings.resize(width, 768)
    reports = CloudReportsWidget()
    reports.resize(width, 768)
    reports.show()
    QApplication.processEvents()
    for tab in (settings.section_tabs, settings.activity.tabs, reports.tabs, reports.usage_tabs):
        assert isinstance(tab, PageTabs)
        assert tab.tabPosition() == tab.TabPosition.North
        assert not tab.tabBar().expanding()
        assert tab.tabBar().mapTo(tab, QPoint(0, 0)).x() <= 2
        assert tab.tabBar().tabRect(0).left() == 0
    reports.close()
