from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def export_csv(conn: sqlite3.Connection, export_dir: str | Path) -> None:
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    _export_receipts(conn, export_path / "receipts.csv")
    _export_items(conn, export_path / "items.csv")


def _export_receipts(conn: sqlite3.Connection, path: Path) -> None:
    rows = conn.execute(
        """
        SELECT id, payer, shop_name, purchased_at, total_amount, source_path, created_at
        FROM receipts
        ORDER BY id
        """
    ).fetchall()
    _write_rows(path, rows)


def _export_items(conn: sqlite3.Connection, path: Path) -> None:
    rows = conn.execute(
        """
        SELECT
            r.id AS receipt_id,
            r.payer,
            r.shop_name,
            r.purchased_at,
            i.item_name,
            i.amount,
            i.category,
            i.confidence
        FROM receipt_items i
        JOIN receipts r ON r.id = i.receipt_id
        ORDER BY i.id
        """
    ).fetchall()
    _write_rows(path, rows)


def _write_rows(path: Path, rows: list[sqlite3.Row]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows([dict(row) for row in rows])

