"""
Question parser — converts RawQuestion objects from AI extractor into
validated Question ORM models with confidence scores and extraction warnings.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings
from app.models.question import (
    AnswerSource,
    ExtractionStatus,
    Question,
    QuestionType,
)
from app.models.warning import ExtractionWarning, WarningType
from app.services.ai_extractor import RawQuestion

logger = logging.getLogger(__name__)

# Map string type names to enum values
QUESTION_TYPE_MAP: dict[str, QuestionType] = {
    "MCQ": QuestionType.MCQ,
    "TRUE_FALSE": QuestionType.TRUE_FALSE,
    "SHORT_ANSWER": QuestionType.SHORT_ANSWER,
    "LONG_ANSWER": QuestionType.LONG_ANSWER,
    "FILL_IN_BLANK": QuestionType.FILL_IN_BLANK,
    "MATCH": QuestionType.MATCH,
    "UNKNOWN": QuestionType.UNKNOWN,
}


@dataclass
class ParseResult:
    questions: list[Question] = field(default_factory=list)
    warnings: list[ExtractionWarning] = field(default_factory=list)


class QuestionParser:
    """
    Validates and normalizes RawQuestion data from the AI extractor into
    proper ORM Question objects. Also generates ExtractionWarning records
    for any issues detected.
    """

    def parse(
        self,
        raw_questions: list[RawQuestion],
        document_id: uuid.UUID,
        ocr_confidence: float,
    ) -> ParseResult:
        """
        Parse a list of raw extracted questions into ORM models.

        Args:
            raw_questions: Output from AIExtractor
            document_id: Parent document UUID
            ocr_confidence: Page-level OCR confidence (0-1)

        Returns:
            ParseResult with Question and ExtractionWarning ORM instances
        """
        result = ParseResult()

        for raw in raw_questions:
            try:
                question, warnings = self._parse_one(raw, document_id, ocr_confidence)
                result.questions.append(question)
                result.warnings.extend(warnings)
            except Exception as e:
                logger.warning("Failed to parse question: %s — %s", raw.question_number, e)
                result.warnings.append(
                    ExtractionWarning(
                        document_id=document_id,
                        warning_type=WarningType.INVALID_FORMAT,
                        message=f"Failed to parse question {raw.question_number}: {e}",
                        page_number=raw.source_page,
                    )
                )

        return result

    def _parse_one(
        self,
        raw: RawQuestion,
        document_id: uuid.UUID,
        ocr_confidence: float,
    ) -> tuple[Question, list[ExtractionWarning]]:
        """Parse and validate a single RawQuestion."""
        warnings: list[ExtractionWarning] = []

        # Determine question type
        q_type = QUESTION_TYPE_MAP.get(raw.question_type.upper(), QuestionType.UNKNOWN)

        # Normalize options
        options = raw.options or []
        if q_type == QuestionType.MCQ and len(options) < 2:
            q_type = QuestionType.UNKNOWN
            warnings.append(
                ExtractionWarning(
                    document_id=document_id,
                    warning_type=WarningType.PARTIAL_OPTIONS,
                    message=f"Question {raw.question_number}: MCQ detected but only {len(options)} option(s) found.",
                    page_number=raw.source_page,
                )
            )

        # Calculate final confidence
        confidence = self._compute_confidence(raw, ocr_confidence, len(options))

        # Determine extraction status
        extraction_status = self._determine_status(confidence)

        # Build ORM object
        question = Question(
            document_id=document_id,
            question_number=raw.question_number,
            question_text=raw.question_text.strip(),
            question_type=q_type,
            options=options,
            answer=raw.answer,
            answer_source=AnswerSource.SAME_DOCUMENT if raw.answer else AnswerSource.NOT_FOUND,
            answer_confidence=0.8 if raw.answer else 0.0,
            source_pages=[raw.source_page],
            is_cross_page=raw.is_cross_page,
            confidence=confidence,
            extraction_status=extraction_status,
            has_image=raw.has_image,
            has_table=raw.has_table,
            extraction_notes=raw.extraction_notes or None,
        )

        # Generate warnings
        if not raw.question_number:
            warnings.append(
                ExtractionWarning(
                    document_id=document_id,
                    warning_type=WarningType.MISSING_NUMBER,
                    message="Question number could not be identified.",
                    page_number=raw.source_page,
                )
            )

        if raw.is_cross_page:
            warnings.append(
                ExtractionWarning(
                    document_id=document_id,
                    warning_type=WarningType.CROSS_PAGE,
                    message=f"Question {raw.question_number} appears to span multiple pages.",
                    page_number=raw.source_page,
                )
            )

        if confidence < settings.CONFIDENCE_MEDIUM:
            warnings.append(
                ExtractionWarning(
                    document_id=document_id,
                    warning_type=WarningType.LOW_CONFIDENCE,
                    message=(
                        f"Question {raw.question_number}: low extraction confidence "
                        f"({confidence:.2f}). Human review recommended."
                    ),
                    page_number=raw.source_page,
                )
            )

        if raw.extraction_notes and "error" in raw.extraction_notes.lower():
            warnings.append(
                ExtractionWarning(
                    document_id=document_id,
                    warning_type=WarningType.OCR_ERROR,
                    message=f"Question {raw.question_number}: {raw.extraction_notes}",
                    page_number=raw.source_page,
                )
            )

        return question, warnings

    def _compute_confidence(
        self,
        raw: RawQuestion,
        ocr_confidence: float,
        option_count: int,
    ) -> float:
        """
        Compute a final confidence score combining multiple signals:
        - AI extraction confidence
        - OCR quality
        - Question completeness (has number, has options for MCQ, not cross-page)
        """
        score = raw.confidence

        # Weight in OCR quality
        score = (score * 0.7) + (ocr_confidence * 0.3)

        # Penalties
        if not raw.question_number:
            score -= 0.10
        if raw.is_cross_page:
            score -= 0.15
        if raw.question_type == "MCQ" and option_count < 2:
            score -= 0.20
        if len(raw.question_text) < 15:
            score -= 0.15
        if raw.has_image:
            score -= 0.05  # Image-dependent questions are harder to verify

        return max(0.0, min(1.0, round(score, 3)))

    @staticmethod
    def _determine_status(confidence: float) -> ExtractionStatus:
        if confidence >= settings.CONFIDENCE_HIGH:
            return ExtractionStatus.EXTRACTED
        elif confidence >= settings.CONFIDENCE_MEDIUM:
            return ExtractionStatus.PARTIAL
        else:
            return ExtractionStatus.REVIEW_REQUIRED
