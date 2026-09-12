import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class SensorType(str, enum.Enum):
    CAMERA = "CAMERA"
    LIDAR = "LIDAR"
    RADAR = "RADAR"
    GPS = "GPS"
    IMU = "IMU"
    ULTRASONIC = "ULTRASONIC"


class SensorState(str, enum.Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


class SensorStatusRecord(Base):
    """Tracks state and health transitions of onboard vehicle sensors."""
    __tablename__ = "sensor_status"

    id = Column(String(64), primary_key=True, default=lambda: f"sens_{uuid.uuid4().hex[:12]}")
    vehicle_id = Column(String(64), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    sensor_type = Column(Enum(SensorType), nullable=False)
    status = Column(Enum(SensorState), default=SensorState.ONLINE, nullable=False)
    message = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    vehicle = relationship("Vehicle", back_populates="sensor_statuses")

    __table_args__ = (
        Index("ix_sensor_vehicle_time", "vehicle_id", "sensor_type", timestamp.desc()),
    )
