import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, JSON, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class CommandType(str, enum.Enum):
    START_SIMULATION = "START_SIMULATION"
    STOP_SIMULATION = "STOP_SIMULATION"
    PAUSE_SIMULATION = "PAUSE_SIMULATION"
    RESET_SIMULATION = "RESET_SIMULATION"
    CHANGE_WEATHER = "CHANGE_WEATHER"
    CHANGE_TIME = "CHANGE_TIME"
    SET_AUTONOMY_MODE = "SET_AUTONOMY_MODE"
    REQUEST_DIAGNOSTICS = "REQUEST_DIAGNOSTICS"


class CommandStatus(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class CommandRecord(Base):
    """Audit log and dispatch tracking for Cloud -> Vehicle commands."""
    __tablename__ = "commands"

    id = Column(String(64), primary_key=True, default=lambda: f"cmd_{uuid.uuid4().hex[:12]}")
    vehicle_id = Column(String(64), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    command_type = Column(Enum(CommandType), nullable=False)
    parameters = Column(JSON, default=dict, nullable=False)
    status = Column(Enum(CommandStatus), default=CommandStatus.PENDING, nullable=False, index=True)
    
    issued_by_user_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)

    result = Column(JSON, nullable=True)
    error_message = Column(String(512), nullable=True)

    vehicle = relationship("Vehicle", back_populates="commands")

    __table_args__ = (
        Index("ix_command_vehicle_status", "vehicle_id", "status", created_at.desc()),
    )
