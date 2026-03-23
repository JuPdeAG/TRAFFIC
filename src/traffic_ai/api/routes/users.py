"""User management endpoints (admin only)."""
from __future__ import annotations
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.api.deps import get_current_user, require_admin
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import User
from traffic_ai.models.schemas import UserOut, UserRoleUpdate, UserCreate

router = APIRouter()
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_admin),
) -> list[UserOut]:
    result = await db.execute(select(User).order_by(User.created_at))
    return [UserOut.model_validate(u) for u in result.scalars().all()]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_admin),
) -> UserOut:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        id=uuid.uuid4(),
        email=body.email,
        name=body.name,
        role=body.role,
        password_hash=_pwd.hash(body.password),
    )
    db.add(user)
    await db.flush()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_role(
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_admin),
) -> UserOut:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    user.role = body.role
    await db.flush()
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_admin),
) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.delete(user)
