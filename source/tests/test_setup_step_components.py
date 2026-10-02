"""Contracts between independent setup forms and their coordinating wizard."""

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication

from i18n import ENGLISH, set_language
from ui.setup.steps.company import CompanyStep
from ui.setup.steps.devices import DevicesStep
from ui.setup.steps.pricing import PriceRates, PricingSelection, PricingStep
from ui.setup.steps.review import ReviewDevice, ReviewStep, SetupReviewData


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_company_step_validates_locally_and_requests_external_actions(app, tmp_path):
    step = CompanyStep(tmp_path / "company.sqlite3")
    requests = []
    step.database_path_requested.connect(lambda: requests.append("database"))
    step.primary_search_requested.connect(lambda: requests.append("primary"))
    step.privacy_notice_requested.connect(lambda: requests.append("privacy"))
    assert not step.validate()
    assert not step.company_name_error.isHidden()
    step.company_name_input.setText("  Example    Company  ")
    assert step.company_name_error.isHidden()
    assert step.validate()
    assert step.company_name_input.text() == "Example Company"
    step.choose_database_path_button.click()
    step.secondary_join_button.click()
    step.view_privacy_notice_button.click()
    assert requests == ["database", "primary", "privacy"]
    assert not (tmp_path / "company.sqlite3").exists()
    step.close()


def test_pricing_snapshot_is_immutable_and_only_validates_selected_slots(app):
    step = PricingStep()
    step.per_device_price_mode.setChecked(True)
    step.price_rows[2]["a4_color"].setValue(3.25)
    step.effective_date.setDate(QDate(2026, 9, 24))
    step.billing_end_day.setCurrentIndex(14)
    draft = step.selection()
    assert draft.mode == "per_device"
    assert draft.effective_date == date(2026, 9, 24)
    assert draft.billing_day == 15
    assert draft.all_selected_rates_are_zero((0, 1))
    assert not draft.all_selected_rates_are_zero((2,))
    step.price_rows[2]["a4_color"].setValue(8)
    assert draft.by_slot[2].a4_color == 3.25
    with pytest.raises(FrozenInstanceError):
        draft.by_slot[2].a4_color = 99
    step.shared_price_mode.setChecked(True)
    step.shared_price_row["a3_bw"].setValue(1.75)
    assert not step.selection().all_selected_rates_are_zero(())
    assert not step.shared_price_box.isHidden()
    assert step.per_device_price_box.isHidden()
    step.close()


def test_deferred_pricing_preserves_draft_rates_and_hides_billing_in_edit_mode(app):
    step = PricingStep(edit_mode=True)
    step.shared_price_mode.setChecked(True)
    step.shared_price_row["a4_bw"].setValue(1.25)
    assert step.billing_section.isHidden()
    step.deferred_price_mode.setChecked(True)
    assert not step.deferred_price_notice.isHidden()
    assert step.effective_row_widget.isHidden()
    assert step.selection().all_selected_rates_are_zero((0, 1, 2))
    step.shared_price_mode.setChecked(True)
    assert step.shared_price_row["a4_bw"].value() == 1.25
    assert step.billing_section.isHidden()
    step.close()


def test_devices_step_only_emits_actions_and_clamps_scan_progress(app):
    step = DevicesStep()
    actions = []
    step.scan_requested.connect(lambda: actions.append("scan"))
    step.verify_requested.connect(lambda: actions.append("verify"))
    step.scan_button.click()
    step.test_button.click()
    assert actions == ["scan", "verify"]
    assert step.device_table.rowCount() == 0
    step.set_scan_progress(9, 4)
    assert step.scan_progress_bar.value() == 4
    assert "100%" in step.scan_progress_bar.format()
    step.set_scan_progress(-3, 4)
    assert step.scan_progress_bar.value() == 0
    step.fallback_toggle.setChecked(True)
    assert not step.fallback_actions.isHidden()
    step.close()


def test_review_uses_supplied_snapshot_and_escapes_customer_data(app):
    set_language(ENGLISH)
    rates = PriceRates(2.5, 0.75, 5, 1.5)
    selection = PricingSelection("shared", date(2026, 9, 24), rates, (rates,), 2, 31)
    data = SetupReviewData(
        company_name="Acme <Lab>",
        first_started="24/09/2026",
        version="5.2.12",
        devices=(ReviewDevice(0, "Printer <One>", "C450i", 1234),),
        pricing=selection,
        edit_mode=False,
        offline_edition=False,
        platform=("Darwin", "arm64"),
    )
    step = ReviewStep()
    step.render(data)
    assert "Acme &lt;Lab&gt;" in step.review_sections["organization"].text()
    assert "Printer &lt;One&gt;" in step.review_sections["devices"].text()
    assert "1,234" in step.review_sections["devices"].text()
    assert "24/09/2026" in step.review_sections["pricing"].text()
    assert "2.50" in step.review_sections["pricing"].text()
    assert "macOS / arm64" in step.review_sections["registration"].text()
    assert step.registration_status_label.text() == "Pending"
    step.render(replace(data, offline_edition=True))
    assert step.registration_status_label.text() == "Offline ready"
    assert "Offline Installation" in step.review_sections["registration"].text()
    step.close()
