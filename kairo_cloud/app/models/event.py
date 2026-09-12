import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, JSON, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class EventSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventRecord(Base):
    """Stores mission events, system warnings, takeovers, and alerts."""
    __tablename__ = "events"

    id = Column(String(64), primary_key=True, default=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    vehicle_id = Column(String(64), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    severity = Column(Enum(EventSeverity), default=EventSeverity.INFO, nullable=False, index=True)
    description = Column(String(512), nullable=False)
    details = Column(JSON, default=dict, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    vehicle = relationship("Vehicle", back_populates="events")

    __table_args__ = (
        Index("ix_events_vehicle_severity_time", "vehicle_id", "severity", timestamp.desc()),
    )
