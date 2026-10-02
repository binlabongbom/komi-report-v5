"""Cross-page presentation contracts for shared components."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit

from pages import _OverviewMetricCard, _OverviewTonerBar
from ui.cloud_reports import _CloudOverviewMetricCard
from ui.components.metric_card import MetricCard
from ui.components.toner_bar import TonerBar
from v5_pages import PageFleetSettings, _TonerLevelBar


@pytest.mark.parametrize("bar_type", [_OverviewTonerBar, _TonerLevelBar])
@pytest.mark.parametrize("value, percentage, displayed", [
    (None, None, "—"),
    ("not available", None, "—"),
    (0, 0.0, "0%"),
    (-12, 0.0, "0%"),
    (31, 31.0, "31%"),
    (100, 100.0, "100%"),
    (125, 100.0, "100%"),
])
def test_toner_values_distinguish_missing_data_from_empty_supply(bar_type, value, percentage, displayed):
    bar = bar_type("C", value, "#009DC4")
    assert isinstance(bar, TonerBar)
    assert bar.property("tonerKey") == "C"
    assert bar.property("tonerPercent") == percentage
    assert bar.value_text == displayed


@pytest.mark.parametrize("bar_type, name, height, minimum, maximum", [
    (_OverviewTonerBar, "overview_toner_bar", 32, 46, 76),
    (_TonerLevelBar, "toner_level_bar", 20, 42, 16777215),
])
def test_shared_toner_preserves_page_geometry_and_white_corners(bar_type, name, height, minimum, maximum):
    bar = bar_type("K", 100, "#1F2937")
    assert bar.objectName() == name
    assert bar.height() == height
    assert bar.minimumWidth() == minimum
    assert bar.maximumWidth() == maximum
    bar.resize(76, height)
    bar.show()
    QApplication.processEvents()
    image = bar.grab().toImage()
    assert image.pixelColor(0, 0).name() == "#ffffff"
    assert image.pixelColor(image.width() - 1, 0).name() == "#ffffff"


@pytest.mark.parametrize("card_type", [_OverviewMetricCard, _CloudOverviewMetricCard])
def test_metric_details_escape_values_and_restore_plain_text(card_type):
    card = card_type("พิมพ์สี", accent="#1677C8")
    assert isinstance(card, MetricCard)
    detail = "A3 <b>5</b>  |  A4 1 & 2"
    card._set_detail(detail)
    assert card.lbl_detail.textFormat() == Qt.TextFormat.RichText
    document = QTextDocument()
    document.setHtml(card.lbl_detail.text())
    assert document.toPlainText().replace("\u00a0", " ") == detail.replace("  |  ", " | ")
    card._set_detail("<b>No separate counter</b>")
    assert card.lbl_detail.textFormat() == Qt.TextFormat.PlainText
    assert card.lbl_detail.text() == "<b>No separate counter</b>"


def test_overview_metric_retains_number_formatting_and_legacy_detail_attribute():
    card = _OverviewMetricCard("พิมพ์สี")
    card.set_metric(1234567, "A3 0  |  A4 1,234,567")
    assert card.lbl_val.text() == "1,234,567"
    assert card.lbl_diff is card.lbl_detail
    card.set_metric(1234567, available=False)
    assert card.lbl_val.text() == "—"
    assert card.lbl_diff.text() == "ไม่มี Counter แยกประเภท"


def test_settings_shared_header_keeps_callbacks_and_editor_contents():
    # Exercise the real factories without starting the settings page's network
    # readers. Editor lifecycle and persistence are covered by test_settings_v5.
    state = SimpleNamespace(
        _task_card_shell=PageFleetSettings._task_card_shell,
        _task_editors={}, _task_buttons={}, _task_closed_labels={},
    )
    events = []

    def toggled(key, checked):
        events.append((key, checked))
        state._task_editors[key].setVisible(checked)

    state._task_toggle_requested = toggled
    summary = "รายละเอียดที่ยาวเพื่อทดสอบการขึ้นบรรทัดใหม่ " * 4
    action_card, action_detail, action = PageFleetSettings._action_task(state, "Action", summary, "Run")
    editor_card, editor_detail, editor, toggle = PageFleetSettings._expandable_task(
        state, "sample", "Editor", summary,
    )
    action.clicked.connect(lambda: events.append("action"))
    field = QLineEdit("unsaved value", editor)
    editor.layout().addWidget(field)
    for card, detail, button in ((action_card, action_detail, action), (editor_card, editor_detail, toggle)):
        card.resize(340, 220)
        card.show()
        QApplication.processEvents()
        assert detail.wordWrap()
        assert detail.parentWidget() is card
        assert button.parentWidget() is card
        assert button.minimumWidth() == 108
        assert len(card.findChildren(QLabel, options=Qt.FindChildOption.FindDirectChildrenOnly)) == 2
        assert detail.geometry().right() < button.geometry().left()
    action.click()
    assert not action.isCheckable()
    assert toggle.isCheckable()
    assert editor.isHidden()
    toggle.click()
    assert not editor.isHidden()
    toggle.click()
    assert editor.isHidden()
    toggle.click()
    assert field.text() == "unsaved value"
    assert events == ["action", ("sample", True), ("sample", False), ("sample", True)]
