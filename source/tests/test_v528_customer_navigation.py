from pathlib import Path


def test_report_tab_refresh_is_debounced_and_guarded():
    text = Path(__file__).resolve().parents[1].joinpath("v5_pages.py").read_text(encoding="utf-8")
    assert "lambda _index: QTimer.singleShot(0, self.refresh_visible)" not in text
    assert "self.report_center.tabs.currentChanged.connect(self._schedule_report_refresh)" in text
    assert "self._report_refresh_busy" in text
    assert "self._report_refresh_pending" in text


def test_top_users_prefers_real_name_over_numeric_placeholder():
    text = Path(__file__).resolve().parents[1].joinpath("services", "summary_service.py").read_text(encoding="utf-8")
    assert "_subject_name_is_placeholder" in text
    assert "item[0] = subject_name" in text


# Collector name replacement is exercised with actual MeterReader inputs in
# test_v528_numeric_subject_names.py. Its helper now lives in subject_identity;
# searching for its definition in meter.py rejected a valid module extraction.
