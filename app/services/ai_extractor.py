"""
AI extractor — uses Google Gemini 1.5 Flash (Vision) to extract structured
questions from document page images.

Falls back gracefully to regex-based extraction if Gemini API key is not set.
"""
from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RawQuestion:
    """Raw question data as returned by the AI extractor."""
    question_number: Optional[str]
    question_text: str
    options: list[dict]           # [{"label": "A", "text": "..."}]
    question_type: str            # "MCQ", "SHORT_ANSWER", etc.
    answer: Optional[str]
    confidence: float
    is_cross_page: bool
    has_image: bool
    has_table: bool
    extraction_notes: str
    source_page: int


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Prompt
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an expert document analyst specializing in educational exam papers.

Analyze the provided page image carefully and extract ALL exam questions visible on this page.

For each question found, return a JSON object with this EXACT structure:
{{
  "question_number": "1" or null,
  "question_text": "Complete question text here",
  "options": [
    {{"label": "A", "text": "First option text"}},
    {{"label": "B", "text": "Second option text"}}
  ],
  "question_type": "MCQ" or "TRUE_FALSE" or "SHORT_ANSWER" or "LONG_ANSWER" or "FILL_IN_BLANK" or "MATCH" or "UNKNOWN",
  "answer": "A" or null,
  "confidence": 0.95,
  "is_cross_page": false,
  "has_image": false,
  "has_table": false,
  "extraction_notes": ""
}}

IMPORTANT RULES:
- Extract EVERY question, even if partially visible or cut off
- For MCQ questions, include ALL options with their labels (A/B/C/D or (a)/(b)/(c)/(d) or 1/2/3/4)
- If answer key information is present on this page, extract the answer
- Set confidence < 0.6 if text is blurry, unclear, or incomplete  
- Set is_cross_page=true if a question appears to continue beyond this page or starts from a previous page
- Set has_image=true if the question references or contains a diagram, figure, or image
- Set has_table=true if the question contains a table
- Fill extraction_notes with any issues, OCR concerns, or uncertainties

Additional OCR text from this page for reference:
{ocr_text}

