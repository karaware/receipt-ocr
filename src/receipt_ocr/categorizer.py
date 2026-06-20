from __future__ import annotations

from typing import Any, Dict, List

from .parser import ReceiptItem


def categorize_items(items: List[ReceiptItem], config: Dict[str, Any]) -> List[ReceiptItem]:
    categories = config.get("categories", {})
    for item in items:
        item.category, item.confidence = _categorize(item.name, categories)
    return items


def _categorize(name: str, categories: Dict[str, List[str]]) -> tuple[str, float]:
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword and keyword in name:
                return category, 0.9
    return "未分類", 0.0

