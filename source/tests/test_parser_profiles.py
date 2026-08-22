import unittest

import parser_profiles


class ParserProfileHelperTests(unittest.TestCase):
    def test_apply_profile_defaults_maps_legacy_account_mode_to_user_profile(self):
        entry = {
            "name": "Legacy account",
            "mode": "account",
            "report_type": "office_print",
            "models": [" Bizhub C360i ", "", "INEO"],
        }

        normalized = parser_profiles.apply_profile_defaults(entry)

        self.assertEqual(normalized["mode"], "user")
        self.assertEqual(normalized["parse_strategy"], "account")
        self.assertEqual(normalized["col_dict_name"], "COLS_ACCOUNT")
        self.assertEqual(normalized["models"], ["bizhub c360i", "ineo"])
        self.assertTrue(
            normalized["detect"](
                "Konica Minolta bizhub c360i",
                "SN-001",
                ["Account Name", "Total"],
                54,
            )
        )
        self.assertFalse(
            normalized["detect"](
                "Konica Minolta bizhub c360i",
                "SN-001",
                ["Total", "Color"],
                54,
            )
        )

    def test_apply_profile_defaults_selects_summary_compact_column_window(self):
        entry = {
            "name": "Compact office",
            "mode": "summary",
            "report_type": "office_print",
            "models": ["bizhub"],
            "col_dict_name": "COLS_SUMMARY_COMPACT",
        }

        normalized = parser_profiles.apply_profile_defaults(entry)

        self.assertEqual(normalized["parse_strategy"], "summary")
        self.assertTrue(normalized["detect"]("bizhub C750i", "SN-002", ["Total"], 25))
        self.assertTrue(normalized["detect"]("bizhub C750i", "SN-002", ["Total"], 39))
        self.assertFalse(normalized["detect"]("bizhub C750i", "SN-002", ["Total"], 40))
        self.assertFalse(normalized["detect"]("bizhub C750i", "SN-002", ["Account Name"], 30))

    def test_apply_profile_defaults_uses_production_strategy_for_production_report_type(self):
        entry = {
            "name": "Press summary",
            "mode": "summary",
            "report_type": "production_print",
            "models": [" C4070 "],
            "col_dict_name": "COLS_SUMMARY",
        }

        normalized = parser_profiles.apply_profile_defaults(entry)

        self.assertEqual(normalized["mode"], "summary")
        self.assertEqual(normalized["parse_strategy"], "production")
        self.assertEqual(normalized["col_dict_name"], "COLS_PRODUCTION")
        self.assertTrue(normalized["detect"]("AccurioPress C4070", "SN-003", ["Total"], 24))
        self.assertFalse(normalized["detect"]("bizhub C360i", "SN-004", ["Total"], 60))

    def test_render_registry_entry_serializes_detect_source_for_label_mode(self):
        entry = {
            "name": "Label test",
            "description": "Synthetic label profile",
            "mode": "label",
            "report_type": "label_print",
            "models": [" AL230 "],
            "color": "#111111",
        }

        rendered = parser_profiles.render_registry_entry(entry)

        self.assertIn('"parse_strategy": "label"', rendered)
        self.assertIn('"col_dict_name": "COLS_LABEL"', rendered)
        self.assertIn('"models":        ["al230"]', rendered)
        self.assertIn("ncols >= 2", rendered)
        self.assertIn("not (bool(hdr)", rendered)

    def test_duplicate_profile_returns_independent_normalized_copy(self):
        original = {
            "name": "Office summary",
            "mode": "summary",
            "report_type": "office_print",
            "models": ["bizhub"],
            "col_dict_name": "COLS_SUMMARY",
            "metadata": {"owner": "qa"},
        }

        duplicated = parser_profiles.duplicate_profile(original)
        duplicated["metadata"]["owner"] = "changed"

        self.assertEqual(duplicated["name"], "Office summary Copy")
        self.assertEqual(duplicated["parse_strategy"], "summary")
        self.assertEqual(duplicated["col_dict_name"], "COLS_SUMMARY")
        self.assertEqual(original["metadata"]["owner"], "qa")


if __name__ == "__main__":
    unittest.main()
