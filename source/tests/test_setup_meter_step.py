"""Meter evidence review must not rebase legacy printers or confirm stale reads."""

from dataclasses import replace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from i18n import set_language
from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue
from services.device_config import DeviceConfig
from ui.setup.steps.meter import MeterReviewDevice, MeterStep


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def device(slot=2):
    return DeviceConfig(slot, f"Printer {slot + 1}", f"192.0.2.{31 + slot}",
                        serial=f"SERIAL-{slot + 1}")


def reading(slot=2, *, total=2475):
    return MeterReading(
        host=device(slot).host,
        collected_at="2026-09-25T01:38:24+00:00",
        counters=(
            WebCounterValue("counter.total.total", "Total", total, "Total", "Meter.Total"),
            WebCounterValue("counter.print.full_color_total", "Print Color Total", 1500, "Print",
                            "Meter.Print.FullColorTotal"),
            WebCounterValue("counter.print.full_color_large", "Print Color Large", 100, "Print",
                            "Meter.Print.FullColorLarge"),
        ),
        source="fixture",
        auth_state=WebAuthState.ADMIN,
    )


def entry(slot=2, *, required=True):
    return MeterReviewDevice(device(slot), reading(slot), required)


def select(step, slot):
    step.device_combo.setCurrentIndex(step.device_combo.findData(slot))


def test_review_all_three_slots_but_only_new_printer_requires_confirmation(app):
    step = MeterStep()
    states = []
    step.readiness_changed.connect(states.append)
    devices = (entry(0, required=False), entry(1, required=False), entry(2))
    step.set_devices(devices)
    assert step.device_combo.count() == 3
    assert step.device_combo.currentData() == 2
    assert not step.ready
    assert step.confirmation.isEnabled()
    assert "2,475" in step.identity_label.text()
    step.confirmation.setChecked(True)
    assert step.ready
    assert step.confirmed_slots == (2,)
    select(step, 0)
    assert step.confirmation.isHidden()
    assert "ใช้ฐานเดิม" in step.baseline_label.text()
    assert step.raw_table.rowCount() == 3
    select(step, 1)
    assert step.raw_table.rowCount() == 3
    select(step, 2)
    assert step.confirmation.isChecked()
    assert step.ready
    step.set_devices(devices)
    assert step.confirmed_slots == (2,)
    assert states[0] is False and states[-1] is True
    assert "ไม่เปลี่ยนประวัติ" in step.summary_lines()[0]
    step.close()


def test_new_install_requires_separate_confirmation_for_each_selected_device(app):
    step = MeterStep()
    step.set_devices((entry(0), entry(1), entry(2)))
    for slot in (0, 1):
        select(step, slot)
        step.confirmation.setChecked(True)
        assert not step.ready
    assert "2/3" in step.next_hint.text()
    select(step, 2)
    step.confirmation.setChecked(True)
    assert step.ready
    assert step.confirmed_slots == (0, 1, 2)
    select(step, 1)
    step.confirmation.setChecked(False)
    assert not step.ready
    assert step.confirmed_slots == (0, 2)
    step.close()


def test_legacy_devices_without_counter_evidence_keep_existing_baselines(app):
    step = MeterStep()
    step.set_devices((MeterReviewDevice(device(0), None), MeterReviewDevice(device(1), None)))
    assert step.ready
    assert step.confirmed_slots == ()
    assert step.confirmation.isHidden()
    assert step.raw_table.rowCount() == step.parser_table.rowCount() == 0
    assert "Total Meter —" in step.identity_label.text()
    assert "ใช้ฐานเดิม" in step.baseline_label.text()
    assert "ไม่ต้องยืนยันฐานใหม่" in step.next_hint.text()
    step.close()


@pytest.mark.parametrize("evidence", [
    MeterReviewDevice(device(), None, True),
    MeterReviewDevice(device(), replace(reading(), counters=reading().counters[1:]), True),
    MeterReviewDevice(device(), replace(reading(), host="192.0.2.99"), True),
    MeterReviewDevice(device(), reading(), True, "SERIAL_MISMATCH: wrong physical printer"),
    MeterReviewDevice(device(), reading(total=-1), True),
    MeterReviewDevice(device(), reading(total=float("nan")), True),
    MeterReviewDevice(device(), reading(total=True), True),
    MeterReviewDevice(device(), reading(total=0.5), True),
    MeterReviewDevice(device(), replace(reading(), counters=(reading().counters[0],) * 2), True),
])
def test_missing_or_invalid_reading_cannot_be_confirmed_or_fabricated_as_zero(app, evidence):
    step = MeterStep()
    step.set_devices((evidence,))
    assert not step.ready
    assert not step.confirmation.isEnabled()
    assert step.empty_label.text()
    step.confirmation.setChecked(True)
    assert not step.ready
    assert step.confirmed_slots == ()
    step.close()


