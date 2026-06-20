from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable

from .pipeline import IMAGE_SUFFIXES


def sync_drive_folder(config: Dict[str, Any]) -> int:
    """Import images from a local Google Drive sync folder into inbox.

    This keeps the MVP dependency-free: Android can upload into a Drive folder,
    Google Drive for desktop can sync that folder to the Mac, and this function
    copies or moves those images into the normal local pipeline inbox.
    """
    drive_config = config.get("drive", {})
    if not drive_config.get("enabled", False):
        return 0

    source_dir_value = drive_config.get("source_dir")
    if not source_dir_value:
        raise ValueError("drive.source_dir is required when drive.enabled is true")

    source_dir = Path(source_dir_value).expanduser()
    if not source_dir.exists():
        raise FileNotFoundError(f"Drive source folder not found: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Drive source path is not a folder: {source_dir}")

    inbox_dir = Path(config["paths"]["inbox_dir"])
    inbox_dir.mkdir(parents=True, exist_ok=True)

    action = drive_config.get("after_import", "archive")
    archive_dir = None
    if action == "archive":
        archive_dir_value = drive_config.get("archive_dir")
        if not archive_dir_value:
            raise ValueError("drive.archive_dir is required when after_import is archive")
        archive_dir = Path(archive_dir_value).expanduser()
        archive_dir.mkdir(parents=True, exist_ok=True)
    elif action not in {"keep", "delete"}:
        raise ValueError("drive.after_import must be one of: archive, keep, delete")

    count = 0
    for source_path in _iter_images(source_dir):
        target_path = _unique_path(inbox_dir / source_path.name)
        shutil.copy2(source_path, target_path)
        _handle_imported_source(source_path, action, archive_dir)
        count += 1
    return count


def _iter_images(path: Path) -> Iterable[Path]:
    return sorted(
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    )


def _handle_imported_source(
    source_path: Path, action: str, archive_dir: Path | None
) -> None:
    if action == "keep":
        return
    if action == "delete":
        source_path.unlink()
        return
    if archive_dir is None:
        raise ValueError("archive_dir is required for archive action")
    shutil.move(str(source_path), str(_unique_path(archive_dir / source_path.name)))


def _unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(1, 10000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find unique target for {target}")
