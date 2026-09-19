"""Document group routes — manage related document sets."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.document import Document, DocumentGroup
from app.models.user import User
from app.schemas.document import (
    DocumentGroupCreate,
    DocumentGroupDetail,
    DocumentGroupResponse,
    DocumentSummary,
)
from app.schemas.common import MessageResponse
from app.services.answer_associator import cross_document_associate

router = APIRouter(prefix="/groups", tags=["Document Groups"])


@router.post(
    "/",
    response_model=DocumentGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new document group",
)
async def create_group(
    payload: DocumentGroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentGroupResponse:
    """
    Create a document group to associate related files.
    Example: a question paper + its answer key.
    """
    group = DocumentGroup(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)

    return DocumentGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        document_count=0,
    )


@router.get(
    "/",
    response_model=list[DocumentGroupResponse],
    summary="List all document groups for the current user",
)
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentGroupResponse]:
    """Return all document groups belonging to the authenticated user."""
    result = await db.execute(
        select(DocumentGroup)
        .where(DocumentGroup.user_id == current_user.id)
        .order_by(DocumentGroup.created_at.desc())
    )
    groups = result.scalars().all()
    responses = []
    for g in groups:
        doc_count = len(g.documents) if g.documents else 0
        responses.append(
            DocumentGroupResponse(
                id=g.id,
                name=g.name,
                description=g.description,
                created_at=g.created_at,
                document_count=doc_count,
            )
        )
    return responses


@router.get(
    "/{group_id}",
    response_model=DocumentGroupDetail,
    summary="Get a document group with its associated documents",
)
async def get_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentGroupDetail:
    """Return a document group along with all its linked documents."""
    group = await _get_group_or_404(group_id, current_user.id, db)

    docs = [DocumentSummary.model_validate(d) for d in (group.documents or [])]
    return DocumentGroupDetail(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        document_count=len(docs),
        documents=docs,
    )


@router.post(
    "/{group_id}/documents/{document_id}",
    response_model=MessageResponse,
    summary="Add an existing document to a group",
)
async def add_document_to_group(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Link an existing document to a document group."""
    await _get_group_or_404(group_id, current_user.id, db)

    doc_result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    doc.group_id = group_id
    return MessageResponse(message="Document added to group successfully.")


@router.post(
    "/{group_id}/process",
    response_model=MessageResponse,
    summary="Trigger cross-document answer association for a group",
)
async def process_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Run answer-key association across all documents in the group.
    This links answers from answer-key documents to questions in question papers.

    All documents in the group must have status COMPLETED or PARTIALLY_PROCESSED.
    """
    group = await _get_group_or_404(group_id, current_user.id, db)

    docs = group.documents or []
    if not docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group has no documents.",
        )

    updated = await cross_document_associate(group_id=group_id, db=db)
    return MessageResponse(
        message=f"Cross-document association complete. {updated} questions updated."
    )


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _get_group_or_404(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> DocumentGroup:
    result = await db.execute(
        select(DocumentGroup).where(
            DocumentGroup.id == group_id,
            DocumentGroup.user_id == user_id,
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document group not found or access denied.",
        )
    return group
