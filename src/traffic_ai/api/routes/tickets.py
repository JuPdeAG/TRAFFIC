"""Maintenance ticket endpoints."""
from __future__ import annotations
import logging
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.api.deps import get_current_user
from traffic_ai.config import settings
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import MaintenanceTicket, User
from traffic_ai.models.schemas import TicketOut, TicketUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    status: str | None = None,
    pilot: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TicketOut]:
    """List maintenance tickets with optional filters."""
    stmt = select(MaintenanceTicket)
    if status:
        stmt = stmt.where(MaintenanceTicket.status == status)
    if pilot:
        stmt = stmt.where(MaintenanceTicket.pilot == pilot)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [TicketOut.model_validate(t) for t in result.scalars().all()]


@router.get("/tickets/assigned/{user_id}", response_model=list[TicketOut])
async def tickets_by_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> list[TicketOut]:
    """List tickets assigned to a specific user."""
    result = await db.execute(select(MaintenanceTicket).where(MaintenanceTicket.assigned_to == user_id))
    return [TicketOut.model_validate(t) for t in result.scalars().all()]


@router.put("/tickets/{ticket_id}/status", response_model=TicketOut)
async def update_ticket_status(
    ticket_id: int,
    update: TicketUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    """Update the status of a maintenance ticket."""
    result = await db.execute(select(MaintenanceTicket).where(MaintenanceTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.status = update.status
    if update.resolution_note:
        ticket.description = (ticket.description or "") + f"\n[Resolution] {update.resolution_note}"
    if update.status in ("resolved", "closed"):
        from datetime import datetime, timezone
        ticket.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return TicketOut.model_validate(ticket)


@router.post("/tickets/{ticket_id}/photo")
async def upload_ticket_photo(
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    photo: UploadFile = File(...),
) -> dict:
    """Upload a photo attachment to a ticket."""
    result = await db.execute(select(MaintenanceTicket).where(MaintenanceTicket.id == ticket_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    contents = await photo.read()
    content_type = photo.content_type or "application/octet-stream"
    logger.info(
        "Ticket %d photo upload: filename=%s, size=%d bytes, content_type=%s",
        ticket_id, photo.filename, len(contents), content_type,
    )

    s3_key = None
    if settings.s3_bucket:
        # TODO: Real S3 upload via boto3
        try:
            import boto3
            s3 = boto3.client("s3", region_name=settings.aws_region)
            s3_key = f"tickets/{ticket_id}/{photo.filename}"
            s3.put_object(
                Bucket=settings.s3_bucket, Key=s3_key,
                Body=contents, ContentType=content_type,
            )
            logger.info("Uploaded ticket photo to s3://%s/%s", settings.s3_bucket, s3_key)
        except Exception:
            logger.exception("Failed to upload ticket photo to S3")
            s3_key = None
    else:
        logger.warning("S3_BUCKET not configured, skipping photo upload to S3")

    return {
        "ticket_id": ticket_id,
        "filename": photo.filename,
        "size_bytes": len(contents),
        "content_type": content_type,
        "s3_key": s3_key,
        "status": "uploaded" if s3_key else "received",
    }
