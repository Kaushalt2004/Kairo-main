import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.command import CommandRecord, CommandStatus, CommandType
from app.models.vehicle import Vehicle
from app.schemas.command import CommandAck, CommandCreate
from app.services.connection_manager import connection_manager

logger = logging.getLogger(__name__)


class CommandService:
    """Service handling secure dispatch and lifecycle management of vehicle commands."""

    async def issue_command(
        self,
        vehicle_id: str,
        command_in: CommandCreate,
        user_id: Optional[str],
        db: AsyncSession
    ) -> CommandRecord:
        """Validates command, persists audit record, and dispatches to connected vehicle."""
        # Verify vehicle exists
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        res = await db.execute(stmt)
        vehicle = res.scalar_one_or_none()
        if not vehicle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vehicle {vehicle_id} not found")

        # Create audit record
        command_record = CommandRecord(
            vehicle_id=vehicle_id,
            command_type=command_in.command_type,
            parameters=command_in.parameters,
            status=CommandStatus.PENDING,
            issued_by_user_id=user_id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(command_record)
        await db.commit()
        await db.refresh(command_record)

        # Attempt dispatch via WebSocket
        payload_to_vehicle = {
            "command_id": command_record.id,
            "command_type": command_record.command_type.value,
            "parameters": command_record.parameters,
            "timestamp": command_record.created_at.isoformat()
        }

        sent = await connection_manager.send_vehicle_command(vehicle_id, payload_to_vehicle)
        if sent:
            command_record.status = CommandStatus.DELIVERED
            command_record.delivered_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(command_record)

        return command_record

    async def handle_vehicle_ack(
        self,
        ack_data: Dict[str, Any],
        db: AsyncSession
    ) -> Optional[CommandRecord]:
        """Handles execution acknowledgment returned from the vehicle agent."""
        command_id = ack_data.get("command_id")
        if not command_id:
            logger.warning("Received command ACK without command_id")
            return None

        stmt = select(CommandRecord).where(CommandRecord.id == command_id)
        res = await db.execute(stmt)
        cmd = res.scalar_one_or_none()
        if not cmd:
            logger.warning("Received ACK for unknown command %s", command_id)
            return None

        status_str = ack_data.get("status", "COMPLETED")
        try:
            cmd.status = CommandStatus(status_str)
        except ValueError:
            cmd.status = CommandStatus.COMPLETED

        cmd.executed_at = datetime.now(timezone.utc)
        cmd.result = ack_data.get("result")
        cmd.error_message = ack_data.get("error_message")

        await db.commit()
        await db.refresh(cmd)

        # Notify active clients of command execution result
        await connection_manager.broadcast_command_update(
            cmd.vehicle_id,
            {
                "command_id": cmd.id,
                "status": cmd.status.value,
                "result": cmd.result,
                "error_message": cmd.error_message,
                "executed_at": cmd.executed_at.isoformat() if cmd.executed_at else None
            }
        )
        return cmd

    async def get_commands_for_vehicle(
        self,
        vehicle_id: str,
        limit: int,
        db: AsyncSession
    ) -> List[CommandRecord]:
        """Queries recent command logs for a vehicle."""
        stmt = (
            select(CommandRecord)
            .where(CommandRecord.vehicle_id == vehicle_id)
            .order_by(CommandRecord.created_at.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())


command_service = CommandService()
