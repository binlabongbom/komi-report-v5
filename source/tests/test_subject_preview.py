"""Synthetic identities, zero/nonzero readings and overlapping raw counters."""
from dataclasses import replace
import unittest

from services.runtime_snapshots import RuntimeCounterRow
from services.subject_preview import build_subject_preview_rows


def preview_counter(field="total.bw", *, value=0, kind="user", sid="1", name="Fixture User", label=None):
    return RuntimeCounterRow(f"counter.{kind}.{field}", label or field, value,
                             f"synthetic/AuthCounter[{sid}]/{field}", kind, sid, name)


def monochrome_preview_counters(value=0):
    observed_fields = ("total.bw", "total.bw_large", "total.black_print_paper", "total.document",
                       "total.duplex_total", "total.paper", "total.print_page_total", "copy.bw", "print.bw")
    # Only the nine named fields above come from the redacted shape evidence.
    # Ten explicitly synthetic fields exercise a 95-row / 5-identity snapshot.
    fields = (*observed_fields, *(f"synthetic.metric_{index}" for index in range(10)))
    return tuple(preview_counter(field, value=value + index, sid=str(subject), name=f"Synthetic {subject}")
                 for subject in range(1, 6) for index, field in enumerate(fields))


class SubjectPreviewTests(unittest.TestCase):
    def test_five_identities_are_visible_without_a_total(self):
        counters = monochrome_preview_counters()
        original = tuple(counters)
        rows = build_subject_preview_rows(counters)
        self.assertEqual(len(counters), 95)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row.total is None and row.total_state == "missing" for row in rows))
        self.assertTrue(all(len(row.counters) == 19 for row in rows))
        self.assertEqual(tuple(counters), original)

    def test_all_measured_zeros_still_show_users_without_inventing_a_total_zero(self):
        counters = tuple(replace(row, count=0) for row in monochrome_preview_counters())
        rows = build_subject_preview_rows(counters)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row.total is None for row in rows))
        self.assertTrue(all(counter.count == 0 for row in rows for counter in row.counters))

    def test_overlapping_nonzero_meters_are_never_summed_or_substituted(self):
        counters = (preview_counter("total.bw", value=100), preview_counter("total.paper", value=80),
                    preview_counter("total.document", value=120), preview_counter("total.print_page_total", value=90))
        row, = build_subject_preview_rows(counters)
        self.assertIsNone(row.total)
        self.assertEqual([item.count for item in row.counters], [100, 80, 120, 90])

    def test_explicit_zero_and_color_total_remain_available_without_double_count(self):
        for value in (0, 150):
            with self.subTest(value=value):
                total = preview_counter("total.total", value=value)
                counters = (total, total, preview_counter("total.bw", value=80),
                            preview_counter("total.full_color", value=70))
                row, = build_subject_preview_rows(counters)
                self.assertEqual(row.total, value)
                self.assertEqual(row.total_state, "available")
                self.assertEqual(len(row.counters), 3)

    def test_label_total_is_not_authority_for_an_unrelated_counter(self):
        row, = build_subject_preview_rows((preview_counter("total.paper", value=500, label="Total Counter"),))
        self.assertIsNone(row.total)

    def test_conflicting_and_invalid_totals_are_not_presented_as_confirmed(self):
        total = preview_counter("total.total", value=100)
        row, = build_subject_preview_rows((total, replace(total, count=101)))
        self.assertIsNone(row.total)
        self.assertEqual(row.total_state, "conflicting")
        for value in (-1, float("inf"), float("nan"), True):
            with self.subTest(value=value):
                row, = build_subject_preview_rows((replace(total, count=value),))
                self.assertIsNone(row.total)
                self.assertEqual(row.total_state, "invalid")

    def test_ids_and_subject_types_are_never_merged_by_display_name(self):
        counters = tuple(preview_counter(kind=kind, sid=sid, name="Same visible name")
                         for kind, sid in (("user", "1"), ("user", "01"), ("account", "1"), ("track", "1")))
        self.assertEqual(len(build_subject_preview_rows(counters)), 4)

    def test_real_name_is_preserved_when_an_id_only_row_follows(self):
        rows = build_subject_preview_rows((preview_counter(name="Known Name"),
                                           preview_counter("copy.bw", name="1")))
        self.assertEqual(rows[0].subject_name, "Known Name")

    def test_machine_counters_are_excluded_from_subject_preview(self):
        counter = replace(preview_counter(), subject_type=None, subject_id=None, subject_name=None)
        self.assertEqual(build_subject_preview_rows((counter,)), ())


if __name__ == "__main__":
    unittest.main()
