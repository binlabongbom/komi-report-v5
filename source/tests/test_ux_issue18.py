"""Behavioral regressions for the UX audit (isolated synthetic database)."""
import json
from datetime import date
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QTableWidget, QTableWidgetItem, QTabWidget, QWidget, QMessageBox, QDialog, QPlainTextEdit
from PyQt6.QtTest import QTest
from PyQt6.QtCharts import QChart, QChartView

import database
from i18n import apply_language, set_language, translate_text
from ui.chart_lifecycle import replace_chart
from ui.common_dialogs import PinnedCountersDialog, AllCountersDialog
from ui.cloud_reports import CloudReportsWidget, _CloudOverviewMetricCard


@pytest.fixture(autouse=True)
def restore_language():
    set_language("th")
    yield
    set_language("th")


@pytest.mark.parametrize("language", ["th", "en"])
@pytest.mark.parametrize("amount", ["฿0.00", "฿8,640.00", "฿12,345,678.90"])
def test_full_amount_fits_without_hidden_digits(language, amount):
    set_language(language)
    card = _CloudOverviewMetricCard("ค่าใช้จ่ายสุทธิ", accent="#008000")
    card.resize(220, card.height())
    card.show()
    card.set_metric(amount, "THB")
    QApplication.processEvents()
    assert card.lbl_val.text() == amount
    assert card.lbl_val.fontMetrics().horizontalAdvance(amount) <= card.lbl_val.contentsRect().width()
    card.close()


def test_names_in_data_controls_never_translate_even_if_exact_ui_label():
    root = QWidget()
    table = QTableWidget(3, 1, root)
    combo = QComboBox(root)
    names = ["บริษัท แสดงผล จำกัด", "ภาพรวม", "อุปกรณ์"]
    for row, name in enumerate(names):
        table.setItem(row, 0, QTableWidgetItem(name))
        combo.addItem(name, row)
    data_label = QLabel("ภาพรวม", root)
    data_label.setProperty("i18n_data", True)
    for language in ("en", "th", "en"):
        set_language(language)
        apply_language(root)
        assert [table.item(row, 0).text() for row in range(3)] == names
        assert [combo.itemText(row) for row in range(3)] == names
        assert data_label.text() == "ภาพรวม"


def test_removed_tab_does_not_reuse_another_pages_title():
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "การทำงานอัตโนมัติ")
    tabs.addTab(QWidget(), "ตรวจสอบมิเตอร์")
    set_language("en")
    apply_language(tabs)
    tabs.removeTab(0)
    apply_language(tabs)
    assert tabs.tabText(0) == "Meter review"
    set_language("th")
    apply_language(tabs)
    assert tabs.tabText(0) == "ตรวจสอบมิเตอร์"


def test_export_copy_is_complete_english():
    set_language("en")
    assert translate_text("ช่วงที่แสดงอยู่") == "Displayed period"
    assert translate_text("ช่วงที่เลือก 31 วัน") == "Selected period 31 days"
    assert not any("\u0e00" <= c <= "\u0e7f" for c in translate_text("เปอร์เซ็นต์แสดงความคืบหน้าตามขั้นตอน"))


def test_wizard_review_translates_templates_without_changing_customer_data():
    from v5_pages import SetupWizardV5
    wizard = SetupWizardV5()
    company = "บริษัท แสดงผล จำกัด"
    printer = "ภาพรวม"
    wizard.company_name_input.setText(company)
    wizard._upsert_discovered({"name": printer, "host": "192.0.2.10",
        "model": "อุปกรณ์", "serial": "QA-1", "result": {
            "online": True, "web_ok": True, "total": 200}}, select=True)
    wizard.per_device_price_mode.setChecked(True)
    for language in ("en", "th", "en"):
        wizard._set_wizard_language(language)
        wizard._update_review()
        apply_language(wizard)
        assert company in wizard.review_sections["organization"].text()
        assert printer in wizard.review_sections["devices"].text()
        assert "อุปกรณ์" in wizard.review_sections["devices"].text()
        assert printer in wizard.review_sections["pricing"].text()
        if language == "en":
            for key, label in wizard.review_sections.items():
                text = label.text().replace(company, "").replace(printer, "").replace("อุปกรณ์", "")
                assert not any("\u0e00" <= c <= "\u0e7f" for c in text), (key, text)
            assert "Ready" in wizard.device_table.item(0, 4).text()
            assert wizard.device_table.item(0, 1).text() == "อุปกรณ์"
        else:
            assert "พร้อมใช้งาน" in wizard.review_sections["devices"].text()
    wizard.close()


