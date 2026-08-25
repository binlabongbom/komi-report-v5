from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal

from config import DEFAULT_SNMP_COMMUNITY
from komi_snmp_profiler.device_profiles import SnmpWalkPolicy, resolve_device_meter_profile
from komi_snmp_profiler.km_counter_profile import KM_COUNTER_DEFINITIONS


class SnmpProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperTrayStatus:
    """Raw, read-only paper state reported by one Printer-MIB input tray."""

    name: str
    level: int | None
    capacity: int | None
    status: int | None
    input_index: int | None = None

    def to_cache(self) -> dict[str, int | str | None]:
        result: dict[str, int | str | None] = {
            "name": self.name,
            "level": self.level,
            "capacity": self.capacity,
            "status": self.status,
        }
        if self.input_index is not None:
            result["input_index"] = self.input_index
        return result


@dataclass(frozen=True)
class PaperAvailability:
    """Conservative display state; only ``empty`` is an explicit paper-out claim."""

    state: Literal["empty", "attention", "available", "unknown"]
    trays: tuple[str, ...] = ()


@dataclass(frozen=True)
class SnmpProbeResult:
    total: int
    model: str = ""
    serial: str = ""
    oid_values: tuple[tuple[str, str], ...] = ()
    total_oid: str = ""
    total_candidates: tuple[tuple[str, int], ...] = ()
    toner: tuple[tuple[str, int], ...] = ()
    paper_trays: tuple[PaperTrayStatus, ...] = ()
    paper_alerts: tuple[str, ...] = ()


