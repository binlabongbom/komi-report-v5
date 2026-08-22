import tempfile
import unittest
from pathlib import Path

import database
from services.import_service import ParsedImport, configured_profile_slot, save_import


def _reading() -> dict:
    return {
        "machine_name": "Import Service Test",
        "serial": "SN-IMPORT",
        "date": "2026/07/20",
        "mode": "summary",
        "total_counter": 100,
        "summary": {"total_color": 40, "total_bw": 60, "total": 100},
        "paper_color": {"a4_color": 40, "a4_bw": 60, "a3_color": 0, "a3_bw": 0},
        "detail": {},
        "warnings": [],
    }


class ImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_path = database.get_db_path()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        database.set_db_path(self.root / "import.sqlite3")
        database.init_db()

    def tearDown(self):
        database.set_db_path(self.original_path)
        self.tmp.cleanup()

    def test_configured_profile_slot_parses_valid_setting(self):
        database.set_cfg("parser_0", "7")
        database.set_cfg("parser_1", "bad")

        self.assertEqual(configured_profile_slot(0), 7)
        self.assertIsNone(configured_profile_slot(1))
        self.assertIsNone(configured_profile_slot(2))

    def test_parsed_import_unknown_parser_helpers(self):
        result = ParsedImport(parser_name="Unknown", parsed={"machine": "bizhub"})

        self.assertTrue(result.is_unknown_parser)
        self.assertEqual(result.unknown_machine_name("fallback.txt"), "bizhub")

    def test_save_import_persists_reading_and_archives_file(self):
        source = self.root / "meter.txt"
        source.write_text("synthetic meter content", encoding="utf-8")
        database.set_cfg("machine_name_0", "Demo Machine")

        result = save_import(0, _reading(), str(source))
        curr, prev = database.get_last_two(0)

        self.assertIsNone(prev)
        self.assertEqual(curr["serial"], "SN-IMPORT")
        self.assertGreater(result.reading_id, 0)
        self.assertIsNotNone(result.archived_path)
        self.assertTrue(result.archived_path.exists())


if __name__ == "__main__":
    unittest.main()
