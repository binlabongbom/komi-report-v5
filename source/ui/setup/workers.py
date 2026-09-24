"""Workers UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, replace
from threading import Event

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from komi_snmp_profiler.connectors import (
    AuthenticatedWebConnectionCounterConnector,
    LegacyAuthenticatedWebConnectionCounterConnector,
    LegacyWebConnectionCounterConnector,
    TlsPolicy,
    WebConnectionAuthenticationError,
    WebConnectionCertificateError,
    WebConnectionCounterConnector,
    WebConnectionSessionBusyError,
    server_certificate_fingerprint,
)
from komi_snmp_profiler.credential_store import PUBLIC_FACTORY_ADMIN_PASSWORDS, AdminCredential, SessionCredentialStore
from komi_snmp_profiler.device_profiles import resolve_device_meter_profile
from komi_snmp_profiler.meter import MeterReader
from services.device_config import DeviceConfig
from services.pipeline_log import pipeline_log
from services.secondary_setup import SecondaryPeerCandidate, SecondaryPeerClient
from services.setup_connectivity import SetupConnectivityReport, check_setup_connectivity
from services.snmp_probe import SnmpTotalProbe


@dataclass(frozen=True)
class DeviceTestResult:
    """One immutable device-test result bound to a scan endpoint and test run."""

    generation: int
    host: str
    slot: int
    payload: dict


class DeviceTestWorker(QObject):
    result = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(
        self,
        devices: list[DeviceConfig],
        *,
        snmp_port: int = 161,
        web_port: int = 443,
        endpoint_ports: dict[str, tuple[int, int]] | None = None,
        generation: int = 0,
    ) -> None:
        super().__init__()
        self.devices = devices
        self.snmp_port = snmp_port
        self.web_port = web_port
        self.endpoint_ports = endpoint_ports or {}
        self.generation = generation

    def _test(self, device: DeviceConfig) -> dict:
        snmp_port, web_port = self.endpoint_ports.get(
            device.host, (self.snmp_port, self.web_port)
        )
        probe_result = None
        reading = None
        errors: list[str] = []
        tls_mode = device.tls_mode
        tls_fingerprint = device.tls_fingerprint
        credential_required = False
        session_busy = False
        credential_default_index: int | None = None
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
            from services.support_diagnostics import diagnostic_report
            errors.append(diagnostic_report(exc, stage='SNMP / Setup', target=f'{device.host}:{snmp_port}', device=device.name))
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
                effective_policy = replace(
                    policy,
                    compatibility=profile.tls_compatibility,
                )
                reader = MeterReader(
                    store,
                    public_connector=WebConnectionCounterConnector(
                        tls_policy=effective_policy,
                        scheme=profile.web_scheme,
                    ),
                    admin_connector=AuthenticatedWebConnectionCounterConnector(
                        tls_policy=effective_policy,
                        scheme=profile.web_scheme,
                    ),
                    legacy_public_connector=LegacyWebConnectionCounterConnector(
                        tls_policy=effective_policy,
                        scheme=profile.web_scheme,
                    ),
                    legacy_admin_connector=LegacyAuthenticatedWebConnectionCounterConnector(
                        tls_policy=effective_policy,
                        scheme=profile.web_scheme,
                    ),
                    allow_implicit_name_export=True,
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
        except WebConnectionAuthenticationError as exc:
            credential_required = True
            from services.support_diagnostics import diagnostic_report
            errors.append(diagnostic_report(exc, stage='WEB / Setup', target=web_host, device=device.name))
            pipeline_log.append(
                stage="WEB",
                action="Setup Web credential required",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                value=exc,
                status="warning",
            )
        except WebConnectionSessionBusyError as exc:
            session_busy = True
            from services.support_diagnostics import diagnostic_report
            errors.append(diagnostic_report(exc, stage='WEB / Setup', target=web_host, device=device.name))
            pipeline_log.append(
                stage="WEB",
                action="Setup Web Connection session busy",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                value=exc,
                status="warning",
            )
        except Exception as exc:
            from services.support_diagnostics import diagnostic_report
            errors.append(diagnostic_report(exc, stage='WEB / Setup', target=device.host, device=device.name))
            pipeline_log.append(
                stage="WEB",
                action="Setup Web read failed",
                device_slot=device.slot,
                device_name=device.name,
                host=device.host,
                value=exc,
                status="error",
            )
        if reading is not None and not device.password:
            used_credential = store.load(web_host)
            if used_credential is not None:
                try:
                    credential_default_index = PUBLIC_FACTORY_ADMIN_PASSWORDS.index(
                        used_credential.password
                    )
                except ValueError:
                    credential_default_index = None
        return {
            "online": probe_result is not None or reading is not None,
            "model": probe_result.model if probe_result else "",
            "serial": probe_result.serial if probe_result else "",
            "total": probe_result.total if probe_result else None,
            "web_ok": reading is not None,
            "error": "\n\n".join(errors),
            "tls_mode": tls_mode,
            "tls_fingerprint": tls_fingerprint,
            "web_auth_state": reading.auth_state.value if reading is not None else "",
            "credential_required": credential_required,
            "session_busy": session_busy,
            "credential_default_index": credential_default_index,
        }

    @pyqtSlot()
    def run(self) -> None:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(self._test, device): device for device in self.devices}
            for future, device in list(futures.items()):
                try:
                    payload = future.result()
                except Exception as exc:
                    payload = {"online": False, "model": "", "serial": "", "total": None, "web_ok": False, "error": str(exc)}
                self.result.emit(
                    DeviceTestResult(
                        generation=self.generation,
                        host=device.host,
                        slot=device.slot,
                        payload=payload,
                    )
                )
        self.finished.emit()


class NetworkDiscoveryWorker(QObject):
    """Find Konica Minolta devices on the active /24 without blocking the wizard."""

    result = pyqtSignal(object)
    progress = pyqtSignal(str)
    progress_count = pyqtSignal(int, int)
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
            total_hosts = len(hosts)
            completed_hosts = 0
            self.progress_count.emit(completed_hosts, total_hosts)
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
                    completed_hosts += 1
                    self.progress_count.emit(completed_hosts, total_hosts)
                    if not self._is_cancelled():
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


class SecondaryPeerDiscoveryWorker(QObject):
    """Discover configured KOMI Primary Desktops without blocking first run."""

    finished = pyqtSignal(object, str)

    def __init__(self, hosts: list[str] | None = None, *, port: int = 3000) -> None:
        super().__init__()
        self.hosts = hosts
        self.port = port

    @pyqtSlot()
    def run(self) -> None:
        try:
            client = SecondaryPeerClient(port=self.port)
            candidates = client.discover(list(self.hosts)) if self.hosts is not None else client.discover_lan()
            self.finished.emit(candidates, "")
        except Exception as exc:
            self.finished.emit([], str(exc))


class SetupConnectivityWorker(QObject):
    """Run first-page Host checks without blocking the Wizard UI."""

    finished = pyqtSignal(object, str)

    def __init__(self, probe: Callable[[], SetupConnectivityReport] | None = None) -> None:
        super().__init__()
        self.probe = probe or check_setup_connectivity

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self.probe(), "")
        except Exception as exc:
            # Keep diagnostics free of arbitrary exception text, which could
            # contain a proxy URL or another environment-specific secret.
            self.finished.emit(None, type(exc).__name__)


class SecondarySnapshotWorker(QObject):
    """Fetch the allow-listed setup snapshot after the user confirms Sync."""

    finished = pyqtSignal(object, str)

    def __init__(self, candidate: SecondaryPeerCandidate) -> None:
        super().__init__()
        self.candidate = candidate
        self.cancelled = Event()

    @pyqtSlot()
    def run(self) -> None:
        try:
            preview = SecondaryPeerClient().prepare_enrollment(self.candidate, cancelled=self.cancelled.is_set)
            self.finished.emit(preview, "")
        except Exception as exc:
            self.finished.emit({}, str(exc))


class EnrollmentCommitWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, preview, settings, repository, devices):
        super().__init__()
        self.preview, self.settings = preview, settings
        self.repository, self.devices = repository, devices

    @pyqtSlot()
    def run(self):
        try:
            self.preview.commit(local_settings=self.settings, repository=self.repository, devices=self.devices)
            self.finished.emit('')
        except Exception as error:
            self.finished.emit(str(error))
