import tempfile
import unittest
from pathlib import Path

from receipt_ocr.drive_client import sync_drive_folder


class DriveClientTest(unittest.TestCase):
    def test_sync_drive_folder_archives_imported_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "drive-inbox"
            archive = root / "drive-processed"
            inbox = root / "inbox"
            source.mkdir()
            (source / "receipt.jpg").write_bytes(b"image")
            (source / "memo.txt").write_text("ignore", encoding="utf-8")

            count = sync_drive_folder(
                {
                    "paths": {"inbox_dir": str(inbox)},
                    "drive": {
                        "enabled": True,
                        "source_dir": str(source),
                        "after_import": "archive",
                        "archive_dir": str(archive),
                    },
                }
            )

            self.assertEqual(count, 1)
            self.assertTrue((inbox / "receipt.jpg").exists())
            self.assertTrue((archive / "receipt.jpg").exists())
            self.assertFalse((source / "receipt.jpg").exists())
            self.assertTrue((source / "memo.txt").exists())

    def test_sync_drive_folder_keeps_source_and_uses_unique_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "drive-inbox"
            inbox = root / "inbox"
            source.mkdir()
            inbox.mkdir()
            (source / "receipt.jpg").write_bytes(b"new")
            (inbox / "receipt.jpg").write_bytes(b"old")

            count = sync_drive_folder(
                {
                    "paths": {"inbox_dir": str(inbox)},
                    "drive": {
                        "enabled": True,
                        "source_dir": str(source),
                        "after_import": "keep",
                    },
                }
            )

            self.assertEqual(count, 1)
            self.assertEqual((inbox / "receipt.jpg").read_bytes(), b"old")
            self.assertEqual((inbox / "receipt_1.jpg").read_bytes(), b"new")
            self.assertTrue((source / "receipt.jpg").exists())

    def test_sync_drive_folder_disabled_is_noop(self):
        count = sync_drive_folder({"drive": {"enabled": False}})

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
