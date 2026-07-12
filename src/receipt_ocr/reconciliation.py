from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from .parser import ReceiptItem


UNCATEGORIZED = "未分類"
ADJUSTMENT_CATEGORY = "調整"
SMALL_DIFFERENCE_LIMIT = 10


@dataclass
class ReconciliationResult:
    items: List[ReceiptItem]
    status: str
    difference: Optional[int]
    reason: str


def reconcile_receipt(
    shop_name: str,
    purchased_at: Optional[str],
    total_amount: Optional[int],
    items: Iterable[ReceiptItem],
    ocr_text: str,
) -> ReconciliationResult:
    reconciled = list(items)
    if not shop_name.strip() or not purchased_at or total_amount is None:
        return ReconciliationResult(reconciled, "needs_review", None, "missing_required")

    difference = total_amount - sum(item.amount for item in reconciled)
    if difference:
        adjustments = _find_explained_adjustments(ocr_text, difference)
        if adjustments:
            reconciled.extend(adjustments)
        elif abs(difference) <= SMALL_DIFFERENCE_LIMIT:
            reconciled.append(
                ReceiptItem("端数調整", difference, ADJUSTMENT_CATEGORY, 1.0)
            )

    remaining = total_amount - sum(item.amount for item in reconciled)
    if remaining:
        return ReconciliationResult(reconciled, "needs_review", remaining, "unexplained_difference")
    if not reconciled or any(item.category == UNCATEGORIZED for item in reconciled):
        return ReconciliationResult(reconciled, "needs_review", 0, "uncategorized")
    return ReconciliationResult(reconciled, "confirmed", 0, "reconciled")


def _find_explained_adjustments(text: str, target: int) -> List[ReceiptItem]:
    candidates: List[ReceiptItem] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        kind = _adjustment_kind(line)
        if not kind:
            continue
        amount = _amount_on_line(line)
        if amount is None and index + 1 < len(lines):
            amount = _amount_on_line(lines[index + 1])
        if amount is None or amount == 0:
            continue
        name, sign = kind
        value = abs(amount) * sign
        candidate = ReceiptItem(name, value, ADJUSTMENT_CATEGORY, 1.0)
        if (candidate.name, candidate.amount) not in {
            (item.name, item.amount) for item in candidates
        }:
            candidates.append(candidate)

    # Receipt adjustment sections are short. A bounded subset search lets a tax and
    # a discount jointly explain the difference without accepting arbitrary gaps.
    candidates = candidates[:12]
    for mask in range(1, 1 << len(candidates)):
        selected = [item for i, item in enumerate(candidates) if mask & (1 << i)]
        if sum(item.amount for item in selected) == target:
            return selected
    return []


def _adjustment_kind(line: str) -> Optional[tuple[str, int]]:
    if any(word in line for word in ("値引", "割引", "クーポン", "円引")):
        return "値引き・クーポン", -1
    if any(word in line for word in ("ポイント利用", "ポイント充当", "ポイント値引")):
        return "ポイント利用", -1
    if any(word in line for word in ("消費税", "外税", "税額")) and "含む" not in line:
        return "税", 1
    if any(word in line for word in ("端数", "丸め")):
        return "端数調整", -1 if "-" in line or "△" in line else 1
    return None


def _amount_on_line(line: str) -> Optional[int]:
    normalized = line.translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
    matches = re.findall(r"(?:[-△]\s*)?[¥￥]?\s*([0-9][0-9,]*)\s*円?", normalized)
    if not matches:
        return None
    return int(matches[-1].replace(",", ""))
