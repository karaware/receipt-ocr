import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from receipt_ocr.drive_api_client import DriveApiClient, DriveImage


class DriveApiClientTest(unittest.TestCase):
    def test_list_filters_non_images_and_paginates(self):
        service = MagicMock()
        service.files.return_value.list.return_value.execute.side_effect = [
            {"nextPageToken": "next", "files": [
                {"id": "a", "name": "one.jpg", "mimeType": "image/jpeg", "size": "3"},
                {"id": "x", "name": "note.txt", "mimeType": "text/plain", "size": "2"},
            ]},
            {"files": [{"id": "b", "name": "two.png", "mimeType": "image/png"}]},
        ]
        images = DriveApiClient(service).list_images("folder")
        self.assertEqual([image.file_id for image in images], ["a", "b"])

    def test_download_rejects_size_mismatch(self):
        service = MagicMock()
        downloader = MagicMock()
        downloader.next_chunk.side_effect = [(None, True)]
        # MediaIoBaseDownload writes through the supplied buffer in production;
        # this empty fake therefore exercises the integrity check.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(IOError):
                DriveApiClient(service, lambda buffer, request: downloader).download(
                    DriveImage("a", "one.jpg", "image/jpeg", 3), Path(tmp) / "one.jpg"
                )


if __name__ == "__main__":
    unittest.main()
