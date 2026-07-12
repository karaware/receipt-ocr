from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .categorizer import categorize_items
from .drive_api_client import DriveApiClient, DriveImage
from .firestore_writer import FirestoreWriter, create_firestore_writer
from .parser import parse_receipt
from .reconciliation import reconcile_receipt
from .source_metadata import resolve_payer
from .vision_client import VisionClient, VisionRequestIndeterminate


@dataclass(frozen=True)
class PocSettings:
    drive_folder_id: str
    household_id: str
    drive_credential_path: str
    vision_credential_path: str
    firestore_credential_path: str
    work_dir: Path
    max_vision_units: int = 20
    default_payer: str | None = None

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
        max_units = int(os.environ.get("POC_MAX_VISION_UNITS", poc.get("max_vision_units", 20)))
        if not 1 <= max_units <= 20:
            raise ValueError("POC_MAX_VISION_UNITS must be between 1 and 20")
        return cls(
            drive_folder_id=required("POC_DRIVE_FOLDER_ID", "drive_folder_id"),
            household_id=required("POC_HOUSEHOLD_ID", "household_id"),
            drive_credential_path=str(Path(str(drive_credential)).expanduser()),
            vision_credential_path=str(Path(str(vision_credential)).expanduser()),
            firestore_credential_path=str(Path(str(firestore_credential)).expanduser()),
            work_dir=Path(os.environ.get("POC_WORK_DIR", poc.get("work_dir", "/var/lib/receipt-ocr-poc/work"))).expanduser(),
            max_vision_units=max_units,
            default_payer=os.environ.get("POC_DEFAULT_PAYER") or poc.get("default_payer"),
        )


class CloudWorker:
    def __init__(
        self,
        config: Mapping[str, Any],
        settings: PocSettings,
        drive: DriveApiClient,
        vision: VisionClient,
        writer: FirestoreWriter,
    ) -> None:
        self._config = config
        self._settings = settings
        self._drive = drive
        self._vision = vision
        self._writer = writer

    def candidates(self) -> list[DriveImage]:
        return self._drive.list_images(self._settings.drive_folder_id)

    def run_once(self, dry_run: bool = False) -> dict[str, Any]:
        for image in self.candidates():
            job = self._writer.get_job(image.file_id)
            if job:
                status = job.get("status")
                if status in {"completed", "confirmed", "needs_review", "vision_reserved", "unknown_after_request"}:
                    continue
                if status == "failed" and job.get("visionAttempted", False):
                    continue
            if dry_run:
                return {"status": "candidate", "driveFileId": image.file_id, "sourceName": image.name}
            return self._process(image)
        return {"status": "idle"}

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


def create_worker(config: Mapping[str, Any]) -> CloudWorker:
    settings = PocSettings.from_config(config)
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
    )


def _item_payload(item: Any) -> dict[str, Any]:
    return {
        "name": item.name,
        "amount": item.amount,
        "category": item.category,
        "confidence": item.confidence,
    }
