from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


TERMINAL_STATUSES = {
    "completed", "confirmed", "needs_review", "unknown_after_request",
    "llm_pending", "llm_running", "llm_retry_wait", "llm_completed", "auth_blocked",
}


@dataclass(frozen=True)
class Reservation:
    reserved: bool
    reason: str


def reservation_decision(
    job: Mapping[str, Any], monthly_usage_count: int, max_monthly_units: int
) -> tuple[Reservation, bool]:
    """Return the monthly reservation result and whether usage must increase."""
    status = job.get("status")
    if status in TERMINAL_STATUSES or status == "vision_reserved":
        return Reservation(False, str(status)), False
    reuse = status == "failed" and not job.get("visionAttempted", False)
    if not reuse and monthly_usage_count >= max_monthly_units:
        return Reservation(False, "limit_reached"), False
    return Reservation(True, "reserved"), not reuse


class FirestoreWriter:
    def __init__(self, db: Any, household_id: str, max_units: int = 800) -> None:
        self._db = db
        self._base = db.collection("households").document(household_id)
        self._max_units = max_units

    def get_job(self, file_id: str) -> Mapping[str, Any] | None:
        snapshot = self._jobs.document(file_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def get_receipt(self, file_id: str) -> Mapping[str, Any] | None:
        snapshot = self._receipts.document(file_id).get()
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
            # Google Cloud Vision's free allocation is monthly.  Keep _total as
            # lifetime telemetry, but only the YYYY-MM document gates new OCR.
            decision, increment = reservation_decision(job, month_count, self._max_units)
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

    def mark_llm_state(
        self, file_id: str, status: str, **fields: Any
    ) -> None:
        payload = {"status": status, "updatedAt": _server_timestamp()}
        payload.update(fields)
        self._jobs.document(file_id).update(payload)

    def list_allowed_categories(self) -> list[Mapping[str, Any]]:
        values: list[Mapping[str, Any]] = []
        for document in self._base.collection("categories").stream():
            data = document.to_dict() or {}
            if data.get("type") != "expense" or not data.get("name"):
                continue
            minors = [str(value) for value in data.get("subcategories", []) if value]
            values.append({"major": str(data["name"]), "minor": minors or ["その他"]})
        if not any(value["major"] == "調整" for value in values):
            values.append({"major": "調整", "minor": ["値引き・税", "端数", "その他"]})
        if not any(value["major"] == "その他" for value in values):
            values.append({"major": "その他", "minor": ["未分類", "その他"]})
        return sorted(values, key=lambda value: str(value["major"]))

    def publish_llm_result(
        self,
        file_id: str,
        receipt: Mapping[str, Any],
        items: list[Mapping[str, Any]],
        audit: Mapping[str, Any],
    ) -> None:
        if len(items) > 200:
            raise ValueError("A receipt cannot contain more than 200 LLM items")
        from firebase_admin import firestore

        receipt_ref = self._base.collection("receipts").document(file_id)
        poc_ref = self._receipts.document(file_id)
        job_ref = self._jobs.document(file_id)
        batch = self._db.batch()
        now = firestore.SERVER_TIMESTAMP
        exists = receipt_ref.get().exists
        status = str(receipt["status"])
        if not exists:
            batch.create(receipt_ref, {
                "shopName": receipt.get("shopName") or "",
                "purchasedAt": receipt.get("purchasedAt") or "",
                "totalAmount": int(receipt.get("totalAmount") or 0),
                "payer": receipt.get("payer") or "",
                "status": status,
                "reviewReason": receipt.get("reviewReason") or "reconciled",
                "difference": receipt.get("difference"),
                "sourceId": file_id,
                "source": "ocr",
                "parseSource": audit.get("parseSource"),
                "parserVersion": audit.get("parserVersion"),
                "llmModel": audit.get("llmModel"),
                "llmPromptVersion": audit.get("llmPromptVersion"),
                "llmSchemaVersion": audit.get("llmSchemaVersion"),
                "llmWarnings": list(audit.get("llmWarnings", [])),
                "createdAt": now,
                "updatedAt": now,
            })
            for index, item in enumerate(items):
                ref = self._base.collection("transactions").document(f"{file_id}-{index:03d}")
                batch.create(ref, {
                    "type": "expense",
                    "amount": int(item["amount"]),
                    "date": receipt.get("purchasedAt") or "",
                    "majorCategory": item.get("majorCategory") or "その他",
                    "minorCategory": item.get("minorCategory") or "未分類",
                    "itemName": item.get("name") or "",
                    "memo": "",
                    "payer": receipt.get("payer") or "",
                    "shopName": receipt.get("shopName") or "",
                    "source": "ocr",
                    "receiptId": file_id,
                    "receiptStatus": status,
                    "createdAt": now,
                    "updatedAt": now,
                })
        poc_payload = dict(receipt)
        poc_payload.update(dict(audit))
        poc_payload.update({"driveFileId": file_id, "createdAt": now, "updatedAt": now})
        batch.set(poc_ref, poc_payload, merge=False)
        batch.update(job_ref, {
            "status": status,
            "parseSource": audit.get("parseSource"),
            "llmLastModel": audit.get("llmModel"),
            "llmPromptVersion": audit.get("llmPromptVersion"),
            "llmSchemaVersion": audit.get("llmSchemaVersion"),
            "error": None,
            "updatedAt": now,
        })
        batch.commit()

    def create_alert(
        self,
        code: str,
        message: str,
        file_id: str | None = None,
        severity: str = "error",
    ) -> None:
        key = hashlib.sha256(f"{code}:{file_id or ''}".encode("utf-8")).hexdigest()[:32]
        ref = self._base.collection("system_alerts").document(key)
        snapshot = ref.get()
        existing = snapshot.to_dict() if snapshot.exists else {}
        if existing and existing.get("resolvedAt") is None:
            return
        ref.set({
            "code": code,
            "severity": severity,
            "driveFileId": file_id,
            "message": message[:200],
            "createdAt": _server_timestamp(),
            "resolvedAt": None,
        }, merge=False)

    def resolve_alert(self, code: str, file_id: str | None = None) -> None:
        key = hashlib.sha256(f"{code}:{file_id or ''}".encode("utf-8")).hexdigest()[:32]
        ref = self._base.collection("system_alerts").document(key)
        if ref.get().exists:
            ref.update({"resolvedAt": _server_timestamp()})

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


def create_firestore_writer(credential_path: str, household_id: str, max_units: int = 800) -> FirestoreWriter:
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
