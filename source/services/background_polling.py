from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from database import get_cfg, set_cfg
from komi_snmp_profiler.meter import MeterReader
from services.daily_cache import DailyCacheStore
from services.device_config import DatabaseCredentialStore, DeviceConfig, DeviceConfigRepository
from services.live_meter_service import meter_reading_to_report
from services.pipeline_log import pipeline_log
from services.polling import DevicePollState, PollingPolicy, PollingStateMachine
from services.reconciliation import reconcile_web_counters
from services.runtime_snapshots import runtime_snapshots
from services.snmp_probe import SnmpTotalProbe
from services.subject_history import SubjectDailyCacheStore
from services.sync_schedule import load_schedule_windows

log = logging.getLogger(__name__)


class BackgroundPollingCoordinator(QObject):
    device_updated = pyqtSignal(int)
    reading_saved = pyqtSignal(int)

    def __init__(
        self,
        repository: DeviceConfigRepository | None = None,
        *,
        probe: SnmpTotalProbe | None = None,
        reader: MeterReader | None = None,
        cache: DailyCacheStore | None = None,
        subject_cache: SubjectDailyCacheStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository or DeviceConfigRepository()
        self.probe = probe or SnmpTotalProbe()
        self.reader = reader or MeterReader(DatabaseCredentialStore(self.repository))
        self.cache = cache or DailyCacheStore()
        self.subject_cache = subject_cache or SubjectDailyCacheStore()
        self.machine = PollingStateMachine()
        self.snmp_interval = timedelta(minutes=5)
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="komi-meter")
        self.states: dict[int, DevicePollState] = {}
        self.last_poll: dict[int, datetime] = {}
        self.active: set[int] = set()
        self._futures: dict[int, Future] = {}
        self._started_at: dict[int, float] = {}
        self._lock = threading.RLock()
        self._rollover_lock = threading.RLock()
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.tick)

    def start(self) -> None:
        self.reload_policy()
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
        for device in self.repository.list(enabled_only=True):
            self.states[device.slot] = DevicePollState(last_snmp_total=device.last_total)
        self.timer.start()
        QTimer.singleShot(250, self.tick)

    def stop(self) -> int:
        """Stop scheduling new work and cancel queued polls where possible.

        A running device read is allowed to finish its transaction/cache write;
        returning the remaining count makes shutdown state observable without
        blocking Qt's UI event loop.
        """
        self.timer.stop()
        with self._lock:
            remaining = sum(not future.done() for future in self._futures.values())
            for future in self._futures.values():
                future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        log.info(
            "background polling stopped",
            extra={"event": "polling_stopped", "operation": "shutdown", "remaining_polls": remaining},
        )
        return remaining

    def tick(self) -> None:
        now = datetime.now().astimezone()
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
                if device.slot in self.active:
                    return
                self.active.add(device.slot)
                self.last_poll[device.slot] = datetime.now().astimezone()
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

    def _finished(self, slot: int, future: Future) -> None:
        with self._lock:
            self.active.discard(slot)
            self._futures.pop(slot, None)
            started = self._started_at.pop(slot, None)
        try:
            saved = bool(future.result())
        except Exception:
            log.exception("background device poll failed: slot=%s", slot)
            saved = False
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
        if saved:
            self.reading_saved.emit(slot)

    def _poll_device(self, device: DeviceConfig, force_web: bool) -> bool:
        now = datetime.now().astimezone()
        state = self.states.setdefault(device.slot, DevicePollState(last_snmp_total=device.last_total))
        snmp_error = ""
        probe_result = None
        preferred_oid = self._preferred_total_oid(device)
        calibration_needed = not preferred_oid
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
            snmp_error = str(exc)
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
            reading = self.reader.read(device.host)
            reconciliation = reconcile_web_counters(
                {
                    counter.canonical_field: counter.count
                    for counter in reading.counters
                    if counter.subject_type is None
                }
            )
            if reconciliation.needs_review:
                for issue in reconciliation.issues:
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
                            + f" · profile={reconciliation.profile_id}"
                        ),
                        status="warning",
                        at=now,
                    )
            elif reconciliation.checked_count:
                pipeline_log.append(
                    stage="WEB",
                    action="Reconciliation passed",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target="Web Connection Device Meter",
                    value=f"ตรวจ {reconciliation.checked_count} จุด · ผลรวมตรงกัน",
                    status="ok",
                    at=now,
                )
            ram_snapshot = runtime_snapshots.update(device.slot, reading)
            subject_state = self.subject_cache.update_reading(device.slot, reading, at=now)
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
                    f"subject daily cache={len(subject_state.get('subjects', {}))}"
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
            cache_state = self.cache.update_reading(
                device.slot,
                reading,
                at=now,
                reconciliation=reconciliation,
            )
            if not reconciliation.billing_safe:
                pipeline_log.append(
                    stage="POLICY",
                    action="Billing evidence held for review",
                    device_slot=device.slot,
                    device_name=device.name,
                    host=device.host,
                    target="Daily Cache reconciliation",
                    value=(
                        f"issues={len(reconciliation.issues)} · "
                        f"checked={reconciliation.checked_count}"
                    ),
                    detail=f"profile={reconciliation.profile_id} · billing_safe=false",
                    status="warning",
                    at=now,
                )
            for key, value in sorted(cache_state.get("latest", {}).items()):
                pipeline_log.append(
                    stage="RAM",
                    action="Normalized counter cached",
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
            self.machine.web_success(state, now)
            self.repository.update_runtime(
                device.slot,
                status="online",
                checked_at=now.isoformat(timespec="seconds"),
                success_at=now.isoformat(timespec="seconds"),
                total=state.last_snmp_total,
            )
            return True
        except Exception as exc:
            web_decision = self.machine.web_failure(state, now)
            message = f"SNMP: {snmp_error}; Web: {exc}" if snmp_error else str(exc)
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
