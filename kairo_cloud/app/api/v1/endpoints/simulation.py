from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.command import CommandType
from app.models.simulation import SimulationSession, SimulationState
from app.models.user import User, UserRole
from app.schemas.command import CommandCreate
from app.schemas.common import ResponseEnvelope
from app.schemas.simulation import SimulationSessionResponse
from app.services.auth_service import get_current_user, require_role
from app.services.command_service import command_service

router = APIRouter()


class StartSimRequest(BaseModel):
    scenario: str = Field(default="Town01_Standard")
    map_name: str = Field(default="Town01")
    weather: str = Field(default="ClearNoon")
    time_of_day: float = Field(default=12.0, ge=0.0, le=24.0)


class WeatherRequest(BaseModel):
    weather: str = Field(..., example="WetCloudyNoon")


class TimeRequest(BaseModel):
    hour: float = Field(..., ge=0.0, le=24.0, example=17.5)


@router.get("/{vehicle_id}/status", response_model=ResponseEnvelope[Optional[SimulationSessionResponse]])
async def get_simulation_status(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves the active or most recent simulation session for the vehicle."""
    stmt = (
        select(SimulationSession)
        .where(SimulationSession.vehicle_id == vehicle_id)
        .order_by(SimulationSession.started_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    data = SimulationSessionResponse.from_orm(session) if session else None
    return ResponseEnvelope(success=True, data=data)


@router.post("/{vehicle_id}/start", response_model=ResponseEnvelope[SimulationSessionResponse])
async def start_simulation(
    vehicle_id: str,
    sim_req: StartSimRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Starts a new simulation run in CARLA/simulator and creates tracking session."""
    session = SimulationSession(
        vehicle_id=vehicle_id,
        scenario_name=sim_req.scenario,
        map_name=sim_req.map_name,
        weather=sim_req.weather,
        time_of_day=sim_req.time_of_day,
        state=SimulationState.RUNNING,
        started_at=datetime.now(timezone.utc)
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Issue command to vehicle agent
    await command_service.issue_command(
        vehicle_id=vehicle_id,
        command_in=CommandCreate(
            command_type=CommandType.START_SIMULATION,
            parameters={
                "session_id": session.id,
                "scenario": sim_req.scenario,
                "map": sim_req.map_name,
                "weather": sim_req.weather,
                "time_of_day": sim_req.time_of_day
            }
        ),
        user_id=current_user.id,
        db=db
    )

    return ResponseEnvelope(
        success=True,
        data=SimulationSessionResponse.from_orm(session),
        message="Simulation started"
    )


@router.post("/{vehicle_id}/stop", response_model=ResponseEnvelope[Optional[SimulationSessionResponse]])
async def stop_simulation(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Stops the active simulation run."""
    stmt = (
        select(SimulationSession)
        .where(SimulationSession.vehicle_id == vehicle_id, SimulationSession.state == SimulationState.RUNNING)
        .order_by(SimulationSession.started_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if session:
        session.state = SimulationState.STOPPED
        session.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(session)

    await command_service.issue_command(
        vehicle_id=vehicle_id,
        command_in=CommandCreate(command_type=CommandType.STOP_SIMULATION, parameters={}),
        user_id=current_user.id,
        db=db
    )

    data = SimulationSessionResponse.from_orm(session) if session else None
    return ResponseEnvelope(success=True, data=data, message="Simulation stopped")


@router.post("/{vehicle_id}/weather", response_model=ResponseEnvelope[bool])
async def change_weather(
    vehicle_id: str,
    weather_req: WeatherRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Dynamically modifies environment weather preset (e.g. WetNoon, HardRainNoon)."""
    await command_service.issue_command(
        vehicle_id=vehicle_id,
        command_in=CommandCreate(
            command_type=CommandType.CHANGE_WEATHER,
            parameters={"weather": weather_req.weather}
        ),
        user_id=current_user.id,
        db=db
    )
    return ResponseEnvelope(success=True, data=True, message=f"Weather change to {weather_req.weather} queued")


@router.post("/{vehicle_id}/time", response_model=ResponseEnvelope[bool])
async def change_time(
    vehicle_id: str,
    time_req: TimeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Dynamically alters simulated time of day (0.0 - 24.0 hours)."""
    await command_service.issue_command(
        vehicle_id=vehicle_id,
        command_in=CommandCreate(
            command_type=CommandType.CHANGE_TIME,
            parameters={"hour": time_req.hour}
        ),
        user_id=current_user.id,
        db=db
    )
    return ResponseEnvelope(success=True, data=True, message=f"Time change to {time_req.hour}:00 queued")
