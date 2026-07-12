import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from receipt_ocr.llm_spool import LlmSpool, load_result


class LlmSpoolTest(unittest.TestCase):
    def test_enqueue_acquire_complete_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "receipt.jpg"
            image.write_bytes(b"image")
            spool = LlmSpool(root / "spool")
            queued = spool.enqueue(
                "file-1", image, "店\n合計 100",
                {"shopName": "店", "totalAmount": 100},
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            self.assertEqual(queued.path.parent, spool.pending)
            running = spool.acquire()
            self.assertIsNotNone(running)
            assert running is not None
            completed = spool.complete(running, running.meta, result_text='{"ok": true}')
            self.assertEqual(load_result(completed), {"ok": True})
            spool.remove(completed)
            self.assertIsNone(spool.find("file-1"))

    def test_retry_with_model_preserves_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "receipt.jpg"
            image.write_bytes(b"image")
            spool = LlmSpool(root / "spool")
            spool.enqueue(
                "file-1", image, "店\n合計 100", {},
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            running = spool.acquire()
            assert running is not None
            completed = spool.complete(running, running.meta, result_text="not-json")
            retried = spool.retry_with_model(completed, "gpt-5.6-terra")
            self.assertEqual(retried.path.parent, spool.pending)
            self.assertEqual(retried.meta["modelStage"], "retry")
            self.assertEqual(retried.request["driveFileId"], "file-1")

    def test_job_directory_and_files_are_group_accessible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "receipt.jpg"
            image.write_bytes(b"image")
            spool = LlmSpool(root / "spool")
            queued = spool.enqueue(
                "file-1", image, "店\n合計 100", {},
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            # Darwin does not retain the setgid bit on this temporary test
            # directory, but group traversal/read-write permissions must remain.
            self.assertEqual(queued.path.stat().st_mode & 0o770, 0o770)
            self.assertEqual((queued.path / "job.json").stat().st_mode & 0o777, 0o660)

    def test_health_status_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            spool = LlmSpool(Path(tmp) / "spool")
            self.assertIsNone(spool.read_health())
            spool.write_health("auth_blocked")
            self.assertEqual(spool.read_health()["status"], "auth_blocked")

    def test_recovers_expired_running_lease_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "receipt.jpg"
            image.write_bytes(b"image")
            spool = LlmSpool(root / "spool")
            spool.enqueue(
                "file-1", image, "店\n合計 100", {},
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            running = spool.acquire()
            self.assertIsNotNone(running)
            assert running is not None
            meta = dict(running.meta)
            meta["leaseStartedAt"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
            (running.path / "job.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertEqual(spool.recover_expired_leases(), 1)
            self.assertEqual(spool.find("file-1").path.parent, spool.pending)


if __name__ == "__main__":
    unittest.main()
