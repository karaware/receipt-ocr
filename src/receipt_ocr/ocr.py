from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List


class OcrError(RuntimeError):
    pass


def run_ocr(image_path: Path, config: Dict[str, Any]) -> str:
    ocr_config = config.get("ocr", {})
    backend = ocr_config.get("backend", "macos_vision")
    if backend == "macos_vision":
        return _run_macos_vision_ocr(image_path, ocr_config)
    if backend == "command":
        return _run_command_ocr(image_path, ocr_config)
    raise OcrError(f"Unsupported OCR backend: {backend}")


def _run_command_ocr(image_path: Path, ocr_config: Dict[str, Any]) -> str:
    command = ocr_config.get("command")
    if not command:
        raise OcrError("ocr.command is not configured")

    expanded = _expand_command(command, image_path)
    result = subprocess.run(
        expanded,
        check=False,
        capture_output=True,
        text=True,
        timeout=int(ocr_config.get("timeout_seconds", 60)),
    )
    if result.returncode != 0:
        raise OcrError(result.stderr.strip() or f"OCR command failed: {expanded}")
    return result.stdout.strip()


def _run_macos_vision_ocr(image_path: Path, ocr_config: Dict[str, Any]) -> str:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "ocr_macos.swift"
    if not script_path.exists():
        raise OcrError(f"OCR script not found: {script_path}")

    module_cache = root / ".swift-module-cache-current"
    module_cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = str(module_cache)

    result = subprocess.run(
        ["swift", str(script_path), str(image_path.resolve())],
        check=False,
        capture_output=True,
        text=True,
        timeout=int(ocr_config.get("timeout_seconds", 60)),
        env=env,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise OcrError(message or f"OCR failed for {image_path}")
    return result.stdout.strip()


def _expand_command(command: List[str], image_path: Path) -> List[str]:
    return [part.replace("{image}", str(image_path)) for part in command]
