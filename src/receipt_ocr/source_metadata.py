from __future__ import annotations

import base64
from pathlib import Path


RECEIPT_PREFIX = "receipt__"


def payer_from_filename(path: str | Path) -> str | None:
    """Decode the payer embedded by the Android receipt capture app.

    Expected shape: receipt__<base64url UTF-8>__<UTC timestamp>__<uuid>.jpg.
    Extra suffixes added by the Drive importer do not affect payer decoding.
    """
    name = Path(path).name
    if not name.startswith(RECEIPT_PREFIX):
        return None
    parts = Path(name).stem.split("__")
    if len(parts) != 4 or parts[0] != "receipt" or not parts[1]:
        return None
    token = parts[1]
    token += "=" * (-len(token) % 4)
    try:
        payer = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8").strip()
    except (UnicodeDecodeError, ValueError):
        return None
    return payer or None


def resolve_payer(path: str | Path, fallback: str | None) -> str:
    payer = payer_from_filename(path)
    if payer:
        return payer
    if fallback and fallback.strip():
        return fallback.strip()
    raise ValueError(
        f"Payer is missing from filename and --payer was not supplied: {Path(path).name}"
    )
