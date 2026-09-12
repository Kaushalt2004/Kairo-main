import uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class TelemetryRecord(Base):
    """Stores persisted (downsampled/sampled) telemetry snapshots for historical analysis and playback."""
    __tablename__ = "telemetry_history"

    id = Column(String(64), primary_key=True, default=lambda: f"tel_{uuid.uuid4().hex[:14]}")
    vehicle_id = Column(String(64), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Key indexed physics & vehicle states
    speed = Column(Float, nullable=False, default=0.0)
    steering = Column(Float, nullable=False, default=0.0)
    throttle = Column(Float, nullable=False, default=0.0)
    brake = Column(Float, nullable=False, default=0.0)
    gear = Column(String(8), default="D", nullable=False)

    # Autonomy
    autonomy_mode = Column(String(32), default="MANUAL", nullable=False)
    system_status = Column(String(32), default="STANDBY", nullable=False)

    # Location
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)

    # Compute
    cpu_usage = Column(Float, nullable=True)
    gpu_usage = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=True)

    # Full structured telemetry payload (extensible for future fields / time-series export)
    raw_payload = Column(JSON, nullable=False)

    vehicle = relationship("Vehicle", back_populates="telemetry_records")

    __table_args__ = (
        Index("ix_telemetry_vehicle_time", "vehicle_id", timestamp.desc()),
    )
