"""
Document processing orchestrator.

Pipeline for each document:
  1. Load file from storage
  2. Split into pages (PDF → render; image → single page)
  3. For each page:
     a. Check if text-selectable or scanned
     b. Run OCR if scanned/image
     c. Run AI extractor (Gemini or fallback)
     d. Parse into Question ORM objects
  4. Run answer key detection within the document
  5. Persist all questions and warnings to the database
  6. Update document status
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document, DocumentStatus, FileType
from app.models.question import Question
from app.models.warning import ExtractionWarning, WarningType
from app.services.ai_extractor import AIExtractor
from app.services.answer_associator import (
    associate_answers_to_questions,
    extract_answers_from_text,
    is_answer_key_section,
)
from app.services.ocr_service import OCRService
from app.services.question_parser import QuestionParser

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """
    Orchestrates the full document → questions pipeline.
    Designed to run inside a Celery worker (sync context via asyncio.run).
    """

    def __init__(self) -> None:
        self.ocr = OCRService()
        self.ai = AIExtractor()
        self.parser = QuestionParser()

    async def process(self, document: Document, db: AsyncSession) -> None:
        """
        Main entry point: process a document end-to-end.
        Updates the document's status in the database on completion/failure.
        """
        doc_id = document.id
        logger.info("Processing document %s (%s)", doc_id, document.original_filename)

        document.status = DocumentStatus.PROCESSING
        document.processing_started_at = datetime.now(timezone.utc)
        await db.flush()

        try:
            pages = self._load_pages(document)
            document.page_count = len(pages)

            all_questions: list[Question] = []
            all_warnings: list[ExtractionWarning] = []
            answer_map: dict[str, str] = {}

            for page_num, (page_image, embedded_text) in enumerate(pages, start=1):
                logger.debug("Processing page %d/%d", page_num, len(pages))

                # ── OCR if needed ──────────────────────────────────────────
                if len(embedded_text.strip()) < settings.MIN_TEXT_CHARS_PER_PAGE:
                    # Scanned page — run OCR
                    quality = self.ocr.detect_image_quality(page_image)
                    ocr_result = self.ocr.process_image(page_image)
                    page_text = ocr_result.text
                    ocr_confidence = ocr_result.confidence

                    if quality["is_blurry"]:
                        all_warnings.append(
                            ExtractionWarning(
                                document_id=doc_id,
                                warning_type=WarningType.BLURRY_IMAGE,
                                message=f"Page {page_num}: low-quality scan detected (blur score: {quality['blur_score']:.1f}). OCR accuracy may be reduced.",
                                page_number=page_num,
                            )
                        )
                else:
                    page_text = embedded_text
                    ocr_confidence = 0.95  # High confidence for selectable text

                # ── Detect answer key section ──────────────────────────────
                if is_answer_key_section(page_text):
                    page_answers = extract_answers_from_text(page_text)
                    answer_map.update(page_answers)
                    logger.debug("Found answer key on page %d: %s", page_num, page_answers)

                # ── AI Extraction ──────────────────────────────────────────
                raw_questions = self.ai.extract_from_page(
                    page_image=page_image,
                    ocr_text=page_text,
                    page_number=page_num,
                )

                if not raw_questions:
                    logger.debug("No questions found on page %d", page_num)
                    continue

                # ── Parse into ORM models ──────────────────────────────────
                parse_result = self.parser.parse(
                    raw_questions=raw_questions,
                    document_id=doc_id,
                    ocr_confidence=ocr_confidence,
                )
                all_questions.extend(parse_result.questions)
                all_warnings.extend(parse_result.warnings)

            # ── Answer Key Association (within document) ───────────────────
            if answer_map and all_questions:
                from app.models.question import AnswerSource
                all_questions, extra_warnings = associate_answers_to_questions(
                    questions=all_questions,
                    answer_map=answer_map,
                    document_id=doc_id,
                    source=AnswerSource.SAME_DOCUMENT,
                )
                all_warnings.extend(extra_warnings)

            # ── Persist to database ────────────────────────────────────────
            for q in all_questions:
                # Link warning objects to question after save
                db.add(q)
            await db.flush()

            # Now assign question IDs to warnings
            for w in all_warnings:
                db.add(w)

            if all_questions:
                document.status = DocumentStatus.COMPLETED
            else:
                document.status = DocumentStatus.PARTIALLY_PROCESSED
                all_warnings.append(
                    ExtractionWarning(
                        document_id=doc_id,
                        warning_type=WarningType.OTHER,
                        message="No questions could be extracted from this document.",
                    )
                )

        except Exception as exc:
            logger.exception("Fatal error processing document %s", doc_id)
            document.status = DocumentStatus.FAILED
            document.processing_error = str(exc)
            db.add(
                ExtractionWarning(
                    document_id=doc_id,
                    warning_type=WarningType.MALFORMED_FILE,
                    message=f"Processing failed: {exc}",
                )
            )

        finally:
            document.processing_completed_at = datetime.now(timezone.utc)
            await db.flush()

    # ── Page Loading ──────────────────────────────────────────────────────────

    def _load_pages(
        self, document: Document
    ) -> list[tuple[Image.Image, str]]:
        """
        Load document pages as (PIL Image, embedded text) tuples.

        - PDF: renders each page at PAGE_RENDER_DPI using PyMuPDF
        - Image: wraps the single image as a one-element list
        """
        file_path = Path(document.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        if document.file_type == FileType.PDF:
            return self._load_pdf_pages(file_path)
        else:
            return self._load_image_page(file_path)

    def _load_pdf_pages(
        self, path: Path
    ) -> list[tuple[Image.Image, str]]:
        """Render all PDF pages to PIL Images using PyMuPDF."""
        pages = []
        try:
            pdf = fitz.open(str(path))
        except Exception as e:
            raise ValueError(f"Cannot open PDF: {e}") from e

        for page_num in range(len(pdf)):
            page = pdf[page_num]

            # Extract embedded text
            text = page.get_text("text")

            # Render page to image at configured DPI
            mat = fitz.Matrix(settings.PAGE_RENDER_DPI / 72, settings.PAGE_RENDER_DPI / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")

            pages.append((image, text))

        pdf.close()
        return pages

    def _load_image_page(
        self, path: Path
    ) -> list[tuple[Image.Image, str]]:
        """Load a single image file as a one-page document."""
        try:
            image = Image.open(str(path)).convert("RGB")
        except Exception as e:
            raise ValueError(f"Cannot open image: {e}") from e
        return [(image, "")]  # No embedded text in images
