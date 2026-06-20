from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG = Path("config/config.json")


def load_config(path: str | Path = DEFAULT_CONFIG) -> Dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        example = Path("config/config.example.json")
        raise FileNotFoundError(
            f"Config not found: {config_path}. Copy {example} to {config_path} first."
        )
    return json.loads(config_path.read_text(encoding="utf-8"))


def ensure_dirs(config: Dict[str, Any]) -> None:
    paths = config["paths"]
    for key in ("inbox_dir", "processed_dir", "failed_dir", "export_dir"):
        Path(paths[key]).mkdir(parents=True, exist_ok=True)
    Path(paths["db_path"]).parent.mkdir(parents=True, exist_ok=True)

