from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from .km_counter_profile import KM_COUNTER_DEFINITIONS
from .models import ConnectionSettings, RawOidValue, ScanMode

DEFAULT_ROOTS = (
    "1.3.6.1.2.1.1",  # SNMPv2-MIB system
    "1.3.6.1.2.1.25.3",  # HOST-RESOURCES device
    "1.3.6.1.2.1.43",  # Printer-MIB
    "1.3.6.1.4.1.2590",  # Minolta legacy enterprise
    "1.3.6.1.4.1.9514",  # Konica legacy enterprise
    "1.3.6.1.4.1.18334",  # Konica Minolta Holdings enterprise
    "1.3.6.1.4.1.50919",  # Konica Minolta, Inc. enterprise
)
DEEP_ROOTS = (
    "1.3.6.1",  # Full tree first
    "1.3.6.1.2.1.1",  # Recovery after agents stop between MIB-2 groups
    "1.3.6.1.2.1.2",
    "1.3.6.1.2.1.4",
    "1.3.6.1.2.1.7",
    "1.3.6.1.2.1.11",
    "1.3.6.1.2.1.25",
    "1.3.6.1.2.1.43",  # Segmented recovery: Printer-MIB
    "1.3.6.1.4.1.2590",  # Segmented recovery: legacy Minolta
    "1.3.6.1.4.1.9514",  # Segmented recovery: legacy Konica
    "1.3.6.1.4.1.18334",  # Segmented recovery: KM Holdings
    "1.3.6.1.4.1.18334.1.1.1.1",  # Some bizhub agents time out before later private branches
    "1.3.6.1.4.1.18334.1.1.1.3",
    "1.3.6.1.4.1.18334.1.1.1.5",  # Large meter/counter branch
    "1.3.6.1.4.1.50919",  # Segmented recovery: current KM
)
DEEP_MAX_ROWS = 50_000


@dataclass(frozen=True)
class ScanProgress:
    mode: ScanMode
    root: str
    roots_completed: int
    roots_total: int
    oids_collected: int


ProgressCallback = Callable[[ScanProgress], None]


class SnmpCollectionError(RuntimeError):
    """Raised when a device cannot be queried reliably."""


class SnmpScanCancelled(SnmpCollectionError):
    """Raised when the user stops an in-progress scan."""


class SnmpCollector(Protocol):
    async def collect(self, settings: ConnectionSettings) -> tuple[list[RawOidValue], list[str]]: ...


def _numeric_value(value: object) -> int | float | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        try:
            return float(str(value))
        except (TypeError, ValueError, OverflowError):
            return None


