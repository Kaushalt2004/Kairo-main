from datetime import datetime, timezone
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class LocationData(BaseModel):
    latitude: float = Field(default=0.0, description="WGS84 Latitude")
    longitude: float = Field(default=0.0, description="WGS84 Longitude")
    altitude: float = Field(default=0.0, description="Altitude above sea level (m)")
    heading: float = Field(default=0.0, description="Heading / Yaw angle in degrees [0, 360)")


class KinematicsData(BaseModel):
    speed: float = Field(default=0.0, description="Current speed in m/s")
    speed_kmh: float = Field(default=0.0, description="Current speed in km/h")
    acceleration: float = Field(default=0.0, description="Longitudinal acceleration in m/s^2")
    yaw_rate: float = Field(default=0.0, description="Yaw rate in rad/s")
    roll: float = Field(default=0.0, description="Roll angle in degrees")
    pitch: float = Field(default=0.0, description="Pitch angle in degrees")


class ControlsData(BaseModel):
    steering: float = Field(default=0.0, ge=-1.0, le=1.0, description="Normalized steering angle [-1.0, 1.0]")
    throttle: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized throttle [0.0, 1.0]")
    brake: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized braking force [0.0, 1.0]")
    gear: str = Field(default="D", description="Gear: P, R, N, D, S")
    handbrake: bool = Field(default=False, description="Handbrake status")
    turn_indicator: str = Field(default="OFF", description="OFF, LEFT, RIGHT, HAZARD")


class ComputeData(BaseModel):
    cpu_usage: float = Field(default=0.0, ge=0.0, le=100.0, description="CPU usage percentage")
    gpu_usage: float = Field(default=0.0, ge=0.0, le=100.0, description="GPU usage percentage")
    memory_usage: float = Field(default=0.0, ge=0.0, le=100.0, description="RAM usage percentage")
    temperature_c: float = Field(default=45.0, description="Onboard compute temperature in Celsius")


class AutonomyData(BaseModel):
    mode: str = Field(default="MANUAL", description="MANUAL, ASSISTED, AUTONOMOUS, EMERGENCY_STOP")
    status: str = Field(default="STANDBY", description="STANDBY, ACTIVE, DISENGAGED, ERROR")
    disengagement_reason: Optional[str] = Field(default=None, description="Reason for last disengagement")
    target_speed_kmh: float = Field(default=0.0, description="Planner target speed")
    cte_meters: float = Field(default=0.0, description="Cross-track error to reference trajectory")


class SensorHealth(BaseModel):
    name: str = Field(..., description="Sensor identifier e.g. front_camera, top_lidar")
    sensor_type: str = Field(..., description="CAMERA, LIDAR, RADAR, GPS, IMU")
    status: str = Field(default="ONLINE", description="ONLINE, DEGRADED, OFFLINE, ERROR")
    fps: float = Field(default=30.0, description="Operational frequency / FPS")
    latency_ms: float = Field(default=15.0, description="Sensor pipeline latency in milliseconds")


class SimulationStateData(BaseModel):
    is_simulated: bool = Field(default=True)
    simulator: str = Field(default="CARLA", description="CARLA, Apollo, Real")
    scenario: str = Field(default="Town01", description="Active simulation scenario / town")
    weather: str = Field(default="ClearNoon", description="Current weather preset")
    time_of_day: float = Field(default=12.0, description="Simulated hour [0.0 - 24.0]")
    simulation_fps: float = Field(default=30.0, description="Simulator tick rate")


class TelemetryPayload(BaseModel):
    """Canonical telemetry packet sent over WebSocket and cached in Redis."""
    vehicle_id: str = Field(..., description="Vehicle ID e.g. KAIRO-001")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = Field(default=0, description="Monotonically increasing packet sequence number")
    location: LocationData = Field(default_factory=LocationData)
    kinematics: KinematicsData = Field(default_factory=KinematicsData)
    controls: ControlsData = Field(default_factory=ControlsData)
    compute: ComputeData = Field(default_factory=ComputeData)
    autonomy: AutonomyData = Field(default_factory=AutonomyData)
    sensors: List[SensorHealth] = Field(default_factory=list)
    simulation: Optional[SimulationStateData] = Field(default_factory=SimulationStateData)
    extra: dict[str, Any] = Field(default_factory=dict)


class TelemetrySnapshot(BaseModel):
    """Summarized historical telemetry record from database."""
    id: str
    vehicle_id: str
    timestamp: datetime
    speed: float
    steering: float
    throttle: float
    brake: float
    gear: str
    autonomy_mode: str
    system_status: str
    latitude: Optional[float]
    longitude: Optional[float]
    heading: Optional[float]
    cpu_usage: Optional[float]
    gpu_usage: Optional[float]
    memory_usage: Optional[float]
    raw_payload: dict[str, Any]

    class Config:
        from_attributes = True
