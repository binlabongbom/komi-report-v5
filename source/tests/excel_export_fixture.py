"""Deterministic 90-user workload; contains no customer data or network calls."""
from dataclasses import replace
from datetime import date, datetime, timedelta, UTC

from services.device_config import DeviceConfig
from services.report_excel_export import CloudReportsExportData, DailyCategoryCost
from test_report_excel_export import _raw, _subject, _usage


def report_for(users=90, days=30, printers=3):
    start = date(2026, 7, 1)
    end = start + timedelta(days=days - 1)
    devices, daily, subjects, raw, costs = [], [], [], [], []
    # Eight exact, independent operation counters plus the cumulative total.
    fields = tuple((f'counter.{op}.{color}.{size}', f'{op} {color} {size}')
                   for op in ('print', 'copy') for size in ('a4', 'a3') for color in ('full_color', 'black'))
    for slot in range(printers):
        serial, name = f'SYNTH-{slot}', f'Fixture {slot + 1}'
        identity = 'serial:' + serial
        devices.append(DeviceConfig(slot, name, f'192.0.2.{10 + slot}', serial=serial))
        for offset in range(days):
            day = start + timedelta(days=offset)
            daily.append(replace(_usage(day, slot=slot, identity=identity, name=name, total=users * 8),
                a4_color=users * 2, a4_bw=users * 2, a3_color=users * 2, a3_bw=users * 2,
                print_color=users * 2, print_bw=users * 2,
                copy_color=users * 2, copy_bw=users * 2, scan=0,
                **{f'{op}_{size}_{color}': users for op in ('print', 'copy') for size in ('a4', 'a3') for color in ('color', 'bw')},
                gross_cost=users * 16, net_cost=users * 16))
            costs.append(DailyCategoryCost(slot, identity, day, *(users * 4 for _ in range(4))))
            for field, label in fields:
                raw.append(_raw(day, slot=slot, field=field, label=label, delta=users, serial=serial, name=name))
            for number in range(users):
                for field, label in fields:
                    raw.append(replace(_raw(day, slot=slot, field=field, label=label, delta=1,
                        subject=True, serial=serial, name=name), subject_id=str(number), subject_name=f'User {number:03d}'))
        for number in range(users):
            subjects.append(replace(_subject(start, slot=slot, identity=identity, name=name, usage=days * 8),
                subject_id=str(number), subject_name=f'User {number:03d}', period_end=end))
    return CloudReportsExportData(tuple(daily), tuple(daily), tuple(daily), (), tuple(subjects),
        tuple(devices), (start.isoformat(), end.isoformat()), None, datetime.now(UTC),
        category_costs=tuple(costs), raw_counter_records=tuple(raw))
