from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .categorizer import categorize_items
from .drive_api_client import DriveApiClient, DriveImage
from .firestore_writer import FirestoreWriter, create_firestore_writer
from .llm_contract import (
    LlmValidationError,
    PROMPT_VERSION,
    RESULT_SCHEMA_VERSION,
    ValidatedLlmReceipt,
    validate_result,
)
from .llm_spool import LlmSpool, SpoolJob, load_error, load_result
from .llm_worker import LlmWorkerSettings
from .parser import parse_receipt
from .reconciliation import reconcile_receipt
from .source_metadata import resolve_payer
from .vision_client import VisionClient, VisionRequestIndeterminate

NON_PROCESSABLE_JOB_STATUSES = {
    "completed", "confirmed", "needs_review", "vision_reserved",
    "unknown_after_request", "llm_pending", "llm_running",
    "llm_retry_wait", "llm_completed", "auth_blocked",
}


@dataclass(frozen=True)
class PocSettings:
    drive_folder_id: str
    household_id: str
    drive_credential_path: str
    vision_credential_path: str
    firestore_credential_path: str
    work_dir: Path
    max_vision_units: int = 800
    default_payer: str | None = None
    max_images_per_run: int = 4

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "PocSettings":
        poc = config.get("poc", {})

        def required(env: str, key: str) -> str:
            value = os.environ.get(env) or poc.get(key)
            if not value:
                raise ValueError(f"{env} or poc.{key} is required")
            return str(value)

        shared = os.environ.get("POC_SERVICE_ACCOUNT_PATH") or poc.get("service_account_path")
        drive_credential = os.environ.get("POC_DRIVE_SERVICE_ACCOUNT_PATH") or poc.get("drive_service_account_path") or shared
        vision_credential = os.environ.get("POC_VISION_SERVICE_ACCOUNT_PATH") or poc.get("vision_service_account_path") or shared
        firestore_credential = os.environ.get("POC_FIRESTORE_SERVICE_ACCOUNT_PATH") or poc.get("firestore_service_account_path") or shared
        if not all((drive_credential, vision_credential, firestore_credential)):
            raise ValueError("PoC service account paths are required")
        max_units = int(os.environ.get("POC_MAX_VISION_UNITS", poc.get("max_vision_units", 800)))
        if not 1 <= max_units <= 1000:
            raise ValueError("POC_MAX_VISION_UNITS must be between 1 and 1000")
        max_images_per_run = int(os.environ.get("POC_MAX_IMAGES_PER_RUN", poc.get("max_images_per_run", 4)))
        if not 1 <= max_images_per_run <= 10:
            raise ValueError("POC_MAX_IMAGES_PER_RUN must be between 1 and 10")
        return cls(
            drive_folder_id=required("POC_DRIVE_FOLDER_ID", "drive_folder_id"),
            household_id=required("POC_HOUSEHOLD_ID", "household_id"),
            drive_credential_path=str(Path(str(drive_credential)).expanduser()),
            vision_credential_path=str(Path(str(vision_credential)).expanduser()),
            firestore_credential_path=str(Path(str(firestore_credential)).expanduser()),
            work_dir=Path(os.environ.get("POC_WORK_DIR", poc.get("work_dir", "/var/lib/receipt-ocr-poc/work"))).expanduser(),
            max_vision_units=max_units,
            default_payer=os.environ.get("POC_DEFAULT_PAYER") or poc.get("default_payer"),
            max_images_per_run=max_images_per_run,
        )


