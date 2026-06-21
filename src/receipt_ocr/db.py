from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .parser import ParsedReceipt


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            payer TEXT NOT NULL,
            shop_name TEXT,
            purchased_at TEXT,
            total_amount INTEGER,
            ocr_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'parsed',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            amount INTEGER NOT NULL,
            category TEXT NOT NULL,
            confidence REAL NOT NULL,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id)
        );

        CREATE TABLE IF NOT EXISTS cloud_sync (
            receipt_id INTEGER PRIMARY KEY,
            cloud_receipt_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id)
        );
        """
    )
    conn.commit()


def already_processed(conn: sqlite3.Connection, source_path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM receipts WHERE source_path = ? LIMIT 1", (source_path,)
    ).fetchone()
    return row is not None


def insert_receipt(
    conn: sqlite3.Connection,
    source_path: str,
    payer: str,
    parsed: ParsedReceipt,
    ocr_text: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO receipts
            (source_path, payer, shop_name, purchased_at, total_amount, ocr_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_path,
            payer,
            parsed.shop_name,
            parsed.purchased_at,
            parsed.total_amount,
            ocr_text,
        ),
    )
    receipt_id = int(cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO receipt_items
            (receipt_id, item_name, amount, category, confidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (receipt_id, item.name, item.amount, item.category, item.confidence)
            for item in parsed.items
        ],
    )
    conn.commit()
    return receipt_id
