"""JWT token creation and verification using python-jose."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from traffic_ai.config import settings


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT token. Returns payload or None."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
