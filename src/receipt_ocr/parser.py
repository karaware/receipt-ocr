from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ReceiptItem:
    name: str
    amount: int
    category: str = "未分類"
    confidence: float = 0.0


@dataclass
class ParsedReceipt:
    shop_name: str = ""
    purchased_at: Optional[str] = None
    total_amount: Optional[int] = None
    items: List[ReceiptItem] = field(default_factory=list)


DATE_PATTERNS = [
    re.compile(r"(20\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})"),
    re.compile(r"(\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})"),
]
AMOUNT_RE = re.compile(r"(-)?[¥￥]?\s*([0-9０-９][0-9０-９,，\s]{1,})\s*円?")
SHOP_NAME_SKIP_KEYWORDS = [
    "領収証",
    "レシート",
    "お客様控",
    "御菓子",
    "菓子司",
]
TOTAL_EXCLUDE_KEYWORDS = [
    "小計",
    "内消費税",
    "消費税",
    "対象",
    "税込計",
    "お預り",
    "預り",
    "現金",
    "クレジット",
    "支払",
    "お釣",
    "釣銭",
]
META_KEYWORDS = [
    "TEL",
    "電話",
    "登録番号",
    "カード番号",
    "承認番号",
    "端末番号",
    "加盟店名",
    "ご利用日",
    "伝票No",
    "伝票番号",
    "取引区分",
    "支払区分",
    "AID",
    "ATC",
    "カードシーケンス番号",
    "アプリケーションラベル",
    "レジ",
    "店：",
    "App Store",
    "Google Play",
    "XXXX",
]
ITEM_SKIP_KEYWORDS = [
    "小計",
    "合計",
    "割引",
    "消費税",
    "対象",
    "含む",
    "クレジット",
    "カード",
    "ポイント",
    "クーポン",
    "登録番号",
]
NON_ITEM_NAME_KEYWORDS = [
    "領収証",
    "株式会社",
    "登録番号",
    "TEL",
    "FAX",
    "レジ",
    "責",
    "取",
    "割引",
    "小計",
    "合計",
]
MAX_REASONABLE_AMOUNT = 1_000_000
DEFAULT_TOTAL_KEYWORDS = [
    "合計",
    "合言十",
    "合 計",
    "会計",
    "税込",
    "日計金額",
    "合計金額",
    "お支払金額",
    "お支払い金額",
    "支払金額",
    "決済金額",
]


def parse_receipt(ocr_text: str, config: Dict[str, Any]) -> ParsedReceipt:
    lines = _clean_lines(ocr_text)
    parser_config = config.get("parser", {})
    ignore_keywords = parser_config.get("ignore_line_keywords", [])
    total_keywords = _merge_keywords(
        DEFAULT_TOTAL_KEYWORDS, parser_config.get("tax_included_keywords", [])
    )

    receipt = ParsedReceipt()
    receipt.shop_name = _guess_shop_name(lines, ignore_keywords)
    receipt.purchased_at = _guess_date(lines)
    receipt.total_amount = _guess_total(lines, total_keywords)
    receipt.items = _guess_items(lines, ignore_keywords, total_keywords)
    return receipt


