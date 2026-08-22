import tempfile
import unittest
from pathlib import Path

import database
from services.import_worker import ImportSaveWorker


def _reading() -> dict:
    return {
        "machine_name": "Worker Test",
        "serial": "SN-WORKER",
        "date": "2026/07/20",
        "mode": "summary",
        "total_counter": 100,
        "summary": {"total_color": 40, "total_bw": 60, "total": 100},
        "paper_color": {"a4_color": 40, "a4_bw": 60, "a3_color": 0, "a3_bw": 0},
        "detail": {},
        "warnings": [],
    }


class ImportSaveWorkerTests(unittest.TestCase):
    def setUp(self):
        self.original_path = database.get_db_path()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        database.set_db_path(self.root / "worker.sqlite3")
        database.init_db()

    def tearDown(self):
        database.set_db_path(self.original_path)
        self.tmp.cleanup()

    def test_run_emits_progress_and_success_after_save_archive(self):
        source = self.root / "meter.txt"
        source.write_text("synthetic meter content", encoding="utf-8")
        database.set_cfg("machine_name_0", "Worker Machine")

        progress = []
        successes = []
        errors = []
        worker = ImportSaveWorker(0, _reading(), str(source))
        worker.progress.connect(progress.append)
        worker.success.connect(successes.append)
        worker.error.connect(errors.append)

        worker.run()

        curr, prev = database.get_last_two(0)
        self.assertEqual(errors, [])
        self.assertEqual(progress, ["กำลังบันทึกข้อมูล...", "กำลังจัดเก็บไฟล์นำเข้า..."])
        self.assertIsNone(prev)
        self.assertEqual(curr["serial"], "SN-WORKER")
        self.assertEqual(len(successes), 1)
        self.assertGreater(successes[0].reading_id, 0)
        self.assertIsNotNone(successes[0].archived_path)
        self.assertTrue(successes[0].archived_path.exists())


if __name__ == "__main__":
    unittest.main()
