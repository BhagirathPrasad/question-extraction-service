"""
OCR service — image preprocessing + Tesseract OCR.

Pipeline for each page image:
  1. Convert to grayscale
  2. Detect and correct rotation (deskew)
  3. Denoise
  4. Adaptive threshold for binarization
  5. Run Tesseract with confidence data
  6. Return text + average word confidence
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    text: str
    confidence: float          # 0.0–1.0 average word confidence
    word_count: int
    is_low_quality: bool       # True if confidence < 0.5


class OCRService:
    """
    Wraps Tesseract OCR with preprocessing for scanned/low-quality images.
    """

    # Tesseract page segmentation mode:
    # 6 = Assume a single uniform block of text (good for most exam pages)
    TSM_CONFIG = "--oem 3 --psm 6"

    def process_image(self, image: Image.Image) -> OCRResult:
        """
        Main entry point: preprocess a PIL Image and run OCR.
        Returns structured OCR result with text and confidence.
        """
        try:
            preprocessed = self._preprocess(image)
            return self._run_tesseract(preprocessed)
        except Exception as exc:
            logger.warning("OCR failed: %s", exc)
            return OCRResult(text="", confidence=0.0, word_count=0, is_low_quality=True)

    def process_bytes(self, image_bytes: bytes) -> OCRResult:
        """Convenience: accept raw bytes and delegate to process_image."""
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return self.process_image(image)

    # ── Preprocessing ──────────────────────────────────────────────────────

    def _preprocess(self, image: Image.Image) -> Image.Image:
        """
        Apply a preprocessing pipeline to improve OCR accuracy on:
        - Low-resolution scans
        - Rotated pages
        - Low-contrast documents
        """
        # Convert PIL → OpenCV (numpy BGR)
        cv_img = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)

        # 1. Convert to grayscale
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

        # 2. Upscale if image is small (helps Tesseract)
        h, w = gray.shape
        if w < 1000:
            scale = 1000 / w
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        # 3. Deskew (correct rotation up to ±45°)
        gray = self._deskew(gray)

        # 4. Denoise
        gray = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

        # 5. Adaptive thresholding (binarize)
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=15,
            C=8,
        )

        # 6. Morphological cleanup — remove small noise
        kernel = np.ones((1, 1), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return Image.fromarray(cleaned)

    @staticmethod
    def _deskew(gray: np.ndarray) -> np.ndarray:
        """
        Detect and correct page skew using Hough line transform.
        Skips correction if the detected angle is > 45° (likely a false detection).
        """
        try:
            # Detect edges
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
            if lines is None:
                return gray

            angles = []
            for rho, theta in lines[:, 0]:
                angle = np.degrees(theta) - 90
                if abs(angle) < 45:
                    angles.append(angle)

            if not angles:
                return gray

            median_angle = float(np.median(angles))
            if abs(median_angle) < 0.5:
                return gray  # No significant skew

            h, w = gray.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            rotated = cv2.warpAffine(
                gray, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated
        except Exception:
            return gray

    # ── Tesseract ─────────────────────────────────────────────────────────

    def _run_tesseract(self, image: Image.Image) -> OCRResult:
        """
        Run Tesseract and extract text + per-word confidence scores.
        """
        # Get per-word data for confidence
        data = pytesseract.image_to_data(
            image,
            config=self.TSM_CONFIG,
            output_type=pytesseract.Output.DICT,
        )

        words = []
        confidences = []
        for i, conf in enumerate(data["conf"]):
            try:
                conf_val = int(conf)
            except (ValueError, TypeError):
                continue
            if conf_val == -1:
                continue  # Non-text block
            word = data["text"][i].strip()
            if word:
                words.append(word)
                confidences.append(conf_val / 100.0)  # Normalize to 0-1

        text = pytesseract.image_to_string(image, config=self.TSM_CONFIG).strip()
        avg_confidence = float(np.mean(confidences)) if confidences else 0.0

        return OCRResult(
            text=text,
            confidence=avg_confidence,
            word_count=len(words),
            is_low_quality=avg_confidence < 0.5,
        )

    def detect_image_quality(self, image: Image.Image) -> dict:
        """
        Assess image quality metrics to flag blurry or low-res scans.
        Returns a dict with quality metrics.
        """
        cv_img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)

        # Blur detection via Laplacian variance
        blur_score = cv2.Laplacian(cv_img, cv2.CV_64F).var()
        is_blurry = blur_score < 100

        h, w = cv_img.shape
        is_low_res = w < 800 or h < 600

        return {
            "blur_score": float(blur_score),
            "is_blurry": is_blurry,
            "width": w,
            "height": h,
            "is_low_res": is_low_res,
        }
