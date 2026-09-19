"""JWT creation/verification and password hashing utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(plain_password: str) -> str:
    """Return bcrypt hash of a plain-text password."""
    pwd_bytes = plain_password[:72].encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored hash."""
    pwd_bytes = plain_password[:72].encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: Typically the user's UUID as a string.
        expires_delta: Custom expiry; defaults to settings.ACCESS_TOKEN_EXPIRE_MINUTES.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """
    Decode and verify a JWT access token.

    Returns:
        The subject (user ID) if token is valid, None otherwise.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload.get("sub")
    except JWTError:
        return None
