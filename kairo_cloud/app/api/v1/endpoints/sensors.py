from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.sensor import SensorState, SensorStatusRecord, SensorType
from app.models.user import User
from app.schemas.common import ResponseEnvelope
from app.schemas.sensor import SensorStatusResponse, SensorStatusUpdate
from app.services.auth_service import auth_service, get_current_user

router = APIRouter()


@router.get("/{vehicle_id}", response_model=ResponseEnvelope[List[SensorStatusResponse]])
async def get_sensor_statuses(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves current operational status of all onboard sensors for the given vehicle."""
    # Group or get the latest status per sensor_type
    stmt = (
        select(SensorStatusRecord)
        .where(SensorStatusRecord.vehicle_id == vehicle_id)
        .order_by(SensorStatusRecord.timestamp.desc())
    )
    res = await db.execute(stmt)
    records = res.scalars().all()

    # Deduplicate by sensor_type, keeping the latest
    seen = set()
    latest_per_sensor = []
    for r in records:
        if r.sensor_type not in seen:
            seen.add(r.sensor_type)
            latest_per_sensor.append(SensorStatusResponse.from_orm(r))

    return ResponseEnvelope(success=True, data=latest_per_sensor)


@router.post("/{vehicle_id}/status", response_model=ResponseEnvelope[SensorStatusResponse])
async def update_sensor_status(
    vehicle_id: str,
    update_in: SensorStatusUpdate,
    x_api_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Vehicle Agent reports a state change for an onboard sensor (e.g. LIDAR DEGRADED)."""
    vehicle = await auth_service.verify_vehicle_api_key(vehicle_id, x_api_key or "", db)
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vehicle API key")

    record = SensorStatusRecord(
        vehicle_id=vehicle_id,
        sensor_type=update_in.sensor_type,
        status=update_in.status,
        message=update_in.message,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return ResponseEnvelope(
        success=True,
        data=SensorStatusResponse.from_orm(record),
        message="Sensor status updated"
    )
