from __future__ import annotations

from pathlib import Path
import re


def sub_once(path: str, pattern: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly 1 regex match, got {count}")
    p.write_text(updated, encoding="utf-8")


def main() -> None:
    sub_once(
        "source/v5_pages.py",
        r"        self\.report_center\.tabs\.currentChanged\.connect\(\s*lambda _index: QTimer\.singleShot\(0, self\.refresh_visible\)\s*\)\s*        self\.report_center_tabs = self\.report_center\.tabs",
        """        self._report_refresh_busy = False
        self._report_refresh_pending = False
        self._report_refresh_timer = QTimer(self)
        self._report_refresh_timer.setSingleShot(True)
        self._report_refresh_timer.setInterval(120)
        self._report_refresh_timer.timeout.connect(self.refresh_visible)
        self.report_center.tabs.currentChanged.connect(self._schedule_report_refresh)
        self.report_center_tabs = self.report_center.tabs""",
    )
    sub_once(
        "source/v5_pages.py",
        r"    @staticmethod\s*\n    def _report_panel\(\) -> tuple\[QFrame, QVBoxLayout\]:",
        """    def _schedule_report_refresh(self, _index: int | None = None) -> None:
        # Coalesce rapid Legacy -> Main changes before touching SQLite/report aggregation.
        self._report_refresh_timer.start()

    @staticmethod
    def _report_panel() -> tuple[QFrame, QVBoxLayout]:""",
    )
    sub_once(
        "source/v5_pages.py",
        r"    def refresh_visible\(self\) -> None:.*?(?=\n    def _export_report_center_excel)",
        '''    def refresh_visible(self) -> None:
        """Load the visible report once; coalesce tab changes while a refresh is active."""
        if self._report_refresh_busy:
            self._report_refresh_pending = True
            return
        self._report_refresh_busy = True
        try:
            self.reports_error.setVisible(False)
            self.report_center.updated_label.setText("กำลังโหลดข้อมูลแท็บนี้…")
            self._populate_report_periods()
            self._refresh_report_center()
        except Exception as error:
            self.report_center.show_error(
                "โหลด Reports ไม่สำเร็จ · ซ่อนตัวเลขไว้เพื่อป้องกันการอ่านผิด "
                f"· {type(error).__name__}: {error}"
            )
            self.reports_error.setText(
                "โหลด Reports ไม่สำเร็จ · ยอดบนหน้าจอถูกซ่อนไว้เพื่อป้องกันการอ่านผิด "
                f"· {type(error).__name__}: {error}"
            )
            self.reports_error.setVisible(True)
        finally:
            self._report_refresh_busy = False
            if self._report_refresh_pending:
                self._report_refresh_pending = False
                self._report_refresh_timer.start()
''',
    )
    sub_once(
        "source/services/summary_service.py",
        r"(?=def _runtime_status\(device, \*, now: datetime\) -> str:)",
        '''def _subject_name_is_placeholder(subject_id: str, subject_name: str) -> bool:
    sid = str(subject_id or "").strip()
    name = str(subject_name or "").strip()
    if not name:
        return True
    if name.casefold() == sid.casefold():
        return True
    if name.isdigit() and sid.isdigit():
        return int(name) == int(sid)
    return False


''',
    )
    sub_once(
        "source/services/summary_service.py",
        r"(        item = subject_totals\.setdefault\(\s*\(subject\.device_identity, subject\.subject_type, subject\.subject_id\),\s*\[subject_name, 0\.0\],\s*\)\s*)(        item\[1\] \+= subject\.period_usage)",
        r'''\1        if (
            _subject_name_is_placeholder(subject.subject_id, item[0])
            and not _subject_name_is_placeholder(subject.subject_id, subject_name)
        ):
            item[0] = subject_name
\2''',
    )

    test_path = Path("source/tests/test_v528_customer_navigation.py")
    test_path.write_text(
        '''from pathlib import Path


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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