class SnmpTotalProbe:
    """Small Printer-MIB probe used by the five-minute background heartbeat."""

    MARKER_LIFE_ROOT = "1.3.6.1.2.1.43.10.2.1.4"
    MODEL_ROOT = "1.3.6.1.2.1.25.3.2.1.3"
    SERIAL_ROOT = "1.3.6.1.2.1.43.5.1.1.17"
    SUPPLY_DESCRIPTION_ROOT = "1.3.6.1.2.1.43.11.1.1.6"
    SUPPLY_CAPACITY_ROOT = "1.3.6.1.2.1.43.11.1.1.8"
    SUPPLY_LEVEL_ROOT = "1.3.6.1.2.1.43.11.1.1.9"
    INPUT_CAPACITY_ROOT = "1.3.6.1.2.1.43.8.2.1.9"
    INPUT_LEVEL_ROOT = "1.3.6.1.2.1.43.8.2.1.10"
    INPUT_STATUS_ROOT = "1.3.6.1.2.1.43.8.2.1.11"
    INPUT_NAME_ROOT = "1.3.6.1.2.1.43.8.2.1.13"
    ALERT_DESCRIPTION_ROOT = "1.3.6.1.2.1.43.18.1.1.8"
    PRIMARY_TOTAL_OID = f"{MARKER_LIFE_ROOT}.1.1"
    MODEL_OID = f"{MODEL_ROOT}.1"
    SERIAL_OID = f"{SERIAL_ROOT}.1"
    PRIVATE_TOTAL_OIDS = tuple(
        definition.oid for definition in KM_COUNTER_DEFINITIONS if definition.canonical_field == "counter.total"
    )

    def __init__(
        self,
        *,
        community: str = DEFAULT_SNMP_COMMUNITY,
        timeout: float = 2.0,
        retries: int = 1,
        port: int = 161,
    ) -> None:
        self.community = community
        self.timeout = timeout
        self.retries = retries
        self.port = port

    @classmethod
    def select_total(cls, totals: list[tuple[str, int]], preferred_oid: str = "") -> tuple[str, int]:
        """Use a Web-calibrated OID first, then model-neutral fallbacks."""
        if not totals:
            raise SnmpProbeError("ไม่พบ Printer-MIB Total Meter")
        if preferred_oid:
            preferred = next(((oid, value) for oid, value in totals if oid == preferred_oid), None)
            if preferred is not None:
                return preferred
        return next(
            ((oid, value) for oid, value in totals if oid == cls.PRIMARY_TOTAL_OID),
            max(totals, key=lambda item: item[1]),
        )

    @classmethod
    def select_total_for_model(
        cls,
        totals: list[tuple[str, int]],
        model: str,
        preferred_oid: str = "",
    ) -> tuple[str, int]:
        profile = resolve_device_meter_profile(model)
        return cls.select_total(totals, preferred_oid or profile.preferred_total_oid)

    @classmethod
    def required_exact_oids(cls) -> tuple[str, ...]:
        """Core heartbeat OIDs; a working Total never depends on SNMP walk support."""
        return (cls.PRIMARY_TOTAL_OID, *cls.PRIVATE_TOTAL_OIDS, cls.MODEL_OID, cls.SERIAL_OID)

    @classmethod
    def parse_toner_levels(
        cls,
        descriptions: list[tuple[str, str]],
        capacities: list[tuple[str, str]],
        levels: list[tuple[str, str]],
    ) -> dict[str, int]:
        """Join Printer-MIB supply rows and return available C/Y/M/K percentages."""

        def by_suffix(values: list[tuple[str, str]], root: str) -> dict[str, str]:
            prefix = f"{root}."
            return {oid[len(prefix) :]: value for oid, value in values if oid.startswith(prefix)}

        description_by_row = by_suffix(descriptions, cls.SUPPLY_DESCRIPTION_ROOT)
        capacity_by_row = by_suffix(capacities, cls.SUPPLY_CAPACITY_ROOT)
        level_by_row = by_suffix(levels, cls.SUPPLY_LEVEL_ROOT)
        color_tokens = (("cyan", "C"), ("yellow", "Y"), ("magenta", "M"), ("black", "K"))
        result: dict[str, int] = {}
        for row, description in description_by_row.items():
            normalized = description.casefold()
            if "toner" not in normalized:
                continue
            color = next((code for token, code in color_tokens if token in normalized), "")
            if not color:
                continue
            try:
                level = int(level_by_row[row])
                capacity = int(capacity_by_row[row])
            except (KeyError, TypeError, ValueError):
                continue
            if level < 0 or capacity <= 0:
                continue
            result[color] = max(0, min(100, round(level * 100 / capacity)))
        return result

    @staticmethod
    def _oid_rows(values: list[tuple[str, str]], root: str) -> dict[str, str]:
        prefix = f"{root}."
        return {oid[len(prefix) :]: value for oid, value in values if oid.startswith(prefix)}

    @staticmethod
    def _integer(value: object) -> int | None:
        match = re.match(r"^-?\d+", str(value).strip())
        return int(match.group()) if match else None

    @classmethod
    def parse_paper_trays(
        cls,
        names: list[tuple[str, str]],
        capacities: list[tuple[str, str]],
        levels: list[tuple[str, str]],
        statuses: list[tuple[str, str]],
    ) -> tuple[PaperTrayStatus, ...]:
        """Join Printer-MIB input rows without treating an unknown value as empty."""
        names_by_row = cls._oid_rows(names, cls.INPUT_NAME_ROOT)
        capacities_by_row = cls._oid_rows(capacities, cls.INPUT_CAPACITY_ROOT)
        levels_by_row = cls._oid_rows(levels, cls.INPUT_LEVEL_ROOT)
        statuses_by_row = cls._oid_rows(statuses, cls.INPUT_STATUS_ROOT)
        rows = sorted(set(names_by_row) | set(capacities_by_row) | set(levels_by_row) | set(statuses_by_row))
        trays: list[PaperTrayStatus] = []
        for row in rows:
            label = names_by_row.get(row, "").strip() or f"Tray {row.rsplit('.', 1)[-1]}"
            trays.append(
                PaperTrayStatus(
                    name=label,
                    level=cls._integer(levels_by_row.get(row)),
                    capacity=cls._integer(capacities_by_row.get(row)),
                    status=cls._integer(statuses_by_row.get(row)),
                    input_index=cls._integer(row.rsplit(".", 1)[-1]),
                )
            )
        return tuple(trays)

    @staticmethod
    def summarize_paper(
        trays: tuple[PaperTrayStatus, ...], alerts: tuple[str, ...] = ()
    ) -> PaperAvailability:
        """Return a fail-safe state for the card without guessing device-specific alerts."""
        explicit_alerts = tuple(
            alert
            for alert in alerts
            if any(token in alert.casefold() for token in ("paper empty", "out of paper", "no paper", "paper out", "tray empty"))
        )
        empty = tuple(
            tray.name
            for tray in trays
            if tray.level == 0 and (tray.capacity is None or tray.capacity > 0)
        )
        if explicit_alerts or empty:
            return PaperAvailability("empty", empty)
        unavailable = tuple(tray.name for tray in trays if tray.status == 6)
        if unavailable:
            return PaperAvailability("attention", unavailable)
        available = any(
            tray.level is not None and (tray.level > 0 or tray.level == -3)
            or tray.status in {3, 4, 5}
            for tray in trays
        )
        return PaperAvailability("available" if available else "unknown")

    def read(self, host: str, *, preferred_oid: str = "") -> SnmpProbeResult:
        try:
            return asyncio.run(self._read(host, preferred_oid=preferred_oid))
        except SnmpProbeError:
            raise
        except Exception as exc:
            raise SnmpProbeError(f"SNMP probe ไม่สำเร็จ: {exc}") from exc

    async def _read(self, host: str, *, preferred_oid: str = "") -> SnmpProbeResult:
        try:
            from pysnmp.hlapi.v3arch.asyncio import (
                CommunityData,
                ContextData,
                ObjectIdentity,
                ObjectType,
                SnmpEngine,
                UdpTransportTarget,
                bulk_walk_cmd,
                get_cmd,
            )
        except ImportError as exc:
            raise SnmpProbeError("ไม่พบ pysnmp") from exc

        engine = SnmpEngine()
        auth = CommunityData(self.community, mpModel=1)
        target = await UdpTransportTarget.create((host, self.port), timeout=self.timeout, retries=self.retries)

        async def walk(root: str, max_rows: int = 32) -> list[tuple[str, str]]:
            values: list[tuple[str, str]] = []
            iterator = bulk_walk_cmd(
                engine,
                auth,
                target,
                ContextData(),
                0,
                10,
                ObjectType(ObjectIdentity(root)),
                lexicographicMode=False,
                lookupMib=False,
                maxRows=max_rows,
            )
            async for error_indication, error_status, _error_index, var_binds in iterator:
                if error_indication:
                    raise SnmpProbeError(str(error_indication))
                if error_status:
                    raise SnmpProbeError(error_status.prettyPrint())
                for name, value in var_binds:
                    if value.__class__.__name__ not in {"NoSuchObject", "NoSuchInstance", "EndOfMibView"}:
                        values.append((name.prettyPrint().lstrip("."), value.prettyPrint()))
            return values

        async def get_exact(oid: str) -> list[tuple[str, str]]:
            error_indication, error_status, _error_index, var_binds = await get_cmd(
                engine,
                auth,
                target,
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lookupMib=False,
            )
            if error_indication or error_status:
                return []
            return [
                (name.prettyPrint().lstrip("."), value.prettyPrint())
                for name, value in var_binds
                if value.__class__.__name__ not in {"NoSuchObject", "NoSuchInstance", "EndOfMibView"}
            ]

        try:
            exact_values: list[tuple[str, str]] = []
            for oid in self.required_exact_oids():
                exact_values.extend(await get_exact(oid))
            total_oid_set = {self.PRIMARY_TOTAL_OID, *self.PRIVATE_TOTAL_OIDS}
            raw_totals = [(oid, value) for oid, value in exact_values if oid in total_oid_set]
            if not raw_totals:
                try:
                    raw_totals = await walk(self.MARKER_LIFE_ROOT)
                except SnmpProbeError:
                    raw_totals = []
            models = [(oid, value) for oid, value in exact_values if oid == self.MODEL_OID]
            serials = [(oid, value) for oid, value in exact_values if oid == self.SERIAL_OID]
            if not models:
                try:
                    models = await walk(self.MODEL_ROOT, 16)
                except SnmpProbeError:
                    models = []
            if not serials:
                try:
                    serials = await walk(self.SERIAL_ROOT, 16)
                except SnmpProbeError:
                    serials = []
            totals = [
                (oid, int(value))
                for oid, value in raw_totals
                if str(value).lstrip("-").isdigit() and int(value) >= 0
            ]
            model = next((value.strip() for _oid, value in models if value.strip()), "")
            serial = next((value.strip() for _oid, value in serials if value.strip()), "")
            profile = resolve_device_meter_profile(model)
            selected_oid, selected_total = self.select_total_for_model(totals, model, preferred_oid)
            supply_descriptions: list[tuple[str, str]] = []
            supply_capacities: list[tuple[str, str]] = []
            supply_levels: list[tuple[str, str]] = []
            input_names: list[tuple[str, str]] = []
            input_capacities: list[tuple[str, str]] = []
            input_levels: list[tuple[str, str]] = []
            input_statuses: list[tuple[str, str]] = []
            paper_alerts: list[tuple[str, str]] = []
            if profile.snmp_walk_policy == SnmpWalkPolicy.SUPPLEMENTAL:
                try:
                    supply_descriptions = await walk(self.SUPPLY_DESCRIPTION_ROOT, 64)
                    supply_capacities = await walk(self.SUPPLY_CAPACITY_ROOT, 64)
                    supply_levels = await walk(self.SUPPLY_LEVEL_ROOT, 64)
                except SnmpProbeError:
                    # Toner is supplementary status; a device without this table
                    # must not turn an otherwise valid heartbeat into offline.
                    pass
                try:
                    input_names = await walk(self.INPUT_NAME_ROOT, 32)
                    input_capacities = await walk(self.INPUT_CAPACITY_ROOT, 32)
                    input_levels = await walk(self.INPUT_LEVEL_ROOT, 32)
                    input_statuses = await walk(self.INPUT_STATUS_ROOT, 32)
                    paper_alerts = await walk(self.ALERT_DESCRIPTION_ROOT, 32)
                except SnmpProbeError:
                    # Input tray telemetry is optional and must not make the
                    # total-meter heartbeat fail on older models.
                    pass
            toner = self.parse_toner_levels(supply_descriptions, supply_capacities, supply_levels)
            paper_trays = self.parse_paper_trays(input_names, input_capacities, input_levels, input_statuses)
            return SnmpProbeResult(
                total=selected_total,
                model=model,
                serial=serial,
                oid_values=tuple(
                    raw_totals
                    + models
                    + serials
                    + supply_descriptions
                    + supply_capacities
                    + supply_levels
                    + input_names
                    + input_capacities
                    + input_levels
                    + input_statuses
                    + paper_alerts
                ),
                total_oid=selected_oid,
                total_candidates=tuple(totals),
                toner=tuple((color, toner[color]) for color in ("C", "Y", "M", "K") if color in toner),
                paper_trays=paper_trays,
                paper_alerts=tuple(value.strip() for _oid, value in paper_alerts if value.strip()),
            )
        finally:
            engine.close_dispatcher()
