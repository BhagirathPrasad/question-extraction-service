"""ExtractionWarning model — records issues during document processing."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WarningType(str, enum.Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"       # Confidence below threshold
    OCR_ERROR = "OCR_ERROR"                 # Tesseract returned noisy text
    MISSING_NUMBER = "MISSING_NUMBER"       # Question number not found
    CROSS_PAGE = "CROSS_PAGE"               # Question spans multiple pages
    UNCLEAR_ANSWER = "UNCLEAR_ANSWER"       # Answer couldn't be reliably identified
    UNMATCHED_ANSWER = "UNMATCHED_ANSWER"   # Answer key entry has no matching question
    INVALID_FORMAT = "INVALID_FORMAT"       # Document format not fully supported
    MALFORMED_FILE = "MALFORMED_FILE"       # File is corrupted or unreadable
    PARTIAL_OPTIONS = "PARTIAL_OPTIONS"     # MCQ options are incomplete
    BLURRY_IMAGE = "BLURRY_IMAGE"           # Low-resolution or blurry scan detected
    OTHER = "OTHER"


class ExtractionWarning(Base):
    """
    Records a warning or review item generated during document processing.
    Linked to the document and optionally to a specific question.
    """
    __tablename__ = "extraction_warnings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional: pinned to a specific question
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    warning_type: Mapped[WarningType] = mapped_column(
        Enum(WarningType, name="warning_type_enum"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ──────────────────────────────────────────────────────
    document: Mapped["Document"] = relationship(  # noqa: F821
        "Document", back_populates="warnings"
    )
    question: Mapped["Question"] = relationship(  # noqa: F821
        "Question", back_populates="warnings"
    )

    def __repr__(self) -> str:
        return f"<Warning id={self.id} type={self.warning_type} page={self.page_number}>"
