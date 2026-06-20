import base64
import unittest

from receipt_ocr.source_metadata import payer_from_filename, resolve_payer


class SourceMetadataTest(unittest.TestCase):
    def test_decodes_unicode_payer(self):
        payer = "妻 家計#1"
        token = base64.urlsafe_b64encode(payer.encode()).decode().rstrip("=")
        filename = f"receipt__{token}__20260620T010203Z__abc-123.jpg"
        self.assertEqual(payer_from_filename(filename), payer)

    def test_drive_unique_suffix_does_not_change_payer(self):
        token = base64.urlsafe_b64encode(b"wife").decode().rstrip("=")
        filename = f"receipt__{token}__20260620T010203Z__abc-123_1.jpg"
        self.assertEqual(payer_from_filename(filename), "wife")

    def test_falls_back_for_legacy_filename(self):
        self.assertEqual(resolve_payer("old-photo.jpg", "me"), "me")

    def test_missing_payer_without_fallback_is_an_error(self):
        with self.assertRaises(ValueError):
            resolve_payer("old-photo.jpg", None)


if __name__ == "__main__":
    unittest.main()
