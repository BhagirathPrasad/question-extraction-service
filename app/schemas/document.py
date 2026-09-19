"""Document and DocumentGroup Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.document import DocumentStatus, FileType


# ── Document Group ────────────────────────────────────────────────────────────

class DocumentGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class DocumentGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    created_at: datetime
    document_count: int = 0

    model_config = {"from_attributes": True}


class DocumentGroupDetail(DocumentGroupResponse):
    documents: list["DocumentSummary"] = []


# ── Document ──────────────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    """Returned immediately after a successful upload."""
    id: uuid.UUID
    original_filename: str
    file_type: FileType
    file_size_bytes: int
    status: DocumentStatus
    is_answer_key: bool
    group_id: Optional[uuid.UUID]
    created_at: datetime
    message: str = "Document uploaded successfully. Processing started."

    model_config = {"from_attributes": True}


class DocumentSummary(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_type: FileType
    file_size_bytes: int
    status: DocumentStatus
    is_answer_key: bool
    group_id: Optional[uuid.UUID]
    page_count: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    status: DocumentStatus
    page_count: Optional[int]
    processing_error: Optional[str]
    processing_started_at: Optional[datetime]
    processing_completed_at: Optional[datetime]
    question_count: int = 0
    warning_count: int = 0

    model_config = {"from_attributes": True}


class DocumentDetail(DocumentSummary):
    processing_error: Optional[str]
    processing_started_at: Optional[datetime]
    processing_completed_at: Optional[datetime]
    question_count: int = 0
    warning_count: int = 0
