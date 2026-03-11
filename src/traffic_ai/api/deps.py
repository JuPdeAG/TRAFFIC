"""FastAPI dependencies for authentication and database access."""
from __future__ import annotations
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.api.auth import verify_token
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Decode JWT token and return the authenticated user."""
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_role(role: str):
    """Return a dependency that checks the user has the required role."""
    async def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role != role and user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role \'{role}\' required")
        return user
    return _check
