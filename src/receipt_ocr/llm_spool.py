from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .llm_contract import FILE_ID_RE, build_input


UTC = timezone.utc
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_OCR_BYTES = 1024 * 1024
MAX_RULE_BYTES = 256 * 1024
MAX_CATEGORY_GROUPS = 200


@dataclass(frozen=True)
class SpoolJob:
    path: Path
    meta: dict[str, Any]

    @property
    def file_id(self) -> str:
        return str(self.meta["driveFileId"])

    @property
    def request(self) -> dict[str, Any]:
        value = self.meta.get("request")
        if not isinstance(value, dict):
            raise ValueError("Spool job has no request")
        return value

    @property
    def image_path(self) -> Path:
        name = str(self.meta.get("imageName", ""))
        candidate = self.path / name
        if not name or candidate.parent != self.path or not candidate.is_file() or candidate.is_symlink():
            raise ValueError("Spool image is missing or unsafe")
        return candidate


class LlmSpool:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pending = root / "pending"
        self.running = root / "running"
        self.completed = root / "completed"
        self.unresolved = root / "unresolved"

    def ensure_dirs(self) -> None:
        for path in (self.pending, self.running, self.completed, self.unresolved):
            path.mkdir(parents=True, exist_ok=True, mode=0o770)

    def enqueue(
        self,
        file_id: str,
        image_path: Path,
        ocr_text: str,
        rule_candidate: Mapping[str, Any],
        allowed_categories: list[Mapping[str, Any]],
        payer: str,
        primary_model: str,
        deadline_hours: int = 24,
    ) -> SpoolJob:
        self.ensure_dirs()
        _validate_file_id(file_id)
        if not 1 <= deadline_hours <= 168:
            raise ValueError("deadline_hours must be between 1 and 168")
        if not image_path.is_file() or image_path.is_symlink():
            raise ValueError("Receipt image is missing or unsafe")
        if image_path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("Receipt image is too large")
        if len(ocr_text.encode("utf-8")) > MAX_OCR_BYTES:
            raise ValueError("OCR text is too large")
        if len(allowed_categories) > MAX_CATEGORY_GROUPS:
            raise ValueError("Too many allowed category groups")
        if len(json.dumps(rule_candidate, ensure_ascii=False).encode("utf-8")) > MAX_RULE_BYTES:
            raise ValueError("Rule candidate is too large")
        existing = self.find(file_id)
        if existing:
            return existing
        image_hash = _file_sha256(image_path)
        request = build_input(file_id, ocr_text, rule_candidate, allowed_categories, image_hash)
        created = _now()
        suffix = image_path.suffix.lower() or ".img"
        image_name = f"source{suffix}"
        meta = {
            "schemaVersion": "receipt-llm-job/v1",
            "driveFileId": file_id,
            "payer": payer,
            "createdAt": created,
            "deadlineAt": _iso(_parse(created) + timedelta(hours=deadline_hours)),
            "nextAttemptAt": created,
            "attempts": 0,
            "transientAttempts": 0,
            "modelStage": "primary",
            "model": primary_model,
            "imageName": image_name,
            "request": request,
        }
        temporary = Path(tempfile.mkdtemp(prefix=f".{file_id}-", dir=self.pending))
        try:
            # mkdtemp defaults to 0700. The producer and isolated Codex worker
            # are different users, so preserve the parent's setgid group and
            # make the job traversable by that shared group before publishing it.
            os.chmod(temporary, 0o2770)
            shutil.copyfile(image_path, temporary / image_name, follow_symlinks=False)
            (temporary / "ocr.txt").write_text(ocr_text, encoding="utf-8")
            _write_json(temporary / "job.json", meta)
            os.chmod(temporary / image_name, 0o660)
            os.chmod(temporary / "ocr.txt", 0o660)
            os.chmod(temporary / "job.json", 0o660)
            target = self.pending / file_id
            temporary.rename(target)
            return SpoolJob(target, meta)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def acquire(self, now: datetime | None = None) -> SpoolJob | None:
        self.ensure_dirs()
        current = now or datetime.now(UTC)
        for path in sorted(self.pending.iterdir()):
            if not path.is_dir() or path.is_symlink() or not FILE_ID_RE.fullmatch(path.name):
                continue
            meta = _read_json(path / "job.json")
            if _parse(str(meta.get("nextAttemptAt"))) > current:
                continue
            target = self.running / path.name
            try:
                path.rename(target)
            except FileNotFoundError:
                continue
            meta["leaseStartedAt"] = _iso(current)
            _write_json(target / "job.json", meta)
            return SpoolJob(target, meta)
        return None

    def requeue(self, job: SpoolJob, meta: Mapping[str, Any]) -> SpoolJob:
        updated = dict(meta)
        updated.pop("leaseStartedAt", None)
        _remove_outputs(job.path)
        _write_json(job.path / "job.json", updated)
        target = self.pending / job.file_id
        job.path.rename(target)
        return SpoolJob(target, updated)

    def complete(
        self,
        job: SpoolJob,
        meta: Mapping[str, Any],
        result_text: str | None = None,
        events_text: str | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> SpoolJob:
        updated = dict(meta)
        updated.pop("leaseStartedAt", None)
        updated["completedAt"] = _now()
        if result_text is not None:
            (job.path / "result.json").write_text(result_text, encoding="utf-8")
            os.chmod(job.path / "result.json", 0o660)
        if events_text:
            (job.path / "events.jsonl").write_text(events_text[-131072:], encoding="utf-8")
            os.chmod(job.path / "events.jsonl", 0o660)
        if error is not None:
            _write_json(job.path / "error.json", dict(error))
        _write_json(job.path / "job.json", updated)
        target = self.completed / job.file_id
        job.path.rename(target)
        return SpoolJob(target, updated)

    def next_completed(self) -> SpoolJob | None:
        self.ensure_dirs()
        for path in sorted(self.completed.iterdir()):
            if path.is_dir() and not path.is_symlink() and FILE_ID_RE.fullmatch(path.name):
                return SpoolJob(path, _read_json(path / "job.json"))
        return None

    def jobs(self, state: str) -> list[SpoolJob]:
        parents = {
            "pending": self.pending,
            "running": self.running,
            "completed": self.completed,
            "unresolved": self.unresolved,
        }
        if state not in parents:
            raise ValueError("Unknown spool state")
        self.ensure_dirs()
        jobs: list[SpoolJob] = []
        for path in sorted(parents[state].iterdir()):
            if not path.is_dir() or path.is_symlink() or not FILE_ID_RE.fullmatch(path.name):
                continue
            try:
                jobs.append(SpoolJob(path, _read_json(path / "job.json")))
            except ValueError:
                # Another service may have atomically moved it between the
                # directory scan and metadata read. Preserve real corruption.
                if not path.exists():
                    continue
                raise
        return jobs

    def retry_with_model(self, job: SpoolJob, model: str) -> SpoolJob:
        meta = dict(job.meta)
        meta.update({
            "modelStage": "retry",
            "model": model,
            "nextAttemptAt": _now(),
            "lastValidationErrors": [],
        })
        _remove_outputs(job.path)
        _write_json(job.path / "job.json", meta)
        target = self.pending / job.file_id
        job.path.rename(target)
        return SpoolJob(target, meta)

    def move_unresolved(self, job: SpoolJob) -> SpoolJob:
        target = self.unresolved / job.file_id
        if target.exists():
            shutil.rmtree(target)
        job.path.rename(target)
        return SpoolJob(target, job.meta)

    def remove(self, job: SpoolJob) -> None:
        if job.path.parent not in {self.pending, self.running, self.completed, self.unresolved}:
            raise ValueError("Refusing to remove a path outside the spool")
        shutil.rmtree(job.path)

    def find(self, file_id: str) -> SpoolJob | None:
        _validate_file_id(file_id)
        for parent in (self.pending, self.running, self.completed, self.unresolved):
            path = parent / file_id
            if path.is_dir() and not path.is_symlink():
                return SpoolJob(path, _read_json(path / "job.json"))
        return None

    def recover_expired_leases(self, minutes: int = 15) -> int:
        self.ensure_dirs()
        threshold = datetime.now(UTC) - timedelta(minutes=minutes)
        recovered = 0
        for path in list(self.running.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            meta = _read_json(path / "job.json")
            started = meta.get("leaseStartedAt")
            if not started or _parse(str(started)) > threshold:
                continue
            self.requeue(SpoolJob(path, meta), meta)
            recovered += 1
        return recovered

    def cleanup(self, unresolved_days: int = 7) -> int:
        self.ensure_dirs()
        threshold = datetime.now(UTC) - timedelta(days=unresolved_days)
        removed = 0
        for path in list(self.unresolved.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            meta = _read_json(path / "job.json")
            stamp = meta.get("completedAt") or meta.get("createdAt")
            if stamp and _parse(str(stamp)) <= threshold:
                shutil.rmtree(path)
                removed += 1
        return removed

    def write_health(self, status: str) -> None:
        self.ensure_dirs()
        _write_json(self.root / "health.json", {
            "status": status,
            "checkedAt": _now(),
        })

    def read_health(self) -> Mapping[str, Any] | None:
        path = self.root / "health.json"
        return _read_json(path) if path.is_file() and not path.is_symlink() else None


def load_result(job: SpoolJob, max_bytes: int = 65536) -> Mapping[str, Any]:
    path = job.path / "result.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
        raise ValueError("LLM result is missing or too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("LLM result must be a JSON object")
    return value


def load_error(job: SpoolJob) -> Mapping[str, Any] | None:
    path = job.path / "error.json"
    return _read_json(path) if path.is_file() and not path.is_symlink() else None


def _validate_file_id(file_id: str) -> None:
    if not FILE_ID_RE.fullmatch(file_id):
        raise ValueError("Unsupported drive file ID")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o660)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Unsafe or missing spool file: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object in {path.name}")
    return value


def _remove_outputs(path: Path) -> None:
    for name in ("result.json", "events.jsonl", "error.json"):
        (path / name).unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return _iso(datetime.now(UTC))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
