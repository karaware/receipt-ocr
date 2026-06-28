from __future__ import annotations

from pathlib import Path
from typing import Any


class VisionRequestIndeterminate(RuntimeError):
    """The request may have reached Vision and must not be retried automatically."""


class VisionClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_service_account(cls, credential_path: str) -> "VisionClient":
        try:
            from google.cloud import vision
        except ImportError as error:
            raise RuntimeError("Install google-cloud-vision to use the PoC worker") from error
        return cls(vision.ImageAnnotatorClient.from_service_account_file(credential_path))

    def document_text(self, image_path: str | Path) -> str:
        data = Path(image_path).read_bytes()
        if not data:
            raise ValueError("Cannot OCR an empty image")
        try:
            from google.cloud import vision

            response = self._client.document_text_detection(
                image=vision.Image(content=data)
            )
        except Exception as error:
            raise VisionRequestIndeterminate(str(error)) from error
        if response.error.message:
            raise VisionRequestIndeterminate(response.error.message)
        return response.full_text_annotation.text or ""