def test_billing_audit_status_translates_while_printer_name_is_preserved():
    from test_billing_audit_ui import _insert_direct_events
    from v5_pages import PageBillingAudit
    _insert_direct_events(1, printer_name="ภาพรวม")
    page = PageBillingAudit()
    for language in ("en", "th", "en"):
        set_language(language)
        page.refresh()
        apply_language(page)
        assert page.table.item(0, 2).text() == "ภาพรวม"
        if language == "en":
            text = page.coverage.text() + page.table.item(0, 3).text()
            assert not any("\u0e00" <= c <= "\u0e7f" for c in text)
        else:
            assert "มีผล" in page.table.item(0, 3).text()
    page.close()


def test_unavailable_pinned_counter_survives_save_and_clear_requires_explicit_confirmation(monkeypatch):
    repository = SimpleNamespace(list=lambda **_: [])
    database.set_cfg("pinned_counters_json", json.dumps(["counter.total.total"]))
    dialog = PinnedCountersDialog(repository)
    assert dialog.table.rowCount() == 1
    dialog._save()
    assert json.loads(database.get_cfg("pinned_counters_json")) == ["counter.total.total"]
    dialog = PinnedCountersDialog(repository)
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog._save()
    assert json.loads(database.get_cfg("pinned_counters_json")) == ["counter.total.total"]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog._save()
    assert json.loads(database.get_cfg("pinned_counters_json")) == []
    empty = PinnedCountersDialog(repository)
    assert not empty.save_button.isEnabled()


def test_replacing_charts_destroys_every_released_native_chart():
    view = QChartView(QChart())
    destroyed = []
    for index in range(12):
        # Do not hold a Python wrapper for the chart across the replacement;
        # that would change SIP ownership and mask the original leak.
        view.chart().destroyed.connect(lambda *args: destroyed.append(True))
        replace_chart(view, QChart())
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(destroyed) == 12
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_missing_readings_are_not_displayed_as_zero():
    widget = CloudReportsWidget()
    period = ("2026-09-01", "2026-09-30")
    widget.set_data(records=(), daily_records=(), subjects=(), devices=(), period=period, last_sync_at=None)
    assert widget.overview_kpis["total_usage"]._full_value == "—"
    assert widget.overview_kpis["total_cost"]._full_value == "—"
    widget.tabs.setCurrentIndex(2)
    assert widget.printer_metric_cards["usage"]._full_value == "—"
    widget.close()


def test_long_counter_can_be_opened_and_copied_with_keyboard(monkeypatch):
    key = "counter." + "long-name." * 30 + "total"
    dialog = AllCountersDialog("Fixture", {key: 20000})
    assert not dialog.details_button.isEnabled()
    dialog.table.selectRow(0)
    dialog.show()
    captured = []
    def inspect_details(details):
        field = details.findChild(QPlainTextEdit)
        field.selectAll()
        field.copy()
        captured.append(QApplication.clipboard().text())
    monkeypatch.setattr(QDialog, "exec", inspect_details)
    dialog.details_button.setFocus()
    QTest.keyClick(dialog.details_button, Qt.Key.Key_Space)
    assert captured == [key + "\n\n20,000"]
    dialog.close()
