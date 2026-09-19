"""Common Pydantic schemas shared across the API."""
from __future__ import annotations

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Generic success message."""
    message: str


class ErrorResponse(BaseModel):
    """Standard error response body."""
    detail: str