Return ONLY a valid JSON array of question objects. No markdown, no explanation, just the JSON array.
If no questions are found, return an empty array: []"""


# ─────────────────────────────────────────────────────────────────────────────
# AI Extractor
# ─────────────────────────────────────────────────────────────────────────────

class AIExtractor:
    """
    Extracts structured questions from page images using Gemini Vision.
    Falls back to regex-based extraction when Gemini is unavailable.
    """

    def __init__(self) -> None:
        self._gemini_client = None
        if settings.is_gemini_enabled:
            self._init_gemini()

    def _init_gemini(self) -> None:
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._gemini_client = genai.GenerativeModel(settings.GEMINI_MODEL)
            logger.info("Gemini AI extractor initialized (model: %s)", settings.GEMINI_MODEL)
        except Exception as e:
            logger.error("Failed to initialize Gemini: %s — falling back to regex", e)
            self._gemini_client = None

    def extract_from_page(
        self,
        page_image: Image.Image,
        ocr_text: str,
        page_number: int,
    ) -> list[RawQuestion]:
        """
        Extract questions from a single page image.

        Uses Gemini Vision if available, otherwise falls back to regex parser.
        """
        if self._gemini_client:
            try:
                return self._extract_with_gemini(page_image, ocr_text, page_number)
            except Exception as e:
                logger.warning(
                    "Gemini extraction failed on page %d: %s — using fallback", page_number, e
                )

        # Fallback: regex-based extraction from OCR text
        return self._extract_with_regex(ocr_text, page_number)

    # ── Gemini ─────────────────────────────────────────────────────────────

    def _extract_with_gemini(
        self,
        page_image: Image.Image,
        ocr_text: str,
        page_number: int,
    ) -> list[RawQuestion]:
        """Send page image + OCR text to Gemini and parse the response."""
        prompt = EXTRACTION_PROMPT.format(ocr_text=ocr_text[:3000] if ocr_text else "N/A")

        # Convert PIL image to bytes for Gemini
        img_bytes = io.BytesIO()
        page_image.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        import google.generativeai as genai
        image_part = {
            "mime_type": "image/png",
            "data": img_bytes.getvalue(),
        }

        response = self._gemini_client.generate_content(
            [prompt, image_part],
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,       # Low temperature for consistent structured output
                max_output_tokens=8192,
            ),
        )

        raw_text = response.text.strip()
        return self._parse_gemini_response(raw_text, page_number)

    def _parse_gemini_response(
        self, raw_text: str, page_number: int
    ) -> list[RawQuestion]:
        """Parse Gemini's JSON response into RawQuestion objects."""
        # Strip markdown code fences if present
        json_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        json_text = re.sub(r"\s*```$", "", json_text, flags=re.MULTILINE).strip()

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            # Try to extract JSON array with regex
            match = re.search(r"\[.*\]", json_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.warning("Could not parse Gemini response as JSON")
                    return []
            else:
                return []

        if not isinstance(data, list):
            data = [data] if isinstance(data, dict) else []

        questions = []
        for item in data:
            if not isinstance(item, dict):
                continue
            question_text = item.get("question_text", "").strip()
            if not question_text:
                continue

            questions.append(
                RawQuestion(
                    question_number=item.get("question_number"),
                    question_text=question_text,
                    options=self._normalize_options(item.get("options", [])),
                    question_type=item.get("question_type", "UNKNOWN"),
                    answer=item.get("answer"),
                    confidence=float(item.get("confidence", 0.7)),
                    is_cross_page=bool(item.get("is_cross_page", False)),
                    has_image=bool(item.get("has_image", False)),
                    has_table=bool(item.get("has_table", False)),
                    extraction_notes=item.get("extraction_notes", ""),
                    source_page=page_number,
                )
            )
        return questions

    # ── Regex Fallback ─────────────────────────────────────────────────────

    def _extract_with_regex(self, ocr_text: str, page_number: int) -> list[RawQuestion]:
        """
        Regex-based fallback extractor.
        Handles common question numbering formats:
          - "1.", "Q1.", "Q.1", "1)", "(1)"
          - Roman numerals: "i.", "ii.", "iii."
        """
        if not ocr_text.strip():
            return []

        # Patterns for question start
        patterns = [
            r"(?:^|\n)\s*(?:Q\.?\s*)?(\d+)[.)]\s+(.+?)(?=(?:\n\s*(?:Q\.?\s*)?\d+[.)]\s+)|\Z)",
            r"(?:^|\n)\s*\((\d+)\)\s+(.+?)(?=(?:\n\s*\(\d+\)\s+)|\Z)",
        ]

        questions = []
        for pattern in patterns:
            matches = re.findall(pattern, ocr_text, re.DOTALL | re.MULTILINE)
            if matches:
                for num, text in matches:
                    text = text.strip()
                    if len(text) < 10:
                        continue

                    options = self._extract_options_from_text(text)
                    question_type = "MCQ" if options else "UNKNOWN"
                    # Remove options from question text
                    clean_text = self._remove_options_from_text(text) if options else text

                    questions.append(
                        RawQuestion(
                            question_number=str(num),
                            question_text=clean_text.strip(),
                            options=options,
                            question_type=question_type,
                            answer=None,
                            confidence=0.55,  # Regex extraction is less reliable
                            is_cross_page=False,
                            has_image=False,
                            has_table=False,
                            extraction_notes="Extracted via regex fallback (Gemini not available)",
                            source_page=page_number,
                        )
                    )
                if questions:
                    break  # Use first pattern that finds questions

        return questions

    def _extract_options_from_text(self, text: str) -> list[dict]:
        """Extract MCQ options from question text."""
        options = []
        # Pattern: (A) or A. or A) followed by text
        option_pattern = re.findall(
            r"[\(\[]?([A-Ea-e])[\).\]]\s+(.+?)(?=[\(\[]?[A-Ea-e][\).\]]\s+|$)",
            text,
            re.MULTILINE,
        )
        for label, opt_text in option_pattern:
            clean_text = opt_text.strip()
            if clean_text:
                options.append({"label": label.upper(), "text": clean_text})
        return options

    def _remove_options_from_text(self, text: str) -> str:
        """Strip option lines from question text."""
        return re.sub(
            r"[\(\[]?[A-Ea-e][\).\]]\s+.+",
            "",
            text,
            flags=re.MULTILINE,
        ).strip()

    @staticmethod
    def _normalize_options(options: list) -> list[dict]:
        """Ensure options are in {"label": ..., "text": ...} format."""
        normalized = []
        for opt in options:
            if isinstance(opt, dict):
                label = str(opt.get("label", "")).strip()
                text = str(opt.get("text", "")).strip()
                if label and text:
                    normalized.append({"label": label, "text": text})
        return normalized
