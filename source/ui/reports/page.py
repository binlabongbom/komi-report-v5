"""Page UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import traceback
from concurrent.futures import CancelledError, ThreadPoolExecutor
from datetime import date, datetime
from threading import Event

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui.reports.legacy as legacy_pages
from database import get_billing_day, get_db_path
from i18n import apply_language
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.legacy_history_import import load_imported_legacy_history
from services.monthly_history import (
    HistoryGranularity,
    MonthlyUsage,
    history_period_range,
    load_monthly_usage,
    load_usage_history,
)
from services.raw_counter_history import load_raw_counter_history, load_usage_meter_baselines
from services.report_period_policy import (
    EXPORT_YEARS,
    ReportPeriodLimitError,
    current_preview_period,
    validate_preview_period,
    validate_report_period,
)
from services.report_scope import report_slots
from services.report_snapshot import SnapshotDataCache, load_report_snapshot
from services.subject_history import SubjectDailyCacheStore, SubjectPeriodUsage, load_subject_history
from services.support_diagnostics import with_diagnostic
from services.usage import default_usage_groups, latest_counters
from ui.cloud_reports import CloudReportsWidget
from ui.reports.export_dialog import ReportExportPeriodDialog
from ui.reports.legacy import PageHistory
from ui.styles import reports as reports_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_GREEN, C_RED, C_TEXT2, F_MD, F_SM, SLOT_COLORS
from widgets import FrozenLeftTable, VisibleCheckBox, btn, fnt


def CloudReportsExportData(*args, **kwargs):
    """Lazy compatibility constructor for the Excel export payload."""
    from services.report_excel_export import CloudReportsExportData as payload_type

    return payload_type(*args, **kwargs)


def export_cloud_reports_xlsx(*args, **kwargs):
    """Load openpyxl-backed export code only when an export is requested."""
    from services.report_excel_export import export_cloud_reports_xlsx as export

    return export(*args, **kwargs)


def suggested_cloud_reports_filename(*args, **kwargs):
    from services.report_excel_export import suggested_cloud_reports_filename as suggest

    return suggest(*args, **kwargs)


class PageHistoryV5(PageHistory):
    """Reports workspace backed by V5 device, billing, and subject history."""

    reading_status_requested = pyqtSignal()

    CURRENT_ROWS = (
        ("Total Meter", "__total_meter__"),
        ("PRINT", None),
        ("A3 Color (Print)", "A3 Color (Print)"),
        ("A3 B&W (Print)", "A3 B&W (Print)"),
        ("A4 Color (Print)", "A4 Color (Print)"),
        ("A4 B&W (Print)", "A4 B&W (Print)"),
        ("Other size (Print)", "Other size (Print)"),
        ("COPY", None),
        ("A3 Color (Copy)", "A3 Color (Copy)"),
        ("A3 B&W (Copy)", "A3 B&W (Copy)"),
        ("A4 Color (Copy)", "A4 Color (Copy)"),
        ("A4 B&W (Copy)", "A4 B&W (Copy)"),
        ("Other size (Copy)", "Other size (Copy)"),
        ("SCAN", None),
        ("SCAN", "SCAN"),
    )

    def __init__(
        self,
        repository: DeviceConfigRepository | None = None,
        cache: DailyCacheStore | None = None,
        subject_cache: SubjectDailyCacheStore | None = None,
        parent=None,
        *,
        staged: bool = False,
    ) -> None:
        self._staged = staged
        self.repository = repository or DeviceConfigRepository()
        self.cache = cache or DailyCacheStore()
        self.subject_cache = subject_cache or SubjectDailyCacheStore()
        if staged:
            QWidget.__init__(self, parent)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            self._build_report_center()
            self._init_background_reports()
            return
        super().__init__(parent)
        if hasattr(self, "chk_show_values"):
            self.chk_show_values.blockSignals(True)
            self.chk_show_values.setChecked(False)
            self.chk_show_values.setText("แสดงตัวเลขบนกราฟ")
            self.chk_show_values.blockSignals(False)
        self._build_reports_header()
        self._build_reports_overview()
        self.tabs.setTabText(
            self.tabs.indexOf(self.tab_current),
            "ค่ามิเตอร์รายเครื่อง",
        )
        self.tabs.setTabText(self.tabs.indexOf(self.tab_monthly), "ยอดใช้งานและค่าใช้จ่าย")
        self.tabs.setTabText(self.tabs.indexOf(self.tab_users), "รายผู้ใช้")
        self.tabs.setTabText(self.tabs.indexOf(self.tab_graph), "แนวโน้ม")
        self._polish_reports_trend()
        self._configure_ysoft_report_builder()
        self.tabs.setCurrentWidget(self.tab_overview)
        self._build_report_center()

    def _build_report_center(self) -> None:
        """Expose one Cloud-style workspace while retaining legacy audit tools.

        Existing tables remain alive but hidden because exports, reconciliation,
        and Billing Audit still depend on them. The normal user path has one
        period selector and three understandable destinations only.
        """
        if not self._staged:
            title_item = self.layout().itemAt(0)
            if title_item is not None and title_item.widget() is not None:
                title_item.widget().setVisible(False)
            self.machine_selector_container.setVisible(False)
            self.report_profile_combo.parentWidget().setVisible(False)
            self.report_advanced_panel.setVisible(False)
            self.tabs.setVisible(False)
        self.report_center = CloudReportsWidget(staged=self._staged)
        self.report_center.refresh_requested.connect(self.refresh_visible)
        self.report_center.export_requested.connect(self._export_report_center_excel)
        self.report_center.export_range_requested.connect(self._export_report_center_excel)
        self.report_center.period_changed.connect(self._staged_period_changed if self._staged else self._refresh_report_center)
        self.report_center.reading_status_requested.connect(self.reading_status_requested)
        self._report_refresh_busy = False
        self._report_refresh_pending = False
        self._report_refresh_timer = QTimer(self)
        self._report_refresh_timer.setSingleShot(True)
        self._report_refresh_timer.setInterval(120)
        self._report_refresh_timer.timeout.connect(self.refresh_visible_cached if self._staged else self.refresh_visible)
        self.report_center.tabs.currentChanged.connect(self._schedule_report_refresh)
        self.report_center_tabs = self.report_center.tabs
        # Cloud Reports owns scrolling within each tab so its header, tab bar
        # and period controls remain visible and hidden pages cannot expand it.
        self.layout().addWidget(self.report_center, 1)

    def _init_background_reports(self) -> None:
        self._snapshot_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="komi-report")
        self._snapshot_jobs = {}
        self._snapshot_cache = {}
        self._snapshot_data = SnapshotDataCache()
        self._snapshot_display_periods = {}
        self._snapshot_display_db = {}
        self._snapshot_generation = 0
        self._snapshot_db = str(get_db_path())
        self._snapshot_closed = False
        self._usage_warm_scheduled = False
        self._snapshot_poll = QTimer(self)
        self._snapshot_poll.setInterval(25)
        self._snapshot_poll.timeout.connect(self._collect_report_snapshots)
        self._snapshot_poll.start()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown_report_loading)

    def shutdown_report_loading(self) -> None:
        controller = getattr(self, '_export_controller', None)
        if controller is not None:
            controller.shutdown()
        if not self._staged or self._snapshot_closed:
            return
        self._snapshot_closed = True
        self._snapshot_poll.stop()
        for future, cancelled in self._snapshot_jobs.values():
            cancelled.set()
            future.cancel()
        self._snapshot_pool.shutdown(wait=False, cancel_futures=True)

    def invalidate_data(self) -> None:
        if not self._staged:
            return
        self._snapshot_generation += 1
        self._snapshot_cache.clear()
        self._snapshot_data = SnapshotDataCache()
        for future, cancelled in self._snapshot_jobs.values():
            cancelled.set()
            future.cancel()
        path = str(get_db_path())
        if path != self._snapshot_db:
            self.cache = DailyCacheStore()
            self.subject_cache = SubjectDailyCacheStore()
        self._snapshot_db = path

    def prepare_overview(self) -> None:
        if self._staged:
            self._request_snapshot(0, background=True)

    def prewarm_tab(self, index: int) -> None:
        if not self._staged or self._snapshot_closed:
            return
        # Do not let speculative construction compete with a selected tab.
        if self._snapshot_jobs and any(key[1] == self.report_center.tabs.currentIndex() for key in self._snapshot_jobs):
            QTimer.singleShot(350, lambda: self.prewarm_tab(index) if not self._snapshot_closed else None)
            return
        self.report_center.prewarm_tab(index)
        self._request_snapshot(index, background=True)

    def on_reports_opened(self) -> None:
        if not self._staged:
            return
        self.refresh_visible_cached()
        if not self._usage_warm_scheduled:
            self._usage_warm_scheduled = True
            QTimer.singleShot(500, lambda: self.prewarm_tab(3) if not self._snapshot_closed else None)

    def _staged_period_changed(self, _selection) -> None:
        self.invalidate_data()
        self.refresh_visible_cached()

    def refresh_visible_cached(self) -> None:
        if not self._staged:
            self.refresh_visible()
            return
        self._request_snapshot(self.report_center.tabs.currentIndex())

    def _request_snapshot(self, index: int, *, background: bool = False) -> None:
        if self._snapshot_closed:
            return
        if str(get_db_path()) != self._snapshot_db:
            self.invalidate_data()
        period = self.report_center.current_period()
        if period is not None and not self.report_center.show_preview_period_limit(period):
            return
        cache_key = (index, period)
        cached = self._snapshot_cache.get(cache_key)
        if cached is not None:
            if not background or index == self.report_center.tabs.currentIndex():
                self._apply_report_snapshot(index, cached)
            return
        key = (self._snapshot_generation, index, period)
        if not background:
            # Cancel speculative jobs at their next read boundary, prioritizing clicks.
            for other, (future, cancelled) in self._snapshot_jobs.items():
                if other != key:
                    cancelled.set()
                    future.cancel()
        if index == self.report_center.tabs.currentIndex():
            self.report_center.set_loading(True)
            displayed = self._snapshot_display_periods.get(index)
            if displayed is not None and self._snapshot_display_db.get(index) != self._snapshot_db:
                self.report_center.error_label.setText("กำลังโหลดฐานข้อมูลใหม่ · ตัวเลขเดิมยังเป็นข้อมูลจากฐานก่อนหน้า")
                self.report_center.error_label.show()
            elif displayed is not None and displayed != period:
                self.report_center.error_label.setText(
                    f"กำลังโหลดช่วงใหม่ · ตัวเลขเดิมยังเป็นช่วง {displayed[0]} ถึง {displayed[1]}"
                )
                self.report_center.error_label.show()
        existing = self._snapshot_jobs.get(key)
        if existing is not None and not existing[1].is_set():
            return
        # A cancelled job may still finish; keep its identity separate from replacements.
        if existing is not None:
            self._snapshot_jobs.pop(key)
        cancelled = Event()
        future = self._snapshot_pool.submit(
            load_report_snapshot, index, period, cache=self.cache, subject_cache=self.subject_cache,
            repository=self.repository, cancelled=cancelled, shared=self._snapshot_data, database_path=self._snapshot_db,
        )
        self._snapshot_jobs[key] = (future, cancelled)

    def _collect_report_snapshots(self) -> None:
        if self._snapshot_closed:
            return
        if str(get_db_path()) != self._snapshot_db:
            self.invalidate_data()
            self.refresh_visible_cached()
            return
        for key, (future, cancelled) in tuple(self._snapshot_jobs.items()):
            if not future.done():
                continue
            self._snapshot_jobs.pop(key, None)
            if cancelled.is_set() or key[0] != self._snapshot_generation:
                continue
            index, requested_period = key[1:]
            selected = index == self.report_center.tabs.currentIndex()
            try:
                snapshot = future.result()
            except CancelledError:
                continue
            except Exception as error:
                if selected:
                    self.report_center.set_loading(False)
                    self.report_center.show_error(f"โหลดรายงานไม่สำเร็จ · {type(error).__name__}: {error} · ลองใหม่ได้")
                continue
            self._snapshot_cache[(index, requested_period)] = snapshot
            self._snapshot_cache[(index, snapshot.data["period"])] = snapshot
            if selected:
                self._apply_report_snapshot(index, snapshot)

    def _apply_report_snapshot(self, index: int, snapshot) -> None:
        self._report_records = snapshot.data["monthly_records"]
        self._snapshot_display_periods[index] = snapshot.data["period"]
        self._snapshot_display_db[index] = self._snapshot_db
        self.report_center.set_periods(snapshot.periods, snapshot.data["period"])
        rendered = self.report_center.set_data(**snapshot.data, tab_index=index,
            snapshot_token=(self._snapshot_generation, index, snapshot.data["period"]))
        self.report_center.set_loading(False)
        if rendered:
            apply_language(self.report_center)

    def _schedule_report_refresh(self, _index: int | None = None) -> None:
        # Coalesce rapid Legacy -> Main changes before touching SQLite/report aggregation.
        self._report_refresh_timer.start()




    def _refresh_report_center(self, selection: object | None = None) -> None:
        """Refresh the visible Cloud reports from one shared date range."""
        if not hasattr(self, "report_center"):
            return
        selected = (tuple(selection) if isinstance(selection, (tuple, list)) and len(selection) == 2
                    else self.report_center.current_period()) or current_preview_period()
        try:
            validate_preview_period(selected)
        except ReportPeriodLimitError:
            self.report_center.set_periods((), selected)
            return
        if not hasattr(self, "_report_records"):
            self._populate_report_periods()
        periods = sorted(
            {self._period_key(record) for record in getattr(self, "_report_records", ())},
            reverse=True,
        )
        self.report_center.set_periods(periods, selected)
        active_tab = self.report_center.tabs.currentIndex()
        is_custom_period = selected is not None and selected not in periods
        # Printers can use posted monthly records for a billing period, but a
        # custom range must aggregate only the daily records inside its dates.
        needs_daily_usage = active_tab in {0, 1, 2, 3}
        needs_subjects = active_tab in {0, 1}
        needs_raw = active_tab in {1, 4}
        needs_legacy = active_tab in {3, 4}
        usage_daily_records = (
            tuple(load_usage_history(report_slots(), granularity="daily", cache=self.cache))
            if needs_daily_usage
            else ()
        )
        if selected:
            start = date.fromisoformat(selected[0])
            end = date.fromisoformat(selected[1])
            daily_records = tuple(
                record
                for record in usage_daily_records
                if record.period_start <= end and record.period_end >= start
            )
            monthly_records = tuple(
                record
                for record in getattr(self, "_report_records", ())
                if self._period_key(record) == selected
            )
            # A canonical billing period retains Posted/Provisional ledger
            # values. A custom range is built from daily usage so the two
            # date fields change the actual report instead of only the label.
            selected_records = monthly_records or daily_records
            subject_range = (
                {"period_start": start, "period_end": end} if is_custom_period else {"only_period": (start, end)}
            )
            subjects = (
                tuple(
                    record
                    for record in load_subject_history(
                        report_slots(), cache=self.subject_cache, **subject_range
                    )
                    if record.period_start == start and record.period_end == end
                )
                if needs_subjects
                else ()
            )
            raw_counter_records = (
                load_raw_counter_history(
                    report_slots(), period_start=start, period_end=end
                )
                if needs_raw
                else ()
            )
        else:
            daily_records = ()
            selected_records = ()
            subjects = ()
            raw_counter_records = ()
        devices = tuple(self._historical_devices())
        last_sync = max(
            (
                str(device.last_success_at)
                for device in devices
                if getattr(device, "last_success_at", None)
            ),
            default=None,
        )
        from services.report_excel_export import build_daily_category_costs
        self.report_center.set_data(
            category_costs=build_daily_category_costs(daily_records) if active_tab == 1 and subjects else (),
            records=selected_records,
            daily_records=daily_records,
            usage_daily_records=usage_daily_records,
            chart_daily_records=(tuple(load_usage_history(report_slots(), granularity='daily',
                cache=self.cache, graph=True)) if active_tab in {0, 2} else usage_daily_records),
            monthly_records=getattr(self, "_report_records", ()),
            subjects=subjects,
            devices=devices,
            legacy_history=load_imported_legacy_history() if needs_legacy else (),
            raw_counter_records=raw_counter_records,
            usage_meter_baselines=(
                load_usage_meter_baselines(report_slots()) if active_tab == 3 else ()
            ),
            period=selected,
            last_sync_at=last_sync,
        )
        apply_language(self.report_center)

    def refresh_visible(self) -> None:
        if self._staged:
            self.invalidate_data()
            self.refresh_visible_cached()
            return
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

    def _export_report_center_excel(self, period=None) -> None:
        """Choose the destination on Qt; all reading/writing runs in a worker."""
        controller = getattr(self, '_export_controller', None)
        if controller is not None and (controller.busy or controller.closed):
            return
        cloud = self.report_center
        # Use the already loaded summary to offer dates immediately. Never read
        # the full daily/user/Raw history just to open the date selector.
        available_records = tuple(cloud._monthly_records)
        available_start = min(
            (record.period_start for record in available_records),
            default=None,
        )
        available_end = max(
            (record.period_end for record in available_records),
            default=None,
        )
        requested_period = period or cloud.current_period()
        if requested_period is not None:
            default_start, default_end = (
                date.fromisoformat(value) for value in requested_period
            )
        elif available_start is not None and available_end is not None:
            default_start, default_end = available_start, available_end
        else:
            default_start = default_end = date.today()
        selected = ReportExportPeriodDialog.get_selection(
            self,
            default_start,
            default_end,
            available_start=available_start,
            available_end=available_end,
        )
        if selected is None:
            return
        start, end = selected.start, selected.end
        validate_report_period(start, end, years=EXPORT_YEARS)
        suggested = (
            f"KOMI_Reports_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
        )
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Reports to Excel",
            suggested,
            "Excel Workbook (*.xlsx)",
        )
        if not path:
            return
        from functools import partial

        from services.report_export_job import export_report_selection
        from ui.report_export import ReportExportController
        if controller is None:
            controller = self._export_controller = ReportExportController(self)
            controller.busy_changed.connect(cloud.set_export_busy)
            controller.failed.connect(self._report_export_failed)
            controller.succeeded.connect(self._report_export_succeeded)
        controller.start(partial(export_report_selection, path, start, end,
            database_path=get_db_path(), devices=tuple(cloud._devices),
            monthly_records=available_records, last_sync_at=cloud._last_sync_at,
            sections=selected.sections,
            include_waste_adjustment=cloud.include_waste_adjustment()))

    def _report_export_failed(self, error) -> None:
        from services.report_export_job import EmptyReportError
        if isinstance(error, EmptyReportError):
            QMessageBox.warning(self, 'ไม่พบข้อมูล', with_diagnostic(str(error), error, 'ไม่พบข้อมูล'))
        else:
            QMessageBox.critical(self, 'Export ไม่สำเร็จ', with_diagnostic(f'ไม่สามารถสร้างไฟล์ Excel ได้:\n{error}', error, 'Export ไม่สำเร็จ'))

    def _report_export_succeeded(self, saved) -> None:
        QMessageBox.information(
            self,
            "Export สำเร็จ",
            f"บันทึกไฟล์ Excel แล้ว\n{saved}",
        )













    def _polish_reports_trend(self) -> None:
        """Make Trends read as a time report instead of a decorative dashboard."""
        labels = {
            "by_machine": "รายเครื่อง",
            "by_type": "ประเภทงาน",
            "by_user": "ผู้ใช้งาน",
        }
        for key, label in labels.items():
            button = self._graph_view_btns.get(key)
            if button is not None:
                button.setText(label)
        self.chk_show_values.setText("แสดงตัวเลขบนกราฟ")
        self.btn_reset_view.setText("จัดกราฟพอดี")
        self.btn_date_reset.setText("รอบบิลปีนี้")
        self.btn_date_all.setText("ทุกช่วง")
        self.btn_save_png.setText("ส่งออก PNG")
        self.pie_container.setVisible(False)

        self.trend_data_note = QLabel("")
        self.trend_data_note.setWordWrap(True)
        self.trend_data_note.setStyleSheet(
            text_styles.label('#245268', background='#EEF6F9', padding='8px 10px', border='1px solid #D7E7EC')
        )
        self.tab_graph.layout().insertWidget(2, self.trend_data_note)

    def _refresh_graph(self) -> None:
        """Render every Trend view on one consistent chart surface."""
        if not legacy_pages._PQG_OK or not hasattr(self, "plot_widget"):
            return
        try:
            data = self._prepare_graph_data()
            if self._available_months_for_filter:
                self._populate_date_filter_dropdowns()
            self._graph_data_cache = data
            self.pie_container.setVisible(False)
            self.plot_widget.setVisible(True)
            self._draw_graph(data)
        except Exception:
            traceback.print_exc()

    def _draw_graph(self, data: dict) -> None:
        """Draw confirmed Ledger values, then add provisional Daily Cache caps."""
        super()._draw_graph(data)
        if not legacy_pages._PQG_OK or not hasattr(self, "plot_widget"):
            return

        slot_monthly = data["slot_monthly"]
        all_months = data["all_months"]
        m_names = data["m_names"]
        view_mode = data["view_mode"]
        provisional_total = sum(
            float(slot_monthly[slot].get(period, {}).get("provisional_total", 0))
            for slot in range(3)
            for period in all_months
        )
        if not all_months:
            self.trend_data_note.setText(
                "ยังไม่มี Posted Ledger ในช่วงที่เลือก · "
                "กราฟจะเริ่มแสดงเมื่อมีรอบบิลที่ยืนยันแล้ว"
            )
            self.btn_save_png.setEnabled(False)
            return
        if provisional_total > 0:
            if view_mode == "by_type":
                provisional_style = (
                    "สีประเภทงานแบบจางและเส้นประ = "
                    "ยอดระหว่างวันจาก Daily Cache (~)"
                )
            else:
                provisional_style = (
                    "สีเขียวโปร่งเส้นประ = ยอดระหว่างวันจาก Daily Cache (~)"
                )
            self.trend_data_note.setText(
                "สีทึบ = ยอดยืนยันจาก Posted Ledger · "
                f"{provisional_style} ซึ่งยังไม่ถูกบันทึกเข้า Ledger"
            )
        else:
            self.trend_data_note.setText(
                "กราฟนี้แสดงยอดยืนยันจาก Posted Ledger ตามช่วงรอบบิลที่เลือก"
            )
        if provisional_total <= 0 or view_mode == "by_user":
            return

        active_slots = [
            slot
            for slot in range(3)
            if any(
                float(slot_monthly[slot].get(period, {}).get("total", 0)) > 0
                or float(
                    slot_monthly[slot]
                    .get(period, {})
                    .get("provisional_total", 0)
                )
                > 0
                for period in all_months
            )
        ]
        if view_mode == "by_machine":
            hidden = getattr(self, "_hidden_machines", set())
            visible_slots = [slot for slot in active_slots if slot not in hidden]
        else:
            visible_slots = active_slots
        if not visible_slots:
            return

        bar_width = legacy_pages.GRAPH_BAR_WIDTH
        group_width = len(visible_slots) * bar_width + 0.15
        type_keys = (
            "copy_color",
            "copy_bw",
            "print_color",
            "print_bw",
            "meter_color",
            "meter_bw",
        )
        hidden_types = getattr(self, "_hidden_types", set())
        visible_type_keys = [key for key in type_keys if key not in hidden_types]
        show_values = self.chk_show_values.isChecked()
        provisional_specs = (
            (
                "copy_color",
                "provisional_copy_color",
                "Copy สี",
                legacy_pages.GRAPH_COLORS_TYPE["copy_color"],
            ),
            (
                "copy_bw",
                "provisional_copy_bw",
                "Copy ขาวดำ",
                legacy_pages.GRAPH_COLORS_TYPE["copy_bw"],
            ),
            (
                "print_color",
                "provisional_print_color",
                "Print สี",
                legacy_pages.GRAPH_COLORS_TYPE["print_color"],
            ),
            (
                "print_bw",
                "provisional_print_bw",
                "Print ขาวดำ",
                legacy_pages.GRAPH_COLORS_TYPE["print_bw"],
            ),
        )

        for index, slot in enumerate(visible_slots):
            xs: list[float] = []
            bases: list[float] = []
            for period_index, period in enumerate(all_months):
                bucket = slot_monthly[slot].get(period, {})
                if view_mode == "by_machine":
                    base = float(bucket.get("total", 0))
                else:
                    base = sum(
                        float(bucket.get(key, 0)) for key in visible_type_keys
                    )
                xs.append(period_index * group_width + index * bar_width)
                bases.append(base)
            if view_mode == "by_type":
                running_bases = list(bases)
                displayed_totals = [0.0] * len(all_months)
                classified_totals = [
                    sum(
                        float(bucket.get(field, 0))
                        for _key, field, _label, _color in provisional_specs
                    )
                    for bucket in (
                        slot_monthly[slot].get(period, {})
                        for period in all_months
                    )
                ]
                for type_key, field, label, color in provisional_specs:
                    if type_key not in visible_type_keys:
                        continue
                    heights = [
                        float(
                            slot_monthly[slot]
                            .get(period, {})
                            .get(field, 0)
                        )
                        for period in all_months
                    ]
                    if not any(value > 0 for value in heights):
                        continue
                    rgb = QColor(color)
                    segment = legacy_pages.pg.BarGraphItem(
                        x=xs,
                        height=heights,
                        y0=list(running_bases),
                        width=bar_width * 0.9,
                        brush=legacy_pages.pg.mkBrush(
                            rgb.red(), rgb.green(), rgb.blue(), 75
                        ),
                        pen=legacy_pages.pg.mkPen(
                            color,
                            width=2,
                            style=Qt.PenStyle.DashLine,
                        ),
                    )
                    self.plot_widget.addItem(segment)
                    for period_index, value in enumerate(heights):
                        if value <= 0:
                            continue
                        self._hover_bars.append(
                            (
                                f"{m_names[slot]} — {label} ระหว่างวัน ~",
                                xs[period_index],
                                value,
                                data["x_labels"][period_index],
                                (rgb.red(), rgb.green(), rgb.blue()),
                            )
                        )
                        running_bases[period_index] += value
                        displayed_totals[period_index] += value

                unknown_heights = []
                for period_index, period in enumerate(all_months):
                    bucket = slot_monthly[slot].get(period, {})
                    unknown = max(
                        0.0,
                        float(bucket.get("provisional_total", 0))
                        - classified_totals[period_index],
                    )
                    unknown_heights.append(unknown)
                if any(value > 0 for value in unknown_heights):
                    unknown_segment = legacy_pages.pg.BarGraphItem(
                        x=xs,
                        height=unknown_heights,
                        y0=list(running_bases),
                        width=bar_width * 0.9,
                        brush=legacy_pages.pg.mkBrush(22, 163, 74, 70),
                        pen=legacy_pages.pg.mkPen(
                            "#168A4A",
                            width=2,
                            style=Qt.PenStyle.DashLine,
                        ),
                    )
                    self.plot_widget.addItem(unknown_segment)
                    for period_index, value in enumerate(unknown_heights):
                        if value <= 0:
                            continue
                        self._hover_bars.append(
                            (
                                f"{m_names[slot]} — อื่น ๆ ระหว่างวัน ~",
                                xs[period_index],
                                value,
                                data["x_labels"][period_index],
                                (22, 163, 74),
                            )
                        )
                        running_bases[period_index] += value
                        displayed_totals[period_index] += value
                if show_values:
                    for x, total, top in zip(
                        xs, displayed_totals, running_bases, strict=True
                    ):
                        if total <= 0:
                            continue
                        text = legacy_pages.pg.TextItem(
                            f"~+{int(total):,}",
                            anchor=(0.5, 1.0),
                        )
                        text.setFont(fnt(F_SM, True))
                        text.setColor(legacy_pages.pg.mkColor(14, 116, 60))
                        text.setPos(x, top)
                        self.plot_widget.addItem(text)
                continue

            heights = [
                float(
                    slot_monthly[slot]
                    .get(period, {})
                    .get("provisional_total", 0)
                )
                for period in all_months
            ]
            if not any(height > 0 for height in heights):
                continue
            cap = legacy_pages.pg.BarGraphItem(
                x=xs,
                height=heights,
                y0=bases,
                width=bar_width * 0.9,
                brush=legacy_pages.pg.mkBrush(22, 163, 74, 70),
                pen=legacy_pages.pg.mkPen(
                    "#168A4A",
                    width=2,
                    style=Qt.PenStyle.DashLine,
                ),
            )
            self.plot_widget.addItem(cap)
            for period_index, (x, value, base) in enumerate(
                zip(xs, heights, bases, strict=True)
            ):
                if value <= 0:
                    continue
                self._hover_bars.append(
                    (
                        f"{m_names[slot]} — ระหว่างวัน ~",
                        x,
                        value,
                        data["x_labels"][period_index],
                        (22, 163, 74),
                    )
                )
                if show_values:
                    text = legacy_pages.pg.TextItem(
                        f"~+{int(value):,}",
                        anchor=(0.5, 1.0),
                    )
                    text.setFont(fnt(F_SM, True))
                    text.setColor(legacy_pages.pg.mkColor(14, 116, 60))
                    text.setPos(x, base + value)
                    self.plot_widget.addItem(text)

    def _save_graph_png(self) -> None:
        """Export the visible Trend chart for every view mode."""
        if not legacy_pages._PQG_OK or not hasattr(self, "plot_widget"):
            QMessageBox.warning(self, "ส่งออกไม่สำเร็จ", "ไม่พบกราฟสำหรับส่งออก")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ส่งออกกราฟเป็น PNG",
            f"KOMI_Report_Trend_{datetime.now():%Y%m%d_%H%M%S}.png",
            "PNG Files (*.png)",
        )
        if not path:
            return
        try:
            import pyqtgraph.exporters as exporters

            exporter = exporters.ImageExporter(self.plot_widget.getPlotItem())
            exporter.parameters()["width"] = 1600
            exporter.export(path)
            QMessageBox.information(self, "ส่งออกสำเร็จ", f"บันทึกไฟล์แล้ว\n{path}")
        except Exception as error:
            QMessageBox.critical(
                self,
                "ส่งออกไม่สำเร็จ",
                with_diagnostic(f"ไม่สามารถบันทึกไฟล์ได้\n{error}", error, "ส่งออกไม่สำเร็จ"),
            )

    def _historical_devices(self) -> list[DeviceConfig]:
        """Include disabled known slots so historical Ledger rows stay visible."""
        return self.repository.list(enabled_only=False)

    @staticmethod
    def _period_key(record) -> tuple[str, str]:
        return record.period_start.isoformat(), record.period_end.isoformat()

    def _build_reports_header(self) -> None:
        panel = QFrame()
        panel.setObjectName("reports_header")
        panel.setStyleSheet(
            reports_styles.HISTORY_PANEL
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        description = QLabel("Report")
        description.setFont(fnt(F_SM, True))
        description.setWordWrap(True)
        description.setMinimumWidth(0)
        description.setStyleSheet(text_styles.label('#123262'))
        layout.addWidget(description)
        self.report_profile_combo = QComboBox()
        self.report_profile_combo.setProperty("i18n_items", True)
        self.report_profile_combo.setMinimumWidth(230)
        layout.addWidget(self.report_profile_combo)
        self.report_search_button = btn("Search", "primary")
        self.report_search_button.clicked.connect(self.refresh)
        layout.addWidget(self.report_search_button)
        self.report_advanced_button = btn("Advanced", "outline")
        self.report_advanced_button.setCheckable(True)
        self.report_advanced_button.toggled.connect(self._toggle_report_advanced)
        layout.addWidget(self.report_advanced_button)

        self.layout().insertWidget(1, panel)

        self.report_advanced_panel = QFrame()
        self.report_advanced_panel.setObjectName("report_advanced_panel")
        self.report_advanced_panel.setStyleSheet(
            reports_styles.HISTORY_REPORT_ADVANCED_PANEL
        )
        advanced = QHBoxLayout(self.report_advanced_panel)
        advanced.setContentsMargins(14, 10, 14, 10)
        advanced.setSpacing(14)
        advanced.addWidget(QLabel("Columns:"))
        self.report_detail_checkbox = QCheckBox("แสดงรายละเอียด Counter")
        self.report_detail_checkbox.toggled.connect(self._set_report_details)
        advanced.addWidget(self.report_detail_checkbox)
        advanced.addSpacing(8)
        advanced.addWidget(QLabel("สรุปตาราง:"))
        self.report_granularity_combo = QComboBox()
        self.report_granularity_combo.setProperty("i18n_items", True)
        for label, value in (
            ("รายวัน", "daily"),
            ("รายสัปดาห์", "weekly"),
            ("รอบบิล", "monthly"),
            ("รายไตรมาส", "quarterly"),
            ("รายปี", "yearly"),
        ):
            self.report_granularity_combo.addItem(label, value)
        self.report_granularity_combo.setCurrentIndex(2)
        self.report_granularity_combo.currentIndexChanged.connect(
            self._set_report_granularity
        )
        advanced.addWidget(self.report_granularity_combo)
        advanced.addStretch()
        advanced_note = QLabel("เลือกช่วงรอบบิลและ Export จากรายงานที่ต้องการ")
        advanced_note.setStyleSheet(text_styles.label('#64748B', border='none'))
        advanced.addWidget(advanced_note)
        self.report_advanced_panel.setVisible(False)
        self.layout().insertWidget(2, self.report_advanced_panel)

    def _configure_ysoft_report_builder(self) -> None:
        self._report_profiles = (
            ("Standard", self.tab_overview),
            ("Per device", self.tab_current),
            ("Usage & cost", self.tab_monthly),
            ("Per user", self.tab_users),
            ("Trend", self.tab_graph),
        )
        self.report_profile_combo.blockSignals(True)
        for label, tab in self._report_profiles:
            self.report_profile_combo.addItem(label, self.tabs.indexOf(tab))
        self.report_profile_combo.blockSignals(False)
        self.report_profile_combo.currentIndexChanged.connect(self._select_report_profile)
        self.tabs.currentChanged.connect(self._sync_report_profile)
        self._sync_report_profile(self.tabs.currentIndex())

    def _select_report_profile(self, _index: int) -> None:
        tab_index = self.report_profile_combo.currentData()
        if isinstance(tab_index, int) and tab_index >= 0:
            self.tabs.setCurrentIndex(tab_index)

    def _sync_report_profile(self, tab_index: int) -> None:
        combo_index = self.report_profile_combo.findData(tab_index)
        if combo_index >= 0 and combo_index != self.report_profile_combo.currentIndex():
            self.report_profile_combo.blockSignals(True)
            self.report_profile_combo.setCurrentIndex(combo_index)
            self.report_profile_combo.blockSignals(False)

    def _toggle_report_advanced(self, visible: bool) -> None:
        self.report_advanced_panel.setVisible(visible)
        # Standard keeps one current total.  The ledger/cache split remains
        # auditable, but is only expanded when the user asks for Advanced.
        self.report_provisional_summary.setVisible(
            visible and getattr(self, "_report_has_provisional", False)
        )

    def _set_report_details(self, checked: bool) -> None:
        self.report_cost_detail_checkbox.setChecked(checked)
        self.chk_detail_monthly.setChecked(checked)

    def _set_report_granularity(self, _index: int) -> None:
        value = self.report_granularity_combo.currentData()
        index = self.history_view_combo.findData(value)
        if index >= 0:
            self.history_view_combo.setCurrentIndex(index)

    def _build_reports_overview(self) -> None:
        self.tab_overview = QWidget()
        layout = QVBoxLayout(self.tab_overview)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        controls = QHBoxLayout()
        title = QLabel("ภาพรวมรอบบิล")
        title.setFont(fnt(F_MD, True))
        controls.addWidget(title)
        controls.addStretch()
        controls.addWidget(QLabel("ช่วงรายงาน:"))
        self.report_period_combo = QComboBox()
        self.report_period_combo.setProperty("i18n_items", True)
        self.report_period_combo.setMinimumWidth(230)
        self.report_period_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_reports_overview()
        )
        controls.addWidget(self.report_period_combo)
        self.report_cost_detail_checkbox = QCheckBox("แสดงรายละเอียดค่าใช้จ่าย")
        self.report_cost_detail_checkbox.setChecked(False)
        self.report_cost_detail_checkbox.toggled.connect(
            self._toggle_report_cost_details
        )
        # This is the underlying control used by the existing report table;
        # its visible counterpart is in the shared Advanced panel.
        self.report_cost_detail_checkbox.setVisible(False)
        layout.addLayout(controls)

        self.report_overview_warning = QLabel("")
        self.report_overview_warning.setWordWrap(True)
        self.report_overview_warning.setTextFormat(Qt.TextFormat.RichText)
        self.report_overview_warning.setOpenExternalLinks(False)
        self.report_overview_warning.linkActivated.connect(
            self._show_overview_review_detail
        )
        self.report_overview_warning.setVisible(False)
        layout.addWidget(self.report_overview_warning)

        self.reports_error = QLabel("")
        self.reports_error.setWordWrap(True)
        self.reports_error.setVisible(False)
        self.reports_error.setStyleSheet(
            reports_styles.HISTORY_REPORTS_ERROR
        )
        layout.addWidget(self.reports_error)

        self.report_period_note = QLabel("")
        self.report_period_note.setWordWrap(True)
        self.report_period_note.setStyleSheet(
            reports_styles.HISTORY_REPORT_PERIOD_NOTE
        )
        self.report_period_note.setVisible(False)
        layout.addWidget(self.report_period_note)

        self.report_provisional_summary = QLabel("")
        self.report_provisional_summary.setWordWrap(True)
        self.report_provisional_summary.setVisible(False)
        self.report_provisional_summary.setStyleSheet(
            reports_styles.HISTORY_REPORT_PROVISIONAL_SUMMARY
        )
        layout.addWidget(self.report_provisional_summary)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self.report_kpis: dict[str, QLabel] = {}
        specs = (
            ("usage", "ยอดใช้งานรวม", "หน้า", "#123262"),
            ("color", "Color", "หน้า", "#007EA8"),
            ("bw", "B&W", "หน้า", "#374151"),
            ("scan", "Scan", "หน้า", "#7756B3"),
            ("cost", "ค่าใช้จ่ายสุทธิ", "บาท", "#087A55"),
            ("devices", "เครื่องพิมพ์", "เครื่อง", "#B54708"),
        )
        for index, (key, label, unit, color) in enumerate(specs):
            card = QFrame()
            card.setStyleSheet(
                reports_styles.HISTORY_REPORTS_OVERVIEW
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(13, 10, 13, 10)
            card_layout.setSpacing(3)
            caption = QLabel(label)
            caption.setStyleSheet(text_styles.label('#4C6378', border='none'))
            value = QLabel("—")
            value.setFont(fnt(F_MD, True))
            value.setStyleSheet(text_styles.label(color, border='none'))
            suffix = QLabel(unit)
            suffix.setStyleSheet(text_styles.label('#5B7084', border='none', font_size='11px'))
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            card_layout.addWidget(suffix)
            cards.addWidget(card, index // 3, index % 3)
            cards.setColumnStretch(index % 3, 1)
            self.report_kpis[key] = value
        layout.addLayout(cards)

        self.report_cost_detail_summary = QLabel("")
        self.report_cost_detail_summary.setWordWrap(True)
        self.report_cost_detail_summary.setVisible(False)
        self.report_cost_detail_summary.setStyleSheet(
            reports_styles.HISTORY_REPORT_COST_DETAIL_SUMMARY
        )
        layout.addWidget(self.report_cost_detail_summary)

        tables = QGridLayout()
        tables.setHorizontalSpacing(14)
        tables.setVerticalSpacing(10)
        tables.setHorizontalSpacing(12)
        tables.setVerticalSpacing(8)
        self.report_printer_title = QLabel("Printer")
        self.report_printer_title.setFont(fnt(F_SM, True))
        self.report_printer_title.setMinimumHeight(20)
        tables.addWidget(self.report_printer_title, 0, 0)
        self.report_user_title = QLabel("User / Account")
        self.report_user_title.setFont(fnt(F_SM, True))
        self.report_user_title.setMinimumHeight(20)
        tables.addWidget(self.report_user_title, 0, 1)

        self.report_printers = QTableWidget()
        self.report_printers.cellClicked.connect(
            self._show_printer_status_detail
        )
        self.report_printers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.report_printers.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.report_printers.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.report_printers.verticalHeader().setVisible(False)
        self._report_printer_status_details: dict[int, str] = {}
        self._report_overview_review_detail = ""
        self._configure_report_printer_columns(False)
        self.report_printers.setMinimumHeight(190)
        tables.addWidget(self.report_printers, 1, 0)

        self.report_users = QTableWidget()
        self.report_users.setColumnCount(2)
        self.report_users.setHorizontalHeaderLabels(["User / Account", "Total Counter"])
        self.report_users.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.report_users.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.report_users.verticalHeader().setVisible(False)
        self.report_users.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.report_users.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.report_users.setColumnWidth(1, 120)
        self.report_users.setMinimumHeight(190)
        tables.addWidget(self.report_users, 1, 1)
        tables.setColumnStretch(0, 3)
        tables.setColumnStretch(1, 2)
        self.reports_tables_layout = tables
        layout.addLayout(tables, 1)

        self.tabs.insertTab(0, self.tab_overview, "ภาพรวม")
        self._apply_reports_responsive(self.width())

    def _configure_report_printer_columns(self, show_cost_details: bool) -> None:
        if show_cost_details:
            labels = [
                "เครื่อง",
                "สถานะ",
                "Color",
                "B&W",
                "Scan",
                "ก่อนหัก",
                "ส่วนลด",
                "สุทธิ",
            ]
            widths = (132, 150, 60, 60, 60, 78, 70, 78)
        else:
            labels = ["เครื่อง", "สถานะ", "Color", "B&W", "Scan", "Cost"]
            widths = (132, 150, 60, 60, 60, 76)
        self.report_printers.clearSpans()
        self.report_printers.setColumnCount(len(labels))
        self.report_printers.setHorizontalHeaderLabels(labels)
        self.report_printers.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        for column in range(1, len(labels)):
            self.report_printers.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.Fixed
            )
        for column, width in enumerate(widths):
            self.report_printers.setColumnWidth(column, width)

    def _toggle_report_cost_details(self, checked: bool) -> None:
        self._configure_report_printer_columns(checked)
        self.report_cost_detail_summary.setVisible(checked)
        self._apply_reports_responsive(self.width())
        self._refresh_reports_overview()

    def _show_printer_status_detail(self, row: int, column: int) -> None:
        if column != 1:
            return
        detail = self._report_printer_status_details.get(row)
        if not detail:
            return
        QMessageBox.information(self, "รายละเอียดสถานะเครื่องพิมพ์", detail)

    def _show_overview_review_detail(self, _link: str) -> None:
        if not self._report_overview_review_detail:
            return
        QMessageBox.information(
            self,
            "ข้อมูลที่รอตรวจสอบ",
            self._report_overview_review_detail,
        )

    def _apply_reports_responsive(self, width: int) -> None:
        if not hasattr(self, "reports_tables_layout"):
            return
        layout = self.reports_tables_layout
        for widget in (
            self.report_printer_title,
            self.report_user_title,
            self.report_printers,
            self.report_users,
        ):
            layout.removeWidget(widget)
        if width < 900:
            layout.addWidget(self.report_printer_title, 0, 0)
            layout.addWidget(self.report_printers, 1, 0)
            layout.addWidget(self.report_user_title, 2, 0)
            layout.addWidget(self.report_users, 3, 0)
            self.report_printers.setMinimumHeight(130)
            self.report_users.setMinimumHeight(110)
            self.report_printers.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch
            )
            layout.setColumnStretch(0, 1)
            layout.setColumnStretch(1, 0)
        else:
            layout.addWidget(self.report_printer_title, 0, 0)
            layout.addWidget(self.report_user_title, 0, 1)
            layout.addWidget(self.report_printers, 1, 0)
            layout.addWidget(self.report_users, 1, 1)
            self.report_printers.setMinimumHeight(190)
            self.report_users.setMinimumHeight(190)
            self.report_printers.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Interactive
            )
            layout.setColumnStretch(0, 3)
            layout.setColumnStretch(1, 2)

    def resizeEvent(self, event) -> None:
        self._apply_reports_responsive(event.size().width())
        super().resizeEvent(event)

    @staticmethod
    def _record_device_identity(record) -> str:
        identity = str(getattr(record, "device_identity", "") or "").strip()
        if identity:
            return identity
        return f"legacy-slot:{int(record.device_slot)}"

    @staticmethod
    def _configured_device_identity(device: DeviceConfig | None) -> str:
        if device is None:
            return ""
        serial = str(device.serial or "").strip()
        if serial:
            return f"serial:{serial}"
        host = str(device.host or "").strip()
        if host:
            return f"host:{host}"
        return f"legacy-slot:{int(device.slot)}"

    @classmethod
    def _record_matches_current_device(cls, record, device: DeviceConfig | None) -> bool:
        if device is None:
            return False
        frozen_identity = str(getattr(record, "device_identity", "") or "").strip()
        if not frozen_identity:
            return int(record.device_slot) == int(device.slot)
        return frozen_identity == cls._configured_device_identity(device)

    @staticmethod
    def _short_serial(serial: str) -> str:
        value = str(serial or "").strip()
        if len(value) <= 8:
            return value
        return f"…{value[-8:]}"

    @classmethod
    def _record_device_label(
        cls,
        record,
        current_by_slot: dict[int, DeviceConfig],
        *,
        include_serial: bool = True,
    ) -> tuple[str, str, bool]:
        slot = int(record.device_slot)
        current = current_by_slot.get(slot)
        identity = cls._record_device_identity(record)
        explicit_identity = bool(str(getattr(record, "device_identity", "") or "").strip())
        is_current = cls._record_matches_current_device(record, current)
        frozen_name = str(getattr(record, "device_name_snapshot", "") or "").strip()
        serial = str(getattr(record, "device_serial_snapshot", "") or "").strip()
        if not serial and identity.startswith("serial:"):
            serial = identity.partition(":")[2]

        if frozen_name:
            name = frozen_name
        elif (not explicit_identity or is_current) and current is not None:
            name = current.name
        else:
            name = f"Slot {slot + 1}"

        suffix = cls._short_serial(serial) if include_serial and serial else ""
        if not suffix and explicit_identity and not is_current:
            suffix = "เครื่องเดิม"
        label = f"{name} · {suffix}" if suffix else name

        details = [name, f"Slot {slot + 1}"]
        if serial:
            details.append(f"Serial: {serial}")
        details.append(f"Identity: {identity}")
        if explicit_identity and not is_current:
            details.append("เครื่องเดิมใน slot นี้ · ใช้ snapshot จาก Ledger")
        else:
            details.append("ตรงกับเครื่องที่ตั้งค่าปัจจุบัน")
        return label, "\n".join(details), is_current

    @classmethod
    def _logical_device_groups(
        cls,
        records,
        devices: list[DeviceConfig],
    ) -> list[dict]:
        current_by_slot = {
            device.slot: device
            for device in devices
            if device.enabled
        }
        first_by_identity: dict[str, object] = {}
        for record in records:
            first_by_identity.setdefault(cls._record_device_identity(record), record)

        groups: list[dict] = []
        if first_by_identity:
            ordered = sorted(
                first_by_identity.items(),
                key=lambda item: (
                    int(item[1].device_slot),
                    str(getattr(item[1], "device_name_snapshot", "") or "").casefold(),
                    item[0],
                ),
            )
            for index, (identity, record) in enumerate(ordered):
                label, tooltip, is_current = cls._record_device_label(
                    record,
                    current_by_slot,
                    include_serial=True,
                )
                groups.append(
                    {
                        "identity": identity,
                        "record": record,
                        "slot": int(record.device_slot),
                        "label": label,
                        "tooltip": tooltip,
                        "is_current": is_current,
                        "color": SLOT_COLORS[index % len(SLOT_COLORS)],
                    }
                )
        else:
            for index, device in enumerate(
                device for device in devices if device.enabled
            ):
                groups.append(
                    {
                        "identity": f"legacy-slot:{int(device.slot)}",
                        "record": None,
                        "slot": int(device.slot),
                        "label": device.name,
                        "tooltip": (
                            f"{device.name}\nSlot {device.slot + 1}\n"
                            f"Identity: {cls._configured_device_identity(device)}"
                        ),
                        "is_current": True,
                        "color": SLOT_COLORS[index % len(SLOT_COLORS)],
                    }
                )
        return groups

    def _populate_report_periods(self) -> None:
        self._report_records = load_usage_history(
            report_slots(),
            granularity="monthly",
            cache=self.cache,
        )
        periods = sorted(
            {self._period_key(record) for record in self._report_records},
            reverse=True,
        )
        current_start, current_end = history_period_range(
            date.today(),
            get_billing_day(),
            "monthly",
        )
        current_period = (current_start.isoformat(), current_end.isoformat())
        today_key = date.today()
        active_frozen_periods = [
            period
            for period in periods
            if date.fromisoformat(period[0]) <= today_key <= date.fromisoformat(period[1])
        ]
        default_period = (
            current_period
            if current_period in periods
            else (active_frozen_periods[0] if active_frozen_periods else (periods[0] if periods else current_period))
        )
        if not periods:
            periods.insert(0, current_period)
        current = self.report_period_combo.currentData()
        samples = {self._period_key(record): record for record in self._report_records}
        self.report_period_combo.blockSignals(True)
        self.report_period_combo.clear()
        for period in periods:
            sample = samples.get(period)
            label = (
                self._history_period_label(sample, "monthly")
                if sample is not None
                else (
                    "รอบบิลปัจจุบัน · "
                    f"{date.fromisoformat(period[0]):%d/%m/%Y}–"
                    f"{date.fromisoformat(period[1]):%d/%m/%Y} · ยังไม่มี Posted Ledger"
                )
            )
            self.report_period_combo.addItem(label, period)
        if current:
            index = self.report_period_combo.findData(current)
            if index >= 0:
                self.report_period_combo.setCurrentIndex(index)
        else:
            index = self.report_period_combo.findData(default_period)
            self.report_period_combo.setCurrentIndex(max(0, index))
        self.report_period_combo.blockSignals(False)
        self._refresh_reports_overview()

    def _refresh_reports_overview(self) -> None:
        selected = self.report_period_combo.currentData()
        records = tuple(
            record
            for record in getattr(self, "_report_records", ())
            if selected and self._period_key(record) == tuple(selected)
        )
        devices = self._historical_devices()
        device_by_slot = {device.slot: device for device in devices}
        enabled_by_slot = {
            device.slot: device
            for device in self.repository.list(enabled_only=True)
        }
        if not selected or not records:
            self._report_has_provisional = False
            self.report_provisional_summary.setVisible(False)
            for value in self.report_kpis.values():
                value.setText("—")
            self.report_cost_detail_summary.setText(
                "ค่าใช้จ่ายก่อนหัก — · ส่วนลดกระดาษเสีย — · ค่าใช้จ่ายสุทธิ —"
            )
            self.report_period_note.setText(
                "ยังไม่มี Posted Ledger สำหรับช่วงรายงานนี้ · "
                "ระบบจะไม่แสดง 0 เพราะยังไม่มีหลักฐานสำหรับคำนวณ"
            )
            self.report_printers.clearSpans()
            self.report_printers.setRowCount(1)
            empty_printer = QTableWidgetItem("ยังไม่มี Posted Ledger สำหรับเครื่องพิมพ์")
            empty_printer.setForeground(QColor(C_TEXT2))
            self.report_printers.setItem(0, 0, empty_printer)
            self.report_printers.setSpan(
                0, 0, 1, self.report_printers.columnCount()
            )
            self.report_users.clearSpans()
            self.report_users.setRowCount(1)
            empty_user = QTableWidgetItem(
                "ยังไม่มี User Authentication / Account Track ในช่วงนี้"
            )
            empty_user.setForeground(QColor(C_TEXT2))
            self.report_users.setItem(0, 0, empty_user)
            self.report_users.setSpan(0, 0, 1, 2)
            self._report_overview_review_detail = (
                "ยังไม่มีข้อมูลที่ Posted สำหรับช่วงรายงานนี้\n"
                "โปรดตรวจสอบรอบบิล หรือสถานะและประวัติการอ่านใน Settings"
            )
            self.report_overview_warning.setText(
                '<a href="review">ยังไม่มีข้อมูลสำหรับช่วงรายงานนี้</a>'
            )
            self.report_overview_warning.setVisible(True)
            self.report_overview_warning.setStyleSheet(
                text_styles.label('#667085', padding='2px 0')
            )
            return
        confirmed_color = sum(record.a3_color + record.a4_color for record in records)
        confirmed_bw = sum(record.a3_bw + record.a4_bw for record in records)
        confirmed_total = confirmed_color + confirmed_bw
        confirmed_scan = sum(record.scan for record in records)
        gross_cost = sum(record.gross_cost for record in records)
        cost = sum(record.net_cost for record in records)
        provisional_color = sum(
            record.provisional_a3_color + record.provisional_a4_color
            for record in records
        )
        provisional_bw = sum(
            record.provisional_a3_bw + record.provisional_a4_bw
            for record in records
        )
        provisional_total = provisional_color + provisional_bw
        provisional_scan = sum(record.provisional_scan for record in records)
        provisional_gross = sum(record.provisional_gross_cost for record in records)
        provisional_cost = sum(record.provisional_net_cost for record in records)
        provisional_days = sum(record.provisional_days for record in records)
        provisional_cost_available = all(
            record.provisional_cost_available
            for record in records
            if record.provisional_days
        )
        has_provisional = provisional_days > 0
        self._report_has_provisional = has_provisional
        color = confirmed_color + provisional_color
        bw = confirmed_bw + provisional_bw
        total = confirmed_total + provisional_total
        scan = confirmed_scan + provisional_scan
        combined_gross = gross_cost + provisional_gross
        combined_cost = cost + provisional_cost
        discount_amount = max(0.0, combined_gross - combined_cost)
        discount_pct = (
            0.0
            if combined_gross == 0
            else (discount_amount / combined_gross) * 100
        )
        incomplete = sum(record.incomplete_days for record in records)
        held = sum(record.held_days for record in records)
        summary_is_held = held > 0
        current_identities = {
            self._record_device_identity(record)
            for record in records
            if self._record_matches_current_device(
                record,
                enabled_by_slot.get(record.device_slot),
            )
        }
        estimate_prefix = "~" if has_provisional else ""
        values = {
            "usage": "—" if summary_is_held else f"{estimate_prefix}{total:,.0f}",
            "color": "—" if summary_is_held else f"{estimate_prefix}{color:,.0f}",
            "bw": "—" if summary_is_held else f"{estimate_prefix}{bw:,.0f}",
            "scan": "—" if summary_is_held else f"{estimate_prefix}{scan:,.0f}",
            "cost": (
                "—"
                if summary_is_held or (has_provisional and not provisional_cost_available)
                else f"{estimate_prefix}{combined_cost:,.2f}"
            ),
            "devices": f"{len(current_identities):,}",
        }
        for key, value in values.items():
            self.report_kpis[key].setText(value)
        if summary_is_held or (has_provisional and not provisional_cost_available):
            self.report_cost_detail_summary.setText(
                "ค่าใช้จ่ายก่อนหัก — · ส่วนลดกระดาษเสีย — · ค่าใช้จ่ายสุทธิ —"
            )
        else:
            self.report_cost_detail_summary.setText(
                f"ค่าใช้จ่ายก่อนหัก {estimate_prefix}{combined_gross:,.2f} บาท · "
                f"ส่วนลดกระดาษเสีย {discount_amount:,.2f} บาท "
                f"({discount_pct:,.2f}%) · "
                f"ค่าใช้จ่ายสุทธิ {estimate_prefix}{combined_cost:,.2f} บาท"
            )

        if has_provisional:
            provisional_cost_text = (
                f"~{provisional_cost:,.2f} บาท"
                if provisional_cost_available
                else "— (ยังไม่มี Pricelist)"
            )
            combined_cost_text = (
                f"~{combined_cost:,.2f} บาท"
                if provisional_cost_available
                else "—"
            )
            self.report_provisional_summary.setText(
                f"ยืนยันแล้วจาก Billing Ledger: {confirmed_total:,.0f} หน้า · "
                f"{cost:,.2f} บาท   |   "
                f"วันนี้จาก Daily Cache: +{provisional_total:,.0f} หน้า · "
                f"{provisional_cost_text}   |   "
                f"รวมปัจจุบัน: ~{total:,.0f} หน้า · {combined_cost_text}\n"
                "ข้อมูลวันนี้เป็นค่าระหว่างวัน ยังไม่ถูกบันทึกลง Billing Ledger"
            )
            self.report_provisional_summary.setVisible(
                self.report_advanced_button.isChecked()
            )
        else:
            self.report_provisional_summary.setVisible(False)

        self.report_period_note.setText(
            f"{self.report_period_combo.currentText()} · ค่าใช้จ่ายสุทธิจาก Ledger "
            "(Pricelist/ส่วนลดตามแต่ละรายการ) · Device Meter จาก Web Connection"
            if selected
            else "ยังไม่มี Posted Ledger สำหรับสร้างรายงาน"
        )

        sorted_records = sorted(
            records,
            key=lambda record: record.total + record.provisional_total,
            reverse=True,
        )
        frozen_identities_by_slot: dict[int, set[str]] = {}
        for record in records:
            frozen_identities_by_slot.setdefault(int(record.device_slot), set()).add(
                self._record_device_identity(record)
            )
        self._report_printer_status_details.clear()
        self.report_printers.setRowCount(len(sorted_records))
        for row, record in enumerate(sorted_records):
            device = enabled_by_slot.get(record.device_slot)
            record_is_current = self._record_matches_current_device(record, device)
            device_name, device_tooltip, is_current = self._record_device_label(
                record,
                enabled_by_slot,
                include_serial=(
                    len(frozen_identities_by_slot.get(int(record.device_slot), ())) > 1
                    or not record_is_current
                ),
            )
            if record.held_days:
                status = f"รอตรวจสอบ {record.held_days} วัน"
            elif record.incomplete_days:
                status = f"ไม่สมบูรณ์ {record.incomplete_days} วัน"
            elif not is_current:
                status = "เครื่องเดิม"
            elif record.provisional_days and record.day_count:
                status = "ยืนยันแล้ว + วันนี้"
            elif record.provisional_days:
                status = (
                    "ระหว่างวัน"
                    if record.provisional_cost_available
                    else "ระหว่างวัน · ไม่มีราคา"
                )
            else:
                status = "Online" if device and device.connection_status == "online" else "ค่าล่าสุด"
            status_tooltip = status
            if record.held_days:
                status_tooltip = (
                    f"รอตรวจสอบ {record.held_days} วัน · วันดังกล่าวไม่รวมในยอด"
                )
                self._report_printer_status_details[row] = (
                    f"{device_name}\n\n"
                    f"รอตรวจสอบ {record.held_days} วัน\n"
                    "ข้อมูลของวันดังกล่าวยังไม่รวมในการคำนวณค่าใช้จ่าย\n\n"
                    "ตรวจรายละเอียดเพิ่มเติมได้ที่ Settings → ตรวจสอบรอบบิล และสถานะการอ่าน"
                )
            elif record.incomplete_days:
                status_tooltip = (
                    f"ข้อมูลไม่สมบูรณ์ {record.incomplete_days} วัน · "
                    "กรุณาตรวจ Settings → ตรวจสอบรอบบิล และสถานะการอ่าน"
                )
                self._report_printer_status_details[row] = (
                    f"{device_name}\n\n"
                    f"ข้อมูลไม่สมบูรณ์ {record.incomplete_days} วัน\n\n"
                    "ตรวจรายละเอียดเพิ่มเติมได้ที่ Settings → ตรวจสอบรอบบิล และสถานะการอ่าน"
                )
            elif status == "เครื่องเดิม":
                status_tooltip = "เครื่องเดิมใน slot นี้ · ยอดใช้ frozen name/Serial snapshot จาก Ledger"
            elif record.provisional_days:
                status_tooltip = (
                    "ข้อมูลวันนี้มาจาก Daily Cache · ค่าใช้จ่ายเป็นประมาณการ "
                    "และยังไม่ถูกบันทึกลง Billing Ledger"
                    if record.provisional_cost_available
                    else "ข้อมูลวันนี้มาจาก Daily Cache · แสดง Usage ได้ แต่ยังไม่มี Pricelist สำหรับประมาณค่าใช้จ่าย"
                )
            if record.remarks:
                status += " · ฉบับแก้ไข"
                status_tooltip += "\n" + "\n".join(record.remarks)
                self._report_printer_status_details[row] = (
                    self._report_printer_status_details.get(row, device_name) + "\n\n" + "\n".join(record.remarks)
                )
            record_combined_gross = record.gross_cost + record.provisional_gross_cost
            record_combined_net = record.net_cost + record.provisional_net_cost
            record_discount = max(0.0, record_combined_gross - record_combined_net)
            record_discount_pct = (
                0.0
                if record_combined_gross == 0
                else (record_discount / record_combined_gross) * 100
            )
            row_estimate = "~" if record.provisional_days else ""
            row_cost = (
                f"{row_estimate}{record_combined_net:,.2f}"
                if record.provisional_cost_available
                else "—"
            )
            base_values = (
                device_name,
                status,
                f"{row_estimate}{record.a3_color + record.a4_color + record.provisional_a3_color + record.provisional_a4_color:,.0f}",
                f"{row_estimate}{record.a3_bw + record.a4_bw + record.provisional_a3_bw + record.provisional_a4_bw:,.0f}",
                f"{row_estimate}{record.scan + record.provisional_scan:,.0f}",
            )
            if self.report_cost_detail_checkbox.isChecked():
                row_values = base_values + (
                    (
                        f"{row_estimate}{record_combined_gross:,.2f}"
                        if record.provisional_cost_available
                        else "—"
                    ),
                    (
                        f"{record_discount_pct:,.2f}%"
                        if record.provisional_cost_available
                        else "—"
                    ),
                    row_cost,
                )
            else:
                row_values = base_values + (row_cost,)
            for column, text in enumerate(row_values):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setToolTip(device_tooltip)
                elif column == 1:
                    item.setToolTip(status_tooltip)
                    if row in self._report_printer_status_details:
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)
                        item.setForeground(QColor("#0B5EA8"))
                    elif record.provisional_days:
                        item.setForeground(QColor("#0B5EA8"))
                else:
                    item.setToolTip(str(text))
                if column >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.report_printers.setItem(row, column, item)

        subject_rows: dict[
            tuple[str, str, str],
            tuple[str, float, str, str, str],
        ] = {}
        if selected:
            period_start = date.fromisoformat(selected[0])
            period_end = date.fromisoformat(selected[1])
            subject_records = tuple(
                record
                for record in load_subject_history(
                    report_slots(),
                    cache=self.subject_cache,
                )
                if record.period_start == period_start and record.period_end == period_end
            )
            for record in subject_records:
                identity = self._record_device_identity(record)
                device_label, device_tooltip, _is_current = self._record_device_label(
                    record,
                    device_by_slot,
                    include_serial=True,
                )
                key = (identity, record.subject_type, record.subject_id)
                previous = subject_rows.get(
                    key,
                    (
                        record.subject_name,
                        record.latest_total,
                        record.subject_type,
                        device_label,
                        device_tooltip,
                    ),
                )
                subject_rows[key] = (
                    record.subject_name,
                    max((value for value in (previous[1], record.latest_total) if value is not None), default=None),
                    record.subject_type,
                    device_label,
                    device_tooltip,
                )
        top_subjects = sorted(subject_rows.values(), key=lambda item: item[1] if item[1] is not None else -1, reverse=True)[:8]
        self.report_users.clearSpans()
        self.report_users.setRowCount(max(1, len(top_subjects)))
        if not top_subjects:
            empty = QTableWidgetItem("ไม่พบ User Authentication / Account Track ในรอบบิลนี้")
            empty.setForeground(QColor(C_TEXT2))
            self.report_users.setItem(0, 0, empty)
            self.report_users.setSpan(0, 0, 1, 2)
        for row, (name, usage, _subject_type, device_label, device_tooltip) in enumerate(top_subjects):
            self.report_users.setRowHeight(row, 42)
            for column, text in enumerate(
                (
                    f"{name}\n{device_label}",
                    f"{usage:,.0f}" if usage is not None else '—',
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(
                    f"{name}\n{device_tooltip}"
                    if column == 0
                    else device_tooltip
                )
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.report_users.setItem(row, column, item)

        warnings: list[str] = []
        identities_by_slot = frozen_identities_by_slot
        historical_identities: set[str] = set()
        for record in records:
            identity = self._record_device_identity(record)
            if not self._record_matches_current_device(
                record,
                enabled_by_slot.get(record.device_slot),
            ):
                historical_identities.add(identity)
        mixed_slots = sum(1 for identities in identities_by_slot.values() if len(identities) > 1)
        if mixed_slots:
            warnings.append(
                f"พบเครื่องเดิม/ปัจจุบันร่วมกัน {mixed_slots} slot · "
                "ยอดรวมแยกตาม frozen Serial snapshot"
            )
        elif historical_identities:
            warnings.append(
                f"พบข้อมูลเครื่องเดิม {len(historical_identities)} identity · "
                "ยอดรวมใช้ frozen name/Serial snapshot"
            )
        if held:
            warnings.append(f"Hold {held:,} device-day ไม่รวมในยอด")
        if incomplete:
            warnings.append(f"ข้อมูลไม่สมบูรณ์ {incomplete:,} device-day")
        if warnings:
            self._report_overview_review_detail = (
                "\n".join(warnings)
                + "\n\nตรวจรายละเอียดเพิ่มเติมได้ที่ Settings → ตรวจสอบรอบบิล และสถานะการอ่าน"
            )
            review_count = held + incomplete
            review_label = (
                f"มีข้อมูลรอตรวจสอบ {review_count:,} device-day"
                if review_count
                else "มีข้อมูลรอตรวจสอบ"
            )
            self.report_overview_warning.setText(
                f'<a href="review">{review_label}</a>'
            )
            self.report_overview_warning.setVisible(True)
            self.report_overview_warning.setStyleSheet(
                text_styles.label('#B42318', padding='2px 0', font_weight='600')
            )
        else:
            self._report_overview_review_detail = ""
            self.report_overview_warning.clear()
            self.report_overview_warning.setVisible(False)

    def refresh(self) -> None:
        if self._staged:
            self.refresh_visible()
            return
        try:
            self.reports_error.setVisible(False)
            super().refresh()
            self._populate_report_periods()
            self._refresh_report_center()
        except Exception as error:
            if hasattr(self, "report_center"):
                self.report_center.show_error(
                    "โหลด Reports ไม่สำเร็จ · ซ่อนตัวเลขไว้เพื่อป้องกันการอ่านผิด "
                    f"· {type(error).__name__}: {error}"
                )
            self.reports_error.setText(
                "โหลด Reports ไม่สำเร็จ · ยอดบนหน้าจอถูกซ่อนไว้เพื่อป้องกันการอ่านผิด "
                f"· {type(error).__name__}: {error}"
            )
            self.reports_error.setVisible(True)
            for value in self.report_kpis.values():
                value.setText("—")
            self.report_period_note.setText("ไม่สามารถยืนยันข้อมูลจาก Posted Ledger ได้")
            self.report_overview_warning.setText(
                "Needs Review · กดรีเฟรชอีกครั้ง หรือตรวจสอบรอบบิลและสถานะการอ่านใน Settings"
            )
            self.report_overview_warning.setStyleSheet(
                text_styles.label('#B42318', background='#FFF1F1', padding='8px 10px', font_weight='700')
            )
            self.btn_export_monthly.setEnabled(False)
            self.btn_export_users.setEnabled(False)
            if hasattr(self, "btn_save_png"):
                self.btn_save_png.setEnabled(False)

    def _build_users_tab(self) -> None:
        layout = QVBoxLayout(self.tab_users)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("รอบบิล:"))
        self.cmb_month_users = QComboBox()
        self.cmb_month_users.setProperty("i18n_items", True)
        self.cmb_month_users.setMinimumWidth(190)
        self.cmb_month_users.currentIndexChanged.connect(self._on_month_users_changed)
        controls.addWidget(self.cmb_month_users)
        controls.addStretch()
        self.search_users = QLineEdit()
        self.search_users.setPlaceholderText("ค้นหา User / Account / เครื่อง")
        self.search_users.setFixedWidth(240)
        self.search_users.textChanged.connect(self._filter_users)
        controls.addWidget(self.search_users)
        self.btn_export_users = btn("Export Excel", "outline")
        self.btn_export_users.clicked.connect(
            lambda: self._export_to_excel(self.tbl_users, "KOMI_V5_User_Account_History")
        )
        controls.addWidget(self.btn_export_users)
        layout.addLayout(controls)

        self.users_boundary = QLabel(
            "User Authentication / Account Track · Total Counter จริงเท่านั้น · "
            "ใช้ดูการกระจายงานและไม่ใช้คำนวณค่าใช้จ่าย"
        )
        self.users_boundary.setWordWrap(True)
        self.users_boundary.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='8px 10px'))
        layout.addWidget(self.users_boundary)

        self.users_reconciliation = QLabel("ยังไม่มีข้อมูล User/Account สำหรับตรวจ Coverage")
        self.users_reconciliation.setWordWrap(True)
        self.users_reconciliation.setStyleSheet(text_styles.label('#64748B', background='#F8FAFC', padding='8px 10px'))
        layout.addWidget(self.users_reconciliation)

        self.lbl_count_users = QLabel("")
        self.lbl_count_users.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(self.lbl_count_users)

        self.tbl_users = FrozenLeftTable()
        self.tbl_users.setAlternatingRowColors(False)
        layout.addWidget(self.tbl_users, 1)
        self._subject_history_records: tuple[SubjectPeriodUsage, ...] = ()
        self._visible_subject_records: tuple[SubjectPeriodUsage, ...] = ()

    @staticmethod
    def _subject_period_label(record: SubjectPeriodUsage) -> str:
        return f"{record.period_start:%d/%m/%Y} – {record.period_end:%d/%m/%Y}"

    def _populate_month_dropdown_users(self, _slot: int) -> None:
        self._subject_history_records = load_subject_history(
            report_slots(),
            cache=self.subject_cache,
        )
        periods = sorted(
            {self._period_key(record) for record in self._subject_history_records},
            reverse=True,
        )
        current = self.cmb_month_users.currentData()
        self.cmb_month_users.blockSignals(True)
        self.cmb_month_users.clear()
        for period in periods:
            sample = next(
                record
                for record in self._subject_history_records
                if self._period_key(record) == period
            )
            self.cmb_month_users.addItem(self._subject_period_label(sample), period)
        if not periods:
            self.cmb_month_users.addItem("ไม่มีข้อมูล", None)
        elif current:
            index = self.cmb_month_users.findData(current)
            self.cmb_month_users.setCurrentIndex(max(0, index))
        self.cmb_month_users.blockSignals(False)
        self._refresh_users(self._current_slot)

    def _filter_users(self, _text: str) -> None:
        self._render_subject_rows()

    def _refresh_users(self, _slot: int) -> None:
        selected = self.cmb_month_users.currentData()
        if selected is None:
            self._visible_subject_records = ()
            self._render_subject_rows()
            self.lbl_count_users.setText("ไม่มีข้อมูล")
            self.users_reconciliation.setText("ยังไม่มีข้อมูล User/Account สำหรับตรวจ Coverage")
            self.btn_export_users.setEnabled(False)
            return
        period_start = date.fromisoformat(selected[0])
        period_end = date.fromisoformat(selected[1])
        self._visible_subject_records = tuple(
            record
            for record in self._subject_history_records
            if record.period_start == period_start and record.period_end == period_end
        )
        self._render_subject_rows()
        self._render_subject_coverage(period_start, period_end)
        self.btn_export_users.setEnabled(bool(self._visible_subject_records))

    def _render_subject_rows(self) -> None:
        device_list = self._historical_devices()
        logical_groups = self._logical_device_groups(
            self._visible_subject_records,
            device_list,
        )
        group_by_identity = {group["identity"]: group for group in logical_groups}
        text = self.search_users.text().strip().casefold()

        grouped: dict[tuple[str, str], dict[str, list[SubjectPeriodUsage]]] = {}
        for record in self._visible_subject_records:
            identity = self._record_device_identity(record)
            grouped.setdefault((record.subject_type, record.subject_id), {}).setdefault(
                identity,
                [],
            ).append(record)

        def matches(records: dict[str, list[SubjectPeriodUsage]]) -> bool:
            searchable: list[str] = []
            for identity, identity_records in records.items():
                for record in identity_records:
                    searchable.extend((record.subject_name, record.subject_id, record.subject_type))
                group = group_by_identity.get(identity)
                searchable.append(group["label"] if group else identity)
            return not text or any(text in value.casefold() for value in searchable)

        rows = [records for records in grouped.values() if matches(records)]
        rows.sort(
            key=lambda records: (
                -sum(
                    record.period_usage
                    for identity_records in records.values()
                    for record in identity_records
                ),
                next(
                    record
                    for identity_records in records.values()
                    for record in identity_records
                ).subject_name.casefold(),
            )
        )
        headers = [
            "User / Account",
            *(group["label"] for group in logical_groups),
            "รวมทุกเครื่อง",
        ]
        table = self.tbl_users
        table.setColumnCount(len(headers))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(headers)
        for column, group in enumerate(logical_groups, start=1):
            item = table.horizontalHeaderItem(column)
            if item is not None:
                item.setToolTip(group["tooltip"])
        table.setColumnWidth(0, 230)
        for column in range(1, len(headers)):
            table.setColumnWidth(column, 155)

        for row_index, records in enumerate(rows):
            sample = next(
                record
                for identity_records in records.values()
                for record in identity_records
            )
            label = sample.subject_name
            if sample.subject_type != "user":
                label = f"{label}  [Account Track]"
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            label_item.setToolTip(
                f"subject_type={sample.subject_type}\nsubject_id={sample.subject_id}\n"
                "แถวเดียวกันใช้ subject ID เดียวกันข้ามเครื่อง"
            )
            if row_index % 2:
                label_item.setBackground(QColor("#FAFAFA"))
            table.setItem(row_index, 0, label_item)

            total_usage = 0.0
            for column, group in enumerate(logical_groups, start=1):
                identity_records = records.get(group["identity"], ())
                period_usage = sum(record.period_usage for record in identity_records)
                value = "—" if not identity_records else f"{period_usage:,.0f}"
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if identity_records:
                    total_usage += period_usage
                    status_parts: list[str] = []
                    reset_count = sum(record.reset_count for record in identity_records)
                    missing_baseline_days = sum(
                        record.missing_baseline_days for record in identity_records
                    )
                    if reset_count:
                        status_parts.append(f"reset {reset_count}")
                    if missing_baseline_days:
                        status_parts.append(f"ไม่มี baseline {missing_baseline_days} วัน")
                    for record in identity_records:
                        for warning in record.warnings:
                            if warning not in status_parts:
                                status_parts.append(warning)
                    latest_value = max(
                        (record.latest_at or "" for record in identity_records),
                        default="",
                    )
                    latest = (latest_value or "—").replace("T", " ")[:16]
                    latest_total = max(
                        (record.latest_total for record in identity_records if record.latest_total is not None),
                        default=None,
                    )
                    latest_text = f'{latest_total:,.0f}' if latest_total is not None else '—'
                    item.setToolTip(
                        f"{group['tooltip']}\n"
                        f"Usage รอบบิล: {period_usage:,.0f}\n"
                        f"Total Counter ล่าสุด: {latest_text}\n"
                        f"ข้อมูลล่าสุด: {latest}\n"
                        f"subject_id={sample.subject_id}\n"
                        f"สถานะ: {'Needs Review · ' + ' · '.join(status_parts) if status_parts else 'OK'}"
                    )
                    if any(record.needs_review for record in identity_records):
                        item.setForeground(QColor(C_RED))
                        item.setBackground(QColor("#FFF1F1"))
                elif row_index % 2:
                    item.setBackground(QColor("#FAFAFA"))
                table.setItem(row_index, column, item)

            total_item = QTableWidgetItem(f"{total_usage:,.0f}")
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            total_item.setFont(fnt(F_SM, True))
            total_item.setForeground(QColor("#123262"))
            if row_index % 2:
                total_item.setBackground(QColor("#FAFAFA"))
            table.setItem(row_index, len(headers) - 1, total_item)
        self.lbl_count_users.setText(
            f"พบ {len(rows):,} User/Account · ตัวเลขคือ Usage รอบบิล · ไม่มีการคำนวณค่าใช้จ่าย"
        )

    def _render_subject_coverage(self, period_start: date, period_end: date) -> None:
        devices = self._historical_devices()
        monthly = load_monthly_usage(report_slots(), cache=self.cache)
        period_monthly = tuple(
            record
            for record in monthly
            if record.period_start == period_start and record.period_end == period_end
        )
        logical_groups = self._logical_device_groups(
            (*period_monthly, *self._visible_subject_records),
            devices,
        )
        group_by_identity = {group["identity"]: group for group in logical_groups}
        device_usage: dict[str, float] = {}
        for record in period_monthly:
            identity = self._record_device_identity(record)
            device_usage[identity] = device_usage.get(identity, 0.0) + record.total
        subject_usage: dict[str, float] = {}
        warnings: list[str] = []
        details: list[str] = []
        for record in self._visible_subject_records:
            identity = self._record_device_identity(record)
            subject_usage[identity] = subject_usage.get(identity, 0.0) + record.period_usage
            if record.needs_review:
                subject_warnings: list[str] = []
                if record.reset_count:
                    subject_warnings.append(f"reset {record.reset_count}")
                if record.missing_baseline_days:
                    subject_warnings.append(f"ไม่มี baseline {record.missing_baseline_days} วัน")
                subject_warnings.extend(record.warnings)
                group = group_by_identity.get(identity)
                device_name = group["label"] if group else identity
                warnings.append(f"{device_name} / {record.subject_name}: {' · '.join(subject_warnings)}")
        for group in logical_groups:
            identity = group["identity"]
            device_name = group["label"]
            user_total = subject_usage.get(identity, 0.0)
            web_total = device_usage.get(identity)
            if web_total is None:
                details.append(f"{device_name}: ยังไม่มี Device Meter สำหรับเทียบ")
                continue
            difference = web_total - user_total
            if user_total > web_total + 0.001:
                warnings.append(
                    f"{device_name}: User/Account {user_total:,.0f} มากกว่า Device Meter {web_total:,.0f} "
                    f"({user_total - web_total:+,.0f})"
                )
            coverage = user_total / web_total * 100 if web_total else 0.0
            details.append(
                f"{device_name}: User/Account {user_total:,.0f} / Device {web_total:,.0f} "
                f"· Coverage {coverage:.1f}% · Public/Untracked {max(0.0, difference):,.0f}"
            )
        if warnings:
            self.users_reconciliation.setText("Needs Review\n" + "\n".join(warnings + details))
            self.users_reconciliation.setStyleSheet(
                text_styles.label('#B42318', background='#FFF1F1', padding='8px 10px', font_weight='700')
            )
        else:
            self.users_reconciliation.setText(
                "Coverage เป็นข้อมูลประกอบและไม่จำเป็นต้องครบ 100%\n" + "\n".join(details)
            )
            self.users_reconciliation.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='8px 10px'))

    def _build_current_tab(self) -> None:
        layout = QVBoxLayout(self.tab_current)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("ค่ามิเตอร์ปัจจุบัน — ทุกเครื่อง")
        title.setFont(fnt(F_MD, True))
        header.addWidget(title)
        header.addStretch()
        self.chk_diff = VisibleCheckBox("รายละเอียดวันนี้")
        self.chk_diff.setMinimumWidth(125)
        self.chk_diff.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.chk_diff.setChecked(False)
        self.chk_diff.stateChanged.connect(self._refresh_current_all)
        header.addWidget(self.chk_diff)
        self.chk_hide_zero = VisibleCheckBox("ซ่อน Counter ที่เป็น 0")
        self.chk_hide_zero.setMinimumWidth(170)
        self.chk_hide_zero.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.chk_hide_zero.setChecked(False)
        self.chk_hide_zero.stateChanged.connect(self._refresh_current_all)
        header.addWidget(self.chk_hide_zero)
        layout.addLayout(header)

        explanation = QLabel(
            "ค่าปัจจุบัน = มิเตอร์สะสมล่าสุด · ต้นวัน = ค่าครั้งแรกของวัน "
            "· เพิ่มวันนี้ = ยอดที่เพิ่มจากต้นวัน"
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='8px 10px'))
        layout.addWidget(explanation)

        self.current_status = QLabel("")
        self.current_status.setWordWrap(True)
        self.current_status.setStyleSheet(text_styles.label(C_TEXT2, font_size='11px'))
        layout.addWidget(self.current_status)

        self.tbl_current_all = FrozenLeftTable()
        self.tbl_current_all.setAlternatingRowColors(False)
        layout.addWidget(self.tbl_current_all, 1)

        self.current_source_note = QLabel(
            "ค่ามิเตอร์ทั้งหมดอ่านจาก Web Connection Device Meter; SNMP ใช้ตรวจสถานะ/trigger เท่านั้น "
            "และจะคงค่า Web ล่าสุดเมื่อเครื่อง Offline"
        )
        self.current_source_note.setWordWrap(True)
        self.current_source_note.setStyleSheet(text_styles.label(C_TEXT2, padding='3px 2px'))
        self.current_source_note.setVisible(False)
        layout.addWidget(self.current_source_note)

    def _build_monthly_tab(self) -> None:
        layout = QVBoxLayout(self.tab_monthly)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

        self.lbl_billing_day = QLabel("")
        self.lbl_billing_day.setStyleSheet(text_styles.label('#245268', background='#EEF6F9', padding='8px 10px'))
        layout.addWidget(self.lbl_billing_day)

        heading = QHBoxLayout()
        self.history_title = QLabel("ประวัติการใช้งานย้อนหลัง — ทุกเครื่อง")
        self.history_title.setFont(fnt(F_MD, True))
        heading.addWidget(self.history_title)
        heading.addStretch()
        layout.addLayout(heading)

        controls = QHBoxLayout()
        controls.setSpacing(14)
        controls.addStretch()
        controls.addWidget(QLabel("มุมมอง:"))
        self.history_view_combo = QComboBox()
        self.history_view_combo.setProperty("i18n_items", True)
        self.history_view_combo.addItem("รายวัน", "daily")
        self.history_view_combo.addItem("รายสัปดาห์", "weekly")
        self.history_view_combo.addItem("รายเดือน", "monthly")
        self.history_view_combo.addItem("รายไตรมาส", "quarterly")
        self.history_view_combo.addItem("รายปี", "yearly")
        self.history_view_combo.setCurrentIndex(2)
        self.history_view_combo.setMinimumWidth(130)
        self.history_view_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_monthly(self._current_slot)
        )
        controls.addWidget(self.history_view_combo)
        self.chk_detail_monthly = QCheckBox("รายละเอียดเพิ่มเติม")
        self.chk_detail_monthly.setMinimumWidth(165)
        self.chk_detail_monthly.setChecked(False)
        self.chk_detail_monthly.stateChanged.connect(lambda _state: self._refresh_monthly(self._current_slot))
        controls.addWidget(self.chk_detail_monthly)
        self.chk_waste_monthly = QCheckBox("ค่าใช้จ่ายสุทธิจาก Ledger")
        self.chk_waste_monthly.setMinimumWidth(200)
        self.chk_waste_monthly.setChecked(True)
        self.chk_waste_monthly.stateChanged.connect(lambda _state: self._refresh_monthly(self._current_slot))
        controls.addWidget(self.chk_waste_monthly)
        self.btn_export_monthly = btn("Export Excel", "outline")
        self.btn_export_monthly.clicked.connect(
            lambda: self._export_to_excel(self.tbl_monthly, "KOMI_V5_Monthly_History")
        )
        controls.addWidget(self.btn_export_monthly)
        layout.addLayout(controls)

        self.tbl_monthly = FrozenLeftTable()
        self.tbl_monthly.setAlternatingRowColors(False)
        layout.addWidget(self.tbl_monthly, 1)

        self.monthly_summary = QLabel("")
        self.monthly_summary.setStyleSheet(text_styles.label('#123262', background='#F8FAFC', padding='9px 12px', font_weight='700'))
        layout.addWidget(self.monthly_summary)

        note = QLabel(
            "เลือกดูรายวัน รายสัปดาห์ รายเดือน รายไตรมาส หรือรายปี · "
            "Usage และค่าใช้จ่ายมาจาก Posted Ledger เท่านั้น · "
            "Pricelist, ส่วนลด, Cost category และรอบบิลยึดค่าที่บันทึกของแต่ละวัน"
        )
        note.setWordWrap(True)
        note.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(note)

    @staticmethod
    def _number(value: float | int | None, *, delta: bool = False) -> str:
        if value is None:
            return "—"
        text = f"{float(value):,.0f}"
        return f"+{text}" if delta and float(value) > 0 else text

    @staticmethod
    def _soft_tone(color: str, white_ratio: float) -> QColor:
        source = QColor(color)
        ratio = min(1.0, max(0.0, white_ratio))
        keep = 1.0 - ratio
        return QColor(
            round(source.red() * keep + 255 * ratio),
            round(source.green() * keep + 255 * ratio),
            round(source.blue() * keep + 255 * ratio),
        )

    def _current_values(self, device: DeviceConfig) -> tuple[dict, dict, dict, dict]:
        state = self.cache.load(device.slot, date.today()) or {}
        latest = state.get("latest") or latest_counters(device.slot)
        opening = state.get("opening") or {}
        delta = state.get("delta") or {}
        current_groups = default_usage_groups(latest)
        opening_groups = default_usage_groups(opening)
        delta_groups = default_usage_groups(delta)
        current_total = latest.get("counter.total.total")
        opening_total = opening.get("counter.total.total")
        # Daily Cache is the segmented source of truth for "today increased".
        # Recomputing latest-opening would hide a reset as zero.
        delta_total = delta.get("counter.total.total")
        return (
            {"__total_meter__": current_total, **current_groups},
            {"__total_meter__": opening_total, **opening_groups},
            {"__total_meter__": delta_total, **delta_groups},
            state,
        )

    def _refresh_current_all(self) -> None:
        table = self.tbl_current_all
        devices = self.repository.list(enabled_only=True)
        show_comparison = self.chk_diff.isChecked()
        hide_zero = self.chk_hide_zero.isChecked()
        columns_per_device = 3 if show_comparison else 1
        subheader_template = (
            ("ปัจจุบัน", "ต้นวัน", "+วันนี้")
            if show_comparison
            else ("ปัจจุบัน",)
        )
        headers = ["รายการ"]
        header_groups: list[tuple[str, int, str]] = []
        subheaders: list[str] = []
        values: list[tuple[dict, dict, dict, dict]] = []
        status_parts: list[str] = []
        for device in devices:
            current, opening, delta, state = self._current_values(device)
            values.append((current, opening, delta, state))
            header_tone = self._soft_tone(
                SLOT_COLORS[device.slot],
                0.82,
            ).name()
            header_groups.append(
                (device.name, columns_per_device, header_tone)
            )
            subheaders.extend(subheader_template)
            headers.extend(subheader_template)
            latest_at = state.get("last_success") or device.last_success_at or "ยังไม่มีข้อมูล"
            latest_label = str(latest_at)
            try:
                parsed_latest = datetime.fromisoformat(
                    latest_label.replace("Z", "+00:00")
                ).astimezone()
                if parsed_latest.date() == date.today():
                    latest_label = f"{parsed_latest:%H:%M} น."
                else:
                    latest_label = f"{parsed_latest:%d/%m/%Y %H:%M} น."
            except (TypeError, ValueError):
                pass
            status_parts.append(
                f"{device.name} · "
                f"{'Online' if device.connection_status == 'online' else 'คงค่าล่าสุด'} · "
                f"ค่ามิเตอร์ล่าสุด {latest_label}"
            )

        visible_rows: list[tuple[str, str | None]] = []
        pending_section: tuple[str, None] | None = None
        for label, key in self.CURRENT_ROWS:
            if key is None:
                pending_section = (label, None)
                continue
            current_values = [current.get(key) for current, _opening, _delta, _state in values]
            has_nonzero = any(
                value is not None and abs(float(value)) > 0
                for value in current_values
            )
            if hide_zero and not has_nonzero:
                continue
            if pending_section is not None:
                visible_rows.append(pending_section)
                pending_section = None
            visible_rows.append((label, key))

        table.setColumnCount(max(1, len(headers)))
        table.setRowCount(len(visible_rows))
        table.setHorizontalHeaderLabels(headers)
        table.setGroupedHeader("รายการ", header_groups, subheaders)
        table.setColumnWidth(0, 190)
        for device_index in range(len(devices)):
            base = 1 + device_index * columns_per_device
            table.setColumnWidth(base, 160 if not show_comparison else 130)
            if show_comparison:
                table.setColumnWidth(base + 1, 115)
                table.setColumnWidth(base + 2, 105)
        table.setGroupSeparators(
            [
                (device_index + 1) * columns_per_device
                for device_index in range(max(0, len(devices) - 1))
            ],
            color="#8291A7",
            width=2,
        )

        section_background = QColor("#EAF1FA")
        for row_index, (label, key) in enumerate(visible_rows):
            is_section = key is None
            label_item = QTableWidgetItem(label)
            label_item.setFont(fnt(F_SM, is_section))
            label_item.setForeground(QColor("#123262" if is_section else C_TEXT2))
            if is_section:
                label_item.setBackground(section_background)
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_index, 0, label_item)

            for device_index, (current, opening, delta, _state) in enumerate(values):
                base = 1 + device_index * columns_per_device
                if key and show_comparison:
                    row_values = (
                        current.get(key),
                        opening.get(key),
                        delta.get(key),
                    )
                elif key:
                    row_values = (current.get(key),)
                else:
                    row_values = (None,) * columns_per_device
                for offset, value in enumerate(row_values):
                    item = QTableWidgetItem("" if is_section else self._number(value, delta=offset == 2))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item.setFont(fnt(F_SM, offset in (0, 2)))
                    if is_section:
                        item.setBackground(section_background)
                    elif row_index % 2:
                        item.setBackground(QColor("#FAFAFA"))
                    if not is_section:
                        item.setForeground(
                            QColor(C_GREEN if show_comparison and offset == 2 else "#172033")
                        )
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row_index, base + offset, item)

        self.current_status.setText("  |  ".join(status_parts) if status_parts else "ยังไม่ได้ตั้งค่าเครื่องพิมพ์")

    @staticmethod
    def _history_period_label(record: MonthlyUsage, granularity: HistoryGranularity) -> str:
        thai_months = (
            "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
            "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
        )
        start = record.period_start
        end = record.period_end

        def thai_date(value: date) -> str:
            return f"{value:%d/%m}/{value.year + 543}"

        if granularity == "daily":
            return thai_date(start)
        if granularity == "weekly":
            return f"{thai_date(start)}–{thai_date(end)}"
        if granularity == "monthly":
            return f"{thai_months[end.month - 1]} {end.year + 543} · {start:%d/%m}–{end:%d/%m}"
        if granularity == "quarterly":
            quarter = ((end.month - 1) // 3) + 1
            return f"ไตรมาส {quarter}/{end.year + 543} · {thai_date(start)}–{thai_date(end)}"
        return f"ปี {end.year + 543} · {thai_date(start)}–{thai_date(end)}"

    def _refresh_monthly(self, _slot: int) -> None:
        devices = self._historical_devices()
        granularity = self.history_view_combo.currentData() or "monthly"
        records = load_usage_history(
            report_slots(),
            granularity=granularity,
            cache=self.cache,
        )
        logical_groups = self._logical_device_groups(records, devices)
        record_map: dict[tuple[date, date, str], list[MonthlyUsage]] = {}
        for record in records:
            key = (
                record.period_start,
                record.period_end,
                self._record_device_identity(record),
            )
            record_map.setdefault(key, []).append(record)
        periods = sorted(
            {(record.period_start, record.period_end) for record in records},
            reverse=True,
        )
        sample_by_period = {
            (record.period_start, record.period_end): record for record in records
        }
        show_detail = self.chk_detail_monthly.isChecked()
        use_net = self.chk_waste_monthly.isChecked()

        subheader_template = ["Color", "B&W", "Cost"]
        if show_detail:
            subheader_template.extend(("A3 Color", "A3 B&W", "A4 Color", "A4 B&W", "Scan"))
        group_span = len(subheader_template)
        headers = ["รอบบิล"]
        header_groups: list[tuple[str, int, str]] = []
        header_group_tooltips: list[str] = []
        subheaders: list[str] = []
        for group in logical_groups:
            header_tone = self._soft_tone(group["color"], 0.82).name()
            header_groups.append((group["label"], group_span, header_tone))
            header_group_tooltips.append(group["tooltip"])
            subheaders.extend(subheader_template)
            headers.extend(subheader_template)
        header_groups.append(("รวมทุกเครื่อง", group_span, "#DCE8F5"))
        subheaders.extend(subheader_template)
        headers.extend(subheader_template)

        table = self.tbl_monthly
        table.setColumnCount(len(headers))
        table.setRowCount(len(periods))
        table.setHorizontalHeaderLabels(headers)
        table.setGroupedHeader("รอบบิล", header_groups, subheaders)
        header_column = 1
        for tooltip in header_group_tooltips:
            item = table.groupedHeaderItem(0, header_column)
            if item is not None:
                item.setToolTip(tooltip)
            header_column += group_span
        table.setColumnWidth(0, 220)
        for column in range(1, len(headers)):
            table.setColumnWidth(column, 104 if show_detail else 112)

        total_usage = 0.0
        total_cost = 0.0
        any_provisional = False
        all_provisional_costs_available = True
        for row_index, period in enumerate(periods):
            sample = sample_by_period[period]
            month_item = QTableWidgetItem(self._history_period_label(sample, granularity))
            month_item.setFont(fnt(F_SM, True))
            month_item.setForeground(QColor("#123262"))
            month_item.setBackground(QColor("#EAF1FA"))
            month_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row_index, 0, month_item)

            column = 1
            row_usage = 0.0
            row_cost = 0.0
            row_totals = [0.0] * group_span
            row_has_provisional = False
            row_cost_available = True
            for group in logical_groups:
                group_records = record_map.get(
                    (period[0], period[1], group["identity"]),
                    (),
                )
                group_has_provisional = any(
                    record.provisional_days for record in group_records
                )
                group_cost_available = all(
                    record.provisional_cost_available
                    for record in group_records
                    if record.provisional_days
                )
                usage = sum(
                    record.total + record.provisional_total
                    for record in group_records
                )
                cost = sum(
                    (
                        record.net_cost + record.provisional_net_cost
                        if use_net
                        else record.gross_cost + record.provisional_gross_cost
                    )
                    for record in group_records
                )
                color = sum(
                    record.a3_color
                    + record.a4_color
                    + record.provisional_a3_color
                    + record.provisional_a4_color
                    for record in group_records
                )
                bw = sum(
                    record.a3_bw
                    + record.a4_bw
                    + record.provisional_a3_bw
                    + record.provisional_a4_bw
                    for record in group_records
                )
                row_usage += usage
                row_cost += cost
                row_has_provisional = row_has_provisional or group_has_provisional
                row_cost_available = row_cost_available and group_cost_available
                values = [color, bw, cost]
                if show_detail:
                    values.extend(
                        (
                            sum(
                                record.a3_color + record.provisional_a3_color
                                for record in group_records
                            ),
                            sum(
                                record.a3_bw + record.provisional_a3_bw
                                for record in group_records
                            ),
                            sum(
                                record.a4_color + record.provisional_a4_color
                                for record in group_records
                            ),
                            sum(
                                record.a4_bw + record.provisional_a4_bw
                                for record in group_records
                            ),
                            sum(
                                record.scan + record.provisional_scan
                                for record in group_records
                            ),
                        )
                    )
                for value_index, value in enumerate(values):
                    is_cost = value_index == 2
                    row_totals[value_index] += value
                    if is_cost and not group_cost_available:
                        text = "—"
                    else:
                        estimate = "~" if group_has_provisional else ""
                        text = (
                            f"{estimate}{value:,.2f}"
                            if is_cost
                            else f"{estimate}{value:,.0f}"
                        )
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item.setForeground(QColor(C_GREEN if is_cost else group["color"]))
                    item.setToolTip(group["tooltip"])
                    white_ratio = 0.90 if row_index % 2 == 0 else 0.86
                    item.setBackground(self._soft_tone(group["color"], white_ratio))
                    table.setItem(row_index, column, item)
                    column += 1

            for value_index, value in enumerate(row_totals):
                is_cost = value_index == 2
                if is_cost and not row_cost_available:
                    text = "—"
                else:
                    estimate = "~" if row_has_provisional else ""
                    text = (
                        f"{estimate}{value:,.2f}"
                        if is_cost
                        else f"{estimate}{value:,.0f}"
                    )
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(fnt(F_SM, True))
                item.setForeground(QColor(C_GREEN if is_cost else "#123262"))
                item.setBackground(QColor("#EDF3F9" if row_index % 2 == 0 else "#E4EDF6"))
                table.setItem(row_index, column, item)
                column += 1
            total_usage += row_usage
            total_cost += row_cost
            any_provisional = any_provisional or row_has_provisional
            all_provisional_costs_available = (
                all_provisional_costs_available and row_cost_available
            )

        view_name = self.history_view_combo.currentText()
        self.history_title.setText(f"ประวัติการใช้งานย้อนหลัง — {view_name} · ทุกเครื่อง")
        self.lbl_billing_day.setText(
            "รอบบิลยึดค่าที่บันทึกใน Ledger ของแต่ละวัน · "
            "เครื่องหมาย ~ คือข้อมูลวันนี้จาก Daily Cache · "
            + (
                "ค่าใช้จ่ายสุทธิหลังส่วนลดที่ถูกแช่แข็งต่อรายการ"
                if use_net
                else "ค่าใช้จ่ายก่อนส่วนลด (Gross) ที่ถูกแช่แข็งต่อรายการ"
            )
        )
        held_days = sum(record.held_days for record in records)
        incomplete_days = sum(record.incomplete_days for record in records)
        quality_parts: list[str] = []
        identities_by_slot: dict[int, set[str]] = {}
        current_by_slot = {device.slot: device for device in devices}
        historical_identities: set[str] = set()
        for record in records:
            identity = self._record_device_identity(record)
            identities_by_slot.setdefault(int(record.device_slot), set()).add(identity)
            if not self._record_matches_current_device(
                record,
                current_by_slot.get(record.device_slot),
            ):
                historical_identities.add(identity)
        mixed_slots = sum(1 for identities in identities_by_slot.values() if len(identities) > 1)
        if mixed_slots:
            quality_parts.append(
                f"เครื่องเดิม/ปัจจุบันร่วมกัน {mixed_slots} slot · แยกตาม Serial snapshot"
            )
        elif historical_identities:
            quality_parts.append(
                f"ข้อมูลเครื่องเดิม {len(historical_identities)} identity · ใช้ frozen snapshot"
            )
        if held_days:
            quality_parts.append(f"Hold {held_days:,} device-day ไม่รวมในยอด")
        if incomplete_days:
            quality_parts.append(f"ข้อมูลไม่สมบูรณ์ {incomplete_days:,} device-day")
        amendment_remarks = tuple(dict.fromkeys(note for record in records for note in record.remarks))
        self.monthly_summary.setToolTip("\n".join(amendment_remarks))
        if amendment_remarks:
            quality_parts.append("มีฉบับแก้ไขตามหลักฐาน Web · ดูหมายเหตุและประวัติบัญชี")
        if any_provisional:
            quality_parts.append("วันนี้เป็นข้อมูลระหว่างวัน ยังไม่ลง Billing Ledger")
        if not periods:
            self.monthly_summary.setText(
                "ยังไม่มี Posted Ledger สำหรับมุมมองนี้ · ไม่มีการคำนวณยอดหรือค่าใช้จ่าย"
            )
            self.monthly_summary.setStyleSheet(
                text_styles.label('#475467', background='#F2F4F7', padding='9px 12px', font_weight='700')
            )
        else:
            total_cost_text = (
                f"~{total_cost:,.2f}"
                if any_provisional and all_provisional_costs_available
                else ("—" if not all_provisional_costs_available else f"{total_cost:,.2f}")
            )
            total_usage_text = (
                f"~{total_usage:,.0f}"
                if any_provisional
                else f"{total_usage:,.0f}"
            )
            self.monthly_summary.setText(
                f"{len(periods):,} ช่วง{view_name} · Usage รวม {total_usage_text} · "
                f"ค่าใช้จ่ายรวม {total_cost_text} บาท"
                + (f" · {' · '.join(quality_parts)}" if quality_parts else "")
            )
            self.monthly_summary.setStyleSheet(
                reports_styles.quality_summary(bool(quality_parts))
            )
        self.btn_export_monthly.setEnabled(bool(periods))

    def _prepare_graph_data(self) -> dict:
        """Build Trend exclusively from V5 Posted Ledger projections."""
        records = load_usage_history(
            report_slots(),
            granularity="monthly",
            cache=self.cache,
        )
        subject_records = load_subject_history(
            report_slots(),
            cache=self.subject_cache,
        )
        slot_monthly: list[dict[str, dict]] = [{} for _ in range(3)]
        names_by_slot: dict[int, set[str]] = {}

        def month_bucket(slot: int, key: str) -> dict:
            return slot_monthly[slot].setdefault(
                key,
                {
                    "a4_color": 0.0,
                    "a4_bw": 0.0,
                    "a3_color": 0.0,
                    "a3_bw": 0.0,
                    "total": 0.0,
                    "total_color": 0.0,
                    "total_bw": 0.0,
                    "copy_color": 0.0,
                    "copy_bw": 0.0,
                    "print_color": 0.0,
                    "print_bw": 0.0,
                    "meter_color": 0.0,
                    "meter_bw": 0.0,
                    "provisional_total": 0.0,
                    "provisional_print_color": 0.0,
                    "provisional_print_bw": 0.0,
                    "provisional_copy_color": 0.0,
                    "provisional_copy_bw": 0.0,
                    "provisional_days": 0,
                    "users": {},
                },
            )

        for record in records:
            slot = int(record.device_slot)
            if not 0 <= slot < 3:
                continue
            key = record.period_end.isoformat()
            bucket = month_bucket(slot, key)
            color = record.a3_color + record.a4_color
            bw = record.a3_bw + record.a4_bw
            for field in ("a4_color", "a4_bw", "a3_color", "a3_bw", "total"):
                bucket[field] += float(getattr(record, field))
            bucket["total_color"] += color
            bucket["total_bw"] += bw
            bucket["copy_color"] += record.copy_color
            bucket["copy_bw"] += record.copy_bw
            bucket["print_color"] += record.print_color
            bucket["print_bw"] += record.print_bw
            bucket["provisional_total"] += record.provisional_total
            bucket["provisional_print_color"] += record.provisional_print_color
            bucket["provisional_print_bw"] += record.provisional_print_bw
            bucket["provisional_copy_color"] += record.provisional_copy_color
            bucket["provisional_copy_bw"] += record.provisional_copy_bw
            bucket["provisional_days"] += record.provisional_days
            names_by_slot.setdefault(slot, set()).add(
                record.device_name_snapshot or f"เครื่อง {slot + 1}"
            )

        for record in subject_records:
            slot = int(record.device_slot)
            if not 0 <= slot < 3:
                continue
            key = record.period_end.isoformat()
            bucket = month_bucket(slot, key)
            user = bucket["users"].setdefault(
                record.subject_name,
                {"color": 0.0, "bw": 0.0, "total": 0.0},
            )
            user["total"] += float(record.period_usage)

        configured = {device.slot: device.name for device in self._historical_devices()}
        m_names: list[str] = []
        for slot in range(3):
            names = sorted(names_by_slot.get(slot, ()))
            if len(names) > 1:
                name = f"Slot {slot + 1} · หลายเครื่อง"
            elif names:
                name = names[0]
            else:
                name = configured.get(slot, f"เครื่อง {slot + 1}")
            m_names.append(name if len(name) <= 24 else f"{name[:21]}…")

        all_months_full = sorted(
            {key for monthly in slot_monthly for key in monthly}
        )
        self._available_months_for_filter = all_months_full
        if all_months_full:
            if (
                self._graph_date_from not in all_months_full
                or self._graph_date_to not in all_months_full
            ):
                self._graph_date_from = all_months_full[0]
                self._graph_date_to = all_months_full[-1]
            if self._graph_date_from > self._graph_date_to:
                self._graph_date_from, self._graph_date_to = (
                    self._graph_date_to,
                    self._graph_date_from,
                )
        all_months = [
            key
            for key in all_months_full
            if self._graph_date_from <= key <= self._graph_date_to
        ]
        x_labels = [
            f"{date.fromisoformat(key):%m/%Y}" for key in all_months
        ]
        if hasattr(self, "btn_save_png"):
            self.btn_save_png.setEnabled(bool(all_months))
        return {
            "slot_monthly": slot_monthly,
            "m_names": m_names,
            "all_months": all_months,
            "x_labels": x_labels,
            "view_mode": self._graph_view_mode,
        }

    def _populate_date_filter_dropdowns(self) -> None:
        items = [
            (key, f"สิ้นรอบ {date.fromisoformat(key):%d/%m/%Y}")
            for key in self._available_months_for_filter
        ]
        self.cmb_date_from.blockSignals(True)
        self.cmb_date_to.blockSignals(True)
        self.cmb_date_from.clear()
        self.cmb_date_to.clear()
        for key, label in items:
            self.cmb_date_from.addItem(label, key)
            self.cmb_date_to.addItem(label, key)
        from_index = self.cmb_date_from.findData(self._graph_date_from)
        to_index = self.cmb_date_to.findData(self._graph_date_to)
        self.cmb_date_from.setCurrentIndex(max(0, from_index))
        self.cmb_date_to.setCurrentIndex(max(0, to_index))
        self.cmb_date_from.blockSignals(False)
        self.cmb_date_to.blockSignals(False)

    def _on_date_reset_all(self) -> None:
        """Show confirmed billing periods whose end date is in the current year."""
        if not self._available_months_for_filter:
            return
        current_year = date.today().year
        periods_this_year = [
            key
            for key in self._available_months_for_filter
            if date.fromisoformat(key).year == current_year
        ]
        selected = periods_this_year or self._available_months_for_filter
        self._graph_date_from = selected[0]
        self._graph_date_to = selected[-1]
        from_index = self.cmb_date_from.findData(self._graph_date_from)
        to_index = self.cmb_date_to.findData(self._graph_date_to)
        self.cmb_date_from.blockSignals(True)
        self.cmb_date_to.blockSignals(True)
        self.cmb_date_from.setCurrentIndex(max(0, from_index))
        self.cmb_date_to.setCurrentIndex(max(0, to_index))
        self.cmb_date_from.blockSignals(False)
        self.cmb_date_to.blockSignals(False)
        self._refresh_graph()
