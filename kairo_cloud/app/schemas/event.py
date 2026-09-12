from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.models.event import EventSeverity


class EventCreate(BaseModel):
    event_type: str = Field(..., example="COLLISION_AVOIDANCE")
    severity: EventSeverity = Field(default=EventSeverity.INFO)
    description: str = Field(..., example="Autonomous emergency braking activated")
    details: dict[str, Any] = Field(default_factory=dict)


class EventResponse(BaseModel):
    id: str
    vehicle_id: str
    event_type: str
    severity: EventSeverity
    description: str
    details: dict[str, Any]
    timestamp: datetime

    class Config:
        from_attributes = True
