"""Question and ExtractionWarning Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.question import AnswerSource, ExtractionStatus, QuestionType
from app.models.warning import WarningType


# ── Option ────────────────────────────────────────────────────────────────────

class QuestionOption(BaseModel):
    label: str   # "A", "B", "1", "2", etc.
    text: str    # Option text


# ── Question ──────────────────────────────────────────────────────────────────

class QuestionResponse(BaseModel):
    """Full question detail with all extracted fields."""
    id: uuid.UUID
    document_id: uuid.UUID
    question_number: Optional[str]
    question_text: str
    question_type: QuestionType
    options: list[dict[str, Any]]
    answer: Optional[str]
    answer_source: AnswerSource
    answer_confidence: float
    source_pages: list[int]
    is_cross_page: bool
    confidence: float
    extraction_status: ExtractionStatus
    has_image: bool
    has_table: bool
    extraction_notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class QuestionSummary(BaseModel):
    """Compact question for list responses."""
    id: uuid.UUID
    question_number: Optional[str]
    question_text: str
    question_type: QuestionType
    extraction_status: ExtractionStatus
    confidence: float
    has_answer: bool = Field(default=False)
    source_pages: list[int]

    model_config = {"from_attributes": True}


class QuestionAnswerResponse(BaseModel):
    """Answer-specific view of a question."""
    question_id: uuid.UUID
    question_number: Optional[str]
    question_text: str
    answer: Optional[str]
    answer_source: AnswerSource
    answer_confidence: float
    is_answer_reliable: bool  # True if answer_confidence >= 0.6

    model_config = {"from_attributes": True}


# ── Warning ───────────────────────────────────────────────────────────────────

class WarningResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    question_id: Optional[uuid.UUID]
    warning_type: WarningType
    message: str
    page_number: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Paginated Responses ───────────────────────────────────────────────────────

class PaginatedQuestions(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[QuestionSummary]


class PaginatedWarnings(BaseModel):
    total: int
    items: list[WarningResponse]
