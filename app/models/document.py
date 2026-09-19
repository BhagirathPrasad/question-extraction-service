"""Document and DocumentGroup models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"                   # Uploaded, not yet processed
    PROCESSING = "PROCESSING"             # Worker is currently processing
    COMPLETED = "COMPLETED"               # All pages extracted successfully
    PARTIALLY_PROCESSED = "PARTIALLY_PROCESSED"  # Some pages failed
    FAILED = "FAILED"                     # Processing failed entirely


class FileType(str, enum.Enum):
    PDF = "PDF"
    JPG = "JPG"
    PNG = "PNG"


class DocumentGroup(Base):
    """
    Groups related documents together — e.g. a question paper + its answer key.
    """
    __tablename__ = "document_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="document_groups")  # noqa: F821
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="group", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<DocumentGroup id={self.id} name={self.name}>"


class Document(Base):
    """
    Represents a single uploaded file (PDF or image).
    Tracks processing status and links to extracted questions.
    """
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[FileType] = mapped_column(
        Enum(FileType, name="file_type_enum"), nullable=False
    )
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status_enum"),
        default=DocumentStatus.PENDING,
        nullable=False,
        index=True,
    )
    # Whether this document is an answer key (vs. question paper)
    is_answer_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=True)
    processing_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="documents")  # noqa: F821
    group: Mapped["DocumentGroup"] = relationship(
        "DocumentGroup", back_populates="documents"
    )
    questions: Mapped[list["Question"]] = relationship(  # noqa: F821
        "Question", back_populates="document", cascade="all, delete-orphan"
    )
    warnings: Mapped[list["ExtractionWarning"]] = relationship(  # noqa: F821
        "ExtractionWarning", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} file={self.original_filename} status={self.status}>"
