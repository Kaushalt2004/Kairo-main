from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.event import EventRecord, EventSeverity
from app.models.user import User
from app.schemas.common import ResponseEnvelope
from app.schemas.event import EventCreate, EventResponse
from app.services.auth_service import auth_service, get_current_user

router = APIRouter()


@router.get("/{vehicle_id}", response_model=ResponseEnvelope[List[EventResponse]])
async def get_vehicle_events(
    vehicle_id: str,
    severity: Optional[EventSeverity] = Query(None, description="Filter by severity"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves critical events, takeover logs, and safety notifications for the vehicle."""
    stmt = select(EventRecord).where(EventRecord.vehicle_id == vehicle_id)
    if severity:
        stmt = stmt.where(EventRecord.severity == severity)
    stmt = stmt.order_by(EventRecord.timestamp.desc()).limit(limit)

    res = await db.execute(stmt)
    records = res.scalars().all()
    return ResponseEnvelope(
        success=True,
        data=[EventResponse.from_orm(r) for r in records]
    )


@router.post("/{vehicle_id}", response_model=ResponseEnvelope[EventResponse], status_code=status.HTTP_201_CREATED)
async def create_event(
    vehicle_id: str,
    event_in: EventCreate,
    x_api_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Vehicle Agent reports an operational event (e.g. TAKEOVER_REQUESTED, COLLISION_AVOIDED)."""
    vehicle = await auth_service.verify_vehicle_api_key(vehicle_id, x_api_key or "", db)
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vehicle API key")

    record = EventRecord(
        vehicle_id=vehicle_id,
        event_type=event_in.event_type,
        severity=event_in.severity,
        description=event_in.description,
        details=event_in.details,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return ResponseEnvelope(
        success=True,
        data=EventResponse.from_orm(record),
        message="Event logged"
    )
