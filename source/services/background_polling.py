from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from database import get_cfg, set_cfg
from komi_snmp_profiler.connectors import (
    WebConnectionSessionBusyError,
    WebConnectionUnsupportedError,
)
from komi_snmp_profiler.meter import MeterReader
from services.daily_cache import DailyCacheStore
from services.device_config import DatabaseCredentialStore, DeviceConfig, DeviceConfigRepository
from services.live_meter_service import meter_reading_to_report
from services.parser_mapping import apply_parser_mapping_overrides
from services.pipeline_log import pipeline_log
from services.computer_names import local_computer_name
from services.polling import DevicePollState, PollingPolicy, PollingStateMachine
from services.raw_counter_history import RawCounterHistoryStore
from services.reconciliation import reconcile_web_counters
from services.runtime_snapshots import runtime_snapshots
from services.snmp_probe import SnmpTotalProbe
from services.subject_history import SubjectDailyCacheStore
from services.sync_schedule import load_schedule_windows
from services.web_observations import WebObservationStore

log = logging.getLogger(__name__)


class BackgroundPollingCoordinator(QObject):
    device_updated = pyqtSignal(int)
    reading_saved = pyqtSignal(int)
    activity_changed = pyqtSignal()
    shared_settings_applied = pyqtSignal()

    def __init__(
        self,
        repository: DeviceConfigRepository | None = None,
        *,
        probe: SnmpTotalProbe | None = None,
        reader: MeterReader | None = None,
        cache: DailyCacheStore | None = None,
        subject_cache: SubjectDailyCacheStore | None = None,
        raw_counter_history: RawCounterHistoryStore | None = None,
        observations: WebObservationStore | None = None,
        peer_history=None,
        shared_reads=None,
        clock=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self.probe = probe or SnmpTotalProbe()
        self.reader = reader or MeterReader(
            DatabaseCredentialStore(self.repository),
            allow_implicit_name_export=True,
        )
        self.cache = cache or DailyCacheStore()
        self.subject_cache = subject_cache or SubjectDailyCacheStore()
        self.raw_counter_history = raw_counter_history or RawCounterHistoryStore()
        self.observations = observations or WebObservationStore()
        # Attached only by a verified member/session provider. Discovery alone
        # never suppresses local collection or authorizes shared observations.
        self.shared_reads = shared_reads
        self.peer_settings = None
        self.peer_network = None
        self.peer_web_view = None
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.machine = PollingStateMachine()
        self.snmp_interval = timedelta(minutes=5)
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="komi-meter")
        self.states: dict[int, DevicePollState] = {}
        self._poll_scopes = {}
        self.last_poll: dict[int, datetime] = {}
        self.active: set[int] = set()
        self._futures: dict[int, Future] = {}
        self._started_at: dict[int, float] = {}
        self._manual_requested: set[int] = set()
        self._web_attempted: set[int] = set()
        self._scheduled_joined: dict[int, datetime] = {}
        self._lock = threading.RLock()
        self._rollover_lock = threading.RLock()
        self._paused_reason = ""
        self._started = False
        self._scheduler_initialized = False
        self._stopped = False
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.tick)
        from services.peer_history_runtime import PeerHistoryRuntime
        self.peer_history = peer_history if peer_history is not None else PeerHistoryRuntime(self)
        from services.peer_network_runtime import PeerNetworkRuntime
        self.peer_network_runtime = PeerNetworkRuntime(self)
        from services.archive_maintenance import ArchiveMaintenance
        self.archive_maintenance = ArchiveMaintenance(self, busy=self._archive_busy)
        self.archive_maintenance.reports_indexed.connect(self._shared_reports_indexed)

    def _shared_reports_indexed(self):
        from services.report_scope import report_slots
        for slot in report_slots():
            self.device_updated.emit(slot)

    def _archive_busy(self):
        with self._lock:
            return bool(self.active) or self.peer_history.busy or self._stopped

    def active_slots(self):
        with self._lock:
            return tuple(sorted(self.active))

    def bind_verified_settings(self, *, authorize, authorize_epoch):
        """Called on the Qt owner thread by the verified membership adapter."""
        from services.peer_settings_runtime import PeerSettingsRuntime
        if self.peer_settings is not None:
            self.peer_settings.stop()
        self.peer_settings = PeerSettingsRuntime(self, authorize=authorize, authorize_epoch=authorize_epoch)
        self.peer_settings.applied.connect(self.shared_settings_applied.emit)
        self.peer_settings.notify()
        return self.peer_settings

    def bind_peer_network(self, node, *, address, context, members):
        """Install the enrolled network as one unit on the Qt owner thread.

        Enrollment must wait for existing local meter jobs to finish. A failed
        bind leaves the local collector intact and does not attach half a set
        of sessions. Desktop and Agent both use this same owner boundary.
        """
        from pathlib import Path
        from services.peer_network import PeerNetworkNode
        if not isinstance(node, PeerNetworkNode):
            raise TypeError('An authenticated peer network is required')
        if Path(node.path).resolve() != Path(self.observations.path).resolve():
            raise ValueError('Peer network belongs to another database')
        if self._stopped or self.active_slots() or self.peer_network is not None:
            raise RuntimeError('Wait for idle collection before binding peer membership')
        sessions = [node.session(member) for member in sorted(set(members)) if member != node.member_id]
        try:
            bound = node.start(address, context=context)
            self.bind_verified_settings(authorize=node.authorize_settings, authorize_epoch=node.authorize_epoch)
            for session in sessions:
                self.peer_history.attach(session)
        except BaseException:
            for session in sessions:
                self.peer_history.detach(session.member)
            if self.peer_settings is not None:
                self.peer_settings.stop()
                self.peer_settings = None
            node.stop(wait=True)
            raise
        self.peer_network = node
        self.shared_reads = node.shared_reads
        from services.peer_web_view import PeerWebViewRuntime
        self.peer_web_view = PeerWebViewRuntime(self)
        node.on_data = self.peer_web_view.notify
        self.peer_web_view.notify()
        self.activity_changed.emit()
        return bound

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError("background polling cannot start after shutdown")
        if self._started:
            return
        self._started = True
        self.peer_history.start()
        self.peer_network_runtime.start()
        self.archive_maintenance.start()
        if self.is_paused:
            log.info("background polling start deferred while paused: %s", self._paused_reason)
            return
        self._activate_scheduler()

    def _activate_scheduler(self) -> None:
        """Initialize once, then start scheduling after start or resume."""
        self.reload_policy()
        if not self._scheduler_initialized:
            repaired = self.cache.repair_pending_ledger()
            if repaired:
                pipeline_log.append(
                    stage="DB",
                    action="Pending billing ledger repaired",
                    target="billing_ledger",
                    value=f"{repaired} daily records",
                    detail="startup idempotency repair",
                    status="ok",
                )
            self._finalize_before(date.today())
            pipeline_log.append(
                stage="POLICY",
                action="Background started",
                target="scheduler",
                value=f"SNMP ทุก {int(self.snmp_interval.total_seconds() // 60)} นาที",
                detail=(
                    f"Web ปกติ {int(self.machine.policy.web_interval.total_seconds() // 60)} นาที · "
                    f"Peak {int(self.machine.policy.peak_web_interval.total_seconds() // 60)} นาที"
                ),
                status="ok",
            )
            self._scheduler_initialized = True
        for device in self.repository.list(enabled_only=True):
            self.states.setdefault(
                device.slot, DevicePollState(last_snmp_total=device.last_total)
            )
        self.timer.start()
        QTimer.singleShot(250, self.tick)

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return bool(self._paused_reason)

    def pause(self, reason: str = "registration_ineligible") -> int:
        """Pause future device reads without shutting down the worker executor.

        A device read already executing is allowed to finish its current atomic
        cache transaction. Queued reads are cancelled and every later timer or
        manual-read request becomes a no-op until :meth:`resume` is called.
        """
        self.timer.stop()
        with self._lock:
            self._paused_reason = reason.strip() or "registration_ineligible"
            cancelled = sum(future.cancel() for future in list(self._futures.values()))
        log.info(
            "background polling paused: %s",
            self._paused_reason,
            extra={
                "event": "polling_paused",
                "operation": "registration_gate",
                "cancelled_queued_polls": cancelled,
            },
        )
        return cancelled

    def resume(self) -> None:
        """Resume an already-started scheduler after a temporary pause."""
        if self._stopped:
            raise RuntimeError("background polling cannot resume after shutdown")
        with self._lock:
            was_paused = bool(self._paused_reason)
            self._paused_reason = ""
        if not was_paused or not self._started:
            return
        self._activate_scheduler()
        log.info("background polling resumed")

    def stop(self, *, wait: bool = False) -> int:
        """Stop scheduling new work and cancel queued polls where possible.

        A running device read is allowed to finish its transaction/cache write;
        returning the remaining count makes shutdown state observable without
        blocking Qt's UI event loop.
        """
        self.timer.stop()
        # Serialize shutdown against submission, but release both locks before
        # draining workers (their completion callbacks also acquire _lock).
        with self._rollover_lock:
            with self._lock:
                self._stopped = True
                remaining = sum(not future.done() for future in self._futures.values())
                for future in list(self._futures.values()):
                    future.cancel()
        # Close incoming requests and fence in-flight grants before releasing
        # process ownership. Repeated stop(wait=True) drains the same listener.
        remaining += self.peer_network_runtime.stop(wait=wait)
        if self.peer_web_view is not None:
            remaining += self.peer_web_view.stop(wait=wait)
        if self.peer_network is not None:
            remaining += self.peer_network.stop(wait=wait)
        self.executor.shutdown(wait=wait, cancel_futures=True)
        if self.peer_settings is not None:
            self.peer_settings.stop()
            self.peer_settings = None
        remaining += self.peer_history.stop(wait=wait)
        remaining += self.archive_maintenance.stop(wait=wait)
        log.info(
            "background polling stopped",
            extra={"event": "polling_stopped", "operation": "shutdown", "remaining_polls": remaining},
        )
        return remaining

    def network_recovered(self):
        self.peer_network_runtime.network_recovered()
        self.peer_history.network_recovered()

    def tick(self) -> None:
        if self._stopped or self.is_paused:
            return
        now = self.clock()
        self._finalize_before(now.date())
        interval = self.machine.policy.snmp_interval_at(now, self.snmp_interval)
        if interval is None:
            return
        for device in self.repository.list(enabled_only=True):
            last = self.last_poll.get(device.slot)
            if last is None or now - last >= interval:
                self._submit(device, force_web=False)

    def reload_policy(self) -> None:
        def parse_clock(value: str, fallback: time) -> time:
            try:
                hour, minute = (int(part) for part in value.split(":", 1))
                return time(hour, minute)
            except (TypeError, ValueError):
                return fallback

        self.snmp_interval = timedelta(minutes=max(1, int(get_cfg("snmp_interval_minutes", "5") or 5)))
        self.machine = PollingStateMachine(
            PollingPolicy(
                web_interval=timedelta(minutes=max(1, int(get_cfg("web_interval_minutes", "15") or 15))),
                peak_web_interval=timedelta(minutes=max(1, int(get_cfg("peak_web_interval_minutes", "5") or 5))),
                work_start=parse_clock(get_cfg("work_start", "08:00"), time(8, 0)),
                work_end=parse_clock(get_cfg("work_end", "17:00"), time(17, 0)),
                schedule_windows=load_schedule_windows(get_cfg("sync_schedule_windows", "")),
            )
        )

    def poll_now(self, slot: int | None = None) -> None:
        if self._stopped or self.is_paused:
            return
        for device in self.repository.list(enabled_only=True):
            if slot is None or device.slot == slot:
                self._submit(device, force_web=True)

    @staticmethod
    def _oid_key(slot: int) -> str:
        return f"snmp_total_oid_{slot}"

    @staticmethod
    def _model_key(slot: int) -> str:
        return f"snmp_total_oid_model_{slot}"

    def _preferred_total_oid(self, device: DeviceConfig) -> str:
        oid = get_cfg(self._oid_key(device.slot), "") or ""
        mapped_model = get_cfg(self._model_key(device.slot), "") or ""
        if oid and mapped_model and device.model and mapped_model != device.model:
            return ""
        return oid

    def _calibrate_total_oid(self, device: DeviceConfig, probe_result, reading, *, at: datetime) -> str:
        web_total = next(
            (
                int(counter.count)
                for counter in reading.counters
                if counter.subject_type is None and counter.canonical_field == "counter.total.total"
            ),
            None,
        )
        if web_total is None or probe_result is None:
            pipeline_log.append(
                stage="POLICY",
                action="SNMP Total OID calibration pending",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="SNMP candidates ↔ Web counter.total.total",
                value="ยังไม่มีค่าครบทั้งสองฝั่ง",
                status="warning",
                at=at,
            )
            return ""

        matches = [oid for oid, value in probe_result.total_candidates if int(value) == web_total]
        current = self._preferred_total_oid(device)
        if matches:
            selected = current if current in matches else (
                SnmpTotalProbe.PRIMARY_TOTAL_OID if SnmpTotalProbe.PRIMARY_TOTAL_OID in matches else matches[0]
            )
            model = probe_result.model or device.model
            set_cfg(self._oid_key(device.slot), selected)
            set_cfg(self._model_key(device.slot), model)
            pipeline_log.append(
                stage="POLICY",
                action="SNMP Total OID calibrated",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=selected,
                value=f"SNMP={web_total} · Web={web_total}",
                detail=f"model={model} · candidates matched={len(matches)}",
                status="ok",
                at=at,
            )
            return selected

        set_cfg(self._oid_key(device.slot), "")
        set_cfg(self._model_key(device.slot), probe_result.model or device.model)
        pipeline_log.append(
            stage="POLICY",
            action="SNMP Total OID calibration failed",
            device_slot=device.slot,
            device_name=device.name,
            host=device.host,
            target="SNMP candidates ↔ Web counter.total.total",
            value=f"Web Total={web_total}",
            detail="ไม่มี SNMP candidate ค่าเท่ากัน; ไม่บันทึก mapping และจะเทียบใหม่รอบถัดไป",
            status="warning",
            at=at,
        )
        return ""

    def _finalize_before(self, today: date) -> None:
        with self._rollover_lock:
            self._finalize_before_locked(today)

    def _finalize_before_locked(self, today: date) -> None:
        # A worker can start shortly before midnight and still be writing the
        # previous day's cache when the first next-day timer fires. Never seal
        # that slot until its in-flight poll has completed.
        with self._lock:
            active_slots = frozenset(self.active)
        try:
            records = self.cache.finalize_before(today, exclude_slots=active_slots)
        except Exception as exc:
            log.exception("daily cache rollover failed; evidence left in cache")
            pipeline_log.append(
                stage="DB",
                action="Daily rollup failed",
                target=today.isoformat(),
                value=type(exc).__name__,
                detail="เก็บ cache เดิมไว้และจะลองใหม่รอบถัดไป",
                status="error",
            )
            records = []
        for record in records:
            pipeline_log.append(
                stage="DB",
                action="Daily rollup saved",
                device_slot=record.device_slot,
                target=record.record_date,
                value=f"{record.sample_count} Web samples",
                detail=f"errors={record.error_count} · incomplete={record.incomplete}",
                status="warning" if record.incomplete else "ok",
            )
        if active_slots:
            return
        try:
            subject_records = self.subject_cache.finalize_before(today)
        except Exception as exc:
            log.exception("subject cache rollover failed; evidence left in cache")
            pipeline_log.append(
                stage="DB",
                action="User/Account daily rollup failed",
                target=today.isoformat(),
                value=type(exc).__name__,
                detail="เก็บ RAM cache เดิมไว้และจะลองใหม่รอบถัดไป",
                status="error",
            )
            return
        if subject_records:
            pipeline_log.append(
                stage="DB",
                action="User/Account daily rollup saved",
                target=today.isoformat(),
                value=f"{len(subject_records)} append-only records",
                detail="Total Counter only · not used for Billing",
                status="warning" if any(record.reset_count for record in subject_records) else "ok",
            )

    def _submit(self, device: DeviceConfig, *, force_web: bool) -> None:
        with self._rollover_lock:
            with self._lock:
                if self._stopped or self._paused_reason:
                    return
                if device.slot in self.active:
                    if force_web:
                        self._manual_requested.add(device.slot)
                    else:
                        now = self.clock()
                        self.last_poll[device.slot] = now
                        state = self.states.get(device.slot)
                        if state is not None and self.machine.scheduled_web_due(state, now):
                            self._scheduled_joined.setdefault(device.slot, now)
                    return
                self.active.add(device.slot)
                self._manual_requested.discard(device.slot)
                self._web_attempted.discard(device.slot)
                self._scheduled_joined.pop(device.slot, None)
                if not force_web:
                    self.last_poll[device.slot] = self.clock()
                self._started_at[device.slot] = monotonic()
            pipeline_log.append(
                stage="POLICY",
                action="เริ่มรอบอ่านทันที" if force_web else "เริ่มรอบตาม Schedule",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="SNMP → Web → RAM Cache",
                value="force Web" if force_web else "ตามกฎ Total/throttle",
                status="info",
            )
            future = self.executor.submit(self._poll_device, device, force_web)
            with self._lock:
                self._futures[device.slot] = future
            future.add_done_callback(lambda item, slot=device.slot: self._finished(slot, item))
            self.activity_changed.emit()

    def _finished(self, slot: int, future: Future) -> None:
        try:
            saved = bool(future.result())
        except Exception:
            log.exception("background device poll failed: slot=%s", slot)
            saved = False
        with self._lock:
            joined = self._scheduled_joined.pop(slot, None)
            if saved and joined is not None and slot in self.states:
                state = self.states[slot]
                state.last_scheduled_web_at = joined
                state.scheduled_clock_initialized = True
            # A manual request that raced the SNMP-only early return needs
            # one real Web read, not an old snapshot and not a retry loop.
            retry_manual = slot in self._manual_requested and slot not in self._web_attempted and not saved
            self._manual_requested.discard(slot)
            self._web_attempted.discard(slot)
            self.active.discard(slot)
            self._futures.pop(slot, None)
            started = self._started_at.pop(slot, None)
        duration_ms = round((monotonic() - started) * 1000) if started is not None else None
        log.info(
            "background device poll finished",
            extra={
                "event": "poll_finished",
                "device_slot": slot,
                "operation": "device_read" if saved else "poll_failed_or_no_reading",
                "duration_ms": duration_ms,
            },
        )
        self.device_updated.emit(slot)
        self.activity_changed.emit()
        if saved:
            self.reading_saved.emit(slot)
        elif retry_manual:
            device = self.repository.get(slot)
            if device is not None and device.enabled:
                self._submit(device, force_web=True)

    def _snmp_round(self, device, state, now, preferred_oid):
        snmp_error = ""
        probe_result = None
        marker_root = getattr(self.probe, "MARKER_LIFE_ROOT", "1.3.6.1.2.1.43.10.2.1.4")
        model_root = getattr(self.probe, "MODEL_ROOT", "1.3.6.1.2.1.25.3.2.1.3")
        serial_root = getattr(self.probe, "SERIAL_ROOT", "1.3.6.1.2.1.43.5.1.1.17")
        pipeline_log.append(
            stage="SNMP",
            action="ส่ง Printer-MIB probe",
            device_slot=device.slot,
            device_name=device.name,
            host=device.host,
            target="; ".join((marker_root, model_root, serial_root)),
            value="port 161",
            status="request",
        )
        try:
            probe = (
                self.probe.read(device.host, preferred_oid=preferred_oid)
                if isinstance(self.probe, SnmpTotalProbe)
                else self.probe.read(device.host)
            )
            probe_result = probe
            decision = self.machine.snmp_success(state, probe.total, now)
            self.repository.update_runtime(
                device.slot,
                status="online",
                checked_at=now.isoformat(timespec="seconds"),
                total=probe.total,
                model=probe.model,
                serial=probe.serial,
            )
            toner = dict(probe.toner)
            paper_trays = tuple(getattr(probe, "paper_trays", ()))
            paper_alerts = tuple(getattr(probe, "paper_alerts", ()))
            paper = [tray.to_cache() for tray in paper_trays]
            paper_summary = SnmpTotalProbe.summarize_paper(paper_trays, paper_alerts)
            heartbeat = self.cache.record_heartbeat(
                device.slot,
                total=probe.total,
                toner=toner,
                paper=paper,
                paper_alerts=list(paper_alerts),
                at=now,
            )
            if probe.oid_values:
                for oid, value in probe.oid_values:
                    is_total = oid == (probe.total_oid or f"{marker_root}.1.1")
                    pipeline_log.append(
                        stage="SNMP",
                        action="Total Meter response" if is_total else "OID response",
                        device_slot=device.slot,
                        device_name=device.name,
                        host=device.host,
                        target=oid,
                        value=value,
                        status="ok",
                        at=now,
                    )
            else:
                pipeline_log.append(
                    stage="SNMP",
                    action="Probe response",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target=marker_root,
                    value=probe.total,
                    detail=f"model={probe.model} · serial={probe.serial}",
                    status="ok",
                    at=now,
                )
            pipeline_log.append(
                stage="SNMP",
                action="Toner response",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="Printer-MIB supplies",
                value=(" · ".join(f"{color}={toner[color]}%" for color in ("C", "Y", "M", "K") if color in toner) or "ไม่พบค่า"),
                status="ok" if toner else "warning",
                at=now,
            )
            pipeline_log.append(
                stage="SNMP",
                action="Paper status response",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="Printer-MIB input trays",
                value=(
                    f"state={paper_summary.state}"
                    + (f" · trays={', '.join(paper_summary.trays)}" if paper_summary.trays else "")
                ),
                detail=(
                    "SNMP input/alert tables are optional; empty is emitted only from level=0 "
                    "or an explicit paper-empty alert"
                ),
                status="warning" if paper_summary.state in {"empty", "attention"} else "ok",
                at=now,
            )
            pipeline_log.append(
                stage="RAM",
                action="SNMP heartbeat cached",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=f"runtime-cache/device-{device.slot + 1}/{now.date().isoformat()}.json",
                value=f"Total={probe.total}",
                        detail=(
                            f"heartbeat_count={heartbeat.get('heartbeat_count', 0)} · "
                            f"Web Total ล่าสุด={heartbeat.get('latest', {}).get('counter.total.total', 'ยังไม่มี')} · "
                            f"ตรงกัน={heartbeat.get('latest', {}).get('counter.total.total') == probe.total}"
                        ),
                        status=(
                            "ok"
                            if heartbeat.get("latest", {}).get("counter.total.total") in (None, probe.total)
                            else "warning"
                        ),
                        at=now,
                    )
        except Exception as exc:
            from services.support_diagnostics import diagnostic_report
            snmp_error = diagnostic_report(exc, stage='SNMP / Probe', target=device.host, device=device.name)
            decision = self.machine.snmp_failure(state, now)
            pipeline_log.append(
                stage="SNMP",
                action="Probe failed",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="Printer-MIB",
                value=snmp_error,
                status="error",
                at=now,
            )

        return decision, snmp_error, probe_result

    def _align_poll_scope(self, device):
        from services.slot_runtime import polling_scope
        scope = polling_scope(device)
        with self._lock:
            previous = self._poll_scopes.get(device.slot, scope)
            self._poll_scopes[device.slot] = scope
            if previous != scope:
                self.states[device.slot] = DevicePollState()
                self.last_poll.pop(device.slot, None)
                runtime_snapshots.clear(device.slot)

    def _poll_device(self, device: DeviceConfig, force_web: bool) -> bool:
        # A future queued before deactivation may start after pause() raced
        # with ThreadPoolExecutor. Do not let it issue its first SNMP/Web read.
        if self.is_paused:
            return False
        self._align_poll_scope(device)
        prepared = None
        if self.shared_reads is not None:
            import uuid
            prepared = self.shared_reads.prepare(device.slot, manual=force_web, probe_only=not force_web, request_id=uuid.uuid4().hex,
                cancelled=lambda: self._stopped or self.is_paused)
            if prepared is None:
                return False
        now = self.clock()
        manual_round = force_web
        round_started_at = now
        state = self.states.setdefault(device.slot, DevicePollState(last_snmp_total=device.last_total))
        snmp_error = ""
        probe_result = None
        preferred_oid = self._preferred_total_oid(device)
        calibration_needed = not preferred_oid
        if prepared is not None and not prepared.job["can_read"]:
            from services.polling import PollDecision
            decision = PollDecision(True, "waiting", "รับผลจากงานอ่านที่เริ่มก่อน")
        else:
            decision, snmp_error, probe_result = self._snmp_round(device, state, now, preferred_oid)

        scheduled_read = not manual_round and (decision.request_web or calibration_needed)
        if prepared is not None and not prepared.job["can_read"]:
            scheduled_read = scheduled_read and self.machine.scheduled_web_due(state, now)
        with self._lock:
            force_web = force_web or device.slot in self._manual_requested
        if prepared is not None and prepared.job["can_read"] and not manual_round:
            prepared = self.shared_reads.finish_probe(prepared,
                request_web=bool(force_web or decision.request_web or calibration_needed),
                cancelled=lambda: self._stopped or self.is_paused)
            if prepared is not None:
                # A peer may have joined the SNMP grant while the probe ran.
                # Its manual request requires Web without moving this PC's
                # original scheduled Web anchor when Web was not due.
                force_web = True
        pipeline_log.append(
            stage="POLICY",
            action="เรียก Web Connection" if force_web or decision.request_web or calibration_needed else "ข้าม Web Connection",
            device_slot=device.slot,
            device_name=device.name,
            host=device.host,
            target="PollingStateMachine",
            value=(
                "ผู้ใช้กดอ่านทันที (force Web)"
                if force_web
                else "ยังไม่มี OID mapping; ใช้ Web เทียบ SNMP candidates"
                if calibration_needed
                else decision.reason
            ),
            detail=f"status={decision.status} · pending_detail={state.pending_detail}",
            status="request" if force_web or decision.request_web or calibration_needed else "skip",
            at=now,
        )

        if not (force_web or decision.request_web or calibration_needed):
            if snmp_error:
                self.repository.update_runtime(
                    device.slot,
                    status=decision.status,
                    checked_at=now.isoformat(timespec="seconds"),
                    error=snmp_error,
                )
            return False

        try:
            with self._lock:
                self._web_attempted.add(device.slot)
            pipeline_log.append(
                stage="WEB",
                action="เริ่ม Web Connection read",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=f"https://{device.host}/wcd",
                value="Administrator → public fallback",
                status="request",
                at=now,
            )
            # Pin the reviewed epoch before reading Web. A confirmation that
            # races this read cannot silently bind the result to a new baseline.
            from services.slot_epoch_store import SlotEpochStore
            observed_serial = (probe_result.serial if probe_result is not None else "") or device.serial
            epoch = SlotEpochStore().head(device.slot)
            read_epoch_id = (epoch["id"] if epoch and
                epoch["document"]["baseline_event"]["payload"]["serial"] == observed_serial else None)
            def read_printer():
                return self.reader.read(
                    device.host,
                    model=(probe_result.model if probe_result is not None else "") or device.model,
                ) if isinstance(self.reader, MeterReader) else self.reader.read(device.host)
            shared_result = None
            if self.shared_reads is not None:
                import uuid
                scope = self.shared_reads.current_scope(device.slot)
                if (scope.serial, scope.epoch_id) != (observed_serial, read_epoch_id):
                    raise ValueError("Printer identity or baseline differs from shared read scope")
                shared_result = self.shared_reads.collect(device.slot, manual=force_web,
                    request_id=uuid.uuid4().hex, read=read_printer, printer_name=device.name, prepared=prepared,
                    cancelled=lambda: self._stopped or self.is_paused)
                if shared_result is None:
                    return False
                reading = shared_result.reading
            else:
                reading = read_printer()
            # Report the actual Web observation time, including a read that
            # crosses midnight. Scheduling retains its separate round anchor.
            observed_at = datetime.fromisoformat(reading.collected_at.replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                raise ValueError("Web observation requires an explicit timezone")
            now = observed_at.astimezone(round_started_at.tzinfo)
            raw_reconciliation = reconcile_web_counters(
                {
                    counter.canonical_field: counter.count
                    for counter in reading.counters
                    if counter.subject_type is None
                }
            )
            if raw_reconciliation.needs_review:
                for issue in raw_reconciliation.issues:
                    pipeline_log.append(
                        stage="WEB",
                        action="Reconciliation warning",
                        device_slot=device.slot,
                        device_name=device.name,
                        host=device.host,
                        target=issue.code,
                        value=issue.message(),
                        detail=(
                            "Web Connection Device Meter · Needs Review · ยังไม่ควรใช้คิดเงิน"
                            + (f" · {issue.breakdown()}" if issue.breakdown() else "")
                            + f" · profile={raw_reconciliation.profile_id}"
                        ),
                        status="warning",
                        at=now,
                    )
            elif raw_reconciliation.checked_count:
                pipeline_log.append(
                    stage="WEB",
                    action="Reconciliation passed",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target="Web Connection Device Meter",
                    value=f"ตรวจ {raw_reconciliation.checked_count} จุด · ผลรวมตรงกัน",
                    status="ok",
                    at=now,
                )
            observed_serial = (probe_result.serial if probe_result is not None else "") or device.serial
            saved_event = shared_result.event if shared_result is not None else None
            if observed_serial and shared_result is None:
                saved_event = self.observations.record(device.slot, reading, serial=observed_serial,
                    printer_name=device.name,
                    epoch_id=read_epoch_id,
                    at=datetime.fromisoformat(reading.collected_at.replace("Z", "+00:00")))
            elif not observed_serial:
                pipeline_log.append(stage="DB", action="Web observation identity unavailable",
                    device_slot=device.slot, device_name=device.name, host=device.host,
                    target="web_observations", value="Missing printer Serial",
                    detail="Local report only; no shareable Web observation queued", status="warning", at=now)
            ram_snapshot = runtime_snapshots.update(device.slot, reading, serial=observed_serial,
                epoch_id=read_epoch_id, event_id=saved_event['id'] if saved_event else '')
            subject_state = self.subject_cache.update_reading(device.slot, reading, at=now)
            try:
                raw_counter_count = self.raw_counter_history.update_reading(
                    device.slot,
                    reading,
                    at=now,
                )
            except Exception as exc:
                raw_counter_count = 0
                log.exception("raw counter history update failed; normalized polling continues")
                pipeline_log.append(
                    stage="DB",
                    action="Legacy raw counter history failed",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target="daily_raw_counter_records",
                    value=type(exc).__name__,
                    detail="ข้อมูล Billing/History ปกติยังทำงานต่อ; จะลองเก็บ Legacy ใหม่รอบถัดไป",
                    status="warning",
                    at=now,
                )
            pipeline_log.append(
                stage="RAM",
                action="Web/User snapshot stored in RAM",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="runtime_snapshots",
                value=f"Web={len(ram_snapshot.web_rows)} · User/Track={len(ram_snapshot.subject_rows)}",
                detail=(
                    f"source={ram_snapshot.source} · collected_at={ram_snapshot.collected_at} · "
                    f"subject daily cache={len(subject_state.get('subjects', {}))} · "
                    f"raw counters={raw_counter_count}"
                ),
                status="ok",
                at=now,
            )
            for counter in reading.counters:
                pipeline_log.append(
                    stage="WEB",
                    action="Counter response",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target=counter.source_path,
                    value=counter.count,
                    detail=f"{counter.canonical_field} · {counter.label}",
                    status="ok",
                    at=now,
                )
            calibrated_oid = self._calibrate_total_oid(device, probe_result, reading, at=now)
            if calibrated_oid:
                web_total = next(
                    (
                        int(counter.count)
                        for counter in reading.counters
                        if counter.subject_type is None and counter.canonical_field == "counter.total.total"
                    ),
                    None,
                )
                if web_total is not None:
                    state.last_snmp_total = web_total
            normalized_reading = apply_parser_mapping_overrides(
                reading,
                device.serial,
            )
            normalized_reconciliation = reconcile_web_counters(
                {
                    counter.canonical_field: counter.count
                    for counter in normalized_reading.counters
                    if counter.subject_type is None
                }
            )
            if normalized_reading is not reading:
                pipeline_log.append(
                    stage="MAP",
                    action="Parser mapping applied",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target="future normalized records",
                    value=f"raw={len(reading.counters)} · normalized={len(normalized_reading.counters)}",
                    detail="Raw/Legacy history and existing Billing Ledger were not changed",
                    status="ok",
                    at=now,
                )
                if not normalized_reconciliation.billing_safe:
                    pipeline_log.append(
                        stage="MAP",
                        action="Mapped counter reconciliation held",
                        device_slot=device.slot,
                        device_name=device.name,
                        host=device.host,
                        target="normalized daily cache",
                        value=(
                            f"issues={len(normalized_reconciliation.issues)} · "
                            f"checked={normalized_reconciliation.checked_count}"
                        ),
                        detail=(
                            "Parser mapping เปลี่ยนชุด Counter; "
                            "ไม่ใช้ผล billing-safe จาก Raw snapshot เดิม"
                        ),
                        status="warning",
                        at=now,
                    )
            cache_state = self.cache.update_reading(
                device.slot,
                normalized_reading,
                at=now,
                reconciliation=normalized_reconciliation,
            )
            if not normalized_reconciliation.billing_safe:
                pipeline_log.append(
                    stage="POLICY",
                    action="Billing evidence held for review",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target="Daily Cache reconciliation",
                    value=(
                        f"issues={len(normalized_reconciliation.issues)} · "
                        f"checked={normalized_reconciliation.checked_count}"
                    ),
                    detail=(
                        f"profile={normalized_reconciliation.profile_id} · "
                        "billing_safe=false"
                    ),
                    status="warning",
                    at=now,
                )
            for key, value in sorted(cache_state.get("latest", {}).items()):
                pipeline_log.append(
                    stage="RAM",
                    action="Normalized counter cached",
                    reader_name=local_computer_name(),
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target=key,
                    value=value,
                    detail=f"daily delta={cache_state.get('delta', {}).get(key, 0)}",
                    status="ok",
                    at=now,
                )
            pipeline_log.append(
                stage="RAM",
                action="Daily cache updated",
                reader_name=local_computer_name(),
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=f"runtime-cache/device-{device.slot + 1}/{now.date().isoformat()}.json",
                value=f"Web sample #{cache_state.get('sample_count', 0)}",
                detail=(
                    f"heartbeat={cache_state.get('heartbeat_count', 0)} · "
                    f"latest Total={cache_state.get('latest', {}).get('counter.total.total', '—')} · "
                    f"delta Total={cache_state.get('delta', {}).get('counter.total.total', 0)}"
                ),
                status="ok",
                at=now,
            )
            report = meter_reading_to_report(reading, machine_name=device.name)
            total = int(report.get("total_counter", state.last_snmp_total or 0))
            state.last_snmp_total = max(state.last_snmp_total or 0, total)
            self.machine.web_success(state, now, scheduled=scheduled_read, scheduled_at=round_started_at)
            self.repository.update_runtime(
                device.slot,
                status="online",
                checked_at=now.isoformat(timespec="seconds"),
                success_at=now.isoformat(timespec="seconds"),
                total=state.last_snmp_total,
            )
            return True
        except (WebConnectionSessionBusyError, WebConnectionUnsupportedError) as exc:
            from services.support_diagnostics import diagnostic_report
            failure_report = diagnostic_report(exc, stage='WEB / Meter', target=device.host, device=device.name)
            state.next_web_retry_at = now + self.machine.policy.retry_interval
            status = "checking" if snmp_error else "online"
            action = (
                "Web Connection session busy"
                if isinstance(exc, WebConnectionSessionBusyError)
                else "Web Connection endpoint unsupported"
            )
            pipeline_log.append(
                stage="WEB",
                action=action,
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target="read-only Meter profile",
                value=failure_report,
                detail="ไม่เพิ่ม Web failure counter และไม่ใช้เป็นหลักฐานว่าเครื่อง offline",
                status="warning",
                at=now,
            )
            self.repository.update_runtime(
                device.slot,
                status=status,
                checked_at=now.isoformat(timespec="seconds"),
                error=failure_report,
            )
            return False
        except Exception as exc:
            web_decision = self.machine.web_failure(state, now)
            from services.support_diagnostics import diagnostic_report
            message = diagnostic_report(exc, stage='WEB / Meter', target=device.host, device=device.name)
            if snmp_error:
                message += '\n\n' + snmp_error
            error_state = self.cache.record_error(device.slot, now.date(), message, at=now)
            pipeline_log.append(
                stage="WEB",
                action="Web Connection failed",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                target=f"https://{device.host}/wcd",
                value=message,
                detail=f"{web_decision.reason} · error_count={error_state.get('error_count', 0)}",
                status="error",
                at=now,
            )
            self.repository.update_runtime(
                device.slot,
                status=web_decision.status,
                checked_at=now.isoformat(timespec="seconds"),
                error=message,
            )
            return False