class CloudWorker:
    def __init__(
        self,
        config: Mapping[str, Any],
        settings: PocSettings,
        drive: DriveApiClient,
        vision: VisionClient,
        writer: FirestoreWriter,
        llm_settings: LlmWorkerSettings | None = None,
        llm_spool: LlmSpool | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._drive = drive
        self._vision = vision
        self._writer = writer
        self._llm_settings = llm_settings or LlmWorkerSettings.from_config(config)
        self._llm_spool = llm_spool or LlmSpool(self._llm_settings.spool_dir)

    def candidates(self) -> list[DriveImage]:
        return self._drive.list_images(self._settings.drive_folder_id)

    def run_once(self, dry_run: bool = False) -> dict[str, Any]:
        """Advance up to ``max_images_per_run`` receipts during one timer run.

        The LLM worker remains intentionally serial, but this worker can enqueue a
        small camera batch in one pass and publish every completed LLM result on
        the next pass.  This avoids adding one five-minute timer interval per
        photo while retaining a bounded Vision request count and runtime.
        """
        if dry_run:
            return self._dry_run_candidate()

        finalized: list[dict[str, Any]] = []
        if self._llm_settings.enabled and not dry_run:
            health_status = self._sync_llm_health()
            self._sync_llm_job_states()
            if health_status == "auth_blocked":
                return {"status": "auth_blocked"}
            for _ in range(self._settings.max_images_per_run):
                result = self._finalize_llm_result()
                if result is None:
                    break
                finalized.append(result)

        processed: list[dict[str, Any]] = []
        for image in self.candidates():
            job = self._writer.get_job(image.file_id)
            if not _is_processable_job(job):
                continue
            processed.append(self._process(image))
            if len(processed) >= self._settings.max_images_per_run:
                break
        return _batch_result(finalized, processed)

    def _dry_run_candidate(self) -> dict[str, Any]:
        for image in self.candidates():
            job = self._writer.get_job(image.file_id)
            if _is_processable_job(job):
                return {"status": "candidate", "driveFileId": image.file_id, "sourceName": image.name}
        return {"status": "idle"}

    def _sync_llm_health(self) -> str | None:
        health = self._llm_spool.read_health()
        if not health:
            return None
        status = str(health.get("status") or "")
        if status == "ok":
            self._writer.resolve_alert("codex_auth_blocked")
            self._writer.resolve_alert("codex_worker_unavailable")
            self._writer.resolve_alert("spool_cleanup_failed")
        elif status == "auth_blocked":
            self._writer.create_alert(
                "codex_auth_blocked", "Codexの再認証が必要です", severity="error"
            )
        elif status == "spool_cleanup_failed":
            self._writer.create_alert(
                "spool_cleanup_failed",
                "LLM一時データの期限切れ削除に失敗しました",
                severity="error",
            )
        elif status:
            self._writer.create_alert(
                "codex_worker_unavailable",
                "Codex workerのhealth checkに失敗しました",
                severity="error",
            )
        return status or None

    def _sync_llm_job_states(self) -> None:
        for job in self._llm_spool.jobs("running"):
            self._writer.mark_llm_state(
                job.file_id,
                "llm_running",
                llmAttempted=True,
                llmAttempts=int(job.meta.get("attempts", 0)),
                llmLastModel=job.meta.get("model"),
            )
        for job in self._llm_spool.jobs("pending"):
            if int(job.meta.get("attempts", 0)) == 0:
                continue
            self._writer.mark_llm_state(
                job.file_id,
                "llm_retry_wait",
                llmAttempted=True,
                llmAttempts=int(job.meta.get("attempts", 0)),
                llmLastModel=job.meta.get("model"),
                llmFailureCode=job.meta.get("lastFailureCode"),
                llmNextAttemptAt=job.meta.get("nextAttemptAt"),
            )

    def _process(self, image: DriveImage) -> dict[str, Any]:
        try:
            payer = resolve_payer(image.name, self._settings.default_payer)
        except Exception as error:
            return {"status": "invalid_source", "driveFileId": image.file_id, "error": str(error)}
        reservation = self._writer.reserve(image.file_id, image.name, payer)
        if not reservation.reserved:
            return {"status": reservation.reason, "driveFileId": image.file_id}

        suffix = Path(image.name).suffix.lower() or ".img"
        target = self._settings.work_dir / f"{image.file_id}{suffix}"
        try:
            self._settings.work_dir.mkdir(parents=True, exist_ok=True)
            self._drive.download(image, target)
            self._writer.mark_vision_started(image.file_id)
            ocr_text = self._vision.document_text(target)
            parsed = parse_receipt(ocr_text, dict(self._config))
            parsed.items = categorize_items(parsed.items, dict(self._config))
            reconciled = reconcile_receipt(
                parsed.shop_name, parsed.purchased_at, parsed.total_amount,
                parsed.items, ocr_text,
            )
            result = {
                "driveFileId": image.file_id,
                "shopName": parsed.shop_name,
                "purchasedAt": parsed.purchased_at,
                "totalAmount": parsed.total_amount,
                "payer": payer,
                "status": reconciled.status,
                "reviewReason": reconciled.reason,
                "difference": reconciled.difference,
                "parsedItems": [_item_payload(item) for item in parsed.items],
                "reconciledItems": [_item_payload(item) for item in reconciled.items],
            }
            if self._llm_settings.enabled:
                try:
                    allowed_categories = self._writer.list_allowed_categories()
                    rule_candidate = dict(result)
                    self._llm_spool.enqueue(
                        image.file_id,
                        target,
                        ocr_text,
                        rule_candidate,
                        list(allowed_categories),
                        payer,
                        self._llm_settings.primary_model,
                        self._llm_settings.deadline_hours,
                    )
                except (OSError, ValueError):
                    return self._publish_direct_rule_fallback(image.file_id, result)
                self._writer.mark_llm_state(
                    image.file_id,
                    "llm_pending",
                    llmAttempted=False,
                    llmAttempts=0,
                    llmPrimaryModel=self._llm_settings.primary_model,
                    llmPromptVersion=PROMPT_VERSION,
                    llmSchemaVersion=RESULT_SCHEMA_VERSION,
                )
                return {"status": "llm_pending", "driveFileId": image.file_id}
            self._writer.complete(image.file_id, result)
            return {"status": reconciled.status, "driveFileId": image.file_id}
        except VisionRequestIndeterminate as error:
            self._writer.mark_unknown(image.file_id, error)
            return {"status": "unknown_after_request", "driveFileId": image.file_id, "error": str(error)}
        except Exception as error:
            self._writer.mark_failed(image.file_id, error)
            return {"status": "failed", "driveFileId": image.file_id, "error": str(error)}
        finally:
            target.unlink(missing_ok=True)

    def _publish_direct_rule_fallback(
        self, file_id: str, candidate: Mapping[str, Any]
    ) -> dict[str, Any]:
        status = "confirmed" if candidate.get("status") == "confirmed" else "needs_review"
        receipt = dict(candidate)
        receipt.update({
            "status": status,
            "reviewReason": (
                candidate.get("reviewReason") if status == "confirmed" else "llm_exhausted"
            ),
        })
        items = [
            _formal_item(item)
            for item in candidate.get("reconciledItems", [])
            if isinstance(item, Mapping)
        ]
        self._writer.publish_llm_result(file_id, receipt, items, {
            "parseSource": "rule_fallback",
            "parserVersion": "rule/v1",
            "llmModel": None,
            "llmPromptVersion": PROMPT_VERSION,
            "llmSchemaVersion": RESULT_SCHEMA_VERSION,
            "llmWarnings": ["spool_unavailable"],
        })
        self._writer.create_alert(
            "codex_worker_unavailable",
            "LLM一時データを作成できないためルール解析を採用しました",
            severity="error",
        )
        if status == "needs_review":
            self._writer.create_alert(
                "llm_exhausted", "LLMとルール解析で自動確定できませんでした",
                file_id, "warning",
            )
        return {"status": status, "driveFileId": file_id, "parseSource": "rule_fallback"}

    def _finalize_llm_result(self) -> dict[str, Any] | None:
        job = self._llm_spool.next_completed()
        if not job:
            return None
        self._writer.mark_llm_state(
            job.file_id,
            "llm_completed",
            llmAttempted=True,
            llmAttempts=int(job.meta.get("attempts", 0)),
            llmLastModel=job.meta.get("model"),
        )
        error = load_error(job)
        if error:
            return self._fallback_from_job(job, str(error.get("code") or "codex_failed"))
        try:
            raw = load_result(job)
            validated = validate_result(raw, job.request)
        except (ValueError, LlmValidationError) as validation_error:
            errors = (
                validation_error.errors
                if isinstance(validation_error, LlmValidationError)
                else [str(validation_error)]
            )
            if job.meta.get("modelStage") != "retry":
                self._llm_spool.retry_with_model(job, self._llm_settings.retry_model)
                self._writer.mark_llm_state(
                    job.file_id,
                    "llm_retry_wait",
                    llmAttempted=True,
                    llmLastModel=job.meta.get("model"),
                    llmFailureCode="validation_failed",
                    llmValidationErrors=list(errors)[:20],
                )
                return {
                    "status": "llm_retry_wait",
                    "driveFileId": job.file_id,
                    "model": self._llm_settings.retry_model,
                }
            return self._fallback_from_job(job, "validation_failed")
        return self._publish_validated(job, validated)

    def _publish_validated(
        self, job: SpoolJob, validated: ValidatedLlmReceipt
    ) -> dict[str, Any]:
        status = "needs_review" if validated.soft_warnings else "confirmed"
        reason = "llm_warning" if validated.soft_warnings else "reconciled"
        items = [
            {
                "name": item.name,
                "amount": item.amount,
                "kind": item.kind,
                "majorCategory": item.major_category,
                "minorCategory": item.minor_category,
                "confidence": item.confidence,
            }
            for item in validated.items
        ]
        confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        receipt = {
            "driveFileId": job.file_id,
            "shopName": validated.shop_name,
            "purchasedAt": validated.purchased_at,
            "totalAmount": validated.total_amount,
            "payer": job.meta.get("payer") or "",
            "status": status,
            "reviewReason": reason,
            "difference": 0,
            "parsedItems": [
                {
                    "name": item["name"],
                    "amount": item["amount"],
                    "category": item["majorCategory"],
                    "minorCategory": item["minorCategory"],
                    "confidence": confidence_map[item["confidence"]],
                }
                for item in items
            ],
            "reconciledItems": [
                {
                    "name": item["name"],
                    "amount": item["amount"],
                    "category": item["majorCategory"],
                    "minorCategory": item["minorCategory"],
                    "confidence": confidence_map[item["confidence"]],
                }
                for item in items
            ],
        }
        audit = {
            "parseSource": "codex",
            "parserVersion": "codex-cli/v1",
            "llmModel": job.meta.get("model"),
            "llmPromptVersion": PROMPT_VERSION,
            "llmSchemaVersion": RESULT_SCHEMA_VERSION,
            "llmWarnings": list(validated.warnings) + list(validated.soft_warnings),
        }
        self._writer.publish_llm_result(job.file_id, receipt, items, audit)
        self._writer.resolve_alert("llm_exhausted", job.file_id)
        self._writer.resolve_alert("codex_rate_limit_over_24h", job.file_id)
        if status == "needs_review":
            self._llm_spool.move_unresolved(job)
        else:
            self._llm_spool.remove(job)
        return {"status": status, "driveFileId": job.file_id, "parseSource": "codex"}

    def _fallback_from_job(self, job: SpoolJob, failure_code: str) -> dict[str, Any]:
        candidate = job.request.get("ruleCandidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("LLM spool has no rule candidate")
        status = str(candidate.get("status") or "needs_review")
        if status != "confirmed":
            status = "needs_review"
        reconciled_items = candidate.get("reconciledItems", [])
        items = [
            _formal_item(item)
            for item in reconciled_items
            if isinstance(item, Mapping)
        ]
        receipt = dict(candidate)
        receipt.update({
            "payer": job.meta.get("payer") or candidate.get("payer") or "",
            "status": status,
            "reviewReason": (
                candidate.get("reviewReason") if status == "confirmed" else "llm_exhausted"
            ),
        })
        audit = {
            "parseSource": "rule_fallback",
            "parserVersion": "rule/v1",
            "llmModel": job.meta.get("model"),
            "llmPromptVersion": PROMPT_VERSION,
            "llmSchemaVersion": RESULT_SCHEMA_VERSION,
            "llmWarnings": [failure_code],
        }
        self._writer.publish_llm_result(job.file_id, receipt, items, audit)
        if failure_code == "auth_blocked":
            self._writer.create_alert(
                "codex_auth_blocked", "Codexの再認証が必要です", severity="error"
            )
        elif failure_code == "rate_limit":
            self._writer.create_alert(
                "codex_rate_limit_over_24h", "Codex利用上限が24時間以上継続しました",
                job.file_id, "warning",
            )
        if status == "needs_review":
            self._writer.create_alert(
                "llm_exhausted", "LLMとルール解析で自動確定できませんでした",
                job.file_id, "warning",
            )
            self._llm_spool.move_unresolved(job)
        else:
            self._llm_spool.remove(job)
        return {"status": status, "driveFileId": job.file_id, "parseSource": "rule_fallback"}


def create_worker(config: Mapping[str, Any]) -> CloudWorker:
    settings = PocSettings.from_config(config)
    llm_settings = LlmWorkerSettings.from_config(config)
    return CloudWorker(
        config,
        settings,
        DriveApiClient.from_service_account(settings.drive_credential_path),
        VisionClient.from_service_account(settings.vision_credential_path),
        create_firestore_writer(
            settings.firestore_credential_path,
            settings.household_id,
            settings.max_vision_units,
        ),
        llm_settings,
        LlmSpool(llm_settings.spool_dir),
    )


def _is_processable_job(job: Mapping[str, Any] | None) -> bool:
    if not job:
        return True
    status = job.get("status")
    return status not in NON_PROCESSABLE_JOB_STATUSES and not (
        status == "failed" and job.get("visionAttempted", False)
    )


def _batch_result(
    finalized: list[dict[str, Any]], processed: list[dict[str, Any]]
) -> dict[str, Any]:
    results = finalized + processed
    if not results:
        return {"status": "idle"}
    if len(results) == 1:
        return results[0]
    return {
        "status": "batch_completed",
        "finalized": finalized,
        "processed": processed,
        "count": len(results),
    }


def _item_payload(item: Any) -> dict[str, Any]:
    return {
        "name": item.name,
        "amount": item.amount,
        "category": item.category,
        "confidence": item.confidence,
    }


def _formal_item(item: Mapping[str, Any]) -> dict[str, Any]:
    category = str(item.get("category") or "未分類")
    if category == "調整":
        name = str(item.get("name") or "")
        minor = "端数" if "端数" in name else "値引き・税"
        major = "調整"
    elif category == "未分類":
        major, minor = "その他", "未分類"
    else:
        major, minor = category, str(item.get("minorCategory") or "その他")
    return {
        "name": str(item.get("name") or ""),
        "amount": int(item.get("amount") or 0),
        "majorCategory": major,
        "minorCategory": minor,
        "confidence": float(item.get("confidence") or 0.0),
    }
