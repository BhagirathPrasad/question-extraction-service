"""
File storage service — validates, saves, and manages uploaded files.
Files are stored under: {UPLOAD_DIR}/{user_id}/{document_id}/original.{ext}
"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import magic
from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.models.document import FileType


EXTENSION_TO_FILE_TYPE: dict[str, FileType] = {
    "pdf": FileType.PDF,
    "jpg": FileType.JPG,
    "jpeg": FileType.JPG,
    "png": FileType.PNG,
}

MIME_TO_FILE_TYPE: dict[str, FileType] = {
    "application/pdf": FileType.PDF,
    "image/jpeg": FileType.JPG,
    "image/png": FileType.PNG,
}


class FileStorageService:
    def __init__(self) -> None:
        self.base_dir = Path(settings.UPLOAD_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save_upload(
        self,
        upload: UploadFile,
        user_id: uuid.UUID,
    ) -> dict:
        """
        Validate and save an uploaded file.

        Validation steps:
        1. Extension whitelist check
        2. File-size limit check
        3. MIME type verification (magic bytes — prevents extension spoofing)

        Returns a dict with file metadata for DB record creation.
        """
        # 1. Validate extension
        original_name = upload.filename or "upload"
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File type '.{ext}' is not supported. Allowed: {settings.ALLOWED_EXTENSIONS}",
            )

        # 2. Read content and check size
        content = await upload.read()
        if len(content) > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB.",
            )
        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        # 3. Validate MIME type via magic bytes (not just extension)
        mime_type = magic.from_buffer(content, mime=True)
        if mime_type not in settings.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File content type '{mime_type}' is not allowed.",
            )

        file_type = MIME_TO_FILE_TYPE[mime_type]

        # Build storage path
        doc_id = uuid.uuid4()
        user_dir = self.base_dir / str(user_id) / str(doc_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename — store with doc_id prefix to avoid conflicts
        safe_ext = "pdf" if file_type == FileType.PDF else ext
        stored_filename = f"{doc_id}.{safe_ext}"
        file_path = user_dir / stored_filename

        # Write to disk
        with open(file_path, "wb") as f:
            f.write(content)

        return {
            "original_filename": self._sanitize_filename(original_name),
            "stored_filename": stored_filename,
            "file_path": str(file_path),
            "file_type": file_type,
            "file_size_bytes": len(content),
        }

    def get_file_path(self, stored_path: str) -> Path:
        """Return the absolute Path for a stored file."""
        return Path(stored_path)

    def delete_file(self, file_path: str) -> None:
        """Delete the stored file and its parent directory if empty."""
        path = Path(file_path)
        if path.exists():
            path.unlink()
        # Remove parent dir if empty
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            shutil.rmtree(parent, ignore_errors=True)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Remove path separators and null bytes from filename."""
        return (
            filename.replace("/", "_")
            .replace("\\", "_")
            .replace("\x00", "")[:512]
        )