class PySnmpCollector:
    def __init__(
        self,
        roots: tuple[str, ...] | None = None,
        *,
        scan_mode: ScanMode = ScanMode.QUICK,
        progress_callback: ProgressCallback | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.scan_mode = scan_mode
        self.roots = roots or (DEEP_ROOTS if scan_mode == ScanMode.DEEP else DEFAULT_ROOTS)
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event

    async def collect(self, settings: ConnectionSettings) -> tuple[list[RawOidValue], list[str]]:
        try:
            from pysnmp.hlapi.v3arch.asyncio import (
                CommunityData,
                ContextData,
                ObjectIdentity,
                ObjectType,
                SnmpEngine,
                UdpTransportTarget,
                UsmUserData,
                bulk_walk_cmd,
                get_cmd,
                usmAesCfb128Protocol,
                usmHMACSHAAuthProtocol,
                walk_cmd,
            )
        except ImportError as err:
            raise SnmpCollectionError("ไม่พบ pysnmp กรุณาติดตั้งด้วย: pip install -e .") from err

        engine = SnmpEngine()
        if settings.version == "3":
            if settings.v3_security_level == "noAuthNoPriv":
                auth = UsmUserData(settings.v3_username)
            elif settings.v3_security_level == "authNoPriv":
                auth = UsmUserData(
                    settings.v3_username,
                    authKey=settings.v3_auth_password,
                    authProtocol=usmHMACSHAAuthProtocol,
                )
            else:
                auth = UsmUserData(
                    settings.v3_username,
                    authKey=settings.v3_auth_password,
                    privKey=settings.v3_priv_password,
                    authProtocol=usmHMACSHAAuthProtocol,
                    privProtocol=usmAesCfb128Protocol,
                )
        else:
            auth = CommunityData(settings.community, mpModel=0 if settings.version == "1" else 1)
        target = await UdpTransportTarget.create(
            (settings.host, settings.port),
            timeout=settings.timeout,
            retries=settings.retries,
        )
        collected: dict[str, RawOidValue] = {}
        warnings: list[str] = []

        try:
            for root_index, root in enumerate(self.roots):
                if self.cancel_event and self.cancel_event.is_set():
                    raise SnmpScanCancelled("ยกเลิกการ Scan แล้ว")
                common_options = {
                    "lexicographicMode": False,
                    "lookupMib": False,
                    "maxRows": DEEP_MAX_ROWS if self.scan_mode == ScanMode.DEEP else settings.max_rows_per_root,
                }
                context = ContextData(contextName=settings.v3_context)
                target_object = ObjectType(ObjectIdentity(root))
                if settings.version == "1":
                    iterator = walk_cmd(engine, auth, target, context, target_object, **common_options)
                else:
                    iterator = bulk_walk_cmd(
                        engine,
                        auth,
                        target,
                        context,
                        0,
                        25,
                        target_object,
                        **common_options,
                    )
                async for error_indication, error_status, error_index, var_binds in iterator:
                    if self.cancel_event and self.cancel_event.is_set():
                        raise SnmpScanCancelled("ยกเลิกการ Scan แล้ว")
                    if error_indication:
                        warnings.append(f"{root}: {error_indication}")
                        break
                    if error_status:
                        position = int(error_index) if error_index else 0
                        warnings.append(f"{root}: {error_status.prettyPrint()} at index {position}")
                        break
                    for name, value in var_binds:
                        oid = name.prettyPrint().lstrip(".")
                        collected[oid] = RawOidValue(
                            oid=oid,
                            value=value.prettyPrint(),
                            data_type=value.__class__.__name__,
                            numeric_value=_numeric_value(value),
                        )
                    if self.progress_callback and len(collected) % 100 == 0:
                        self.progress_callback(
                            ScanProgress(
                                mode=self.scan_mode,
                                root=root,
                                roots_completed=root_index,
                                roots_total=len(self.roots),
                                oids_collected=len(collected),
                            )
                        )
                if self.progress_callback:
                    self.progress_callback(
                        ScanProgress(
                            mode=self.scan_mode,
                            root=root,
                            roots_completed=root_index + 1,
                            roots_total=len(self.roots),
                            oids_collected=len(collected),
                        )
                    )
                if self.scan_mode == ScanMode.DEEP and len(collected) >= DEEP_MAX_ROWS:
                    warnings.append(f"Deep Scan ถึงขีดจำกัด {DEEP_MAX_ROWS:,} OIDs")
                    break

            targeted_found = 0
            context = ContextData(contextName=settings.v3_context)
            for definition in KM_COUNTER_DEFINITIONS:
                if definition.oid in collected:
                    targeted_found += 1
                    continue
                if self.cancel_event and self.cancel_event.is_set():
                    raise SnmpScanCancelled("ยกเลิกการ Scan แล้ว")
                error_indication, error_status, _error_index, var_binds = await get_cmd(
                    engine,
                    auth,
                    target,
                    context,
                    ObjectType(ObjectIdentity(definition.oid)),
                    lookupMib=False,
                )
                if error_indication or error_status:
                    continue
                for name, value in var_binds:
                    if value.__class__.__name__ in {"NoSuchObject", "NoSuchInstance", "EndOfMibView"}:
                        continue
                    oid = name.prettyPrint().lstrip(".")
                    collected[oid] = RawOidValue(
                        oid=oid,
                        value=value.prettyPrint(),
                        data_type=value.__class__.__name__,
                        numeric_value=_numeric_value(value),
                    )
                    targeted_found += 1
            warnings.append(f"Targeted KM counter probes พบ {targeted_found}/{len(KM_COUNTER_DEFINITIONS)} ค่า")
        except SnmpScanCancelled:
            raise
        except Exception as err:
            raise SnmpCollectionError(f"อ่าน SNMP จาก {settings.host} ไม่สำเร็จ: {err}") from err
        finally:
            engine.close_dispatcher()

        if not collected:
            details = "; ".join(warnings) if warnings else "ไม่มี response"
            raise SnmpCollectionError(
                f"ไม่พบข้อมูล SNMP จาก {settings.host} ({details}) ตรวจ IP, community, SNMP version และ firewall"
            )
        return sorted(collected.values(), key=lambda item: tuple(int(part) for part in item.oid.split("."))), warnings
