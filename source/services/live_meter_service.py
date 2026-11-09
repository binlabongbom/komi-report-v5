from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from database import check_duplicate, save_reading
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.models import MeterReading, WebCounterValue
from komi_snmp_profiler.mono_950i import SCHEMA_VERSION as MONO_950I_SCHEMA_VERSION
from services.runtime_snapshots import RuntimeCounterRow
from services.subject_preview import build_subject_preview_rows


class MeterReaderLike(Protocol):
    def read(self, host: str) -> MeterReading: ...


@dataclass(frozen=True)
class LiveMeterPreview:
    reading: MeterReading
    parsed: dict


@dataclass(frozen=True)
class SavedLiveMeter:
    reading_id: int
    slot: int
    host: str


def _number(value: int | float | None) -> int:
    if value is None:
        return 0
    return max(0, int(round(value)))


def _counter_index(counters: tuple[WebCounterValue, ...]) -> dict[str, int]:
    return {
        item.canonical_field: _number(item.count)
        for item in counters
        if item.subject_type is None
    }


def _first(index: dict[str, int], *fields: str) -> int:
    for field in fields:
        if field in index:
            return index[field]
    return 0


def _color_total(index: dict[str, int], prefix: str) -> int:
    explicit = _first(index, f"{prefix}.color_total", f"{prefix}.full_color_total")
    single_two = _first(
        index,
        f"{prefix}.single_two_color_total",
        f"{prefix}.single_color_total",
        f"{prefix}.double_color_total",
    )
    return explicit + single_two


def _subject_accounts(counters: tuple[WebCounterValue, ...], *, legacy_size_breakdown: bool = True) -> list[dict]:
    accounts: list[dict] = []
    subjects = build_subject_preview_rows(tuple(RuntimeCounterRow.from_counter(item) for item in counters))
    for subject in subjects:
        subject_type, subject_id, name = subject.subject_type, subject.subject_id, subject.subject_name
        values = {item.canonical_field: _number(item.count) for item in subject.counters}
        prefix = f"counter.{subject_type}"
        total = _number(subject.total) if subject.total is not None else None
        size_available = total is not None and legacy_size_breakdown
        copy_color = _color_total(values, f"{prefix}.copy")
        print_color = _color_total(values, f"{prefix}.print")
        copy_bw = _first(values, f"{prefix}.copy.bw_total", f"{prefix}.copy.black_total")
        print_bw = _first(values, f"{prefix}.print.bw_total", f"{prefix}.print.black_total")
        accounts.append(
            {
                "name": name,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "total": total,
                "total_available": total is not None,
                "total_state": subject.total_state,
                # The legacy manual-save schema cannot represent an unknown
                # total safely. Preserve unknowns here and reject that save;
                # the raw-counter and live-preview paths remain available.
                "color_a4": copy_color + print_color if size_available else None,
                "bw_a4": copy_bw + print_bw if size_available else None,
                "color_a3": 0 if size_available else None,
                "bw_a3": 0 if size_available else None,
                "source_fields": sorted(values),
            }
        )
    return accounts


