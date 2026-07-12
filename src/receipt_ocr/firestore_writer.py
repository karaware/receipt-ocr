from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


TERMINAL_STATUSES = {"completed", "confirmed", "needs_review", "unknown_after_request"}


@dataclass(frozen=True)
class Reservation:
    reserved: bool
    reason: str


def reservation_decision(
    job: Mapping[str, Any], usage_count: int, max_units: int
) -> tuple[Reservation, bool]:
    """Return the atomic reservation result and whether usage must increase."""
    status = job.get("status")
    if status in TERMINAL_STATUSES or status == "vision_reserved":
        return Reservation(False, str(status)), False
    reuse = status == "failed" and not job.get("visionAttempted", False)
    if not reuse and usage_count >= max_units:
        return Reservation(False, "limit_reached"), False
    return Reservation(True, "reserved"), not reuse


class FirestoreWriter:
    def __init__(self, db: Any, household_id: str, max_units: int = 20) -> None:
        self._db = db
        self._base = db.collection("households").document(household_id)
        self._max_units = max_units

    def get_job(self, file_id: str) -> Mapping[str, Any] | None:
        snapshot = self._jobs.document(file_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def reserve(self, file_id: str, source_name: str, payer: str) -> Reservation:
        from firebase_admin import firestore

        job_ref = self._jobs.document(file_id)
        month_ref = self._usage.document(datetime.now(timezone.utc).strftime("%Y-%m"))
        total_ref = self._usage.document("_total")
        transaction = self._db.transaction()

        @firestore.transactional
        def apply(transaction: Any) -> Reservation:
            job_snapshot = job_ref.get(transaction=transaction)
            job = job_snapshot.to_dict() if job_snapshot.exists else {}
            month_snapshot = month_ref.get(transaction=transaction)
            total_snapshot = total_ref.get(transaction=transaction)
            month_count = int((month_snapshot.to_dict() or {}).get("units", 0)) if month_snapshot.exists else 0
            total_count = int((total_snapshot.to_dict() or {}).get("units", 0)) if total_snapshot.exists else 0
            decision, increment = reservation_decision(job, total_count, self._max_units)
            if not decision.reserved:
                return decision

            now = firestore.SERVER_TIMESTAMP
            if increment:
                transaction.set(month_ref, {"units": month_count + 1, "updatedAt": now}, merge=True)
                transaction.set(total_ref, {"units": total_count + 1, "updatedAt": now}, merge=True)
            transaction.set(job_ref, {
                "status": "vision_reserved", "driveFileId": file_id,
                "sourceName": source_name, "payer": payer,
                "visionUnits": int(job.get("visionUnits", 0)) + (1 if increment else 0),
                "visionAttempted": False, "error": None,
                "createdAt": job.get("createdAt", now), "updatedAt": now,
            }, merge=True)
            return decision

        return apply(transaction)

    def mark_vision_started(self, file_id: str) -> None:
        self._jobs.document(file_id).update({
            # Persist the ambiguous state before making the external call. A VM
            # crash during the request therefore cannot trigger a duplicate OCR.
            "status": "unknown_after_request",
            "visionAttempted": True,
            "updatedAt": _server_timestamp(),
        })

    def complete(self, file_id: str, result: Mapping[str, Any]) -> None:
        batch = self._db.batch()
        payload = dict(result)
        payload.update({"createdAt": _server_timestamp(), "updatedAt": _server_timestamp()})
        batch.set(self._receipts.document(file_id), payload, merge=False)
        batch.update(self._jobs.document(file_id), {
            "status": result["status"], "error": None, "updatedAt": _server_timestamp()
        })
        batch.commit()

    def mark_unknown(self, file_id: str, error: Exception) -> None:
        self._set_failure(file_id, "unknown_after_request", error)

    def mark_failed(self, file_id: str, error: Exception) -> None:
        self._set_failure(file_id, "failed", error)

    def retry_unknown(self, file_id: str) -> bool:
        ref = self._jobs.document(file_id)
        snapshot = ref.get()
        job = snapshot.to_dict() if snapshot.exists else {}
        retryable = job.get("status") == "unknown_after_request" or (
            job.get("status") == "vision_reserved" and not job.get("visionAttempted", False)
        )
        if not retryable:
            return False
        ref.update({"status": "discovered", "error": None, "updatedAt": _server_timestamp()})
        return True

    def list_jobs(self, limit: int = 50) -> list[Mapping[str, Any]]:
        return [doc.to_dict() for doc in self._jobs.order_by("updatedAt", direction="DESCENDING").limit(limit).stream()]

    def _set_failure(self, file_id: str, status: str, error: Exception) -> None:
        self._jobs.document(file_id).update({
            "status": status, "error": str(error)[:500], "updatedAt": _server_timestamp()
        })

    @property
    def _jobs(self) -> Any:
        return self._base.collection("poc_ocr_jobs")

    @property
    def _receipts(self) -> Any:
        return self._base.collection("poc_receipts")

    @property
    def _usage(self) -> Any:
        return self._base.collection("poc_ocr_usage")


def create_firestore_writer(credential_path: str, household_id: str, max_units: int = 20) -> FirestoreWriter:
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as error:
        raise RuntimeError("Install firebase-admin to use the PoC worker") from error
    app_name = "receipt-ocr-poc"
    try:
        app = firebase_admin.get_app(app_name)
    except ValueError:
        app = firebase_admin.initialize_app(
            credentials.Certificate(str(Path(credential_path).expanduser())), name=app_name
        )
    return FirestoreWriter(firestore.client(app=app), household_id, max_units)


def _server_timestamp() -> Any:
    from firebase_admin import firestore
    return firestore.SERVER_TIMESTAMP
