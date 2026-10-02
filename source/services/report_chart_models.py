"""Immutable chart values prepared by report workers without importing Qt."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from services.report_models import _combined, _record_identity, cooperate

FIVE_CATEGORIES = ('Print Color', 'Print B&W', 'Copy Color', 'Copy B&W', 'Scan')


@dataclass(frozen=True)
class ChartSeries:
    label: str
    values: tuple[float, ...]
    role: Literal['print', 'copy', 'scan', 'device']
    light: bool = False
    palette_index: int = 0


@dataclass(frozen=True)
class ChartModel:
    categories: tuple[str, ...]
    series: tuple[ChartSeries, ...]
    # Overview has two bars but one centered date label for each day.
    day_labels: tuple[str, ...] = ()
    estimated: bool = False


def slot_label(slot: int, devices_by_slot, record=None) -> str:
    device = devices_by_slot.get(slot)
    name = str(getattr(device, 'name', '') or '').strip()
    if not name and record is not None:
        name = str(getattr(record, 'device_name_snapshot', '')
                   or getattr(record, 'machine_name', '') or '').strip()
    return f"Slot {slot + 1} · {name or 'ยังไม่ได้ตั้งชื่อ'}"


def _in_period(record, period) -> bool:
    return period is None or (str(record.period_start) <= period[1]
                              and str(record.period_end) >= period[0])


def build_paper_mix(records, *, cancelled=None) -> ChartModel:
    totals = [0.0] * 9
    fields = tuple(f'{operation}_{paper}_{color}' for operation in ('print', 'copy')
                   for paper in ('a4', 'a3') for color in ('color', 'bw')) + ('scan',)
    seen = False
    for index, record in enumerate(records):
        cooperate(cancelled, index)
        seen = True
        for position, field in enumerate(fields):
            totals[position] += _combined(record, field)
    series = []
    for operation_index, operation in enumerate(('print', 'copy')):
        for paper_index, paper in enumerate(('a4', 'a3')):
            values = [0.0] * 5
            for color_index in range(2):
                values[operation_index * 2 + color_index] = totals[operation_index * 4 + paper_index * 2 + color_index]
            series.append(ChartSeries(f'{operation.title()} {paper.upper()}', tuple(values), operation, paper == 'a3'))
    series.append(ChartSeries('Scan', (0, 0, 0, 0, totals[-1]), 'scan'))
    return ChartModel(FIVE_CATEGORIES if seen else (), tuple(series))


def build_overview_timeline(records, *, period=None, identity=None, cancelled=None) -> ChartModel:
    grouped = defaultdict(lambda: [0.0] * 4)
    for position, record in enumerate(records):
        cooperate(cancelled, position)
        if not _in_period(record, period) or (identity and _record_identity(record) != identity):
            continue
        day = str(record.period_start)[:10]
        for index, (operation, paper) in enumerate((('print', 'a4'), ('print', 'a3'), ('copy', 'a4'), ('copy', 'a3'))):
            grouped[day][index] += sum(_combined(record, f'{operation}_{paper}_{color}') for color in ('color', 'bw'))
    days = sorted(grouped)[-14:]
    categories = tuple(f'{day[8:10]}/{day[5:7]} {operation}' for day in days for operation in ('P', 'C'))
    series = []
    for index, (operation, paper) in enumerate((('print', 'a4'), ('print', 'a3'), ('copy', 'a4'), ('copy', 'a3'))):
        values = tuple(grouped[day][index] if position % 2 == index // 2 else 0.0
                       for day in days for position in range(2))
        series.append(ChartSeries(f'{operation.title()} {paper.upper()}', values, operation, paper == 'a3'))
    return ChartModel(categories, tuple(series), tuple(f'{day[8:10]}/{day[5:7]}' for day in days))


def build_printer_timeline(records, slots, devices, *, period=None, cancelled=None) -> ChartModel:
    daily = defaultdict(lambda: [0.0, 0.0])
    estimated = False
    for position, record in enumerate(records):
        cooperate(cancelled, position)
        if not _in_period(record, period):
            continue
        day, slot = str(record.period_start)[:10], int(record.device_slot)
        for index, color in enumerate(('color', 'bw')):
            daily[(day, slot)][index] += sum(_combined(record, f'{operation}_{paper}_{color}')
                                            for operation in ('print', 'copy') for paper in ('a3', 'a4'))
        estimated |= any('ค่าเฉลี่ยประมาณการ' in note for note in getattr(record, 'remarks', ()))
    dates = sorted({day for day, _slot in daily})[-14:]
    devices_by_slot = {int(device.slot): device for device in devices}
    series = []
    for index, slot in enumerate(sorted(set(slots))):
        name = slot_label(slot, devices_by_slot)
        for shade, label in enumerate(('Color', 'B&W')):
            series.append(ChartSeries(f'{name} · {label}', tuple(daily[(day, slot)][shade] for day in dates),
                                      'device', bool(shade), index))
    return ChartModel(tuple(f'{day[8:10]}/{day[5:7]}' for day in dates), tuple(series), estimated=estimated)


def build_report_chart_models(index, records, chart_daily_records, devices, printer_rows, *, period, cancelled=None):
    """Prepare only the selected tab's charts using the snapshot's exact data scope."""
    result = {'paper_mix': build_paper_mix(records, cancelled=cancelled)}
    if index == 0:
        result['overview_timeline'] = build_overview_timeline(chart_daily_records, period=period, cancelled=cancelled)
    elif index == 2:
        result['printer_timeline'] = build_printer_timeline(
            chart_daily_records, (int(row['slot']) for row in printer_rows), devices, period=period, cancelled=cancelled)
    else:
        raise ValueError('Prepared charts are available for Overview and Printers only')
    return MappingProxyType(result)
