import copy
import unittest
from datetime import date

from receipt_ocr.llm_contract import (
    LlmValidationError,
    build_input,
    input_sha256,
    validate_result,
)


class LlmContractTest(unittest.TestCase):
    def setUp(self):
        self.request = build_input(
            "file-1",
            "丸亀製麺\n2026/05/13\nかけ(大) 630\n値引 -100\n合計 530",
            {"shopName": "丸亀製麺", "purchasedAt": "2026-05-13", "totalAmount": 530},
            [
                {"major": "食費", "minor": ["外食"]},
                {"major": "調整", "minor": ["値引き・税", "端数"]},
            ],
            "a" * 64,
        )
        self.result = {
            "schemaVersion": "receipt-llm-result/v1",
            "driveFileId": "file-1",
            "inputSha256": self.request["inputSha256"],
            "shopName": {"value": "丸亀製麺", "confidence": "high", "evidenceLineNumbers": [1]},
            "purchasedAt": {"value": "2026-05-13", "confidence": "high", "evidenceLineNumbers": [2]},
            "totalAmount": {"value": 530, "confidence": "high", "evidenceLineNumbers": [5]},
            "items": [
                {"name": "かけ(大)", "amount": 630, "kind": "product", "majorCategory": "食費", "minorCategory": "外食", "confidence": "high", "evidenceLineNumbers": [3]},
                {"name": "値引", "amount": -100, "kind": "discount", "majorCategory": "調整", "minorCategory": "値引き・税", "confidence": "high", "evidenceLineNumbers": [4]},
            ],
            "warnings": [],
        }

    def test_hash_is_stable_and_excludes_its_own_field(self):
        self.assertEqual(self.request["inputSha256"], input_sha256(self.request))

    def test_validates_exact_receipt(self):
        value = validate_result(self.result, self.request, today=date(2026, 7, 12))
        self.assertEqual(value.total_amount, 530)
        self.assertEqual(sum(item.amount for item in value.items), 530)
        self.assertEqual(value.soft_warnings, ())

    def test_rejects_unknown_field(self):
        invalid = copy.deepcopy(self.result)
        invalid["extra"] = "bad"
        with self.assertRaises(LlmValidationError) as raised:
            validate_result(invalid, self.request, today=date(2026, 7, 12))
        self.assertIn("result_unknown_fields", raised.exception.errors)

    def test_rejects_total_mismatch(self):
        invalid = copy.deepcopy(self.result)
        invalid["totalAmount"]["value"] = 540
        with self.assertRaises(LlmValidationError) as raised:
            validate_result(invalid, self.request, today=date(2026, 7, 12))
        self.assertIn("items_total_mismatch", raised.exception.errors)

    def test_rejects_category_outside_allowlist(self):
        invalid = copy.deepcopy(self.result)
        invalid["items"][0]["majorCategory"] = "娯楽"
        with self.assertRaises(LlmValidationError) as raised:
            validate_result(invalid, self.request, today=date(2026, 7, 12))
        self.assertIn("items[0]_category", raised.exception.errors)

    def test_rejects_zero_amount_in_application_validation(self):
        invalid = copy.deepcopy(self.result)
        invalid["items"][0]["amount"] = 0
        with self.assertRaises(LlmValidationError) as raised:
            validate_result(invalid, self.request, today=date(2026, 7, 12))
        self.assertIn("items[0]_amount", raised.exception.errors)


if __name__ == "__main__":
    unittest.main()
