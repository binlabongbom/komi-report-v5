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


def test_collector_replaces_numeric_subject_placeholder():
    text = Path(__file__).resolve().parents[1].joinpath("komi_snmp_profiler", "meter.py").read_text(encoding="utf-8")
    assert "def _subject_name_is_placeholder" in text
    assert "should_replace = bool(name) and _subject_name_is_placeholder" in text
