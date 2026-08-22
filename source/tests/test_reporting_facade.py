from datetime import date

from services.reporting_facade import ReportReadService


def test_report_read_service_uses_injected_data_sources():
    service = ReportReadService(
        slots_loader=lambda: [0, 2],
        usage_loader=lambda slots, *, granularity: [(tuple(slots), granularity)],
        subject_loader=lambda slots: [(tuple(slots), "subjects")],
    )

    assert service.usage() == [((0, 2), "monthly")]
    assert service.subjects() == [((0, 2), "subjects")]


def test_report_read_service_passes_custom_subject_range():
    calls = []

    def subjects(slots, **kwargs):
        calls.append((tuple(slots), kwargs))
        return ["selected"]

    service = ReportReadService(
        slots_loader=lambda: [1],
        usage_loader=lambda *_args, **_kwargs: (),
        subject_loader=subjects,
    )
    start = date(2026, 7, 10)
    end = date(2026, 7, 20)

    assert service.subjects(period_start=start, period_end=end) == ["selected"]
    assert calls == [((1,), {"period_start": start, "period_end": end})]
