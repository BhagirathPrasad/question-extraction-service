"""Document upload, status, and management routes."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.document import Document, DocumentGroup, DocumentStatus
from app.models.question import Question
from app.models.warning import ExtractionWarning
from app.models.user import User
from app.schemas.document import (
    DocumentDetail,
    DocumentStatusResponse,
    DocumentSummary,
    DocumentUploadResponse,
)
from app.schemas.question import PaginatedQuestions, PaginatedWarnings, QuestionSummary, WarningResponse
from app.services.file_storage import FileStorageService
from app.workers.tasks import process_document_task

router = APIRouter(prefix="/documents", tags=["Documents"])
storage = FileStorageService()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF or image for asynchronous processing",
)
async def upload_document(
    file: UploadFile = File(..., description="PDF, JPG, or PNG file"),
    is_answer_key: bool = Form(False, description="Set true if this document is an answer key"),
    group_id: Optional[uuid.UUID] = Form(None, description="Associate with an existing document group"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document for asynchronous question extraction.

    - Returns immediately with a document ID and PENDING status.
    - Processing is queued via Celery; poll `/documents/{id}/status` for updates.
    - Supported: PDF, JPG/JPEG, PNG (max 50 MB).
    """
    # Validate group ownership if provided
    if group_id:
        grp = await db.execute(
            select(DocumentGroup).where(
                DocumentGroup.id == group_id,
                DocumentGroup.user_id == current_user.id,
            )
        )
        if not grp.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document group not found or access denied.",
            )

    # Validate + store file
    doc_record = await storage.save_upload(
        upload=file,
        user_id=current_user.id,
    )

    # Create DB record
    document = Document(
        user_id=current_user.id,
        group_id=group_id,
        original_filename=doc_record["original_filename"],
        stored_filename=doc_record["stored_filename"],
        file_path=doc_record["file_path"],
        file_type=doc_record["file_type"],
        file_size_bytes=doc_record["file_size_bytes"],
        is_answer_key=is_answer_key,
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    await db.flush()
    await db.refresh(document)

    # Queue async processing task
    process_document_task.delay(str(document.id))

    return DocumentUploadResponse.model_validate(document)


@router.get(
    "/",
    response_model=list[DocumentSummary],
    summary="List all documents for the current user",
)
async def list_documents(
    status_filter: Optional[DocumentStatus] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentSummary]:
    """List all documents belonging to the authenticated user."""
    query = select(Document).where(Document.user_id == current_user.id)
    if status_filter:
        query = query.where(Document.status == status_filter)
    query = query.order_by(Document.created_at.desc())

    result = await db.execute(query)
    docs = result.scalars().all()
    return [DocumentSummary.model_validate(d) for d in docs]


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Check processing status of a document",
)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """
    Poll this endpoint after upload to track processing progress.
    Status flow: PENDING → PROCESSING → COMPLETED | PARTIALLY_PROCESSED | FAILED
    """
    doc = await _get_document_or_404(document_id, current_user.id, db)

    # Count questions and warnings
    q_count = await db.execute(
        select(func.count()).where(Question.document_id == doc.id)
    )
    w_count = await db.execute(
        select(func.count()).where(ExtractionWarning.document_id == doc.id)
    )

    response = DocumentStatusResponse.model_validate(doc)
    response.question_count = q_count.scalar() or 0
    response.warning_count = w_count.scalar() or 0
    return response


@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="Get full document details",
)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    """Retrieve full metadata for a document."""
    doc = await _get_document_or_404(document_id, current_user.id, db)

    q_count_result = await db.execute(
        select(func.count()).where(Question.document_id == doc.id)
    )
    w_count_result = await db.execute(
        select(func.count()).where(ExtractionWarning.document_id == doc.id)
    )

    detail = DocumentDetail.model_validate(doc)
    detail.question_count = q_count_result.scalar() or 0
    detail.warning_count = w_count_result.scalar() or 0
    return detail


@router.get(
    "/{document_id}/questions",
    response_model=PaginatedQuestions,
    summary="Retrieve extracted questions for a document",
)
async def get_document_questions(
    document_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedQuestions:
    """
    Return all extracted questions for a document, paginated.
    Questions are ordered by their question number / extraction order.
    """
    await _get_document_or_404(document_id, current_user.id, db)

    total_result = await db.execute(
        select(func.count()).where(Question.document_id == document_id)
    )
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    q_result = await db.execute(
        select(Question)
        .where(Question.document_id == document_id)
        .order_by(Question.created_at)
        .offset(offset)
        .limit(per_page)
    )
    questions = q_result.scalars().all()

    items = []
    for q in questions:
        summary = QuestionSummary.model_validate(q)
        summary.has_answer = bool(q.answer)
        items.append(summary)

    return PaginatedQuestions(total=total, page=page, per_page=per_page, items=items)


@router.get(
    "/{document_id}/warnings",
    response_model=PaginatedWarnings,
    summary="Retrieve extraction warnings and review items",
)
async def get_document_warnings(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedWarnings:
    """
    Return all extraction warnings for a document.
    Use this to identify questions or pages that need human review.
    """
    await _get_document_or_404(document_id, current_user.id, db)

    w_result = await db.execute(
        select(ExtractionWarning)
        .where(ExtractionWarning.document_id == document_id)
        .order_by(ExtractionWarning.created_at)
    )
    warnings = w_result.scalars().all()
    total = len(warnings)

    return PaginatedWarnings(
        total=total,
        items=[WarningResponse.model_validate(w) for w in warnings],
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all extracted data",
)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Permanently delete a document, its questions, warnings, and stored file.
    This action is irreversible.
    """
    doc = await _get_document_or_404(document_id, current_user.id, db)

    # Remove stored file
    storage.delete_file(doc.file_path)

    await db.delete(doc)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_document_or_404(
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Document:
    """Fetch document by ID, enforcing ownership. Raises 404 if not found."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )
    return doc
