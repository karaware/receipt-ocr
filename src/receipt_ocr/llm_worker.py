from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .llm_contract import build_prompt
from .llm_spool import LlmSpool, SpoolJob


UTC = timezone.utc
TRANSIENT_DELAYS_MINUTES = (5, 30, 120)


@dataclass(frozen=True)
class LlmWorkerSettings:
    enabled: bool
    spool_dir: Path
    codex_bin: str
    schema_path: Path
    primary_model: str
    retry_model: str
    primary_timeout_seconds: int
    retry_timeout_seconds: int
    deadline_hours: int
    unresolved_retention_days: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "LlmWorkerSettings":
        llm = config.get("poc", {}).get("llm", {})
        root = Path(__file__).resolve().parents[2]
        return cls(
            enabled=bool(llm.get("enabled", False)),
            spool_dir=Path(str(llm.get(
                "spool_dir", "/var/lib/receipt-ocr-poc/llm-spool"
            ))).expanduser(),
            codex_bin=str(llm.get(
                "codex_bin", "/var/lib/receipt-ocr-codex/.local/bin/codex"
            )),
            schema_path=Path(str(llm.get(
                "schema_path", root / "schema" / "receipt-llm-result-v1.json"
            ))).expanduser(),
            primary_model=str(llm.get("primary_model", "gpt-5.6-luna")),
            retry_model=str(llm.get("retry_model", "gpt-5.6-terra")),
            primary_timeout_seconds=int(llm.get("primary_timeout_seconds", 180)),
            retry_timeout_seconds=int(llm.get("retry_timeout_seconds", 240)),
            deadline_hours=int(llm.get("deadline_hours", 24)),
            unresolved_retention_days=int(llm.get("unresolved_retention_days", 7)),
        )


