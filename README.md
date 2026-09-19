# Question Extraction Service

A scalable FastAPI service that accepts PDF/image documents (exam papers/question banks), processes them asynchronously using OCR and AI (Google Gemini 1.5 Flash), and extracts structured, machine-readable questions.

## Features
- **Async Processing:** Upload large PDFs; extraction happens in the background via Celery + Redis.
- **AI Extraction:** Uses Gemini Vision for high-quality extraction of questions, options, types, and answers.
- **Fallback OCR:** Includes a local Tesseract OCR fallback with OpenCV preprocessing (deskew, denoise) for imperfect scans.
- **Answer Key Matching:** Automatically matches answer key entries within the same document or across linked documents via "Document Groups".
- **Confidence Scoring:** Flags low-confidence extractions, missing options, and cross-page questions for human review.
- **Robust APIs:** Full JWT authentication, document management, and structured question retrieval endpoints.

## Technology Stack
- **API:** FastAPI, Pydantic
- **Database:** PostgreSQL (asyncpg), SQLAlchemy 2.0, Alembic
- **Queue:** Celery, Redis
- **File Parsing:** PyMuPDF (`fitz`), Pillow, OpenCV, Tesseract OCR
- **AI/LLM:** Google Generative AI (Gemini 1.5 Flash)
- **Containerization:** Docker, Docker Compose

---

## Quickstart (Docker Compose)

The easiest way to run the service is using Docker Compose.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/BhagirathPrasad/question-extraction-service.git
   cd question-extraction-service
   ```

2. **Configure Environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set `GEMINI_API_KEY` to your Google AI Studio API key. (If you don't provide one, it will fall back to regex-based Tesseract OCR which has much lower accuracy).

3. **Start the services:**
   ```bash
   docker-compose up -d --build
   ```

4. **Access the Application:**
   - Interactive API Docs (Swagger UI): http://localhost:8000/docs
   - The database migrations are applied automatically on startup.

---

## Local Development (Without Docker)

### Requirements
- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Tesseract OCR (`brew install tesseract` or `apt-get install tesseract-ocr`)
- `libmagic` (for file type detection)

### Setup

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup database
# Ensure PostgreSQL is running, create database "question_extraction"
# Configure DATABASE_URL in .env
alembic upgrade head

# 4. Start Redis
# Ensure Redis is running locally on port 6379

# 5. Start the Celery Worker (in a separate terminal)
celery -A app.workers.celery_app worker --loglevel=info

# 6. Start the FastAPI server
uvicorn app.main:app --reload
```

---

## Deliverables Overview

| Deliverable | Location | Description |
| :--- | :--- | :--- |
| **1. Source Code** | `app/` | Complete FastAPI backend, Celery workers, and OCR/AI services |
| **2. Database Schema & Migrations** | `migrations/`, `app/models/` | Alembic async migrations and SQLAlchemy 2.0 ORM models |
| **3. Sample Input Documents** | `sample_documents/` | Multi-page exam PDF, question image, and separate answer key |
| **4. Sample Extracted Output** | `sample_output/` | Structured JSON output representing clean & review-required data |
| **5. Setup & Configuration** | `README.md`, `.env.example` | Clear environment setup and single-command Docker launch |
| **6. Architecture Documentation** | `docs/ARCHITECTURE.md` | In-depth design documentation with Mermaid architecture diagrams |
| **7. Automated Tests** | `tests/` | Pytest test suite covering auth and document processing |
| **8. Postman Collection** | `postman/question_extraction_api.json` | Ready-to-import Postman collection covering all workflows |
| **9. OpenAPI / Swagger Spec** | `docs/openapi.json`, `/docs` | Interactive Swagger UI and exported OpenAPI 3.0 JSON specification |

---

## Testing

Run automated tests directly inside the Docker container:

```bash
docker exec -e PYTHONPATH=. pbnc-api-1 pytest
```

---

## API Usage Flow

1. `POST /auth/register` to create an account.
2. `POST /auth/login` to get a JWT token.
3. Include the token in the `Authorization: Bearer <token>` header for subsequent requests.
4. `POST /documents/upload` with a PDF or image file. It returns a `document_id`.
5. `GET /documents/{document_id}/status` to poll until `status` is `COMPLETED`.
6. `GET /documents/{document_id}/questions` to retrieve the extracted questions.
7. `GET /documents/{document_id}/warnings` to view any extraction issues requiring review.

See `/docs` (Swagger UI) for the interactive documentation.
