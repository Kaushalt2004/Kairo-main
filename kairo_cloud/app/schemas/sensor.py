from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.sensor import SensorState, SensorType


class SensorStatusUpdate(BaseModel):
    sensor_type: SensorType
    status: SensorState
    message: Optional[str] = None


class SensorStatusResponse(BaseModel):
    id: str
    vehicle_id: str
    sensor_type: SensorType
    status: SensorState
    message: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True
