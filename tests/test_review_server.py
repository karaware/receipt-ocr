import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from receipt_ocr.db import init_db
from receipt_ocr.review_server import (
    apply_category,
    get_items,
    get_receipts,
    get_uncategorized_items,
)


class ReviewServerTest(unittest.TestCase):
    def test_apply_category_updates_item_and_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "receipts.sqlite3"
            export_dir = root / "export"
            config_path = root / "config.json"
            config = {
                "paths": {
                    "db_path": str(db_path),
                    "export_dir": str(export_dir),
                },
                "categories": {
                    "食費": ["牛乳"],
                    "日用品": ["洗剤"],
                },
            }
            config_path.write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )

            conn = sqlite3.connect(db_path)
            init_db(conn)
            receipt_id = conn.execute(
                """
                INSERT INTO receipts
                    (source_path, payer, shop_name, purchased_at, total_amount, ocr_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("source.jpg", "me", "AEON", "2026-06-13", 100, "ocr"),
            ).lastrowid
            item_id = conn.execute(
                """
                INSERT INTO receipt_items
                    (receipt_id, item_name, amount, category, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (receipt_id, "おにぎり", 100, "未分類", 0.0),
            ).lastrowid
            matching_item_id = conn.execute(
                """
                INSERT INTO receipt_items
                    (receipt_id, item_name, amount, category, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (receipt_id, "手巻おにぎり", 120, "未分類", 0.0),
            ).lastrowid
            conn.commit()
            conn.close()

            self.assertEqual(len(get_uncategorized_items(config)), 2)

            apply_category(config_path, config, item_id, "食費", "おにぎり")

            updated = sqlite3.connect(db_path)
            row = updated.execute(
                "SELECT category, confidence FROM receipt_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            self.assertEqual(row, ("食費", 1.0))
            matching_row = updated.execute(
                "SELECT category, confidence FROM receipt_items WHERE id = ?",
                (matching_item_id,),
            ).fetchone()
            self.assertEqual(matching_row, ("食費", 1.0))
            self.assertIn("おにぎり", json.loads(config_path.read_text())["categories"]["食費"])
            self.assertTrue((export_dir / "items.csv").exists())

            receipts = get_receipts(config)
            items = get_items(config)

            self.assertEqual(receipts[0]["shop_name"], "AEON")
            self.assertEqual(items[0]["item_name"], "手巻おにぎり")
            self.assertEqual(items[0]["category"], "食費")


if __name__ == "__main__":
    unittest.main()
