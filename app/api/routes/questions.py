"""Question retrieval routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.document import Document
from app.models.question import Question
from app.models.user import User
from app.schemas.question import QuestionAnswerResponse, QuestionResponse

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.get(
    "/{question_id}",
    response_model=QuestionResponse,
    summary="Get full details of a single extracted question",
)
async def get_question(
    question_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestionResponse:
    """
    Retrieve complete details for an extracted question including:
    - Question text and options
    - Extraction confidence score
    - Source page(s)
    - Answer (if available)
    - Extraction notes/warnings
    """
    question = await _get_question_or_404(question_id, current_user.id, db)
    return QuestionResponse.model_validate(question)


@router.get(
    "/{question_id}/answer",
    response_model=QuestionAnswerResponse,
    summary="Get answer information for a specific question",
)
async def get_question_answer(
    question_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestionAnswerResponse:
    """
    Retrieve answer-specific information for a question.
    Includes answer source and reliability indicator.

    - `answer_source`: WHERE the answer came from (same doc, linked doc, or not found)
    - `is_answer_reliable`: True when answer_confidence >= 0.60
    """
    question = await _get_question_or_404(question_id, current_user.id, db)

    return QuestionAnswerResponse(
        question_id=question.id,
        question_number=question.question_number,
        question_text=question.question_text,
        answer=question.answer,
        answer_source=question.answer_source,
        answer_confidence=question.answer_confidence,
        is_answer_reliable=question.answer_confidence >= 0.60,
    )


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _get_question_or_404(
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Question:
    """Fetch a question by ID, enforcing user ownership via the parent document."""
    result = await db.execute(
        select(Question)
        .join(Document, Document.id == Question.document_id)
        .where(Question.id == question_id, Document.user_id == user_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found or access denied.",
        )
    return question
