"""
Application configuration — loaded from environment variables / .env file.
All secrets must be set via environment; never hard-code them here.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────
    APP_NAME: str = "Question Extraction Service"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = False

    # ── Database ───────────────────────────────────────────────────────────
    # Async URL (asyncpg) — used by FastAPI routes
    DATABASE_URL: str = (
        "postgresql+asyncpg://qes_user:qes_password@localhost:5432/question_extraction"
    )
    # Sync URL (psycopg2) — used by Alembic migrations
    DATABASE_URL_SYNC: str = ""

    @model_validator(mode="after")
    def derive_sync_url(self) -> "Settings":
        if not self.DATABASE_URL_SYNC:
            self.DATABASE_URL_SYNC = self.DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        return self

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT / Auth ─────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # ── File Storage ───────────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: list[str] = ["pdf", "jpg", "jpeg", "png"]
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
    ]

    # ── Google Gemini ──────────────────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # ── Celery ─────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # ── Processing ─────────────────────────────────────────────────────────
    PAGE_RENDER_DPI: int = 200          # DPI for PDF page rendering
    MIN_TEXT_CHARS_PER_PAGE: int = 50   # Below this → treat page as scanned
    CONFIDENCE_HIGH: float = 0.85
    CONFIDENCE_MEDIUM: float = 0.60

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def is_gemini_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
