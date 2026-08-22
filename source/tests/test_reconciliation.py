from services.reconciliation import reconcile_web_counters


def _matching_counters() -> dict[str, int]:
    return {
        "counter.print.total": 100,
        "counter.print.full_color_total": 60,
        "counter.print.full_color_large": 10,
        "counter.print.full_color_long_size": 0,
        "counter.print.bw_total": 40,
        "counter.print.bw_large": 2,
        "counter.copy.total": 20,
        "counter.copy.full_color_total": 5,
        "counter.copy.full_color_large": 1,
        "counter.copy.bw_total": 15,
        "counter.copy.bw_large": 2,
        "counter.scan_fax.print_total": 1,
        "counter.scan_fax.print_large": 0,
        "counter.total.total": 121,
        "counter.total.total_large": 15,
        "counter.paper.black.a3": 2,
        "counter.paper.black.a4": 38,
        "counter.paper.black.print_page_total": 40,
        "counter.paper.full_color.a3": 11,
        "counter.paper.full_color.a4": 49,
        "counter.paper.full_color.print_page_total": 60,
        "counter.total.paper_size_a3": 13,
        "counter.total.paper_size_a4": 87,
        "counter.total.paper": 100,
    }


def test_reconciliation_accepts_consistent_web_meter_sums():
    report = reconcile_web_counters(_matching_counters())

    assert report.checked_count == 12
    assert report.needs_review is False
    assert report.issues == ()
    assert "ตรงกันทั้งหมด" in report.summary()


def test_reconciliation_reports_each_mismatch_with_values_and_difference():
    counters = _matching_counters()
    counters["counter.print.total"] = 101
    counters["counter.paper.full_color.a4"] = 48
    counters["counter.total.paper_size_a4"] = 86

    report = reconcile_web_counters(counters)

    assert report.needs_review is True
    assert {issue.code for issue in report.issues} >= {
        "print_total_by_color",
        "device_total_by_operation",
        "paper_full_color_by_size",
        "paper_total_by_size",
    }
    text = report.summary(limit=20)
    assert "Needs Review" in text
    assert "ต่าง" in text


def test_reconciliation_does_not_compare_snmp_or_user_account_totals():
    report = reconcile_web_counters(
        {
            "snmp.total": 999,
            "counter.user.total.total": 40,
            "counter.track.total.total": 50,
            "counter.total.total": 1_000,
        }
    )

    assert report.checked_count == 0
    assert report.needs_review is False
    assert "ยังไม่มีคู่ Counter" in report.summary()


def _c450i_live_large_counters() -> dict[str, int]:
    """Reviewed 2026-07-21 C450i Web Connection device-meter snapshot."""

    return {
        "counter.print.total": 227_599,
        "counter.print.full_color_total": 177_920,
        "counter.print.full_color_large": 11_813,
        "counter.print.full_color_long_size": 0,
        "counter.print.bi_color_total": 38,
        "counter.print.bi_color_large": 4,
        "counter.print.bi_color_long_size": 0,
        "counter.print.bw_total": 49_641,
        "counter.print.bw_large": 1_031,
        "counter.print.bw_long_size": 0,
        "counter.copy.total": 33_617,
        "counter.copy.full_color_total": 6_206,
        "counter.copy.full_color_large": 245,
        "counter.copy.bi_color_total": 7,
        "counter.copy.bi_color_large": 3,
        "counter.copy.mono_color_total": 5,
        "counter.copy.mono_color_large": 2,
        "counter.copy.bw_total": 27_399,
        "counter.copy.bw_large": 427,
        "counter.scan_fax.print_total": 151,
        "counter.scan_fax.print_large": 8,
        "counter.total.total": 261_367,
        "counter.total.total_large": 13_525,
    }


def test_reconciliation_does_not_double_count_scan_fax_in_device_total_large():
    report = reconcile_web_counters(_c450i_live_large_counters())

    assert report.needs_review is False
    assert not any(issue.code == "device_large_by_operation" for issue in report.issues)


def test_reconciliation_large_mismatch_explains_only_print_and_copy_components():
    counters = _c450i_live_large_counters()
    counters["counter.total.total_large"] = 13_524

    report = reconcile_web_counters(counters)
    issue = next(issue for issue in report.issues if issue.code == "device_large_by_operation")

    assert issue.right_value == 13_525
    assert {term.key for term in issue.right_terms} == {
        "counter.print.full_color_large",
        "counter.print.full_color_long_size",
        "counter.print.bi_color_large",
        "counter.print.bi_color_long_size",
        "counter.print.bw_large",
        "counter.print.bw_long_size",
        "counter.copy.full_color_large",
        "counter.copy.bi_color_large",
        "counter.copy.mono_color_large",
        "counter.copy.bw_large",
    }
    assert "counter.scan_fax.print_large" not in issue.breakdown()