class LlmWorker:
    def __init__(self, settings: LlmWorkerSettings, spool: LlmSpool | None = None) -> None:
        self.settings = settings
        self.spool = spool or LlmSpool(settings.spool_dir)

    def run_once(self, dry_run: bool = False) -> dict[str, Any]:
        try:
            self._preflight()
        except RuntimeError as error:
            if not self.settings.enabled:
                raise
            status = "auth_blocked" if "auth" in str(error).lower() else "worker_unavailable"
            self.spool.write_health(status)
            return {"status": status}
        self.spool.recover_expired_leases()
        try:
            self.spool.cleanup(self.settings.unresolved_retention_days)
        except (OSError, ValueError):
            self.spool.write_health("spool_cleanup_failed")
            return {"status": "spool_cleanup_failed"}
        if dry_run:
            return self.status()
        health = self.spool.read_health()
        if health and health.get("status") == "auth_blocked":
            return {"status": "auth_blocked"}
        job = self.spool.acquire()
        if not job:
            return {"status": "idle"}
        return self._run(job)

    def _run(self, job: SpoolJob) -> dict[str, Any]:
        meta = dict(job.meta)
        meta["attempts"] = int(meta.get("attempts", 0)) + 1
        meta["lastAttemptAt"] = _iso(datetime.now(UTC))
        model = str(meta.get("model") or self.settings.primary_model)
        timeout = (
            self.settings.retry_timeout_seconds
            if meta.get("modelStage") == "retry"
            else self.settings.primary_timeout_seconds
        )
        result_path = job.path / "result.json"
        result_path.unlink(missing_ok=True)
        command = [
            self.settings.codex_bin,
            "--ask-for-approval", "never",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--cd", str(job.path),
            "--model", model,
            "--image", str(job.image_path),
            "--output-schema", str(self.settings.schema_path),
            "--output-last-message", str(result_path),
            "--json",
            "-",
        ]
        try:
            result = subprocess.run(
                command,
                input=build_prompt(job.request),
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=_safe_environment(),
            )
        except subprocess.TimeoutExpired as error:
            return self._handle_failure(job, meta, "timeout", str(error))
        except OSError as error:
            return self._handle_failure(job, meta, "worker_unavailable", str(error), terminal=True)

        if result.returncode == 0 and result_path.is_file():
            text = result_path.read_text(encoding="utf-8")
            self.spool.complete(job, meta, result_text=text, events_text=result.stdout)
            self.spool.write_health("ok")
            return {"status": "llm_completed", "driveFileId": job.file_id, "model": model}

        code = _failure_code(result.stdout, result.stderr)
        detail = (result.stderr or result.stdout or f"codex exited {result.returncode}")[-2000:]
        return self._handle_failure(
            job, meta, code, detail,
            terminal=code in {"auth_blocked", "worker_unavailable"},
        )

    def _handle_failure(
        self,
        job: SpoolJob,
        meta: dict[str, Any],
        code: str,
        detail: str,
        terminal: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        deadline = _parse(str(meta.get("deadlineAt")))
        if code == "rate_limit":
            next_attempt = now + timedelta(hours=5)
            if next_attempt < deadline and not terminal:
                meta.update({"nextAttemptAt": _iso(next_attempt), "lastFailureCode": code})
                self.spool.requeue(job, meta)
                return {"status": "llm_retry_wait", "driveFileId": job.file_id, "failureCode": code}
        elif code in {"timeout", "network", "server_error"}:
            attempt = int(meta.get("transientAttempts", 0))
            if attempt < len(TRANSIENT_DELAYS_MINUTES) and now < deadline and not terminal:
                delay = TRANSIENT_DELAYS_MINUTES[attempt]
                meta.update({
                    "transientAttempts": attempt + 1,
                    "nextAttemptAt": _iso(now + timedelta(minutes=delay)),
                    "lastFailureCode": code,
                })
                self.spool.requeue(job, meta)
                return {"status": "llm_retry_wait", "driveFileId": job.file_id, "failureCode": code}

        error = {"code": code, "detail": _sanitize_detail(detail), "terminal": True}
        self.spool.complete(job, meta, error=error)
        if code in {"auth_blocked", "worker_unavailable"}:
            self.spool.write_health(code)
        return {"status": code, "driveFileId": job.file_id}

    def auth_status(self) -> dict[str, Any]:
        self._preflight(check_schema=False)
        result = subprocess.run(
            [self.settings.codex_bin, "login", "status"],
            text=True, capture_output=True, check=False, timeout=30,
            env=_safe_environment(),
        )
        text = (result.stdout + "\n" + result.stderr).strip()
        return {
            "status": "authenticated" if result.returncode == 0 else "auth_blocked",
            "chatgpt": "chatgpt" in text.lower(),
        }

    def health_check(self) -> dict[str, Any]:
        try:
            self._preflight(check_schema=False)
        except RuntimeError as error:
            status = "auth_blocked" if "auth" in str(error).lower() else "worker_unavailable"
            self.spool.write_health(status)
            return {"status": status}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.txt"
            try:
                result = subprocess.run(
                    [
                        self.settings.codex_bin, "--ask-for-approval", "never",
                        "exec", "--ephemeral", "--ignore-user-config",
                        "--sandbox", "read-only",
                        "--skip-git-repo-check", "--cd", temporary,
                        "--model", self.settings.primary_model,
                        "--output-last-message", str(output), "Reply with the single word OK.",
                    ],
                    text=True, capture_output=True, check=False,
                    timeout=self.settings.primary_timeout_seconds,
                    env=_safe_environment(),
                )
                ok = (
                    result.returncode == 0
                    and output.is_file()
                    and output.read_text(encoding="utf-8").strip() == "OK"
                )
                status = "ok" if ok else _failure_code(result.stdout, result.stderr)
            except subprocess.TimeoutExpired:
                status = "timeout"
            except OSError:
                status = "worker_unavailable"
            self.spool.write_health(status)
            return {"status": status}

    def cleanup(self) -> dict[str, Any]:
        removed = self.spool.cleanup(self.settings.unresolved_retention_days)
        return {"status": "cleaned", "removed": removed}

    def status(self) -> dict[str, Any]:
        self.spool.ensure_dirs()
        return {
            "status": "ready",
            "pending": _count_dirs(self.spool.pending),
            "running": _count_dirs(self.spool.running),
            "completed": _count_dirs(self.spool.completed),
            "unresolved": _count_dirs(self.spool.unresolved),
        }

    def _preflight(self, check_schema: bool = True) -> None:
        if not self.settings.enabled:
            raise RuntimeError("poc.llm.enabled is false")
        if os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY"):
            raise RuntimeError("API key authentication is forbidden for the Plus-only LLM worker")
        codex_home_value = os.environ.get("CODEX_HOME")
        codex_home = (
            Path(codex_home_value).expanduser()
            if codex_home_value
            else Path(os.environ.get("HOME", "~")).expanduser() / ".codex"
        )
        auth_path = codex_home / "auth.json"
        if auth_path.is_file():
            try:
                auth = json.loads(auth_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("Codex auth.json cannot be validated") from error
            if not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt":
                raise RuntimeError(
                    "Codex must use ChatGPT authentication; API authentication is forbidden"
                )
            tokens = auth.get("tokens")
            if not isinstance(tokens, dict) or not tokens.get("refresh_token"):
                raise RuntimeError("Codex ChatGPT authentication has no refresh token")
            auth_stat = auth_path.stat()
            if stat.S_IMODE(auth_stat.st_mode) & 0o077:
                raise RuntimeError("Codex auth.json permissions must be 0600")
            if hasattr(os, "geteuid") and auth_stat.st_uid != os.geteuid():
                raise RuntimeError("Codex auth.json must be owned by the worker user")
        if not Path(self.settings.codex_bin).is_file():
            raise RuntimeError(f"Codex binary not found: {self.settings.codex_bin}")
        if check_schema and not self.settings.schema_path.is_file():
            raise RuntimeError(f"LLM output schema not found: {self.settings.schema_path}")


def _safe_environment() -> dict[str, str]:
    allowed = {
        "HOME", "CODEX_HOME", "PATH", "LANG", "LC_ALL", "SSL_CERT_FILE",
        "CODEX_CA_CERTIFICATE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _failure_code(stdout: str, stderr: str) -> str:
    text = (stdout + "\n" + stderr).lower()
    if any(value in text for value in ("401", "unauthorized", "login required", "not logged in", "refresh token")):
        return "auth_blocked"
    if any(value in text for value in ("rate limit", "usage limit", "too many requests", "429")):
        return "rate_limit"
    if any(value in text for value in ("timed out", "timeout")):
        return "timeout"
    if any(value in text for value in ("connection", "network", "dns", "resolve host")):
        return "network"
    if any(value in text for value in ("500", "502", "503", "504", "server error")):
        return "server_error"
    return "codex_failed"


def _sanitize_detail(value: str) -> str:
    # Keep diagnostics bounded without persisting prompts, OCR, or bearer tokens.
    lowered = value.lower()
    if "bearer " in lowered or "refresh_token" in lowered or "access_token" in lowered:
        return "Codex authentication failed; sensitive detail omitted"
    return " ".join(value.split())[:500]


def _count_dirs(path: Path) -> int:
    return sum(1 for item in path.iterdir() if item.is_dir() and not item.is_symlink())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
