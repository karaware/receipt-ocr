import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from receipt_ocr.cloud_worker import CloudWorker, PocSettings
from receipt_ocr.drive_api_client import DriveImage
from receipt_ocr.vision_client import VisionRequestIndeterminate


class CloudWorkerTest(unittest.TestCase):
    def _worker(self, tmp, writer, drive=None, vision=None):
        settings = PocSettings("folder", "home", "d", "v", "f", Path(tmp), 20, "me")
        config = {
            "parser": {"tax_included_keywords": ["合計"], "ignore_line_keywords": []},
            "categories": {"食費": ["パン"]},
        }
        drive = drive or MagicMock()
        drive.list_images.return_value = [DriveImage("file-1", "receipt.jpg", "image/jpeg", 1)]
        return CloudWorker(config, settings, drive, vision or MagicMock(), writer)

    def test_completed_file_is_not_downloaded_or_ocrd(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = {"status": "completed"}
            worker = self._worker(tmp, writer)
            self.assertEqual(worker.run_once(), {"status": "idle"})
            worker._drive.download.assert_not_called()
            worker._vision.document_text.assert_not_called()

    def test_processes_one_file_and_does_not_store_ocr_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = None
            writer.reserve.return_value = MagicMock(reserved=True, reason="reserved")
            drive = MagicMock()
            drive.list_images.return_value = [DriveImage("file-1", "receipt.jpg", "image/jpeg", None)]
            drive.download.side_effect = lambda image, target: Path(target).write_bytes(b"x")
            vision = MagicMock()
            vision.document_text.return_value = "店\n2026/06/28\nパン 100\n合計 100"
            result = self._worker(tmp, writer, drive, vision).run_once()
            self.assertEqual(result["driveFileId"], "file-1")
            payload = writer.complete.call_args.args[1]
            self.assertNotIn("ocrText", payload)
            self.assertNotIn("items", payload)
            self.assertFalse((Path(tmp) / "file-1.jpg").exists())

    def test_dry_run_does_not_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = None
            result = self._worker(tmp, writer).run_once(dry_run=True)
            self.assertEqual(result["status"], "candidate")
            writer.reserve.assert_not_called()

    def test_failure_before_vision_can_reuse_its_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = {"status": "failed", "visionAttempted": False}
            writer.reserve.return_value = MagicMock(reserved=True, reason="reserved")
            drive = MagicMock()
            drive.list_images.return_value = [DriveImage("file-1", "receipt.jpg", "image/jpeg", None)]
            drive.download.side_effect = OSError("temporary Drive failure")
            result = self._worker(tmp, writer, drive).run_once()
            self.assertEqual(result["status"], "failed")
            writer.reserve.assert_called_once()

    def test_indeterminate_vision_response_is_not_automatically_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = None
            writer.reserve.return_value = MagicMock(reserved=True, reason="reserved")
            drive = MagicMock()
            drive.list_images.return_value = [DriveImage("file-1", "receipt.jpg", "image/jpeg", None)]
            drive.download.side_effect = lambda image, target: Path(target).write_bytes(b"x")
            vision = MagicMock()
            vision.document_text.side_effect = VisionRequestIndeterminate("timeout")
            result = self._worker(tmp, writer, drive, vision).run_once()
            self.assertEqual(result["status"], "unknown_after_request")
            writer.mark_unknown.assert_called_once()
            writer.mark_failed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
