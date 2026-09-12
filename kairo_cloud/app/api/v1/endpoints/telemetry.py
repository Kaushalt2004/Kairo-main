from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.common import ResponseEnvelope
from app.schemas.telemetry import TelemetryPayload, TelemetrySnapshot
from app.services.auth_service import auth_service, get_current_user
from app.services.telemetry_service import telemetry_service

router = APIRouter()


@router.get("/{vehicle_id}/latest", response_model=ResponseEnvelope[Dict[str, Any]])
async def get_latest_telemetry(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetches the latest real-time telemetry frame for a vehicle from the Redis cache or DB."""
    payload = await telemetry_service.get_latest_telemetry(vehicle_id, db)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry data found for vehicle {vehicle_id}"
        )
    return ResponseEnvelope(success=True, data=payload)


@router.get("/{vehicle_id}/history", response_model=ResponseEnvelope[List[TelemetrySnapshot]])
async def get_telemetry_history(
    vehicle_id: str,
    start_time: Optional[datetime] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[datetime] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to retrieve"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves downsampled historical telemetry snapshots for timeline analysis or playback."""
    records = await telemetry_service.get_historical_telemetry(
        vehicle_id=vehicle_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        db=db
    )
    snapshots = [TelemetrySnapshot.from_orm(r) for r in records]
    return ResponseEnvelope(success=True, data=snapshots)


@router.post("/{vehicle_id}/ingest", response_model=ResponseEnvelope[bool])
async def rest_ingest_telemetry(
    vehicle_id: str,
    payload: TelemetryPayload,
    x_api_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """REST HTTP ingestion fallback for agents where WebSocket outbound is restricted."""
    vehicle = await auth_service.verify_vehicle_api_key(vehicle_id, x_api_key or "", db)
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vehicle API key")

    payload_dict = payload.model_dump(mode="json")
    await telemetry_service.ingest_telemetry(vehicle_id, payload_dict, db)
    return ResponseEnvelope(success=True, data=True, message="Telemetry ingested")
