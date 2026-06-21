from __future__ import annotations

from typing import Any, Dict, List

from .parser import ReceiptItem


def categorize_items(
    items: List[ReceiptItem], config: Dict[str, Any], cloud_rules: Dict[str, str] | None = None
) -> List[ReceiptItem]:
    categories = config.get("categories", {})
    for item in items:
        normalized = normalize_item_name(item.name)
        if cloud_rules and normalized in cloud_rules:
            item.category, item.confidence = cloud_rules[normalized], 1.0
        else:
            item.category, item.confidence = _categorize(item.name, categories)
    return items


def normalize_item_name(name: str) -> str:
    return "".join(name.strip().lower().split())


def _categorize(name: str, categories: Dict[str, List[str]]) -> tuple[str, float]:
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword and keyword in name:
                return category, 0.9
    return "未分類", 0.0