def test_real_zero_total_is_valid_evidence(app):
    step = MeterStep()
    step.set_devices((MeterReviewDevice(device(), reading(total=0), True),))
    assert step.confirmation.isEnabled()
    assert "Total Meter 0" in step.identity_label.text()
    step.confirmation.setChecked(True)
    assert step.ready
    step.close()


@pytest.mark.parametrize("change", [
    lambda value: replace(value, device=replace(value.device, host="192.0.2.44")),
    lambda value: replace(value, device=replace(value.device, serial="OTHER-PRINTER")),
    lambda value: replace(value, device=replace(value.device, username="other-admin")),
    lambda value: replace(value, reading=replace(value.reading, collected_at="2026-09-25T02:00:00+00:00")),
    lambda value: replace(value, raw_reading=reading(total=2476)),
])
def test_changed_configuration_or_evidence_invalidates_only_affected_confirmation(app, change):
    step = MeterStep()
    original = (entry(0), entry(2))
    step.set_devices(original)
    step.confirmation.setChecked(True)
    select(step, 2)
    step.confirmation.setChecked(True)
    assert step.ready
    step.set_devices((original[0], change(original[1])))
    assert not step.ready
    assert step.confirmed_slots == (0,)
    assert not step.confirmation.isChecked()
    step.close()


def test_invalidation_discards_stale_reading_and_cannot_be_reconfirmed(app):
    step = MeterStep()
    original = entry()
    step.set_devices((original,))
    step.confirmation.setChecked(True)
    step.invalidate(2)
    assert not step.ready
    assert not step.confirmation.isEnabled()
    assert step.raw_table.rowCount() == 0
    assert step.devices[0].reading is None
    step.set_devices((original,))
    assert not step.ready
    assert step.confirmation.isEnabled()
    step.close()


def test_parser_source_navigation_uses_source_path_not_row_order_or_canonical_name(app):
    raw = reading()
    normalized = replace(raw, counters=(
        replace(raw.counters[2], canonical_field="counter.print.custom_large", category="Mapped", count=101),
        raw.counters[0],
        raw.counters[1],
    ))
    step = MeterStep()
    step.set_devices((MeterReviewDevice(device(), normalized, True, raw_reading=raw),))
    assert step.raw_table.item(2, 3).text() == "100"
    assert step.parser_table.item(0, 1).text() == "101"
    assert step.parser_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == "counter.print.custom_large"
    step.views.setCurrentIndex(1)
    step.parser_table.cellClicked.emit(0, 2)
    assert step.views.currentIndex() == 0
    assert step.raw_table.currentRow() == 2
    assert step.raw_table.item(2, 2).data(Qt.ItemDataRole.UserRole) == raw.counters[2].source_path
    step.close()


def test_unmatched_source_does_not_navigate_to_unrelated_raw_row(app):
    raw = reading()
    parsed = replace(raw, counters=(replace(raw.counters[1], source_path="derived.total"),))
    step = MeterStep()
    step.set_devices((MeterReviewDevice(device(), parsed, True, raw_reading=raw),))
    step.views.setCurrentIndex(1)
    step.parser_table.cellActivated.emit(0, 2)
    assert step.views.currentIndex() == 1
    step.close()


def test_parser_mapping_does_not_replace_the_confirmed_raw_meter_value(app):
    raw = reading()
    parsed = replace(raw, counters=tuple(
        replace(counter, canonical_field="mapped.total")
        if counter.canonical_field == "counter.total.total" else counter
        for counter in raw.counters
    ))
    step = MeterStep()
    step.set_devices((MeterReviewDevice(device(), parsed, True, raw_reading=raw),))
    assert "Total Meter 2,475" in step.identity_label.text()
    assert step.confirmation.isEnabled()
    step.confirmation.setChecked(True)
    assert step.ready
    assert "2,475" in step.summary_lines()[0]
    step.close()


def test_user_counters_do_not_appear_or_supply_device_total(app):
    raw = reading()
    user_counter = replace(raw.counters[0], subject_type="user", subject_id="123", count=77)
    step = MeterStep()
    step.set_devices((MeterReviewDevice(device(), replace(raw, counters=(user_counter,)), True),))
    assert not step.ready
    assert step.raw_table.rowCount() == step.parser_table.rowCount() == 0
    step.close()


def test_dynamic_translation_and_wrapping_preserve_business_values_and_confirmation(app):
    raw = reading()
    name = "<printer-name> " * 8
    step = MeterStep()
    step.set_devices((MeterReviewDevice(replace(device(), name=name), raw, True),))
    step.confirmation.setChecked(True)
    set_language("en")
    step.retranslate()
    assert step.device_combo.accessibleName() == "Select printer"
    assert name in step.device_combo.currentText()
    assert step.views.tabText(1) == "Parser values"
    assert step.raw_table.item(1, 2).data(Qt.ItemDataRole.UserRole) == raw.counters[1].source_path
    assert step.raw_table.wordWrap() and step.parser_table.wordWrap()
    assert step.raw_table.textElideMode() == Qt.TextElideMode.ElideNone
    assert step.ready
    assert step.confirmation.isChecked()
    step.close()
