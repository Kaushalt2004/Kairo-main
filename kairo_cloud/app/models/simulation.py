import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class SimulationState(str, enum.Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RESETTING = "RESETTING"


class SimulationSession(Base):
    """Tracks simulation session lifecycle, configuration, and run metrics."""
    __tablename__ = "simulation_sessions"

    id = Column(String(64), primary_key=True, default=lambda: f"sim_{uuid.uuid4().hex[:12]}")
    vehicle_id = Column(String(64), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_name = Column(String(128), default="Town01_Standard", nullable=False)
    map_name = Column(String(128), default="Town01", nullable=False)
    weather = Column(String(64), default="ClearNoon", nullable=False)
    time_of_day = Column(Float, default=12.0, nullable=False)  # 0.0 to 24.0 hours
    state = Column(Enum(SimulationState), default=SimulationState.STOPPED, nullable=False)

    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    total_distance_m = Column(Float, default=0.0, nullable=False)
    total_frames = Column(Integer, default=0, nullable=False)
    metrics = Column(JSON, default=dict, nullable=False)

    vehicle = relationship("Vehicle", back_populates="simulation_sessions")

    __table_args__ = (
        Index("ix_sim_vehicle_time", "vehicle_id", started_at.desc()),
    )
