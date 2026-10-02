"""Independent chart arithmetic and worker/UI boundary regression contracts."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import date
from threading import Event
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from services.report_chart_models import (
    FIVE_CATEGORIES,
    build_overview_timeline,
    build_paper_mix,
    build_printer_timeline,
    build_report_chart_models,
)


def record(day=1, slot=0, **changes):
    values = dict(period_start=date(2026, 9, day), period_end=date(2026, 9, day),
                  device_slot=slot, device_identity=f'serial:{slot}',
                  print_a4_color=10, print_a4_bw=5, print_a3_color=2, print_a3_bw=1,
                  copy_a4_color=4, copy_a4_bw=3, copy_a3_color=1, copy_a3_bw=2, scan=8,
                  provisional_print_a4_color=0.5, remarks=())
    return SimpleNamespace(**(values | changes))


def test_five_category_totals_include_estimates_and_keep_paper_sizes_separate():
    model = build_paper_mix([record()])
    assert model.categories == FIVE_CATEGORIES
    assert [series.values for series in model.series] == [
        (10.5, 5, 0, 0, 0), (2, 1, 0, 0, 0),
        (0, 0, 4, 3, 0), (0, 0, 1, 2, 0), (0, 0, 0, 0, 8),
    ]
    assert [sum(series.values[index] for series in model.series) for index in range(5)] == [12.5, 6, 5, 5, 8]
    assert [series.light for series in model.series] == [False, True, False, True, False]


def test_overview_limits_the_selected_period_then_uses_fourteen_chronological_days():
    records = [record(day) for day in reversed(range(1, 21))]
    records.append(record(6, slot=1, print_a4_color=1000))
    model = build_overview_timeline(records, period=('2026-09-03', '2026-09-18'), identity='serial:0')
    assert model.day_labels == tuple(f'{day:02}/09' for day in range(5, 19))
    assert len(model.categories) == 28
    assert model.series[0].values == (15.5, 0) * 14
    assert model.series[1].values == (3, 0) * 14
    assert model.series[2].values == (0, 7) * 14
    assert model.series[3].values == (0, 3) * 14


def test_printer_timeline_groups_replaced_devices_by_slot_and_keeps_gaps():
    records = [record(1, slot=2), record(3, slot=0),
               record(3, slot=0, device_identity='serial:replacement', remarks=('ค่าเฉลี่ยประมาณการ',))]
    devices = [SimpleNamespace(slot=0, name='Reception'), SimpleNamespace(slot=2, name='Office')]
    model = build_printer_timeline(records, [2, 0, 0], devices)
    assert model.categories == ('01/09', '03/09')
    assert [series.label for series in model.series] == [
        'Slot 1 · Reception · Color', 'Slot 1 · Reception · B&W',
        'Slot 3 · Office · Color', 'Slot 3 · Office · B&W',
    ]
    assert [series.values for series in model.series] == [(0, 35), (0, 22), (17.5, 0), (11, 0)]
    assert [series.palette_index for series in model.series] == [0, 0, 1, 1]
    assert model.estimated


@pytest.mark.parametrize('builder', [
    lambda rows, event: build_paper_mix(rows, cancelled=event),
    lambda rows, event: build_overview_timeline(rows, cancelled=event),
    lambda rows, event: build_printer_timeline(rows, [0], [], cancelled=event),
])
def test_cancelled_preparation_does_not_scan_history(builder):
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError):
        builder([record()], cancelled)


def test_models_are_immutable_and_can_be_prepared_without_a_gui_thread():
    with ThreadPoolExecutor(max_workers=1) as pool:
        models = pool.submit(build_report_chart_models, 0, [record()], [record()], [], [],
                             period=('2026-09-01', '2026-09-30')).result(timeout=5)
    with pytest.raises(TypeError):
        models['another'] = models['paper_mix']
    with pytest.raises(FrozenInstanceError):
        models['paper_mix'].series = ()
    with pytest.raises(FrozenInstanceError):
        models['paper_mix'].series[0].values = ()


def test_qt_renderer_rejects_worker_thread_widget_construction():
    from ui.reports.charts import render_chart
    app = QApplication.instance() or QApplication([])
    assert app is not None
    model = build_paper_mix([record()])
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match='GUI thread'):
            pool.submit(render_chart, model).result(timeout=5)


@pytest.mark.parametrize('index', [0, 2])
def test_prepared_snapshots_render_without_reaggregating_on_gui(monkeypatch, index):
    from excel_export_fixture import report_for

    from services.report_models import build_printer_rows
    from ui import cloud_reports
    app = QApplication.instance() or QApplication([])
    report = report_for(users=2, days=3)
    rows = build_printer_rows(report.selected_records, report.devices)
    with ThreadPoolExecutor(max_workers=1) as pool:
        models = pool.submit(build_report_chart_models, index, report.selected_records, report.usage_daily_records,
                             report.devices, rows, period=report.period, cancelled=Event()).result(timeout=5)
    widget = cloud_reports.CloudReportsWidget(staged=True)
    widget.tabs.setCurrentIndex(index)
    for name in ('build_paper_mix', 'build_overview_timeline', 'build_printer_timeline'):
        monkeypatch.setattr(cloud_reports, name, lambda *a, **kw: pytest.fail('GUI aggregated prepared chart data'))
    widget.set_data(records=report.selected_records, daily_records=report.selected_daily_records,
                    subjects=report.subjects, devices=report.devices, period=report.period, last_sync_at=None,
                    prepared_models={'printers': rows, 'charts': models}, tab_index=index)
    for _ in range(40):
        app.processEvents()
        if not widget._pending_render_tail:
            break
        QTest.qWait(10)
    view = widget.overview_mix if index == 0 else widget.printer_mix
    assert view.chart().axes(Qt.Orientation.Horizontal)[0].categories() == list(FIVE_CATEGORIES)
    assert [sum(bar.at(i) for bar in view.chart().series()[0].barSets()) for i in range(5)] == [36, 36, 36, 36, 0]
    widget.close()


def test_chart_preparation_has_no_qt_dependency():
    import os
    import subprocess
    import sys
    from pathlib import Path
    source = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c',
                             "import services.report_chart_models; import sys; assert not any(n.startswith('PyQt6') for n in sys.modules)"],
                            env={**os.environ, 'PYTHONPATH': str(source)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
