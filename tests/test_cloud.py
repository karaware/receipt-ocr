import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from receipt_ocr.cloud import sync_cloud
from receipt_ocr.db import init_db


class CloudSyncTest(unittest.TestCase):
    def test_failure_is_retryable_and_cloud_id_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "receipts.sqlite3"
            conn = sqlite3.connect(db_path)
            init_db(conn)
            receipt_id = conn.execute(
                """
                INSERT INTO receipts(source_path, payer, shop_name, purchased_at, total_amount, ocr_text)
                VALUES ('source.jpg', 'me', '店', '2026-06-20', 100, '商品 100\n合計 100')
                """
            ).lastrowid
            conn.execute(
                "INSERT INTO receipt_items(receipt_id, item_name, amount, category, confidence) VALUES (?, '商品', 100, '食費', 0.9)",
                (receipt_id,),
            )
            conn.commit()
            conn.close()
            config = {
                "paths": {"db_path": str(db_path)},
                "cloud": {
                    "enabled": True,
                    "household_id": "home",
                    "service_account_path": "unused.json",
                },
            }

            with patch("receipt_ocr.cloud._firestore_client", return_value=object()), patch(
                "receipt_ocr.cloud._write_receipt_batch", side_effect=RuntimeError("offline")
            ):
                self.assertEqual(sync_cloud(config), {"synced": 0, "failed": 1})

            failed = sqlite3.connect(db_path).execute(
                "SELECT cloud_receipt_id, status, attempts FROM cloud_sync"
            ).fetchone()
            self.assertEqual(failed[1:], ("failed", 1))

            with patch("receipt_ocr.cloud._firestore_client", return_value=object()), patch(
                "receipt_ocr.cloud._write_receipt_batch"
            ) as write:
                self.assertEqual(sync_cloud(config), {"synced": 1, "failed": 0})
                self.assertEqual(write.call_args.args[2], failed[0])

            synced = sqlite3.connect(db_path).execute(
                "SELECT cloud_receipt_id, status, attempts FROM cloud_sync"
            ).fetchone()
            self.assertEqual(synced, (failed[0], "synced", 2))


if __name__ == "__main__":
    unittest.main()
