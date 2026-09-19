"""
Answer associator — matches answer-key entries to extracted questions.

Supports:
  1. Same-document answer key (appears at end/beginning of document)
  2. Cross-document association (separate answer key PDF linked via DocumentGroup)
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.question import AnswerSource, Question
from app.models.warning import ExtractionWarning, WarningType

logger = logging.getLogger(__name__)


# ── Answer Key Detection ───────────────────────────────────────────────────────

ANSWER_KEY_PATTERNS = [
    # "Answer Key", "Answers", "Solutions", "Key"
    r"(?i)\b(?:answer\s*key|answers?|solutions?|key)\b",
]

# Patterns for answer key entries like: "1. A", "1) B", "Q1. C", "1 - D"
ANSWER_ENTRY_PATTERNS = [
    r"(?:Q\.?\s*)?(\d+)[.):\s-]+([A-Ea-e])\b",
    r"\((\d+)\)\s*[:\-]?\s*([A-Ea-e])\b",
    r"(\d+)\s*[:\-]\s*([A-Ea-e])\b",
]


def extract_answers_from_text(text: str) -> dict[str, str]:
    """
    Parse answer key text into a mapping of question_number → answer.
    E.g. {"1": "A", "2": "C", "3": "B"}
    """
    answers: dict[str, str] = {}

    for pattern in ANSWER_ENTRY_PATTERNS:
        matches = re.findall(pattern, text)
        for num, ans in matches:
            answers[num.strip()] = ans.upper().strip()

    return answers


def is_answer_key_section(text: str) -> bool:
    """Return True if the text looks like an answer key section."""
    for pattern in ANSWER_KEY_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


# ── Within-Document Association ───────────────────────────────────────────────

def associate_answers_to_questions(
    questions: list[Question],
    answer_map: dict[str, str],
    document_id: uuid.UUID,
    source: AnswerSource = AnswerSource.SAME_DOCUMENT,
) -> tuple[list[Question], list[ExtractionWarning]]:
    """
    Update questions with matched answers from an answer map.

    Returns:
        Tuple of (updated questions, new warnings for unmatched answers)
    """
    matched_nums: set[str] = set()
    warnings: list[ExtractionWarning] = []

    for question in questions:
        q_num = (question.question_number or "").strip()
        if q_num in answer_map:
            question.answer = answer_map[q_num]
            question.answer_source = source
            question.answer_confidence = 0.90
            matched_nums.add(q_num)
        elif question.answer:
            # Already has answer from extraction
            pass
        else:
            if not question.answer:
                question.answer_source = AnswerSource.UNMATCHED

    # Warn about answer key entries that couldn't be matched
    for num, ans in answer_map.items():
        if num not in matched_nums:
            warnings.append(
                ExtractionWarning(
                    document_id=document_id,
                    warning_type=WarningType.UNMATCHED_ANSWER,
                    message=(
                        f"Answer key entry '{num}:{ans}' could not be matched "
                        "to any extracted question."
                    ),
                )
            )

    return questions, warnings


# ── Cross-Document Association ────────────────────────────────────────────────

async def cross_document_associate(
    group_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """
    Associate answers from answer-key documents to questions in question papers
    within the same document group.

    Returns the count of questions updated.
    """
    # Load all documents in the group
    docs_result = await db.execute(
        select(Document).where(Document.group_id == group_id)
    )
    docs = docs_result.scalars().all()

    answer_key_docs = [d for d in docs if d.is_answer_key]
    question_docs = [d for d in docs if not d.is_answer_key]

    if not answer_key_docs or not question_docs:
        logger.info("Group %s: no answer key docs or question docs found for cross-association", group_id)
        return 0

    # Gather answer maps from all answer key documents
    combined_answers: dict[str, str] = {}
    for ak_doc in answer_key_docs:
        # Load questions from answer key doc (these have answers extracted)
        aq_result = await db.execute(
            select(Question)
            .where(Question.document_id == ak_doc.id)
            .where(Question.answer.isnot(None))
        )
        ak_questions = aq_result.scalars().all()
        for q in ak_questions:
            if q.question_number and q.answer:
                combined_answers[q.question_number.strip()] = q.answer

    if not combined_answers:
        logger.info("Group %s: no answers found in answer key documents", group_id)
        return 0

    updated_count = 0
    for q_doc in question_docs:
        q_result = await db.execute(
            select(Question).where(Question.document_id == q_doc.id)
        )
        questions = q_result.scalars().all()

        for question in questions:
            q_num = (question.question_number or "").strip()
            if q_num in combined_answers and not question.answer:
                question.answer = combined_answers[q_num]
                question.answer_source = AnswerSource.LINKED_DOCUMENT
                question.answer_confidence = 0.85
                updated_count += 1

    await db.flush()
    logger.info("Group %s: updated %d questions with answers from answer key", group_id, updated_count)
    return updated_count
