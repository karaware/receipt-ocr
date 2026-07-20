import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from receipt_ocr.cloud_worker import CloudWorker, PocSettings
from receipt_ocr.drive_api_client import DriveImage
from receipt_ocr.vision_client import VisionRequestIndeterminate


class CloudWorkerTest(unittest.TestCase):
    def _worker(self, tmp, writer, drive=None, vision=None, llm_enabled=False):
        settings = PocSettings("folder", "home", "d", "v", "f", Path(tmp), 20, "me")
        config = {
            "parser": {"tax_included_keywords": ["合計"], "ignore_line_keywords": []},
            "categories": {"食費": ["パン"]},
            "poc": {"llm": {
                "enabled": llm_enabled,
                "spool_dir": str(Path(tmp) / "llm-spool"),
            }},
        }
        if drive is None:
            drive = MagicMock()
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

    def test_confirmed_file_is_not_downloaded_or_ocrd(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = {"status": "confirmed"}
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
            self.assertEqual(payload["difference"], 0)
            self.assertEqual(
                payload["parsedItems"],
                [{"name": "パン", "amount": 100, "category": "食費", "confidence": 0.9}],
            )
            self.assertEqual(payload["parsedItems"], payload["reconciledItems"])
            self.assertFalse((Path(tmp) / "file-1.jpg").exists())

    def test_processes_a_camera_batch_in_one_timer_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = None
            writer.reserve.return_value = MagicMock(reserved=True, reason="reserved")
            drive = MagicMock()
            drive.list_images.return_value = [
                DriveImage(f"file-{index}", f"receipt-{index}.jpg", "image/jpeg", None)
                for index in range(1, 5)
            ]
            drive.download.side_effect = lambda image, target: Path(target).write_bytes(b"x")
            vision = MagicMock()
            vision.document_text.return_value = "店\n2026/06/28\nパン 100\n合計 100"

            result = self._worker(tmp, writer, drive, vision).run_once()

            self.assertEqual(result["status"], "batch_completed")
            self.assertEqual(result["count"], 4)
            self.assertEqual(len(result["processed"]), 4)
            self.assertEqual(writer.reserve.call_count, 4)
            self.assertEqual(writer.complete.call_count, 4)

    def test_finalizes_all_completed_llm_results_before_processing_new_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            drive = MagicMock()
            drive.list_images.return_value = []
            worker = self._worker(tmp, writer, drive, llm_enabled=True)
            worker._finalize_llm_result = MagicMock(side_effect=[
                {"status": "confirmed", "driveFileId": "file-1"},
                {"status": "needs_review", "driveFileId": "file-2"},
                None,
            ])

            result = worker.run_once()

            self.assertEqual(result["status"], "batch_completed")
            self.assertEqual(result["finalized"], [
                {"status": "confirmed", "driveFileId": "file-1"},
                {"status": "needs_review", "driveFileId": "file-2"},
            ])
            self.assertEqual(result["processed"], [])

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

    def test_llm_enabled_enqueues_without_storing_ocr_in_firestore(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = None
            writer.reserve.return_value = MagicMock(reserved=True, reason="reserved")
            writer.list_allowed_categories.return_value = [
                {"major": "食費", "minor": ["その他"]},
                {"major": "調整", "minor": ["値引き・税"]},
            ]
            drive = MagicMock()
            drive.list_images.return_value = [DriveImage("file-1", "receipt.jpg", "image/jpeg", None)]
            drive.download.side_effect = lambda image, target: Path(target).write_bytes(b"x")
            vision = MagicMock()
            vision.document_text.return_value = "店\n2026/06/28\nパン 100\n合計 100"

            worker = self._worker(tmp, writer, drive, vision, llm_enabled=True)
            result = worker.run_once()

            self.assertEqual(result["status"], "llm_pending")
            writer.complete.assert_not_called()
            writer.mark_llm_state.assert_called_once()
            self.assertNotIn("店\n2026", str(writer.method_calls))
            job = worker._llm_spool.find("file-1")
            self.assertIsNotNone(job)
            assert job is not None
            self.assertIn("パン 100", (job.path / "ocr.txt").read_text(encoding="utf-8"))

    def test_completed_valid_llm_result_is_published_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            drive = MagicMock()
            drive.list_images.return_value = []
            worker = self._worker(tmp, writer, drive, llm_enabled=True)
            spool = worker._llm_spool
            image = Path(tmp) / "receipt.jpg"
            image.write_bytes(b"image")
            queued = spool.enqueue(
                "file-1", image, "店\n2026/06/28\nパン 100\n合計 100",
                {
                    "shopName": "店", "purchasedAt": "2026-06-28",
                    "totalAmount": 100, "status": "confirmed",
                },
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            running = spool.acquire()
            assert running is not None
            request = running.request
            raw = {
                "schemaVersion": "receipt-llm-result/v1",
                "driveFileId": "file-1",
                "inputSha256": request["inputSha256"],
                "shopName": {"value": "店", "confidence": "high", "evidenceLineNumbers": [1]},
                "purchasedAt": {"value": "2026-06-28", "confidence": "high", "evidenceLineNumbers": [2]},
                "totalAmount": {"value": 100, "confidence": "high", "evidenceLineNumbers": [4]},
                "items": [{
                    "name": "パン", "amount": 100, "kind": "product",
                    "majorCategory": "食費", "minorCategory": "その他",
                    "confidence": "high", "evidenceLineNumbers": [3],
                }],
                "warnings": [],
            }
            spool.complete(running, running.meta, result_text=json.dumps(raw))

            result = worker.run_once()

            self.assertEqual(result["status"], "confirmed")
            writer.publish_llm_result.assert_called_once()
            self.assertIsNone(spool.find(queued.file_id))

    def test_invalid_primary_result_is_requeued_for_retry_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            drive = MagicMock()
            drive.list_images.return_value = []
            worker = self._worker(tmp, writer, drive, llm_enabled=True)
            image = Path(tmp) / "receipt.jpg"
            image.write_bytes(b"image")
            worker._llm_spool.enqueue(
                "file-1", image, "店\n合計 100",
                {"status": "confirmed", "totalAmount": 100},
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            running = worker._llm_spool.acquire()
            assert running is not None
            worker._llm_spool.complete(running, running.meta, result_text="{}")

            result = worker.run_once()

            self.assertEqual(result["status"], "llm_retry_wait")
            retried = worker._llm_spool.find("file-1")
            assert retried is not None
            self.assertEqual(retried.meta["model"], "gpt-5.6-terra")

    def test_spool_failure_uses_validated_rule_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            writer.get_job.return_value = None
            writer.reserve.return_value = MagicMock(reserved=True, reason="reserved")
            writer.list_allowed_categories.return_value = [
                {"major": "食費", "minor": ["その他"]},
            ]
            drive = MagicMock()
            drive.list_images.return_value = [DriveImage("file-1", "receipt.jpg", "image/jpeg", None)]
            drive.download.side_effect = lambda image, target: Path(target).write_bytes(b"x")
            vision = MagicMock()
            vision.document_text.return_value = "店\n2026/06/28\nパン 100\n合計 100"
            worker = self._worker(tmp, writer, drive, vision, llm_enabled=True)
            worker._llm_spool.enqueue = MagicMock(side_effect=OSError("disk full"))

            result = worker.run_once()

            self.assertEqual(result["status"], "confirmed")
            self.assertEqual(result["parseSource"], "rule_fallback")
            writer.publish_llm_result.assert_called_once()
            writer.create_alert.assert_called()

    def test_invalid_retry_result_uses_confirmed_rule_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MagicMock()
            drive = MagicMock()
            drive.list_images.return_value = []
            worker = self._worker(tmp, writer, drive, llm_enabled=True)
            image = Path(tmp) / "receipt.jpg"
            image.write_bytes(b"image")
            worker._llm_spool.enqueue(
                "file-1", image, "店\n2026/06/28\nパン 100\n合計 100",
                {
                    "shopName": "店", "purchasedAt": "2026-06-28",
                    "totalAmount": 100, "payer": "me", "status": "confirmed",
                    "reviewReason": "reconciled", "difference": 0,
                    "reconciledItems": [{
                        "name": "パン", "amount": 100,
                        "category": "食費", "confidence": 0.9,
                    }],
                },
                [{"major": "食費", "minor": ["その他"]}],
                "me", "gpt-5.6-luna",
            )
            primary = worker._llm_spool.acquire()
            assert primary is not None
            completed = worker._llm_spool.complete(primary, primary.meta, result_text="{}")
            worker._llm_spool.retry_with_model(completed, "gpt-5.6-terra")
            retry = worker._llm_spool.acquire()
            assert retry is not None
            worker._llm_spool.complete(retry, retry.meta, result_text="{}")

            result = worker.run_once()

            self.assertEqual(result["status"], "confirmed")
            self.assertEqual(result["parseSource"], "rule_fallback")
            writer.publish_llm_result.assert_called_once()
            self.assertIsNone(worker._llm_spool.find("file-1"))


if __name__ == "__main__":
    unittest.main()
