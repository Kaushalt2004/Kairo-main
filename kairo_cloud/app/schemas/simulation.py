from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel
from app.models.simulation import SimulationState


class SimulationSessionResponse(BaseModel):
    id: str
    vehicle_id: str
    scenario_name: str
    map_name: str
    weather: str
    time_of_day: float
    state: SimulationState
    started_at: datetime
    ended_at: Optional[datetime] = None
    total_distance_m: float
    total_frames: int
    metrics: dict[str, Any]

    class Config:
        from_attributes = True