def meter_reading_to_report(reading: MeterReading, *, machine_name: str | None = None) -> dict:
    """Convert one verified live Meter reading into the V4-compatible report shape."""
    index = _counter_index(reading.counters)
    a4_full = _first(index, "counter.paper.full_color.a4")
    a4_single_two = _first(index, "counter.paper.single_two_color.a4")
    a3_full = _first(index, "counter.paper.full_color.a3")
    a3_single_two = _first(index, "counter.paper.single_two_color.a3")
    a4_color = a4_full + a4_single_two
    a3_color = a3_full + a3_single_two
    a4_bw = _first(index, "counter.paper.black.a4", "counter.paper.bw.a4")
    a3_bw = _first(index, "counter.paper.black.a3", "counter.paper.bw.a3")

    total_color = a4_color + a3_color
    total_bw = a4_bw + a3_bw
    total_counter = _first(index, "counter.total.total") or total_color + total_bw

    collected = datetime.fromisoformat(reading.collected_at.replace("Z", "+00:00"))
    read_date = collected.astimezone().strftime("%Y/%m/%d")

    copy_color = _color_total(index, "counter.copy")
    copy_bw = _first(index, "counter.copy.bw_total", "counter.copy.black_total")
    print_color = _color_total(index, "counter.print")
    print_bw = _first(index, "counter.print.bw_total", "counter.print.black_total")

    evidence = [
        {
            "canonical_field": item.canonical_field,
            "label": item.label,
            "count": item.count,
            "category": item.category,
            "source_path": item.source_path,
            "confidence": item.confidence.value,
            "subject_type": item.subject_type,
            "subject_id": item.subject_id,
            "subject_name": item.subject_name,
        }
        for item in reading.counters
    ]
    mono_profile = reading.schema_version == MONO_950I_SCHEMA_VERSION
    accounts = _subject_accounts(reading.counters, legacy_size_breakdown=not mono_profile)
    warnings = list(reading.warnings)
    if mono_profile and accounts:
        warnings.append(
            "950i: ยืนยัน Total ผู้ใช้จาก Black/BW แล้ว แต่ยังไม่มี A3/A4 รายผู้ใช้ที่ยืนยัน; "
            "ไม่บันทึกเป็นรายงานแยกขนาดแบบเดิมหรือแทนค่าที่ขาดด้วย 0"
        )
    if any(account["total"] is None for account in accounts):
        warnings.append(
            "พบข้อมูลผู้ใช้ แต่บางรายการไม่มี Total ที่ยืนยัน; คง Counter ต้นฉบับไว้ "
            "และยังบันทึกเป็นรายงานรวมแบบเดิมไม่ได้ ไม่แทนค่าที่ขาดด้วย 0"
        )

    return {
        "mode": "live_meter",
        "machine_name": machine_name or f"bizhub @ {reading.host}",
        "serial": reading.host,
        "date": read_date,
        "total_counter": total_counter,
        "summary": {
            "total_color": total_color,
            "total_bw": total_bw,
            "total": total_counter,
        },
        "paper_size": {
            "a3": a3_color + a3_bw,
            "a4": a4_color + a4_bw,
            "b4": 0,
            "b5": 0,
        },
        "paper_color": {
            "a4_color": a4_color,
            "a4_bw": a4_bw,
            "a3_color": a3_color,
            "a3_bw": a3_bw,
        },
        "detail": {
            "copy": {"total": copy_color + copy_bw, "color": copy_color, "bw": copy_bw},
            "print": {"total": print_color + print_bw, "color": print_color, "bw": print_bw},
        },
        "accounts": accounts or None,
        "meters": {},
        "warnings": warnings,
        "parser_name": "KOMI Live Meter",
        "source_metadata": {
            "schema_version": reading.schema_version,
            "source": reading.source,
            "auth_state": reading.auth_state.value,
            "host": reading.host,
            "collected_at": reading.collected_at,
            "confidence_policy": "source_preserved_no_oid_guessing",
        },
        "counter_evidence": evidence,
    }


class LiveMeterService:
    def __init__(self, reader: MeterReaderLike) -> None:
        self.reader = reader

    def read(
        self,
        host: str,
        *,
        machine_name: str | None = None,
        model: str = "",
    ) -> LiveMeterPreview:
        reading = (
            self.reader.read(host, model=model)
            if isinstance(self.reader, MeterReader)
            else self.reader.read(host)
        )
        return LiveMeterPreview(reading, meter_reading_to_report(reading, machine_name=machine_name))

    def save(self, slot: int, preview: LiveMeterPreview) -> SavedLiveMeter:
        if not 0 <= slot <= 2:
            raise ValueError("slot ต้องอยู่ระหว่าง 0–2")
        if preview.reading.schema_version == MONO_950I_SCHEMA_VERSION:
            raise ValueError(
                "ยังบันทึกรายงานแยกขนาดแบบเดิมไม่ได้: 950i ยืนยัน Total ผู้ใช้แล้ว "
                "แต่ยังไม่มี A3/A4 รายผู้ใช้ที่ยืนยัน; ไม่แทนค่าที่ขาดด้วย 0"
            )
        if any(account["total"] is None for account in _subject_accounts(preview.reading.counters)):
            raise ValueError(
                "ยังบันทึกรายงานรวมไม่ได้: มี User / Account ที่ไม่มี Total ที่ยืนยัน; "
                "ตรวจ Counter ต้นฉบับได้โดยไม่แทนยอดด้วย 0"
            )
        parsed = preview.parsed
        if check_duplicate(slot, parsed["serial"], parsed["date"]):
            raise ValueError("มี Meter ของเครื่องและวันที่นี้ในช่องที่เลือกแล้ว")
        reading_id = save_reading(slot, parsed, f"LIVE-{preview.reading.host}")
        return SavedLiveMeter(reading_id, slot, preview.reading.host)
