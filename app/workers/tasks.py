"""
Celery tasks — asynchronous document processing.

Celery workers are synchronous; we use asyncio.run() to bridge into
the async SQLAlchemy/document processor layer.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_document_task",
    max_retries=3,
    default_retry_delay=30,  # seconds
    soft_time_limit=600,     # 10 minutes soft limit
    time_limit=660,          # 11 minutes hard kill limit
)
def process_document_task(self, document_id: str) -> dict:
    """
    Celery task: process an uploaded document asynchronously.

    Args:
        document_id: UUID string of the document to process.

    Returns:
        Dict with processing result metadata.

    Retries up to 3 times on transient failures (network issues, etc.)
    Does NOT retry on fatal errors (file not found, corrupt file).
    """
    logger.info("Starting task for document %s", document_id)

    try:
        result = asyncio.run(_async_process(document_id))
        logger.info("Task completed for document %s — status: %s", document_id, result.get("status"))
        return result
    except FileNotFoundError as exc:
        # Fatal — don't retry
        logger.error("Document file not found, won't retry: %s", exc)
        return {"document_id": document_id, "status": "FAILED", "error": str(exc)}
    except Exception as exc:
        logger.warning(
            "Task failed for document %s (attempt %d): %s",
            document_id, self.request.retries + 1, exc
        )
        raise self.retry(exc=exc)


async def _async_process(document_id: str) -> dict:
    """
    Async processing body — runs inside asyncio.run() from the Celery task.
    """
    from app.database import async_session_factory
    from app.models.document import Document
    from app.services.document_processor import DocumentProcessor

    doc_uuid = uuid.UUID(document_id)
    processor = DocumentProcessor()

    async with async_session_factory() as session:
        try:
            # Fetch document
            result = await session.execute(
                select(Document).where(Document.id == doc_uuid)
            )
            document = result.scalar_one_or_none()

            if not document:
                raise FileNotFoundError(f"Document {document_id} not found in database")

            # Run full processing pipeline
            await processor.process(document=document, db=session)
            await session.commit()

            return {
                "document_id": document_id,
                "status": document.status.value,
                "page_count": document.page_count,
            }

        except Exception:
            await session.rollback()
            raise
