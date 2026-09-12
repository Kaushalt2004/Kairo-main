from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models.vehicle import VehicleStatus
from app.schemas.telemetry import TelemetryPayload


class VehicleRegisterRequest(BaseModel):
    id: str = Field(..., example="KAIRO-001", min_length=3, max_length=64, description="Unique vehicle ID")
    name: str = Field(..., example="Apollo Lincoln MKZ", min_length=2, max_length=255)
    vin: Optional[str] = Field(None, example="1FA6P8CF5H5XXXXXX", max_length=64)
    model: str = Field(default="Lincoln MKZ", max_length=128)
    simulator_type: str = Field(default="CARLA", description="CARLA, Apollo, Real")


class VehicleRegisterResponse(BaseModel):
    id: str
    name: str
    simulator_type: str
    status: VehicleStatus
    api_key: str = Field(..., description="Store this securely. Plaintext is only shown once upon registration.")
    created_at: datetime


class VehicleStatusUpdate(BaseModel):
    status: VehicleStatus


class VehicleResponse(BaseModel):
    id: str
    org_id: Optional[str] = None
    name: str
    vin: Optional[str] = None
    model: str
    simulator_type: str
    status: VehicleStatus
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_connected: bool = False
    latest_telemetry: Optional[TelemetryPayload] = None

    class Config:
        from_attributes = True
