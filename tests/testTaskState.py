import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from taskState import createTaskRecord, normalizeTaskRecord  # noqa: E402


class TaskStateTests(unittest.TestCase):
    def test_create_task_record_contains_expected_fields(self):
        record = createTaskRecord(task_id="job1", status="running", progress=12, message="hello")
        self.assertEqual(record["taskId"], "job1")
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["progress"], 12)
        self.assertIn("stats", record)
        self.assertIn("files", record)
        self.assertIn("processLog", record)
        self.assertEqual(record["stats"]["totalTiles"], 0)

    def test_normalize_task_record_folds_top_level_tile_stats(self):
        normalized = normalizeTaskRecord(
            "job2",
            {
                "status": "completed",
                "progress": 100,
                "message": "done",
                "totalTiles": 10,
                "processedTiles": 9,
                "failedTiles": 1,
            },
        )
        self.assertEqual(normalized["taskId"], "job2")
        self.assertEqual(normalized["stats"]["totalTiles"], 10)
        self.assertEqual(normalized["stats"]["processedTiles"], 9)
        self.assertEqual(normalized["stats"]["failedTiles"], 1)
        self.assertEqual(normalized["stats"]["remainingTiles"], 0)


if __name__ == "__main__":
    unittest.main()
