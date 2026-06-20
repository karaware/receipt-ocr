from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable

from .categorizer import categorize_items
from .db import already_processed, connect, init_db, insert_receipt
from .exporter import export_csv
from .ocr import run_ocr
from .parser import parse_receipt
from .source_metadata import resolve_payer


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".webp"}


def run_local(
    config: Dict[str, Any], payer: str | None = None, keep_failed: bool = True
) -> int:
    paths = config["paths"]
    inbox = Path(paths["inbox_dir"])
    processed = Path(paths["processed_dir"])
    failed = Path(paths["failed_dir"])
    conn = connect(paths["db_path"])
    init_db(conn)

    count = 0
    for image_path in _iter_images(inbox):
        source_path = str(image_path.resolve())
        if already_processed(conn, source_path):
            continue
        try:
            ocr_text = run_ocr(image_path, config)
            parsed = parse_receipt(ocr_text, config)
            parsed.items = categorize_items(parsed.items, config)
            image_payer = resolve_payer(image_path, payer)
            insert_receipt(conn, source_path, image_payer, parsed, ocr_text)
            _move_unique(image_path, processed / image_path.name)
            count += 1
        except Exception:
            if keep_failed:
                _move_unique(image_path, failed / image_path.name)
            raise

    export_csv(conn, paths["export_dir"])
    return count


def _iter_images(path: Path) -> Iterable[Path]:
    if not path.exists():
        return []
    return sorted(
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    )


def _move_unique(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.move(str(source), str(target))
        return
    stem = target.stem
    suffix = target.suffix
    for index in range(1, 10000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            shutil.move(str(source), str(candidate))
            return
    raise RuntimeError(f"Could not find unique target for {target}")
