from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.command import CommandRecord
from app.models.user import User, UserRole
from app.schemas.command import CommandCreate, CommandResponse
from app.schemas.common import ResponseEnvelope
from app.services.auth_service import get_current_user, require_role
from app.services.command_service import command_service

router = APIRouter()


@router.post("/{vehicle_id}", response_model=ResponseEnvelope[CommandResponse], status_code=status.HTTP_202_ACCEPTED)
async def send_command(
    vehicle_id: str,
    command_in: CommandCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.ADMIN, UserRole.OPERATOR]))
):
    """Dispatches a whitelisted command to the designated vehicle."""
    cmd_record = await command_service.issue_command(
        vehicle_id=vehicle_id,
        command_in=command_in,
        user_id=current_user.id,
        db=db
    )
    return ResponseEnvelope(
        success=True,
        data=CommandResponse.from_orm(cmd_record),
        message=f"Command {cmd_record.command_type.value} issued ({cmd_record.status.value})"
    )


@router.get("/{vehicle_id}", response_model=ResponseEnvelope[List[CommandResponse]])
async def list_commands(
    vehicle_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves recent command audit logs for a vehicle."""
    records = await command_service.get_commands_for_vehicle(vehicle_id=vehicle_id, limit=limit, db=db)
    return ResponseEnvelope(
        success=True,
        data=[CommandResponse.from_orm(r) for r in records]
    )


@router.get("/{vehicle_id}/{command_id}", response_model=ResponseEnvelope[CommandResponse])
async def get_command_status(
    vehicle_id: str,
    command_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Queries execution state and result of a specific command."""
    stmt = select(CommandRecord).where(
        CommandRecord.id == command_id,
        CommandRecord.vehicle_id == vehicle_id
    )
    res = await db.execute(stmt)
    cmd = res.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Command {command_id} not found")

    return ResponseEnvelope(
        success=True,
        data=CommandResponse.from_orm(cmd)
    )
