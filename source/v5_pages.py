from __future__ import annotations

import csv
import ipaddress
import json
import re
import socket
import traceback
import webbrowser
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path
from threading import Event
from time import perf_counter
from uuid import uuid4

from PyQt6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PyQt6.QtCore import QDate, QObject, QRectF, Qt, QThread, QTime, QTimer, QVariantAnimation, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import pages as legacy_pages
from config import (
    C_BORDER,
    C_EMPTY_BG,
    C_GREEN,
    C_MUTED_TEXT,
    C_RED,
    C_SECTION_TEXT,
    C_TABLE_ALT,
    C_TEXT2,
    C_TONER_BORDER,
    C_TONER_TRACK,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_BILLING_DAY,
    DEFAULT_WASTE_PCT,
    F_2XL,
    F_LG,
    F_MD,
    F_SM,
    F_XL,
    PACKAGE_VERSION,
    SLOT_COLORS,
)
from database import (
    _open,
    copy_database_for_first_run,
    get_billing_day,
    get_cfg,
    get_db_path,
    init_db,
    set_cfg,
    set_db_path,
)
from i18n import ENGLISH, THAI, apply_language, get_language, set_language, tr, translate_text
from komi_snmp_profiler.connectors import (
    AuthenticatedWebConnectionCounterConnector,
    TlsPolicy,
    WebConnectionCertificateError,
    WebConnectionCounterConnector,
    server_certificate_fingerprint,
)
from komi_snmp_profiler.credential_store import AdminCredential, SessionCredentialStore
from komi_snmp_profiler.device_profiles import resolve_device_meter_profile
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.models import WebAuthState
from pages import PageHistory
from runtime_config import RUNTIME_SETTINGS, save_runtime_database_path
from services.autostart import configure_autostart
from services.billing_ledger import (
    AuditRow,
    audit_coverage,
    count_audit_rows,
    get_audit_row,
    list_audit_rows,
)
from services.billing_v5 import period_gross_cost, period_net_cost
from services.daily_cache import DailyCacheStore
from services.desktop_shortcuts import create_desktop_shortcuts
from services.device_config import DatabaseCredentialStore, DeviceConfig, DeviceConfigRepository
from services.legacy_history_import import (
    LegacyHistoryImportError,
    LegacyHistoryImportResult,
    LegacyHistoryPreview,
    detect_legacy_history_sources,
    import_legacy_history,
    load_imported_legacy_history,
    preview_legacy_history,
)
from services.monthly_history import (
    HistoryGranularity,
    MonthlyUsage,
    history_period_range,
    load_monthly_usage,
    load_usage_history,
)
from services.pipeline_log import PipelineEvent, pipeline_log
from services.polling import PollingPolicy, ScheduleWindow
from services.pricing import PriceList, PricingRepository
from services.reconciliation import ReconciliationReport, reconcile_web_counters
from services.registration_data_notice import DRAFT_NOTICE_VERSION, registration_data_notice
from services.registration_envelope import (
    normalize_device_models,
    runtime_platform,
)
from services.v5_2_runtime_state import V52RuntimeStateRepository
from services.report_scope import report_slots
from services.runtime_snapshots import RuntimeCounterRow, runtime_snapshots
from services.snmp_probe import PaperTrayStatus, SnmpTotalProbe
from services.subject_history import SubjectDailyCacheStore, SubjectPeriodUsage, load_subject_history
from services.sync_schedule import (
    DailyTimelineEntry,
    build_daily_timeline,
    default_schedule_windows,
    dump_schedule_windows,
    load_schedule_windows,
    schedule_mode_at,
)
from services.usage import (
    DEFAULT_USAGE_LABELS,
    billing_period,
    current_device_identity,
    current_period_counters,
    current_period_counters_by_identity,
    default_usage_groups,
    latest_counters,
)
from services.web_access import (
    MIN_ACCESS_CODE_LENGTH,
    set_web_access_code,
    validate_web_access_code,
    web_access_status,
)
from services.web_service import WebServiceStatus, web_service_manager
from ui.cloud_reports import CloudReportsWidget
from ui.common_dialogs import AllCountersDialog, PinnedCountersDialog
from ui_consistency import install_button_system
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


class SetupDeviceStatusDelegate(QStyledItemDelegate):
    """Preserve the row's explicit status colour when Qt marks it selected."""

    def paint(self, painter, option, index) -> None:
        paint_option = QStyleOptionViewItem(option)
        paint_option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, paint_option, index)


class WizardComboBox(QComboBox):
    """Theme-stable combo box with a painted chevron on every platform."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#172033"), 2.0))
        center_y = self.height() / 2.0
        right = self.width() - 13.0
        path = QPainterPath()
        path.moveTo(right - 10.0, center_y - 2.5)
        path.lineTo(right - 5.0, center_y + 2.5)
        path.lineTo(right, center_y - 2.5)
        painter.drawPath(path)


class DeviceTestWorker(QObject):
    result = pyqtSignal(int, object)
    finished = pyqtSignal()

    def __init__(
        self,
        devices: list[DeviceConfig],
        *,
        snmp_port: int = 161,
        web_port: int = 443,
        endpoint_ports: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        super().__init__()
        self.devices = devices
        self.snmp_port = snmp_port
        self.web_port = web_port
        self.endpoint_ports = endpoint_ports or {}

    def _test(self, device: DeviceConfig) -> dict:
        snmp_port, web_port = self.endpoint_ports.get(
            device.host, (self.snmp_port, self.web_port)
        )
        probe_result = None
        reading = None
        errors: list[str] = []
        tls_mode = device.tls_mode
        tls_fingerprint = device.tls_fingerprint
        pipeline_log.append(
            stage="POLICY",
            action="Setup Test All",
            device_slot=device.slot,
            device_name=device.name,
            host=device.host,
            target="SNMP + Web Connection",
            value="concurrent test",
            status="request",
        )
        try:
            pipeline_log.append(
                stage="SNMP",
                action="Setup probe request",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="Printer-MIB Total / Model / Serial",
                status="request",
            )
            probe_result = SnmpTotalProbe(port=snmp_port).read(device.host)
            for oid, value in probe_result.oid_values:
                pipeline_log.append(
                    stage="SNMP",
                    action="Setup Total Meter response" if oid == probe_result.total_oid else "Setup OID response",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target=oid,
                    value=value,
                    status="ok",
                )
        except Exception as exc:
            errors.append(f"SNMP: {exc}")
            pipeline_log.append(
                stage="SNMP",
                action="Setup probe failed",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                value=exc,
                status="error",
            )
        try:
            web_host = device.host if web_port == 443 else f"{device.host}:{web_port}"
            store = SessionCredentialStore()
            if device.password:
                store.save(
                    web_host,
                    AdminCredential(username=device.username, password=device.password),
                )
            pipeline_log.append(
                stage="WEB",
                action="Setup Web read request",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=f"https://{web_host}/wcd",
                status="request",
            )
            if web_port != 443 and device.host in {"127.0.0.1", "localhost", "::1"}:
                tls_policy = TlsPolicy(mode="insecure")
            else:
                tls_policy = TlsPolicy(
                    mode=tls_mode,
                    fingerprint_sha256=tls_fingerprint,
                )
            meter_model = (probe_result.model if probe_result is not None else "") or device.model
            profile = resolve_device_meter_profile(meter_model)

            def read_with_policy(policy: TlsPolicy):
                reader = MeterReader(
                    store,
                    public_connector=WebConnectionCounterConnector(tls_policy=policy),
                    admin_connector=AuthenticatedWebConnectionCounterConnector(tls_policy=policy),
                )
                if profile.profile_id == "generic":
                    return reader.read(web_host)
                return reader.read(web_host, model=meter_model)

            try:
                reading = read_with_policy(tls_policy)
            except WebConnectionCertificateError:
                if tls_policy.mode != "system":
                    raise
                compatibility_policy = replace(
                    tls_policy,
                    compatibility=profile.tls_compatibility,
                )
                tls_fingerprint = (
                    server_certificate_fingerprint(web_host)
                    if profile.profile_id == "generic"
                    else server_certificate_fingerprint(
                        web_host,
                        tls_policy=compatibility_policy,
                    )
                )
                tls_mode = "fingerprint"
                reading = read_with_policy(
                    TlsPolicy(
                        mode="fingerprint",
                        fingerprint_sha256=tls_fingerprint,
                        compatibility=profile.tls_compatibility,
                    )
                )

            if device.password and reading.auth_state != WebAuthState.ADMIN:
                reading = None
                raise ValueError(
                    "Administrator password ไม่ผ่านการตรวจสอบ; กรุณาตรวจรหัสของเครื่องพิมพ์"
                )
            pipeline_log.append(
                stage="WEB",
                action="Setup Web read complete",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=reading.source,
                value=f"{len(reading.counters)} counters",
                detail=f"auth={reading.auth_state.value}",
                status="ok",
            )
        except Exception as exc:
            errors.append(f"Web: {exc}")
            pipeline_log.append(
                stage="WEB",
                action="Setup Web read failed",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                value=exc,
                status="error",
            )
        return {
            "online": probe_result is not None or reading is not None,
            "model": probe_result.model if probe_result else "",
            "serial": probe_result.serial if probe_result else "",
            "total": probe_result.total if probe_result else None,
            "web_ok": reading is not None,
            "error": "; ".join(errors),
            "tls_mode": tls_mode,
            "tls_fingerprint": tls_fingerprint,
            "web_auth_state": reading.auth_state.value if reading is not None else "",
        }

    @pyqtSlot()
    def run(self) -> None:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(self._test, device): device.slot for device in self.devices}
            for future, slot in [(future, slot) for future, slot in futures.items()]:
                try:
                    payload = future.result()
                except Exception as exc:
                    payload = {"online": False, "model": "", "serial": "", "total": None, "web_ok": False, "error": str(exc)}
                self.result.emit(slot, payload)
        self.finished.emit()


class NetworkDiscoveryWorker(QObject):
    """Find Konica Minolta devices on the active /24 without blocking the wizard."""

    result = pyqtSignal(object)
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, hosts: list[str] | None = None, *, snmp_port: int = 161) -> None:
        super().__init__()
        self.hosts = hosts
        self.snmp_port = snmp_port
        self._cancel_requested = Event()

    def cancel(self) -> None:
        """Cancel queued discovery immediately without waiting for SNMP timeout."""
        self._cancel_requested.set()

    def _is_cancelled(self) -> bool:
        return (
            self._cancel_requested.is_set()
            or QThread.currentThread().isInterruptionRequested()
        )

    @staticmethod
    def _local_network() -> ipaddress.IPv4Network:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.connect(("8.8.8.8", 80))
            address = client.getsockname()[0]
        return ipaddress.ip_network(f"{address}/24", strict=False)

    def _probe(self, host: str) -> dict | None:
        try:
            result = SnmpTotalProbe(timeout=0.6, retries=0, port=self.snmp_port).read(host)
        except Exception:
            return None
        model = result.model.strip()
        if not any(token in model.casefold() for token in ("konica", "minolta", "bizhub")):
            return None
        return {"host": host, "model": model, "serial": result.serial.strip(), "total": result.total}

    @pyqtSlot()
    def run(self) -> None:
        executor: ThreadPoolExecutor | None = None
        futures = []
        try:
            if self.hosts is None:
                network = self._local_network()
                hosts = [str(host) for host in network.hosts()]
                scope = network.with_prefixlen
            else:
                hosts = self.hosts
                scope = f"IP {hosts[0]} – {hosts[-1]}" if hosts else "ช่วง IP ว่าง"
            if not hosts:
                raise ValueError("ไม่พบ IP สำหรับสแกน")
            self.progress.emit(f"กำลังสแกน Konica Minolta ใน {scope}…")
            # Keep only a bounded batch in flight. Submitting an entire /24 at
            # once made cancellation race with ThreadPoolExecutor while it was
            # still creating workers, which could leave dozens of probes alive
            # after the Wizard had already reported cancellation.
            max_workers = 16
            executor = ThreadPoolExecutor(max_workers=max_workers)
            host_iter = iter(hosts)
            pending = set()

            def fill_queue() -> None:
                while len(pending) < max_workers and not self._is_cancelled():
                    try:
                        host = next(host_iter)
                    except StopIteration:
                        break
                    future = executor.submit(self._probe, host)
                    futures.append(future)
                    pending.add(future)

            fill_queue()
            while pending and not self._is_cancelled():
                done, pending = wait_futures(
                    pending,
                    timeout=0.05,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    if self._is_cancelled():
                        break
                    found = future.result()
                    if found:
                        self.result.emit(found)
                fill_queue()
            if self._is_cancelled():
                self.progress.emit("ยกเลิกการค้นหาแล้ว")
            else:
                self.progress.emit("สแกนเครือข่ายเสร็จแล้ว")
        except Exception as exc:
            if not self._is_cancelled():
                self.progress.emit(f"สแกนอัตโนมัติไม่ได้: {exc}")
        finally:
            if executor is not None:
                for future in futures:
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
            self.finished.emit()


class LegacyHistoryImportDialog(QDialog):
    """Preview and import only V4.6 aggregate usage history."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.preview: LegacyHistoryPreview | None = None
        self.import_result: LegacyHistoryImportResult | None = None
        self.setWindowTitle(tr("นำเข้าประวัติการใช้งาน V4.6", "Import V4.6 usage history"))
        self.resize(860, 620)
        self.setMinimumSize(720, 520)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel(tr("นำเข้าประวัติการใช้งาน V4.6", "Import V4.6 usage history"))
        title.setFont(fnt(F_2XL, True))
        root.addWidget(title)
        intro = QLabel(
            tr(
                "เลือกสำเนา Database จาก KOMI Report V4.6 ระบบจะตรวจสอบและแสดง Preview ก่อนนำเข้า",
                "Choose a copy of a KOMI Report V4.6 database. It will be checked and previewed before import.",
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{C_TEXT2};")
        root.addWidget(intro)

        boundary = QLabel(
            tr(
                "ประวัติต่อด้วย Slot เดิม · Serial ใช้เป็นหลักฐานการเปลี่ยนเครื่อง ไม่ใช้แบ่งประวัติ "
                "· ไม่แตะ IP, Username/Password, ราคา, Settings หรือ Billing Ledger",
                "History continues by logical Slot · Serial marks printer replacement and never splits the Slot "
                "· IP, credentials, prices, settings and Billing Ledger are not imported",
            )
        )
        boundary.setWordWrap(True)
        boundary.setStyleSheet(
            "background:#FFF7E6;color:#7A4B00;border:1px solid #F2D28B;"
            "border-radius:6px;padding:10px 12px;font-weight:700;"
        )
        root.addWidget(boundary)

        source_row = QHBoxLayout()
        self.source_path = QLineEdit()
        self.source_path.setReadOnly(True)
        self.source_path.setPlaceholderText(
            tr("ยังไม่ได้เลือก Database V4.6", "No V4.6 database selected")
        )
        self.source_path.setMinimumHeight(42)
        source_row.addWidget(self.source_path, 1)
        self.choose_button = btn(tr("เลือก Database…", "Choose database…"), "outline")
        self.choose_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.choose_button)
        root.addLayout(source_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        self.preview_summary = QLabel(
            tr(
                "เลือก Database เพื่อดูจำนวนรายการ ช่วงวันที่ และข้อมูลซ้ำ",
                "Choose a database to preview rows, date range and duplicates.",
            )
        )
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setMinimumHeight(92)
        self.preview_summary.setStyleSheet(
            "background:#F8FAFC;color:#173A63;border:1px solid #D7E1EA;"
            "border-radius:7px;padding:14px;"
        )
        content_layout.addWidget(self.preview_summary)

        self.device_table = QTableWidget(0, 5)
        self.device_table.setObjectName("legacy_history_device_table")
        self.device_table.setHorizontalHeaderLabels(
            (
                "Slot",
                tr("จุดติดตั้งใน V5", "V5 installation point"),
                tr("ชื่อเครื่องเดิม", "Previous printer name"),
                "Serial Number",
                tr("จำนวนรายการ", "Rows"),
            )
        )
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.verticalHeader().setDefaultSectionSize(38)
        self.device_table.setMinimumHeight(150)
        device_header = self.device_table.horizontalHeader()
        device_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        device_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        device_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        device_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        device_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        content_layout.addWidget(self.device_table)

        self.preview_note = QLabel(
            tr(
                "ไฟล์ต้นฉบับจะเปิดแบบ Read-only และ V5 จะสร้าง Backup ก่อนเขียนข้อมูล",
                "The source stays read-only and V5 creates a backup before writing.",
            )
        )
        self.preview_note.setWordWrap(True)
        self.preview_note.setStyleSheet(f"color:{C_TEXT2};")
        content_layout.addWidget(self.preview_note)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel(tr("พร้อมเลือกไฟล์", "Ready to choose a file"))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{C_TEXT2};")
        footer.addWidget(self.status_label, 1)
        self.close_button = btn(tr("ยกเลิก", "Cancel"), "outline")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        self.import_button = btn(tr("นำเข้าประวัติ", "Import history"), "primary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._run_import)
        footer.addWidget(self.import_button)
        root.addLayout(footer)

    def _set_status(self, text: str, *, state: str = "normal") -> None:
        colours = {
            "normal": C_TEXT2,
            "working": "#1769AA",
            "success": C_GREEN,
            "error": C_RED,
        }
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{colours[state]};font-weight:700;")

    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("เลือกสำเนา Database V4.6", "Choose a copy of the V4.6 database"),
            "",
            "SQLite Database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if path:
            self.load_source(path)

    def load_source(self, path: str) -> LegacyHistoryPreview | None:
        """Load a preview; public for focused UI checks."""

        self.preview = None
        self.import_result = None
        self.source_path.setText(path)
        self.import_button.setEnabled(False)
        self._set_status(tr("กำลังตรวจสอบ Database…", "Checking database…"), state="working")
        QApplication.processEvents()
        try:
            preview = preview_legacy_history(path)
        except LegacyHistoryImportError as err:
            self.device_table.setRowCount(0)
            self.preview_summary.setText(str(err))
            self._set_status(tr("ตรวจสอบไม่ผ่าน", "Validation failed"), state="error")
            return None
        self.preview = preview
        self._render_preview(preview)
        self.import_button.setEnabled(preview.new_rows > 0)
        if preview.new_rows:
            self.import_button.setText(
                tr(
                    f"สำรองและนำเข้า {preview.new_rows:,} รายการ",
                    f"Back up and import {preview.new_rows:,} rows",
                )
            )
            self._set_status(tr("ตรวจสอบผ่าน พร้อมนำเข้า", "Validated and ready"), state="success")
        else:
            self.import_button.setText(tr("ไม่มีข้อมูลใหม่", "No new history"))
            self._set_status(
                tr("ข้อมูลทั้งหมดเคยนำเข้าแล้ว", "All history has already been imported"),
                state="normal",
            )
        return preview

    def _render_preview(self, preview: LegacyHistoryPreview) -> None:
        date_range = (
            f"{preview.date_min} – {preview.date_max}"
            if preview.date_min and preview.date_max
            else tr("ไม่พบวันที่ที่อ่านได้", "No readable dates")
        )
        self.preview_summary.setText(
            tr(
                f"ช่วงข้อมูล: {date_range}\n"
                f"พบทั้งหมด {preview.total_rows:,} · นำเข้าใหม่ {preview.new_rows:,} · "
                f"ข้อมูลซ้ำ {preview.duplicate_rows:,} · อ่านไม่ได้ {preview.rejected_rows:,}",
                f"Date range: {date_range}\n"
                f"Total {preview.total_rows:,} · New {preview.new_rows:,} · "
                f"Duplicates {preview.duplicate_rows:,} · Rejected {preview.rejected_rows:,}",
            )
        )
        configured = {device.slot: device.name for device in DeviceConfigRepository().list()}
        self.device_table.setRowCount(len(preview.devices))
        for row, device in enumerate(preview.devices):
            values = (
                f"Slot {device.slot + 1}",
                configured.get(device.slot, tr("กำหนดใน Setup Wizard", "Set in Setup Wizard")),
                device.machine_name or "—",
                device.serial or "—",
                f"{device.reading_count:,}",
            )
            for column, value in enumerate(values):
                self.device_table.setItem(row, column, QTableWidgetItem(value))

    def _run_import(self) -> None:
        if self.preview is None:
            return
        self.choose_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self._set_status(tr("กำลังสำรองและนำเข้า…", "Backing up and importing…"), state="working")
        QApplication.processEvents()
        try:
            result = import_legacy_history(self.preview)
        except LegacyHistoryImportError as err:
            self.choose_button.setEnabled(True)
            self.import_button.setEnabled(True)
            self._set_status(str(err), state="error")
            return
        self.import_result = result
        self.import_button.setText(tr("นำเข้าสำเร็จ", "Import complete"))
        self.close_button.setText(tr("ปิด", "Close"))
        self.preview_note.setText(
            tr(
                f"Backup: {result.backup_path.name}",
                f"Backup: {result.backup_path.name}",
            )
        )
        self._set_status(
            tr(
                f"นำเข้าประวัติสำเร็จ {result.imported_rows:,} รายการ",
                f"Imported {result.imported_rows:,} history rows",
            ),
            state="success",
        )


class SetupWizardV5(QDialog):
    ADVANCED_SCAN_EXAMPLES = ("เช่น 192.168.1.1", "เช่น 192.168.1.255")

    _LIGHT_STYLE = """
        QDialog#setup_wizard_v5 {
            background: #F4F7FA;
            color: #172033;
        }
        QDialog#setup_wizard_v5 QLabel {
            color: #172033;
            background: transparent;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch {
            background: #FFFFFF;
            border: 1px solid #B8C8D8;
            border-radius: 9px;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton {
            min-width: 42px;
            min-height: 30px;
            background: transparent;
            color: #52677D;
            border: 0;
            border-radius: 7px;
            padding: 1px 8px;
            font-weight: 700;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton:hover {
            background: #EEF6FC;
            color: #174F78;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton:checked {
            background: #DCEEFF;
            color: #075B98;
        }
        QDialog#setup_wizard_v5 QFrame#wizard_language_switch QPushButton:focus {
            border: 1px solid #0879C9;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary {
            background: #0879C9;
            color: #FFFFFF;
            border: 1px solid #0879C9;
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 700;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary:hover {
            background: #066BAF;
            border-color: #066BAF;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary:pressed {
            background: #075384;
            border-color: #075384;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_primary:disabled {
            background: #E5ECF2;
            color: #52677D;
            border-color: #C2CFDB;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_outline {
            background: #FFFFFF;
            color: #24506E;
            border: 1px solid #B8C8D8;
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 600;
        }
        QDialog#setup_wizard_v5 QPushButton#btn_outline:hover {
            background: #EAF3FA;
            color: #123262;
            border-color: #93B9D6;
        }
    """

    _MODAL_LIGHT_STYLE = """
        QDialog#wizard_modal {
            background: #F4F7FA;
            color: #172033;
        }
        QDialog#wizard_modal QLabel {
            color: #334155;
            background: transparent;
        }
        QDialog#wizard_modal QLineEdit,
        QDialog#wizard_modal QComboBox {
            min-height: 34px;
            background: #FFFFFF;
            color: #172033;
            border: 1px solid #B8C8D8;
            border-radius: 7px;
            padding: 4px 9px;
            selection-background-color: #DCEEFF;
            selection-color: #102A43;
        }
        QDialog#wizard_modal QLineEdit:focus,
        QDialog#wizard_modal QComboBox:focus {
            border: 2px solid #0879C9;
        }
        QDialog#wizard_modal QComboBox::drop-down {
            width: 34px;
            border-left: 1px solid #D6E0EA;
        }
        QDialog#wizard_modal QComboBox QAbstractItemView {
            background: #FFFFFF;
            color: #172033;
            border: 1px solid #B8C8D8;
            selection-background-color: #DCEEFF;
            selection-color: #102A43;
            outline: 0;
            padding: 4px;
        }
    """

    def __init__(
        self,
        parent=None,
        *,
        edit_mode: bool = False,
        lab_mode: bool = False,
        lab_hosts: list[str] | None = None,
        lab_snmp_port: int = 161,
        lab_web_port: int = 443,
        legacy_source_paths: list[str] | None = None,
        runtime_config_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._apply_light_appearance()
        install_button_system(QApplication.instance())
        set_language(get_cfg("ui_language", THAI))
        self.repository = DeviceConfigRepository()
        self.registration_state = V52RuntimeStateRepository()
        self.pricing = PricingRepository()
        self.edit_mode = edit_mode
        self.lab_mode = lab_mode
        self.lab_hosts = lab_hosts
        self.lab_snmp_port = lab_snmp_port
        self.lab_web_port = lab_web_port
        self.runtime_config_path = Path(runtime_config_path or RUNTIME_SETTINGS.config_path)
        self.selected_database_path = Path(get_db_path()).expanduser().resolve(strict=False)
        self.legacy_source_paths = detect_legacy_history_sources(
            legacy_source_paths or (),
            include_known_locations=legacy_source_paths is None,
        )
        self.has_legacy_history = bool(
            self.legacy_source_paths or load_imported_legacy_history()
        )
        self.results: dict[int, dict] = {}
        # QDialog.open() is asynchronous; retain every child dialog for the
        # Wizard lifetime as required by Qt and to keep macOS Accessibility
        # from querying a wrapper that Python has already released.
        self._wizard_child_dialogs: list[QDialog] = []
        self._thread: QThread | None = None
        self._scan_thread: QThread | None = None
        self._worker: DeviceTestWorker | None = None
        self._scan_worker: NetworkDiscoveryWorker | None = None
        self.setWindowTitle(f"ตั้งค่า KOMI Report V{PACKAGE_VERSION}")
        self.setMinimumSize(800, 520)
        self._build()
        self._load_existing()
        apply_language(self)
        self._sync_language_switch()
        self._fit_to_available_screen()

    def _fit_to_available_screen(self) -> None:
        """Keep the Wizard a normal centered window on common office displays."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(1120, 720)
            return
        available = screen.availableGeometry()
        width = min(1120, max(self.minimumWidth(), int(available.width() * 0.90)))
        height = min(720, max(self.minimumHeight(), int(available.height() * 0.90)))
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _apply_light_appearance(self) -> None:
        """Keep onboarding readable and identical when the OS uses Dark Mode."""
        self.setObjectName("setup_wizard_v5")
        palette = QPalette(self.palette())
        light_roles = {
            QPalette.ColorRole.Window: "#F4F7FA",
            QPalette.ColorRole.WindowText: "#172033",
            QPalette.ColorRole.Base: "#FFFFFF",
            QPalette.ColorRole.AlternateBase: "#F7FAFD",
            QPalette.ColorRole.Text: "#172033",
            QPalette.ColorRole.Button: "#FFFFFF",
            QPalette.ColorRole.ButtonText: "#172033",
            QPalette.ColorRole.Highlight: "#DCEEFF",
            QPalette.ColorRole.HighlightedText: "#102A43",
            QPalette.ColorRole.PlaceholderText: "#52677D",
            QPalette.ColorRole.ToolTipBase: "#173A63",
            QPalette.ColorRole.ToolTipText: "#FFFFFF",
        }
        for role, colour in light_roles.items():
            palette.setColor(role, QColor(colour))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#64748B"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#64748B"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setStyleSheet(self._LIGHT_STYLE)

    def _prepare_wizard_dialog(self, dialog: QDialog) -> None:
        """Keep every Wizard-owned modal readable when macOS uses Dark Mode."""
        dialog.setObjectName("wizard_modal")
        dialog.setPalette(self.palette())
        dialog.setAutoFillBackground(True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dialog.setStyleSheet(self._MODAL_LIGHT_STYLE)
        apply_language(dialog)
        if get_language() == ENGLISH:
            for field in dialog.findChildren(QLineEdit):
                field.setPlaceholderText(translate_text(field.placeholderText()))

    def _style_wizard_combo(self, combo: QComboBox, *, popup_width: int | None = None) -> None:
        """Give non-editable choices the same light treatment on Mac and Windows."""
        combo.setMinimumHeight(40)
        combo.setStyleSheet(
            "QComboBox{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;"
            "border-radius:7px;padding:5px 40px 5px 10px;font-weight:700;}"
            "QComboBox:focus{border:2px solid #0879C9;}"
            "QComboBox::drop-down{width:34px;border-left:1px solid #D6E0EA;}"
            "QComboBox::down-arrow{image:none;width:0;height:0;}"
            "QComboBox QAbstractItemView{background:#FFFFFF;color:#172033;"
            "border:1px solid #B8C8D8;selection-background-color:#DCEEFF;"
            "selection-color:#102A43;outline:0;padding:4px;}"
        )
        view = combo.view()
        view.setPalette(self.palette())
        view.setStyleSheet(
            "QAbstractItemView{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;"
            "selection-background-color:#DCEEFF;selection-color:#102A43;outline:0;padding:4px;}"
        )
        if popup_width is not None:
            view.setMinimumWidth(popup_width)

    def _style_price_calendar(self, calendar: QCalendarWidget) -> None:
        """Prevent the native dark calendar popup from escaping the Wizard theme."""
        calendar.setPalette(self.palette())
        calendar.setGridVisible(False)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        calendar.setStyleSheet(
            "QCalendarWidget{background:#FFFFFF;color:#172033;}"
            "QCalendarWidget QWidget#qt_calendar_navigationbar{background:#173A63;}"
            "QCalendarWidget QToolButton{background:transparent;color:#FFFFFF;border:none;"
            "border-radius:4px;padding:5px 8px;font-weight:700;}"
            "QCalendarWidget QToolButton:hover{background:#245783;}"
            "QCalendarWidget QSpinBox{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;"
            "border-radius:4px;padding:3px;}"
            "QCalendarWidget QMenu{background:#FFFFFF;color:#172033;border:1px solid #B8C8D8;}"
            "QCalendarWidget QAbstractItemView:enabled{background:#FFFFFF;color:#172033;"
            "selection-background-color:#0879C9;selection-color:#FFFFFF;outline:0;}"
            "QCalendarWidget QAbstractItemView:disabled{color:#94A3B8;}"
        )

    def _open_wizard_child(
        self,
        dialog: QDialog,
        on_finished: Callable[[int], None] | None = None,
    ) -> QDialog:
        """Open a retained modal child without spinning a nested event loop."""
        if dialog.objectName() != "wizard_modal":
            self._prepare_wizard_dialog(dialog)
        self._wizard_child_dialogs.append(dialog)
        if on_finished is not None:
            dialog.finished.connect(on_finished)
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _build_wizard_message(
        self,
        title: str,
        message: str,
        *,
        icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_MessageBoxWarning,
    ) -> QDialog:
        """Build a stable cross-platform alert instead of a native QMessageBox.

        macOS can recalculate a native QMessageBox after the application-wide
        button styling is applied, which leaves the action outside the visible
        dialog.  This Qt-owned layout keeps the copy and action inside a known
        responsive width on macOS, Windows and Linux.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setMinimumWidth(500)
        dialog.setMaximumWidth(680)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(20)
        content = QHBoxLayout()
        content.setSpacing(18)
        content.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_label = QLabel()
        icon_label.setObjectName("wizard_alert_icon")
        icon_label.setFixedSize(52, 52)
        icon_label.setPixmap(self.style().standardIcon(icon).pixmap(48, 48))
        icon_label.setAccessibleName(
            tr("คำเตือน", "Warning")
            if icon == QStyle.StandardPixmap.SP_MessageBoxWarning
            else tr("ข้อมูล", "Information")
        )
        content.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("wizard_alert_title")
        heading.setFont(fnt(F_LG, True))
        heading.setWordWrap(True)
        message_label = QLabel(message)
        message_label.setObjectName("wizard_alert_message")
        message_label.setFont(fnt(F_MD))
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message_label.setMinimumWidth(350)
        message_label.setMaximumWidth(500)
        copy.addWidget(heading)
        copy.addWidget(message_label)
        content.addLayout(copy, 1)
        root.addLayout(content)

        actions = QHBoxLayout()
        actions.addStretch()
        confirm = btn(tr("ตกลง", "OK"), "primary")
        confirm.setAccessibleName(tr("ปิดข้อความ", "Close message"))
        confirm.setMinimumWidth(104)
        confirm.clicked.connect(dialog.accept)
        actions.addWidget(confirm)
        root.addLayout(actions)

        self._prepare_wizard_dialog(dialog)
        dialog.adjustSize()
        dialog.resize(max(500, dialog.sizeHint().width()), dialog.sizeHint().height())
        return dialog

    def _show_wizard_message(
        self,
        title: str,
        message: str,
        *,
        icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_MessageBoxWarning,
    ) -> None:
        self._open_wizard_child(
            self._build_wizard_message(title, message, icon=icon)
        )

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        header = QHBoxLayout()
        header.setSpacing(16)
        self.title = QLabel("ข้อมูลองค์กร")
        self.title.setFont(fnt(F_2XL, True))
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self.title, 1)
        self.header_controls = QWidget()
        self.header_controls.setObjectName("wizard_header_controls")
        header_tools = QHBoxLayout(self.header_controls)
        header_tools.setContentsMargins(0, 0, 0, 0)
        header_tools.setSpacing(10)
        self.language_switch = QFrame()
        self.language_switch.setObjectName("wizard_language_switch")
        self.language_switch.setAccessibleName("ภาษา / Language")
        language_layout = QHBoxLayout(self.language_switch)
        language_layout.setContentsMargins(2, 2, 2, 2)
        language_layout.setSpacing(0)
        self.language_button_group = QButtonGroup(self)
        self.language_button_group.setExclusive(True)
        self.thai_language_button = QPushButton("ไทย")
        self.thai_language_button.setCheckable(True)
        self.thai_language_button.setAccessibleName("ใช้ภาษาไทย")
        self.english_language_button = QPushButton("EN")
        self.english_language_button.setCheckable(True)
        self.english_language_button.setAccessibleName("Use English")
        self.language_button_group.addButton(self.thai_language_button)
        self.language_button_group.addButton(self.english_language_button)
        self.thai_language_button.clicked.connect(
            lambda: self._set_wizard_language(THAI)
        )
        self.english_language_button.clicked.connect(
            lambda: self._set_wizard_language(ENGLISH)
        )
        language_layout.addWidget(self.thai_language_button)
        language_layout.addWidget(self.english_language_button)
        header_tools.addWidget(self.language_switch)
        self.step_label = QLabel("1 / 4")
        self.step_label.setStyleSheet("color:#1769AA;font-weight:700;")
        self.step_label.setAccessibleName("ความคืบหน้าการตั้งค่า")
        header_tools.addWidget(self.step_label)
        self.header_controls.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header.addWidget(self.header_controls, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.progress_labels: list[QLabel] = []
        for step_name in ("องค์กร", "เครื่องพิมพ์", "ราคา", "ตรวจสอบ"):
            label = QLabel(step_name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(30)
            self.progress_labels.append(label)
            progress.addWidget(label, 1)
        root.addLayout(progress)
        self._update_progress(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._company_page())
        self.stack.addWidget(self._device_page())
        self.stack.addWidget(self._price_page())
        self.stack.addWidget(self._review_page())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.note = QLabel("ขั้นที่ 1: กรอกชื่อบริษัท · วันที่เริ่มใช้และ Version มาจากระบบอัตโนมัติ")
        self.note.setStyleSheet(f"color:{C_TEXT2};")
        nav.addWidget(self.note)
        nav.addStretch()
        self.back_button = btn("← ย้อนกลับ", "outline")
        self.back_button.setVisible(False)
        self.back_button.clicked.connect(self._back)
        nav.addWidget(self.back_button)
        nav.addWidget(self.test_button)
        self.test_button.setVisible(False)
        self.next_button = btn("ค้นหาเครื่องพิมพ์ →", "primary")
        self.next_button.clicked.connect(self._next)
        nav.addWidget(self.next_button)
        root.addLayout(nav)

    def _company_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.company_scroll = QScrollArea()
        self.company_scroll.setWidgetResizable(True)
        self.company_scroll.setMinimumSize(0, 0)
        self.company_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.company_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.company_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.company_scroll.setStyleSheet("QScrollArea{background:#F4F7FA;border:none;}")
        content = QWidget()
        content.setObjectName("company_setup_content")
        content.setStyleSheet("QWidget#company_setup_content{background:#F4F7FA;}")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(14)

        intro = QLabel("ข้อมูลสำหรับเริ่มใช้งาน")
        intro.setFont(fnt(F_XL, True))
        intro.setStyleSheet("color:#123262;")
        layout.addWidget(intro)
        description = QLabel(
            "ระบุชื่อบริษัทสำหรับแสดงในรายงานและการลงทะเบียนโปรแกรม "
            "ส่วนวันที่เริ่มใช้และ Version ระบบกำหนดให้เพื่อป้องกันข้อมูลผิด"
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(description)

        self.company_card = QFrame()
        self.company_card.setObjectName("company_setup_card")
        self.company_card.setFixedWidth(760)
        self.company_card.setStyleSheet(
            "QFrame#company_setup_card{background:#FFFFFF;border:1px solid #C9D9E8;"
            "border-radius:8px;}"
        )
        self.company_form = QFormLayout(self.company_card)
        self.company_form.setContentsMargins(24, 22, 24, 22)
        self.company_form.setHorizontalSpacing(18)
        self.company_form.setVerticalSpacing(14)
        self.company_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.company_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.company_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.company_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.company_name_input = QLineEdit()
        self.company_name_input.setObjectName("company_name_input")
        self.company_name_input.setPlaceholderText("เช่น บริษัท ตัวอย่าง จำกัด")
        self.company_name_input.setMaxLength(160)
        self.company_name_input.setMinimumHeight(44)
        self.company_name_input.setMinimumWidth(470)
        self.company_name_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.company_name_input.setFont(fnt(F_LG))
        self._company_name_normal_style = (
            "QLineEdit{background:#FFFFFF;color:#172033;border:1px solid #B8C7D9;"
            "border-radius:6px;padding:8px 11px;}"
            "QLineEdit:focus{border:2px solid #1769AA;}"
        )
        self._company_name_error_style = (
            "QLineEdit{background:#FFF7F6;color:#172033;border:2px solid #B42318;"
            "border-radius:6px;padding:7px 10px;}"
            "QLineEdit:focus{border:2px solid #B42318;}"
        )
        self.company_name_input.setStyleSheet(self._company_name_normal_style)
        self.company_name_error = QLabel("กรุณากรอกชื่อบริษัท")
        self.company_name_error.setObjectName("company_name_error")
        self.company_name_error.setStyleSheet(
            "color:#B42318;background:transparent;border:none;font-weight:600;"
        )
        self.company_name_error.setWordWrap(True)
        self.company_name_error.setVisible(False)
        self.company_name_container = QWidget()
        company_name_layout = QVBoxLayout(self.company_name_container)
        company_name_layout.setContentsMargins(0, 0, 0, 0)
        company_name_layout.setSpacing(6)
        company_name_layout.addWidget(self.company_name_input)
        company_name_layout.addWidget(self.company_name_error)
        self.company_name_input.textChanged.connect(self._clear_company_name_error)
        self.first_started_input = QLineEdit()
        self.first_started_input.setReadOnly(True)
        self.first_started_input.setMinimumHeight(42)
        self.first_started_input.setMinimumWidth(470)
        self.first_started_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.version_input = QLineEdit(PACKAGE_VERSION)
        self.version_input.setReadOnly(True)
        self.version_input.setMinimumHeight(42)
        self.version_input.setMinimumWidth(470)
        self.version_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        readonly_style = (
            "QLineEdit{background:#F1F5F9;color:#475569;border:1px solid #D6E0EA;"
            "border-radius:6px;padding:8px 11px;font-weight:700;}"
        )
        self.first_started_input.setStyleSheet(readonly_style)
        self.version_input.setStyleSheet(readonly_style)

        self.database_path_container = QWidget()
        self.database_path_container.setMinimumHeight(94)
        self.database_path_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        database_layout = QVBoxLayout(self.database_path_container)
        database_layout.setContentsMargins(0, 0, 0, 0)
        database_layout.setSpacing(7)
        database_path_row = QHBoxLayout()
        database_path_row.setContentsMargins(0, 0, 0, 0)
        database_path_row.setSpacing(8)
        self.database_path_input = QLineEdit(str(self.selected_database_path))
        self.database_path_input.setReadOnly(True)
        self.database_path_input.setMinimumHeight(42)
        self.database_path_input.setMinimumWidth(320)
        self.database_path_input.setStyleSheet(readonly_style)
        self.database_path_input.setToolTip(str(self.selected_database_path))
        database_path_row.addWidget(self.database_path_input, 1)
        self.choose_database_path_button = btn("เลือกตำแหน่ง…", "outline")
        self.choose_database_path_button.clicked.connect(self._choose_database_destination)
        database_path_row.addWidget(self.choose_database_path_button)
        database_layout.addLayout(database_path_row)
        database_actions = QHBoxLayout()
        database_actions.setContentsMargins(0, 0, 0, 0)
        database_actions.setSpacing(9)
        self.legacy_import_button = btn("นำเข้าฐานข้อมูลเดิม…", "outline")
        self.legacy_import_button.clicked.connect(self._open_legacy_history_import)
        database_actions.addWidget(self.legacy_import_button)
        self.database_path_status = QLabel(
            "สร้าง Database ใหม่ที่ Path นี้ · การนำเข้า V4.6 จะนำเข้าเฉพาะ Meter/Usage History"
        )
        self.database_path_status.setWordWrap(True)
        self.database_path_status.setStyleSheet("color:#52677D;border:none;")
        database_actions.addWidget(self.database_path_status, 1)
        database_layout.addLayout(database_actions)

        self.company_form_labels = []
        for label_text, field in (
            ("ชื่อบริษัท *", self.company_name_container),
            ("วันที่เริ่มใช้งาน", self.first_started_input),
            ("Version ที่ใช้", self.version_input),
            ("Database Path", self.database_path_container),
        ):
            label = QLabel(label_text)
            label.setMinimumWidth(145)
            label.setFont(fnt(F_MD, True))
            label.setStyleSheet("color:#334155;background:transparent;border:none;")
            label.setBuddy(self.company_name_input if field is self.company_name_container else field)
            self.company_form_labels.append(label)
            self.company_form.addRow(label, field)
        self.company_name_input.setAccessibleName("ชื่อบริษัท")
        self.company_name_input.setAccessibleDescription("ใช้แสดงในรายงานและระบุการติดตั้งนี้")
        layout.addWidget(self.company_card, 0, Qt.AlignmentFlag.AlignHCenter)

        self.company_notice = QLabel(
            "<b>ขอบเขตข้อมูลที่ปลอดภัย:</b> Registration ส่ง Serial Number, Model และสถานะเลือกใช้ตาม "
            "ประกาศข้อมูลการลงทะเบียน; Online ส่งเฉพาะ Status และ Aggregate Total Meter · "
            "ไม่ส่ง IP, MAC, hostname, Credential, Counter รายละเอียด, ผู้ใช้, เอกสาร หรือ Log"
        )
        self.company_notice.setWordWrap(True)
        self.company_notice.setFixedWidth(760)
        self.company_notice.setStyleSheet(
            "background:#EEF6F9;color:#245268;border:1px solid #C7DFE8;"
            "border-radius:6px;padding:12px;"
        )
        layout.addWidget(self.company_notice, 0, Qt.AlignmentFlag.AlignHCenter)

        privacy_card = QFrame()
        privacy_card.setObjectName("registration_privacy_card")
        privacy_card.setFixedWidth(760)
        privacy_card.setStyleSheet(
            "QFrame#registration_privacy_card{background:#FFFFFF;border:1px solid #C9D9E8;"
            "border-radius:8px;} QLabel{border:none;background:transparent;}"
        )
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(14, 12, 14, 12)
        privacy_layout.setSpacing(8)
        privacy_row = QHBoxLayout()
        privacy_copy = QVBoxLayout()
        privacy_title = QLabel("ประกาศข้อมูลการลงทะเบียน")
        privacy_title.setFont(fnt(F_MD, True))
        self.privacy_notice_status = QLabel()
        self.privacy_notice_status.setWordWrap(True)
        privacy_copy.addWidget(privacy_title)
        privacy_copy.addWidget(self.privacy_notice_status)
        privacy_row.addLayout(privacy_copy, 1)
        self.view_privacy_notice_button = btn("ดูข้อมูลที่ส่ง", "outline")
        self.view_privacy_notice_button.setAccessibleName("เปิดดูประกาศข้อมูลการลงทะเบียน")
        self.view_privacy_notice_button.clicked.connect(self._show_privacy_notice)
        privacy_row.addWidget(self.view_privacy_notice_button)
        privacy_layout.addLayout(privacy_row)
        self.privacy_notice_accepted = QCheckBox("ฉันได้อ่านและรับทราบข้อมูลการลงทะเบียนฉบับนี้")
        self.privacy_notice_accepted.setAccessibleName("รับทราบประกาศข้อมูลการลงทะเบียน")
        self.privacy_notice_status.setText(
            tr(
                f"ฉบับ {DRAFT_NOTICE_VERSION} · ต้องรับทราบก่อนใช้ Online Registration",
                f"Version {DRAFT_NOTICE_VERSION} · acknowledgement is required for Online Registration",
            )
        )
        privacy_layout.addWidget(self.privacy_notice_accepted)
        layout.addWidget(privacy_card, 0, Qt.AlignmentFlag.AlignHCenter)

        mode_card = QFrame()
        mode_card.setObjectName("registration_mode_card")
        mode_card.setFixedWidth(760)
        mode_card.setStyleSheet(
            "QFrame#registration_mode_card{background:#FFFFFF;border:1px solid #C9D9E8;"
            "border-radius:8px;} QLabel,QRadioButton{border:none;background:transparent;}"
        )
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(14, 12, 14, 12)
        mode_layout.setSpacing(7)
        mode_title = QLabel(tr("โหมดการลงทะเบียน", "Registration mode"))
        mode_title.setFont(fnt(F_MD, True))
        mode_layout.addWidget(mode_title)
        self.registration_mode_group = QButtonGroup(self)
        self.registration_mode_group.setExclusive(True)
        self.registration_online_mode = QRadioButton(
            tr("ออนไลน์ · ลงทะเบียนอัตโนมัติ", "Online · automatic registration")
        )
        self.registration_online_mode.setAccessibleName(
            tr("เลือกรับบริการแบบออนไลน์", "Use Online Registration")
        )
        self.registration_offline_mode = QRadioButton(
            tr("ออฟไลน์ · ใช้ไฟล์ License", "Offline · use a license file")
        )
        self.registration_offline_mode.setAccessibleName(
            tr("เลือกใช้งานแบบ Offline License", "Use an Offline License")
        )
        self.registration_mode_group.addButton(self.registration_online_mode)
        self.registration_mode_group.addButton(self.registration_offline_mode)
        selected_mode = get_cfg("v52_registration_mode", "online")
        self.registration_offline_mode.setChecked(selected_mode == "offline")
        self.registration_online_mode.setChecked(selected_mode != "offline")
        mode_layout.addWidget(self.registration_online_mode)
        online_hint = QLabel(
            tr(
                "ออนไลน์จะส่งสถานะและ Total Meter รวมตามประกาศข้อมูล โดยไม่ให้กรอก API Key",
                "Online mode sends status and aggregate Total Meter under the Data Notice. No API key is required.",
            )
        )
        online_hint.setWordWrap(True)
        online_hint.setStyleSheet("color:#52677D;border:none;margin-left:22px;")
        mode_layout.addWidget(online_hint)
        mode_layout.addWidget(self.registration_offline_mode)
        offline_hint = QLabel(
            tr(
                "Offline License ไม่ส่ง Registration, Status หรือ Meter ไปยัง Host",
                "Offline License sends no Registration, Status, or Meter telemetry to the Host.",
            )
        )
        offline_hint.setWordWrap(True)
        offline_hint.setStyleSheet("color:#52677D;border:none;margin-left:22px;")
        mode_layout.addWidget(offline_hint)
        self.registration_online_mode.toggled.connect(self._registration_mode_changed)
        self.registration_offline_mode.toggled.connect(self._registration_mode_changed)
        self._registration_mode_changed()
        layout.addWidget(mode_card, 0, Qt.AlignmentFlag.AlignHCenter)
        if self.lab_mode:
            lab_notice = QLabel(
                "<b>SETUP LAB</b> · หน้านี้ใช้ Wizard ตัวจริง แต่ใช้ฐานข้อมูลชั่วคราวและ "
                "Virtual Printer บน LAN ข้อมูลจะไม่ปนกับโปรแกรมที่ใช้งานอยู่"
            )
            lab_notice.setWordWrap(True)
            lab_notice.setFixedWidth(760)
            lab_notice.setStyleSheet(
                "background:#FFF8E8;color:#75510A;border:1px solid #E8D7A4;"
                "border-radius:6px;padding:12px;"
            )
            layout.addWidget(lab_notice, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.company_scroll.setWidget(content)
        page_layout.addWidget(self.company_scroll)
        return page

    def _clear_company_name_error(self) -> None:
        if self.company_name_error.isHidden():
            return
        self.company_name_error.setVisible(False)
        self.company_name_input.setStyleSheet(self._company_name_normal_style)
        self.company_name_input.setAccessibleDescription(
            tr(
                "ใช้แสดงในรายงานและระบุการติดตั้งนี้",
                "Used in reports and to identify this installation",
            )
        )

    def _show_company_name_error(self) -> None:
        self.company_name_error.setText(
            tr("กรุณากรอกชื่อบริษัท", "Enter the company name to continue")
        )
        self.company_name_error.setVisible(True)
        self.company_name_input.setStyleSheet(self._company_name_error_style)
        self.company_name_input.setAccessibleDescription(self.company_name_error.text())
        self.company_name_input.setFocus()

    def _show_privacy_notice(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(
            tr("ประกาศข้อมูลการลงทะเบียน", "Registration Data Notice")
        )
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(registration_data_notice(get_language()))
        layout.addWidget(text)
        close_button = btn(tr("ปิด", "Close"), "primary")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self._open_wizard_child(dialog)

    def _registration_mode_changed(self, _checked: bool = False) -> None:
        online = self.registration_online_mode.isChecked()
        self.privacy_notice_accepted.setEnabled(online)
        if hasattr(self, "review_sections") and self._selected_entries():
            self._update_review()

    def _set_wizard_language(self, language: str) -> None:
        """Apply and persist a language selected on the first setup screen."""
        set_language(language)
        set_cfg("ui_language", language)
        apply_language(self)
        self._sync_language_switch()

    def _sync_language_switch(self) -> None:
        """Keep the compact language labels stable in either UI language."""
        is_english = get_language() == ENGLISH
        for button in (self.thai_language_button, self.english_language_button):
            button.blockSignals(True)
        self.thai_language_button.setText("ไทย")
        self.english_language_button.setText("EN")
        self.thai_language_button.setChecked(not is_english)
        self.english_language_button.setChecked(is_english)
        for button in (self.thai_language_button, self.english_language_button):
            button.blockSignals(False)

    def _choose_database_destination(self) -> None:
        start = str(self.selected_database_path)
        selected, _ = QFileDialog.getSaveFileName(
            self,
            tr("เลือก Path สำหรับสร้าง Database", "Choose where to create the database"),
            start,
            "SQLite Database (*.db *.sqlite *.sqlite3)",
        )
        if selected:
            self._set_database_destination(selected)

    def _set_database_destination(self, selected: str) -> bool:
        """Validate and stage a new database path without creating it yet."""
        candidate = Path(selected).expanduser()
        if not candidate.suffix:
            candidate = candidate.with_suffix(".db")
        candidate = candidate.resolve(strict=False)
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        if candidate.exists() and candidate != active:
            self._show_wizard_message(
                tr("Path นี้มีไฟล์อยู่แล้ว", "A file already exists at this path"),
                tr(
                    "กรุณาเลือกชื่อ Database ใหม่ หรือใช้ปุ่ม ‘นำเข้าฐานข้อมูลเดิม’",
                    "Choose a new database filename or use ‘Import existing database’.",
                ),
            )
            return False
        self.selected_database_path = candidate
        self.database_path_input.setText(str(candidate))
        self.database_path_input.setToolTip(str(candidate))
        if self.lab_mode:
            status = tr(
                "SETUP LAB · แสดง Path เพื่อทดสอบเท่านั้น และจะไม่สร้างไฟล์จริง",
                "SETUP LAB · the path is shown for testing and no database file will be created",
            )
        elif candidate == active:
            status = tr(
                "ใช้ Database Path ค่าเริ่มต้นนี้",
                "Using this default database path",
            )
        else:
            status = tr(
                "พร้อมสร้าง Database ใหม่เมื่อกดบันทึก · ยังไม่มีการเขียนไฟล์",
                "Ready to create the database when setup is saved · no file has been written yet",
            )
        self.database_path_status.setText(status)
        self.database_path_status.setStyleSheet("color:#52677D;border:none;")
        return True

    def _activate_selected_database_path(self) -> None:
        """Create, verify and activate the staged first-run database destination."""
        if self.lab_mode:
            return
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        target = self.selected_database_path.expanduser().resolve(strict=False)
        if target == active:
            return
        created = copy_database_for_first_run(target)
        try:
            save_runtime_database_path(created, config_path=self.runtime_config_path)
        except Exception:
            created.unlink(missing_ok=True)
            raise
        set_db_path(created)
        init_db()

    def _update_progress(self, active_step: int) -> None:
        for index, label in enumerate(self.progress_labels):
            if index < active_step:
                style = "background:#EDF8F2;color:#176B49;border-radius:5px;font-weight:700;"
            elif index == active_step:
                style = "background:#DCEEFF;color:#0B4F8A;border-radius:5px;font-weight:800;"
            else:
                style = "background:#E9EEF4;color:#64748B;border-radius:5px;font-weight:600;"
            label.setStyleSheet(style)

    def _device_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        intro = QLabel(
            "ระบบจะค้นหาเฉพาะเครือข่าย LAN ที่เครื่องนี้เชื่อมต่อ · "
            "เลือกเครื่องพิมพ์ได้สูงสุด 3 เครื่อง"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(intro)

        actions = QHBoxLayout()
        self.scan_button = btn("ค้นหาเครื่องพิมพ์อัตโนมัติ", "primary")
        self.scan_button.setAccessibleDescription("สแกน Konica Minolta ในเครือข่าย LAN ที่เชื่อมต่ออยู่")
        self.scan_button.clicked.connect(lambda: self._scan_network())
        actions.addWidget(self.scan_button)
        self.cancel_scan_button = btn("ยกเลิกการค้นหา", "outline")
        self.cancel_scan_button.clicked.connect(self._cancel_scan)
        self.cancel_scan_button.setVisible(False)
        actions.addWidget(self.cancel_scan_button)
        self.fallback_toggle = btn("ค้นหาไม่พบ? ใช้วิธีอื่น", "outline")
        self.fallback_toggle.setCheckable(True)
        self.fallback_toggle.toggled.connect(self._toggle_fallback_actions)
        actions.addWidget(self.fallback_toggle)
        actions.addStretch()
        self.selection_badge = QLabel("เลือกแล้ว 0/3")
        self.selection_badge.setStyleSheet("background:#EAF1FA;color:#1769AA;padding:7px 11px;font-weight:700;border-radius:5px;")
        self.selection_badge.setAccessibleName("จำนวนเครื่องพิมพ์ที่เลือก")
        actions.addWidget(self.selection_badge)
        layout.addLayout(actions)

        self.fallback_actions = QWidget()
        fallback_layout = QHBoxLayout(self.fallback_actions)
        fallback_layout.setContentsMargins(0, 0, 0, 0)
        fallback_layout.setSpacing(10)
        self.advanced_scan_button = btn("กำหนดช่วง IP", "outline")
        self.advanced_scan_button.clicked.connect(self._advanced_scan)
        fallback_layout.addWidget(self.advanced_scan_button)
        self.manual_setup_button = btn("เพิ่ม IP ด้วยตนเอง", "outline")
        self.manual_setup_button.clicked.connect(self._manual_setup)
        fallback_layout.addWidget(self.manual_setup_button)
        fallback_hint = QLabel("ใช้เมื่อเครื่องพิมพ์อยู่นอกช่วงเครือข่ายที่ค้นหาอัตโนมัติ")
        fallback_hint.setStyleSheet(f"color:{C_TEXT2};")
        fallback_layout.addWidget(fallback_hint)
        fallback_layout.addStretch()
        self.fallback_actions.setVisible(False)
        layout.addWidget(self.fallback_actions)

        self.scan_status = QLabel("พร้อมค้นหา · ระบบยังไม่ได้สแกนเครือข่าย")
        self.scan_status.setStyleSheet("background:#EEF6F9;color:#245268;padding:8px 10px;")
        self.scan_status.setAccessibleName("สถานะการค้นหาเครื่องพิมพ์")
        layout.addWidget(self.scan_status)

        self.device_table = QTableWidget(0, 6)
        self.device_table.setHorizontalHeaderLabels(
            ("เลือก", "ชื่อรุ่น", "IP address", "Serial Number", "สถานะ", "สิทธิ์เข้าถึง")
        )
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setAlternatingRowColors(False)
        self.device_table.setObjectName("setup_device_table")
        self.device_table.setWordWrap(False)
        table_palette = QPalette(self.palette())
        table_palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        table_palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F7FAFD"))
        table_palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
        table_palette.setColor(QPalette.ColorRole.Highlight, QColor("#DCEEFF"))
        table_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#172033"))
        self.device_table.setPalette(table_palette)
        self.device_table.viewport().setAutoFillBackground(True)
        self.device_table.setStyleSheet(
            "QTableWidget#setup_device_table{background:#FFFFFF;color:#172033;"
            "border:1px solid #C9D9E8;gridline-color:#D6E0EA;}"
            "QTableWidget#setup_device_table:focus{border:2px solid #1769AA;}"
            "QTableWidget#setup_device_table::item {padding:0 10px;}"
            "QTableWidget#setup_device_table QHeaderView::section{background:#EAF1F7;"
            "color:#173A63;border:none;border-right:1px solid #C9D9E8;"
            "border-bottom:1px solid #B8C8D8;padding:8px 10px;font-weight:700;}"
            "QTableWidget#setup_device_table QTableCornerButton::section{background:#EAF1F7;"
            "border:none;border-right:1px solid #C9D9E8;border-bottom:1px solid #B8C8D8;}"
        )
        self.device_table.setItemDelegate(SetupDeviceStatusDelegate(self.device_table))
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.verticalHeader().setDefaultSectionSize(46)
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.setAccessibleName("รายการเครื่องพิมพ์ที่ค้นพบ")
        self.device_table.cellClicked.connect(self._device_table_action)
        self.device_table.cellActivated.connect(self._device_table_action)
        layout.addWidget(self.device_table, 1)
        actions = QHBoxLayout()
        hint = QLabel("เลือกเครื่อง → ตรวจสอบ → สถานะพร้อมใช้งาน จึงกดถัดไปได้")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C_TEXT2};")
        actions.addWidget(hint)
        actions.addStretch()
        self.test_button = btn("ตรวจสอบเครื่องที่เลือก", "outline")
        self.test_button.setAccessibleDescription("ตรวจสอบ SNMP และ Web ของเครื่องพิมพ์ที่เลือก")
        self.test_button.clicked.connect(self._test_all)
        layout.addLayout(actions)
        self.discovered_devices: list[dict] = []
        return page

    def _toggle_fallback_actions(self, visible: bool) -> None:
        self.fallback_actions.setVisible(visible)
        self.fallback_toggle.setText("ซ่อนวิธีอื่น" if visible else "ค้นหาไม่พบ? ใช้วิธีอื่น")

    def _cancel_scan(self) -> None:
        if self._scan_thread is None:
            return
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        self._scan_thread.requestInterruption()
        self.scan_status.setText("กำลังยกเลิกการค้นหา…")
        self.cancel_scan_button.setEnabled(False)

    def _open_legacy_history_import(self) -> None:
        dialog = LegacyHistoryImportDialog(self)
        def import_finished(_result: int) -> None:
            if dialog.import_result is not None:
                imported = dialog.import_result.imported_rows
                self.database_path_status.setText(
                    tr(
                        f"นำเข้าประวัติ V4.6 แล้ว {imported:,} รายการ · ไม่เปลี่ยนการตั้งค่าเครื่อง",
                        f"Imported {imported:,} V4.6 history rows · printer settings unchanged",
                    )
                )
                self.database_path_status.setStyleSheet(
                    f"color:{C_GREEN};border:none;font-weight:700;"
                )

        self._open_wizard_child(dialog, import_finished)

    def _review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        title = QLabel("ตรวจสอบทีละส่วนก่อนบันทึก")
        title.setFont(fnt(F_XL, True))
        layout.addWidget(title)

        review_scroll = QScrollArea()
        review_scroll.setWidgetResizable(True)
        review_scroll.setFrameShape(QFrame.Shape.NoFrame)
        review_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        review_panel = QFrame()
        review_panel.setObjectName("setup_review_panel")
        review_panel.setStyleSheet(
            "QFrame#setup_review_panel{background:#FFFFFF;border:1px solid #CBD5E1;"
            "border-radius:8px;}"
        )
        panel_layout = QVBoxLayout(review_panel)
        panel_layout.setContentsMargins(18, 8, 18, 8)
        panel_layout.setSpacing(0)
        self.review_sections: dict[str, QLabel] = {}
        for key, section_title, target_step in (
            ("organization", "องค์กร", 0),
            ("devices", "เครื่องพิมพ์", 1),
            ("pricing", "ราคา", 2),
            ("billing", "รอบบิล", 2),
            ("registration", "ข้อมูลลงทะเบียน", None),
        ):
            section = QFrame()
            section.setStyleSheet(
                "QFrame{background:#FFFFFF;border:none;border-bottom:1px solid #E2E8F0;}"
            )
            section_layout = QHBoxLayout(section)
            section_layout.setContentsMargins(2, 7, 2, 7)
            copy = QVBoxLayout()
            copy.setSpacing(3)
            heading = QLabel(f"✓  {section_title}")
            heading.setFont(fnt(F_MD, True))
            heading.setStyleSheet("color:#176B49;border:none;")
            body = QLabel("")
            body.setWordWrap(True)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            body.setStyleSheet("color:#334155;border:none;")
            copy.addWidget(heading)
            copy.addWidget(body)
            section_layout.addLayout(copy, 1)
            if target_step is None:
                self.registration_status_label = QLabel("ยังไม่ส่ง")
                self.registration_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.registration_status_label.setFixedSize(86, 32)
                self.registration_status_label.setStyleSheet(
                    "background:#FFF8E8;color:#75510A;border:1px solid #E8D7A4;"
                    "border-radius:16px;font-weight:700;"
                )
                section_layout.addWidget(
                    self.registration_status_label, 0, Qt.AlignmentFlag.AlignTop
                )
            else:
                edit = btn("แก้ไข", "outline")
                edit.setFixedSize(78, 36)
                edit.setAccessibleName(f"แก้ไข{section_title}")
                edit.clicked.connect(
                    lambda _checked=False, step=target_step: self._go_to_step(step)
                )
                section_layout.addWidget(edit, 0, Qt.AlignmentFlag.AlignTop)
            panel_layout.addWidget(section)
            self.review_sections[key] = body
        review_scroll.setWidget(review_panel)
        layout.addWidget(review_scroll, 1)

        self.review_ready_note = QLabel(
            "<b>พร้อมนำเครื่องพิมพ์เข้าระบบ</b><br>"
            "เมื่อกดบันทึก ระบบจะเก็บการตั้งค่าในเครื่องและเริ่มตรวจมิเตอร์ตามรอบที่กำหนด"
        )
        self.review_ready_note.setWordWrap(True)
        self.review_ready_note.setFont(fnt(F_LG))
        self.review_ready_note.setStyleSheet(
            "background:#EDF8F2;color:#176B49;border:1px solid #B8DFC9;"
            "border-radius:6px;padding:12px;"
        )
        layout.addWidget(self.review_ready_note)
        return page

    def _go_to_step(self, target_step: int) -> None:
        while self.stack.currentIndex() > target_step:
            self._back()

    def _price_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 12, 0, 0)
        self.price_scroll = QScrollArea()
        self.price_scroll.setObjectName("wizard_price_scroll")
        self.price_scroll.setWidgetResizable(True)
        self.price_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.price_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.price_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        price_palette = QPalette(self.palette())
        price_palette.setColor(QPalette.ColorRole.Window, QColor("#F4F7FA"))
        price_palette.setColor(QPalette.ColorRole.Base, QColor("#F4F7FA"))
        price_palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
        self.price_scroll.setPalette(price_palette)
        self.price_scroll.viewport().setPalette(price_palette)
        self.price_scroll.viewport().setAutoFillBackground(True)
        self.price_scroll.setStyleSheet(
            "QScrollArea#wizard_price_scroll{background:#F4F7FA;border:none;}"
            "QScrollArea#wizard_price_scroll QScrollBar:vertical{background:#E7EDF4;"
            "width:9px;border:none;border-radius:4px;}"
            "QScrollArea#wizard_price_scroll QScrollBar::handle:vertical{background:#91A4B8;"
            "min-height:28px;border:none;border-radius:4px;}"
            "QScrollArea#wizard_price_scroll QScrollBar::add-line:vertical,"
            "QScrollArea#wizard_price_scroll QScrollBar::sub-line:vertical{height:0;border:none;}"
        )
        content = QWidget()
        content.setObjectName("wizard_price_content")
        content.setMaximumWidth(1280)
        content.setPalette(price_palette)
        content.setAutoFillBackground(True)
        content.setStyleSheet("QWidget#wizard_price_content{background:#F4F7FA;color:#172033;}")
        self.price_content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 2, 12, 6)
        layout.setSpacing(10)

        self.price_intro = QLabel(
            "กำหนดราคาต่อหน้าสำหรับ A4/A3 สีและขาวดำ · ราคา 0.00 หมายถึงไม่คิดค่าใช้จ่าย"
        )
        self.price_intro.setWordWrap(True)
        self.price_intro.setFont(fnt(F_MD))
        self.price_intro.setStyleSheet(f"color:{C_TEXT2};border:none;background:transparent;")

        mode_section = QFrame()
        mode_section.setObjectName("price_mode_section")
        mode_section.setStyleSheet("QFrame#price_mode_section{background:transparent;border:none;}")
        mode_layout = QVBoxLayout(mode_section)
        mode_layout.setContentsMargins(0, 2, 0, 4)
        mode_layout.setSpacing(6)
        mode_header = QHBoxLayout()
        mode_header.setSpacing(12)
        mode_title = QLabel("วิธีใช้ราคา")
        mode_title.setFont(fnt(F_LG, True))
        mode_title.setStyleSheet("color:#172033;border:none;background:transparent;")
        mode_header.addWidget(mode_title)
        mode_header.addWidget(self.price_intro, 1)
        mode_layout.addLayout(mode_header)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        mode_row.addStretch()
        self.shared_price_mode = QPushButton("ใช้ราคาเดียวกันทุกเครื่อง")
        self.per_device_price_mode = QPushButton("ตั้งราคาแยกรายเครื่อง")
        self.deferred_price_mode = QPushButton("ตั้งค่าราคาภายหลัง")
        self.price_mode_group = QButtonGroup(self)
        self.price_mode_group.setExclusive(True)
        mode_style = (
            "QPushButton{background:#FFFFFF;color:#172033;border:1px solid #CBD5E1;"
            "border-radius:6px;padding:12px 18px;font-weight:700;text-align:left;}"
            "QPushButton:hover{border-color:#7C91AA;background:#F8FAFC;}"
            "QPushButton:checked{background:#EAF3FB;color:#0B4F8A;border:2px solid #1769AA;}"
            "QPushButton:focus{border:2px solid #1769AA;background:#F8FCFF;}"
        )
        for button in (
            self.shared_price_mode,
            self.per_device_price_mode,
            self.deferred_price_mode,
        ):
            button.setCheckable(True)
            button.setFont(fnt(F_MD, True))
            button.setStyleSheet(mode_style)
            button.setMinimumHeight(44)
            button.setMaximumWidth(480)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.price_mode_group.addButton(button)
        self.shared_price_mode.toggled.connect(self._price_mode_changed)
        self.per_device_price_mode.toggled.connect(self._price_mode_changed)
        self.deferred_price_mode.toggled.connect(self._price_mode_changed)
        mode_row.addWidget(self.shared_price_mode)
        mode_row.addWidget(self.per_device_price_mode)
        mode_row.addWidget(self.deferred_price_mode)
        mode_row.addStretch()
        mode_layout.addLayout(mode_row)

        self.effective_row_widget = QWidget()
        effective_row = QHBoxLayout(self.effective_row_widget)
        effective_row.setContentsMargins(0, 2, 0, 0)
        effective_row.setSpacing(10)
        effective_label = QLabel("วันที่เริ่มใช้ราคาชุดนี้")
        effective_label.setStyleSheet("color:#334155;font-weight:700;border:none;background:transparent;")
        effective_row.addWidget(effective_label)
        self.effective_date = QDateEdit(QDate.currentDate())
        self.effective_date.setCalendarPopup(True)
        self.effective_date.setDisplayFormat("dd/MM/yyyy")
        self.effective_date.setMinimumWidth(150)
        self.effective_date.setMaximumWidth(190)
        self.effective_date.setMinimumHeight(38)
        self.effective_date.setFont(fnt(F_MD, True))
        self.effective_date.setStyleSheet(
            "QDateEdit{background:#FFFFFF;color:#172033;border:1px solid #B8C7D9;"
            "border-radius:6px;padding:7px 11px;font-weight:700;}"
            "QDateEdit:focus{border:2px solid #1769AA;}"
        )
        self._style_price_calendar(self.effective_date.calendarWidget())
        effective_row.addWidget(self.effective_date)
        effective_hint = QLabel("รายการตั้งแต่วันนี้จะใช้ราคาชุดนี้")
        effective_hint.setStyleSheet(f"color:{C_TEXT2};border:none;background:transparent;")
        effective_row.addWidget(effective_hint)
        effective_row.addStretch()
        mode_layout.addWidget(self.effective_row_widget)
        layout.addWidget(mode_section)

        self.deferred_price_notice = QLabel(
            "<b>ยังไม่คิดค่าใช้จ่ายในขณะนี้</b><br>"
            "ระบบจะบันทึกราคา 0.00 ทุกประเภท และสามารถตั้งราคาจริงภายหลังได้จาก Settings"
        )
        self.deferred_price_notice.setWordWrap(True)
        self.deferred_price_notice.setStyleSheet(
            "background:#FFF8E8;color:#75510A;border:1px solid #E8D7A4;"
            "border-radius:6px;padding:12px;"
        )
        self.deferred_price_notice.setVisible(False)
        layout.addWidget(self.deferred_price_notice)

        self.shared_price_box = QFrame()
        self.shared_price_box.setObjectName("shared_price_box")
        self.shared_price_box.setStyleSheet("QFrame#shared_price_box{background:transparent;border:none;}")
        shared_layout = QVBoxLayout(self.shared_price_box)
        shared_layout.setContentsMargins(0, 2, 0, 4)
        shared_layout.setSpacing(5)
        shared_header = QHBoxLayout()
        shared_header.setSpacing(12)
        shared_title = QLabel("ราคาสำหรับทุกเครื่อง")
        shared_title.setFont(fnt(F_LG, True))
        shared_title.setStyleSheet("color:#172033;border:none;background:transparent;")
        shared_header.addWidget(shared_title)
        shared_note = QLabel("หน่วย: บาทต่อหน้าที่พิมพ์ · ใส่ 0.00 สำหรับรายการที่ไม่คิดเงิน")
        shared_note.setStyleSheet(f"color:{C_TEXT2};border:none;background:transparent;")
        shared_header.addWidget(shared_note, 1)
        shared_layout.addLayout(shared_header)
        self.shared_price_row = self._price_inputs()
        shared_layout.addWidget(self._price_grid(self.shared_price_row))
        layout.addWidget(self.shared_price_box)

        self.per_device_price_box = QFrame()
        self.per_device_price_box.setObjectName("per_device_price_box")
        self.per_device_price_box.setStyleSheet("QFrame#per_device_price_box{background:transparent;border:none;}")
        device_layout = QVBoxLayout(self.per_device_price_box)
        device_layout.setContentsMargins(0, 14, 0, 12)
        device_layout.setSpacing(8)
        device_title = QLabel("ราคาแยกรายเครื่อง")
        device_title.setFont(fnt(F_XL, True))
        device_title.setStyleSheet("color:#172033;border:none;background:transparent;")
        device_layout.addWidget(device_title)
        device_note = QLabel("กำหนด 4 ราคาของแต่ละเครื่องแยกกัน · แสดงเฉพาะเครื่องที่เลือกในขั้นแรก")
        device_note.setStyleSheet(f"color:{C_TEXT2};border:none;background:transparent;")
        device_layout.addWidget(device_note)
        self.price_rows: list[dict[str, QDoubleSpinBox]] = []
        self.device_price_cards: list[tuple[QFrame, QLabel]] = []
        for slot in range(3):
            card = QFrame()
            card.setObjectName(f"device_price_card_{slot}")
            card.setStyleSheet(
                f"QFrame#device_price_card_{slot}{{background:transparent;border:none;"
                "border-top:1px solid #D6E0EA;}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 14, 0, 14)
            card_layout.setSpacing(7)
            card_title = QLabel(f"เครื่อง {slot + 1}")
            card_title.setFont(fnt(F_MD, True))
            card_title.setStyleSheet("color:#172033;border:none;background:transparent;")
            card_layout.addWidget(card_title)
            row = self._price_inputs()
            card_layout.addWidget(self._price_grid(row))
            self.price_rows.append(row)
            self.device_price_cards.append((card, card_title))
            device_layout.addWidget(card)
        layout.addWidget(self.per_device_price_box)

        self.billing_section = QFrame()
        self.billing_section.setObjectName("billing_section")
        self.billing_section.setStyleSheet("QFrame#billing_section{background:transparent;border-top:1px solid #D6E0EA;}")
        billing_layout = QHBoxLayout(self.billing_section)
        billing_layout.setContentsMargins(0, 8, 0, 4)
        billing_layout.setSpacing(24)
        billing_copy = QVBoxLayout()
        billing_copy.setSpacing(3)
        billing_title = QLabel("รอบบิลและส่วนลด")
        billing_title.setFont(fnt(F_LG, True))
        billing_title.setStyleSheet("color:#172033;border:none;background:transparent;")
        billing_copy.addWidget(billing_title)
        self.billing_defaults = QLabel(
            "ค่าแนะนำ: กระดาษเสีย 2% · ตัดรอบวันที่ 31"
        )
        self.billing_defaults.setWordWrap(True)
        self.billing_defaults.setStyleSheet(
            "color:#75510A;border:none;background:transparent;"
        )
        billing_copy.addWidget(self.billing_defaults)
        billing_copy.addStretch()
        billing_layout.addLayout(billing_copy, 0)
        billing = QGridLayout()
        billing.setHorizontalSpacing(16)
        billing.setVerticalSpacing(4)
        self.waste_paper_pct = QDoubleSpinBox()
        self.waste_paper_pct.setRange(0, 100)
        self.waste_paper_pct.setDecimals(1)
        self.waste_paper_pct.setSuffix(" %")
        self.billing_end_day = WizardComboBox()
        for day in range(1, 32):
            self.billing_end_day.addItem(f"วันที่ {day} ของเดือน", day)
        billing_input_style = (
            "QDoubleSpinBox,QComboBox{background:#FFFFFF;color:#172033;border:1px solid #B8C7D9;"
            "border-radius:6px;padding:7px 11px;font-weight:700;}"
            "QDoubleSpinBox:focus,QComboBox:focus{border:2px solid #1769AA;}"
        )
        for spin in (self.waste_paper_pct, self.billing_end_day):
            spin.setMinimumHeight(38)
            spin.setMaximumWidth(300)
            spin.setFont(fnt(F_MD, True))
            spin.setStyleSheet(billing_input_style)
        self.waste_paper_pct.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._style_wizard_combo(self.billing_end_day, popup_width=260)
        waste_label = QLabel("ส่วนลดกระดาษเสีย")
        waste_label.setStyleSheet("color:#334155;font-weight:700;border:none;background:transparent;")
        billing_day_label = QLabel("วันสิ้นสุดรอบบิล")
        billing_day_label.setStyleSheet("color:#334155;font-weight:700;border:none;background:transparent;")
        billing.addWidget(waste_label, 0, 0)
        billing.addWidget(billing_day_label, 0, 1)
        billing.addWidget(self.waste_paper_pct, 1, 0)
        billing.addWidget(self.billing_end_day, 1, 1)
        waste_hint = QLabel("หักเปอร์เซ็นต์นี้ออกจากยอดค่าใช้จ่ายรวม")
        waste_hint.setStyleSheet(f"color:{C_TEXT2};border:none;background:transparent;")
        billing_hint = QLabel("เดือนที่ไม่มีวันที่เลือก จะใช้วันสุดท้ายของเดือน")
        billing_hint.setStyleSheet(f"color:{C_TEXT2};border:none;background:transparent;")
        billing.addWidget(waste_hint, 2, 0)
        billing.addWidget(billing_hint, 2, 1)
        billing.setColumnStretch(0, 1)
        billing.setColumnStretch(1, 1)
        billing_layout.addLayout(billing, 1)
        layout.addWidget(self.billing_section)
        layout.addStretch()
        self.price_scroll.setWidget(content)
        page_layout.addWidget(self.price_scroll)
        return page

    @staticmethod
    def _price_inputs() -> dict[str, QDoubleSpinBox]:
        inputs: dict[str, QDoubleSpinBox] = {}
        for key in ("a4_color", "a4_bw", "a3_color", "a3_bw"):
            spin = QDoubleSpinBox()
            spin.setRange(0, 9999)
            spin.setDecimals(2)
            spin.setMinimumHeight(42)
            spin.setMinimumWidth(150)
            spin.setMaximumWidth(230)
            spin.setFont(fnt(F_LG, True))
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setStyleSheet(
                "QDoubleSpinBox{background:#FFFFFF;color:#172033;border:1px solid #B8C7D9;"
                "border-radius:6px;padding:8px 11px;font-weight:700;}"
                "QDoubleSpinBox:focus{border:2px solid #1769AA;background:#F8FCFF;}"
            )
            inputs[key] = spin
        return inputs

    @staticmethod
    def _price_cell(spin: QDoubleSpinBox) -> QWidget:
        """Keep the number field clear; the unit belongs beside it, not inside it."""
        cell = QWidget()
        cell.setObjectName("price_value_cell")
        cell.setStyleSheet("QWidget#price_value_cell{background:#FFFFFF;border:none;}")
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(10, 4, 10, 4)
        cell_layout.setSpacing(8)
        cell_layout.addStretch()
        cell_layout.addWidget(spin)
        unit = QLabel("บาท/หน้า")
        unit.setStyleSheet("color:#475569;font-weight:700;border:none;background:transparent;")
        unit.setMinimumWidth(66)
        cell_layout.addWidget(unit)
        cell_layout.addStretch()
        return cell

    @staticmethod
    def _price_grid(inputs: dict[str, QDoubleSpinBox]) -> QFrame:
        matrix = QFrame()
        matrix.setObjectName("price_matrix")
        matrix.setStyleSheet(
            "QFrame#price_matrix{background:#D6E0EA;border:1px solid #D6E0EA;"
            "border-radius:6px;}"
        )
        grid = QGridLayout(matrix)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
        headers = ("ขนาดกระดาษ", "สี (Color)", "ขาวดำ (B&W)")
        for column, text in enumerate(headers):
            header = QLabel(text)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setMinimumHeight(34)
            if column == 1:
                background = "#E5F5FA"
                color = "#087A96"
            elif column == 2:
                background = "#EEF1F4"
                color = "#334155"
            else:
                background = "#F1F5F9"
                color = "#334155"
            header.setStyleSheet(
                f"background:{background};color:{color};border:none;padding:4px 8px;font-weight:800;"
            )
            grid.addWidget(header, 0, column)
        for row, size in enumerate(("A4", "A3"), start=1):
            size_label = QLabel(size)
            size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            size_label.setMinimumWidth(110)
            size_label.setMinimumHeight(52)
            size_label.setStyleSheet(
                "background:#F8FAFC;color:#172033;border:none;padding:6px 10px;font-weight:800;"
            )
            grid.addWidget(size_label, row, 0)
        grid.addWidget(SetupWizardV5._price_cell(inputs["a4_color"]), 1, 1)
        grid.addWidget(SetupWizardV5._price_cell(inputs["a4_bw"]), 1, 2)
        grid.addWidget(SetupWizardV5._price_cell(inputs["a3_color"]), 2, 1)
        grid.addWidget(SetupWizardV5._price_cell(inputs["a3_bw"]), 2, 2)
        grid.setColumnMinimumWidth(0, 110)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        return matrix

    def _price_mode_changed(self, _checked: bool = False) -> None:
        deferred = self.deferred_price_mode.isChecked()
        shared = self.shared_price_mode.isChecked() and not deferred
        per_device = self.per_device_price_mode.isChecked() and not deferred
        self.shared_price_box.setVisible(shared)
        self.per_device_price_box.setVisible(per_device)
        self.deferred_price_notice.setVisible(deferred)
        self.effective_row_widget.setVisible(not deferred)
        show_billing = not deferred and not self.edit_mode
        self.billing_section.setVisible(show_billing)
        self.billing_defaults.setVisible(show_billing)

    def _refresh_device_price_cards(self) -> None:
        selected = {device.slot: device for device in self._configs()}
        for slot, (card, title) in enumerate(self.device_price_cards):
            device = selected.get(slot)
            card.setVisible(device is not None)
            if device is not None:
                title.setText(f"{device.name} · ราคาเฉพาะเครื่อง")

    def _load_existing(self) -> None:
        first_started = get_cfg("client_first_started_at", "") or date.today().isoformat()
        self.first_started_input.setText(self._display_first_started(first_started))
        self.company_name_input.setText(get_cfg("company_name", "") or "")
        if self.lab_mode and not self.company_name_input.text().strip():
            self.company_name_input.setText("บริษัท ตัวอย่าง จำกัด")
        registration_snapshot = self.registration_state.snapshot()
        self.privacy_notice_accepted.setChecked(
            bool(registration_snapshot.get("notice_accepted"))
        )
        saved_mode = str(registration_snapshot.get("mode") or "online")
        self.registration_offline_mode.setChecked(saved_mode == "offline")
        self.registration_online_mode.setChecked(saved_mode != "offline")
        self._registration_mode_changed()
        existing_devices = self.repository.list()
        for device in existing_devices:
            result = {
                # A saved status is historical evidence, not proof that the
                # printer is reachable in this setup session.  Always require
                # a fresh SNMP + Web verification before showing Ready.
                "online": False,
                "web_ok": False,
                "tested": False,
                "saved": True,
                "previous_connection_status": device.connection_status,
                "model": device.model,
                "serial": device.serial,
                "total": device.last_total,
            }
            self.results[device.slot] = result
            self._upsert_discovered(
                {
                    "slot": device.slot,
                    "name": device.name,
                    "host": device.host,
                    "model": device.model,
                    "serial": device.serial,
                    "username": device.username,
                    "password": device.password,
                    "tls_mode": device.tls_mode,
                    "tls_fingerprint": device.tls_fingerprint,
                    "result": result,
                },
                select=device.enabled,
            )
        today = date.today()
        for slot, row in enumerate(self.price_rows):
            prices = self.pricing.get_prices(slot, today)
            for key, spin in row.items():
                spin.setValue(getattr(prices, key))
        if existing_devices:
            first_prices = self.pricing.get_prices(existing_devices[0].slot, today)
            for key, spin in self.shared_price_row.items():
                spin.setValue(getattr(first_prices, key))
        self.waste_paper_pct.setValue(float(get_cfg("waste_paper_pct", str(DEFAULT_WASTE_PCT)) or DEFAULT_WASTE_PCT))
        billing_day = int(get_cfg("billing_day", str(DEFAULT_BILLING_DAY)) or DEFAULT_BILLING_DAY)
        self.billing_end_day.setCurrentIndex(max(0, min(30, billing_day - 1)))
        mode = get_cfg("pricing_mode", "per_device" if existing_devices else "shared")
        self.shared_price_mode.setChecked(mode not in {"per_device", "deferred"})
        self.per_device_price_mode.setChecked(mode == "per_device")
        self.deferred_price_mode.setChecked(mode == "deferred")
        self._price_mode_changed()

    @staticmethod
    def _display_first_started(value: str) -> str:
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return value

    def _selected_entries(self) -> list[dict]:
        return [entry for entry in self.discovered_devices if entry.get("selected")]

    def _selection_changed(self) -> None:
        selected_count = len(self._selected_entries())
        self.selection_badge.setText(f"เลือกแล้ว {selected_count}/3")
        for row in range(len(self.discovered_devices)):
            self._render_discovered_row(row)
        self._update_device_actions()

    def _set_device_selected(self, row: int, selected: bool) -> None:
        if row >= len(self.discovered_devices):
            return
        entry = self.discovered_devices[row]
        if selected and not entry.get("selected") and len(self._selected_entries()) >= 3:
            self._show_wizard_message(
                "เลือกได้สูงสุด 3 เครื่อง",
                "KOMI Report V5 ตั้งค่าได้สูงสุด 3 เครื่อง",
                icon=QStyle.StandardPixmap.SP_MessageBoxInformation,
            )
            self._render_discovered_row(row)
            return
        entry["selected"] = selected
        self._selection_changed()

    def _upsert_discovered(self, payload: dict, *, select: bool = False) -> None:
        host = str(payload["host"])
        row = next((index for index, item in enumerate(self.discovered_devices) if item["host"] == host), None)
        if row is None:
            entry = {
                "slot": payload.get("slot"),
                "name": payload.get("name") or payload.get("model") or host,
                "host": host,
                "model": payload.get("model") or "—",
                "serial": payload.get("serial") or "—",
                "username": payload.get("username") or DEFAULT_ADMIN_USERNAME,
                "password": payload.get("password") or "",
                "tls_mode": payload.get("tls_mode") or "system",
                "tls_fingerprint": payload.get("tls_fingerprint") or "",
                "result": payload.get("result") or {"online": True, "web_ok": False},
                "is_virtual": bool(payload.get("is_virtual", False)),
                "found_in_registration_scan": bool(payload.get("found_in_registration_scan", False)),
                "selected": bool(select),
            }
            self.discovered_devices.append(entry)
            row = len(self.discovered_devices) - 1
        else:
            entry = self.discovered_devices[row]
            entry.update({key: value for key, value in payload.items() if key != "host" and value is not None})
            entry["host"] = host
            entry["result"] = payload.get("result", entry.get("result", {}))
        self._render_discovered_row(row)
        if select:
            entry["selected"] = True
            self._selection_changed()

    def _render_discovered_row(self, row: int) -> None:
        entry = self.discovered_devices[row]
        self.device_table.setRowCount(len(self.discovered_devices))
        result = entry.get("result", {})
        selected = bool(entry.get("selected"))
        if result.get("online") and result.get("web_ok"):
            prefix = "● VIRTUAL · " if entry.get("is_virtual") else "● "
            status, color = f"{prefix}พร้อมใช้งาน · SNMP + Web ผ่าน", C_GREEN
            background = QColor("#EDF8F2") if selected else None
        elif result.get("tested"):
            status, color = "● ไม่ผ่าน · " + str(result.get("error") or "Web Connection อ่านค่าไม่ได้")[:60], C_RED
            background = QColor("#FDECEC") if selected else None
        elif result.get("online"):
            status, color = "● พบเครื่อง · รอตรวจสอบ Web", C_TEXT2
            background = QColor("#E3F0FB") if selected else None
        elif result.get("saved"):
            status, color = "บันทึกไว้ · รอตรวจสอบรอบนี้", C_TEXT2
            background = QColor("#E3F0FB") if selected else None
        elif result.get("error"):
            status, color = "● ไม่ผ่าน · " + str(result["error"])[:60], C_RED
            background = QColor("#FDECEC")
        else:
            status, color = "รอทดสอบ", C_TEXT2
            background = QColor("#E3F0FB") if selected else None
        checkbox = QCheckBox()
        checkbox.setChecked(selected)
        checkbox.setAccessibleName(f"เลือก {entry['name']}")
        checkbox.setToolTip(f"เลือก {entry['name']} เข้าระบบ")
        checkbox.toggled.connect(
            lambda checked, current_row=row: self._set_device_selected(current_row, checked)
        )
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(8, 0, 8, 0)
        checkbox_layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignCenter)
        if background is not None:
            checkbox_container.setStyleSheet(f"background:{background.name()};")
        self.device_table.setCellWidget(row, 0, checkbox_container)

        values = (entry["model"], entry["host"], entry["serial"], status)
        for column, value in enumerate(values, start=1):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter
                | (Qt.AlignmentFlag.AlignRight if column == 2 else Qt.AlignmentFlag.AlignLeft)
            )
            if column == 4:
                item.setForeground(QColor(color))
            if background is not None:
                item.setBackground(background)
            if result.get("tested") and not (result.get("online") and result.get("web_ok")):
                item.setForeground(QColor(C_RED) if column == 4 else QColor("#7F1D1D"))
            item.setToolTip(str(value))
            self.device_table.setItem(row, column, item)
        credential_item = QTableWidgetItem("ตั้งค่า")
        credential_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        credential_item.setForeground(QColor("#1769AA"))
        credential_item.setToolTip(f"ตั้งค่า Username / Password สำหรับ {entry['name']}")
        if background is not None:
            credential_item.setBackground(background)
        self.device_table.setItem(row, 5, credential_item)

    def _device_table_action(self, row: int, column: int) -> None:
        if column != 5 or row >= len(self.discovered_devices):
            return
        self._open_credentials(str(self.discovered_devices[row]["host"]))

    def _open_credentials(self, host: str) -> None:
        entry = next((item for item in self.discovered_devices if item["host"] == host), None)
        if entry is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"User / Password · {host}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        username = QLineEdit(entry["username"])
        password = QLineEdit(entry["password"])
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", username)
        form.addRow("Password", password)
        layout.addLayout(form)
        hint = QLabel(
            tr(
                f"Username: {DEFAULT_ADMIN_USERNAME} · กรุณากรอก password ของเครื่อง",
                f"Username: {DEFAULT_ADMIN_USERNAME} · Enter the printer password",
            )
        )
        hint.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        save = btn("บันทึก", "primary")
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        def credentials_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted):
                entry["username"] = username.text().strip() or DEFAULT_ADMIN_USERNAME
                entry["password"] = password.text()

        self._open_wizard_child(dialog, credentials_finished)

    def _advanced_scan(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Advanced scan")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        start = QLineEdit()
        end = QLineEdit()
        start.setPlaceholderText(self.ADVANCED_SCAN_EXAMPLES[0])
        end.setPlaceholderText(self.ADVANCED_SCAN_EXAMPLES[1])
        form.addRow("IP เริ่มต้น", start)
        form.addRow("IP สิ้นสุด", end)
        layout.addLayout(form)
        hint = QLabel("สแกนได้สูงสุด 1,024 IP ต่อครั้ง")
        hint.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        confirm = btn("เริ่ม Advanced scan", "primary")
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        def advanced_finished(result: int) -> None:
            if result != int(QDialog.DialogCode.Accepted):
                return
            try:
                first = ipaddress.ip_address(start.text().strip())
                last = ipaddress.ip_address(end.text().strip())
                if first.version != 4 or last.version != 4 or int(last) < int(first):
                    raise ValueError
                values = range(int(first), int(last) + 1)
                if len(values) > 1024:
                    raise ValueError("กรุณาแบ่งช่วงให้ไม่เกิน 1,024 IP")
                self._scan_network(
                    [str(ipaddress.ip_address(value)) for value in values]
                )
            except ValueError as exc:
                self._show_wizard_message(
                    "ช่วง IP ไม่ถูกต้อง",
                    str(exc) or "กรุณาระบุ IPv4 เริ่มต้นและสิ้นสุดให้ถูกต้อง",
                )

        self._open_wizard_child(dialog, advanced_finished)

    def _manual_setup(self) -> None:
        """Add up to three devices directly when network discovery is not useful."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Manual setup")
        dialog.setMinimumWidth(650)
        layout = QVBoxLayout(dialog)
        hint = QLabel("กรอก IP ของเครื่องที่ต้องการตั้งค่าได้สูงสุด 3 เครื่อง · Username ใช้ administrator")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        for column, text in enumerate(("เครื่อง", "IP address", "Username", "Password")):
            header = QLabel(text)
            header.setStyleSheet("font-weight:700;color:#123A63;")
            grid.addWidget(header, 0, column)
        rows: list[tuple[QLineEdit, QLineEdit]] = []
        for index in range(3):
            grid.addWidget(QLabel(f"MFP {index + 1}"), index + 1, 0)
            host = QLineEdit()
            host.setPlaceholderText(self._manual_ip_example(index))
            grid.addWidget(host, index + 1, 1)
            grid.addWidget(QLabel(DEFAULT_ADMIN_USERNAME), index + 1, 2)
            password = QLineEdit()
            password.setPlaceholderText(tr("กรอก Administrator password", "Enter Administrator password"))
            password.setEchoMode(QLineEdit.EchoMode.Password)
            grid.addWidget(password, index + 1, 3)
            rows.append((host, password))
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        confirm = btn("เพิ่มเครื่องที่กรอก", "primary")
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        def manual_finished(result: int) -> None:
            if result != int(QDialog.DialogCode.Accepted):
                return
            try:
                self._add_manual_entries(
                    [
                        (
                            host.text().strip(),
                            password.text(),
                        )
                        for host, password in rows
                    ]
                )
            except ValueError as exc:
                self._show_wizard_message("IP address ไม่ถูกต้อง", str(exc))

        self._open_wizard_child(dialog, manual_finished)

    @staticmethod
    def _manual_ip_example(index: int) -> str:
        return f"เช่น 192.168.1.{101 + index}"

    def _add_manual_entries(self, entries: list[tuple[str, str]]) -> None:
        """Validate manual rows, then make those rows the current selection."""
        valid_entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for host, password in entries:
            if not host:
                continue
            try:
                address = ipaddress.ip_address(host)
            except ValueError as exc:
                raise ValueError(f"{host} ไม่ใช่ IP address ที่ถูกต้อง") from exc
            if address.version != 4:
                raise ValueError(f"{host} ต้องเป็น IPv4 address")
            if host not in seen:
                valid_entries.append((host, password))
                seen.add(host)
        if not valid_entries:
            raise ValueError("กรุณากรอก IP อย่างน้อย 1 เครื่อง")

        self.device_table.clearSelection()
        for host, password in valid_entries[:3]:
            self._upsert_discovered(
                {
                    "name": host,
                    "host": host,
                    "model": "รอทดสอบ",
                    "serial": "—",
                    "username": DEFAULT_ADMIN_USERNAME,
                    "password": password,
                    "result": {"online": False, "web_ok": False},
                },
                select=True,
            )
        self.scan_status.setText("เพิ่มเครื่องด้วย Manual setup แล้ว · กดทดสอบการเชื่อมต่อเพื่ออ่าน Model และ Serial")
        self._selection_changed()

    @staticmethod
    def _default_device_name(model: str, fallback: str) -> str:
        cleaned = " ".join(model.split())
        upper = cleaned.upper()
        if upper.startswith("KONICA MINOLTA"):
            cleaned = cleaned[len("KONICA MINOLTA") :].strip()
        if cleaned.upper().startswith("KM "):
            return cleaned
        if cleaned.casefold().startswith("bizhub"):
            return f"KM {cleaned}"
        return cleaned or fallback

    def _name_selected_devices(
        self,
        on_complete: Callable[[], None] | None = None,
    ) -> QDialog | None:
        """Confirm logical Slots and installation-point names after connection tests."""
        selected = self._selected_entries()
        if not selected:
            return None
        self._assign_selected_slots(selected)
        existing_names = {device.slot: device.name for device in self.repository.list()}
        dialog = QDialog(self)
        dialog.setWindowTitle("กำหนด Slot และจุดติดตั้ง")
        dialog.setMinimumWidth(720)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Slot คือจุดติดตั้งหรือแผนก · เปลี่ยนเครื่องในอนาคตให้ใช้ Slot เดิมเพื่อให้ประวัติต่อเนื่อง"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("background:#EDF8F2;color:#176B49;border:1px solid #B8DFC9;padding:10px;")
        layout.addWidget(intro)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(9)
        for column, text in enumerate(("Slot", "IP address", "ชื่อจุดติดตั้ง / แผนก")):
            label = QLabel(text)
            label.setStyleSheet("font-weight:700;color:#123A63;")
            grid.addWidget(label, 0, column)
        mapping_inputs: list[tuple[dict, QComboBox, QLineEdit]] = []
        for index, entry in enumerate(selected):
            slot_combo = WizardComboBox()
            for slot in range(3):
                slot_combo.addItem(f"Slot {slot + 1}", slot)
            slot_combo.setCurrentIndex(int(entry["slot"]))
            slot_combo.setMinimumWidth(132)
            self._style_wizard_combo(slot_combo, popup_width=160)
            grid.addWidget(slot_combo, index + 1, 0)
            grid.addWidget(QLabel(entry["host"]), index + 1, 1)
            slot = int(entry["slot"])
            default_name = existing_names.get(slot) or str(entry.get("name") or "").strip()
            if not default_name or default_name == entry["host"]:
                default_name = self._default_device_name(
                    str(entry.get("model") or ""),
                    f"จุดติดตั้ง {slot + 1}",
                )
            name_input = QLineEdit(default_name)
            name_input.setPlaceholderText("เช่น แผนกบัญชี")
            grid.addWidget(name_input, index + 1, 2)
            mapping_inputs.append((entry, slot_combo, name_input))
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        proceed = btn("ถัดไป →", "primary")
        cancel.clicked.connect(dialog.reject)
        actions.addWidget(cancel)
        actions.addWidget(proceed)
        layout.addLayout(actions)

        def confirm_names() -> None:
            chosen_slots = [
                int(slot_combo.currentData())
                for _entry, slot_combo, _name in mapping_inputs
            ]
            if len(set(chosen_slots)) != len(chosen_slots):
                self._show_wizard_message(
                    "Slot ซ้ำกัน", "เครื่องแต่ละเครื่องต้องอยู่คนละ Slot"
                )
                return
            for entry, slot_combo, name_input in mapping_inputs:
                slot = int(slot_combo.currentData())
                entry["slot"] = slot
                entry["name"] = (
                    name_input.text().strip() or f"จุดติดตั้ง {slot + 1}"
                )
            dialog.accept()

        proceed.clicked.connect(confirm_names)

        def naming_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted) and on_complete is not None:
                on_complete()

        return self._open_wizard_child(dialog, naming_finished)

    def _scan_network(self, hosts: list[str] | None = None) -> None:
        if isinstance(hosts, bool):
            hosts = None
        if self._scan_thread is not None:
            return
        self.scan_button.setEnabled(False)
        self.advanced_scan_button.setEnabled(False)
        self.manual_setup_button.setEnabled(False)
        self.scan_button.setText("กำลังค้นหา…")
        self.cancel_scan_button.setEnabled(True)
        self.cancel_scan_button.setVisible(True)
        thread = QThread(self)
        effective_hosts, snmp_port = self._scan_parameters(hosts)
        worker = NetworkDiscoveryWorker(effective_hosts, snmp_port=snmp_port)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._discovery_result)
        worker.progress.connect(self.scan_status.setText)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._scan_finished)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _scan_parameters(self, hosts: list[str] | None) -> tuple[list[str] | None, int]:
        """Use virtual ports only for the explicit local simulator endpoint."""
        effective_hosts = hosts
        if self.lab_mode and effective_hosts is None and self.lab_hosts:
            effective_hosts = list(self.lab_hosts)
        virtual_hosts = set(self.lab_hosts or ())
        uses_virtual_endpoint = bool(
            self.lab_mode
            and effective_hosts
            and virtual_hosts
            and set(effective_hosts).issubset(virtual_hosts)
        )
        return effective_hosts, self.lab_snmp_port if uses_virtual_endpoint else 161

    def _lab_endpoint_ports(self) -> dict[str, tuple[int, int]]:
        if not self.lab_mode:
            return {}
        return {
            host: (self.lab_snmp_port, self.lab_web_port)
            for host in (self.lab_hosts or ())
        }

    def _discovery_result(self, result: dict) -> None:
        is_virtual = str(result.get("serial") or "").startswith("KOMI-DEMO-")
        model = str(result.get("model") or "")
        self._upsert_discovered(
            {
                **result,
                "name": self._default_device_name(model, str(result.get("host") or "เครื่องพิมพ์")),
                "is_virtual": is_virtual,
                "found_in_registration_scan": True,
                "result": {**result, "online": True, "web_ok": False},
            },
            select=self.lab_mode and is_virtual,
        )

    def _scan_finished(self) -> None:
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)
        self.advanced_scan_button.setEnabled(True)
        self.manual_setup_button.setEnabled(True)
        self.scan_button.setText("ค้นหาอีกครั้ง")
        self.cancel_scan_button.setVisible(False)
        self.cancel_scan_button.setEnabled(True)
        self._update_device_actions()
        if self.lab_mode:
            virtual_entries = [entry for entry in self._selected_entries() if entry.get("is_virtual")]
            if virtual_entries:
                self.scan_status.setText("พบ Virtual Printer ผ่าน SNMP แล้ว · กำลังทดสอบ Web Connection จริง…")
                QTimer.singleShot(100, self._test_all)

    def _stop_active_workers(self, timeout_ms: int = 5000) -> bool:
        """Ask setup workers to stop before Qt destroys their QThread owners."""
        threads = [
            thread
            for thread in (self._scan_thread, self._thread)
            if thread is not None and thread.isRunning()
        ]
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        for thread in threads:
            thread.requestInterruption()
            thread.quit()
        return all(thread.wait(timeout_ms) for thread in threads)

    def closeEvent(self, event) -> None:
        if not self._stop_active_workers():
            event.ignore()
            return
        super().closeEvent(event)

    def _configs(self) -> list[DeviceConfig]:
        devices: list[DeviceConfig] = []
        selected = self._selected_entries()
        self._assign_selected_slots(selected)
        for entry in selected:
            slot = int(entry["slot"])
            result = entry.get("result", {})
            self.results[slot] = result
            devices.append(
                DeviceConfig(
                    slot=slot,
                    name=entry["name"],
                    host=entry["host"],
                    username=entry["username"],
                    password=entry["password"],
                    tls_mode=entry.get("tls_mode", "system"),
                    tls_fingerprint=entry.get("tls_fingerprint", ""),
                    enabled=True,
                    model=result.get("model") or entry["model"].replace("—", ""),
                    serial=result.get("serial") or entry["serial"].replace("—", ""),
                    connection_status="online" if result.get("online") else "pending",
                    last_total=result.get("total"),
                )
            )
        if not devices:
            raise ValueError("กรุณาตั้งค่าเครื่องอย่างน้อย 1 เครื่อง")
        return devices

    def _registration_devices(self) -> list[dict[str, object]]:
        """Return scan results plus selected manual devices without network identity."""
        inventory: list[dict[str, object]] = []
        for entry in self.discovered_devices:
            selected = bool(entry.get("selected"))
            if not selected and not entry.get("found_in_registration_scan"):
                continue
            result = entry.get("result", {})
            serial_number = str(result.get("serial") or entry.get("serial") or "").strip()
            model = str(result.get("model") or entry.get("model") or "").strip()
            raw_slot = entry.get("slot")
            inventory.append(
                {
                    "serial_number": serial_number,
                    "model": model,
                    "selected": selected,
                    "device_slot": int(raw_slot) + 1 if selected and raw_slot is not None else None,
                }
            )
        return inventory

    @staticmethod
    def _assign_selected_slots(selected: list[dict]) -> None:
        """Preserve existing logical Slots and assign only genuinely new devices."""

        used: set[int] = set()
        pending: list[dict] = []
        for entry in selected:
            raw_slot = entry.get("slot")
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                pending.append(entry)
                continue
            if 0 <= slot <= 2 and slot not in used:
                entry["slot"] = slot
                used.add(slot)
            else:
                pending.append(entry)
        available = [slot for slot in range(3) if slot not in used]
        for entry, slot in zip(pending, available, strict=False):
            entry["slot"] = slot

    def _test_all(self) -> None:
        try:
            devices = self._configs()
        except ValueError as exc:
            self._show_wizard_message("ข้อมูลไม่ครบ", str(exc))
            return
        if self._thread is not None:
            return
        self.test_button.setEnabled(False)
        self.test_button.setText("กำลังตรวจสอบเครื่องที่เลือก…")
        thread = QThread(self)
        worker = DeviceTestWorker(
            devices,
            snmp_port=161,
            web_port=443,
            endpoint_ports=self._lab_endpoint_ports(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._test_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._test_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _test_result(self, slot: int, payload: dict) -> None:
        payload = {**payload, "tested": True}
        self.results[slot] = payload
        row = next((index for index, entry in enumerate(self.discovered_devices) if entry.get("slot") == slot), None)
        if row is None:
            return
        entry = self.discovered_devices[row]
        entry["result"] = payload
        entry["model"] = payload.get("model") or entry["model"]
        entry["serial"] = payload.get("serial") or entry["serial"]
        entry["tls_mode"] = payload.get("tls_mode") or entry.get("tls_mode", "system")
        entry["tls_fingerprint"] = payload.get("tls_fingerprint") or entry.get("tls_fingerprint", "")
        self._render_discovered_row(row)
        self._update_device_actions()

    def _test_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.test_button.setEnabled(True)
        self.test_button.setText("ตรวจสอบเครื่องที่เลือก")
        try:
            devices = self._configs()
        except ValueError:
            return
        all_ready = all(
            self.results.get(device.slot, {}).get("online") and self.results[device.slot].get("web_ok")
            for device in devices
        )
        if all_ready:
            if self.lab_mode:
                self.scan_status.setText("Virtual Printer พร้อมใช้งาน · ผ่าน SNMP และ Web แล้ว")
            self._update_device_actions()

    def _update_device_actions(self) -> None:
        selected = self._selected_entries()
        all_ready = bool(selected) and all(
            entry.get("result", {}).get("online")
            and entry.get("result", {}).get("web_ok")
            for entry in selected
        )
        if self.stack.currentIndex() == 1:
            self.next_button.setEnabled(all_ready)
        if self._thread is None:
            self.test_button.setEnabled(bool(selected))
        if all_ready:
            self.scan_status.setText(
                f"พร้อมนำเข้าระบบ {len(selected)} เครื่อง · ผ่าน SNMP และ Web ครบแล้ว"
            )

    def _next(self) -> None:
        index = self.stack.currentIndex()
        if index == 0:
            company_name = " ".join(self.company_name_input.text().split())
            if not company_name:
                self._show_company_name_error()
                return
            self.company_name_input.setText(company_name)
            self.stack.setCurrentIndex(1)
            self.title.setText("นำเครื่องพิมพ์เข้าระบบ")
            self.step_label.setText("2 / 4")
            self.language_switch.setVisible(False)
            self.note.setText("ขั้นที่ 2: ค้นหา เลือก และตรวจสอบเครื่องพิมพ์ก่อนนำเข้าระบบ")
            self._update_progress(1)
            self.back_button.setVisible(True)
            self.test_button.setVisible(True)
            self.next_button.setText("ถัดไป →")
            self._update_device_actions()
            apply_language(self)
            self._sync_language_switch()
            if (
                not self.discovered_devices
                and self._scan_thread is None
                and QApplication.platformName() != "offscreen"
            ):
                QTimer.singleShot(
                    0,
                    lambda: self._scan_network(self.lab_hosts if self.lab_mode else None),
                )
            return
        if index == 1:
            try:
                devices = self._configs()
            except ValueError as exc:
                self._show_wizard_message("ข้อมูลไม่ครบ", str(exc))
                return
            not_ready = [
                device.name
                for device in devices
                if not (self.results.get(device.slot, {}).get("online") and self.results[device.slot].get("web_ok"))
            ]
            if not_ready:
                self._show_wizard_message(
                    "ยังทดสอบไม่ผ่าน",
                    "ทุกเครื่องที่เลือกต้องผ่านทั้ง SNMP และ Web Connection ก่อนดำเนินการ:\n"
                    + "\n".join(f"• {name}" for name in not_ready),
                )
                return
            if QApplication.platformName() != "offscreen":
                self._name_selected_devices(on_complete=self._enter_price_step)
                return
            self._enter_price_step()
            return
        if index == 2:
            if self._all_selected_prices_are_zero() and not self.deferred_price_mode.isChecked():
                self._show_wizard_message(
                    "ราคายังเป็น 0.00 ทั้งหมด",
                    "กรุณากรอกราคาอย่างน้อยหนึ่งรายการ หรือเลือก ‘ตั้งค่าราคาภายหลัง’ "
                    "เพื่อยืนยันว่าขณะนี้ยังไม่คิดค่าใช้จ่าย",
                )
                self.deferred_price_mode.setFocus()
                return
            self._update_review()
            self.stack.setCurrentIndex(3)
            self.title.setText("ตรวจสอบและเริ่มใช้งาน")
            self.step_label.setText("4 / 4")
            self.note.setText("ขั้นที่ 4: ตรวจสอบแต่ละส่วนก่อนนำเครื่องพิมพ์เข้าระบบ")
            self._update_progress(3)
            self.next_button.setText("จบการทดสอบ" if self.lab_mode else "บันทึกและเปิดโปรแกรม")
            apply_language(self)
            self._sync_language_switch()
            return
        if index == 3:
            self._save()

    def _enter_price_step(self) -> None:
        self.stack.setCurrentIndex(2)
        self._refresh_device_price_cards()
        self.test_button.setVisible(False)
        self.title.setText("ตั้งค่าราคา")
        self.step_label.setText("3 / 4")
        self.note.setText(
            "ขั้นที่ 3: ตั้งราคาตอนนี้ หรือเลือกตั้งค่าภายหลังอย่างชัดเจน"
        )
        self._update_progress(2)
        self.back_button.setVisible(True)
        self.next_button.setText("ตรวจสอบการตั้งค่า →")
        self.next_button.setEnabled(True)
        apply_language(self)
        self._sync_language_switch()

    def _back(self) -> None:
        index = self.stack.currentIndex()
        if index <= 0:
            return
        self.stack.setCurrentIndex(index - 1)
        titles = ("ข้อมูลองค์กร", "นำเครื่องพิมพ์เข้าระบบ", "ตั้งค่าราคา")
        button_text = ("ค้นหาเครื่องพิมพ์ →", "ถัดไป →", "ตรวจสอบการตั้งค่า →")
        notes = (
            "ขั้นที่ 1: กรอกชื่อบริษัท · วันที่เริ่มใช้และ Version มาจากระบบอัตโนมัติ",
            "ขั้นที่ 2: ค้นหา เลือก และตรวจสอบเครื่องพิมพ์ก่อนนำเข้าระบบ",
            "ขั้นที่ 3: ตั้งราคาตอนนี้ หรือเลือกตั้งค่าภายหลังอย่างชัดเจน",
        )
        self.title.setText(titles[index - 1])
        self.step_label.setText(f"{index} / 4")
        self.note.setText(notes[index - 1])
        self._update_progress(index - 1)
        self.back_button.setVisible(index - 1 > 0)
        self.test_button.setVisible(index - 1 == 1)
        self.language_switch.setVisible(index - 1 == 0)
        self.next_button.setText(button_text[index - 1])
        self.next_button.setEnabled(True)
        if index - 1 == 1:
            self._update_device_actions()
        apply_language(self)
        self._sync_language_switch()

    def _update_review(self) -> None:
        devices = self._configs()
        shared = self.shared_price_mode.isChecked()
        deferred = self.deferred_price_mode.isChecked()
        company = escape(self.company_name_input.text().strip())
        self.review_sections["organization"].setText(
            f"<b>{company}</b> · เริ่มใช้งาน {escape(self.first_started_input.text())} · "
            f"Version {escape(PACKAGE_VERSION)}"
        )
        device_lines: list[str] = []
        for device in devices:
            meter = self.results.get(device.slot, {}).get("total")
            meter_text = f"{meter:,.0f}" if isinstance(meter, (int, float)) else "—"
            device_lines.append(
                f"<b>{escape(device.name)}</b> · {escape(device.model or 'ไม่ทราบรุ่น')} · "
                f"พร้อมใช้งาน · Meter {meter_text}"
            )
        self.review_sections["devices"].setText("<br>".join(device_lines))

        if deferred:
            pricing_text = (
                "<b>ตั้งค่าภายหลัง</b> · ขณะนี้ราคา 0.00 ทุกประเภทและยังไม่คิดค่าใช้จ่าย"
            )
        elif shared:
            pricing_text = (
                f"<b>ใช้ราคาเดียวกันทุกเครื่อง</b> · เริ่มใช้ "
                f"{self.effective_date.date().toString('dd/MM/yyyy')}<br>"
                f"{self._price_summary(self.shared_price_row)}"
            )
        else:
            price_lines = [
                f"<b>ราคาแยกรายเครื่อง</b> · เริ่มใช้ "
                f"{self.effective_date.date().toString('dd/MM/yyyy')}"
            ]
            for device in devices:
                price_lines.append(
                    f"{escape(device.name)}: {self._price_summary(self.price_rows[device.slot])}"
                )
            pricing_text = "<br>".join(price_lines)
        self.review_sections["pricing"].setText(pricing_text)

        if self.edit_mode:
            billing_text = "รอบบิลและส่วนลดจัดการจากหน้า Settings โดยไม่เปลี่ยนตาม Wizard นี้"
        elif deferred:
            billing_text = "ยังไม่เริ่มคิดค่าใช้จ่าย · ตั้งราคาและรอบบิลภายหลังได้จาก Settings"
        else:
            billing_text = (
                f"ส่วนลดกระดาษเสีย {self.waste_paper_pct.value():g}% · "
                f"สิ้นสุดรอบวันที่ {self._billing_day()} ของเดือน"
            )
        self.review_sections["billing"].setText(billing_text)
        platform_name, architecture = runtime_platform()
        if platform_name == "Darwin":
            platform_name = "macOS"
        model_rows = normalize_device_models(device.model for device in devices)
        model_text = ", ".join(
            f"{escape(str(row['model']))} × {row['quantity']}" for row in model_rows
        ) or "—"
        online_mode = self.registration_online_mode.isChecked()
        delivery_copy = (
            f"<b>{tr('Online Registration:', 'Online Registration:')}</b> "
            f"{tr('ลงทะเบียนอัตโนมัติและส่ง Status กับ Aggregate Total Meter ทุก 6 ชั่วโมงโดยประมาณ', 'automatic registration with Status and aggregate Total Meter about every 6 hours')}<br>"
            if online_mode
            else f"<b>{tr('Offline License:', 'Offline License:')}</b> "
            f"{tr('ไม่ส่ง Registration, Status หรือ Meter ไปยัง Host', 'no Registration, Status, or Meter telemetry is sent to the Host')}<br>"
        )
        self.review_sections["registration"].setText(
            delivery_copy
            + f"<b>{tr('ข้อมูลที่อนุญาตเมื่อใช้ Online:', 'Allowed data in Online mode:')}</b> "
            f"{tr('ชื่อบริษัท:', 'Company:')} {company} · Version {escape(PACKAGE_VERSION)} · "
            f"{escape(platform_name)} / {escape(architecture)} · "
            f"{tr('Serial Number + รุ่นเครื่อง + สถานะเลือกใช้ + Aggregate Total Meter', 'serial number + printer model + selected state + aggregate Total Meter')} "
            f"({model_text})<br>"
            f"<b>{tr('ไม่ส่ง:', 'Never sent:')}</b> "
            f"{tr('IP, MAC, hostname, Credential, Counter รายละเอียด, ผู้ใช้, เอกสาร, Print Job, Raw SNMP/XML/Error หรือ Log', 'IP, MAC, hostname, credentials, detailed counters, users, documents, print jobs, raw SNMP/XML/errors, or logs')}<br>"
            f"<b>{tr('การแจ้งเตือน:', 'Alerts:')}</b> "
            f"{tr('Host อาจแจ้งว่า Desktop ขาดการเชื่อมต่อหลัง 3 วัน; ข้อความนี้ไม่ใช่หลักฐานว่าเครื่องพิมพ์เสีย', 'the Host may report Desktop connectivity loss after 3 days; this is not proof of a printer fault')}"
        )
        if not online_mode:
            self.registration_status_label.setText(tr("Offline License", "Offline License"))
        elif self.privacy_notice_accepted.isChecked():
            self.registration_status_label.setText(
                tr("รอบันทึก", "Pending")
            )
        else:
            self.registration_status_label.setText(tr("รอยอมรับ", "Accept"))
        apply_language(self)
        self._sync_language_switch()

    @staticmethod
    def _price_summary(inputs: dict[str, QDoubleSpinBox]) -> str:
        return (
            f"A4 สี <b>{inputs['a4_color'].value():,.2f}</b> · "
            f"A4 ขาวดำ <b>{inputs['a4_bw'].value():,.2f}</b> · "
            f"A3 สี <b>{inputs['a3_color'].value():,.2f}</b> · "
            f"A3 ขาวดำ <b>{inputs['a3_bw'].value():,.2f}</b> บาท/หน้า"
        )

    def _save(self) -> None:
        try:
            company_name = " ".join(self.company_name_input.text().split())
            if not company_name:
                raise ValueError("กรุณากรอกชื่อบริษัท")
            registration_mode = (
                "offline" if self.registration_offline_mode.isChecked() else "online"
            )
            if registration_mode == "online" and not self.privacy_notice_accepted.isChecked():
                self._show_wizard_message(
                    tr("กรุณารับทราบข้อมูล", "Acknowledge the Data Notice"),
                    tr(
                        "รับทราบประกาศข้อมูลการลงทะเบียน หรือเลือก Offline License ก่อนบันทึก",
                        "Acknowledge the Registration Data Notice or select Offline License before saving.",
                    ),
                )
                self.privacy_notice_accepted.setFocus()
                return
            devices = self._configs()
            if self.lab_mode:
                self.accept()
                return
            self._activate_selected_database_path()
            self.repository.replace_all(devices)
            effective = self.effective_date.date().toPyDate()
            shared = self.shared_price_mode.isChecked()
            deferred = self.deferred_price_mode.isChecked()
            for device in devices:
                row = self.shared_price_row if shared else self.price_rows[device.slot]
                self.pricing.set_prices(
                    device.slot,
                    effective,
                    PriceList(
                        **{
                            key: 0.0 if deferred else spin.value()
                            for key, spin in row.items()
                        }
                    ),
                )
            set_cfg(
                "pricing_mode",
                "deferred" if deferred else ("shared" if shared else "per_device"),
            )
            if not self.edit_mode:
                set_cfg("billing_day", str(self._billing_day()))
                set_cfg("waste_paper_pct", str(round(self.waste_paper_pct.value(), 1)))
            set_cfg("work_start", get_cfg("work_start", "08:00") or "08:00")
            set_cfg("work_end", get_cfg("work_end", "17:00") or "17:00")
            set_cfg("snmp_interval_minutes", "5")
            set_cfg("db_path", str(get_db_path()))
            set_cfg("company_name", company_name)
            if not get_cfg("client_first_started_at", ""):
                set_cfg("client_first_started_at", date.today().isoformat())
            installation_id = get_cfg("installation_id", "") or str(uuid4())
            set_cfg("installation_id", installation_id)
            set_cfg("v52_registration_mode", registration_mode)
        except Exception as exc:
            self._show_wizard_message("บันทึกไม่สำเร็จ", str(exc))
            return

        # Registration is intentionally second and local-only: configuration
        # failure must never roll back Device, Billing, History, or Report data.
        # The lifecycle coordinator queues schema 3 after the Wizard closes;
        # no transport is called from the dialog.
        try:
            self.registration_state.configure(
                registration_mode,
                company_name,
                installation_id,
                get_cfg("client_first_started_at", "") or date.today().isoformat(),
                DRAFT_NOTICE_VERSION if registration_mode == "online" else "",
                (
                    datetime.now().astimezone().isoformat(timespec="seconds")
                    if registration_mode == "online"
                    else ""
                ),
            )
            set_cfg("registration_pending_envelope", "")
            set_cfg("registration_status", "v52_configured")
        except Exception:
            set_cfg("registration_pending_envelope", "")
            set_cfg("registration_status", "action_required")
        self.accept()

    def _billing_day(self) -> int:
        return int(self.billing_end_day.currentData() or DEFAULT_BILLING_DAY)

    def _all_selected_prices_are_zero(self) -> bool:
        if self.deferred_price_mode.isChecked():
            return True
        if self.shared_price_mode.isChecked():
            rows = (self.shared_price_row,)
        else:
            selected_slots = {device.slot for device in self._configs()}
            rows = tuple(self.price_rows[slot] for slot in sorted(selected_slots))
        return all(spin.value() == 0 for row in rows for spin in row.values())


class PageDeviceOverview(QWidget):
    def __init__(self, repository: DeviceConfigRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self.cache = DailyCacheStore()
        self.mode = "usage"
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        header = QHBoxLayout()
        self.title = QLabel("Usage รอบบิลปัจจุบัน")
        self.title.setFont(fnt(F_2XL, True))
        header.addWidget(self.title)
        header.addStretch()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Usage รอบนี้", "usage")
        self.mode_combo.addItem("Counter สะสมล่าสุด", "latest")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        header.addWidget(self.mode_combo)
        self.refresh_button = btn("อ่านค่าทันที", "outline")
        header.addWidget(self.refresh_button)
        root.addLayout(header)
        self.period_label = QLabel("")
        self.period_label.setStyleSheet(f"color:{C_TEXT2};")
        root.addWidget(self.period_label)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        root.addLayout(self.grid)
        self.cost_summary = QLabel("")
        self.cost_summary.setStyleSheet("background:#EEF6F9;color:#245268;padding:12px;font-weight:700;")
        root.addWidget(self.cost_summary)
        root.addStretch()

    def _mode_changed(self) -> None:
        self.mode = self.mode_combo.currentData()
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        devices = self.repository.list(enabled_only=True)
        start, end = billing_period()
        self.period_label.setText(f"รอบบิล {start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')} · SNMP ทุก 5 นาที")
        columns = max(1, min(3, len(devices)))
        try:
            pinned = json.loads(get_cfg("pinned_counters_json", "[]") or "[]")
        except json.JSONDecodeError:
            pinned = []
        for index, device in enumerate(devices):
            counters = current_period_counters(device.slot) if self.mode == "usage" else latest_counters(device.slot)
            groups = default_usage_groups(counters)
            card = QFrame()
            card.setObjectName("card")
            card.setStyleSheet(f"QFrame#card{{border:1px solid {C_BORDER};border-top:4px solid {SLOT_COLORS[device.slot]};border-radius:8px;}}")
            layout = QVBoxLayout(card)
            cap = QHBoxLayout()
            name = QLabel(device.name)
            name.setFont(fnt(F_MD, True))
            cap.addWidget(name)
            cap.addStretch()
            status = QLabel("● Online" if device.connection_status == "online" else "● Offline")
            status.setStyleSheet(f"color:{C_GREEN if device.connection_status == 'online' else C_RED};")
            cap.addWidget(status)
            layout.addLayout(cap)
            identity = QLabel(f"{device.model or 'Model —'} · {device.serial or 'Serial —'}")
            identity.setStyleSheet(f"color:{C_TEXT2};")
            layout.addWidget(identity)
            latest = device.last_success_at or device.last_checked_at or "ยังไม่มีข้อมูล"
            last_label = QLabel(f"ข้อมูลล่าสุด: {latest}")
            last_label.setStyleSheet(f"color:{C_TEXT2};font-size:11px;")
            layout.addWidget(last_label)
            if self.mode == "usage":
                cache_state = self.cache.load(device.slot, end)
                if cache_state and cache_state.get("first_success"):
                    first_success = str(cache_state["first_success"])
                    try:
                        first_success = first_success[11:16]
                    except (IndexError, TypeError):
                        pass
                    baseline = QLabel(
                        f"เริ่มนับ Usage วันนี้ {first_success} น. · รอบแรกเป็น baseline\n"
                        "เลือก ‘Counter สะสมล่าสุด’ เพื่อดูยอดที่อยู่ในเครื่อง"
                    )
                    baseline.setWordWrap(True)
                    baseline.setStyleSheet("background:#FFF7E8;color:#7A5411;padding:8px;border-radius:5px;font-size:11px;")
                    layout.addWidget(baseline)
            meter_grid = QGridLayout()
            for row, label in enumerate(DEFAULT_USAGE_LABELS):
                meter_grid.addWidget(QLabel(label), row, 0)
                value = groups.get(label)
                number = QLabel("—" if value is None else f"{value:,.0f}")
                number.setAlignment(Qt.AlignmentFlag.AlignRight)
                number.setFont(fnt(F_SM, True))
                meter_grid.addWidget(number, row, 1)
            offset = len(DEFAULT_USAGE_LABELS)
            for extra_row, key in enumerate(pinned, start=offset):
                meter_grid.addWidget(QLabel(key), extra_row, 0)
                number = QLabel(f"{counters.get(key, 0):,.0f}" if key in counters else "—")
                number.setAlignment(Qt.AlignmentFlag.AlignRight)
                number.setFont(fnt(F_SM, True))
                meter_grid.addWidget(number, extra_row, 1)
            layout.addLayout(meter_grid)
            gross = period_gross_cost(device.slot)
            cost = QLabel(f"ค่าใช้จ่ายก่อนส่วนลด: {gross:,.2f} บาท")
            cost.setStyleSheet("color:#18875D;font-weight:700;")
            layout.addWidget(cost)
            more = QPushButton("ดูค่าทั้งหมด")
            more.clicked.connect(lambda _checked=False, d=device, c=counters: AllCountersDialog(f"{d.name} — Counter ทั้งหมด", c, self).exec())
            layout.addWidget(more)
            self.grid.addWidget(card, index // columns, index % columns)
        gross, waste_pct, net = period_net_cost([device.slot for device in devices])
        historical_slots: list[str] = []
        for device in devices:
            configured_identity = current_device_identity(device.slot)
            identities = current_period_counters_by_identity(device.slot)
            if any(
                item.device_identity != configured_identity
                for item in identities
            ):
                historical_slots.append(f"{device.name} (Slot {device.slot + 1})")
        summary = (
            f"รวมก่อนส่วนลด {gross:,.2f} บาท · ส่วนลดกระดาษเสีย {waste_pct:g}% · "
            f"ยอดสุทธิ {net:,.2f} บาท"
        )
        if historical_slots:
            summary += (
                " · ⚠ ยอดรวมรวมเครื่องเดิมใน slot: "
                + ", ".join(historical_slots)
            )
            self.cost_summary.setStyleSheet(
                "background:#FFF4E5;color:#8A4B08;padding:12px;font-weight:700;"
            )
        else:
            self.cost_summary.setStyleSheet(
                "background:#EEF6F9;color:#245268;padding:12px;font-weight:700;"
            )
        self.cost_summary.setText(summary)
        self.title.setText("Usage รอบบิลปัจจุบัน" if self.mode == "usage" else "Counter สะสมล่าสุด")


class PagePipelineLog(QWidget):
    """Live observability for SNMP → Web → RAM cache → daily database."""

    sync_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    STAGES = (
        ("ทุกขั้นตอน", None),
        ("ตรวจสถานะ (SNMP)", "SNMP"),
        ("อ่าน Meter (Web)", "WEB"),
        ("เก็บข้อมูล (RAM / DB)", "RAM_DB"),
        ("กฎระบบ", "POLICY"),
    )

    def __init__(
        self,
        repository: DeviceConfigRepository | None = None,
        cache: DailyCacheStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self.cache = cache or DailyCacheStore()
        self._last_live_signature: tuple[object, ...] | None = None
        self._visible_events: list[PipelineEvent] = []
        self._build()
        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self._refresh_if_visible)
        self.timer.start()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        self.page_title = QLabel("สถานะและประวัติการอ่าน")
        self.page_title.setFont(fnt(F_2XL, True))
        root.addWidget(self.page_title)
        self.page_note = QLabel(
            "เช็กว่าเครื่องใดอ่าน Meter สำเร็จ มีอะไรต้องทำหรือไม่ แล้วค่อยเปิดรายละเอียดเมื่อจำเป็น "
            "· Live Log เก็บเฉพาะรอบที่เปิดโปรแกรมนี้ สูงสุด 5,000 เหตุการณ์"
        )
        self.page_note.setWordWrap(True)
        self.page_note.setStyleSheet(f"color:{C_TEXT2};")
        root.addWidget(self.page_note)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._status_tab(), "สถานะการอ่าน")
        self.tabs.addTab(self._live_tab(), "ประวัติการอ่าน")
        self.tabs.addTab(self._cache_tab(), "ข้อมูลวันนี้")
        self.tabs.addTab(self._timeline_tab(), "การทำงานอัตโนมัติ")
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        root.addWidget(self.tabs, 1)

    def _status_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        top.addWidget(self.status_banner, 1)
        sync_button = btn("อ่านข้อมูลตอนนี้", "primary")
        sync_button.clicked.connect(self.sync_requested.emit)
        top.addWidget(sync_button)
        refresh_button = btn("รีเฟรช", "outline")
        refresh_button.clicked.connect(self.refresh_status)
        top.addWidget(refresh_button)
        layout.addLayout(top)

        schedule_row = QHBoxLayout()
        self.status_schedule = QLabel()
        self.status_schedule.setWordWrap(True)
        self.status_schedule.setStyleSheet(f"color:{C_TEXT2};padding:2px 4px;")
        schedule_row.addWidget(self.status_schedule, 1)
        settings_button = btn("ตั้งเวลาอ่านข้อมูล", "outline")
        settings_button.clicked.connect(self.settings_requested.emit)
        schedule_row.addWidget(settings_button)
        layout.addLayout(schedule_row)

        self.status_rows = QVBoxLayout()
        self.status_rows.setSpacing(10)
        layout.addLayout(self.status_rows)
        layout.addStretch()
        return page

    def _timeline_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.timeline_status = QLabel("")
        self.timeline_status.setWordWrap(True)
        self.timeline_status.setStyleSheet("background:#EEF6F9;color:#245268;padding:10px;font-weight:700;")
        top.addWidget(self.timeline_status, 1)
        refresh_button = btn("Refresh timeline", "outline")
        refresh_button.clicked.connect(self.refresh_timeline)
        top.addWidget(refresh_button)
        layout.addLayout(top)

        schedule_card = QFrame()
        schedule_card.setStyleSheet(
            "QFrame#schedule_timeline_card{background:white;border:1px solid #D6E0EA;border-radius:8px;}"
            "QLabel{background:transparent;border:none;}"
        )
        schedule_card.setObjectName("schedule_timeline_card")
        schedule_layout = QVBoxLayout(schedule_card)
        schedule_layout.setContentsMargins(14, 12, 14, 12)
        schedule_layout.setSpacing(8)
        schedule_heading = QLabel("แผนการอ่านข้อมูลวันนี้")
        schedule_heading.setFont(fnt(F_MD, True))
        schedule_layout.addWidget(schedule_heading)
        self.schedule_summary = QLabel()
        self.schedule_summary.setWordWrap(True)
        self.schedule_summary.setStyleSheet("color:#475569;")
        schedule_layout.addWidget(self.schedule_summary)
        self.schedule_band = QFrame()
        self.schedule_band.setObjectName("schedule_timeline_band")
        self.schedule_band.setStyleSheet("QFrame#schedule_timeline_band{background:transparent;border:none;}")
        self.schedule_band_layout = QHBoxLayout(self.schedule_band)
        self.schedule_band_layout.setContentsMargins(0, 0, 0, 0)
        self.schedule_band_layout.setSpacing(3)
        schedule_layout.addWidget(self.schedule_band)
        self.schedule_notice = QLabel("เป็นแผนที่ตั้งไว้ · ผลการอ่านจริงดูได้จากแท็บ ประวัติการอ่าน")
        self.schedule_notice.setWordWrap(True)
        self.schedule_notice.setStyleSheet("color:#64748B;font-size:12px;")
        schedule_layout.addWidget(self.schedule_notice)
        schedule_actions = QHBoxLayout()
        schedule_actions.addStretch()
        schedule_settings_button = btn("ตั้งเวลาอ่านข้อมูล", "outline")
        schedule_settings_button.clicked.connect(self.settings_requested.emit)
        schedule_actions.addWidget(schedule_settings_button)
        schedule_layout.addLayout(schedule_actions)
        layout.addWidget(schedule_card)

        self.next_poll_label = QLabel("")
        self.next_poll_label.setWordWrap(True)
        self.next_poll_label.setStyleSheet(f"color:{C_TEXT2};padding:2px 4px 8px;")
        layout.addWidget(self.next_poll_label)

        self.timeline_detail_toggle = QCheckBox("แสดงตารางรายละเอียดตามช่วงเวลา")
        self.timeline_detail_toggle.toggled.connect(self._toggle_timeline_detail)
        layout.addWidget(self.timeline_detail_toggle)
        self.timeline_table = QTableWidget(0, 7)
        self.timeline_table.setHorizontalHeaderLabels(
            ["เวลา", "โหมด", "SNMP", "Web Connection", "RAM / Daily Cache", "Database", "หมายเหตุ"]
        )
        self.timeline_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.timeline_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.timeline_table.verticalHeader().setVisible(False)
        self.timeline_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.timeline_table)
        for column, width in enumerate((125, 110, 210, 230, 330, 260, 260)):
            self.timeline_table.setColumnWidth(column, width)
        layout.addWidget(self.timeline_table)
        self.timeline_table.setVisible(False)
        layout.addWidget(self._technical_rules_section())
        layout.addStretch()
        return scroll

    def _live_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.device_filter = QComboBox()
        self.device_filter.addItem("ทุกเครื่อง", None)
        for device in self.repository.list(enabled_only=True):
            self.device_filter.addItem(f"{device.name} ({device.host})", device.slot)
        self.device_filter.currentIndexChanged.connect(self.refresh_live)
        controls.addWidget(self.device_filter)
        self.stage_filter = QComboBox()
        for label, stage in self.STAGES:
            self.stage_filter.addItem(label, stage)
        self.stage_filter.currentIndexChanged.connect(self.refresh_live)
        controls.addWidget(self.stage_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("ค้นหาเหตุผล, counter หรือข้อความในเหตุการณ์...")
        self.search.textChanged.connect(self.refresh_live)
        controls.addWidget(self.search, 1)
        refresh_button = btn("รีเฟรช", "outline")
        refresh_button.clicked.connect(self.refresh_live)
        controls.addWidget(refresh_button)
        copy_button = btn("คัดลอก", "outline")
        copy_button.clicked.connect(self._copy_live)
        controls.addWidget(copy_button)
        clear_button = btn("ล้าง Live Log", "outline")
        clear_button.clicked.connect(self._clear_live)
        controls.addWidget(clear_button)
        layout.addLayout(controls)

        self.live_count = QLabel("")
        self.live_count.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(self.live_count)
        self.live_table = QTableWidget(0, 4)
        self.live_table.setHorizontalHeaderLabels(
            ["เวลา", "เครื่อง", "ผลลัพธ์", "รายละเอียด"]
        )
        self.live_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.live_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.live_table.verticalHeader().setVisible(False)
        self.live_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.live_table)
        for column, width in enumerate((150, 200, 120, 520)):
            self.live_table.setColumnWidth(column, width)
        layout.addWidget(self.live_table, 1)
        self.live_detail = QPlainTextEdit()
        self.live_detail.setReadOnly(True)
        self.live_detail.setPlaceholderText("คลิกเหตุการณ์เพื่อดู Stage, endpoint และรายละเอียดเชิงเทคนิค")
        self.live_detail.setMinimumHeight(92)
        self.live_detail.setMaximumHeight(132)
        self.live_detail.setStyleSheet(
            "background:#F8FAFC;border:1px solid #D6E0EA;border-radius:6px;padding:7px;color:#334155;"
        )
        self.live_table.cellClicked.connect(self._show_live_detail)
        self.live_table.itemActivated.connect(
            lambda item: self._show_live_detail(item.row(), item.column())
        )
        layout.addWidget(self.live_detail)
        return page

    def _cache_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        hint = QLabel(
            "ข้อมูลที่อ่านวันนี้พักอยู่ใน Cache ก่อนปิดเป็น Daily Record เมื่อเปลี่ยนวัน "
            "· รายละเอียด raw อยู่ในคอลัมน์ด้านขวาเพื่อใช้ตรวจสอบ"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("background:#EEF6F9;color:#245268;padding:10px;")
        layout.addWidget(hint)
        refresh_button = btn("รีเฟรชข้อมูลวันนี้", "outline")
        refresh_button.clicked.connect(self.refresh_cache)
        layout.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignRight)
        self.cache_table = QTableWidget(0, 13)
        self.cache_table.setHorizontalHeaderLabels(
            [
                "เครื่อง / IP",
                "วันที่",
                "SNMP reads",
                "Web saves",
                "Opening Total",
                "Latest Total",
                "Daily Delta",
                "SNMP Total OID",
                "Errors",
                "First / Last success",
                "Cache status",
                "DB ล่าสุด",
                "Rollup status",
            ]
        )
        self.cache_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cache_table.verticalHeader().setVisible(False)
        self.cache_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.cache_table)
        for column, width in enumerate((190, 100, 90, 90, 110, 110, 100, 290, 70, 230, 130, 120, 190)):
            self.cache_table.setColumnWidth(column, width)
        layout.addWidget(self.cache_table, 1)
        return page

    def _technical_rules_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("sync_technical_section")
        section.setStyleSheet(
            "QFrame#sync_technical_section{background:white;border:1px solid #D6E0EA;border-radius:8px;}"
            "QLabel{background:transparent;border:none;}"
        )
        layout = QVBoxLayout(section)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        title = QLabel("รายละเอียดทางเทคนิค")
        title.setFont(fnt(F_MD, True))
        layout.addWidget(title)
        note = QLabel("กฎที่ใช้อยู่จริงสำหรับ Scheduler, Web Meter, Cache และการปิดข้อมูลรายวัน")
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748B;")
        layout.addWidget(note)
        self.rules_table = QTableWidget(0, 3)
        self.rules_table.setHorizontalHeaderLabels(["ขั้นตอน", "ค่าปัจจุบัน", "เงื่อนไข / ผลลัพธ์"])
        self.rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self._stabilize_table(self.rules_table)
        self.rules_table.setColumnWidth(0, 220)
        self.rules_table.setColumnWidth(1, 260)
        layout.addWidget(self.rules_table)
        return section

    @staticmethod
    def _stabilize_table(table: QTableWidget) -> None:
        """Keep every row on the same text origin and avoid Qt alternate-state jitter."""
        table.setAlternatingRowColors(False)
        table.setWordWrap(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setFixedHeight(40)

    @staticmethod
    def _align_log_item(item: QTableWidgetItem, row: int, *, centered: bool = False) -> None:
        alignment = Qt.AlignmentFlag.AlignCenter if centered else Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        if row % 2:
            item.setBackground(QColor("#F7F8FA"))

    def _refresh_if_visible(self) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        if self.tabs.currentIndex() == 0:
            self.refresh_status()
        elif self.tabs.currentIndex() == 1:
            self.refresh_live()
        elif self.tabs.currentIndex() == 2:
            self.refresh_cache()
        else:
            self.refresh_timeline()

    @staticmethod
    def _display_time(value: str | None) -> str:
        if not value:
            return "ยังไม่มีข้อมูล"
        try:
            return datetime.fromisoformat(value).strftime("%d/%m %H:%M") + " น."
        except ValueError:
            return value.replace("T", " ")

    def _next_poll_for_device(self, device: DeviceConfig, now: datetime, snmp_minutes: int) -> str:
        start_actions = {"เริ่มรอบตาม Schedule", "เริ่มรอบอ่านทันที"}
        latest = next(
            (
                event
                for event in pipeline_log.snapshot(limit=2_000)
                if event.device_slot == device.slot and event.action in start_actions
            ),
            None,
        )
        if latest is None:
            if device.last_checked_at or device.last_success_at:
                return "ระบบจะตรวจ SNMP ตามรอบที่กำหนด"
            return "รอ Scheduler เริ่มรอบแรก หรือกดอ่านข้อมูลตอนนี้"
        try:
            due = datetime.fromisoformat(latest.at) + timedelta(minutes=snmp_minutes)
        except ValueError:
            return "รอ Scheduler รอบถัดไป"
        if due <= now:
            return "ถึงเวลาตรวจแล้ว · กำลังรอ Timer/คิว"
        return f"SNMP รอบถัดไปประมาณ {due.strftime('%H:%M')} น."

    @staticmethod
    def _plain_error(value: str) -> str:
        lowered = value.lower()
        if "timeout" in lowered:
            return "เชื่อมต่อเครื่องไม่สำเร็จภายในเวลาที่กำหนด"
        if "credential" in lowered or "unauthorized" in lowered or "login" in lowered:
            return "ตรวจสอบ Administrator credential ของเครื่องนี้"
        if "tls" in lowered or "ssl" in lowered:
            return "เชื่อมต่อ Web Connection ของเครื่องไม่สำเร็จ"
        return "อ่านข้อมูลจากเครื่องไม่สำเร็จ · ดูรายละเอียดเพื่อส่งให้ทีม Support"

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _open_device_events(self, slot: int) -> None:
        self.tabs.setCurrentIndex(1)
        index = self.device_filter.findData(slot)
        if index >= 0:
            self.device_filter.setCurrentIndex(index)
        self.refresh_live()

    def _status_for_device(
        self,
        device: DeviceConfig,
        state: dict | None,
        events: list[PipelineEvent],
        now: datetime,
        snmp_minutes: int,
    ) -> tuple[str, str, str, str, str]:
        latest_success = device.last_success_at or (state or {}).get("last_success")
        error_event = next(
            (event for event in events if event.device_slot == device.slot and event.status == "error"),
            None,
        )
        review_event = next(
            (
                event
                for event in events
                if event.device_slot == device.slot
                and event.status == "warning"
                and ("review" in event.action.lower() or "reconciliation" in event.action.lower())
            ),
            None,
        )
        status = (device.connection_status or "pending").lower()
        if status == "offline" or device.last_error or error_event:
            raw_reason = device.last_error or (error_event.value if error_event else "")
            return (
                "เชื่อมต่อไม่ได้",
                self._plain_error(raw_reason),
                "#B42318",
                "ตรวจ IP หรือ Credential แล้วกดอ่านข้อมูลตอนนี้",
                latest_success or "",
            )
        if review_event:
            return (
                "ต้องตรวจสอบ",
                "ข้อมูล Meter ต้องตรวจสอบก่อนนำไปใช้คิดค่าใช้จ่าย",
                "#B54708",
                "เปิดประวัติการอ่านและข้อมูลวันนี้เพื่อตรวจรายละเอียด",
                latest_success or "",
            )
        if status == "syncing":
            return ("กำลังอ่านข้อมูล", "ระบบกำลังอ่าน Meter ของเครื่องนี้", "#1769AA", "รอผลการอ่าน", latest_success or "")
        if not latest_success:
            return (
                "รอรอบแรก",
                "ยังไม่มีการอ่าน Web Meter ที่สำเร็จในรอบนี้",
                "#64748B",
                self._next_poll_for_device(device, now, snmp_minutes),
                "",
            )
        return (
            "ปกติ",
            f"Web Meter ล่าสุด {self._display_time(latest_success)}",
            C_GREEN,
            self._next_poll_for_device(device, now, snmp_minutes),
            latest_success,
        )

    def refresh_status(self) -> None:
        now = datetime.now().astimezone()
        snmp_minutes = max(1, int(get_cfg("snmp_interval_minutes", "5") or 5))
        policy = self._policy()
        mode = schedule_mode_at(now.timetz().replace(tzinfo=None), policy)
        devices = self.repository.list(enabled_only=True)
        events = pipeline_log.snapshot(limit=2_000)
        rows: list[tuple[DeviceConfig, tuple[str, str, str, str, str]]] = []
        for device in devices:
            rows.append((device, self._status_for_device(device, self.cache.load(device.slot, date.today()), events, now, snmp_minutes)))
        issues = sum(
            status in {"เชื่อมต่อไม่ได้", "ต้องตรวจสอบ"}
            for _device, (status, *_rest) in rows
        )
        waiting = sum(
            status in {"รอรอบแรก", "กำลังอ่านข้อมูล"}
            for _device, (status, *_rest) in rows
        )
        if not devices:
            headline = "ยังไม่มีเครื่องที่เปิดใช้งาน · ไปที่ตั้งค่าเพื่อเพิ่มเครื่องพิมพ์"
            style = "background:#FFF4E5;color:#8A4B08;border:1px solid #F4C98B;padding:11px 13px;font-weight:700;"
        elif issues:
            headline = f"ต้องตรวจสอบ {issues}/{len(devices)} เครื่อง · ดูคำแนะนำในแต่ละรายการด้านล่าง"
            style = "background:#FFF4E5;color:#8A4B08;border:1px solid #F4C98B;padding:11px 13px;font-weight:700;"
        elif waiting:
            headline = f"กำลังเริ่มต้นการอ่าน · {waiting}/{len(devices)} เครื่องรอ Scheduler หรือกำลังอ่าน Meter"
            style = "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;padding:11px 13px;font-weight:700;"
        else:
            headline = f"ทุกเครื่องปกติ · {len(devices)} เครื่อง · Web Meter ล่าสุดตามรายการด้านล่าง"
            style = "background:#EDF8F2;color:#16875D;border:1px solid #B8DFC9;padding:11px 13px;font-weight:700;"
        self.status_banner.setText(headline)
        self.status_banner.setStyleSheet(style)
        self.status_schedule.setText(
            f"ตอนนี้อยู่ในช่วง {mode} · SNMP ทุก {snmp_minutes} นาที · "
            "รายละเอียดแผนงานอยู่ที่แท็บ การทำงานอัตโนมัติ"
        )
        self._clear_layout(self.status_rows)
        for device, (status, description, colour, next_action, _latest_success) in rows:
            card = QFrame()
            card.setStyleSheet(
                "QFrame{background:white;border:1px solid #D6E0EA;border-radius:8px;}"
                "QLabel{background:transparent;border:none;}"
            )
            body = QHBoxLayout(card)
            body.setContentsMargins(15, 12, 14, 12)
            body.setSpacing(12)
            copy = QVBoxLayout()
            name = QLabel(f"{device.name}  ·  {device.host}")
            name.setFont(fnt(F_MD, True))
            copy.addWidget(name)
            detail = QLabel(description)
            detail.setWordWrap(True)
            detail.setStyleSheet("color:#475569;")
            copy.addWidget(detail)
            action = QLabel(next_action)
            action.setWordWrap(True)
            action.setStyleSheet("color:#64748B;")
            copy.addWidget(action)
            body.addLayout(copy, 1)
            marker = QLabel(status)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setMinimumWidth(106)
            marker.setStyleSheet(f"color:{colour};font-weight:700;padding:7px 8px;")
            body.addWidget(marker)
            details_button = btn("ดูรายละเอียด", "outline")
            details_button.clicked.connect(lambda _checked=False, slot=device.slot: self._open_device_events(slot))
            body.addWidget(details_button)
            self.status_rows.addWidget(card)
        apply_language(self)

    @staticmethod
    def _clock(value: str, fallback: time) -> time:
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
            return time(hour, minute)
        except (TypeError, ValueError):
            return fallback

    def _policy(self) -> PollingPolicy:
        return PollingPolicy(
            web_interval=timedelta(minutes=max(1, int(get_cfg("web_interval_minutes", "15") or 15))),
            peak_web_interval=timedelta(
                minutes=max(1, int(get_cfg("peak_web_interval_minutes", "5") or 5))
            ),
            work_start=self._clock(get_cfg("work_start", "08:00") or "08:00", time(8, 0)),
            work_end=self._clock(get_cfg("work_end", "17:00") or "17:00", time(17, 0)),
            schedule_windows=load_schedule_windows(get_cfg("sync_schedule_windows", "")),
        )

    def _next_poll_text(self, now: datetime, snmp_minutes: int) -> str:
        events = pipeline_log.snapshot(limit=2_000)
        start_actions = {"เริ่มรอบตาม Schedule", "เริ่มรอบอ่านทันที"}
        lines: list[str] = []
        for device in self.repository.list(enabled_only=True):
            latest = next(
                (
                    event
                    for event in events
                    if event.device_slot == device.slot and event.action in start_actions
                ),
                None,
            )
            if latest is None:
                lines.append(f"{device.name}: รอ Scheduler เริ่มรอบแรก")
                continue
            due = datetime.fromisoformat(latest.at) + timedelta(minutes=snmp_minutes)
            if due <= now:
                lines.append(f"{device.name}: ถึงเวลาตรวจแล้ว กำลังรอ Timer/คิว")
            else:
                lines.append(f"{device.name}: SNMP รอบถัดไปประมาณ {due.strftime('%H:%M:%S')} น.")
        return " · ".join(lines) or "ยังไม่มีเครื่องที่เปิดใช้งาน"

    def refresh_timeline(self) -> None:
        now = datetime.now().astimezone()
        policy = self._policy()
        snmp_minutes = max(1, int(get_cfg("snmp_interval_minutes", "5") or 5))
        rows = build_daily_timeline(policy, snmp_minutes=snmp_minutes)
        mode = schedule_mode_at(now.timetz().replace(tzinfo=None), policy)
        self.timeline_status.setText(
            f"วันนี้ {now.strftime('%d/%m/%Y')} · ตอนนี้ {now.strftime('%H:%M:%S')} น. · โหมด {mode} · "
            f"SNMP ทุก {snmp_minutes} นาที"
        )
        self._render_schedule_band(rows, policy, now, snmp_minutes)
        self.next_poll_label.setText(self._next_poll_text(now, snmp_minutes))
        self.timeline_table.setRowCount(len(rows))
        current_clock = now.hour * 60 + now.minute
        for row, entry in enumerate(rows):
            values = (
                entry.time_range,
                entry.mode,
                entry.snmp,
                entry.web,
                entry.ram,
                entry.database,
                entry.note,
            )
            active = self._range_contains(entry.time_range, current_clock)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if active:
                    item.setBackground(QColor("#E8F7F0"))
                    if column in (0, 1):
                        item.setForeground(QColor(C_GREEN))
                elif row % 2:
                    item.setBackground(QColor("#F7F8FA"))
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignCenter if column in (0, 1) else Qt.AlignmentFlag.AlignLeft)
                    | Qt.AlignmentFlag.AlignVCenter
                )
                self.timeline_table.setItem(row, column, item)
        self.refresh_rules()
        apply_language(self)

    def _toggle_timeline_detail(self, visible: bool) -> None:
        self.timeline_table.setVisible(visible)

    @staticmethod
    def _timeline_duration(label: str) -> int:
        if "–" not in label:
            return 1
        try:
            start_text, end_text = label.split("–", 1)
            start_hour, start_minute = (int(value) for value in start_text.split(":", 1))
            end_hour, end_minute = (int(value) for value in end_text.split(":", 1))
            return max(1, (end_hour * 60 + end_minute) - (start_hour * 60 + start_minute) + 1)
        except ValueError:
            return 1

    def _render_schedule_band(
        self,
        rows: tuple[DailyTimelineEntry, ...],
        policy: PollingPolicy,
        now: datetime,
        snmp_minutes: int,
    ) -> None:
        while self.schedule_band_layout.count():
            item = self.schedule_band_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        current_clock = now.hour * 60 + now.minute
        self.schedule_summary.setText(
            f"00:00 — 24:00 · SNMP ทุก {snmp_minutes} นาที · "
            f"Web ช่วงปกติทุก {int(policy.web_interval.total_seconds() // 60)} นาที"
        )
        peak_index = 0
        for entry in rows[1:]:
            active = self._range_contains(entry.time_range, current_clock)
            if entry.mode == "Normal":
                background, border, title = "#F1F5F9", "#CBD5E1", "Normal"
            elif entry.mode == "Peak":
                peak_index += 1
                title = "ช่วงเริ่มงาน" if peak_index == 1 else "ช่วงเลิกงาน"
                background, border = "#E8F0FE", "#B7CAE8"
            else:
                background, border, title = "#E8F7F0", "#A9D8BC", entry.mode
            if active:
                border = C_GREEN
            segment = QFrame()
            segment.setStyleSheet(
                f"QFrame{{background:{background};border:1px solid {border};border-radius:5px;}}"
                "QLabel{background:transparent;border:none;}"
            )
            segment_layout = QVBoxLayout(segment)
            segment_layout.setContentsMargins(6, 6, 6, 6)
            segment_layout.setSpacing(2)
            span = QLabel(entry.time_range)
            span.setAlignment(Qt.AlignmentFlag.AlignCenter)
            span.setStyleSheet("color:#475569;font-size:11px;")
            segment_layout.addWidget(span)
            name = QLabel(title)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setWordWrap(True)
            name.setFont(fnt(F_SM, True))
            segment_layout.addWidget(name)
            web = QLabel(entry.web.replace("เมื่อ Total เพิ่ม · ", "Web "))
            web.setAlignment(Qt.AlignmentFlag.AlignCenter)
            web.setWordWrap(True)
            web.setStyleSheet("color:#475569;font-size:11px;")
            segment_layout.addWidget(web)
            self.schedule_band_layout.addWidget(segment, self._timeline_duration(entry.time_range))

    @staticmethod
    def _range_contains(label: str, minute: int) -> bool:
        if "–" not in label:
            return False
        start_text, end_text = label.split("–", 1)

        def parse(value: str) -> int:
            hour, minute_value = (int(part) for part in value.split(":", 1))
            return hour * 60 + minute_value

        try:
            return parse(start_text) <= minute <= parse(end_text)
        except ValueError:
            return False

    @staticmethod
    def _event_text(event: PipelineEvent) -> str:
        return " ".join(
            (event.device_name, event.host, event.stage, event.action, event.target, event.value, event.detail, event.status)
        ).lower()

    def refresh_live(self) -> None:
        selected_slot = self.device_filter.currentData()
        selected_stage = self.stage_filter.currentData()
        search = self.search.text().strip().lower()
        events = pipeline_log.snapshot(limit=2_000)
        signature = (
            len(events),
            events[0].sequence if events else 0,
            selected_slot,
            selected_stage,
            search,
        )
        if signature == self._last_live_signature:
            return
        self._last_live_signature = signature
        filtered = [
            event
            for event in events
            if (selected_slot is None or event.device_slot == selected_slot)
            and (
                selected_stage is None
                or (selected_stage == "RAM_DB" and event.stage in {"RAM", "DB"})
                or event.stage == selected_stage
            )
            and (not search or search in self._event_text(event))
        ][:750]
        self._visible_events = filtered
        self.live_table.setRowCount(len(filtered))
        for row, event in enumerate(filtered):
            try:
                display_time = datetime.fromisoformat(event.at).strftime("%d/%m %H:%M:%S")
            except ValueError:
                display_time = event.at.replace("T", " ")
            values = (
                display_time,
                event.device_name or "ระบบ",
                self._event_result(event),
                self._event_summary(event),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 2:
                    item.setForeground(QColor(self._event_colour(event)))
                self._align_log_item(item, row, centered=column == 2)
                self.live_table.setItem(row, column, item)
        self.live_count.setText(
            f"แสดง {len(filtered):,} / {len(events):,} เหตุการณ์ล่าสุด · แถวใหม่อยู่ด้านบน · "
            "คลิกแถวเพื่อดูรายละเอียดเทคนิค"
        )
        if not filtered:
            self.live_detail.clear()
        apply_language(self)

    @staticmethod
    def _event_result(event: PipelineEvent) -> str:
        labels = {
            "ok": "สำเร็จ",
            "error": "ไม่สำเร็จ",
            "warning": "ต้องตรวจสอบ",
            "request": "กำลังอ่าน",
            "skip": "ข้ามรอบ",
        }
        return labels.get(event.status, "ข้อมูลระบบ")

    @staticmethod
    def _event_colour(event: PipelineEvent) -> str:
        return {
            "ok": C_GREEN,
            "error": C_RED,
            "warning": "#B54708",
            "request": "#1769AA",
            "skip": C_TEXT2,
        }.get(event.status, C_TEXT2)

    @staticmethod
    def _event_summary(event: PipelineEvent) -> str:
        summary = event.action
        if event.value and event.value not in {"—", "None"}:
            summary += f" · {event.value}"
        elif event.detail:
            summary += f" · {event.detail}"
        return summary

    def _show_live_detail(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self._visible_events):
            return
        event = self._visible_events[row]
        self.live_detail.setPlainText(
            "\n".join(
                (
                    f"เวลา: {event.at}",
                    f"เครื่อง: {event.device_name or 'ระบบ'} {event.host}".strip(),
                    f"Stage: {event.stage}",
                    f"Action: {event.action}",
                    f"Target: {event.target or '—'}",
                    f"Value: {event.value or '—'}",
                    f"Detail: {event.detail or '—'}",
                )
            )
        )

    def _copy_live(self) -> None:
        rows = ["เวลา\tเครื่อง\tผลลัพธ์\tรายละเอียด"]
        for event in self._visible_events:
            try:
                stamp = datetime.fromisoformat(event.at).strftime("%d/%m %H:%M:%S")
            except ValueError:
                stamp = event.at.replace("T", " ")
            rows.append(
                "\t".join((stamp, event.device_name or "ระบบ", self._event_result(event), self._event_summary(event)))
            )
        QApplication.clipboard().setText("\n".join(rows))

    def _clear_live(self) -> None:
        choice = QMessageBox.question(
            self,
            "ล้าง Live Log",
            "ล้างเฉพาะเหตุการณ์ของรอบที่เปิดโปรแกรมนี้\nไม่กระทบ Meter, Cache หรือ Billing",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        pipeline_log.clear()
        pipeline_log.append(stage="POLICY", action="ล้าง Live Log", target="RAM ring buffer", status="info")
        self._last_live_signature = None
        self.refresh_live()

    @staticmethod
    def _total(payload: dict | None, section: str) -> object:
        values = (payload or {}).get(section, {})
        return values.get("counter.total.total", values.get("counter.total.print_page_total", "—"))

    def refresh_cache(self) -> None:
        devices = self.repository.list(enabled_only=True)
        today = date.today()
        self.cache_table.setRowCount(len(devices))
        with _open(commit=False) as conn:
            latest_rows = {
                device.slot: conn.execute(
                    """SELECT record_date,sample_count,error_count,incomplete,last_success
                       FROM daily_meter_records WHERE device_slot=?
                       ORDER BY record_date DESC LIMIT 1""",
                    (device.slot,),
                ).fetchone()
                for device in devices
            }
        for row, device in enumerate(devices):
            state = self.cache.load(device.slot, today)
            db_row = latest_rows.get(device.slot)
            if state:
                first_last = f"{state.get('first_success') or '—'}\n{state.get('last_success') or '—'}"
                cache_status = f"{state.get('last_status', 'pending')} · RAM+disk"
                record_date = state.get("record_date", today.isoformat())
                heartbeat_count = state.get("heartbeat_count", 0)
                sample_count = state.get("sample_count", 0)
                error_count = state.get("error_count", 0)
            else:
                first_last = "—"
                cache_status = "ยังไม่มี Cache วันนี้"
                record_date = today.isoformat()
                heartbeat_count = sample_count = error_count = 0
            if db_row:
                db_last = f"{db_row[0]} · {db_row[1]} Web"
                db_state = "Packed วันนี้" if db_row[0] == today.isoformat() else (
                    "วันนี้ยังพักใน Cache (ปกติ)" if state else "รอข้อมูลวันนี้"
                )
                if db_row[3]:
                    db_state += " · incomplete"
            else:
                db_last = "ยังไม่มี Daily Record"
                db_state = "วันนี้ยังพักใน Cache" if state else "รอการอ่านสำเร็จ"
            values = (
                f"{device.name}\n{device.host}",
                str(record_date),
                str(heartbeat_count),
                str(sample_count),
                str(self._total(state, "opening")),
                str(self._total(state, "latest")),
                str(self._total(state, "delta")),
                get_cfg(f"snmp_total_oid_{device.slot}", "ยังไม่ Calibrate") or "ยังไม่ Calibrate",
                str(error_count),
                first_last,
                cache_status,
                db_last,
                db_state,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._align_log_item(item, row, centered=column in (1, 2, 3, 8))
                self.cache_table.setItem(row, column, item)
        apply_language(self)

    def refresh_rules(self) -> None:
        work_start = get_cfg("work_start", "08:00") or "08:00"
        work_end = get_cfg("work_end", "17:00") or "17:00"
        rules = (
            ("SNMP heartbeat", f"ทุก {get_cfg('snmp_interval_minutes', '5')} นาที", "อ่าน Total/Model/Serial และเพิ่ม heartbeat_count"),
            ("SNMP Total OID", "Auto-calibrate แยกรุ่น/เครื่อง", "เทียบ SNMP candidates กับ Web counter.total.total; ตรงกันแล้วจึงจำ OID"),
            ("Total ไม่เพิ่ม", "ไม่เรียก Web", "เก็บสถานะ Online และค่าล่าสุดไว้"),
            ("Total เพิ่ม", f"Web throttle {get_cfg('web_interval_minutes', '15')} นาที", "อ่าน Full Counter แล้วเพิ่ม sample_count"),
            ("Peak window", f"{work_start} / {work_end} ±30 นาที", f"ลด Web throttle เหลือ {get_cfg('peak_web_interval_minutes', '5')} นาที"),
            ("SNMP ไม่ตอบ", "Web fallback 5 ครั้ง", "ห่างครั้งละ 5 นาที แล้วเป็น Offline"),
            ("Offline", "ยัง probe SNMP ทุก 5 นาที", "จำกัด Web probe ซ้ำประมาณ 1 ชั่วโมง"),
            ("RAM / Daily Cache", "atomic JSON แยกเครื่อง/วัน", "เก็บ opening, latest, delta, counts และ errors"),
            ("เปลี่ยนวัน", "1 Daily Record / เครื่อง / วัน", "commit DB สำเร็จแล้วจึงลบ Cache วันเก่า"),
            ("ปิดโปรแกรม/เครื่องก่อนจบวัน", "ใช้ค่าล่าสุด", "Daily Record ระบุ incomplete; ไม่ประมาณค่าที่หาย"),
        )
        self.rules_table.setRowCount(len(rules))
        for row, values in enumerate(rules):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._align_log_item(item, row)
                self.rules_table.setItem(row, column, item)


def _flatten_ram(value: object, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_ram(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            rows.extend(_flatten_ram(child, f"{prefix}[{index}]"))
    else:
        rows.append((prefix or "value", "" if value is None else str(value)))
    return rows


class ConnectionInspectorWorker(QObject):
    result = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, device: DeviceConfig) -> None:
        super().__init__()
        self.device = device

    @pyqtSlot()
    def run(self) -> None:
        preferred_oid = get_cfg(f"snmp_total_oid_{self.device.slot}", "") or ""
        probe = SnmpTotalProbe()
        reader = MeterReader(DatabaseCredentialStore(DeviceConfigRepository()))

        def read_snmp() -> tuple[object | None, str, float]:
            started = perf_counter()
            try:
                return probe.read(self.device.host, preferred_oid=preferred_oid), "", perf_counter() - started
            except Exception as exc:
                return None, str(exc), perf_counter() - started

        def read_web() -> tuple[object | None, str, float]:
            started = perf_counter()
            try:
                return reader.read(self.device.host, model=self.device.model), "", perf_counter() - started
            except Exception as exc:
                return None, str(exc), perf_counter() - started

        with ThreadPoolExecutor(max_workers=2) as executor:
            snmp_future = executor.submit(read_snmp)
            web_future = executor.submit(read_web)
            snmp_result, snmp_error, snmp_seconds = snmp_future.result()
            reading, web_error, web_seconds = web_future.result()

        snmp_rows: list[tuple[str, str, str]] = []
        if snmp_result is not None:
            snmp_rows.extend(
                [
                    ("Total Meter", f"{snmp_result.total:,}", snmp_result.total_oid),
                    ("Selected OID", snmp_result.total_oid, "Web-calibrated mapping" if preferred_oid else "candidate selection"),
                    ("Model", snmp_result.model, "Printer-MIB"),
                    ("Serial", snmp_result.serial, "Printer-MIB"),
                ]
            )
            for oid, value in snmp_result.total_candidates:
                snmp_rows.append((f"Candidate: {oid}", f"{value:,}", "ตรงกับ Selected" if oid == snmp_result.total_oid else ""))
        elif snmp_error:
            snmp_rows.append(("ERROR", snmp_error, "SNMP read failed"))

        web_rows: list[tuple[str, str, str]] = []
        if reading is not None:
            for index, counter in enumerate(reading.counters):
                subject = f" · {counter.subject_type}:{counter.subject_id}" if counter.subject_type else ""
                web_rows.append(
                    (
                        f"[{index:03d}] {counter.canonical_field}{subject}",
                        f"{counter.count:,}" if isinstance(counter.count, (int, float)) else str(counter.count),
                        f"{counter.label} · {counter.source_path}",
                    )
                )
        elif web_error:
            web_rows.append(("ERROR", web_error, "Web Connection read failed"))

        ram_rows: list[tuple[str, str, str]] = []
        if reading is not None:
            for counter in reading.counters:
                if counter.subject_type is None:
                    continue
                subject = counter.subject_name or counter.subject_id or "Unknown"
                ram_rows.append(
                    (
                        f"{counter.subject_type}:{subject} · {counter.canonical_field}",
                        f"{counter.count:,}" if isinstance(counter.count, (int, float)) else str(counter.count),
                        f"{counter.label} · {counter.source_path}",
                    )
                )
            if not ram_rows:
                ram_rows.append(("ไม่พบ User Authentication / Account Track", "—", "RAM snapshot"))
        elif web_error:
            ram_rows.append(("ERROR", "ไม่มี User/Account RAM snapshot", web_error))

        web_counters = {
            counter.canonical_field: counter.count
            for counter in reading.counters
            if reading is not None and counter.subject_type is None
        } if reading is not None else {}

        self.result.emit(
            {
                "device": self.device,
                "snmp_rows": snmp_rows,
                "web_rows": web_rows,
                "ram_rows": ram_rows,
                "snmp_seconds": snmp_seconds,
                "web_seconds": web_seconds,
                "snmp_error": snmp_error,
                "web_error": web_error,
                "reconciliation": reconcile_web_counters(web_counters),
            }
        )
        self.finished.emit()


class PageConnectionInspector(QWidget):
    """Temporary raw-data inspector with one fresh snapshot and three columns."""

    def __init__(self, repository: DeviceConfigRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self._thread: QThread | None = None
        self._worker: ConnectionInspectorWorker | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        header = QHBoxLayout()
        title = QLabel("Connection Inspector")
        title.setFont(fnt(F_2XL, True))
        header.addWidget(title)
        header.addStretch()
        self.device_combo = QComboBox()
        header.addWidget(self.device_combo)
        self.mock_mode = QCheckBox("Mock data (ไม่เชื่อมต่อเครื่อง)")
        self.mock_mode.setChecked(True)
        self.mock_mode.toggled.connect(self._mode_changed)
        header.addWidget(self.mock_mode)
        self.read_button = btn("แสดง Mock ตอนนี้", "primary")
        self.read_button.clicked.connect(self._read_now)
        header.addWidget(self.read_button)
        root.addLayout(header)

        explanation = QLabel(
            "SNMP ใช้ดูสถานะเท่านั้น · Web Connection เป็น Device Meter · "
            "RAM แสดง User Authentication / Account Track · ไม่เขียน Daily Cache หรือ Database"
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("background:#EEF6F9;color:#245268;padding:10px;")
        root.addWidget(explanation)
        self.status = QLabel("เลือกเครื่องแล้วกด ‘อ่านข้อมูลตอนนี้’")
        self.status.setStyleSheet(f"color:{C_TEXT2};")
        root.addWidget(self.status)
        self.reconciliation_status = QLabel("รอตรวจผลรวม Web Connection")
        self.reconciliation_status.setWordWrap(True)
        self.reconciliation_status.setStyleSheet("background:#F8FAFC;color:#64748B;padding:9px 12px;")
        root.addWidget(self.reconciliation_status)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.snmp_table, self.snmp_count = self._column(grid, 0, "1 · SNMP Status", "สถานะ/Identity/Total diagnostic · ไม่ใช้คิดเงิน")
        self.web_table, self.web_count = self._column(grid, 1, "2 · Web Connection", "Device Meter และแหล่งข้อมูล Usage/Billing")
        self.ram_table, self.ram_count = self._column(grid, 2, "3 · RAM User/Account", "User Authentication / Account Track เท่านั้น")
        for column in range(3):
            grid.setColumnStretch(column, 1)
        root.addLayout(grid, 1)

    def _mode_changed(self, enabled: bool) -> None:
        self.read_button.setText("แสดง Mock ตอนนี้" if enabled else "อ่านข้อมูลตอนนี้")
        self.status.setText(
            "Mock mode — ใช้ snapshot ล่าสุดโดยไม่เชื่อมต่อเครื่อง"
            if enabled
            else "Live mode — ปุ่มจะเชื่อมต่อ SNMP และ Web Connection จริง"
        )

    def _column(self, grid: QGridLayout, column: int, title: str, subtitle: str) -> tuple[QTableWidget, QLabel]:
        frame = QFrame()
        frame.setObjectName(f"inspectorColumn{column}")
        frame.setStyleSheet(
            f"QFrame#{frame.objectName()}{{border:1px solid {C_BORDER};border-top:4px solid {SLOT_COLORS[column]};border-radius:8px;}}"
        )
        layout = QVBoxLayout(frame)
        heading = QLabel(title)
        heading.setFont(fnt(F_MD, True))
        layout.addWidget(heading)
        hint = QLabel(subtitle)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(hint)
        count = QLabel("0 รายการ")
        count.setStyleSheet(f"color:{C_TEXT2};font-size:11px;")
        layout.addWidget(count)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Key / OID", "Value"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 280)
        layout.addWidget(table, 1)
        grid.addWidget(frame, 0, column)
        return table, count

    def refresh(self) -> None:
        selected = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self.repository.list(enabled_only=True):
            self.device_combo.addItem(f"{device.name} · {device.host}", device.slot)
        if selected is not None:
            index = self.device_combo.findData(selected)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)
        self.read_button.setEnabled(self.device_combo.count() > 0 and self._thread is None)

    def _read_now(self) -> None:
        if self._thread is not None:
            return
        slot = self.device_combo.currentData()
        device = self.repository.get(slot) if slot is not None else None
        if device is None:
            self.status.setText("ไม่พบเครื่องที่เลือก")
            return
        if self.mock_mode.isChecked():
            self._render_mock(device)
            return
        for table, count in (
            (self.snmp_table, self.snmp_count),
            (self.web_table, self.web_count),
            (self.ram_table, self.ram_count),
        ):
            table.setRowCount(0)
            count.setText("กำลังอ่าน…")
        self.status.setText(f"กำลังอ่าน {device.name} ({device.host}) — SNMP และ Web พร้อมกัน…")
        self.read_button.setEnabled(False)
        self.read_button.setText("กำลังอ่าน…")
        thread = QThread(self)
        worker = ConnectionInspectorWorker(device)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._render_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._read_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _render_mock(self, device: DeviceConfig) -> None:
        state = DailyCacheStore().load(device.slot, date.today()) or {}
        latest = state.get("latest") or latest_counters(device.slot)
        selected_oid = get_cfg(f"snmp_total_oid_{device.slot}", "") or SnmpTotalProbe.PRIMARY_TOTAL_OID
        total = latest.get("counter.total.total", device.last_total if device.last_total is not None else 0)
        snmp_rows = [
            ("Total Meter", f"{float(total):,.0f}", "MOCK จาก snapshot ล่าสุด"),
            ("Selected OID", selected_oid, "mapping ที่บันทึกไว้"),
            ("Model", device.model or "Mock model", "device settings"),
            ("Serial", device.serial or "Mock serial", "device settings"),
        ]
        web_rows = [
            (f"[{index:03d}] {key}", f"{float(value):,.0f}", "MOCK จาก Daily Cache.latest")
            for index, (key, value) in enumerate(sorted(latest.items()))
        ]
        runtime_snapshot = runtime_snapshots.get(device.slot)
        ram_rows = [
            (
                f"{row.subject_type}:{row.subject_name or row.subject_id or 'Unknown'} · {row.canonical_field}",
                f"{float(row.count):,.0f}" if isinstance(row.count, (int, float)) else str(row.count),
                f"{row.label} · {row.source_path}",
            )
            for row in (runtime_snapshot.subject_rows if runtime_snapshot is not None else ())
        ]
        if not ram_rows:
            ram_rows.append(("ไม่พบ User Authentication / Account Track", "—", "MOCK RAM snapshot"))
        self._render_result(
            {
                "mode": "mock",
                "device": device,
                "snmp_rows": snmp_rows,
                "web_rows": web_rows,
                "ram_rows": ram_rows,
                "snmp_seconds": 0.0,
                "web_seconds": 0.0,
                "snmp_error": "",
                "web_error": "",
                "reconciliation": reconcile_web_counters(latest),
            }
        )

    @staticmethod
    def _fill_table(table: QTableWidget, count: QLabel, rows: list[tuple[str, str, str]]) -> None:
        table.setRowCount(len(rows))
        for row, (key, value, detail) in enumerate(rows):
            key_item = QTableWidgetItem(key)
            value_item = QTableWidgetItem(value)
            if detail:
                key_item.setToolTip(detail)
                value_item.setToolTip(detail)
            table.setItem(row, 0, key_item)
            table.setItem(row, 1, value_item)
        count.setText(f"{len(rows):,} รายการ")

    def _render_result(self, payload: dict) -> None:
        self._fill_table(self.snmp_table, self.snmp_count, payload["snmp_rows"])
        self._fill_table(self.web_table, self.web_count, payload["web_rows"])
        self._fill_table(self.ram_table, self.ram_count, payload["ram_rows"])
        device: DeviceConfig = payload["device"]
        errors = [message for message in (payload["snmp_error"], payload["web_error"]) if message]
        if payload.get("mode") == "mock":
            summary = (
                f"MOCK · {device.name} · SNMP Total {payload['snmp_rows'][0][1]} · "
                f"Web {len(payload['web_rows']):,} ค่า · RAM {len(payload['ram_rows']):,} fields · ไม่มีการเชื่อมต่อเครื่อง"
            )
        else:
            summary = (
                f"อ่าน {device.name} เสร็จ · SNMP {payload['snmp_seconds']:.2f}s · "
                f"Web {payload['web_seconds']:.2f}s · Web {len(payload['web_rows']):,} ค่า · RAM {len(payload['ram_rows']):,} fields"
            )
        if errors:
            summary += " · Error: " + " | ".join(errors)
        self.status.setText(summary)
        report = payload.get("reconciliation") or ReconciliationReport(0, ())
        self._render_reconciliation(report)

    def _render_reconciliation(self, report: ReconciliationReport) -> None:
        self.reconciliation_status.setText(report.summary(limit=4))
        self.reconciliation_status.setToolTip(report.audit_summary(limit=max(1, len(report.issues))))
        if report.needs_review:
            self.reconciliation_status.setStyleSheet(
                "background:#FFF1F0;color:#A62B2B;border:1px solid #F2B8B5;padding:9px 12px;font-weight:700;"
            )
        elif report.checked_count:
            self.reconciliation_status.setStyleSheet(
                "background:#EDF8F2;color:#176B49;border:1px solid #B8DFC9;padding:9px 12px;font-weight:700;"
            )
        else:
            self.reconciliation_status.setStyleSheet("background:#F8FAFC;color:#64748B;padding:9px 12px;")

    def _read_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.read_button.setEnabled(self.device_combo.count() > 0)
        self.read_button.setText("แสดง Mock ตอนนี้" if self.mock_mode.isChecked() else "อ่านข้อมูลตอนนี้")


class _TonerLevelBar(QWidget):
    """Compact toner percentage with a dynamic 20%-opacity fill."""

    def __init__(self, key: str, value: object, color: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.color = QColor(color)
        try:
            self.value = max(0.0, min(100.0, float(value)))
            self.value_text = f"{self.value:,.0f}%"
        except (TypeError, ValueError):
            self.value = 0.0
            self.value_text = "—"
        self.setObjectName("toner_level_bar")
        self.setProperty("tonerKey", key)
        self.setProperty("tonerPercent", self.value if self.value_text != "—" else None)
        # Four toner bars must remain side-by-side even when three printer
        # cards share the minimum-width desktop content area.
        self.setMinimumWidth(42)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # The application-wide QWidget background would otherwise remain
        # visible in the antialiased corners around the rounded toner track.
        self.setAutoFillBackground(False)
        self.setStyleSheet("background:transparent;border:none;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Match the white device card behind the rounded track so no page-gray
        # corner pixels leak through the custom-painted widget.
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        rect = QRectF(0.5, 0.5, max(0.0, self.width() - 1.0), max(0.0, self.height() - 1.0))
        path = QPainterPath()
        path.addRoundedRect(rect, 6.0, 6.0)

        painter.fillPath(path, QColor(C_TONER_TRACK))
        if self.value > 0:
            painter.save()
            painter.setClipPath(path)
            fill = QColor(self.color)
            fill.setAlphaF(0.20)
            fill_width = rect.width() * (self.value / 100.0)
            painter.fillRect(QRectF(rect.left(), rect.top(), fill_width, rect.height()), fill)
            painter.restore()

        painter.setPen(QPen(QColor(C_TONER_BORDER), 1.0))
        painter.drawPath(path)
        painter.setPen(self.color)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.key}  {self.value_text}")


class _PulsingStatusIndicator(QWidget):
    """Large connection light that pulses while a printer is online."""

    def __init__(self, status: str, color: str, tooltip: str, parent=None) -> None:
        super().__init__(parent)
        self.status = status
        self.color = QColor(color)
        self._pulse = 0.35
        self.setObjectName("device_connection_indicator")
        self.setProperty("connectionStatus", status or "unknown")
        self.setFixedSize(30, 30)
        self.setToolTip(tooltip)
        # Keep the semantic color discoverable to styles, accessibility tools,
        # and lightweight UI regression tests. Painting remains custom.
        self.setStyleSheet(f"color:{color};")
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(1_200)
        self._animation.setStartValue(0.35)
        self._animation.setKeyValueAt(0.5, 1.0)
        self._animation.setEndValue(0.35)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._set_pulse)
        if status == "online":
            self._animation.start()

    def _set_pulse(self, value: object) -> None:
        self._pulse = float(value)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        pulse = self._pulse if self.status == "online" else 0.55
        halo = QColor(self.color)
        halo.setAlphaF(0.18 + (0.22 * pulse))
        halo_radius = 9.0 + (3.0 * pulse)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, int(halo_radius), int(halo_radius))
        core = QColor(self.color)
        core.setAlphaF(0.75 + (0.25 * pulse))
        painter.setBrush(core)
        painter.drawEllipse(center, 6, 6)


class PageImportV5(QWidget):
    """Device-first live intake view for SNMP, Web and RAM counters."""

    changed = pyqtSignal()
    settings_requested = pyqtSignal(int)
    sync_requested = pyqtSignal()
    sync_log_requested = pyqtSignal()

    def __init__(
        self,
        legacy_import: QWidget,
        repository: DeviceConfigRepository | None = None,
        cache: DailyCacheStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.legacy = legacy_import
        self.repository = repository or DeviceConfigRepository()
        self.cache = cache or DailyCacheStore()
        self._device_cards: list[QWidget] = []
        self._grid_columns = 0
        self._empty_device_state: QWidget | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("รับข้อมูลรายเครื่อง")
        title.setFont(fnt(F_2XL, True))
        header.addWidget(title)
        header.addStretch()

        self.sync_log_button = btn("สถานะการอ่าน", "outline")
        self.sync_log_button.clicked.connect(self.sync_log_requested.emit)
        header.addWidget(self.sync_log_button)

        sync_controls = QVBoxLayout()
        sync_controls.setContentsMargins(0, 0, 0, 0)
        sync_controls.setSpacing(3)
        self.sync_button = btn("อ่านข้อมูลตอนนี้", "primary")
        self.sync_button.clicked.connect(self._request_sync)
        sync_controls.addWidget(self.sync_button, 0, Qt.AlignmentFlag.AlignRight)
        self.sync_message = QLabel("")
        self.sync_message.setObjectName("import_sync_message")
        self.sync_message.setWordWrap(True)
        self.sync_message.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.sync_message.setStyleSheet("color:#C62828;font-size:10px;font-weight:600;")
        self.sync_message.setMaximumWidth(310)
        self.sync_message.hide()
        sync_controls.addWidget(self.sync_message, 0, Qt.AlignmentFlag.AlignRight)
        header.addLayout(sync_controls)
        root.addLayout(header)

        self.device_grid = QGridLayout()
        self.device_grid.setContentsMargins(0, 4, 0, 4)
        self.device_grid.setHorizontalSpacing(16)
        self.device_grid.setVerticalSpacing(18)
        self.device_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        root.addLayout(self.device_grid)

        self.legacy.setParent(self)
        self.legacy.setVisible(False)
        if hasattr(self.legacy, "changed"):
            self.legacy.changed.connect(self.changed)
        root.addStretch()
        self.refresh()

    def _request_sync(self) -> None:
        self.sync_message.clear()
        self.sync_message.hide()
        self.sync_button.setEnabled(False)
        self.sync_button.setText(tr("กำลัง Sync…", "Syncing…"))
        self.sync_requested.emit()

    def sync_completed(self) -> None:
        self.sync_button.setText(tr("อ่านข้อมูลตอนนี้", "Read now"))
        self.sync_button.setEnabled(True)
        devices = self.repository.list(enabled_only=True)
        failed = [device for device in devices if device.connection_status != "online"]
        if failed:
            self.sync_message.setText(
                tr(
                    "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้ โปรดตรวจสอบเครือข่าย",
                    "Could not connect to the printer. Check the network connection.",
                )
            )
            self.sync_message.setToolTip(
                "\n".join(
                    f"{device.name}: {device.last_error or device.connection_status}"
                    for device in failed
                )
            )
            self.sync_message.show()
        else:
            self.sync_message.clear()
            self.sync_message.hide()

    @staticmethod
    def _format_number(value: object) -> str:
        if value in (None, ""):
            return "—"
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _section_title(text: str, source: str = "") -> QLabel:
        label = QLabel(text if not source else f"{text}   {source}")
        label.setFont(fnt(F_MD, True))
        label.setStyleSheet(f"color:{C_SECTION_TEXT};padding-top:10px;padding-bottom:4px;background:transparent;")
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{C_BORDER};")
        return line

    @staticmethod
    def _value_row(label: str, value: str, source: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)
        name = QLabel(label)
        name.setStyleSheet(f"color:{C_TEXT2};background:transparent;")
        name.setFixedWidth(100)
        row.addWidget(name)
        number = QLabel(value)
        number.setFont(fnt(F_MD, True))
        number.setAlignment(Qt.AlignmentFlag.AlignRight)
        number.setWordWrap(True)
        number.setMinimumWidth(0)
        number.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(number, 1)
        if source:
            badge = QLabel(source)
            badge.setStyleSheet("color:#64748B;font-size:10px;")
            badge.setFixedWidth(45)
            badge.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(badge)
        return row

    def _snapshot(self, device: DeviceConfig) -> dict:
        state = self.cache.load(device.slot, date.today()) or {}
        counters = latest_counters(device.slot)
        ram_snapshot = runtime_snapshots.get(device.slot)
        snmp_total = state.get("last_snmp_total", device.last_total)
        web_total = counters.get("counter.total.total", device.last_total)
        toner = state.get("snmp_toner") or {}
        paper = state.get("snmp_paper") or []
        paper_alerts = state.get("snmp_paper_alerts") or []
        web_rows = (
            ram_snapshot.web_rows
            if ram_snapshot is not None
            else tuple(
                RuntimeCounterRow(key, key, value, "Daily Cache")
                for key, value in sorted(counters.items())
            )
        )
        subject_rows = ram_snapshot.subject_rows if ram_snapshot is not None else ()
        return {
            "snmp_total": snmp_total,
            "web_total": web_total,
            "toner": toner,
            "paper": paper,
            "paper_alerts": paper_alerts,
            "web_rows": web_rows,
            "subject_rows": subject_rows,
            "counter_count": len(web_rows),
            "last_success": state.get("last_success") or device.last_success_at,
            "reconciliation": reconcile_web_counters(
                {row.canonical_field: row.count for row in web_rows}
            ),
        }

    def _web_table(self, rows: tuple[RuntimeCounterRow, ...]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("import_web_table")
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Counter", tr("ค่า", "Value")])
        table.setRowCount(len(rows))
        table.setMinimumWidth(0)
        table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        table.setFixedHeight(202)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Qt applies the global ``item`` padding again to ``item:alternate``.
        # Paint zebra rows explicitly so every row keeps the same text origin.
        table.setAlternatingRowColors(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setStyleSheet(
            "QTableWidget#import_web_table::item{padding:0 8px;}"
            "QTableWidget#import_web_table QHeaderView::section{padding:0 8px;}"
        )
        vertical_header = table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical_header.setDefaultSectionSize(34)
        vertical_header.setMinimumSectionSize(34)
        horizontal_header = table.horizontalHeader()
        horizontal_header.setFixedHeight(38)
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(1, 84)
        for index, row in enumerate(rows):
            field = QTableWidgetItem(row.canonical_field)
            field.setToolTip(f"{row.label}\n{row.source_path}")
            field.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value = QTableWidgetItem(self._format_number(row.count))
            value.setData(Qt.ItemDataRole.UserRole, row.count)
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if index % 2:
                field.setBackground(QColor(C_TABLE_ALT))
                value.setBackground(QColor(C_TABLE_ALT))
            table.setItem(index, 0, field)
            table.setItem(index, 1, value)
        return table

    @staticmethod
    def _set_zero_rows_hidden(table: QTableWidget, hidden: bool) -> None:
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            try:
                is_zero = not isinstance(raw, bool) and float(raw) == 0.0
            except (TypeError, ValueError):
                is_zero = False
            table.setRowHidden(row, hidden and is_zero)

    @staticmethod
    def _subject_total_rows(rows: tuple[RuntimeCounterRow, ...]) -> tuple[RuntimeCounterRow, ...]:
        """Return one explicit Total counter per User/Account without guessing a sum."""
        totals: dict[tuple[str, str], RuntimeCounterRow] = {}
        for row in rows:
            canonical = row.canonical_field.casefold()
            label = row.label.strip().casefold()
            if not (canonical.endswith(".total.total") or label in {"total", "total counter"}):
                continue
            identity = row.subject_id or row.subject_name or "unknown"
            key = (row.subject_type or "subject", identity)
            totals.setdefault(key, row)
        return tuple(totals.values())

    def _subject_table(self, rows: tuple[RuntimeCounterRow, ...]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("import_subject_table")
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["User / Account", "Total Counter"])
        table.setRowCount(len(rows))
        table.setMinimumWidth(0)
        table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        table.setFixedHeight(222)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setStyleSheet(
            "QTableWidget#import_subject_table::item{padding:0 8px;}"
            "QTableWidget#import_subject_table QHeaderView::section{padding:0 8px;}"
        )
        vertical_header = table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical_header.setDefaultSectionSize(34)
        vertical_header.setMinimumSectionSize(34)
        horizontal_header = table.horizontalHeader()
        horizontal_header.setFixedHeight(38)
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(1, 120)
        for index, row in enumerate(rows):
            subject = QTableWidgetItem(row.subject_name or row.subject_id or "Unknown")
            subject.setToolTip(
                f"type={row.subject_type or 'unknown'} · id={row.subject_id or '—'}\n{row.source_path}"
            )
            subject.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value = QTableWidgetItem(self._format_number(row.count))
            value.setToolTip(row.canonical_field)
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if index % 2:
                for item in (subject, value):
                    item.setBackground(QColor(C_TABLE_ALT))
            table.setItem(index, 0, subject)
            table.setItem(index, 1, value)
        return table

    def _toner_row(self, toner: dict) -> QWidget:
        panel = QWidget()
        panel.setObjectName("toner_level_row")
        # Override the application-wide QWidget page background. This wrapper
        # sits inside a white device card, so any exposed gaps around/between
        # the four custom bars must match that card instead of page gray.
        panel.setStyleSheet("QWidget#toner_level_row{background:#FFFFFF;border:none;}")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        colors = {"C": "#009DC4", "Y": "#B28700", "M": "#D81B60", "K": "#1F2937"}
        for key in ("C", "Y", "M", "K"):
            layout.addWidget(_TonerLevelBar(key, toner.get(key), colors[key]), 1)
        return panel

    @staticmethod
    def _cached_paper_trays(paper: object) -> tuple[PaperTrayStatus, ...]:
        """Read only identifiable physical input trays from the SNMP cache."""
        trays: list[PaperTrayStatus] = []
        if isinstance(paper, list):
            for item in paper:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "Tray")
                level = SnmpTotalProbe._integer(item.get("level"))
                capacity = SnmpTotalProbe._integer(item.get("capacity"))
                status = SnmpTotalProbe._integer(item.get("status"))
                input_index = SnmpTotalProbe._integer(item.get("input_index"))
                trays.append(PaperTrayStatus(name, level, capacity, status, input_index))
        return tuple(trays)

    @staticmethod
    def _tray_display_name(tray: PaperTrayStatus) -> str | None:
        """Map vendor labels to the configured operator-facing tray slots."""
        normalized = tray.name.casefold()
        if "bypass" in normalized:
            return "Bypass Tray"
        patterns = (
            r"(?:tray|cassette|drawer)\s*(?:no\.?\s*)?([1-5])\b",
            r"\b([1-5])(?:st|nd|rd|th)\s*(?:tray|cassette|drawer)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return f"Tray{match.group(1)}"
        if tray.input_index in {1, 2, 3, 4, 5}:
            return f"Tray{tray.input_index}"
        return None

    @classmethod
    def _ordered_paper_trays(cls, paper: object) -> tuple[tuple[str, PaperTrayStatus], ...]:
        discovered: dict[str, PaperTrayStatus] = {}
        for tray in cls._cached_paper_trays(paper):
            label = cls._tray_display_name(tray)
            if label is not None:
                discovered.setdefault(label, tray)
        # The two-row order mirrors the physical tray arrangement requested
        # by the operator: odd trays on top, even trays then Bypass below.
        order = ("Tray1", "Tray3", "Tray5", "Tray2", "Tray4", "Bypass Tray")
        return tuple((label, discovered[label]) for label in order if label in discovered)

    @staticmethod
    def _paper_tray_rows(
        ordered_trays: tuple[tuple[str, PaperTrayStatus], ...],
    ) -> tuple[tuple[tuple[str, PaperTrayStatus], ...], ...]:
        """Keep the physical tray matrix, with Bypass on its own row."""
        by_name = dict(ordered_trays)
        top = tuple((name, by_name[name]) for name in ("Tray1", "Tray3", "Tray5") if name in by_name)
        bottom = tuple((name, by_name[name]) for name in ("Tray2", "Tray4") if name in by_name)
        bypass = (("Bypass Tray", by_name["Bypass Tray"]),) if "Bypass Tray" in by_name else ()
        return tuple(row for row in (top, bottom, bypass) if row)

    @staticmethod
    def _paper_tray_columns(ordered_trays: tuple[tuple[str, PaperTrayStatus], ...]) -> int:
        return 3 if any(name == "Tray5" for name, _tray in ordered_trays) else 2

    @staticmethod
    def _paper_tile_state(tray: PaperTrayStatus, alerts: tuple[str, ...]) -> tuple[str, str, str, str]:
        """Render only confirmed-empty trays in orange; all other states stay neutral grey."""
        normalized_names = (tray.name.casefold(), (PageImportV5._tray_display_name(tray) or "").casefold())
        scoped_alerts = tuple(
            alert
            for alert in alerts
            if any(name and name in alert.casefold() for name in normalized_names)
        )
        summary = SnmpTotalProbe.summarize_paper((tray,), scoped_alerts)
        labels = {
            "empty": ("empty", "#F59E0B", "#FFFFFF", "#D97706"),
            "attention": ("unknown", "#E5E7EB", "#475569", "#CBD5E1"),
            "available": ("available", "#E5E7EB", "#334155", "#CBD5E1"),
            "unknown": ("unknown", "#E5E7EB", "#475569", "#CBD5E1"),
        }
        return labels[summary.state]

    def _paper_tray_tiles(self, paper: object, alerts: object) -> QWidget | None:
        ordered_trays = self._ordered_paper_trays(paper)
        if not ordered_trays:
            return None
        known_alerts = tuple(str(alert) for alert in alerts if str(alert).strip()) if isinstance(alerts, list) else ()
        panel = QWidget()
        panel.setObjectName("paper_tray_tiles")
        panel.setStyleSheet("QWidget#paper_tray_tiles{background:transparent;border:none;}")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title = QLabel("สถานะถาดกระดาษ")
        title.setStyleSheet(f"color:{C_TEXT2};background:transparent;")
        layout.addWidget(title)
        columns = self._paper_tray_columns(ordered_trays)
        for row_trays in self._paper_tray_rows(ordered_trays):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            is_bypass_row = row_trays[0][0] == "Bypass Tray"
            for tray_name, tray in row_trays:
                state, background, foreground, border = self._paper_tile_state(tray, known_alerts)
                tooltip_state = "กระดาษหมด" if state == "empty" else "สถานะกระดาษปกติ" if state == "available" else "อ่านสถานะกระดาษไม่ได้"
                tile = QFrame()
                tile.setObjectName("paper_tray_tile")
                tile.setProperty("trayName", tray_name)
                tile.setProperty("paperState", state)
                tile.setFixedHeight(20)
                tile_layout = QVBoxLayout(tile)
                tile_layout.setContentsMargins(4, 1, 4, 1)
                name = QLabel(tray_name)
                name.setAlignment(Qt.AlignmentFlag.AlignCenter)
                name.setStyleSheet("background:transparent;border:none;font-size:10px;font-weight:700;")
                tile.setStyleSheet(
                    f"background:{background};color:{foreground};border:1px solid {border};"
                    "border-radius:6px;"
                )
                tile.setToolTip(f"{tray_name} · {tooltip_state}")
                tile_layout.addWidget(name)
                row.addWidget(tile, columns if is_bypass_row else 1)
            if not is_bypass_row:
                for _blank in range(columns - len(row_trays)):
                    row.addStretch(1)
            layout.addLayout(row)
        return panel

    @staticmethod
    def _connection_indicator(device: DeviceConfig) -> _PulsingStatusIndicator:
        status = device.connection_status.casefold()
        if status == "online":
            color = "#00A651"
            text = "เชื่อมต่อแล้ว"
        elif status in {"pending", "unknown", ""}:
            color = "#F5C000"
            text = "ยังไม่ได้ตรวจสอบ"
        else:
            color = "#D71920"
            text = "ไม่สามารถเชื่อมต่อได้"
        detail = device.last_error or text
        checked = f"\nตรวจล่าสุด: {device.last_checked_at}" if device.last_checked_at else ""
        return _PulsingStatusIndicator(status or "unknown", color, f"{text}\n{detail}{checked}")

    def _device_card(self, device: DeviceConfig) -> QFrame:
        snapshot = self._snapshot(device)
        card = QFrame()
        card.setObjectName("import_device_card")
        card.setStyleSheet(
            f"QFrame#import_device_card{{background:white;border:1px solid {C_BORDER};"
            f"border-top:4px solid {SLOT_COLORS[device.slot]};border-radius:8px;}}"
            "QFrame#import_device_card QLabel{background:transparent;}"
        )
        # The page changes between one, two and three columns.  A hard minimum
        # width makes QGridLayout overlap cards at 1024 px, so the responsive
        # reflow owns the column count and cards are allowed to shrink cleanly.
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(9)

        top = QHBoxLayout()
        name = QLabel(device.name)
        name.setFont(fnt(F_MD, True))
        name.setWordWrap(True)
        name.setMinimumWidth(0)
        top.addWidget(name, 1)
        top.addStretch()
        connection_indicator = self._connection_indicator(device)
        top.addWidget(connection_indicator)
        layout.addLayout(top)
        card._connection_indicator = connection_indicator

        layout.addLayout(self._value_row("ชื่อรุ่น", device.model or "—"))
        layout.addLayout(self._value_row("Serial number", device.serial or "—"))
        layout.addLayout(self._value_row("Total Meter", self._format_number(snapshot["snmp_total"])))
        toner_title = QLabel("ปริมาณหมึก")
        toner_title.setStyleSheet(f"color:{C_TEXT2};background:transparent;")
        layout.addWidget(toner_title)
        layout.addWidget(self._toner_row(snapshot["toner"]))
        paper_tiles = self._paper_tray_tiles(snapshot["paper"], snapshot["paper_alerts"])
        if paper_tiles is not None:
            layout.addWidget(paper_tiles)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_title(tr("ปริมาณการใช้งาน", "Usage")))
        layout.addLayout(self._value_row("ยอดรวม Meter", self._format_number(snapshot["web_total"])))
        detail = QLabel(
            tr(
                f"อ่านได้ {snapshot['counter_count']:,} Counter"
                + (f" · ล่าสุด {str(snapshot['last_success'])[11:16]} น." if snapshot["last_success"] else ""),
                f"Read {snapshot['counter_count']:,} counters"
                + (f" · latest {str(snapshot['last_success'])[11:16]}" if snapshot["last_success"] else ""),
            )
        )
        detail.setStyleSheet(f"color:{C_MUTED_TEXT};font-size:10px;background:transparent;")
        layout.addWidget(detail)
        web_table = self._web_table(snapshot["web_rows"])
        zero_count = sum(
            1
            for row in snapshot["web_rows"]
            if not isinstance(row.count, bool) and isinstance(row.count, (int, float)) and float(row.count) == 0.0
        )
        zero_checkbox = QCheckBox(
            tr(
                f"ซ่อน Counter ที่มีค่าเป็น 0 ({zero_count:,} รายการ)",
                f"Hide zero-value counters ({zero_count:,} items)",
            )
        )
        zero_checkbox.toggled.connect(
            lambda checked, table=web_table: self._set_zero_rows_hidden(table, checked)
        )
        zero_checkbox.setParent(card)
        zero_checkbox.hide()
        card._zero_checkbox = zero_checkbox
        reconciliation: ReconciliationReport = snapshot["reconciliation"]
        reconciliation_label = QLabel(translate_text(reconciliation.summary(limit=3)))
        reconciliation_label.setWordWrap(True)
        if reconciliation.needs_review:
            reconciliation_label.setStyleSheet(
                "background:#FFF1F0;color:#A62B2B;border:1px solid #F2B8B5;padding:8px;font-size:10px;font-weight:700;"
            )
        elif reconciliation.checked_count:
            reconciliation_label.setStyleSheet(
                "background:#EDF8F2;color:#176B49;border:1px solid #B8DFC9;padding:8px;font-size:10px;font-weight:700;"
            )
        else:
            reconciliation_label.setStyleSheet("background:#F8FAFC;color:#64748B;padding:8px;font-size:10px;")
        reconciliation_label.setToolTip(reconciliation.audit_summary(limit=max(1, len(reconciliation.issues))))
        reconciliation_label.setParent(card)
        reconciliation_label.hide()
        card._reconciliation_label = reconciliation_label
        card._web_table = web_table
        layout.addWidget(web_table)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_title("User Authentication / Account Track"))
        subject_rows = snapshot["subject_rows"]
        subject_total_rows = self._subject_total_rows(subject_rows)
        if subject_total_rows:
            subject_detail = QLabel(
                tr(
                    f"RAM snapshot · {len(subject_total_rows):,} User/Account · แสดง Total Counter",
                    f"RAM snapshot · {len(subject_total_rows):,} users/accounts · Total Counter",
                )
            )
            subject_detail.setStyleSheet(f"color:{C_MUTED_TEXT};font-size:10px;background:transparent;")
            layout.addWidget(subject_detail)
            subject_table = self._subject_table(subject_total_rows)
            card._subject_table = subject_table
            layout.addWidget(subject_table)
        else:
            empty = QLabel(
                tr(
                    "ไม่พบ User Authentication / Account Track ที่เปิดใช้งาน",
                    "No enabled User Authentication / Account Track data",
                )
            )
            empty.setWordWrap(True)
            empty.setMinimumWidth(0)
            empty.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            empty.setStyleSheet(
                f"background:{C_EMPTY_BG};color:{C_MUTED_TEXT};padding:9px;border-radius:5px;"
            )
            layout.addWidget(empty)
            card._subject_table = None
        layout.addStretch()
        return card

    @staticmethod
    def _responsive_columns(width: int, device_count: int) -> int:
        """Keep counter labels readable while using the available width."""
        readable_columns = max(1, min(3, width // 300))
        return max(1, min(readable_columns, device_count))

    def _clear_grid_positions(self) -> None:
        while self.device_grid.count():
            self.device_grid.takeAt(0)
        for column in range(3):
            self.device_grid.setColumnStretch(column, 0)
            self.device_grid.setColumnMinimumWidth(column, 0)

    def _reflow_device_cards(self, *, force: bool = False) -> None:
        if not self._device_cards:
            return
        available_width = max(0, self.width() - 44)
        columns = self._responsive_columns(available_width, len(self._device_cards))
        if not force and columns == self._grid_columns:
            return
        self._clear_grid_positions()
        self._grid_columns = columns
        for index, card in enumerate(self._device_cards):
            self.device_grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.device_grid.setColumnStretch(column, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_device_cards()

    def refresh(self) -> None:
        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._device_cards.clear()
        self._empty_device_state = None
        self._grid_columns = 0
        devices = self.repository.list(enabled_only=True)
        for device in devices:
            card = self._device_card(device)
            self._device_cards.append(card)
        if self._device_cards:
            self._reflow_device_cards(force=True)
        if not devices:
            empty = QLabel("ยังไม่ได้ตั้งค่าเครื่องพิมพ์ · ไปที่ Settings เพื่อเพิ่ม 1–3 เครื่อง")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("background:white;border:1px solid #CBD5E1;padding:28px;color:#64748B;")
            self._empty_device_state = empty
            self.device_grid.addWidget(empty, 0, 0)
            self.device_grid.setColumnStretch(0, 1)


class ReportExportPeriodDialog(QDialog):
    """Choose one explicit report range before creating the Excel workbook."""

    def __init__(
        self,
        start: date,
        end: date,
        *,
        available_start: date | None = None,
        available_end: date | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.available_start = available_start
        self.available_end = available_end
        self.setWindowTitle("Export รายงาน Excel")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("เลือกช่วงเวลาที่ต้องการ Export")
        title.setFont(fnt(F_LG, True))
        layout.addWidget(title)
        description = QLabel(
            "Excel จะมี 3 ชีต: การใช้งานรายเครื่อง, มุมมองผู้ใช้ และมุมมองรายวัน"
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color:{C_TEXT2};")
        layout.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.start_date = QDateEdit(QDate(start.year, start.month, start.day))
        self.end_date = QDateEdit(QDate(end.year, end.month, end.day))
        for editor in (self.start_date, self.end_date):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd/MM/yyyy")
            editor.setMinimumHeight(40)
        form.addRow("วันที่เริ่มต้น", self.start_date)
        form.addRow("วันที่สิ้นสุด", self.end_date)
        layout.addLayout(form)

        quick = QHBoxLayout()
        quick.setSpacing(8)
        current_button = QPushButton("ช่วงที่แสดงอยู่")
        current_button.clicked.connect(lambda: self._set_range(start, end))
        quick.addWidget(current_button)
        month_button = QPushButton("เดือนนี้")
        month_button.clicked.connect(self._set_current_month)
        quick.addWidget(month_button)
        if available_start is not None and available_end is not None:
            all_button = QPushButton("ข้อมูลทั้งหมด")
            all_button.clicked.connect(
                lambda: self._set_range(available_start, available_end)
            )
            quick.addWidget(all_button)
        quick.addStretch(1)
        layout.addLayout(quick)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{C_TEXT2};padding:8px;background:#F5F8FA;")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        self.export_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.export_button.setText("Export Excel")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.start_date.dateChanged.connect(self._validate)
        self.end_date.dateChanged.connect(self._validate)
        self._validate()

    def selected_range(self) -> tuple[date, date]:
        return self.start_date.date().toPyDate(), self.end_date.date().toPyDate()

    def _set_range(self, start: date, end: date) -> None:
        self.start_date.setDate(QDate(start.year, start.month, start.day))
        self.end_date.setDate(QDate(end.year, end.month, end.day))

    def _set_current_month(self) -> None:
        today = date.today()
        month_start = today.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        self._set_range(month_start, next_month - timedelta(days=1))

    def _validate(self) -> None:
        start, end = self.selected_range()
        valid = start <= end
        self.export_button.setEnabled(valid)
        if not valid:
            self.status.setText("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
            self.status.setStyleSheet("color:#B42318;padding:8px;background:#FFF1F0;")
            return
        days = (end - start).days + 1
        available = ""
        if self.available_start is not None and self.available_end is not None:
            available = (
                f" · ข้อมูลที่พบ {self.available_start:%d/%m/%Y}–"
                f"{self.available_end:%d/%m/%Y}"
            )
        self.status.setText(f"ช่วงที่เลือก {days:,} วัน{available}")
        self.status.setStyleSheet(f"color:{C_TEXT2};padding:8px;background:#F5F8FA;")

    @classmethod
    def get_range(
        cls,
        parent,
        start: date,
        end: date,
        *,
        available_start: date | None = None,
        available_end: date | None = None,
    ) -> tuple[date, date] | None:
        dialog = cls(
            start,
            end,
            available_start=available_start,
            available_end=available_end,
            parent=parent,
        )
        return dialog.selected_range() if dialog.exec() == QDialog.DialogCode.Accepted else None


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
    ) -> None:
        self.repository = repository or DeviceConfigRepository()
        self.cache = cache or DailyCacheStore()
        self.subject_cache = subject_cache or SubjectDailyCacheStore()
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
        title_item = self.layout().itemAt(0)
        if title_item is not None and title_item.widget() is not None:
            title_item.widget().setVisible(False)
        self.machine_selector_container.setVisible(False)
        self.report_profile_combo.parentWidget().setVisible(False)
        self.report_advanced_panel.setVisible(False)
        self.tabs.setVisible(False)
        self.report_center = CloudReportsWidget()
        self.report_center.refresh_requested.connect(self.refresh)
        self.report_center.export_requested.connect(self._export_report_center_excel)
        self.report_center.period_changed.connect(self._refresh_report_center)
        self.report_center.reading_status_requested.connect(self.reading_status_requested)
        self.report_center_tabs = self.report_center.tabs
        self.report_center_scroll = QScrollArea()
        self.report_center_scroll.setObjectName("cloud_reports_scroll")
        self.report_center_scroll.setWidget(self.report_center)
        self.report_center_scroll.setWidgetResizable(True)
        self.report_center_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.report_center_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.report_center_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.layout().addWidget(self.report_center_scroll, 1)
        self._populate_report_periods()
        self._refresh_report_center()

    @staticmethod
    def _report_panel() -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("report_content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        return panel, layout

    @staticmethod
    def _report_date_edit(value: QDate) -> QDateEdit:
        editor = QDateEdit(value)
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("dd/MM/yyyy")
        editor.setMinimumWidth(128)
        return editor

    @staticmethod
    def _setup_plain_table(table: QTableWidget, headers: tuple[str, ...]) -> None:
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for index in range(len(headers)):
            table.horizontalHeader().setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.Stretch
                if index < len(headers) - 1
                else QHeaderView.ResizeMode.ResizeToContents,
            )

    def _build_usage_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        filter_panel, filters = self._report_panel()
        filter_panel.setObjectName("report_filter_panel")
        row = QHBoxLayout()
        row.addWidget(QLabel("Report"))
        self.usage_report_type = QComboBox()
        self.usage_report_type.addItem("Summary", "summary")
        self.usage_report_type.addItem("Per device", "device")
        self.usage_report_type.addItem("Per user", "user")
        self.usage_report_type.setMinimumWidth(180)
        row.addWidget(self.usage_report_type)
        row.addSpacing(18)
        row.addWidget(QLabel("Report period"))
        period_start, _period_end = history_period_range(
            date.today(), get_billing_day(), "monthly"
        )
        self.usage_from_date = self._report_date_edit(
            QDate(period_start.year, period_start.month, period_start.day)
        )
        self.usage_to_date = self._report_date_edit(QDate.currentDate())
        row.addWidget(self.usage_from_date)
        row.addWidget(QLabel("–"))
        row.addWidget(self.usage_to_date)
        row.addSpacing(12)
        self.usage_search_button = btn("Search", "primary")
        self.usage_search_button.clicked.connect(self._refresh_usage_report)
        row.addWidget(self.usage_search_button)
        self.usage_advanced_button = btn("Advanced", "outline")
        self.usage_advanced_button.setCheckable(True)
        self.usage_advanced_button.toggled.connect(
            lambda visible: self.usage_advanced_panel.setVisible(visible)
        )
        row.addWidget(self.usage_advanced_button)
        row.addStretch()
        filters.addLayout(row)

        self.usage_advanced_panel = QWidget()
        advanced = QHBoxLayout(self.usage_advanced_panel)
        advanced.setContentsMargins(0, 4, 0, 0)
        advanced.addWidget(QLabel("Device"))
        self.usage_device_filter = QComboBox()
        self.usage_device_filter.addItem("All devices", None)
        advanced.addWidget(self.usage_device_filter)
        self.usage_include_scan = QCheckBox("Include Scan")
        self.usage_include_scan.setChecked(True)
        advanced.addWidget(self.usage_include_scan)
        advanced.addWidget(QLabel("View"))
        self.usage_display_mode = QComboBox()
        self.usage_display_mode.addItem("Table", "table")
        self.usage_display_mode.addItem("Trend", "trend")
        self.usage_display_mode.currentIndexChanged.connect(self._set_usage_display_mode)
        advanced.addWidget(self.usage_display_mode)
        advanced.addStretch()
        self.usage_advanced_panel.setVisible(False)
        filters.addWidget(self.usage_advanced_panel)
        layout.addWidget(filter_panel)

        self.usage_metric_tabs = QTabWidget()
        self.usage_metric_tabs.setMaximumHeight(44)
        for title in ("Total", "Color", "B/W", "A4", "A3", "Scan", "Cost"):
            self.usage_metric_tabs.addTab(QWidget(), title)
        self.usage_metric_tabs.currentChanged.connect(self._refresh_usage_report)
        layout.addWidget(self.usage_metric_tabs)

        summary_panel, summary_layout = self._report_panel()
        summary_layout.addWidget(QLabel("Summary", font=fnt(F_LG, True)))
        self.usage_summary_table = QTableWidget()
        self._setup_plain_table(
            self.usage_summary_table,
            ("Counter type", "Pages", "Cost (฿)"),
        )
        self.usage_summary_table.setMaximumHeight(285)
        summary_layout.addWidget(self.usage_summary_table)
        layout.addWidget(summary_panel)

        details_panel, details_layout = self._report_panel()
        self.usage_details_title = QLabel("Breakdown by device")
        self.usage_details_title.setFont(fnt(F_LG, True))
        details_layout.addWidget(self.usage_details_title)
        self.usage_details_table = QTableWidget()
        self._setup_plain_table(
            self.usage_details_table,
            ("Device", "Location", "Pages", "Cost (฿)"),
        )
        details_layout.addWidget(self.usage_details_table, 1)
        self.usage_trend_chart = QChartView()
        self.usage_trend_chart.setMinimumHeight(260)
        self.usage_trend_chart.setVisible(False)
        details_layout.addWidget(self.usage_trend_chart, 1)
        layout.addWidget(details_panel, 1)
        return page

    def _build_management_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        filter_panel, filters = self._report_panel()
        filter_panel.setObjectName("report_filter_panel")
        row = QHBoxLayout()
        row.addWidget(QLabel("Year"))
        self.management_year = QComboBox()
        self.management_year.setMinimumWidth(120)
        row.addWidget(self.management_year)
        row.addSpacing(18)
        self.management_period_group = QButtonGroup(self)
        self.management_period_buttons: dict[str, QPushButton] = {}
        for key, label in (("year", "Year"), ("q1", "Q1"), ("q2", "Q2"), ("q3", "Q3"), ("q4", "Q4")):
            button = btn(label, "outline")
            button.setCheckable(True)
            button.clicked.connect(lambda checked, value=key: self._set_management_period(value))
            self.management_period_group.addButton(button)
            self.management_period_buttons[key] = button
            row.addWidget(button)
        self.management_period_buttons["year"].setChecked(True)
        row.addStretch()
        self.management_search_button = btn("Search", "primary")
        self.management_search_button.clicked.connect(self._refresh_management_report)
        row.addWidget(self.management_search_button)
        filters.addLayout(row)
        layout.addWidget(filter_panel)

        overview_panel, overview = self._report_panel()
        self.management_title = QLabel("Company overview")
        self.management_title.setFont(fnt(F_XL, True))
        overview.addWidget(self.management_title)
        charts = QHBoxLayout()
        self.management_color_chart = QChartView()
        self.management_size_chart = QChartView()
        self.management_color_chart.setMinimumHeight(240)
        self.management_size_chart.setMinimumHeight(240)
        charts.addWidget(self.management_color_chart, 1)
        charts.addWidget(self.management_size_chart, 1)
        overview.addLayout(charts)
        layout.addWidget(overview_panel)

        printed_panel, printed = self._report_panel()
        printed.addWidget(QLabel("Printed pages", font=fnt(F_LG, True)))
        self.management_printed_table = QTableWidget()
        self._setup_plain_table(
            self.management_printed_table,
            ("", "Pages (A4)", "Price (A4)", "Pages (A3)", "Price (A3)", "Total pages", "Total price"),
        )
        self.management_printed_table.setMaximumHeight(190)
        printed.addWidget(self.management_printed_table)
        layout.addWidget(printed_panel)

        rankings = QHBoxLayout()
        self.management_top_users = self._management_ranking_panel("Top five users", "User")
        self.management_top_devices = self._management_ranking_panel("Most used devices", "Device")
        rankings.addWidget(self.management_top_users, 1)
        rankings.addWidget(self.management_top_devices, 1)
        layout.addLayout(rankings, 1)
        return page

    def _management_ranking_panel(self, title: str, first_column: str) -> QFrame:
        panel, layout = self._report_panel()
        layout.addWidget(QLabel(title, font=fnt(F_LG, True)))
        table = QTableWidget()
        self._setup_plain_table(table, (first_column, "Pages", "Cost (฿)"))
        layout.addWidget(table)
        if first_column == "User":
            self.management_top_users_table = table
        else:
            self.management_top_devices_table = table
        return panel

    def _build_meter_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        filter_panel, filters = self._report_panel()
        filter_panel.setObjectName("report_filter_panel")
        row = QHBoxLayout()
        row.addWidget(QLabel("Readout"))
        self.meter_readout_type = QComboBox()
        self.meter_readout_type.addItem("First and last readout", "first_last")
        self.meter_readout_type.addItem("Daily readout", "daily")
        row.addWidget(self.meter_readout_type)
        row.addSpacing(18)
        row.addWidget(QLabel("Device"))
        self.meter_device_filter = QComboBox()
        self.meter_device_filter.addItem("All devices", None)
        row.addWidget(self.meter_device_filter)
        row.addSpacing(18)
        row.addWidget(QLabel("Period"))
        self.meter_period_filter = QComboBox()
        self.meter_period_filter.addItem("Today", "today")
        self.meter_period_filter.addItem("Last 7 days", "week")
        self.meter_period_filter.addItem("Last 30 days", "month")
        row.addWidget(self.meter_period_filter)
        self.meter_search_button = btn("Search", "primary")
        self.meter_search_button.clicked.connect(self._refresh_meter_report)
        row.addWidget(self.meter_search_button)
        row.addStretch()
        filters.addLayout(row)
        layout.addWidget(filter_panel)

        meter_panel, meter = self._report_panel()
        meter.addWidget(QLabel("Device counters", font=fnt(F_LG, True)))
        self.meter_table = QTableWidget()
        meter.addWidget(self.meter_table, 1)
        layout.addWidget(meter_panel, 2)

        history_panel, history = self._report_panel()
        history.addWidget(QLabel("Readout history", font=fnt(F_LG, True)))
        self.meter_history_table = QTableWidget()
        self._setup_plain_table(
            self.meter_history_table,
            ("Device", "Date", "First readout", "Last readout", "Total meter"),
        )
        history.addWidget(self.meter_history_table)
        layout.addWidget(history_panel, 1)
        return page

    def _refresh_report_center(self, selection: object | None = None) -> None:
        """Refresh the visible Cloud reports from one shared date range."""
        if not hasattr(self, "report_center"):
            return
        periods = sorted(
            {self._period_key(record) for record in getattr(self, "_report_records", ())},
            reverse=True,
        )
        selected = (
            tuple(selection)
            if isinstance(selection, (tuple, list)) and len(selection) == 2
            else self.report_center.current_period()
        )
        if selected is None:
            selected = periods[0] if periods else None
        self.report_center.set_periods(periods, selected)
        usage_daily_records = tuple(
            load_usage_history(report_slots(), granularity="daily", cache=self.cache)
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
            subjects = tuple(
                record
                for record in load_subject_history(
                    report_slots(), cache=self.subject_cache
                )
                if record.period_start == start and record.period_end == end
            )
        else:
            daily_records = ()
            selected_records = ()
            subjects = ()
        devices = tuple(self._historical_devices())
        last_sync = max(
            (
                str(device.last_success_at)
                for device in devices
                if getattr(device, "last_success_at", None)
            ),
            default=None,
        )
        self.report_center.set_data(
            records=selected_records,
            daily_records=daily_records,
            usage_daily_records=usage_daily_records,
            monthly_records=getattr(self, "_report_records", ()),
            subjects=subjects,
            devices=devices,
            legacy_history=load_imported_legacy_history(),
            period=selected,
            last_sync_at=last_sync,
        )
        apply_language(self.report_center)

    def _export_report_center_excel(self) -> None:
        """Choose a date range, then export three user-facing report views."""
        cloud = self.report_center
        available_records = tuple(cloud._usage_daily_records)
        available_start = min(
            (record.period_start for record in available_records),
            default=None,
        )
        available_end = max(
            (record.period_end for record in available_records),
            default=None,
        )
        if cloud._period is not None:
            default_start, default_end = (
                date.fromisoformat(value) for value in cloud._period
            )
        elif available_start is not None and available_end is not None:
            default_start, default_end = available_start, available_end
        else:
            default_start = default_end = date.today()
        selected = ReportExportPeriodDialog.get_range(
            self,
            default_start,
            default_end,
            available_start=available_start,
            available_end=available_end,
        )
        if selected is None:
            return
        start, end = selected
        daily_records = tuple(
            record
            for record in available_records
            if record.period_start <= end and record.period_end >= start
        )
        if not daily_records:
            QMessageBox.warning(
                self,
                "ไม่พบข้อมูล",
                "ไม่มีข้อมูลรายงานในช่วงวันที่เลือก กรุณาเลือกช่วงเวลาใหม่",
            )
            return
        subjects = tuple(
            load_subject_history(
                report_slots(),
                cache=self.subject_cache,
                period_start=start,
                period_end=end,
            )
        )
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
        try:
            saved = export_cloud_reports_xlsx(
                path,
                CloudReportsExportData(
                    selected_records=daily_records,
                    selected_daily_records=daily_records,
                    usage_daily_records=daily_records,
                    monthly_records=tuple(cloud._monthly_records),
                    subjects=subjects,
                    devices=tuple(cloud._devices),
                    period=(start.isoformat(), end.isoformat()),
                    last_sync_at=cloud._last_sync_at,
                    generated_at=datetime.now().astimezone(),
                ),
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "Export ไม่สำเร็จ",
                f"ไม่สามารถสร้างไฟล์ Excel ได้:\n{error}",
            )
            return
        QMessageBox.information(
            self,
            "Export สำเร็จ",
            f"บันทึกไฟล์ Excel แล้ว\n{saved}",
        )

    def _populate_report_device_filters(self) -> None:
        devices = self.repository.list(enabled_only=True)
        for control in (self.usage_device_filter, self.meter_device_filter):
            current = control.currentData()
            control.blockSignals(True)
            control.clear()
            control.addItem("All devices", None)
            for device in devices:
                control.addItem(f"{device.name} · {device.host}", device.slot)
            index = control.findData(current)
            control.setCurrentIndex(max(0, index))
            control.blockSignals(False)

    @staticmethod
    def _date_from_editor(editor: QDateEdit) -> date:
        return editor.date().toPyDate()

    @staticmethod
    def _record_total(record: MonthlyUsage, field: str) -> float:
        confirmed = float(getattr(record, field, 0.0) or 0.0)
        provisional_field = f"provisional_{field}"
        provisional = float(getattr(record, provisional_field, 0.0) or 0.0)
        return confirmed + provisional

    def _usage_records_in_range(self) -> tuple[MonthlyUsage, ...]:
        start = self._date_from_editor(self.usage_from_date)
        end = self._date_from_editor(self.usage_to_date)
        if end < start:
            start, end = end, start
            self.usage_from_date.setDate(QDate(start.year, start.month, start.day))
            self.usage_to_date.setDate(QDate(end.year, end.month, end.day))
        selected_slot = self.usage_device_filter.currentData()
        return tuple(
            record
            for record in load_usage_history(
                report_slots(), granularity="daily", cache=self.cache
            )
            if record.period_start <= end
            and record.period_end >= start
            and (selected_slot is None or record.device_slot == selected_slot)
        )

    @staticmethod
    def _usage_metric_value(record: MonthlyUsage, metric: str) -> float:
        fields = {
            "Total": "total",
            "Color": "a3_color",
            "B/W": "a3_bw",
            "A4": "a4_color",
            "A3": "a3_color",
            "Scan": "scan",
            "Cost": "net_cost",
        }
        if metric == "Color":
            return (
                PageHistoryV5._record_total(record, "a3_color")
                + PageHistoryV5._record_total(record, "a4_color")
            )
        if metric == "B/W":
            return (
                PageHistoryV5._record_total(record, "a3_bw")
                + PageHistoryV5._record_total(record, "a4_bw")
            )
        if metric == "A4":
            return (
                PageHistoryV5._record_total(record, "a4_color")
                + PageHistoryV5._record_total(record, "a4_bw")
            )
        if metric == "A3":
            return (
                PageHistoryV5._record_total(record, "a3_color")
                + PageHistoryV5._record_total(record, "a3_bw")
            )
        return PageHistoryV5._record_total(record, fields[metric])

    @staticmethod
    def _write_table_row(
        table: QTableWidget,
        row: int,
        values: tuple[str, ...],
        *,
        bold: bool = False,
    ) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFont(fnt(F_SM, bold))
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft
                if column == 0
                else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, column, item)

    def _refresh_usage_report(self, *_args) -> None:
        if not hasattr(self, "usage_summary_table"):
            return
        self._populate_report_device_filters()
        records = self._usage_records_in_range()
        include_scan = self.usage_include_scan.isChecked()
        metrics = [
            ("Total", sum(self._record_total(item, "total") for item in records), None),
            (
                "Color",
                sum(
                    self._record_total(item, "a3_color")
                    + self._record_total(item, "a4_color")
                    for item in records
                ),
                None,
            ),
            (
                "B/W",
                sum(
                    self._record_total(item, "a3_bw")
                    + self._record_total(item, "a4_bw")
                    for item in records
                ),
                None,
            ),
            (
                "A4",
                sum(
                    self._record_total(item, "a4_color")
                    + self._record_total(item, "a4_bw")
                    for item in records
                ),
                None,
            ),
            (
                "A3",
                sum(
                    self._record_total(item, "a3_color")
                    + self._record_total(item, "a3_bw")
                    for item in records
                ),
                None,
            ),
        ]
        if include_scan:
            metrics.append(("Scan", sum(self._record_total(item, "scan") for item in records), None))
        costs_available = all(
            item.provisional_cost_available or not item.provisional_days
            for item in records
        )
        total_cost = sum(self._record_total(item, "net_cost") for item in records)
        metrics.append(("Cost", 0.0, total_cost if costs_available else None))
        table = self.usage_summary_table
        table.setRowCount(len(metrics))
        for row, (label, pages, cost) in enumerate(metrics):
            self._write_table_row(
                table,
                row,
                (
                    label,
                    f"{pages:,.0f}" if label != "Cost" else "—",
                    f"{cost:,.2f}" if cost is not None else "—",
                ),
                bold=label == "Total",
            )

        report_type = str(self.usage_report_type.currentData() or "summary")
        if report_type == "user":
            self._render_usage_users(records)
        else:
            self._render_usage_devices(records, report_type)
        self._render_usage_trend(records)
        self.report_updated_at.setText(
            f"Updated {datetime.now():%d/%m/%Y %H:%M}"
        )

    def _render_usage_devices(
        self,
        records: tuple[MonthlyUsage, ...],
        report_type: str,
    ) -> None:
        self.usage_details_title.setText(
            "Breakdown by device" if report_type == "device" else "Usage overview by device"
        )
        self._setup_plain_table(
            self.usage_details_table,
            ("Device", "Location", "Pages", "Cost (฿)"),
        )
        devices = {device.slot: device for device in self.repository.list(enabled_only=False)}
        grouped: dict[tuple[int, str], list[MonthlyUsage]] = {}
        for record in records:
            grouped.setdefault(
                (record.device_slot, self._record_device_identity(record)), []
            ).append(record)
        rows: list[tuple[str, str, float, float | None]] = []
        for (slot, _identity), items in grouped.items():
            sample = items[0]
            device = devices.get(slot)
            label = sample.device_name_snapshot or (device.name if device else f"Slot {slot + 1}")
            location = device.host if device else "—"
            usage = sum(self._record_total(item, "total") for item in items)
            has_cost = all(
                item.provisional_cost_available or not item.provisional_days
                for item in items
            )
            cost = sum(self._record_total(item, "net_cost") for item in items) if has_cost else None
            rows.append((label, location, usage, cost))
        rows.sort(key=lambda item: item[2], reverse=True)
        self.usage_details_table.setRowCount(len(rows))
        for row, (label, location, usage, cost) in enumerate(rows):
            self._write_table_row(
                self.usage_details_table,
                row,
                (label, location, f"{usage:,.0f}", f"{cost:,.2f}" if cost is not None else "—"),
            )

    def _render_usage_users(self, records: tuple[MonthlyUsage, ...]) -> None:
        self.usage_details_title.setText("Breakdown by user")
        self._setup_plain_table(
            self.usage_details_table,
            ("User / Account", "Type", "Pages", "Latest readout"),
        )
        selected_slots = {record.device_slot for record in records}
        start = self._date_from_editor(self.usage_from_date)
        end = self._date_from_editor(self.usage_to_date)
        grouped: dict[tuple[str, str], list[SubjectPeriodUsage]] = {}
        for item in load_subject_history(report_slots(), cache=self.subject_cache):
            if (
                item.device_slot in selected_slots
                and item.period_start <= end
                and item.period_end >= start
            ):
                grouped.setdefault((item.subject_type, item.subject_id), []).append(item)
        rows: list[tuple[str, str, float, str]] = []
        for (subject_type, _subject_id), items in grouped.items():
            latest = max(items, key=lambda item: item.latest_at or "")
            rows.append(
                (
                    latest.subject_name,
                    subject_type.title(),
                    sum(item.period_usage for item in items),
                    latest.latest_at or "—",
                )
            )
        rows.sort(key=lambda item: item[2], reverse=True)
        self.usage_details_table.setRowCount(len(rows))
        for row, (name, subject_type, usage, latest) in enumerate(rows):
            self._write_table_row(
                self.usage_details_table,
                row,
                (name, subject_type, f"{usage:,.0f}", latest),
            )

    def _set_usage_display_mode(self, _index: int) -> None:
        is_trend = self.usage_display_mode.currentData() == "trend"
        self.usage_details_table.setVisible(not is_trend)
        self.usage_trend_chart.setVisible(is_trend)

    def _render_usage_trend(self, records: tuple[MonthlyUsage, ...]) -> None:
        metric = self.usage_metric_tabs.tabText(self.usage_metric_tabs.currentIndex())
        buckets: dict[date, float] = {}
        for item in records:
            buckets[item.period_start] = buckets.get(item.period_start, 0.0) + self._usage_metric_value(item, metric)
        self._set_bar_chart(
            self.usage_trend_chart,
            f"{metric} trend",
            [value.strftime("%d/%m") for value in sorted(buckets)],
            ((metric, [buckets[value] for value in sorted(buckets)], "#5BC0DE"),),
        )

    def _set_management_period(self, period: str) -> None:
        for key, button in self.management_period_buttons.items():
            button.setChecked(key == period)
            button.setObjectName("btn_primary" if key == period else "btn_outline")
            button.style().unpolish(button)
            button.style().polish(button)
        self._management_period = period
        self._refresh_management_report()

    @staticmethod
    def _set_bar_chart(
        view: QChartView,
        title: str,
        labels: list[str],
        data_sets: tuple[tuple[str, list[float], str], ...],
    ) -> None:
        chart = QChart()
        chart.setTitle(title)
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        series = QBarSeries()
        maximum = 0.0
        for name, values, color in data_sets:
            values = values or [0.0]
            item = QBarSet(name)
            item.append(values)
            item.setColor(QColor(color))
            series.append(item)
            maximum = max(maximum, max(values, default=0.0))
        chart.addSeries(series)
        categories = QBarCategoryAxis()
        categories.append(labels or ["No data"])
        chart.addAxis(categories, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(categories)
        axis = QValueAxis()
        axis.setRange(0, max(1.0, maximum * 1.15))
        axis.setLabelFormat("%.0f")
        chart.addAxis(axis, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis)
        chart.legend().setVisible(len(data_sets) > 1)
        view.setChart(chart)

    def _management_records_in_range(self) -> tuple[MonthlyUsage, ...]:
        records = load_usage_history(report_slots(), granularity="daily", cache=self.cache)
        years = sorted({item.period_start.year for item in records} | {date.today().year}, reverse=True)
        current_year = self.management_year.currentData()
        self.management_year.blockSignals(True)
        self.management_year.clear()
        for year in years:
            self.management_year.addItem(str(year), year)
        index = self.management_year.findData(current_year if current_year in years else date.today().year)
        self.management_year.setCurrentIndex(max(0, index))
        self.management_year.blockSignals(False)
        year = int(self.management_year.currentData() or date.today().year)
        period = getattr(self, "_management_period", "year")
        month_ranges = {
            "year": (1, 12), "q1": (1, 3), "q2": (4, 6),
            "q3": (7, 9), "q4": (10, 12),
        }
        first_month, last_month = month_ranges[period]
        start = date(year, first_month, 1)
        end = date(year, last_month, 31 if last_month in {1, 3, 5, 7, 8, 10, 12} else 30)
        if last_month == 2:
            end = date(year, 2, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28)
        return tuple(item for item in records if start <= item.period_start <= end)

    def _refresh_management_report(self, *_args) -> None:
        if not hasattr(self, "management_printed_table"):
            return
        records = self._management_records_in_range()
        year = self.management_year.currentData() or date.today().year
        self.management_title.setText(f"Company overview · {year}")
        months = sorted({item.period_start.replace(day=1) for item in records})
        labels = [month.strftime("%b") for month in months]
        color_values = [
            sum(
                self._record_total(item, "a3_color") + self._record_total(item, "a4_color")
                for item in records if item.period_start.replace(day=1) == month
            )
            for month in months
        ]
        bw_values = [
            sum(
                self._record_total(item, "a3_bw") + self._record_total(item, "a4_bw")
                for item in records if item.period_start.replace(day=1) == month
            )
            for month in months
        ]
        a4_values = [
            sum(
                self._record_total(item, "a4_color") + self._record_total(item, "a4_bw")
                for item in records if item.period_start.replace(day=1) == month
            )
            for month in months
        ]
        a3_values = [
            sum(
                self._record_total(item, "a3_color") + self._record_total(item, "a3_bw")
                for item in records if item.period_start.replace(day=1) == month
            )
            for month in months
        ]
        self._set_bar_chart(
            self.management_color_chart,
            "B/W vs Color trend",
            labels,
            (("B/W", bw_values, "#6B7280"), ("Color", color_values, "#E76F51")),
        )
        self._set_bar_chart(
            self.management_size_chart,
            "A4 vs A3 trend",
            labels,
            (("A4", a4_values, "#5BC0DE"), ("A3", a3_values, "#8E7CC3")),
        )
        self._render_management_printed_pages(records)
        self._render_management_rankings(records)
        self.report_updated_at.setText(f"Updated {datetime.now():%d/%m/%Y %H:%M}")

    def _render_management_printed_pages(self, records: tuple[MonthlyUsage, ...]) -> None:
        a4_color = sum(self._record_total(item, "a4_color") for item in records)
        a4_bw = sum(self._record_total(item, "a4_bw") for item in records)
        a3_color = sum(self._record_total(item, "a3_color") for item in records)
        a3_bw = sum(self._record_total(item, "a3_bw") for item in records)
        cost_available = all(
            item.provisional_cost_available or not item.provisional_days
            for item in records
        )
        total_cost = sum(self._record_total(item, "net_cost") for item in records)
        rows = (
            ("B/W", a4_bw, "—", a3_bw, "—", a4_bw + a3_bw, "—"),
            ("Color", a4_color, "—", a3_color, "—", a4_color + a3_color, "—"),
            (
                "Total", a4_bw + a4_color, "—", a3_bw + a3_color, "—",
                a4_bw + a4_color + a3_bw + a3_color,
                f"{total_cost:,.2f}" if cost_available else "—",
            ),
        )
        self.management_printed_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            self._write_table_row(
                self.management_printed_table,
                row,
                tuple(
                    value if isinstance(value, str) else f"{value:,.0f}"
                    for value in values
                ),
                bold=row == len(rows) - 1,
            )

    def _render_management_rankings(self, records: tuple[MonthlyUsage, ...]) -> None:
        devices = {device.slot: device for device in self.repository.list(enabled_only=False)}
        grouped: dict[tuple[int, str], list[MonthlyUsage]] = {}
        for item in records:
            grouped.setdefault((item.device_slot, self._record_device_identity(item)), []).append(item)
        device_rows: list[tuple[str, float, float | None]] = []
        for (slot, _identity), items in grouped.items():
            configured = devices.get(slot)
            label = (
                items[0].device_name_snapshot
                or (configured.name if configured is not None else "")
                or f"Slot {slot + 1}"
            )
            usage = sum(self._record_total(item, "total") for item in items)
            known_cost = all(item.provisional_cost_available or not item.provisional_days for item in items)
            cost = sum(self._record_total(item, "net_cost") for item in items) if known_cost else None
            device_rows.append((label, usage, cost))
        self._fill_ranking_table(self.management_top_devices_table, device_rows)

        years = {item.period_start.year for item in records}
        user_rows: dict[tuple[str, str], list[SubjectPeriodUsage]] = {}
        for item in load_subject_history(report_slots(), cache=self.subject_cache):
            if item.period_start.year in years:
                user_rows.setdefault((item.subject_type, item.subject_id), []).append(item)
        ranked_users = [
            (items[0].subject_name, sum(item.period_usage for item in items), None)
            for items in user_rows.values()
        ]
        self._fill_ranking_table(self.management_top_users_table, ranked_users)

    def _fill_ranking_table(
        self,
        table: QTableWidget,
        rows: list[tuple[str, float, float | None]],
    ) -> None:
        rows = sorted(rows, key=lambda item: item[1], reverse=True)[:5]
        table.setRowCount(len(rows))
        for row, (label, usage, cost) in enumerate(rows):
            self._write_table_row(
                table, row, (label, f"{usage:,.0f}", f"{cost:,.2f}" if cost is not None else "—")
            )

    def _meter_rows_for_period(
        self,
    ) -> list[tuple[DeviceConfig, str, str, dict[str, float], dict[str, float], dict[str, float]]]:
        selected_slot = self.meter_device_filter.currentData()
        devices = [
            device
            for device in self.repository.list(enabled_only=True)
            if selected_slot is None or device.slot == selected_slot
        ]
        rows: list[
            tuple[DeviceConfig, str, str, dict[str, float], dict[str, float], dict[str, float]]
        ] = []
        for device in devices:
            state = self.cache.load(device.slot, date.today()) or {}
            opening = state.get("opening") if isinstance(state.get("opening"), dict) else {}
            latest = state.get("latest") if isinstance(state.get("latest"), dict) else {}
            delta = state.get("delta") if isinstance(state.get("delta"), dict) else {}
            first = str(state.get("first_success") or "")
            last = str(state.get("last_success") or "")
            if not latest:
                with _open(commit=False) as conn:
                    row = conn.execute(
                        """SELECT opening_json,closing_json,first_success,last_success
                           FROM daily_meter_records WHERE device_slot=?
                           ORDER BY record_date DESC LIMIT 1""",
                        (device.slot,),
                    ).fetchone()
                if row is not None:
                    try:
                        opening = json.loads(row[0])
                        latest = json.loads(row[1])
                    except (TypeError, json.JSONDecodeError):
                        opening, latest = {}, {}
                    first, last = str(row[2] or ""), str(row[3] or "")
            rows.append(
                (
                    device,
                    first or "—",
                    last or "—",
                    {str(key): float(value) for key, value in opening.items()},
                    {str(key): float(value) for key, value in latest.items()},
                    {str(key): float(value) for key, value in delta.items()},
                )
            )
        return rows

    def _refresh_meter_report(self, *_args) -> None:
        if not hasattr(self, "meter_table"):
            return
        self._populate_report_device_filters()
        rows = self._meter_rows_for_period()
        counter_keys = sorted(
            {
                key
                for _device, _first, _last, opening, latest, delta in rows
                for values in (opening, latest, delta)
                for key in values
            }
        )
        labels = ["Device", "First readout", "Last readout"] + [
            key.removeprefix("counter.").replace("_", " ").title()
            for key in counter_keys
        ]
        self.meter_table.setColumnCount(len(labels))
        self.meter_table.setHorizontalHeaderLabels(labels)
        self.meter_table.setRowCount(len(rows))
        self.meter_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.meter_table.verticalHeader().setVisible(False)
        for column in range(len(labels)):
            self.meter_table.setColumnWidth(column, 150 if column < 3 else 122)
        daily = self.meter_readout_type.currentData() == "daily"
        for row, (device, first, last, opening, latest, delta) in enumerate(rows):
            def value_for(key: str) -> str:
                if daily:
                    return f"{delta[key]:,.0f}" if key in delta else "—"
                if key in opening and key in latest:
                    return f"{opening[key]:,.0f}\n{latest[key]:,.0f}"
                return f"{latest[key]:,.0f}" if key in latest else "—"
            display = (device.name, first, last) + tuple(
                value_for(key) for key in counter_keys
            )
            self._write_table_row(self.meter_table, row, display)
        self._render_meter_history()
        self.report_updated_at.setText(f"Updated {datetime.now():%d/%m/%Y %H:%M}")

    def _render_meter_history(self) -> None:
        period = self.meter_period_filter.currentData()
        days = {"today": 1, "week": 7, "month": 30}.get(period, 1)
        start = date.today() - timedelta(days=days - 1)
        selected_slot = self.meter_device_filter.currentData()
        devices = {device.slot: device for device in self.repository.list(enabled_only=False)}
        query = """SELECT device_slot,record_date,first_success,last_success,closing_json
                   FROM daily_meter_records WHERE record_date>=?"""
        params: list[object] = [start.isoformat()]
        if selected_slot is not None:
            query += " AND device_slot=?"
            params.append(selected_slot)
        query += " ORDER BY record_date DESC,device_slot LIMIT 60"
        with _open(commit=False) as conn:
            records = conn.execute(query, params).fetchall()
        self.meter_history_table.setRowCount(len(records))
        for row, (slot, record_date, first, last, closing_json) in enumerate(records):
            try:
                closing = json.loads(closing_json)
            except (TypeError, json.JSONDecodeError):
                closing = {}
            device = devices.get(int(slot))
            total = closing.get("counter.total.total") if isinstance(closing, dict) else None
            self._write_table_row(
                self.meter_history_table,
                row,
                (
                    device.name if device else f"Slot {int(slot) + 1}",
                    str(record_date),
                    str(first or "—"),
                    str(last or "—"),
                    f"{float(total):,.0f}" if total is not None else "—",
                ),
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
            "background:#EEF6F9;color:#245268;padding:8px 10px;"
            "border:1px solid #D7E7EC;"
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
                        xs, displayed_totals, running_bases
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
                zip(xs, heights, bases)
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
                f"ไม่สามารถบันทึกไฟล์ได้\n{error}",
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
            "QFrame#reports_header{background:#ECF3F8;border:1px solid #C3D2DF;"
            "border-radius:8px;}"
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        description = QLabel("Report")
        description.setFont(fnt(F_SM, True))
        description.setWordWrap(True)
        description.setMinimumWidth(0)
        description.setStyleSheet("color:#123262;")
        layout.addWidget(description)
        self.report_profile_combo = QComboBox()
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
            "QFrame#report_advanced_panel{background:#F8FAFC;border:1px solid #C9D5E1;"
            "border-radius:8px;}"
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
        advanced_note.setStyleSheet("color:#64748B;border:none;")
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
            "background:#FFF1F1;color:#B42318;padding:9px 11px;"
            "border:1px solid #FDA29B;border-radius:5px;font-weight:700;"
        )
        layout.addWidget(self.reports_error)

        self.report_period_note = QLabel("")
        self.report_period_note.setWordWrap(True)
        self.report_period_note.setStyleSheet(
            "background:#EEF6F9;color:#245268;padding:8px 10px;border-radius:5px;"
        )
        self.report_period_note.setVisible(False)
        layout.addWidget(self.report_period_note)

        self.report_provisional_summary = QLabel("")
        self.report_provisional_summary.setWordWrap(True)
        self.report_provisional_summary.setVisible(False)
        self.report_provisional_summary.setStyleSheet(
            "background:#DCEEFF;color:#074F8C;padding:9px 11px;"
            "border-left:4px solid #0B75C9;"
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
                "background:white;border:1px solid #C9D5E1;border-radius:8px;"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(13, 10, 13, 10)
            card_layout.setSpacing(3)
            caption = QLabel(label)
            caption.setStyleSheet("color:#4C6378;border:none;")
            value = QLabel("—")
            value.setFont(fnt(F_MD, True))
            value.setStyleSheet(f"color:{color};border:none;")
            suffix = QLabel(unit)
            suffix.setStyleSheet("color:#5B7084;border:none;font-size:11px;")
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
            "background:#F8FAFC;color:#344054;padding:7px 10px;"
            "border:1px solid #E4E7EC;border-radius:5px;"
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
                "color:#667085;padding:2px 0;"
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
                    max(previous[1], record.latest_total),
                    record.subject_type,
                    device_label,
                    device_tooltip,
                )
        top_subjects = sorted(subject_rows.values(), key=lambda item: item[1], reverse=True)[:8]
        self.report_users.clearSpans()
        self.report_users.setRowCount(max(1, len(top_subjects)))
        if not top_subjects:
            empty = QTableWidgetItem("ไม่พบ User Authentication / Account Track ในรอบบิลนี้")
            empty.setForeground(QColor(C_TEXT2))
            self.report_users.setItem(0, 0, empty)
            self.report_users.setSpan(0, 0, 1, 2)
        for row, (name, usage, subject_type, device_label, device_tooltip) in enumerate(top_subjects):
            self.report_users.setRowHeight(row, 42)
            for column, text in enumerate(
                (
                    f"{name}\n{device_label}",
                    f"{usage:,.0f}",
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
                "color:#B42318;padding:2px 0;font-weight:600;"
            )
        else:
            self._report_overview_review_detail = ""
            self.report_overview_warning.clear()
            self.report_overview_warning.setVisible(False)

    def refresh(self) -> None:
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
                "background:#FFF1F1;color:#B42318;padding:8px 10px;font-weight:700;"
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
        self.users_boundary.setStyleSheet("background:#EEF6F9;color:#245268;padding:8px 10px;")
        layout.addWidget(self.users_boundary)

        self.users_reconciliation = QLabel("ยังไม่มีข้อมูล User/Account สำหรับตรวจ Coverage")
        self.users_reconciliation.setWordWrap(True)
        self.users_reconciliation.setStyleSheet("background:#F8FAFC;color:#64748B;padding:8px 10px;")
        layout.addWidget(self.users_reconciliation)

        self.lbl_count_users = QLabel("")
        self.lbl_count_users.setStyleSheet(f"color:{C_TEXT2};")
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
                        (record.latest_total for record in identity_records),
                        default=0.0,
                    )
                    item.setToolTip(
                        f"{group['tooltip']}\n"
                        f"Usage รอบบิล: {period_usage:,.0f}\n"
                        f"Total Counter ล่าสุด: {latest_total:,.0f}\n"
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
                "background:#FFF1F1;color:#B42318;padding:8px 10px;font-weight:700;"
            )
        else:
            self.users_reconciliation.setText(
                "Coverage เป็นข้อมูลประกอบและไม่จำเป็นต้องครบ 100%\n" + "\n".join(details)
            )
            self.users_reconciliation.setStyleSheet("background:#EEF6F9;color:#245268;padding:8px 10px;")

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
        explanation.setStyleSheet("background:#EEF6F9;color:#245268;padding:8px 10px;")
        layout.addWidget(explanation)

        self.current_status = QLabel("")
        self.current_status.setWordWrap(True)
        self.current_status.setStyleSheet(f"color:{C_TEXT2};font-size:11px;")
        layout.addWidget(self.current_status)

        self.tbl_current_all = FrozenLeftTable()
        self.tbl_current_all.setAlternatingRowColors(False)
        layout.addWidget(self.tbl_current_all, 1)

        self.current_source_note = QLabel(
            "ค่ามิเตอร์ทั้งหมดอ่านจาก Web Connection Device Meter; SNMP ใช้ตรวจสถานะ/trigger เท่านั้น "
            "และจะคงค่า Web ล่าสุดเมื่อเครื่อง Offline"
        )
        self.current_source_note.setWordWrap(True)
        self.current_source_note.setStyleSheet(f"color:{C_TEXT2};padding:3px 2px;")
        self.current_source_note.setVisible(False)
        layout.addWidget(self.current_source_note)

    def _build_monthly_tab(self) -> None:
        layout = QVBoxLayout(self.tab_monthly)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

        self.lbl_billing_day = QLabel("")
        self.lbl_billing_day.setStyleSheet("background:#EEF6F9;color:#245268;padding:8px 10px;")
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
        self.monthly_summary.setStyleSheet("background:#F8FAFC;color:#123262;padding:9px 12px;font-weight:700;")
        layout.addWidget(self.monthly_summary)

        note = QLabel(
            "เลือกดูรายวัน รายสัปดาห์ รายเดือน รายไตรมาส หรือรายปี · "
            "Usage และค่าใช้จ่ายมาจาก Posted Ledger เท่านั้น · "
            "Pricelist, ส่วนลด, Cost category และรอบบิลยึดค่าที่บันทึกของแต่ละวัน"
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C_TEXT2};")
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
        if any_provisional:
            quality_parts.append("วันนี้เป็นข้อมูลระหว่างวัน ยังไม่ลง Billing Ledger")
        if not periods:
            self.monthly_summary.setText(
                "ยังไม่มี Posted Ledger สำหรับมุมมองนี้ · ไม่มีการคำนวณยอดหรือค่าใช้จ่าย"
            )
            self.monthly_summary.setStyleSheet(
                "background:#F2F4F7;color:#475467;padding:9px 12px;font-weight:700;"
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
                "background:#FFF4E5;color:#8A4B08;padding:9px 12px;font-weight:700;"
                if quality_parts
                else "background:#F8FAFC;color:#123262;padding:9px 12px;font-weight:700;"
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


class ScheduleTimeRangeEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, start: time, end: time, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.start = QTimeEdit(start)
        self.end = QTimeEdit(end)
        for control in (self.start, self.end):
            control.setDisplayFormat("HH:mm")
            control.setMinimumWidth(82)
            control.setMinimumHeight(32)
            control.timeChanged.connect(self.changed)
        arrow = QLabel("–")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet("color:#64748B;background:transparent;border:none;")
        layout.addWidget(self.start)
        layout.addWidget(arrow)
        layout.addWidget(self.end)

    def values(self) -> tuple[time, time]:
        start = self.start.time()
        end = self.end.time()
        return time(start.hour(), start.minute()), time(end.hour(), end.minute())


class WeekdaySelector(QWidget):
    changed = pyqtSignal()
    LABELS = ("M", "T", "W", "TH", "F", "SA", "SU")
    ACCESSIBLE_LABELS = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )

    def __init__(self, weekdays: frozenset[int], parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.boxes: list[QCheckBox] = []
        for index, label in enumerate(self.LABELS):
            box = QCheckBox(label)
            box.setChecked(index in weekdays)
            box.setToolTip(self.ACCESSIBLE_LABELS[index])
            box.setAccessibleName(self.ACCESSIBLE_LABELS[index])
            box.setStyleSheet("QCheckBox{font-size:10px;spacing:1px;padding:0 1px;}")
            box.toggled.connect(self.changed)
            layout.addWidget(box)
            self.boxes.append(box)

    def values(self) -> frozenset[int]:
        return frozenset(index for index, box in enumerate(self.boxes) if box.isChecked())


class WebAccessCodeDialog(QDialog):
    """Simple owner-only dialog for setting the LAN Web access code."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ตั้งรหัสเข้า Web Report")
        self.setModal(True)
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("รหัสสำหรับเครื่องอื่นใน LAN")
        title.setFont(fnt(F_LG, True))
        title.setStyleSheet("color:#102A43;border:none;")
        layout.addWidget(title)
        description = QLabel(
            "ผู้ใช้ที่เปิด Web Report จากเครื่องอื่นต้องใช้รหัสนี้ เมื่อเปลี่ยนแล้วทุกเครื่องจะต้องเข้าสู่ระบบใหม่"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color:#52677D;border:none;")
        layout.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.access_code = QLineEdit()
        self.access_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_code.setMaxLength(128)
        self.access_code.setPlaceholderText(f"อย่างน้อย {MIN_ACCESS_CODE_LENGTH} ตัวอักษร")
        self.access_code.setAccessibleName("รหัส Web ใหม่")
        self.confirm_code = QLineEdit()
        self.confirm_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_code.setMaxLength(128)
        self.confirm_code.setPlaceholderText("กรอกรหัสเดิมอีกครั้ง")
        self.confirm_code.setAccessibleName("ยืนยันรหัส Web ใหม่")
        form.addRow("รหัสใหม่", self.access_code)
        form.addRow("ยืนยันรหัส", self.confirm_code)
        layout.addLayout(form)

        show_code = QCheckBox("แสดงรหัสที่กำลังกรอก")
        show_code.toggled.connect(self._toggle_code_visibility)
        layout.addWidget(show_code)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            "color:#B42318;background:#FEF3F2;border:1px solid #F2B8B5;border-radius:6px;padding:8px 10px;"
        )
        self.error.hide()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText("บันทึกรหัสใหม่")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_language(self)

    def _toggle_code_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.access_code.setEchoMode(mode)
        self.confirm_code.setEchoMode(mode)

    def _validate_and_accept(self) -> None:
        try:
            validate_web_access_code(self.access_code.text())
        except ValueError as error:
            self.error.setText(translate_text(str(error)))
            self.error.show()
            self.access_code.setFocus()
            return
        if self.access_code.text() != self.confirm_code.text():
            self.error.setText(
                tr(
                    "รหัสใหม่และช่องยืนยันไม่ตรงกัน",
                    "The new code and confirmation do not match",
                )
            )
            self.error.show()
            self.confirm_code.setFocus()
            return
        self.error.hide()
        self.accept()

    def value(self) -> str:
        return self.access_code.text()


class PageFleetSettings(QWidget):
    changed = pyqtSignal()
    billing_audit_requested = pyqtSignal()
    activity_requested = pyqtSignal()
    advanced_tools_requested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        registration_runtime=None,
        offline_license_public_keys: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = DeviceConfigRepository()
        self.registration_runtime = registration_runtime
        self.offline_license_public_keys = dict(offline_license_public_keys or {})
        self.web_service = web_service_manager()
        self._dirty_sections: set[str] = set()
        self._active_editor: str | None = None
        self._loading_config = False
        self._task_editors: dict[str, QFrame] = {}
        self._task_buttons: dict[str, QPushButton] = {}
        self._task_closed_labels: dict[str, str] = {}
        self._setup_wizard_dialog: SetupWizardV5 | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 20, 26, 26)
        layout.setSpacing(11)

        header = QFrame()
        header.setObjectName("settings_header")
        header.setStyleSheet("QFrame#settings_header{background:transparent;border:none;} QLabel{border:none;}")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_copy = QVBoxLayout()
        title = QLabel("ตั้งค่าการใช้งาน")
        title.setFont(fnt(F_2XL, True))
        title.setStyleSheet("color:#102A43;border:none;")
        subtitle = QLabel("ถ้าระบบทำงานปกติ คุณไม่จำเป็นต้องเปลี่ยนค่าใด")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#52677D;border:none;")
        header_copy.addWidget(title)
        header_copy.addWidget(subtitle)
        header_layout.addLayout(header_copy, 1)
        layout.addWidget(header)

        device_card, self.device_summary, edit_devices = self._action_task(
            "เครื่องพิมพ์และราคา",
            "กำลังโหลดข้อมูล…",
            "เปลี่ยน",
        )
        self.device_summary.setAccessibleName("รายชื่อเครื่องพิมพ์ที่ใช้งาน")
        choose = btn("ข้อมูลที่ใช้ในรายงาน", "outline")
        choose.clicked.connect(self._choose_counters)
        device_row = device_card.layout().itemAt(0).layout()
        if device_row is not None:
            device_row.insertWidget(1, choose, 0, Qt.AlignmentFlag.AlignVCenter)
        edit_devices.clicked.connect(self._edit_devices)
        layout.addWidget(device_card)

        registration_card, self.registration_summary, self.registration_retry_button = self._action_task(
            "การลงทะเบียนและความเป็นส่วนตัว",
            "กำลังตรวจสอบสถานะ…",
            "ลองส่งอีกครั้ง",
        )
        self.registration_summary.setAccessibleName("สถานะการลงทะเบียนโปรแกรม")
        self.registration_retry_button.setAccessibleName("ลองส่งข้อมูลลงทะเบียนอีกครั้ง")
        self.registration_retry_button.clicked.connect(self._retry_registration)
        registration_row = registration_card.layout().itemAt(0).layout()
        self.registration_privacy_button = btn("ดูข้อมูลที่ส่ง", "outline")
        self.registration_privacy_button.setAccessibleName("เปิดดูประกาศข้อมูลการลงทะเบียน")
        self.registration_privacy_button.clicked.connect(self._show_registration_privacy)
        if registration_row is not None:
            registration_row.insertWidget(
                1,
                self.registration_privacy_button,
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
        self.registration_notice_accept = QCheckBox(
            tr(
                "ฉันได้อ่านและรับทราบข้อมูลการลงทะเบียนเวอร์ชันปัจจุบัน",
                "I have read and acknowledge the current Registration Data Notice",
            )
        )
        self.registration_notice_accept.setAccessibleName(
            tr(
                "รับทราบข้อมูลการลงทะเบียนเวอร์ชันปัจจุบัน",
                "Acknowledge the current Registration Data Notice",
            )
        )
        self.registration_notice_accept.clicked.connect(self._accept_registration_notice)
        registration_card.layout().addWidget(self.registration_notice_accept)

        registration_mode_row = QHBoxLayout()
        registration_mode_label = QLabel(tr("โหมดการลงทะเบียน", "Registration mode"))
        registration_mode_label.setStyleSheet("color:#334155;font-weight:700;border:none;")
        registration_mode_row.addWidget(registration_mode_label)
        self.registration_mode_group = QButtonGroup(self)
        self.registration_mode_group.setExclusive(True)
        self.registration_online_mode = QRadioButton(
            tr("ออนไลน์ · ลงทะเบียนอัตโนมัติ", "Online · automatic registration")
        )
        self.registration_online_mode.setAccessibleName(
            tr("เลือกรับบริการแบบออนไลน์", "Use Online Registration")
        )
        self.registration_offline_mode = QRadioButton(
            tr("ออฟไลน์ · ใช้ไฟล์ License", "Offline · use a license file")
        )
        self.registration_offline_mode.setAccessibleName(
            tr("เลือกใช้งานแบบ Offline License", "Use an Offline License")
        )
        self.registration_mode_group.addButton(self.registration_online_mode)
        self.registration_mode_group.addButton(self.registration_offline_mode)
        registration_mode_row.addWidget(self.registration_online_mode)
        registration_mode_row.addWidget(self.registration_offline_mode)
        registration_mode_row.addStretch()
        registration_card.layout().addLayout(registration_mode_row)
        self.registration_online_mode.clicked.connect(lambda: self._set_registration_mode("online"))
        self.registration_offline_mode.clicked.connect(lambda: self._set_registration_mode("offline"))

        self.offline_license_summary = QLabel()
        self.offline_license_summary.setWordWrap(True)
        self.offline_license_summary.setAccessibleName(
            tr("สถานะ Offline License", "Offline License status")
        )
        self.offline_license_summary.setStyleSheet(
            "color:#52677D;background:#F8FAFC;border:1px solid #D6E0EA;"
            "border-radius:6px;padding:8px 10px;"
        )
        registration_card.layout().addWidget(self.offline_license_summary)
        offline_actions = QHBoxLayout()
        self.offline_request_button = btn(tr("สร้างไฟล์คำขอ…", "Export request…"), "outline")
        self.offline_request_button.setAccessibleName(
            tr("สร้างคำขอ Offline License", "Export Offline License request")
        )
        self.offline_request_button.clicked.connect(self._export_offline_request)
        offline_actions.addWidget(self.offline_request_button)
        self.offline_import_button = btn(tr("นำเข้า License…", "Import license…"), "outline")
        self.offline_import_button.setAccessibleName(
            tr("นำเข้าไฟล์ Offline License", "Import Offline License file")
        )
        self.offline_import_button.clicked.connect(self._import_offline_license)
        offline_actions.addWidget(self.offline_import_button)
        offline_actions.addStretch()
        registration_card.layout().addLayout(offline_actions)
        layout.addWidget(registration_card)

        (
            billing_card,
            self.billing_summary,
            self.billing_editor,
            self.billing_toggle,
        ) = self._expandable_task(
            "billing",
            "รอบบิล",
            "กำลังโหลดข้อมูล…",
            closed_action="แก้ไข",
        )
        billing_body = self.billing_editor.layout()
        billing_grid = QGridLayout()
        billing_grid.setHorizontalSpacing(24)
        billing_grid.setVerticalSpacing(10)
        billing_grid.setColumnStretch(0, 1)
        billing_grid.setColumnStretch(1, 1)
        self.billing_day = QSpinBox()
        self.billing_day.setRange(1, 31)
        self.billing_day.setSuffix(" ของเดือน")
        self.billing_day.setAccessibleName("วันสิ้นสุดรอบบิล")
        self.waste = QDoubleSpinBox()
        self.waste.setRange(0, 100)
        self.waste.setDecimals(1)
        self.waste.setSuffix(" %")
        self.waste.setAccessibleName("ส่วนลดกระดาษเสีย")
        billing_grid.addWidget(
            self._field("วันสิ้นสุดรอบบิล", self.billing_day, "ถ้าเดือนไม่มีวันที่เลือก ระบบใช้วันสุดท้ายของเดือน"),
            0,
            0,
        )
        billing_grid.addWidget(
            self._field("ส่วนลดกระดาษเสีย", self.waste, "หักออกจากยอดค่าใช้จ่ายก่อนสรุปรอบบิล"),
            0,
            1,
        )
        billing_body.addLayout(billing_grid)
        billing_impact = QLabel("การเปลี่ยนแปลงมีผลกับรายการใหม่เท่านั้น และไม่แก้ยอดย้อนหลัง")
        billing_impact.setWordWrap(True)
        billing_impact.setStyleSheet(
            "color:#75510A;background:#FFF7E8;border:1px solid #F2C879;"
            "border-radius:6px;padding:8px 10px;"
        )
        billing_body.addWidget(billing_impact)
        (
            self.billing_save_status,
            billing_actions,
            self.billing_save_button,
        ) = self._editor_actions(
            "บันทึกรอบบิลและตรวจสอบ",
            self._save_billing,
            lambda: self._cancel_section("billing"),
        )
        billing_body.addLayout(billing_actions)
        layout.addWidget(billing_card)

        (
            schedule_card,
            self.schedule_task_summary,
            self.schedule_task_editor,
            self.schedule_toggle,
        ) = self._expandable_task(
            "schedule",
            "การอ่านข้อมูลอัตโนมัติ",
            "กำลังโหลดข้อมูล…",
            closed_action="จัดเวลา",
        )
        schedule_body = self.schedule_task_editor.layout()
        self.autostart = QCheckBox("เปิดโปรแกรมอัตโนมัติเมื่อเข้าสู่ระบบ")
        self.autostart.setAccessibleName("เปิดโปรแกรมอัตโนมัติเมื่อเข้าสู่ระบบ")
        schedule_body.addWidget(self.autostart)
        self.autostart_status = QLabel()
        self.autostart_status.setWordWrap(True)
        schedule_body.addWidget(self.autostart_status)
        self.schedule = QLabel()
        self.schedule.setWordWrap(True)
        self.schedule.setMinimumHeight(54)
        self.schedule.setAccessibleName("สรุปเวลาการอ่านข้อมูลอัตโนมัติ")
        self.schedule.setStyleSheet(
            "background:#EEF6F9;color:#245268;border:1px solid #C9DFE8;border-radius:7px;padding:10px 12px;"
        )
        schedule_body.addWidget(self.schedule)
        self.advanced_schedule_button = btn(
            tr("ปรับเวลาแบบละเอียด", "Edit detailed schedule"),
            "outline",
        )
        self.advanced_schedule_button.setCheckable(True)
        self.advanced_schedule_button.setAccessibleName(
            tr(
                "แสดงหรือซ่อนการตั้งเวลาแบบละเอียด",
                "Show or hide the detailed schedule",
            )
        )
        self.advanced_schedule_button.toggled.connect(self._toggle_schedule_editor)
        schedule_body.addWidget(self.advanced_schedule_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.schedule_editor = QFrame()
        self.schedule_editor.setObjectName("schedule_editor")
        self.schedule_editor.setStyleSheet("QFrame#schedule_editor{background:#F8FAFC;border:none;}")
        schedule_editor_layout = QVBoxLayout(self.schedule_editor)
        schedule_editor_layout.setContentsMargins(10, 10, 10, 10)
        schedule_editor_layout.setSpacing(8)
        schedule_hint = QLabel(
            tr(
                "สำหรับเจ้าหน้าที่: กำหนดช่วงเวลา วัน และความถี่แยกตามแหล่งข้อมูล หากไม่แน่ใจให้ใช้ค่าเดิม",
                "For staff: set time ranges, days, and reading intervals. Keep the defaults if you are unsure.",
            )
        )
        schedule_hint.setWordWrap(True)
        schedule_hint.setStyleSheet("color:#64748B;border:none;")
        schedule_editor_layout.addWidget(schedule_hint)
        self.schedule_windows_table = QTableWidget(0, 6)
        self.schedule_windows_table.setHorizontalHeaderLabels(
            [
                tr("ชื่อช่วงเวลา", "Window name"),
                tr("เริ่ม–สิ้นสุด", "Start–end"),
                tr("วันที่ทำงาน", "Days"),
                tr("ตรวจสถานะ", "Status check"),
                tr("อ่านมิเตอร์", "Meter read"),
                "",
            ]
        )
        self.schedule_windows_table.setAccessibleName(
            tr("ตารางเวลาการอ่านข้อมูลแบบละเอียด", "Detailed reading schedule")
        )
        self.schedule_windows_table.verticalHeader().setVisible(False)
        self.schedule_windows_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.schedule_windows_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.schedule_windows_table.setMinimumHeight(250)
        self.schedule_windows_table.setMaximumHeight(390)
        header = self.schedule_windows_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.schedule_windows_table.setColumnWidth(5, 112)
        schedule_editor_layout.addWidget(self.schedule_windows_table)
        self.add_schedule_window_button = btn(
            tr("เพิ่มช่วงเวลา", "Add time window"),
            "outline",
        )
        self.add_schedule_window_button.clicked.connect(self._add_schedule_window)
        schedule_editor_layout.addWidget(self.add_schedule_window_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._schedule_row_controls: list[
            tuple[QLineEdit, ScheduleTimeRangeEditor, WeekdaySelector, QSpinBox, QSpinBox]
        ] = []
        self.schedule_editor.hide()
        schedule_body.addWidget(self.schedule_editor)
        (
            self.schedule_save_status,
            schedule_actions,
            self.schedule_save_button,
        ) = self._editor_actions(
            "บันทึกเวลาและตรวจสอบ",
            self._save_schedule,
            lambda: self._cancel_section("schedule"),
        )
        schedule_body.addLayout(schedule_actions)
        layout.addWidget(schedule_card)

        (
            program_card,
            self.web_task_summary,
            self.web_task_editor,
            self.web_toggle,
        ) = self._expandable_task(
            "web",
            "รายงานจากเครื่องอื่นใน LAN",
            "กำลังตรวจสอบสถานะ…",
            closed_action="จัดการ",
        )
        program_body = self.web_task_editor.layout()
        self.web_service_enabled = QCheckBox("อนุญาตให้เครื่องอื่นใน LAN เปิดดูรายงาน")
        self.web_service_enabled.setAccessibleName("เปิดรายงานผ่าน Web สำหรับเครื่องอื่นใน LAN")
        program_body.addWidget(self.web_service_enabled)
        self.web_service_status = QLabel()
        self.web_service_status.setWordWrap(True)
        program_body.addWidget(self.web_service_status)
        self.web_service_url = QLabel()
        self.web_service_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.web_service_url.setWordWrap(True)
        self.web_service_url.setAccessibleName("ที่อยู่ Web Report สำหรับเครื่องอื่นใน LAN")
        self.web_service_url.setStyleSheet(
            "color:#245268;background:#EEF6F9;border:1px solid #C9DFE8;"
            "border-radius:7px;padding:9px 11px;font-weight:700;"
        )
        program_body.addWidget(self.web_service_url)
        web_security = QFrame()
        web_security.setObjectName("web_security")
        web_security.setStyleSheet(
            "QFrame#web_security{background:#F8FAFC;border:1px solid #D6E0EA;border-radius:7px;}"
            "QLabel{background:transparent;border:none;}"
        )
        web_security_layout = QHBoxLayout(web_security)
        web_security_layout.setContentsMargins(11, 9, 11, 9)
        web_security_copy = QVBoxLayout()
        web_security_title = QLabel("รหัสเข้า Web Report")
        web_security_title.setStyleSheet("color:#334155;font-weight:700;")
        self.web_access_status = QLabel()
        self.web_access_status.setWordWrap(True)
        self.web_access_status.setAccessibleName("สถานะรหัสเข้า Web Report")
        web_security_copy.addWidget(web_security_title)
        web_security_copy.addWidget(self.web_access_status)
        web_security_layout.addLayout(web_security_copy, 1)
        immediate = QLabel("มีผลทันที")
        immediate.setStyleSheet(
            "color:#8A4B08;background:#FFF7E8;border:1px solid #F2C879;"
            "border-radius:10px;padding:4px 8px;font-weight:700;"
        )
        immediate.setAccessibleName("การเปลี่ยนรหัสมีผลทันที")
        web_security_layout.addWidget(immediate)
        self.change_web_access_button = btn("เปลี่ยนรหัส Web", "outline")
        self.change_web_access_button.setAccessibleName("ตั้งหรือเปลี่ยนรหัสเข้า Web Report")
        self.change_web_access_button.clicked.connect(self._change_web_access_code)
        web_security_layout.addWidget(self.change_web_access_button)
        program_body.addWidget(web_security)
        web_actions = QHBoxLayout()
        self.open_web_button = btn("เปิดหน้า Web", "outline")
        self.open_web_button.clicked.connect(self._open_web)
        web_actions.addWidget(self.open_web_button)
        self.copy_web_button = btn("คัดลอกที่อยู่ LAN", "outline")
        self.copy_web_button.clicked.connect(self._copy_lan_url)
        web_actions.addWidget(self.copy_web_button)
        web_actions.addStretch()
        program_body.addLayout(web_actions)
        (
            self.web_save_status,
            web_save_actions,
            self.web_save_button,
        ) = self._editor_actions(
            "บันทึกและตรวจสอบ LAN",
            self._save_web,
            lambda: self._cancel_section("web"),
        )
        program_body.addLayout(web_save_actions)
        layout.addWidget(program_card)

        (
            support_card,
            self.support_summary,
            self.support_task_editor,
            self.support_section_toggle,
        ) = self._expandable_task(
            "support",
            "ช่วยเหลือและตรวจสอบปัญหา",
            "เลือกอาการที่พบ ระบบจะพาไปยังข้อมูลที่เกี่ยวข้อง",
            closed_action="แก้ปัญหา",
        )
        support_body = self.support_task_editor.layout()
        symptom_label = QLabel("พบปัญหาอะไร")
        symptom_label.setStyleSheet("color:#334155;font-weight:700;border:none;")
        support_body.addWidget(symptom_label)
        symptom_actions = QHBoxLayout()
        stale_button = btn("ข้อมูลไม่อัปเดต", "outline")
        stale_button.clicked.connect(self.activity_requested.emit)
        symptom_actions.addWidget(stale_button)
        mismatch_button = btn("ยอดไม่ตรง", "outline")
        mismatch_button.clicked.connect(self.billing_audit_requested.emit)
        symptom_actions.addWidget(mismatch_button)
        web_problem_button = btn("เปิด Web ไม่ได้", "outline")
        web_problem_button.clicked.connect(lambda: self._set_active_editor("web"))
        symptom_actions.addWidget(web_problem_button)
        symptom_actions.addStretch()
        support_body.addLayout(symptom_actions)

        staff_label = QLabel("ข้อมูลสำหรับเจ้าหน้าที่")
        staff_label.setStyleSheet("color:#334155;font-weight:700;border:none;margin-top:4px;")
        support_body.addWidget(staff_label)
        self.support_toggle = btn("แสดงข้อมูลสำหรับเจ้าหน้าที่", "outline")
        self.support_toggle.setCheckable(True)
        self.support_toggle.setAccessibleName("แสดงหรือซ่อนข้อมูลสำหรับเจ้าหน้าที่")
        self.support_toggle.toggled.connect(self._toggle_staff_tools)
        support_body.addWidget(self.support_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.support_details = QFrame()
        self.support_details.setObjectName("settings_support_details")
        self.support_details.setStyleSheet(
            "QFrame#settings_support_details{background:#F8FAFC;border:1px solid #D6E0EA;"
            "border-radius:8px;} QLabel{background:transparent;border:none;}"
        )
        support_details_layout = QVBoxLayout(self.support_details)
        support_details_layout.setContentsMargins(12, 12, 12, 12)
        support_details_layout.setSpacing(10)
        warning = QLabel(
            "คำเตือน: รายละเอียดบางรายการมีผลต่อฐานข้อมูลและประวัติการใช้งาน โปรดอ่านข้อความยืนยันก่อนดำเนินการ"
        )
        warning.setWordWrap(True)
        warning.setAccessibleName("คำเตือนสำหรับเครื่องมือเจ้าหน้าที่")
        warning.setStyleSheet(
            "color:#8A4B08;background:#FFF7E8;border:1px solid #F2C879;border-radius:7px;padding:9px 11px;"
        )
        support_details_layout.addWidget(warning)
        support_actions = QHBoxLayout()
        activity_button = btn("สถานะและประวัติการอ่าน", "outline")
        activity_button.clicked.connect(self.activity_requested.emit)
        support_actions.addWidget(activity_button)
        audit_button = btn("ตรวจสอบรอบบิล", "outline")
        audit_button.clicked.connect(self.billing_audit_requested.emit)
        support_actions.addWidget(audit_button)
        advanced_button = btn("เครื่องมือขั้นสูง", "outline")
        advanced_button.clicked.connect(self.advanced_tools_requested.emit)
        support_actions.addWidget(advanced_button)
        support_actions.addStretch()
        support_details_layout.addLayout(support_actions)
        self.active_database_path = QLabel()
        self.active_database_path.setWordWrap(True)
        self.active_database_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.active_database_path.setAccessibleName("ตำแหน่งฐานข้อมูลที่กำลังใช้งาน")
        self.active_database_path.setStyleSheet(
            "background:#FFFFFF;color:#52677D;border:1px solid #D6E0EA;"
            "border-radius:6px;padding:8px 10px;"
        )
        support_details_layout.addWidget(self.active_database_path)
        self.registration_support_detail = QLabel(
            tr("ยังไม่แสดงรายละเอียดทางเทคนิค", "Technical details are hidden")
        )
        self.registration_support_detail.setWordWrap(True)
        self.registration_support_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.registration_support_detail.setAccessibleName(
            tr("รายละเอียดสำหรับ Support", "Support details")
        )
        self.registration_support_detail.setStyleSheet(
            "background:#FFFFFF;color:#52677D;border:1px solid #D6E0EA;"
            "border-radius:6px;padding:8px 10px;"
        )
        support_details_layout.addWidget(self.registration_support_detail)
        shortcut_button = btn("สร้าง Shortcut ใหม่", "outline")
        shortcut_button.clicked.connect(self._create_shortcuts)
        support_details_layout.addWidget(shortcut_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.support_details.hide()
        support_body.addWidget(self.support_details)
        layout.addWidget(support_card)

        for control in (self.billing_day, self.waste):
            control.valueChanged.connect(lambda _value, section="billing": self._mark_dirty(section))
        self.autostart.toggled.connect(lambda _checked: self._mark_dirty("schedule"))
        self.web_service_enabled.toggled.connect(lambda _checked: self._mark_dirty("web"))
        self._web_status_timer = QTimer(self)
        self._web_status_timer.setInterval(2000)
        self._web_status_timer.timeout.connect(self._refresh_web_status)
        self._web_status_timer.timeout.connect(self._refresh_registration_status)
        self._web_status_timer.start()
        self.refresh_from_config()
        layout.addStretch()

    @staticmethod
    def _task_card_shell() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settings_task_card")
        card.setStyleSheet(
            "QFrame#settings_task_card{background:#FFFFFF;border:1px solid #D6E0EA;"
            "border-radius:10px;} QLabel{background:transparent;border:none;}"
        )
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 13, 16, 14)
        body.setSpacing(10)
        return card, body

    def _action_task(
        self,
        title: str,
        summary: str,
        action_text: str,
    ) -> tuple[QFrame, QLabel, QPushButton]:
        card, body = self._task_card_shell()
        row = QHBoxLayout()
        row.setSpacing(14)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        heading = QLabel(title)
        heading.setFont(fnt(F_MD, True))
        heading.setStyleSheet("color:#102A43;border:none;")
        detail = QLabel(summary)
        detail.setWordWrap(True)
        detail.setStyleSheet("color:#52677D;border:none;")
        copy.addWidget(heading)
        copy.addWidget(detail)
        row.addLayout(copy, 1)
        action = btn(action_text, "outline")
        action.setMinimumWidth(108)
        row.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(row)
        return card, detail, action

    def _expandable_task(
        self,
        key: str,
        title: str,
        summary: str,
        *,
        closed_action: str = "เปลี่ยน",
    ) -> tuple[QFrame, QLabel, QFrame, QPushButton]:
        card, body = self._task_card_shell()
        row = QHBoxLayout()
        row.setSpacing(14)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        heading = QLabel(title)
        heading.setFont(fnt(F_MD, True))
        heading.setStyleSheet("color:#102A43;border:none;")
        detail = QLabel(summary)
        detail.setWordWrap(True)
        detail.setStyleSheet("color:#52677D;border:none;")
        copy.addWidget(heading)
        copy.addWidget(detail)
        row.addLayout(copy, 1)
        toggle = btn(translate_text(closed_action), "outline")
        toggle.setCheckable(True)
        toggle.setMinimumWidth(108)
        toggle.setAccessibleName(
            tr(
                f"เปิดหรือปิด {title}",
                f"Open or close {translate_text(title)}",
            )
        )
        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(row)

        editor = QFrame()
        editor.setObjectName(f"settings_editor_{key}")
        editor.setStyleSheet(
            f"QFrame#settings_editor_{key}{{background:#F8FAFC;border:1px solid #D6E0EA;"
            "border-radius:8px;} QLabel{background:transparent;}"
        )
        editor_body = QVBoxLayout(editor)
        editor_body.setContentsMargins(13, 12, 13, 13)
        editor_body.setSpacing(10)
        editor.hide()
        body.addWidget(editor)
        self._task_editors[key] = editor
        self._task_buttons[key] = toggle
        self._task_closed_labels[key] = closed_action
        toggle.toggled.connect(
            lambda checked, task_key=key: self._task_toggle_requested(task_key, checked)
        )
        return card, detail, editor, toggle

    def _editor_actions(
        self,
        save_text: str,
        save_handler: Callable[[], None],
        cancel_handler: Callable[[], None],
    ) -> tuple[QLabel, QHBoxLayout, QPushButton]:
        row = QHBoxLayout()
        row.setSpacing(8)
        status = QLabel("ค่าปัจจุบันถูกบันทึกแล้ว")
        status.setWordWrap(True)
        status.setStyleSheet("color:#64748B;border:none;")
        row.addWidget(status, 1)
        cancel = btn("ยกเลิก", "outline")
        cancel.clicked.connect(cancel_handler)
        row.addWidget(cancel)
        save = btn(save_text, "success")
        save.setEnabled(False)
        save.clicked.connect(save_handler)
        row.addWidget(save)
        return status, row, save

    def _task_toggle_requested(self, key: str, checked: bool) -> None:
        if checked:
            self._set_active_editor(key)
        elif self._active_editor == key:
            self._set_active_editor(None)

    def _set_active_editor(self, key: str | None, *, force: bool = False) -> bool:
        current = self._active_editor
        if current == key:
            return True
        if current is not None and current in self._dirty_sections and not force:
            QMessageBox.information(
                self,
                tr("ยังไม่ได้บันทึก", "Unsaved changes"),
                tr(
                    "กรุณาบันทึกหรือยกเลิกส่วนที่กำลังแก้ก่อนเปิดส่วนอื่น",
                    "Save or cancel the section you are editing before opening another section.",
                ),
            )
            if key is not None:
                button = self._task_buttons[key]
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            if current is not None:
                current_button = self._task_buttons[current]
                current_button.blockSignals(True)
                current_button.setChecked(True)
                current_button.blockSignals(False)
            return False

        for task_key, editor in self._task_editors.items():
            visible = task_key == key
            editor.setVisible(visible)
            button = self._task_buttons[task_key]
            button.blockSignals(True)
            button.setChecked(visible)
            button.setText(
                tr("ปิด", "Close")
                if visible
                else translate_text(self._task_closed_labels[task_key])
            )
            button.blockSignals(False)
        self._active_editor = key
        return True

    def _toggle_schedule_editor(self, visible: bool) -> None:
        self.schedule_editor.setVisible(visible)
        self.advanced_schedule_button.setText(
            tr("ซ่อนการตั้งเวลาแบบละเอียด", "Hide detailed schedule")
            if visible
            else tr("ปรับเวลาแบบละเอียด", "Edit detailed schedule")
        )

    def _toggle_staff_tools(self, visible: bool) -> None:
        self.support_details.setVisible(visible)
        self.support_toggle.setText(
            tr("ซ่อนข้อมูลสำหรับเจ้าหน้าที่", "Hide staff information")
            if visible
            else tr("แสดงข้อมูลสำหรับเจ้าหน้าที่", "Show staff information")
        )

    @staticmethod
    def _group_page() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("settings_group_page")
        page.setStyleSheet(
            "QWidget#settings_group_page{background:transparent;border:none;}"
        )
        body = QVBoxLayout(page)
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(12)
        scroll.setWidget(page)
        return scroll, body

    @staticmethod
    def _section(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settings_section")
        card.setStyleSheet(
            "QFrame#settings_section{background:#FFFFFF;border:1px solid #D6E0EA;"
            "border-radius:10px;} QLabel{background:transparent;border:none;}"
        )
        body = QVBoxLayout(card)
        body.setContentsMargins(17, 15, 17, 17)
        body.setSpacing(10)
        heading = QLabel(title)
        heading.setFont(fnt(F_MD, True))
        heading.setStyleSheet("color:#102A43;background:transparent;border:none;")
        body.addWidget(heading)
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet("color:#64748B;background:transparent;border:none;")
        body.addWidget(detail)
        return card, body

    @staticmethod
    def _field(label: str, control: QWidget, hint: str = "") -> QWidget:
        field = QWidget()
        field.setObjectName("settings_field")
        field.setStyleSheet(
            "QWidget#settings_field{border:none;background:transparent;}"
        )
        body = QVBoxLayout(field)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        name = QLabel(label)
        name.setStyleSheet("color:#334155;background:transparent;border:none;font-weight:700;")
        name.setBuddy(control)
        body.addWidget(name)
        control.setMinimumHeight(38)
        control.setMaximumWidth(320)
        body.addWidget(control)
        if hint:
            note = QLabel(hint)
            note.setWordWrap(True)
            note.setStyleSheet("color:#64748B;background:transparent;border:none;font-size:10px;")
            body.addWidget(note)
        return field

    def _mark_dirty(self, section: str) -> None:
        if self._loading_config:
            return
        self._dirty_sections.add(section)
        widgets = {
            "billing": (self.billing_save_status, self.billing_save_button),
            "schedule": (self.schedule_save_status, self.schedule_save_button),
            "web": (self.web_save_status, self.web_save_button),
        }
        status, save_button = widgets[section]
        status.setText(tr("มีการแก้ไขที่ยังไม่ได้บันทึก", "Unsaved changes"))
        status.setStyleSheet("color:#B54708;font-weight:700;border:none;")
        save_button.setEnabled(True)
        if section == "schedule":
            self._refresh_schedule()
        self._refresh_task_summaries()

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty_sections)

    def discard_unsaved_changes(self) -> None:
        """Explicitly restore persisted values before the app exits."""
        self._dirty_sections.clear()
        self.refresh_from_config(force=True)
        self._set_active_editor(None, force=True)

    def refresh_from_config(self, *, force: bool = False) -> bool:
        if self._dirty_sections and not force:
            self._refresh_web_status()
            self._refresh_web_access_status()
            return False
        self._loading_config = True
        controls = (
            self.billing_day, self.waste, self.autostart, self.web_service_enabled,
        )
        for control in controls:
            control.blockSignals(True)
        self.billing_day.setValue(int(get_cfg("billing_day", "31") or 31))
        self.waste.setValue(float(get_cfg("waste_paper_pct", "2") or 2))
        stored_windows = load_schedule_windows(get_cfg("sync_schedule_windows", ""))
        self._using_unsaved_default_schedule = stored_windows is None
        self._replace_schedule_windows(stored_windows if stored_windows is not None else default_schedule_windows())
        registration = self._autostart_registration_status()
        configured_autostart = get_cfg("autostart_enabled", "")
        self.autostart.setChecked(
            registration
            if registration is not None
            else configured_autostart == "1"
        )
        self._refresh_autostart_status(registration)
        self.web_service_enabled.setChecked(get_cfg("web_service_enabled", "1") != "0")
        for control in controls:
            control.blockSignals(False)
        device_count = self._refresh_device_summary()
        active_path = str(get_db_path())
        database_text = (
            f"ฐานข้อมูลที่กำลังใช้งาน (อ่านอย่างเดียว): {active_path}\n"
            "การย้าย Database path ยังไม่รองรับใน V5 local release"
        )
        self.active_database_path.setText(database_text)
        self.active_database_path.setToolTip(database_text)
        self._dirty_sections.clear()
        for status, save_button in (
            (self.billing_save_status, self.billing_save_button),
            (self.schedule_save_status, self.schedule_save_button),
            (self.web_save_status, self.web_save_button),
        ):
            status.setText(tr("ค่าปัจจุบันถูกบันทึกแล้ว", "Current settings are saved"))
            status.setStyleSheet("color:#16875D;font-weight:700;border:none;")
            save_button.setEnabled(False)
        self._refresh_schedule()
        self._refresh_task_summaries(device_count=device_count, registration=registration)
        self._refresh_registration_status()
        self._refresh_web_status()
        self._refresh_web_access_status()
        self._loading_config = False
        return True

    def _refresh_registration_status(self) -> None:
        runtime = self._registration_service()
        snapshot = runtime.snapshot()
        mode = str(snapshot.get("mode") or "online")
        effective_status = str(snapshot.get("status") or "not_configured")
        labels = {
            "not_configured": tr("ยังไม่ได้ตั้งค่า", "Not configured"),
            "waiting_for_internet": tr("รออินเทอร์เน็ต", "Waiting for internet"),
            "pending": tr("รอส่งแบบ Background", "Pending background delivery"),
            "retrying": tr("กำลังลองใหม่", "Retrying"),
            "registered": tr("ลงทะเบียนแล้ว", "Registered"),
            "action_required": tr("ต้องตรวจสอบ", "Needs attention"),
            "needs_review": tr("ต้องตรวจสอบ", "Needs attention"),
            "offline_request_required": tr(
                "Offline License · กรุณาสร้างไฟล์คำขอ",
                "Offline License · export a request file",
            ),
            "offline_request_ready": tr(
                "Offline License · สร้างคำขอแล้ว รอนำเข้า License",
                "Offline License · request exported, waiting for license import",
            ),
            "offline_license": tr("Offline License", "Offline License"),
        }
        detail = labels.get(effective_status, tr("ต้องตรวจสอบ", "Needs attention"))
        last_sent_at = str(snapshot.get("last_sent_at") or "")
        if last_sent_at and mode == "online":
            detail += tr(
                f" · ส่งครั้งล่าสุด {last_sent_at}",
                f" · last sent {last_sent_at}",
            )
        if mode == "online":
            detail += tr(
                " · Host จะแยก Desktop ขาดการเชื่อมต่อหลัง 3 วัน และไม่สรุปว่าเครื่องพิมพ์เสีย",
                " · the Host separates Desktop connectivity loss after 3 days and does not claim a printer fault",
            )
        self.registration_summary.setText(detail)
        self.registration_summary.setToolTip("")
        for control in (self.registration_online_mode, self.registration_offline_mode):
            control.blockSignals(True)
        self.registration_online_mode.setChecked(mode == "online")
        self.registration_offline_mode.setChecked(mode == "offline")
        for control in (self.registration_online_mode, self.registration_offline_mode):
            control.blockSignals(False)
        self.registration_retry_button.setVisible(
            mode == "online"
            and effective_status
            in {
                "waiting_for_internet",
                "pending",
                "retrying",
                "action_required",
                "needs_review",
            }
        )
        self.registration_retry_button.setEnabled(mode == "online")
        self.registration_retry_button.setText(tr("ลองส่งอีกครั้ง", "Retry"))
        self.offline_request_button.setVisible(mode == "offline")
        self.offline_import_button.setVisible(mode == "offline")
        self.offline_license_summary.setVisible(mode == "offline")
        license_metadata = snapshot.get("offline_license")
        if mode == "offline" and isinstance(license_metadata, dict):
            expires_at = str(license_metadata.get("expires_at") or "—")
            bound_devices = license_metadata.get("bound_devices")
            bound_rows = []
            if isinstance(bound_devices, list):
                for device in bound_devices:
                    if not isinstance(device, dict):
                        continue
                    bound_rows.append(
                        f"{device.get('model') or 'Unknown'} · {device.get('serial_number') or '—'} · "
                        f"Slot {device.get('device_slot') or '—'}"
                    )
            self.offline_license_summary.setText(
                tr(
                    f"Offline License ใช้งานถึง {expires_at} · ผูกกับ " + ("; ".join(bound_rows) or "—"),
                    f"Offline License valid until {expires_at} · bound to " + ("; ".join(bound_rows) or "—"),
                )
            )
        elif mode == "offline":
            self.offline_license_summary.setText(
                tr(
                    "ยังไม่มี Offline License · สร้างไฟล์คำขอแล้วนำ License ที่ได้รับกลับเข้ามา",
                    "No Offline License yet · export a request and import the issued license file",
                )
            )
        accepted_current = bool(snapshot.get("notice_accepted"))
        self.registration_notice_accept.setChecked(accepted_current)
        self.registration_notice_accept.setVisible(mode == "online")
        self.registration_notice_accept.setEnabled(mode == "online" and not accepted_current)
        support_code = str(snapshot.get("support_code") or "none")
        next_attempt = str(snapshot.get("next_attempt_at") or "—")
        self.registration_support_detail.setText(
            tr(
                f"Registration mode: {mode} · Support code: {support_code} · รอบถัดไป: {next_attempt}",
                f"Registration mode: {mode} · Support code: {support_code} · next attempt: {next_attempt}",
            )
        )

    def _accept_registration_notice(self, checked: bool) -> None:
        if not checked:
            self._refresh_registration_status()
            return
        self._registration_service().accept_notice(
            DRAFT_NOTICE_VERSION,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self._refresh_registration_status()
        self.registration_summary.setText(
            tr(
                "รับทราบข้อมูลการลงทะเบียนแล้ว · ระบบจะลงทะเบียนอัตโนมัติเมื่อการเชื่อมต่อพร้อม",
                "Registration Data Notice acknowledged · automatic registration will continue when connectivity is ready",
            )
        )

    def _retry_registration(self) -> None:
        retried = self._registration_service().retry_now()
        self._refresh_registration_status()
        if retried:
            self.registration_summary.setText(
                tr(
                    "จัดคิวใหม่แล้ว · ระบบจะลองส่งใน Background",
                    "Queued again · background delivery will retry",
                )
            )

    def _registration_service(self):
        if self.registration_runtime is None:
            from services.v5_2_runtime import V52RuntimeCoordinator

            self.registration_runtime = V52RuntimeCoordinator(parent=self)
        return self.registration_runtime

    def _set_registration_mode(self, mode: str) -> None:
        try:
            self._registration_service().set_mode(mode)
            set_cfg("v52_registration_mode", mode)
        except (OSError, RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                tr("เปลี่ยนโหมดไม่สำเร็จ", "Could not change mode"),
                tr(
                    "การตั้งค่าเดิมยังคงอยู่ กรุณาลองอีกครั้ง",
                    "The previous setting is unchanged. Please try again.",
                ),
            )
        self._refresh_registration_status()
        self.changed.emit()

    def _export_offline_request(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("สร้างคำขอ Offline License", "Export Offline License request"),
            "KOMI-Desktop.komirequest",
            "KOMI Request (*.komirequest)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.casefold() != ".komirequest":
            destination = destination.with_suffix(".komirequest")
        try:
            self._registration_service().create_offline_request(destination)
        except (OSError, RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                tr("สร้างคำขอไม่สำเร็จ", "Could not export request"),
                tr(
                    "ตรวจสอบว่าได้เลือกเครื่องพิมพ์และ OS Credential Vault พร้อมใช้งาน",
                    "Check that printers are selected and the OS Credential Vault is available.",
                ),
            )
            return
        self._refresh_registration_status()
        QMessageBox.information(
            self,
            tr("สร้างคำขอแล้ว", "Request exported"),
            tr(
                "บันทึกไฟล์คำขอแล้ว · ไฟล์นี้ไม่มีรหัสผ่านหรือ Token",
                "The request file was saved. It contains no password or token.",
            ),
        )

    def _import_offline_license(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            tr("นำเข้าไฟล์ Offline License", "Import Offline License file"),
            "",
            "KOMI License (*.komilicense)",
        )
        if not path:
            return
        try:
            self._registration_service().import_offline_license(
                Path(path), self.offline_license_public_keys
            )
        except (OSError, RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                tr("นำเข้า License ไม่สำเร็จ", "Could not import license"),
                tr(
                    "ไฟล์ไม่ตรงกับ Desktop นี้ หมดอายุ หรือยังไม่มีข้อมูลยืนยันจาก Host",
                    "The file does not match this Desktop, has expired, or Host verification data is unavailable.",
                ),
            )
            return
        self._refresh_registration_status()
        self.changed.emit()
        QMessageBox.information(
            self,
            tr("นำเข้า License แล้ว", "License imported"),
            tr(
                "Offline License พร้อมใช้งาน และไม่มีการส่ง Registration, Status หรือ Meter",
                "Offline License is active and no Registration, Status, or Meter telemetry is sent.",
            ),
        )

    def _show_registration_privacy(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(
            tr("ประกาศข้อมูลการลงทะเบียน", "Registration Data Notice")
        )
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(registration_data_notice(get_language()))
        layout.addWidget(text)
        close_button = btn(tr("ปิด", "Close"), "primary")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self._registration_privacy_dialog = dialog
        dialog.open()

    def _refresh_device_summary(self) -> int:
        devices = self.repository.list(enabled_only=True)
        if devices:
            names = ", ".join(device.name for device in devices)
            self.device_summary.setText(
                tr(
                    f"{len(devices)}/3 เครื่อง · {names} · เปลี่ยนผ่านขั้นตอนตรวจสอบเครื่องและราคา",
                    f"{len(devices)}/3 printers · {names} · Change through the verified printer and pricing flow",
                )
            )
            self.device_summary.setToolTip(
                "\n".join(
                    f"{device.name} · {device.host} · Serial {device.serial or '—'}"
                    for device in devices
                )
            )
        else:
            self.device_summary.setText(
                tr(
                    "ยังไม่ได้ตั้งค่าเครื่องพิมพ์ · กดเปลี่ยนเพื่อเริ่มต้น",
                    "No printer configured · Select Change to get started",
                )
            )
            self.device_summary.setToolTip("")
        return len(devices)

    def _refresh_task_summaries(
        self,
        *,
        device_count: int | None = None,
        registration: bool | None = None,
    ) -> None:
        if device_count is None:
            device_count = len(self.repository.list(enabled_only=True))
        billing_prefix = (
            tr("กำลังแก้ไข · ", "Editing · ") if "billing" in self._dirty_sections else ""
        )
        self.billing_summary.setText(
            billing_prefix
            + tr(
                f"ปิดรอบวันที่ {self.billing_day.value()} · ส่วนลดกระดาษเสีย {self.waste.value():g}%",
                f"Closes on day {self.billing_day.value()} · Waste-paper discount {self.waste.value():g}%",
            )
        )
        if registration is None:
            registration = self._autostart_registration_status()
        automatic = registration is True or self.autostart.isChecked()
        schedule_prefix = (
            tr("กำลังแก้ไข · ", "Editing · ") if "schedule" in self._dirty_sections else ""
        )
        automatic_text = tr("เปิดพร้อมระบบ", "Starts at sign-in") if automatic else tr(
            "เปิดแอปด้วยตนเอง", "Open the app manually"
        )
        self.schedule_task_summary.setText(
            schedule_prefix
            + tr(
                f"{automatic_text} · ใช้ตารางเวลา {len(self._schedule_row_controls)} ช่วง",
                f"{automatic_text} · {len(self._schedule_row_controls)} reading windows",
            )
        )
        if device_count == 0:
            self.support_summary.setText(
                tr(
                    "ยังไม่มีเครื่องพิมพ์ · เริ่มจากส่วนเครื่องพิมพ์และราคา",
                    "No printer configured · Start with Printers and pricing",
                )
            )
        else:
            self.support_summary.setText(
                tr(
                    "เลือกอาการที่พบ ระบบจะพาไปยังข้อมูลที่เกี่ยวข้อง",
                    "Choose the problem you see to open the relevant information",
                )
            )

    @staticmethod
    def _autostart_registration_status() -> bool | None:
        """Read the planned OS registration path without creating or deleting it."""
        try:
            registration_path = configure_autostart(True, apply=False)
        except OSError:
            return None
        if registration_path is None:
            return None
        return registration_path.exists()

    def _refresh_autostart_status(self, registered: bool | None) -> None:
        if registered is True:
            self.autostart_status.setText(
                tr(
                    "พบ OS registration สำหรับเปิดอัตโนมัติแล้ว",
                    "Automatic start is registered with the operating system",
                )
            )
            self.autostart_status.setStyleSheet(
                "color:#16875D;background:#EDF8F2;border:1px solid #B8DFC9;"
                "border-radius:5px;padding:7px 9px;"
            )
        elif registered is False:
            self.autostart_status.setText(
                tr(
                    "ไม่พบ OS registration · เลือก checkbox แล้วกดบันทึกเพื่อเปิดใช้งาน",
                    "No OS registration found. Select the checkbox and save to enable it.",
                )
            )
            self.autostart_status.setStyleSheet(
                "color:#8A4B08;background:#FFF4E5;border:1px solid #F4C98B;"
                "border-radius:5px;padding:7px 9px;"
            )
        else:
            self.autostart_status.setText(
                tr(
                    "ตรวจ OS registration ไม่ได้ · checkbox แสดงค่าที่บันทึกไว้",
                    "OS registration could not be checked. The checkbox shows the stored setting.",
                )
            )
            self.autostart_status.setStyleSheet(
                "color:#64748B;background:#F8FAFC;border:1px solid #D6E0EA;"
                "border-radius:5px;padding:7px 9px;"
            )

    @staticmethod
    def _web_runtime_matches(desired_enabled: bool, status: WebServiceStatus) -> bool:
        if desired_enabled:
            return status.state in {"running", "external", "starting"}
        return status.state in {"stopped", "failed"}

    def _refresh_web_status(self, status: WebServiceStatus | None = None) -> None:
        current = status or self.web_service.status()
        colours = {
            "running": ("#16875D", "#EDF8F2", "#B8DFC9", tr("● พร้อมใช้งาน", "● Ready")),
            "external": (
                "#16875D",
                "#EDF8F2",
                "#B8DFC9",
                tr("● พร้อมใช้งาน (เปิดจากภายนอก)", "● Ready (started externally)"),
            ),
            "starting": ("#8A4B08", "#FFF4E5", "#F4C98B", tr("● กำลังเริ่ม", "● Starting")),
            "failed": ("#B42318", "#FEF3F2", "#F2B8B5", tr("● เริ่มไม่สำเร็จ", "● Start failed")),
            "stopped": ("#64748B", "#F8FAFC", "#D6E0EA", tr("● ปิดอยู่", "● Disabled")),
        }
        colour, background, border, label = colours[current.state]
        self.web_service_status.setText(f"{label} · {translate_text(current.detail)}")
        self.web_service_status.setStyleSheet(
            f"color:{colour};background:{background};border:1px solid {border};"
            "border-radius:5px;padding:7px 9px;"
        )
        lan_is_local_only = any(
            marker in current.lan_url.lower()
            for marker in ("127.0.0.1", "localhost", "[::1]")
        )
        if lan_is_local_only:
            address_text = tr(
                "ยังไม่พบที่อยู่ LAN · ตรวจว่าเครื่องนี้เชื่อมต่อเครือข่ายแล้ว",
                "No LAN address found · Check that this computer is connected to the network",
            )
        elif current.state in {"running", "external"}:
            address_text = tr(
                f"พร้อมเปิดจากเครื่องอื่น: {current.lan_url}",
                f"Ready on other computers: {current.lan_url}",
            )
        else:
            address_text = tr(
                f"เมื่อเปิดใช้งาน เครื่องอื่นจะเข้าได้ที่: {current.lan_url}",
                f"When enabled, other computers can use: {current.lan_url}",
            )
        self.web_service_url.setText(address_text)
        self.web_service_url.setToolTip(
            tr(
                f"เครื่องนี้เปิดจากแอป Desktop หรือ {current.local_url}",
                f"On this computer, use the Desktop app or {current.local_url}",
            )
        )
        ready = current.state in {"running", "external"}
        self.open_web_button.setVisible(ready)
        self.open_web_button.setEnabled(ready)
        self.copy_web_button.setVisible(ready and not lan_is_local_only)
        self.copy_web_button.setEnabled(ready and not lan_is_local_only)
        desired_enabled = self.web_service_enabled.isChecked()
        pending = desired_enabled and current.state == "starting"
        runtime_mismatch = not self._web_runtime_matches(desired_enabled, current)
        previous_mismatch = getattr(self, "_web_runtime_mismatch", False)
        if "web" not in self._dirty_sections:
            if pending:
                self.web_save_button.setEnabled(False)
                self.web_save_status.setText(
                    tr(
                        "กำลังเริ่ม Web Report และรอตรวจสอบสถานะ",
                        "Starting Web Report and waiting to verify its status",
                    )
                )
                self.web_save_status.setStyleSheet(
                    "color:#B54708;font-weight:700;border:none;"
                )
            elif runtime_mismatch:
                self.web_save_button.setEnabled(True)
                self.web_save_status.setText(
                    tr(
                        "สถานะบริการยังไม่ตรงกับค่าที่เลือก · กดบันทึกและตรวจสอบ LAN เพื่อลองอีกครั้ง",
                        "The service does not match the selected setting. Save and verify LAN access to try again.",
                    )
                )
                self.web_save_status.setStyleSheet(
                    "color:#B42318;font-weight:700;border:none;"
                )
            elif previous_mismatch:
                self.web_save_button.setEnabled(False)
                self.web_save_status.setText(
                    tr(
                        "การตั้งค่าและสถานะ Web Report ตรงกันแล้ว",
                        "The Web Report setting and service status now match",
                    )
                )
                self.web_save_status.setStyleSheet(
                    "color:#16875D;font-weight:700;border:none;"
                )
        self._web_runtime_mismatch = runtime_mismatch or pending
        if "web" in self._dirty_sections:
            self.web_task_summary.setText(
                tr(
                    "กำลังแก้ไข · การเปลี่ยนแปลงยังไม่มีผลจนกว่าจะบันทึก",
                    "Editing · Changes do not take effect until saved",
                )
            )
        elif pending:
            self.web_task_summary.setText(
                tr(
                    "กำลังเริ่ม Web Report · ระบบกำลังตรวจสอบสถานะ",
                    "Starting Web Report · Waiting to verify the service",
                )
            )
        elif runtime_mismatch and desired_enabled:
            self.web_task_summary.setText(
                tr(
                    "ต้องแก้ไข · ตั้งให้เปิดแล้ว แต่ Web Report ยังไม่เริ่ม",
                    "Needs attention · Web Report is enabled but has not started",
                )
            )
        elif runtime_mismatch:
            self.web_task_summary.setText(
                tr(
                    "ต้องแก้ไข · ตั้งให้ปิดแล้ว แต่ Web Report ยังทำงานอยู่",
                    "Needs attention · Web Report is disabled but is still running",
                )
            )
        elif ready and not lan_is_local_only:
            self.web_task_summary.setText(
                tr(
                    f"เปิดอยู่ · เครื่องอื่นเข้าได้ที่ {current.lan_url}",
                    f"Enabled · Other computers can use {current.lan_url}",
                )
            )
        else:
            self.web_task_summary.setText(
                tr(
                    "ปิดอยู่ · เครื่องอื่นยังเปิดรายงานไม่ได้",
                    "Disabled · Other computers cannot open reports",
                )
            )

    def _open_web(self) -> None:
        webbrowser.open(self.web_service.status().local_url)

    def _copy_lan_url(self) -> None:
        current = self.web_service.status()
        if any(
            marker in current.lan_url.lower()
            for marker in ("127.0.0.1", "localhost", "[::1]")
        ):
            QMessageBox.information(
                self,
                tr("ยังคัดลอกไม่ได้", "Nothing to copy yet"),
                tr(
                    "ยังไม่พบที่อยู่ LAN กรุณาตรวจการเชื่อมต่อเครือข่าย",
                    "No LAN address was found. Check the network connection.",
                ),
            )
            return
        QApplication.clipboard().setText(current.lan_url)
        self.web_save_status.setText(tr("คัดลอกที่อยู่ LAN แล้ว", "LAN address copied"))
        self.web_save_status.setStyleSheet("color:#16875D;font-weight:700;border:none;")

    def _refresh_web_access_status(self) -> None:
        status = web_access_status(self.web_service.runtime_root / ".env.local")
        if status.configured:
            self.web_access_status.setText(
                tr(
                    f"ตั้งรหัสแล้ว · Username: {status.user} · ระบบไม่แสดงรหัสปัจจุบัน",
                    f"Access code set · Username: {status.user} · The current code is never displayed",
                )
            )
            self.web_access_status.setStyleSheet("color:#16875D;")
            self.change_web_access_button.setText(
                tr("เปลี่ยนรหัส Web", "Change Web access code")
            )
        else:
            self.web_access_status.setText(
                tr(
                    "ยังไม่ได้ตั้งรหัส · เครื่องอื่นใน LAN จะยังเข้าสู่ระบบไม่ได้",
                    "Access code not set · Other LAN computers cannot sign in yet",
                )
            )
            self.web_access_status.setStyleSheet("color:#B54708;")
            self.change_web_access_button.setText(
                tr("ตั้งรหัส Web", "Set Web access code")
            )

    def _apply_web_access_code(self, access_code: str) -> WebServiceStatus:
        set_web_access_code(self.web_service.runtime_root / ".env.local", access_code)
        before = self.web_service.status()
        if before.state in {"running", "starting"}:
            result = self.web_service.restart()
        elif before.state == "external":
            result = self.web_service.restart()
        elif self.web_service_enabled.isChecked():
            result = self.web_service.start()
        else:
            result = before
        self._refresh_web_access_status()
        self._refresh_web_status(result)
        return result

    def _change_web_access_code(self) -> None:
        dialog = WebAccessCodeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            status = self._apply_web_access_code(dialog.value())
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                tr("เปลี่ยนรหัส Web ไม่สำเร็จ", "Could not change the Web access code"),
                translate_text(str(error)),
            )
            return
        if status.state == "external":
            QMessageBox.warning(
                self,
                tr("บันทึกรหัสแล้ว", "Access code saved"),
                tr(
                    "บันทึกรหัสใหม่แล้ว แต่ Web service เปิดจาก Shortcut แยก กรุณาปิด Web service เดิมและเปิดใหม่ก่อนใช้งาน",
                    "The new code was saved, but Web Report was started from a separate shortcut. Stop and restart that Web service before signing in.",
                ),
            )
            return
        QMessageBox.information(
            self,
            tr("เปลี่ยนรหัส Web แล้ว", "Web access code changed"),
            tr(
                "เครื่องอื่นใน LAN ต้องเข้าสู่ระบบใหม่ด้วยรหัสที่เพิ่งตั้ง",
                "Other LAN computers must sign in again with the new code.",
            ),
        )

    def _create_shortcuts(self) -> None:
        try:
            result = create_desktop_shortcuts()
        except Exception as exc:
            QMessageBox.warning(self, "สร้าง Shortcut ไม่สำเร็จ", str(exc))
            return
        names = "\n".join(path.name for path in result.created_paths)
        QMessageBox.information(
            self,
            "สร้าง Shortcut แล้ว",
            f"สร้างไว้ที่ {result.desktop_path}\n\n{names}\n\nShortcut ทุกอันเรียก source กลางชุดเดียวกัน",
        )

    def _edit_devices(self) -> None:
        if self._dirty_sections:
            QMessageBox.information(
                self,
                tr("ยังไม่ได้บันทึก", "Unsaved changes"),
                tr(
                    "กรุณาบันทึกหรือยกเลิกส่วนที่กำลังแก้ก่อนเปลี่ยนเครื่องพิมพ์",
                    "Save or cancel the section you are editing before changing printers.",
                ),
            )
            return
        dialog = SetupWizardV5(self, edit_mode=True)
        self._setup_wizard_dialog = dialog

        def setup_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted):
                self.refresh_from_config(force=True)
                self.changed.emit()
            self._setup_wizard_dialog = None

        dialog.finished.connect(setup_finished)
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_section(self, section: str) -> None:
        self._dirty_sections.discard(section)
        self.refresh_from_config(force=True)
        self._set_active_editor(None, force=True)

    def _mark_section_saved(
        self,
        section: str,
        *,
        message: str | None = None,
        close: bool = True,
    ) -> None:
        self._dirty_sections.discard(section)
        status, save_button = {
            "billing": (self.billing_save_status, self.billing_save_button),
            "schedule": (self.schedule_save_status, self.schedule_save_button),
            "web": (self.web_save_status, self.web_save_button),
        }[section]
        status.setText(
            message
            or tr(
                f"บันทึกและตรวจสอบแล้ว {datetime.now():%H:%M} น.",
                f"Saved and verified at {datetime.now():%H:%M}",
            )
        )
        status.setStyleSheet("color:#16875D;font-weight:700;border:none;")
        save_button.setEnabled(False)
        self._refresh_task_summaries()
        self.changed.emit()
        if close:
            self._set_active_editor(None, force=True)

    def _save_billing(self) -> None:
        set_cfg("billing_day", str(self.billing_day.value()))
        set_cfg("waste_paper_pct", str(round(self.waste.value(), 1)))
        stored_day = int(get_cfg("billing_day", "0") or 0)
        stored_waste = float(get_cfg("waste_paper_pct", "-1") or -1)
        if stored_day != self.billing_day.value() or stored_waste != round(self.waste.value(), 1):
            self.billing_save_status.setText(
                tr("บันทึกรอบบิลไม่สำเร็จ", "Could not save billing settings")
            )
            self.billing_save_status.setStyleSheet("color:#B42318;font-weight:700;border:none;")
            return
        self._mark_section_saved("billing")

    def _save_schedule(self) -> None:
        try:
            schedule_windows = self._schedule_windows_from_table()
        except ValueError as error:
            QMessageBox.warning(
                self,
                tr("ตรวจตารางเวลา", "Check the schedule"),
                translate_text(str(error)),
            )
            return
        try:
            configure_autostart(self.autostart.isChecked(), apply=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("ตั้งค่า Auto-start ไม่สำเร็จ", "Could not configure automatic start"),
                translate_text(str(exc)),
            )
            return
        serialized_windows = dump_schedule_windows(schedule_windows)
        expected_autostart = "1" if self.autostart.isChecked() else "0"
        set_cfg("sync_schedule_windows", serialized_windows)
        set_cfg("autostart_enabled", expected_autostart)
        stored_windows = load_schedule_windows(get_cfg("sync_schedule_windows", ""))
        stored_autostart = get_cfg("autostart_enabled", "")
        if stored_windows != schedule_windows or stored_autostart != expected_autostart:
            self.schedule_save_button.setEnabled(True)
            self.schedule_save_status.setText(
                tr(
                    "บันทึกตารางเวลาไม่ครบ กรุณาลองอีกครั้ง",
                    "The schedule was not stored completely. Try again.",
                )
            )
            self.schedule_save_status.setStyleSheet(
                "color:#B42318;font-weight:700;border:none;"
            )
            return
        self._using_unsaved_default_schedule = False
        registration = self._autostart_registration_status()
        self._refresh_autostart_status(registration)
        self._refresh_schedule()
        registration_matches = (
            registration is True
            if self.autostart.isChecked()
            else registration is False
        )
        if not registration_matches:
            self.schedule_save_button.setEnabled(True)
            self.schedule_save_status.setText(
                tr(
                    "บันทึกตารางเวลาแล้ว แต่ Auto-start ยังไม่ตรงกับค่าที่เลือก · กดลองตรวจอีกครั้ง",
                    "The schedule was saved, but automatic start does not match the selected setting. Try verifying again.",
                )
            )
            self.schedule_save_status.setStyleSheet(
                "color:#B54708;font-weight:700;border:none;"
            )
            self._refresh_task_summaries(registration=registration)
            self.changed.emit()
            return
        self._mark_section_saved("schedule")

    def _save_web(self) -> None:
        web_enabled = self.web_service_enabled.isChecked()
        set_cfg("web_service_enabled", "1" if web_enabled else "0")
        web_status = self.web_service.start() if web_enabled else self.web_service.stop()
        self._refresh_web_status(web_status)
        stored_enabled = get_cfg("web_service_enabled", "") == "1"
        if (
            stored_enabled != web_enabled
            or not self._web_runtime_matches(web_enabled, web_status)
            or web_status.state == "starting"
        ):
            self.web_save_button.setEnabled(web_status.state != "starting")
            self.web_save_status.setText(
                tr(
                    "บันทึกค่าแล้ว แต่สถานะ Web Report ยังไม่ตรง · ตรวจข้อความด้านบนแล้วลองอีกครั้ง",
                    "The setting was saved, but the Web Report status still does not match. Check the message above and try again.",
                )
            )
            self.web_save_status.setStyleSheet("color:#B42318;font-weight:700;border:none;")
            self.changed.emit()
            return
        self._mark_section_saved("web")

    def _save(self) -> None:
        """Compatibility dispatcher for older callers; the UI has no global Save."""
        for section, handler in (
            ("billing", self._save_billing),
            ("schedule", self._save_schedule),
            ("web", self._save_web),
        ):
            if section in self._dirty_sections:
                handler()
                return

    def _refresh_schedule(self) -> None:
        try:
            windows = self._schedule_windows_from_table()
        except ValueError:
            windows = ()
        if windows:
            first_start = min(window.start for window in windows)
            last_end = max(window.end for window in windows)
            summary = tr(
                f"ตั้งเวลาอ่านข้อมูลไว้ {len(windows)} ช่วง · "
                f"ครอบคลุม {first_start:%H:%M}–{last_end:%H:%M}\n"
                "หากไม่แน่ใจ ไม่จำเป็นต้องเปลี่ยนค่ารายละเอียด",
                f"Reading schedule has {len(windows)} windows · "
                f"covering {first_start:%H:%M}–{last_end:%H:%M}\n"
                "If unsure, keep the recommended schedule.",
            )
        else:
            summary = tr(
                "ยังไม่ได้ตั้งเวลาอ่านข้อมูลอัตโนมัติ",
                "No automatic reading schedule is configured",
            )
        default_prefix = (
            tr("ใช้ค่าแนะนำของระบบ · ", "Using recommended defaults · ")
            if getattr(self, "_using_unsaved_default_schedule", False)
            else ""
        )
        self.schedule.setText(f"{default_prefix}{summary}")

    def _replace_schedule_windows(self, windows: tuple[ScheduleWindow, ...]) -> None:
        self.schedule_windows_table.setRowCount(0)
        self._schedule_row_controls.clear()
        for window in windows:
            self._append_schedule_window(window, mark_dirty=False)
        self._refresh_schedule()

    def _append_schedule_window(self, window: ScheduleWindow, *, mark_dirty: bool) -> None:
        row = self.schedule_windows_table.rowCount()
        self.schedule_windows_table.insertRow(row)
        self.schedule_windows_table.setRowHeight(row, 48)
        name = QLineEdit(window.label)
        name.setMinimumWidth(110)
        clock_range = ScheduleTimeRangeEditor(window.start, window.end)
        weekdays = WeekdaySelector(window.weekdays)
        snmp_interval = QSpinBox()
        snmp_interval.setRange(1, 1_440)
        snmp_interval.setSuffix(tr(" นาที", " min"))
        snmp_interval.setValue(int((window.snmp_interval or timedelta(minutes=5)).total_seconds() // 60))
        web_interval = QSpinBox()
        web_interval.setRange(1, 1_440)
        web_interval.setSuffix(tr(" นาที", " min"))
        web_interval.setValue(int(window.web_interval.total_seconds() // 60))
        remove = btn(tr("ลบ", "Remove"), "outline")
        remove.setMinimumWidth(86)
        remove.setMinimumWidth(54)
        for control in (name, snmp_interval, web_interval):
            control.setMinimumHeight(32)
        self.schedule_windows_table.setCellWidget(row, 0, name)
        self.schedule_windows_table.setCellWidget(row, 1, clock_range)
        self.schedule_windows_table.setCellWidget(row, 2, weekdays)
        self.schedule_windows_table.setCellWidget(row, 3, snmp_interval)
        self.schedule_windows_table.setCellWidget(row, 4, web_interval)
        self.schedule_windows_table.setCellWidget(row, 5, remove)
        controls = (name, clock_range, weekdays, snmp_interval, web_interval)
        self._schedule_row_controls.append(controls)
        remove.clicked.connect(lambda _checked=False, row_controls=controls: self._remove_schedule_window(row_controls))
        name.textChanged.connect(self._mark_schedule_dirty)
        clock_range.changed.connect(self._mark_schedule_dirty)
        weekdays.changed.connect(self._mark_schedule_dirty)
        snmp_interval.valueChanged.connect(self._mark_schedule_dirty)
        web_interval.valueChanged.connect(self._mark_schedule_dirty)
        if mark_dirty:
            self._mark_dirty("schedule")

    def _add_schedule_window(self) -> None:
        start = QTime.currentTime()
        start = QTime(start.hour(), 0)
        end = start.addSecs(60 * 60)
        self._append_schedule_window(
            ScheduleWindow(
                start=time(start.hour(), start.minute()),
                end=time(end.hour(), end.minute()),
                web_interval=timedelta(minutes=60),
                label=f"ช่วงที่ {len(self._schedule_row_controls) + 1}",
                snmp_interval=timedelta(minutes=15),
                weekdays=frozenset(range(5)),
            ),
            mark_dirty=True,
        )

    def _remove_schedule_window(
        self,
        controls: tuple[QLineEdit, ScheduleTimeRangeEditor, WeekdaySelector, QSpinBox, QSpinBox],
    ) -> None:
        try:
            index = self._schedule_row_controls.index(controls)
        except ValueError:
            return
        self.schedule_windows_table.removeRow(index)
        self._schedule_row_controls.pop(index)
        self._mark_dirty("schedule")

    def _mark_schedule_dirty(self, *_args) -> None:
        self._mark_dirty("schedule")

    def _schedule_windows_from_table(self) -> tuple[ScheduleWindow, ...]:
        windows: list[ScheduleWindow] = []
        for index, (name, clock_range, weekdays, snmp_interval, web_interval) in enumerate(self._schedule_row_controls, start=1):
            start_clock, end_clock = clock_range.values()
            label = name.text().strip() or f"ช่วงที่ {index}"
            if start_clock >= end_clock:
                raise ValueError(f"{label}: เวลาสิ้นสุดต้องอยู่หลังเวลาเริ่ม")
            selected_days = weekdays.values()
            if not selected_days:
                raise ValueError(f"{label}: เลือกอย่างน้อย 1 วันในสัปดาห์")
            windows.append(
                ScheduleWindow(
                    start=start_clock,
                    end=end_clock,
                    web_interval=timedelta(minutes=web_interval.value()),
                    label=label,
                    snmp_interval=timedelta(minutes=snmp_interval.value()),
                    weekdays=selected_days,
                )
            )
        ordered = tuple(sorted(windows, key=lambda item: item.start))
        for previous, current in zip(ordered, ordered[1:]):
            if previous.end > current.start and previous.weekdays & current.weekdays:
                raise ValueError(
                    f"ช่วงเวลา {previous.label} และ {current.label} ซ้อนกันในวันเดียวกัน กรุณาแก้ไขก่อนบันทึก"
                )
        return ordered

    def _choose_counters(self) -> None:
        if PinnedCountersDialog(self.repository, self).exec() == QDialog.DialogCode.Accepted:
            self.changed.emit()


_AUDIT_STATE_LABELS = {
    "effective": "มีผล",
    "open_hold": "Hold รอตรวจ",
    "open_reversal": "Reversal ยังไม่ครบคู่",
    "resolved_hold": "Hold แก้แล้ว",
    "superseded": "ถูกแทนที่",
    "paired_reversal": "Reversal จับคู่แล้ว",
}


def _pretty_audit_json(raw: str) -> str:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return str(raw)
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def audit_row_detail_text(row: AuditRow) -> str:
    """Human-readable, full-fidelity representation used by the detail dialog."""
    replaces = f"Ledger #{row.replaces_ledger_id}" if row.replaces_ledger_id is not None else "—"
    source_record = (
        f"Daily Record #{row.source_daily_record_id}"
        if row.source_daily_record_id is not None
        else "Manual / ไม่มี Daily Record"
    )
    return "\n".join(
        [
            f"Ledger ID: #{row.id}",
            f"Event: {row.entry_kind}",
            f"สถานะปัจจุบัน: {_AUDIT_STATE_LABELS.get(row.effective_state, row.effective_state)}",
            f"แทนที่ / เชื่อมโยงจาก: {replaces}",
            f"Source: {source_record}",
            f"Source hash (SHA-256): {row.source_hash}",
            f"Idempotency key: {row.idempotency_key}",
            "",
            f"เครื่อง: {row.device_name_snapshot or '—'}",
            f"Slot / Identity: {row.device_slot + 1} / {row.device_identity}",
            f"Serial snapshot: {row.device_serial_snapshot or '—'}",
            f"วันที่ข้อมูล: {row.record_date}",
            f"รอบบิลที่ถูกตรึง: {row.period_start} – {row.period_end}",
            f"วันสิ้นสุดรอบบิล: {row.billing_day}",
            f"บันทึกเมื่อ: {row.created_at}",
            "",
            f"ยอดก่อนหัก: {row.currency} {row.gross_cents / 100:,.2f}",
            f"กระดาษเสีย: {row.waste_basis_points / 100:g}% ({row.waste_basis_points} basis points)",
            f"ยอดสุทธิ: {row.currency} {row.net_cents / 100:,.2f}",
            f"Formula version: {row.formula_version}",
            f"เหตุผล / หมายเหตุ: {row.hold_reason or '—'}",
            "",
            "Delta snapshot:",
            _pretty_audit_json(row.delta_json),
            "",
            "Category snapshot:",
            _pretty_audit_json(row.category_json),
            "",
            "Price snapshot (cents):",
            _pretty_audit_json(row.price_cents_json),
            "",
            "Attestation:",
            _pretty_audit_json(row.attestation_json),
        ]
    )


class BillingAuditDetailDialog(QDialog):
    def __init__(self, row: AuditRow, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Billing Audit · Ledger #{row.id}")
        self.resize(860, 680)
        layout = QVBoxLayout(self)
        heading = QLabel(f"Ledger #{row.id} · {row.entry_kind.upper()}")
        heading.setFont(fnt(F_2XL, True))
        layout.addWidget(heading)
        body = QPlainTextEdit(audit_row_detail_text(row))
        body.setReadOnly(True)
        body.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        body.setObjectName("billingAuditDetail")
        layout.addWidget(body, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PageBillingAudit(QWidget):
    """Read-only, pageable proof of effective and intentionally held billing."""

    PAGE_SIZE = 100
    EXPORT_FIELDS = tuple(AuditRow.__dataclass_fields__)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loaded_limit = self.PAGE_SIZE
        self._rows: list[AuditRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Billing Audit — Local only")
        title.setFont(fnt(F_2XL, True))
        layout.addWidget(title)
        hint = QLabel(
            "Ledger เป็น append-only: Hold จะไม่ถูกคิดเงิน และการแก้ยอดจะเพิ่ม Reversal + Replacement "
            "โดยไม่แก้หรือลบรายการเดิม · ดับเบิลคลิกแถวเพื่อดูหลักฐานครบ"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "background:#EEF6F9;color:#245268;border:1px solid #C8E1EA;"
            "border-radius:6px;padding:12px;"
        )
        layout.addWidget(hint)
        self.coverage = QLabel()
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(QLabel("สถานะ"))
        self.state_filter = QComboBox()
        self.state_filter.setObjectName("billingAuditStateFilter")
        self.state_filter.addItem("ทั้งหมด", None)
        self.state_filter.addItem("มีผลต่อยอด", "effective")
        self.state_filter.addItem("Hold รอตรวจ", "open_hold")
        self.state_filter.addItem("Reversal ยังไม่ครบคู่", "open_reversal")
        self.state_filter.addItem("รายการแก้ไขทั้งหมด", "correction")
        filters.addWidget(self.state_filter)
        self.search = QLineEdit()
        self.search.setObjectName("billingAuditSearch")
        self.search.setPlaceholderText("ค้นหา ID, เครื่อง, Serial, เหตุผล, hash หรือวันที่ แล้วกด Enter")
        filters.addWidget(self.search, 1)
        self.refresh_button = btn("Refresh", "outline")
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("billingAuditTable")
        self.table.setAccessibleName("รายการ Billing Audit")
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "วันที่",
                "เครื่อง",
                "Event / ผล",
                "สุทธิ",
                "รอบบิล",
                "เชื่อมโยง Ledger",
                "เหตุผล",
                "บันทึกเมื่อ",
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 4, 5, 6, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.row_count = QLabel()
        self.row_count.setStyleSheet("color:#64748B;")
        actions.addWidget(self.row_count)
        actions.addStretch(1)
        self.load_more_button = btn("โหลดเพิ่ม", "outline")
        self.detail_button = btn("ดูรายละเอียด", "outline")
        self.detail_button.setEnabled(False)
        self.export_button = btn("Export CSV", "outline")
        actions.addWidget(self.load_more_button)
        actions.addWidget(self.detail_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)

        self.state_filter.currentIndexChanged.connect(self._reset_and_refresh)
        self.search.returnPressed.connect(self._reset_and_refresh)
        self.refresh_button.clicked.connect(self._reset_and_refresh)
        self.load_more_button.clicked.connect(self._load_more)
        self.detail_button.clicked.connect(self._show_selected_detail)
        self.export_button.clicked.connect(self._export)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(self._show_detail)
        self.refresh()

    def _current_state(self) -> str | None:
        value = self.state_filter.currentData()
        return str(value) if value else None

    def _reset_and_refresh(self, _value=None) -> None:
        self._loaded_limit = self.PAGE_SIZE
        self.refresh()

    def _load_more(self) -> None:
        self._loaded_limit += self.PAGE_SIZE
        self.refresh()

    def _refresh_coverage(self) -> None:
        coverage = audit_coverage()
        self.coverage.setText(
            f"มีผลต่อยอด {coverage.effective_posted} วัน · Hold รอตรวจ {coverage.open_holds} วัน · "
            f"Reversal ยังไม่ครบคู่ {coverage.open_reversals} วัน · "
            f"มีประวัติการแก้ไข {coverage.corrected_sources} วัน\n"
            f"ข้อมูลเก่าก่อนใช้ Ledger {coverage.legacy_uncovered} วัน · "
            f"ข้อมูลใหม่ที่ควรมี Ledger แต่หาย {coverage.expected_missing} วัน"
        )
        if coverage.expected_missing or coverage.open_reversals:
            style = "background:#FFF0F0;color:#A61B1B;border:1px solid #F4B4B4;"
        elif coverage.open_holds:
            style = "background:#FFF8E8;color:#7A4A00;border:1px solid #EACB88;"
        else:
            style = "background:#EDF8F2;color:#146C4A;border:1px solid #B8DFC9;"
        self.coverage.setStyleSheet(f"{style}border-radius:6px;padding:10px 12px;font-weight:700;")

    def refresh(self) -> None:
        self._refresh_coverage()
        state = self._current_state()
        search = self.search.text()
        total = count_audit_rows(state=state, search=search)
        self._rows = list_audit_rows(self._loaded_limit, state=state, search=search)
        self.table.setRowCount(len(self._rows))
        state_colors = {
            "effective": QColor("#146C4A"),
            "open_hold": QColor("#9A5A00"),
            "open_reversal": QColor("#B42318"),
            "resolved_hold": QColor("#1769AA"),
            "superseded": QColor("#64748B"),
            "paired_reversal": QColor("#64748B"),
        }
        for row_no, row in enumerate(self._rows):
            state_label = _AUDIT_STATE_LABELS.get(row.effective_state, row.effective_state)
            link = f"#{row.replaces_ledger_id}" if row.replaces_ledger_id is not None else "—"
            machine = row.device_name_snapshot or row.device_identity
            values = [
                f"#{row.id}",
                row.record_date,
                machine,
                f"{row.entry_kind.upper()} · {state_label}",
                f"฿{row.net_cents / 100:,.2f}",
                f"{row.period_start} – {row.period_end}",
                link,
                row.hold_reason or "—",
                row.created_at,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(audit_row_detail_text(row) if column in {0, 3, 6, 7} else str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.id)
                if column == 3:
                    item.setForeground(state_colors.get(row.effective_state, QColor(C_TEXT2)))
                self.table.setItem(row_no, column, item)
        self.row_count.setText(f"แสดง {len(self._rows):,} จาก {total:,} รายการ")
        remaining = max(0, total - len(self._rows))
        self.load_more_button.setVisible(remaining > 0)
        self.load_more_button.setText(f"โหลดเพิ่ม ({remaining:,})" if remaining else "โหลดเพิ่ม")
        self.detail_button.setEnabled(False)
        apply_language(self)

    def _selected_ledger_id(self) -> int | None:
        row_no = self.table.currentRow()
        item = self.table.item(row_no, 0) if row_no >= 0 else None
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _selection_changed(self) -> None:
        self.detail_button.setEnabled(self._selected_ledger_id() is not None)

    def _show_detail(self, row_no: int, _column: int = 0) -> None:
        item = self.table.item(row_no, 0)
        if item is None:
            return
        row = get_audit_row(int(item.data(Qt.ItemDataRole.UserRole)))
        if row is not None:
            BillingAuditDetailDialog(row, self).exec()

    def _show_selected_detail(self) -> None:
        row_no = self.table.currentRow()
        if row_no >= 0:
            self._show_detail(row_no)

    def _export_rows_to(self, path: str) -> int:
        rows = list_audit_rows(limit=None, state=self._current_state(), search=self.search.text())
        with open(path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(self.EXPORT_FIELDS)
            for row in rows:
                writer.writerow([getattr(row, field) for field in self.EXPORT_FIELDS])
        return len(rows)

    def _export(self) -> None:
        suggested = f"komi-billing-audit-{date.today().isoformat()}.csv"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Billing Audit",
            suggested,
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            count = self._export_rows_to(path)
        except OSError as exc:
            QMessageBox.warning(self, "Export ไม่สำเร็จ", str(exc))
            return
        QMessageBox.information(self, "Export สำเร็จ", f"บันทึก {count:,} รายการแล้ว")


class PageSettingsV5(QWidget):
    changed = pyqtSignal()
    sync_requested = pyqtSignal()

    def __init__(
        self,
        legacy_settings: QWidget,
        parent=None,
        *,
        registration_runtime=None,
        offline_license_public_keys: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.stack = QStackedWidget()
        self.fleet_content = PageFleetSettings(
            registration_runtime=registration_runtime,
            offline_license_public_keys=offline_license_public_keys,
        )
        self.activity = PagePipelineLog()
        self.activity.page_title.hide()
        self.activity.page_note.hide()
        self.audit = PageBillingAudit()
        self.legacy_content = legacy_settings
        embed_mode = getattr(self.legacy_content, "set_v5_embed_mode", None)
        if callable(embed_mode):
            embed_mode()
        self.fleet = self._scroll_page(self.fleet_content)
        self._activity_host = self._detail_page(
            "สถานะและประวัติการอ่าน",
            "ใช้สำหรับตรวจสอบเมื่อข้อมูลไม่อัปเดต ผู้ใช้งานทั่วไปไม่จำเป็นต้องเปิดหน้านี้",
            self.activity,
        )
        self._audit_host = self._detail_page(
            "ตรวจสอบรอบบิล",
            "ดูหลักฐานและรายการที่ระบบพักไว้เพื่อตรวจสอบ โดยไม่เปลี่ยนยอดย้อนหลังอัตโนมัติ",
            self.audit,
        )
        self.legacy = self._scroll_page(self.legacy_content)
        self._legacy_host = self._detail_page(
            "เครื่องมือขั้นสูง",
            "คำเตือน: การรีเซ็ตหรือปรับ Parser อาจเปลี่ยนผลการอ่านข้อมูล กรุณาตรวจข้อความยืนยันทุกครั้ง",
            self.legacy,
            warning=True,
        )
        for page in (self.fleet, self._activity_host, self._audit_host, self._legacy_host):
            self.stack.addWidget(page)
        self._logical_pages = [self.fleet, self.activity, self.audit, self.legacy]
        self._host_for_page = {
            self.fleet: self.fleet,
            self.activity: self._activity_host,
            self.audit: self._audit_host,
            self.legacy: self._legacy_host,
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack)
        self.fleet_content.changed.connect(self.changed)
        self.fleet_content.activity_requested.connect(self.show_activity)
        self.fleet_content.billing_audit_requested.connect(self.show_audit)
        self.fleet_content.advanced_tools_requested.connect(self.show_advanced)
        self.activity.sync_requested.connect(self.sync_requested)
        self.activity.settings_requested.connect(self.show_main)
        if hasattr(self.legacy_content, "changed"):
            self.legacy_content.changed.connect(self.changed)

    @staticmethod
    def _scroll_page(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _detail_page(
        self,
        title: str,
        description: str,
        content: QWidget,
        *,
        warning: bool = False,
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 20)
        layout.setSpacing(12)
        top = QHBoxLayout()
        back = btn("← กลับไปการตั้งค่า", "outline")
        back.setAccessibleName("กลับไปหน้าการตั้งค่าหลัก")
        back.clicked.connect(self.show_main)
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        heading = QLabel(title)
        heading.setFont(fnt(F_2XL, True))
        heading.setStyleSheet("color:#102A43;border:none;")
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet(
            "color:#8A4B08;background:#FFF7E8;border:1px solid #F2C879;"
            "border-radius:7px;padding:8px 10px;"
            if warning
            else "color:#52677D;border:none;"
        )
        copy.addWidget(heading)
        copy.addWidget(detail)
        top.addLayout(copy, 1)
        layout.addLayout(top)
        layout.addWidget(content, 1)
        return page

    def ensure_unlocked(self) -> bool:
        self.fleet_content.refresh_from_config()
        return True

    def has_unsaved_changes(self) -> bool:
        return self.fleet_content.has_unsaved_changes()

    def discard_unsaved_changes(self) -> None:
        self.fleet_content.discard_unsaved_changes()

    def show_main(self) -> None:
        self.stack.setCurrentWidget(self.fleet)
        self.fleet_content.refresh_from_config()
        apply_language(self.fleet_content)

    def show_activity(self) -> None:
        self.stack.setCurrentWidget(self._activity_host)
        self.activity.refresh()
        apply_language(self._activity_host)

    def show_audit(self) -> None:
        self.stack.setCurrentWidget(self._audit_host)
        self.audit.refresh()
        apply_language(self._audit_host)

    def show_advanced(self) -> None:
        self.stack.setCurrentWidget(self._legacy_host)
        refresh = getattr(self.legacy_content, "_refresh_ui", None)
        if callable(refresh):
            refresh()
        apply_language(self._legacy_host)

    def refresh(self) -> None:
        current = self.currentWidget()
        if current is self.activity:
            self.activity.refresh()
        elif current is self.audit:
            self.audit.refresh()
        else:
            self.fleet_content.refresh_from_config()

    @property
    def _authenticated(self):
        return True

    @_authenticated.setter
    def _authenticated(self, value):
        if hasattr(self.legacy_content, "_authenticated"):
            self.legacy_content._authenticated = True
        show_protected = getattr(self.legacy_content, "_set_protected_visible", None)
        if callable(show_protected):
            show_protected(True)

    def setCurrentWidget(self, widget: QWidget) -> None:
        host = self._host_for_page.get(widget, widget)
        self.stack.setCurrentWidget(host)
        if widget is self.activity:
            self.activity.refresh()
        elif widget is self.audit:
            self.audit.refresh()

    def currentWidget(self) -> QWidget:
        current = self.stack.currentWidget()
        for logical, host in self._host_for_page.items():
            if current is host:
                return logical
        return self.fleet

    def widget(self, index: int) -> QWidget:
        return self._logical_pages[index]

    def count(self) -> int:
        return len(self._logical_pages)
