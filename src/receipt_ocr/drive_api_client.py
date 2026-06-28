from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp", "image/heic"}


@dataclass(frozen=True)
class DriveImage:
    file_id: str
    name: str
    mime_type: str
    size: int | None


class DriveApiClient:
    def __init__(self, service: Any, downloader_factory: Any = None) -> None:
        self._service = service
        self._downloader_factory = downloader_factory

    @classmethod
    def from_service_account(cls, credential_path: str) -> "DriveApiClient":
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as error:
            raise RuntimeError("Install google-api-python-client to use the PoC worker") from error
        credentials = service_account.Credentials.from_service_account_file(
            credential_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        return cls(build("drive", "v3", credentials=credentials, cache_discovery=False))

    def list_images(self, folder_id: str) -> list[DriveImage]:
        escaped = folder_id.replace("'", "\\'")
        token = None
        images: list[DriveImage] = []
        while True:
            response = self._service.files().list(
                q=f"'{escaped}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,mimeType,size)",
                pageSize=100,
                pageToken=token,
                orderBy="createdTime,name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            for item in response.get("files", []):
                mime_type = str(item.get("mimeType", ""))
                if mime_type not in IMAGE_MIME_TYPES:
                    continue
                images.append(DriveImage(
                    str(item["id"]), str(item["name"]), mime_type,
                    int(item["size"]) if item.get("size") else None,
                ))
            token = response.get("nextPageToken")
            if not token:
                return images

    def download(self, image: DriveImage, target: str | Path) -> str:
        if self._downloader_factory is None:
            try:
                from googleapiclient.http import MediaIoBaseDownload
            except ImportError as error:
                raise RuntimeError("Install google-api-python-client to use the PoC worker") from error
            downloader_factory = MediaIoBaseDownload
        else:
            downloader_factory = self._downloader_factory
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        request = self._service.files().get_media(fileId=image.file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = downloader_factory(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        content = buffer.getvalue()
        if image.size is not None and len(content) != image.size:
            raise IOError(f"Drive download size mismatch for {image.file_id}")
        target_path.write_bytes(content)
        return hashlib.sha256(content).hexdigest()
