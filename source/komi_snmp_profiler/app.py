from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Literal

from .calibration import compare_snapshots
from .connectors import WebConnectionCounterConnector, WebConnectionError
from .credential_store import (
    AdminCredential,
    CredentialStoreError,
    SessionCredentialStore,
)
from .exporter import (
    export_counter_candidates_csv,
    export_csv,
    export_decoded_csv,
    export_json,
    export_meter_csv,
    export_meter_json,
)
from .meter import MeterReader
from .meter_export import MeterExportKind, MeterExportReader, MeterExportTable
from .models import ConnectionSettings, CounterDelta, DeviceSnapshot, MeterReading, ScanMode
from .print_calibration import run_print_calibration
from .service import ProfilerService
from .snmp_client import PySnmpCollector, ScanProgress, SnmpCollectionError, SnmpScanCancelled
from .system_print import PrintingError, PrintTestRequest, system_print_backend

CALIBRATION_JOBS = ("A4 Color", "A4 Black", "A3 Color", "A3 Black")
METER_SUMMARY_FIELDS = (
    "counter.total.total",
    "counter.total.paper",
    "counter.paper.black.a3",
    "counter.paper.black.a4",
    "counter.paper.full_color.a3",
    "counter.paper.full_color.a4",
    "counter.paper.single_two_color.a3",
    "counter.paper.single_two_color.a4",
)


def meter_counter_rows(reading: MeterReading) -> list[tuple[object, ...]]:
    """Return every Web Connection value without filtering or collapsing duplicate subjects."""
    return [
        (
            item.canonical_field,
            item.label,
            item.count,
            item.category,
            item.subject_name or item.subject_id or item.subject_type or "",
            item.source_path,
            reading.auth_state.value,
        )
        for item in reading.counters
    ]


@dataclass(frozen=True)
class OperationResult:
    kind: Literal["scan", "calibration", "progress", "meter", "meter_export"]
    snapshot: DeviceSnapshot | None = None
    before_snapshot: DeviceSnapshot | None = None
    deltas: tuple[CounterDelta, ...] = ()
    job_id: str | None = None
    progress: ScanProgress | None = None
    meter: MeterReading | None = None
    meter_export: MeterExportTable | None = None
    meter_export_kind: MeterExportKind | None = None
    error: str | None = None


class ProfilerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("KOMI SNMP Profiler")
        self.geometry("1380x820")
        self.minsize(1080, 680)
        self.snapshot: DeviceSnapshot | None = None
        self.last_quick_snapshot: DeviceSnapshot | None = None
        self.before_snapshot: DeviceSnapshot | None = None
        self.meter_reading: MeterReading | None = None
        self.results: queue.Queue[OperationResult] = queue.Queue()
        self.filter_text = tk.StringVar()
        self.calibration_job = tk.StringVar(value=CALIBRATION_JOBS[0])
        self.expected_pages = tk.StringVar(value="1")
        self.printer_name = tk.StringVar()
        self.scan_mode = tk.StringVar(value="Quick")
        self.scan_cancel_event: threading.Event | None = None
        self.print_backend = system_print_backend()
        self.status_text = tk.StringVar(value="พร้อมตรวจเครื่อง bizhub Office")
        self.meter_auth_text = tk.StringVar(value="Administrator: ยังไม่ได้ตั้ง password")
        self.credential_store = SessionCredentialStore()
        self.meter_export_views: dict[MeterExportKind, tuple[ttk.Treeview, tk.StringVar, ttk.Button]] = {}
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.after(150, self.refresh_printers)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        connection = ttk.LabelFrame(root, text="Connection", padding=10)
        connection.pack(fill="x")

        self.host = self._field(connection, "IP / Host", "", 0, 0, 22)
        self.community = self._field(connection, "Community", "public", 0, 2, 16, show="•")
        self.port = self._field(connection, "Port", "161", 0, 4, 7)
        ttk.Label(connection, text="Version").grid(row=0, column=6, padx=(12, 4), sticky="w")
        self.version = ttk.Combobox(connection, values=("2c", "1", "3"), state="readonly", width=6)
        self.version.set("2c")
        self.version.grid(row=0, column=7, sticky="w")
        ttk.Label(connection, text="Mode").grid(row=0, column=8, padx=(12, 4), sticky="w")
        self.scan_mode_combo = ttk.Combobox(
            connection,
            textvariable=self.scan_mode,
            values=("Quick", "Deep"),
            state="readonly",
            width=7,
        )
        self.scan_mode_combo.grid(row=0, column=9, sticky="w")
        self.scan_button = ttk.Button(connection, text="Scan SNMP", command=self.scan)
        self.scan_button.grid(row=0, column=10, padx=(16, 4))
        self.cancel_button = ttk.Button(connection, text="Cancel", command=self.cancel_scan, state="disabled")
        self.cancel_button.grid(row=0, column=11)

        meter = ttk.LabelFrame(root, text="Administrator Meter Reader", padding=8)
        meter.pack(fill="x", pady=(8, 0))
        ttk.Label(meter, textvariable=self.meter_auth_text).pack(side="left")
        ttk.Button(meter, text="Change Password (Session)", command=self.configure_admin_credential).pack(
            side="left", padx=(16, 6)
        )
        self.meter_button = ttk.Button(meter, text="Read Meter", command=self.read_meter)
        self.meter_button.pack(side="left")

        v3 = ttk.LabelFrame(root, text="SNMP v3 (ใช้เมื่อ Version = 3)", padding=8)
        v3.pack(fill="x", pady=(8, 0))
        self.v3_username = self._field(v3, "Read user", "initial", 0, 0, 14)
        ttk.Label(v3, text="Security").grid(row=0, column=2, padx=(12, 4), sticky="w")
        self.v3_security = ttk.Combobox(
            v3,
            values=("authPriv", "authNoPriv", "noAuthNoPriv"),
            state="readonly",
            width=13,
        )
        self.v3_security.set("authPriv")
        self.v3_security.grid(row=0, column=3, sticky="w")
        self.v3_auth = self._field(v3, "Auth password", "", 0, 4, 14, show="•")
        self.v3_priv = self._field(v3, "Privacy password", "", 0, 6, 14, show="•")
        self.v3_context = self._field(v3, "Context", "", 0, 8, 12)

        print_tools = ttk.LabelFrame(root, text="Automatic Print & Calibrate", padding=10)
        print_tools.pack(fill="x", pady=(10, 0))
        ttk.Label(print_tools, text="Printer").pack(side="left")
        self.printer_combo = ttk.Combobox(
            print_tools,
            textvariable=self.printer_name,
            state="readonly",
            width=28,
        )
        self.printer_combo.pack(side="left", padx=(5, 5))
        ttk.Button(print_tools, text="Refresh", command=self.refresh_printers).pack(side="left", padx=(0, 14))
        ttk.Label(print_tools, text="Test job").pack(side="left")
        job = ttk.Combobox(
            print_tools,
            textvariable=self.calibration_job,
            values=CALIBRATION_JOBS,
            state="readonly",
            width=12,
        )
        job.pack(side="left", padx=(5, 8))
        ttk.Label(print_tools, text="Pages").pack(side="left")
        ttk.Entry(print_tools, textvariable=self.expected_pages, width=5).pack(side="left", padx=(5, 10))
        self.print_button = ttk.Button(print_tools, text="Print & Calibrate", command=self.print_and_calibrate)
        self.print_button.pack(side="left")

        tools = ttk.Frame(root, padding=(0, 10))
        tools.pack(fill="x")
        ttk.Label(tools, text="Manual calibration").pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Save as BEFORE", command=self.save_before).pack(side="left")
        ttk.Button(tools, text="Compare AFTER", command=self.show_deltas).pack(side="left", padx=6)
        ttk.Button(tools, text="Export JSON", command=lambda: self.export("json")).pack(side="left", padx=(18, 6))
        ttk.Button(tools, text="Export CSV", command=lambda: self.export("csv")).pack(side="left")
        ttk.Button(tools, text="Counter Candidates", command=self.show_counter_candidates).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(tools, text="Decoded Tables", command=self.show_decoded_tables).pack(side="left", padx=(8, 0))
        ttk.Label(tools, text="Filter").pack(side="left", padx=(16, 5))
        search = ttk.Entry(tools, textvariable=self.filter_text, width=32)
        search.pack(side="left")
        search.bind("<KeyRelease>", lambda _event: self.render_snapshot())

        columns = ("oid", "label", "value", "field", "confidence", "description")
        self.tree = ttk.Treeview(root, columns=columns, show="headings")
        for column, title, width in (
            ("oid", "OID", 245),
            ("label", "ชื่อค่า", 180),
            ("value", "Raw value", 180),
            ("field", "KOMI field", 180),
            ("confidence", "Confidence", 90),
            ("description", "ความหมาย", 360),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=70)
        scroll_y = ttk.Scrollbar(root, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(root, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.pack(fill="both", expand=True, side="left")
        scroll_y.pack(fill="y", side="right")
        scroll_x.pack(fill="x", side="bottom")

        status = ttk.Label(self, textvariable=self.status_text, relief="sunken", anchor="w", padding=6)
        status.pack(fill="x", side="bottom")

    def _field(
        self,
        parent: ttk.Widget,
        label: str,
        default: str,
        row: int,
        column: int,
        width: int,
        show: str | None = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=column, padx=(8, 4), sticky="w")
        entry = ttk.Entry(parent, width=width, show=show)
        entry.insert(0, default)
        entry.grid(row=row, column=column + 1, sticky="w")
        return entry

    def _settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            host=self.host.get(),
            community=self.community.get(),
            port=int(self.port.get()),
            version=self.version.get(),
            v3_username=self.v3_username.get(),
            v3_security_level=self.v3_security.get(),
            v3_auth_password=self.v3_auth.get(),
            v3_priv_password=self.v3_priv.get(),
            v3_context=self.v3_context.get(),
        )

    def scan(self) -> None:
        try:
            settings = self._settings()
        except (ValueError, TypeError) as err:
            messagebox.showerror("Connection ไม่ถูกต้อง", str(err))
            return
        self.scan_button.configure(state="disabled")
        self.print_button.configure(state="disabled")
        self.meter_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.scan_cancel_event = threading.Event()
        mode = ScanMode.DEEP if self.scan_mode.get() == "Deep" else ScanMode.QUICK
        self.status_text.set(f"กำลัง {mode.value.title()} Scan จาก {settings.host}…")

        def worker() -> None:
            try:

                def on_progress(progress: ScanProgress) -> None:
                    self.results.put(OperationResult(kind="progress", progress=progress))

                collector = PySnmpCollector(
                    scan_mode=mode,
                    progress_callback=on_progress,
                    cancel_event=self.scan_cancel_event,
                )
                snapshot = asyncio.run(
                    ProfilerService(collector, WebConnectionCounterConnector()).scan(settings)
                )
                self.results.put(OperationResult(kind="scan", snapshot=snapshot))
            except (SnmpCollectionError, SnmpScanCancelled, ValueError) as err:
                self.results.put(OperationResult(kind="scan", error=str(err)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_result)

    def _poll_result(self) -> None:
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_result)
            return
        if result.kind == "progress" and result.progress:
            progress = result.progress
            self.status_text.set(
                f"{progress.mode.value.title()} Scan · {progress.oids_collected:,} OIDs · "
                f"root {progress.roots_completed}/{progress.roots_total}"
            )
            self.after(100, self._poll_result)
            return
        self.scan_button.configure(state="normal")
        self.print_button.configure(state="normal")
        self.meter_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.scan_cancel_event = None
        if result.error:
            if result.kind == "meter_export" and result.meter_export_kind:
                view = self.meter_export_views.get(result.meter_export_kind)
                if view:
                    _tree, status, button = view
                    status.set(result.error)
                    button.configure(state="normal")
            self.status_text.set("Operation ไม่สำเร็จ")
            messagebox.showerror("KOMI SNMP Profiler", result.error)
            return
        if result.kind == "meter_export" and result.meter_export and result.meter_export_kind:
            self._render_meter_export(result.meter_export)
            return
        if result.kind == "meter" and result.meter:
            self.meter_reading = result.meter
            self._open_meter_reading(result.meter)
            self.meter_auth_text.set(
                f"Auth: {result.meter.auth_state.value} · Source: {result.meter.source}"
            )
            self.status_text.set(
                f"Read Meter สำเร็จ · {len(result.meter.counters):,} counters · "
                f"auth {result.meter.auth_state.value} · warnings {len(result.meter.warnings)}"
            )
            return
        if result.kind == "calibration":
            self.before_snapshot = result.before_snapshot
            self.snapshot = result.snapshot
            self.render_snapshot()
            self._open_deltas(list(result.deltas))
            self.status_text.set(
                f"Print & Calibrate สำเร็จ · job {result.job_id} · พบ Counter ที่เพิ่ม {len(result.deltas)} ค่า"
            )
            return
        self.snapshot = result.snapshot
        self.render_snapshot()
        if self.snapshot:
            warning = f" · warnings {len(self.snapshot.warnings)}" if self.snapshot.warnings else ""
            comparison = ""
            if self.snapshot.scan_mode == ScanMode.QUICK:
                self.last_quick_snapshot = self.snapshot
            elif self.last_quick_snapshot and self.last_quick_snapshot.host == self.snapshot.host:
                quick_oids = {item.oid for item in self.last_quick_snapshot.values}
                extra_count = sum(item.oid not in quick_oids for item in self.snapshot.values)
                comparison = f" · มากกว่า Quick {extra_count:,} OIDs"
            self.status_text.set(
                f"{self.snapshot.scan_mode.value.title()} Scan พบ {len(self.snapshot.values):,} OIDs · "
                f"Counter candidates {len(self.snapshot.counter_candidates):,} ค่า · "
                f"Web counters {len(self.snapshot.web_counters):,} ค่า · "
                f"Decoded {len(self.snapshot.entities):,} รายการ จาก {self.snapshot.host}{comparison}{warning}"
            )

    def cancel_scan(self) -> None:
        if self.scan_cancel_event:
            self.scan_cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_text.set("กำลังยกเลิก Scan…")

    def _meter_reader(self) -> MeterReader:
        return MeterReader(self.credential_store)

    def _close_app(self) -> None:
        self.credential_store.clear()
        self.destroy()

    def configure_admin_credential(self) -> None:
        host = self.host.get().strip()
        try:
            MeterReader._host(host)
        except ValueError as err:
            messagebox.showerror("IP / Host ไม่ถูกต้อง", str(err))
            return
        window = tk.Toplevel(self)
        window.title("Administrator Password")
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Device: {host}").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Account").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(frame, text="Administrator").grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text="Administrator password").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=8)
        password = ttk.Entry(frame, width=28, show="•")
        password.grid(row=2, column=1, sticky="w", pady=8)

        def save() -> None:
            try:
                self._meter_reader().save_credential(
                    host,
                    AdminCredential(password=password.get()),
                )
            except (CredentialStoreError, ValueError) as err:
                password.delete(0, "end")
                messagebox.showerror("Credential store", str(err), parent=window)
                return
            password.delete(0, "end")
            self.meter_auth_text.set("Administrator: ใช้ password ที่เปลี่ยนใน session นี้")
            window.destroy()

        def remove() -> None:
            try:
                self._meter_reader().delete_credential(host)
            except CredentialStoreError as err:
                messagebox.showerror("Credential store", str(err), parent=window)
                return
            password.delete(0, "end")
            self.meter_auth_text.set("Administrator: ยังไม่ได้ตั้ง password")
            window.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Reset Default", command=remove).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Use This Session", command=save).pack(side="left")
        password.focus_set()
        window.transient(self)
        window.grab_set()

    def read_meter(self) -> None:
        host = self.host.get().strip()
        try:
            MeterReader._host(host)
        except ValueError as err:
            messagebox.showerror("IP / Host ไม่ถูกต้อง", str(err))
            return
        self.scan_button.configure(state="disabled")
        self.print_button.configure(state="disabled")
        self.meter_button.configure(state="disabled")
        self.status_text.set(f"กำลังอ่าน Meter จาก {host}…")

        def worker() -> None:
            try:
                reading = self._meter_reader().read(host)
                self.results.put(OperationResult(kind="meter", meter=reading))
            except (CredentialStoreError, WebConnectionError, ValueError) as err:
                self.results.put(OperationResult(kind="meter", error=str(err)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_result)

    def _open_meter_reading(self, reading: MeterReading) -> None:
        window = tk.Toplevel(self)
        window.title(f"Meter Reader — {reading.host}")
        window.geometry("1240x640")
        ttk.Label(
            window,
            text=(
                f"Source: {reading.source} · Auth: {reading.auth_state.value} · "
                f"Warnings: {len(reading.warnings)}"
            ),
            padding=10,
        ).pack(fill="x")
        actions = ttk.Frame(window, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="Export Meter JSON", command=lambda: self.export_meter("json")).pack(side="right")
        ttk.Button(actions, text="Export Meter CSV", command=lambda: self.export_meter("csv")).pack(
            side="right", padx=(0, 6)
        )

        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        summary_tab = ttk.Frame(notebook)
        all_tab = ttk.Frame(notebook)
        export_tab = ttk.Frame(notebook)
        notebook.add(summary_tab, text="Summary")
        notebook.add(all_tab, text=f"All Web Connection Counters ({len(reading.counters):,})")
        notebook.add(export_tab, text="User / Account Track Export")

        summary_tree = ttk.Treeview(
            summary_tab,
            columns=("field", "label", "count", "subject", "source", "auth"),
            show="headings",
        )
        for column, title, width in (
            ("field", "Canonical field", 250),
            ("label", "Meter", 210),
            ("count", "Count", 100),
            ("subject", "Account / User", 170),
            ("source", "Source", 220),
            ("auth", "Auth", 110),
        ):
            summary_tree.heading(column, text=title)
            summary_tree.column(column, width=width)
        by_field = {item.canonical_field: item for item in reading.counters if item.subject_type is None}
        for field in METER_SUMMARY_FIELDS:
            item = by_field.get(field)
            summary_tree.insert(
                "",
                "end",
                values=(
                    field,
                    item.label if item else "ไม่พบใน response",
                    item.count if item else "—",
                    "",
                    reading.source,
                    reading.auth_state.value,
                ),
            )
        summary_tree.pack(fill="both", expand=True)

        all_tree = ttk.Treeview(
            all_tab,
            columns=("field", "label", "count", "category", "subject", "source_path", "auth"),
            show="headings",
        )
        for column, title, width in (
            ("field", "Canonical field", 230),
            ("label", "Web Connection value", 200),
            ("count", "Count", 90),
            ("category", "Category", 130),
            ("subject", "Account / User", 150),
            ("source_path", "Source path", 350),
            ("auth", "Auth", 100),
        ):
            all_tree.heading(column, text=title)
            all_tree.column(column, width=width, minwidth=70)
        for row in meter_counter_rows(reading):
            all_tree.insert("", "end", values=row)
        all_scroll_y = ttk.Scrollbar(all_tab, orient="vertical", command=all_tree.yview)
        all_scroll_x = ttk.Scrollbar(all_tab, orient="horizontal", command=all_tree.xview)
        all_tree.configure(yscrollcommand=all_scroll_y.set, xscrollcommand=all_scroll_x.set)
        all_scroll_y.pack(fill="y", side="right")
        all_scroll_x.pack(fill="x", side="bottom")
        all_tree.pack(fill="both", expand=True, side="left")

        ttk.Label(
            export_tab,
            text="Meter Count > PC export · รับและ parse ใน RAM เท่านั้น ไม่มีไฟล์ใน Downloads",
            padding=(8, 8, 8, 4),
        ).pack(fill="x")
        export_notebook = ttk.Notebook(export_tab)
        export_notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.meter_export_views.clear()
        for kind, title in (("User", "User Counter"), ("Track", "Account Track")):
            self._build_meter_export_view(export_notebook, reading.host, kind, title)

    def _build_meter_export_view(
        self,
        notebook: ttk.Notebook,
        host: str,
        kind: MeterExportKind,
        title: str,
    ) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=title)
        toolbar = ttk.Frame(tab, padding=8)
        toolbar.pack(fill="x")
        status = tk.StringVar(value=f"กด Load {title} เพื่อรับข้อมูลจาก Web Connection")
        ttk.Label(toolbar, textvariable=status).pack(side="left", fill="x", expand=True)
        button = ttk.Button(
            toolbar,
            text=f"Load {title}",
            command=lambda: self._load_meter_export(host, kind),
        )
        button.pack(side="right")
        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(table_frame, show="headings")
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(fill="y", side="right")
        scroll_x.pack(fill="x", side="bottom")
        tree.pack(fill="both", expand=True, side="left")
        self.meter_export_views[kind] = (tree, status, button)

    def _load_meter_export(self, host: str, kind: MeterExportKind) -> None:
        view = self.meter_export_views.get(kind)
        if not view:
            return
        _tree, status, button = view
        label = "User Counter" if kind == "User" else "Account Track"
        status.set(f"กำลังสร้างและรับ {label} export เข้า RAM…")
        button.configure(state="disabled")

        def worker() -> None:
            try:
                table = MeterExportReader(self.credential_store).read(host, kind)
                self.results.put(
                    OperationResult(
                        kind="meter_export",
                        meter_export=table,
                        meter_export_kind=kind,
                    )
                )
            except (CredentialStoreError, WebConnectionError, ValueError) as err:
                self.results.put(
                    OperationResult(kind="meter_export", meter_export_kind=kind, error=str(err))
                )

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_result)

    def _render_meter_export(self, table: MeterExportTable) -> None:
        view = self.meter_export_views.get(table.kind)
        if not view:
            return
        tree, status, button = view
        tree.delete(*tree.get_children())
        column_ids = tuple(f"column_{index}" for index in range(len(table.columns)))
        tree.configure(columns=column_ids)
        for column_id, heading in zip(column_ids, table.columns, strict=True):
            tree.heading(column_id, text=heading)
            tree.column(column_id, width=max(110, min(260, len(heading) * 10)), minwidth=80)
        for row in table.rows:
            tree.insert("", "end", values=row)
        visible_delimiter = "TAB" if table.delimiter == "\t" else table.delimiter
        status.set(
            f"รับข้อมูลสำเร็จ {len(table.rows):,} แถว · {len(table.columns):,} คอลัมน์ · "
            f"encoding {table.encoding} · delimiter {visible_delimiter} · RAM only"
        )
        button.configure(state="normal")
        self.status_text.set(f"โหลด {table.kind} Meter Count export สำเร็จ · {len(table.rows):,} แถว")

    def export_meter(self, export_type: str) -> None:
        if not self.meter_reading:
            messagebox.showinfo("Meter Export", "กรุณา Read Meter ก่อน")
            return
        extension = ".json" if export_type == "json" else ".csv"
        path = filedialog.asksaveasfilename(
            title=f"Export Meter {export_type.upper()}",
            defaultextension=extension,
            filetypes=[(export_type.upper(), f"*{extension}")],
        )
        if not path:
            return
        try:
            if export_type == "json":
                exported = export_meter_json(self.meter_reading, path)
            else:
                exported = export_meter_csv(self.meter_reading, path)
        except OSError as err:
            messagebox.showerror("Meter Export", str(err))
            return
        self.status_text.set(f"Export Meter แล้ว: {exported}")

    def refresh_printers(self) -> None:
        try:
            printers = self.print_backend.list_printers()
        except PrintingError as err:
            self.printer_combo.configure(values=())
            self.status_text.set(str(err))
            return
        self.printer_combo.configure(values=printers)
        if printers and self.printer_name.get() not in printers:
            self.printer_name.set(printers[0])
        if not printers:
            self.status_text.set("ไม่พบ printer queue ที่ติดตั้งในระบบ")

    def _print_request(self) -> PrintTestRequest:
        job_type = self.calibration_job.get()
        paper_size, mode = job_type.split(maxsplit=1)
        return PrintTestRequest(
            printer=self.printer_name.get(),
            paper_size=paper_size,
            color=mode == "Color",
            pages=int(self.expected_pages.get()),
        )

    def print_and_calibrate(self) -> None:
        try:
            settings = self._settings()
            request = self._print_request()
        except (TypeError, ValueError) as err:
            messagebox.showerror("ข้อมูลไม่ถูกต้อง", str(err))
            return
        confirmed = messagebox.askyesno(
            "ยืนยันการพิมพ์จริง",
            f"ส่ง {request.document_name}\nไปยัง {request.printer}\n\n"
            "แอปจะอ่าน SNMP ก่อนพิมพ์ รอคิวจบ แล้วอ่านอีกครั้ง ต้องการดำเนินการหรือไม่?",
        )
        if not confirmed:
            return

        self.scan_button.configure(state="disabled")
        self.print_button.configure(state="disabled")
        self.status_text.set(f"กำลังเก็บ BEFORE และส่ง {request.document_name}…")

        def worker() -> None:
            try:
                result = asyncio.run(
                    run_print_calibration(
                        settings,
                        PySnmpCollector(),
                        self.print_backend,
                        request,
                        counter_connector=WebConnectionCounterConnector(),
                    )
                )
                self.results.put(
                    OperationResult(
                        kind="calibration",
                        snapshot=result.after,
                        before_snapshot=result.before,
                        deltas=result.deltas,
                        job_id=result.job_id,
                    )
                )
            except (PrintingError, SnmpCollectionError, ValueError) as err:
                self.results.put(OperationResult(kind="calibration", error=str(err)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_result)

    def render_snapshot(self) -> None:
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        if not self.snapshot:
            return
        query = self.filter_text.get().strip().lower()
        for item in self.snapshot.values:
            haystack = " ".join(
                (item.oid, item.label, item.value, item.canonical_field or "", item.description_th)
            ).lower()
            if query and query not in haystack:
                continue
            self.tree.insert(
                "",
                "end",
                values=(
                    item.oid,
                    item.label,
                    item.value,
                    item.canonical_field or "—",
                    item.confidence.value,
                    item.description_th,
                ),
            )
        for item in self.snapshot.web_counters:
            haystack = " ".join((item.source_path, item.label, str(item.count), item.canonical_field)).lower()
            if query and query not in haystack:
                continue
            self.tree.insert(
                "",
                "end",
                values=(
                    f"WEB:{item.source_path}",
                    item.label,
                    item.count,
                    item.canonical_field,
                    item.confidence.value,
                    "ค่าจาก Web Connection JSON API; ใช้เมื่อ SNMP ไม่เปิดเผย Counter รายละเอียด",
                ),
            )

    def show_decoded_tables(self) -> None:
        if not self.snapshot:
            messagebox.showinfo("Decoded Tables", "กรุณา Scan เครื่องก่อน")
            return
        window = tk.Toplevel(self)
        window.title("Decoded SNMP Tables")
        window.geometry("1080x520")
        ttk.Label(
            window,
            text=(
                f"ประกอบ indexed tables ได้ {len(self.snapshot.entities):,} รายการ "
                f"จาก {len(self.snapshot.values):,} OIDs"
            ),
            padding=10,
        ).pack(fill="x")
        ttk.Button(window, text="Export Decoded CSV", command=self.export_decoded).pack(anchor="e", padx=10)
        tree = ttk.Treeview(window, columns=("category", "index", "name", "fields"), show="headings")
        for column, title, width in (
            ("category", "Category", 140),
            ("index", "SNMP index", 140),
            ("name", "Name", 250),
            ("fields", "Decoded fields", 520),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width)
        for entity in self.snapshot.entities:
            fields = " · ".join(f"{key}={value}" for key, value in entity.fields)
            tree.insert("", "end", values=(entity.category, entity.index, entity.name, fields))
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def show_counter_candidates(self) -> None:
        if not self.snapshot:
            messagebox.showinfo("Counter Candidates", "กรุณา Scan เครื่องก่อน")
            return
        window = tk.Toplevel(self)
        window.title("Print-volume Counter Candidates")
        window.geometry("1180x560")
        ttk.Label(
            window,
            text=(
                f"พบค่าที่อาจเป็นปริมาณการพิมพ์ {len(self.snapshot.counter_candidates):,} ค่า · "
                "mapped = Standard Printer MIB, inferred/unknown ต้องยืนยันด้วย Print & Calibrate"
            ),
            padding=10,
        ).pack(fill="x")
        ttk.Button(window, text="Export Counter CSV", command=self.export_counter_candidates).pack(
            anchor="e", padx=10
        )
        tree = ttk.Treeview(
            window,
            columns=("oid", "label", "value", "unit", "confidence", "reason"),
            show="headings",
        )
        for column, title, width in (
            ("oid", "OID", 270),
            ("label", "ค่าที่อาจเป็น Counter", 230),
            ("value", "ปริมาณ", 110),
            ("unit", "หน่วย", 110),
            ("confidence", "Confidence", 90),
            ("reason", "เหตุผล / วิธีตรวจ", 340),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width)
        for item in self.snapshot.counter_candidates:
            tree.insert(
                "",
                "end",
                values=(item.oid, item.label, item.value, item.unit, item.confidence.value, item.reason),
            )
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def export_counter_candidates(self) -> None:
        if not self.snapshot or not self.snapshot.counter_candidates:
            messagebox.showinfo("Counter Candidates", "ยังไม่พบ Counter candidate สำหรับ export")
            return
        path = filedialog.asksaveasfilename(
            title="Export Counter Candidates CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            exported = export_counter_candidates_csv(self.snapshot, path)
        except OSError as err:
            messagebox.showerror("Export error", str(err))
            return
        self.status_text.set(f"Export Counter candidates แล้ว: {exported}")

    def export_decoded(self) -> None:
        if not self.snapshot or not self.snapshot.entities:
            messagebox.showinfo("Decoded Tables", "ยังไม่มี decoded entities สำหรับ export")
            return
        path = filedialog.asksaveasfilename(
            title="Export Decoded CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            exported = export_decoded_csv(self.snapshot, path)
        except OSError as err:
            messagebox.showerror("Export error", str(err))
            return
        self.status_text.set(f"Export decoded tables แล้ว: {exported}")

    def save_before(self) -> None:
        if not self.snapshot:
            messagebox.showinfo("Calibration", "กรุณา Scan เครื่องก่อน")
            return
        self.before_snapshot = self.snapshot
        self.status_text.set(f"บันทึก BEFORE แล้ว ({len(self.snapshot.values):,} OIDs) — ให้พิมพ์งานควบคุมแล้ว Scan อีกครั้ง")

    def show_deltas(self) -> None:
        if not self.before_snapshot or not self.snapshot:
            messagebox.showinfo("Calibration", "ต้อง Save as BEFORE แล้ว Scan AFTER ก่อน")
            return
        try:
            expected_pages = int(self.expected_pages.get())
            if expected_pages <= 0:
                raise ValueError("จำนวนหน้าทดสอบต้องมากกว่า 0")
            deltas = compare_snapshots(self.before_snapshot, self.snapshot, expected_pages)
        except (TypeError, ValueError) as err:
            messagebox.showerror("Calibration", str(err))
            return
        self._open_deltas(deltas)

    def _open_deltas(self, deltas: list[CounterDelta]) -> None:
        try:
            expected_pages = int(self.expected_pages.get())
        except ValueError:
            expected_pages = 0
        window = tk.Toplevel(self)
        window.title("Calibration — Counter changes")
        window.geometry("980x480")
        ttk.Label(
            window,
            text=(
                f"Test: {self.calibration_job.get()} · {expected_pages} หน้า — "
                "ค่าที่ตรงจำนวนหน้าเป็น candidate และยังต้องทดสอบซ้ำ"
            ),
            padding=10,
        ).pack(fill="x")
        tree = ttk.Treeview(
            window,
            columns=("oid", "label", "before", "after", "delta", "match", "confidence"),
            show="headings",
        )
        for column, title, width in (
            ("oid", "OID", 260),
            ("label", "ชื่อ", 210),
            ("before", "Before", 100),
            ("after", "After", 100),
            ("delta", "เพิ่ม", 80),
            ("match", "ตรงงานทดสอบ", 110),
            ("confidence", "Confidence", 100),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width)
        for item in deltas:
            tree.insert(
                "",
                "end",
                values=(
                    item.oid,
                    item.label,
                    item.before,
                    item.after,
                    item.delta,
                    "YES" if item.matches_expected else "",
                    item.confidence.value,
                ),
            )
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.status_text.set(f"Calibration พบ Counter ที่เพิ่ม {len(deltas)} ค่า")

    def export(self, export_type: str) -> None:
        if not self.snapshot:
            messagebox.showinfo("Export", "กรุณา Scan เครื่องก่อน")
            return
        extension = ".json" if export_type == "json" else ".csv"
        path = filedialog.asksaveasfilename(
            title=f"Export {export_type.upper()}",
            defaultextension=extension,
            filetypes=[(export_type.upper(), f"*{extension}")],
        )
        if not path:
            return
        try:
            exported = export_json(self.snapshot, path) if export_type == "json" else export_csv(self.snapshot, path)
        except OSError as err:
            messagebox.showerror("Export error", str(err))
            return
        self.status_text.set(f"Export แล้ว: {exported}")


def main() -> None:
    ProfilerApp().mainloop()


if __name__ == "__main__":
    main()
