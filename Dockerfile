# ─────────────────────────────────────────────────────────────────────────────
# Question Extraction Service — Dockerfile
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# System dependencies
# - tesseract-ocr: OCR engine for scanned documents
# - tesseract-ocr-eng: English language pack
# - libmagic1: MIME-type detection for uploaded files
# - libgl1: Required by OpenCV
# - poppler-utils: PDF utilities (optional, for fallback)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
FROM base AS app

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Non-root user for security
RUN useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default: run API server (overridden in docker-compose for worker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
