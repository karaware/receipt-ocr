import tempfile
import unittest
from pathlib import Path

from receipt_ocr.vision_client import VisionClient


class VisionClientTest(unittest.TestCase):
    def test_empty_image_is_rejected_before_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "empty.jpg"
            image.touch()
            with self.assertRaises(ValueError):
                VisionClient(object()).document_text(image)


if __name__ == "__main__":
    unittest.main()