def _merge_keywords(*groups: Iterable[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for group in groups:
        for keyword in group:
            if keyword and keyword not in seen:
                merged.append(keyword)
                seen.add(keyword)
    return merged


def _clean_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _guess_shop_name(lines: Iterable[str], ignore_keywords: List[str]) -> str:
    for line in lines:
        if any(keyword in line for keyword in ignore_keywords):
            continue
        if any(keyword in line for keyword in SHOP_NAME_SKIP_KEYWORDS):
            continue
        if _amount_from_line(line) is not None:
            continue
        if _date_from_line(line) is not None:
            continue
        if not _looks_like_item_name(line):
            continue
        return line[:80]
    return ""


def _guess_date(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        parsed = _date_from_line(line)
        if parsed:
            return parsed.isoformat()
    return None


def _date_from_line(line: str) -> Optional[date]:
    normalized = _to_ascii_digits(line)
    for pattern in DATE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        year = int(match.group(1))
        if year < 100:
            year += 2000
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _guess_total(lines: Iterable[str], total_keywords: List[str]) -> Optional[int]:
    indexed_lines = list(lines)
    candidates = []
    total_line_indexes = [
        index
        for index, line in enumerate(indexed_lines)
        if any(keyword in line for keyword in total_keywords)
    ]
    for index, line in enumerate(indexed_lines):
        amounts = _amounts_from_line(line)
        if not amounts:
            continue
        if _is_meta_line(line):
            continue
        if _is_total_excluded_line(line):
            continue
        if any(keyword in line for keyword in total_keywords):
            base_score = 30
        else:
            base_score = 1
            if any(0 < index - total_index <= 8 for total_index in total_line_indexes):
                base_score += 15
            if "¥" in line or "￥" in line:
                base_score += 3
        if "小計" in line:
            base_score -= 2
        if any(keyword in line for keyword in ("消費税", "対象")):
            base_score -= 8
        for amount in amounts:
            candidates.append((base_score, amount))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][1]


def _is_total_excluded_line(line: str) -> bool:
    return any(keyword in line for keyword in TOTAL_EXCLUDE_KEYWORDS)


def _guess_items(
    lines: Iterable[str], ignore_keywords: List[str], total_keywords: List[str]
) -> List[ReceiptItem]:
    items = []
    indexed_lines = list(lines)
    item_end_index = _first_item_end_index(indexed_lines, total_keywords)
    block_items = _guess_block_items(indexed_lines, item_end_index)
    if block_items:
        return block_items
    seen = set()
    for index, line in enumerate(indexed_lines):
        if item_end_index is not None and index >= item_end_index:
            break
        if line.strip().startswith("#"):
            continue
        if any(keyword in line for keyword in ignore_keywords + total_keywords):
            continue
        if any(keyword in line for keyword in ITEM_SKIP_KEYWORDS):
            continue
        if _is_meta_line(line):
            continue
        if _date_from_line(line) is not None:
            continue
        amount = _amount_from_line(line)
        if amount is None:
            continue
        if amount < 0:
            continue
        if amount < 100 and "," not in line and "¥" not in line and "￥" not in line:
            continue
        name = AMOUNT_RE.sub("", _to_ascii_digits(line)).strip(" -*:$¥￥\t")
        if len(name) < 2:
            name = _nearby_item_name(indexed_lines, index)
        if len(name) < 2:
            continue
        key = (name, amount)
        if key in seen:
            continue
        seen.add(key)
        items.append(ReceiptItem(name=name[:120], amount=amount))
    return items


def _amount_from_line(line: str) -> Optional[int]:
    amounts = _amounts_from_line(line)
    if not amounts:
        return None
    return amounts[-1]


def _amounts_from_line(line: str) -> List[int]:
    normalized = _to_ascii_digits(line)
    amounts = []
    for match in AMOUNT_RE.finditer(normalized):
        raw = match.group(2)
        digits = re.sub(r"\s+", "", raw).replace(",", "").replace("，", "")
        if len(digits) > 7:
            continue
        amount = int(digits)
        if match.group(1):
            amount *= -1
        if 0 < amount <= MAX_REASONABLE_AMOUNT:
            amounts.append(amount)
        elif -MAX_REASONABLE_AMOUNT <= amount < 0:
            amounts.append(amount)
    return amounts


def _guess_block_items(
    lines: List[str], item_end_index: Optional[int]
) -> List[ReceiptItem]:
    start_index = _first_item_start_index(lines)
    scoped_lines = lines[start_index:item_end_index] if item_end_index is not None else lines[start_index:]
    names: List[str] = []
    amounts: List[int] = []
    for line in scoped_lines:
        amount = _single_amount_line(line)
        if amount is not None:
            amounts.append(amount)
            continue
        name = _clean_item_name(line)
        if _looks_like_product_name(name):
            names.append(name)

    positive_amounts = [amount for amount in amounts if amount > 0]
    if len(positive_amounts) < 2 or len(names) < 2:
        return []

    items: List[ReceiptItem] = []
    name_index = 0
    for amount in amounts:
        if amount < 0:
            continue
        if name_index >= len(names):
            break
        items.append(ReceiptItem(name=names[name_index], amount=amount))
        name_index += 1
    return items


def _single_amount_line(line: str) -> Optional[int]:
    normalized = _to_ascii_digits(line).strip()
    if not re.fullmatch(r"-?[¥￥]?\s*[0-9, ]{2,}\s*※?", normalized):
        return None
    return _amount_from_line(normalized)


def _nearby_item_name(lines: List[str], amount_index: int) -> str:
    for offset in range(1, 5):
        candidate_index = amount_index - offset
        if candidate_index < 0:
            break
        candidate = lines[candidate_index]
        if _date_from_line(candidate) is not None:
            continue
        if _is_meta_line(candidate):
            continue
        if any(keyword in candidate for keyword in ITEM_SKIP_KEYWORDS):
            continue
        cleaned = _clean_item_name(candidate)
        if len(cleaned) >= 2 and _looks_like_item_name(cleaned):
            return cleaned
        if _amount_from_line(candidate) is not None:
            continue
    return ""


def _clean_item_name(line: str) -> str:
    normalized = _to_ascii_digits(line)
    normalized = re.sub(r"^[#*$¥￥\s]*\d{1,4}\s+", "", normalized)
    normalized = re.sub(r"^[#*$¥￥\s]+", "", normalized)
    return normalized.strip(" -*:$¥￥\t")[:120]


def _looks_like_item_name(line: str) -> bool:
    if re.fullmatch(r"[0-9,，.\s]+", line):
        return False
    return re.search(r"[A-Za-z一-龯ぁ-んァ-ン]", line) is not None


def _looks_like_product_name(line: str) -> bool:
    if len(line) < 2:
        return False
    if not _looks_like_item_name(line):
        return False
    if _single_amount_line(line) is not None:
        return False
    if any(keyword in line for keyword in NON_ITEM_NAME_KEYWORDS):
        return False
    if re.fullmatch(r"[（(]?\d+個.*", line):
        return False
    if "個" in line and "単" in line:
        return False
    if re.fullmatch(r"\d+%?", line):
        return False
    return True


def _first_item_end_index(lines: List[str], total_keywords: List[str]) -> Optional[int]:
    for index, line in enumerate(lines):
        if "小計" in line or any(keyword in line for keyword in total_keywords):
            return index
    return None


def _first_item_start_index(lines: List[str]) -> int:
    for index, line in enumerate(lines):
        if _date_from_line(line) is not None:
            return index + 1
    return 0


def _is_meta_line(line: str) -> bool:
    normalized = _to_ascii_digits(line)
    if any(keyword in normalized for keyword in META_KEYWORDS):
        return True
    digits = re.sub(r"\D", "", normalized)
    if len(digits) >= 8 and not ("," in normalized or "¥" in normalized or "￥" in normalized):
        return True
    return False


def _to_ascii_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
