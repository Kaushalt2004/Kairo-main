from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import redis_manager
from app.core.security import generate_api_key, hash_api_key
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, VehicleStatus
from app.schemas.common import ResponseEnvelope
from app.schemas.vehicle import (
    VehicleRegisterRequest,
    VehicleRegisterResponse,
    VehicleResponse,
    VehicleStatusUpdate,
)
from app.services.auth_service import get_current_user, require_role
from app.services.connection_manager import connection_manager
from app.services.telemetry_service import telemetry_service

router = APIRouter()


@router.post("/register", response_model=ResponseEnvelope[VehicleRegisterResponse], status_code=status.HTTP_201_CREATED)
async def register_vehicle(
    vehicle_in: VehicleRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Registers a new vehicle in the fleet and generates a cryptographically secure API key."""
    stmt = select(Vehicle).where(Vehicle.id == vehicle_in.id)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vehicle with ID {vehicle_in.id} already exists"
        )

    # Generate plaintext API key and SHA-256 hash
    plaintext_key = generate_api_key(prefix=f"kairo_{vehicle_in.id.lower().replace('-', '_')}")
    key_hash = hash_api_key(plaintext_key)

    new_vehicle = Vehicle(
        id=vehicle_in.id,
        name=vehicle_in.name,
        vin=vehicle_in.vin,
        model=vehicle_in.model,
        simulator_type=vehicle_in.simulator_type,
        api_key_hash=key_hash,
        status=VehicleStatus.OFFLINE,
        is_active=True
    )
    db.add(new_vehicle)
    await db.commit()
    await db.refresh(new_vehicle)

    return ResponseEnvelope(
        success=True,
        data=VehicleRegisterResponse(
            id=new_vehicle.id,
            name=new_vehicle.name,
            simulator_type=new_vehicle.simulator_type,
            status=new_vehicle.status,
            api_key=plaintext_key,
            created_at=new_vehicle.created_at
        ),
        message="Vehicle registered successfully. Store the API key safely."
    )


@router.get("", response_model=ResponseEnvelope[List[VehicleResponse]])
async def list_vehicles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all registered vehicles in the fleet with their live connection status."""
    stmt = select(Vehicle).order_by(Vehicle.id.asc())
    res = await db.execute(stmt)
    vehicles = res.scalars().all()

    response_items = []
    for v in vehicles:
        is_connected = connection_manager.is_vehicle_connected(v.id) or await redis_manager.is_vehicle_online(v.id)
        latest_tel = await telemetry_service.get_latest_telemetry(v.id, db)
        
        # Effective status
        eff_status = v.status
        if is_connected and eff_status == VehicleStatus.OFFLINE:
            eff_status = VehicleStatus.ONLINE
        elif not is_connected and eff_status == VehicleStatus.ONLINE:
            eff_status = VehicleStatus.OFFLINE

        resp_obj = VehicleResponse(
            id=v.id,
            org_id=v.org_id,
            name=v.name,
            vin=v.vin,
            model=v.model,
            simulator_type=v.simulator_type,
            status=eff_status,
            is_active=v.is_active,
            created_at=v.created_at,
            updated_at=v.updated_at,
            is_connected=is_connected,
            latest_telemetry=latest_tel
        )
        response_items.append(resp_obj)

    return ResponseEnvelope(success=True, data=response_items)


@router.get("/{vehicle_id}", response_model=ResponseEnvelope[VehicleResponse])
async def get_vehicle(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns details and live state for a single vehicle."""
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    res = await db.execute(stmt)
    v = res.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vehicle {vehicle_id} not found")

    is_connected = connection_manager.is_vehicle_connected(v.id) or await redis_manager.is_vehicle_online(v.id)
    latest_tel = await telemetry_service.get_latest_telemetry(v.id, db)

    resp_obj = VehicleResponse(
        id=v.id,
        org_id=v.org_id,
        name=v.name,
        vin=v.vin,
        model=v.model,
        simulator_type=v.simulator_type,
        status=VehicleStatus.ONLINE if is_connected else v.status,
        is_active=v.is_active,
        created_at=v.created_at,
        updated_at=v.updated_at,
        is_connected=is_connected,
        latest_telemetry=latest_tel
    )
    return ResponseEnvelope(success=True, data=resp_obj)


@router.put("/{vehicle_id}/status", response_model=ResponseEnvelope[VehicleResponse])
async def update_vehicle_status(
    vehicle_id: str,
    status_update: VehicleStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Updates vehicle status (e.g., MAINTENANCE, STANDBY)."""
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    res = await db.execute(stmt)
    v = res.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vehicle {vehicle_id} not found")

    v.status = status_update.status
    v.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(v)

    is_connected = connection_manager.is_vehicle_connected(v.id)
    latest_tel = await telemetry_service.get_latest_telemetry(v.id, db)

    resp_obj = VehicleResponse(
        id=v.id,
        org_id=v.org_id,
        name=v.name,
        vin=v.vin,
        model=v.model,
        simulator_type=v.simulator_type,
        status=v.status,
        is_active=v.is_active,
        created_at=v.created_at,
        updated_at=v.updated_at,
        is_connected=is_connected,
        latest_telemetry=latest_tel
    )
    return ResponseEnvelope(success=True, data=resp_obj, message="Vehicle status updated")


@router.delete("/{vehicle_id}", response_model=ResponseEnvelope[bool])
async def delete_vehicle(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN]))
):
    """De-registers and removes a vehicle from the platform."""
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    res = await db.execute(stmt)
    v = res.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vehicle {vehicle_id} not found")

    await db.delete(v)
    await db.commit()
    return ResponseEnvelope(success=True, data=True, message=f"Vehicle {vehicle_id} deleted")
