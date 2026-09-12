import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class VehicleStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    STANDBY = "STANDBY"
    SIMULATION = "SIMULATION"
    MAINTENANCE = "MAINTENANCE"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(String(64), primary_key=True)  # e.g., "KAIRO-001"
    org_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(255), nullable=False)
    vin = Column(String(64), unique=True, nullable=True)
    model = Column(String(128), default="Lincoln MKZ", nullable=False)
    simulator_type = Column(String(64), default="CARLA", nullable=False)  # CARLA, Apollo, Real
    api_key_hash = Column(String(64), nullable=False, index=True)
    status = Column(Enum(VehicleStatus), default=VehicleStatus.OFFLINE, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="vehicles")
    connections = relationship("VehicleConnection", back_populates="vehicle", cascade="all, delete-orphan")
    telemetry_records = relationship("TelemetryRecord", back_populates="vehicle", cascade="all, delete-orphan")
    sensor_statuses = relationship("SensorStatusRecord", back_populates="vehicle", cascade="all, delete-orphan")
    commands = relationship("CommandRecord", back_populates="vehicle", cascade="all, delete-orphan")
    simulation_sessions = relationship("SimulationSession", back_populates="vehicle", cascade="all, delete-orphan")
    events = relationship("EventRecord", back_populates="vehicle", cascade="all, delete-orphan")


class VehicleConnection(Base):
    __tablename__ = "vehicle_connections"

    id = Column(String(64), primary_key=True, default=lambda: f"conn_{uuid.uuid4().hex[:12]}")
    vehicle_id = Column(String(64), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    connected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    disconnected_at = Column(DateTime(timezone=True), nullable=True)
    client_ip = Column(String(64), nullable=True)
    protocol = Column(String(32), default="WebSocket", nullable=False)
    close_reason = Column(String(255), nullable=True)

    vehicle = relationship("Vehicle", back_populates="connections")
