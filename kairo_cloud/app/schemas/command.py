from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, validator
from app.models.command import CommandStatus, CommandType


class CommandCreate(BaseModel):
    command_type: CommandType = Field(..., description="Whitelisted command action")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Validated parameter payload")

    @validator("parameters")
    def validate_command_parameters(cls, v, values):
        cmd_type = values.get("command_type")
        if cmd_type == CommandType.CHANGE_WEATHER:
            valid_weathers = {"ClearNoon", "CloudyNoon", "WetNoon", "WetCloudyNoon", "SoftRainNoon", "MidRainyNoon", "HardRainNoon", "ClearSunset", "CloudySunset", "WetSunset", "WetCloudySunset"}
            weather = v.get("weather")
            if weather and weather not in valid_weathers:
                raise ValueError(f"Weather '{weather}' not in supported presets: {list(valid_weathers)}")
        elif cmd_type == CommandType.CHANGE_TIME:
            hour = v.get("hour")
            if hour is not None and not (0.0 <= float(hour) <= 24.0):
                raise ValueError("hour must be between 0.0 and 24.0")
        elif cmd_type == CommandType.SET_AUTONOMY_MODE:
            valid_modes = {"MANUAL", "ASSISTED", "AUTONOMOUS", "EMERGENCY_STOP"}
            mode = v.get("mode")
            if mode and mode not in valid_modes:
                raise ValueError(f"Autonomy mode '{mode}' not in supported modes: {list(valid_modes)}")
        return v


class CommandAck(BaseModel):
    """Acknowledgement packet returned by the Vehicle Agent upon executing command."""
    command_id: str
    status: CommandStatus = Field(..., description="EXECUTING, COMPLETED, or FAILED")
    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None


class CommandResponse(BaseModel):
    id: str
    vehicle_id: str
    command_type: CommandType
    parameters: dict[str, Any]
    status: CommandStatus
    issued_by_user_id: Optional[str]
    created_at: datetime
    delivered_at: Optional[datetime]
    executed_at: Optional[datetime]
    result: Optional[dict[str, Any]]
    error_message: Optional[str]

    class Config:
        from_attributes = True
