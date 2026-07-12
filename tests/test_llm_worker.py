import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from receipt_ocr.llm_spool import LlmSpool, load_error
from receipt_ocr.llm_worker import LlmWorker, LlmWorkerSettings


class LlmWorkerTest(unittest.TestCase):
    def _worker(self, root: Path):
        codex = root / "codex"
        codex.write_text("binary", encoding="utf-8")
        schema = root / "schema.json"
        schema.write_text("{}", encoding="utf-8")
        settings = LlmWorkerSettings(
            True, root / "spool", str(codex), schema,
            "gpt-5.6-luna", "gpt-5.6-terra", 30, 30, 24, 7,
        )
        spool = LlmSpool(settings.spool_dir)
        image = root / "receipt.jpg"
        image.write_bytes(b"image")
        spool.enqueue(
            "file-1", image, "店\n合計 100", {},
            [{"major": "食費", "minor": ["その他"]}],
            "me", settings.primary_model,
        )
        return LlmWorker(settings, spool), spool

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_success_moves_job_to_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, spool = self._worker(Path(tmp))

            def run(command, **kwargs):
                self.assertLess(command.index("--ask-for-approval"), command.index("exec"))
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text(json.dumps({"ok": True}), encoding="utf-8")
                return MagicMock(returncode=0, stdout='{"type":"turn.completed"}', stderr="")

            with patch("receipt_ocr.llm_worker.subprocess.run", side_effect=run):
                result = worker.run_once()
            self.assertEqual(result["status"], "llm_completed")
            self.assertEqual(spool.next_completed().file_id, "file-1")

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_auth_failure_is_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, spool = self._worker(Path(tmp))
            failure = MagicMock(returncode=1, stdout="", stderr="401 unauthorized")
            with patch("receipt_ocr.llm_worker.subprocess.run", return_value=failure):
                result = worker.run_once()
            self.assertEqual(result["status"], "auth_blocked")
            self.assertEqual(spool.read_health()["status"], "auth_blocked")
            completed = spool.next_completed()
            assert completed is not None
            self.assertEqual(load_error(completed)["code"], "auth_blocked")

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_health_check_publishes_status_to_spool(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, spool = self._worker(Path(tmp))

            def run(command, **kwargs):
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text("OK\n", encoding="utf-8")
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("receipt_ocr.llm_worker.subprocess.run", side_effect=run):
                self.assertEqual(worker.health_check()["status"], "ok")
            self.assertEqual(spool.read_health()["status"], "ok")

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_rejects_non_chatgpt_auth_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker, _ = self._worker(root)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            auth = codex_home / "auth.json"
            auth.write_text(json.dumps({"auth_mode": "apikey"}), encoding="utf-8")
            auth.chmod(0o600)
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                self.assertEqual(worker.run_once()["status"], "auth_blocked")

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_timeout_is_requeued_with_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, spool = self._worker(Path(tmp))
            with patch(
                "receipt_ocr.llm_worker.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["codex"], 30),
            ):
                result = worker.run_once()
            self.assertEqual(result["status"], "llm_retry_wait")
            queued = spool.find("file-1")
            assert queued is not None
            self.assertEqual(queued.meta["transientAttempts"], 1)

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_rate_limit_is_requeued_without_api_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, spool = self._worker(Path(tmp))
            failure = MagicMock(returncode=1, stdout="", stderr="429 usage limit")
            with patch("receipt_ocr.llm_worker.subprocess.run", return_value=failure):
                result = worker.run_once()
            self.assertEqual(result["status"], "llm_retry_wait")
            self.assertEqual(spool.find("file-1").meta["lastFailureCode"], "rate_limit")


if __name__ == "__main__":
    unittest.main()
