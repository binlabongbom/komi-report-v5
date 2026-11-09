"""Synthetic TXT regressions. No customer names, serials, files or network."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import parser


def mono_lines(model="950i"):
    rows = [[""] * 35 for _ in range(7)]
    rows[0][0], rows[0][4] = "Machine Name", model
    rows[1][0], rows[1][4] = "Serial No.", "SYNTHETIC-NOT-A-DEVICE"
    rows[2][0], rows[2][4] = "Date", "1/1/2026 10:00"
    headers = {
        3: {0: "User Name", 1: "Total Counter", 3: "No. of Originals Counter",
            8: "PaperSizeCounter", 18: "Nin1", 22: "Copy", 25: "Printer", 28: "Scan / Fax"},
        4: {8: "A3", 9: "A4", 10: "B4", 11: "B5", 22: "Total", 23: "Large Size",
            24: "No. of Prints Counter", 25: "Total", 26: "Large Size", 27: "No. of Prints Counter"},
        5: {22: "Total", 23: "Total", 25: "Total", 26: "Total", 28: "Print", 29: "Scans", 30: "Fax TX"},
    }
    for row_index, headings in headers.items():
        for column, value in headings.items():
            rows[row_index][column] = value
    for name, total, copies, prints in (("Test Alpha", 120, 40, 80), ("Paper Team", 75, 15, 60), ("Public", 0, 0, 0)):
        row = ["0"] * 34 + [""]
        row[0], row[1], row[3] = name, str(total), str(total + 10)
        row[8], row[9], row[10], row[11] = "2", "7", "3", "4"
        row[22], row[25] = str(copies), str(prints)
        # Deliberately different from operation/page totals. These must never
        # leak into color/A3/A4 operation fields via the color layout.
        row[23], row[24], row[26], row[27] = "5", "31", "9", "51"
        row[28], row[29], row[30] = "601", "907", "303"
        rows.append(row)
    return rows


def color_lines(model="bizhub C250i"):
    rows = [[""] * 55 for _ in range(7)]
    rows[0][0], rows[0][4] = "Machine Name", model
    rows[1][0], rows[1][4] = "Serial No.", "SYNTHETIC-COLOR"
    rows[2][0], rows[2][4] = "Date", "1/1/2026 10:00"
    rows[3][0], rows[3][1] = "User Name", "Total Counter"
    row = ["0"] * 55
    row[0] = "Color Fixture"
    for column, value in {1: 100, 3: 110, 8: 30, 9: 70, 22: 40, 23: 9, 24: 11,
                          28: 8, 29: 12, 36: 60, 37: 13, 38: 17, 41: 14, 42: 16,
                          48: 22, 49: 28, 52: 22, 53: 28}.items():
        row[column] = str(value)
    rows.append(row)
    return rows


class MonochromeUserTxtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile_patch = patch.object(parser, "_USER_PROFILES_JSON", self.root / "absent-profiles.json")
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)

    def parse(self, rows):
        path = self.root / "synthetic-user-export.txt"
        # Explicit CRLF mirrors the printer export on every host. Disable
        # Windows text translation to avoid producing CRCRLF and extra rows.
        path.write_text("\r\n".join("\t".join(row) for row in rows), encoding="utf-16", newline="")
        self.assertNotIn("\r\r\n", path.read_bytes().decode("utf-16"))
        return parser.detect_parser(str(path))[1]

    def test_exact_monochrome_totals_and_zero_accounts_are_preserved(self):
        parsed = self.parse(mono_lines())
        self.assertEqual(parsed["counter_layout"], "950i-monochrome-user")
        self.assertEqual(parsed["serial"], "SYNTHETIC-NOT-A-DEVICE")
        self.assertEqual(len(parsed["accounts"]), 3)
        self.assertEqual([row["name"] for row in parsed["accounts"]], ["Test Alpha", "Paper Team", "Public"])
        self.assertEqual(parsed["total_counter"], 195)
        self.assertEqual(parsed["detail"]["copy"]["total"], 55)
        self.assertEqual(parsed["detail"]["print"]["total"], 140)
        self.assertEqual(parsed["summary"], {"total_color": 0, "total_bw": 195, "total": 195})
        self.assertEqual(parsed["accounts"][0]["print_total"], 80)

    def test_large_size_physical_print_and_scan_counts_are_not_size_color_counts(self):
        parsed = self.parse(mono_lines())
        for operation, expected in (("copy", 55), ("print", 140)):
            self.assertEqual(parsed["detail"][operation]["bw"], expected)
            for field in ("color", "a4_bw", "a3_bw", "a4_color", "a3_color"):
                self.assertEqual(parsed["detail"][operation][field], 0)
        self.assertEqual(parsed["paper_size"], {"a3": 6, "a4": 21, "b4": 9, "b5": 12})
        self.assertEqual(parsed["paper_color"]["a4_bw"], 21)
        self.assertTrue(any("ไม่มี A3/A4" in warning for warning in parsed["warnings"]))

    def test_mismatch_is_kept_as_source_data_with_warning(self):
        rows = mono_lines()
        rows[7][1] = "127"
        parsed = self.parse(rows)
        self.assertEqual(parsed["total_counter"], 202)
        self.assertEqual(parsed["detail"]["print"]["total"], 140)
        self.assertTrue(any("ไม่เท่ากับ" in warning for warning in parsed["warnings"]))

    def test_known_model_alone_does_not_authorize_unknown_layout(self):
        rows = mono_lines()
        rows[4][25] = "Unverified Metric"
        with self.assertRaisesRegex(ValueError, "โครงสร้างไฟล์"):
            self.parse(rows)

    def test_truncated_and_invalid_counter_rows_fail_instead_of_inventing_zero(self):
        for value in ("", "oops", "-1", "3.5"):
            with self.subTest(value=value):
                rows = mono_lines()
                rows[7][25] = value
                with self.assertRaisesRegex(ValueError, "จำนวนเต็ม"):
                    self.parse(rows)
        rows = mono_lines()
        rows[7] = rows[7][:25]
        with self.assertRaisesRegex(ValueError, "จำนวนเต็ม"):
            self.parse(rows)

    def test_missing_names_and_empty_exports_fail(self):
        rows = mono_lines()
        rows[7][0] = ""
        with self.assertRaisesRegex(ValueError, "ไม่มีชื่อ"):
            self.parse(rows)
        with self.assertRaisesRegex(ValueError, "ไม่พบแถว"):
            self.parse(mono_lines()[:7])

    def test_model_prefix_and_whitespace_do_not_change_mapping(self):
        for model in ("950i", "KM bizhub 950i", "KONICA MINOLTA bizhub 950I"):
            with self.subTest(model=model):
                rows = mono_lines(model)
                rows[4][25] = "  TOTAL  "
                self.assertEqual(self.parse(rows)["detail"]["print"]["total"], 140)

    def test_color_layout_is_unchanged(self):
        for model in ("bizhub C250i", "C450i", "C950i"):
            with self.subTest(model=model):
                parsed = self.parse(color_lines(model))
                self.assertNotIn("counter_layout", parsed)
                self.assertEqual(parsed["total_counter"], 100)
                self.assertEqual(parsed["detail"]["copy"], {
                    "total": 40, "color": 17, "bw": 23, "a4_color": 9, "a4_bw": 11, "a3_color": 8, "a3_bw": 12})
                self.assertEqual(parsed["detail"]["print"], {
                    "total": 60, "color": 27, "bw": 33, "a4_color": 13, "a4_bw": 17, "a3_color": 14, "a3_bw": 16})
                self.assertEqual(parsed["summary"], {"total_color": 44, "total_bw": 56, "total": 100})
                self.assertEqual(parsed["warnings"], [])

    def test_custom_profile_remains_authoritative(self):
        profile = {"name": "Explicit synthetic map", "types": ["user"], "column_map": {
            "user": 0, "grand_total": 1, "copy_total": 22, "print_total": 27}}
        with patch.object(parser, "_find_user_profile", return_value=profile):
            parsed = self.parse(mono_lines())
        self.assertEqual(parsed["parser_name"], "Explicit synthetic map")
        self.assertEqual(parsed["detail"]["print"]["total"], 153)

    def test_metadata_keys_remain_exact_with_optional_terminal_punctuation(self):
        for label in ("Serial No", "Serial No.", "Serial No:", "Serial No.:"):
            with self.subTest(label=label):
                rows = mono_lines()
                rows[1][0] = label
                rows[6][0], rows[6][4] = "Print Date", "must-not-replace-export-date"
                parsed = self.parse(rows)
                self.assertEqual(parsed["serial"], "SYNTHETIC-NOT-A-DEVICE")
                self.assertEqual(parsed["date"], "1/1/2026 10:00")


if __name__ == "__main__":
    unittest.main()
