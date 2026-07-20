from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .db import connect, init_db
from .parser import ReceiptItem
from .reconciliation import reconcile_receipt


DEFAULT_CATEGORY_SEED = [
    {"id": "income", "name": "収入", "type": "income", "subcategories": ["給与", "賞与", "その他"]},
    {"id": "food", "name": "食費", "type": "expense", "subcategories": ["食料品", "外食", "飲料", "その他", "値引き・税・手数料"]},
    {"id": "daily", "name": "日用品", "type": "expense", "subcategories": ["生活用品", "衛生用品", "その他", "値引き・税・手数料"]},
    {"id": "consumables", "name": "消耗品", "type": "expense", "subcategories": ["消耗品", "その他", "値引き・税・手数料"]},
    {"id": "adjustment", "name": "調整", "type": "expense", "subcategories": ["値引き・税", "端数", "その他", "値引き・税・手数料"]},
    {"id": "other", "name": "その他", "type": "expense", "subcategories": ["未分類", "その他", "値引き・税・手数料"]},
]


def sync_cloud(config: Dict[str, Any], include_existing_as_review: bool = False) -> Dict[str, int]:
    cloud = _cloud_config(config)
    db = _firestore_client(cloud)
    conn = connect(config["paths"]["db_path"])
    init_db(conn)
    rows = conn.execute(
        """
        SELECT r.* FROM receipts r
        LEFT JOIN cloud_sync s ON s.receipt_id = r.id
        WHERE s.status IS NULL OR s.status != 'synced'
        ORDER BY r.id
        """
    ).fetchall()
    result = {"synced": 0, "failed": 0}
    for row in rows:
        receipt_id = int(row["id"])
        cloud_id = _ensure_sync_row(conn, receipt_id, str(row["source_path"]))
        try:
            items = _local_items(conn, receipt_id)
            reconciled = reconcile_receipt(
                str(row["shop_name"] or ""), row["purchased_at"], row["total_amount"], items, str(row["ocr_text"])
            )
            if include_existing_as_review:
                reconciled.status = "needs_review"
                reconciled.reason = "initial_migration"
            _write_receipt_batch(db, cloud["household_id"], cloud_id, row, reconciled)
            conn.execute(
                "UPDATE cloud_sync SET status='synced', error=NULL, attempts=attempts+1, synced_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE receipt_id=?",
                (receipt_id,),
            )
            conn.commit()
            result["synced"] += 1
        except Exception as error:
            conn.execute(
                "UPDATE cloud_sync SET status='failed', error=?, attempts=attempts+1, updated_at=CURRENT_TIMESTAMP WHERE receipt_id=?",
                (str(error)[:1000], receipt_id),
            )
            conn.commit()
            result["failed"] += 1
    return result


def bootstrap_cloud(config: Dict[str, Any], emails: Iterable[str]) -> None:
    cloud = _cloud_config(config)
    db = _firestore_client(cloud)
    household = db.collection("households").document(cloud["household_id"])
    household.set({"name": cloud.get("household_name", "家計簿"), "currency": "JPY", "timezone": "Asia/Tokyo"}, merge=True)
    for email in emails:
        normalized = email.strip().lower()
        if normalized:
            household.collection("allowed_emails").document(normalized).set({"email": normalized})
    for category in DEFAULT_CATEGORY_SEED:
        household.collection("categories").document(category["id"]).set(category, merge=True)


def fetch_category_rules(config: Dict[str, Any]) -> Mapping[str, str]:
    cloud = _cloud_config(config)
    db = _firestore_client(cloud)
    docs = db.collection("households").document(cloud["household_id"]).collection("category_rules").stream()
    return {str(doc.get("normalized_name")): str(doc.get("category")) for doc in docs}


def _write_receipt_batch(db: Any, household_id: str, cloud_id: str, row: sqlite3.Row, result: Any) -> None:
    base = db.collection("households").document(household_id)
    receipt_ref = base.collection("receipts").document(cloud_id)
    # create() makes retries idempotent and prevents a stale Mac copy from
    # overwriting corrections made in the web app.
    if receipt_ref.get().exists:
        return
    batch = db.batch()
    batch.create(receipt_ref, {
        "shopName": row["shop_name"] or "", "purchasedAt": row["purchased_at"],
        "totalAmount": row["total_amount"], "payer": row["payer"],
        "status": result.status, "reviewReason": result.reason,
        "difference": result.difference, "sourceId": cloud_id,
        "source": "ocr", "createdAt": _server_timestamp(), "updatedAt": _server_timestamp(),
    })
    if len(result.items) > 450:
        raise ValueError("A receipt cannot contain more than 450 items")
    for index, item in enumerate(result.items):
        transaction_ref = base.collection("transactions").document(f"{cloud_id}-{index:03d}")
        major, minor = _category_parts(item.category, item.name)
        batch.create(transaction_ref, {
            "type": "expense", "amount": item.amount, "date": row["purchased_at"],
            "majorCategory": major, "minorCategory": minor, "itemName": item.name,
            "memo": "", "payer": row["payer"], "shopName": row["shop_name"] or "",
            "source": "ocr", "receiptId": cloud_id, "receiptStatus": result.status,
            "createdAt": _server_timestamp(), "updatedAt": _server_timestamp(),
        })
    batch.commit()


def _local_items(conn: sqlite3.Connection, receipt_id: int) -> List[ReceiptItem]:
    rows = conn.execute("SELECT item_name, amount, category, confidence FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)).fetchall()
    return [ReceiptItem(str(r["item_name"]), int(r["amount"]), str(r["category"]), float(r["confidence"])) for r in rows]


def _ensure_sync_row(conn: sqlite3.Connection, receipt_id: int, source_path: str) -> str:
    row = conn.execute("SELECT cloud_receipt_id FROM cloud_sync WHERE receipt_id=?", (receipt_id,)).fetchone()
    if row:
        return str(row["cloud_receipt_id"])
    digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()
    cloud_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"receipt-ocr:{digest}"))
    conn.execute("INSERT INTO cloud_sync(receipt_id, cloud_receipt_id) VALUES (?, ?)", (receipt_id, cloud_id))
    conn.commit()
    return cloud_id


def _category_parts(category: str, item_name: str) -> tuple[str, str]:
    if category == "調整":
        return "調整", "端数" if "端数" in item_name else "値引き・税"
    return (category if category != "未分類" else "その他", "未分類" if category == "未分類" else "その他")


def _cloud_config(config: Dict[str, Any]) -> Dict[str, Any]:
    cloud = config.get("cloud", {})
    if not cloud.get("enabled") or not cloud.get("household_id") or not cloud.get("service_account_path"):
        raise ValueError("cloud.enabled, cloud.household_id and cloud.service_account_path are required")
    return cloud


def _firestore_client(cloud: Dict[str, Any]) -> Any:
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as error:
        raise RuntimeError("Install firebase-admin to use cloud commands") from error
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(str(Path(cloud["service_account_path"]).expanduser())))
    return firestore.client()


def _server_timestamp() -> Any:
    from firebase_admin import firestore
    return firestore.SERVER_TIMESTAMP
