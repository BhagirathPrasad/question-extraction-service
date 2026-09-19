"""Question model — stores extracted exam questions with confidence metadata."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class QuestionType(str, enum.Enum):
    MCQ = "MCQ"                   # Multiple choice with options
    TRUE_FALSE = "TRUE_FALSE"     # Binary true/false question
    SHORT_ANSWER = "SHORT_ANSWER" # Short free-text response
    LONG_ANSWER = "LONG_ANSWER"   # Essay / long-form response
    FILL_IN_BLANK = "FILL_IN_BLANK"
    MATCH = "MATCH"               # Match-the-following
    UNKNOWN = "UNKNOWN"           # Could not determine type


class ExtractionStatus(str, enum.Enum):
    EXTRACTED = "EXTRACTED"             # High confidence, clean extraction
    PARTIAL = "PARTIAL"                 # Extracted but may have OCR issues
    REVIEW_REQUIRED = "REVIEW_REQUIRED" # Low confidence, needs human review


class AnswerSource(str, enum.Enum):
    SAME_DOCUMENT = "SAME_DOCUMENT"       # Answer found in same document
    LINKED_DOCUMENT = "LINKED_DOCUMENT"   # Answer from a linked answer-key doc
    NOT_FOUND = "NOT_FOUND"               # No answer key available
    UNMATCHED = "UNMATCHED"               # Answer key exists but couldn't match


class Question(Base):
    """
    A single extracted exam question.

    Schema fields:
      - question_number: original numbering (e.g. "1", "Q2", "ii")
      - question_text: full text of the question
      - options: JSONB array — [{"label": "A", "text": "Paris"}, ...]
      - answer: correct answer string (letter for MCQ, text for others)
      - source_pages: JSONB array of 1-based page numbers
      - confidence: 0.0–1.0 extraction confidence
    """
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Core Question Fields ───────────────────────────────────────────────
    question_number: Mapped[str] = mapped_column(String(50), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        Enum(QuestionType, name="question_type_enum"),
        default=QuestionType.UNKNOWN,
        nullable=False,
    )
    # [{"label": "A", "text": "Option text"}, ...]
    options: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # ── Answer Fields ──────────────────────────────────────────────────────
    answer: Mapped[str] = mapped_column(Text, nullable=True)
    answer_source: Mapped[AnswerSource] = mapped_column(
        Enum(AnswerSource, name="answer_source_enum"),
        default=AnswerSource.NOT_FOUND,
        nullable=False,
    )
    answer_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # ── Source Tracking ────────────────────────────────────────────────────
    # [1, 2] — 1-based page numbers from which this question was extracted
    source_pages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    is_cross_page: Mapped[bool] = mapped_column(default=False, nullable=False)

    # ── Extraction Metadata ────────────────────────────────────────────────
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus, name="extraction_status_enum"),
        default=ExtractionStatus.REVIEW_REQUIRED,
        nullable=False,
        index=True,
    )
    has_image: Mapped[bool] = mapped_column(default=False, nullable=False)
    has_table: Mapped[bool] = mapped_column(default=False, nullable=False)
    extraction_notes: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ──────────────────────────────────────────────────────
    document: Mapped["Document"] = relationship(  # noqa: F821
        "Document", back_populates="questions"
    )
    warnings: Mapped[list["ExtractionWarning"]] = relationship(  # noqa: F821
        "ExtractionWarning", back_populates="question"
    )

    def __repr__(self) -> str:
        return (
            f"<Question id={self.id} num={self.question_number} "
            f"confidence={self.confidence:.2f}>"
        )
