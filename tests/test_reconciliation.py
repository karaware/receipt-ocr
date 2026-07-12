import unittest

from receipt_ocr.parser import ReceiptItem
from receipt_ocr.reconciliation import reconcile_receipt


class ReconciliationTest(unittest.TestCase):
    def test_exact_categorized_receipt_is_confirmed(self):
        result = reconcile_receipt("店", "2026-06-20", 300, [ReceiptItem("パン", 300, "食費", 0.9)], "")
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.difference, 0)

    def test_explicit_discount_is_added(self):
        result = reconcile_receipt("店", "2026-06-20", 290, [ReceiptItem("パン", 300, "食費", 0.9)], "クーポン値引 10円")
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.items[-1].amount, -10)

    def test_yen_off_discount_is_added(self):
        result = reconcile_receipt(
            "店",
            "2026-06-20",
            920,
            [
                ReceiptItem("かけ(大)", 630, "食費", 0.9),
                ReceiptItem("かしわ天", 220, "食費", 0.9),
                ReceiptItem("鮭おむすび", 170, "食費", 0.9),
            ],
            "5枚天ぷら●100円引 -¥100",
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.reason, "reconciled")
        self.assertEqual(result.items[-1].name, "値引き・クーポン")
        self.assertEqual(result.items[-1].amount, -100)

    def test_small_unknown_difference_is_rounded(self):
        result = reconcile_receipt("店", "2026-06-20", 299, [ReceiptItem("パン", 300, "食費", 0.9)], "")
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.items[-1].name, "端数調整")

    def test_large_unknown_difference_requires_review(self):
        result = reconcile_receipt("店", "2026-06-20", 280, [ReceiptItem("パン", 300, "食費", 0.9)], "")
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.difference, -20)

    def test_uncategorized_requires_review(self):
        result = reconcile_receipt("店", "2026-06-20", 300, [ReceiptItem("商品", 300)], "")
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.reason, "uncategorized")

    def test_missing_required_field_requires_review(self):
        result = reconcile_receipt("", "2026-06-20", 300, [ReceiptItem("パン", 300, "食費", 0.9)], "")
        self.assertEqual(result.reason, "missing_required")


if __name__ == "__main__":
    unittest.main()
