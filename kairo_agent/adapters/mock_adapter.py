import asyncio
import math
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from kairo_agent.adapters.base import BaseVehicleAdapter


class MockAdapter(BaseVehicleAdapter):
    """High-fidelity simulation adapter for testing Kairo Cloud without CARLA/Apollo dependencies."""

    def __init__(self, vehicle_id: str = "KAIRO-001"):
        self.vehicle_id = vehicle_id
        self._seq = 0
        self._running = False
        self._is_paused = False

        # Simulated state
        self._speed_kmh = 0.0
        self._target_speed_kmh = 45.0
        self._steering = 0.0
        self._throttle = 0.0
        self._brake = 0.0
        self._gear = "D"
        self._autonomy_mode = "AUTONOMOUS"
        self._autonomy_status = "ACTIVE"

        # Coordinates (centered around San Francisco / Silicon Valley testbed)
        self._lat_base = 37.4220
        self._lon_base = -122.0841
        self._angle_rad = 0.0
        self._heading = 0.0

        # Simulation metadata
        self._scenario = "Town01_Standard"
        self._map = "Town01"
        self._weather = "ClearNoon"
        self._time_of_day = 14.5  # 2:30 PM
        self._start_time = time.time()

    async def initialize(self) -> bool:
        self._running = True
        self._start_time = time.time()
        return True

    async def poll_telemetry(self) -> Optional[Dict[str, Any]]:
        if not self._running:
            return None

        self._seq += 1
        dt = 0.1  # ~10 Hz step

        if not self._is_paused and self._autonomy_mode != "EMERGENCY_STOP":
            # Smoothly ramp speed toward target speed
            if self._speed_kmh < self._target_speed_kmh:
                self._speed_kmh = min(self._target_speed_kmh, self._speed_kmh + 1.2)
                self._throttle = min(1.0, 0.35 + random.uniform(-0.05, 0.05))
                self._brake = 0.0
            else:
                self._speed_kmh = self._target_speed_kmh + random.uniform(-1.0, 1.0)
                self._throttle = 0.2
                self._brake = 0.0

            # Progress along simulated loop track
            self._angle_rad += (self._speed_kmh / 3.6 * dt) / 150.0  # 150m radius track
            self._heading = (math.degrees(self._angle_rad) + 90.0) % 360.0
            self._steering = math.sin(self._angle_rad * 2.0) * 0.25 + random.uniform(-0.02, 0.02)
        else:
            # Stopped or paused
            self._speed_kmh = max(0.0, self._speed_kmh - 5.0)
            self._throttle = 0.0
            self._brake = 1.0 if self._autonomy_mode == "EMERGENCY_STOP" else 0.5
            self._steering = 0.0

        # Update GPS coordinates
        radius_deg = 0.0015
        lat = self._lat_base + radius_deg * math.sin(self._angle_rad)
        lon = self._lon_base + radius_deg * math.cos(self._angle_rad)

        speed_ms = self._speed_kmh / 3.6
        accel = 0.8 if self._throttle > 0.2 else (-1.2 if self._brake > 0.1 else 0.0)

        # Compute usage jitter
        cpu_usage = min(100.0, max(15.0, 38.0 + random.uniform(-4.0, 6.0)))
        gpu_usage = min(100.0, max(20.0, 52.0 + random.uniform(-5.0, 8.0)))
        mem_usage = 42.5 + (self._seq % 50) * 0.05

        return {
            "vehicle_id": self.vehicle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seq": self._seq,
            "location": {
                "latitude": round(lat, 7),
                "longitude": round(lon, 7),
                "altitude": 15.2,
                "heading": round(self._heading, 2)
            },
            "kinematics": {
                "speed": round(speed_ms, 2),
                "speed_kmh": round(self._speed_kmh, 1),
                "acceleration": round(accel, 2),
                "yaw_rate": round(self._steering * 0.8, 3),
                "roll": round(random.uniform(-0.5, 0.5), 2),
                "pitch": round(random.uniform(-0.3, 0.3), 2)
            },
            "controls": {
                "steering": round(self._steering, 3),
                "throttle": round(self._throttle, 3),
                "brake": round(self._brake, 3),
                "gear": self._gear,
                "handbrake": False,
                "turn_indicator": "OFF" if abs(self._steering) < 0.15 else ("LEFT" if self._steering < 0 else "RIGHT")
            },
            "compute": {
                "cpu_usage": round(cpu_usage, 1),
                "gpu_usage": round(gpu_usage, 1),
                "memory_usage": round(mem_usage, 1),
                "temperature_c": round(51.2 + random.uniform(-0.4, 0.4), 1)
            },
            "autonomy": {
                "mode": self._autonomy_mode,
                "status": self._autonomy_status,
                "disengagement_reason": None,
                "target_speed_kmh": self._target_speed_kmh,
                "cte_meters": round(random.uniform(-0.08, 0.08), 3)
            },
            "sensors": [
                {"name": "front_camera_60", "sensor_type": "CAMERA", "status": "ONLINE", "fps": 30.0, "latency_ms": 14.2},
                {"name": "rear_camera", "sensor_type": "CAMERA", "status": "ONLINE", "fps": 30.0, "latency_ms": 15.1},
                {"name": "top_hesai_lidar", "sensor_type": "LIDAR", "status": "ONLINE", "fps": 10.0, "latency_ms": 22.0},
                {"name": "front_radar", "sensor_type": "RADAR", "status": "ONLINE", "fps": 20.0, "latency_ms": 8.5},
                {"name": "novatel_gnss_imu", "sensor_type": "GPS", "status": "ONLINE", "fps": 10.0, "latency_ms": 5.0}
            ],
            "simulation": {
                "is_simulated": True,
                "simulator": "CARLA",
                "scenario": self._scenario,
                "weather": self._weather,
                "time_of_day": round(self._time_of_day, 1),
                "simulation_fps": 30.0
            }
        }

    async def execute_command(self, command_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Executes incoming cloud commands against simulated vehicle systems."""
        if command_type == "START_SIMULATION":
            self._is_paused = False
            self._target_speed_kmh = 45.0
            self._scenario = parameters.get("scenario", self._scenario)
            self._weather = parameters.get("weather", self._weather)
            return {"status": "started", "scenario": self._scenario, "weather": self._weather}

        elif command_type == "STOP_SIMULATION":
            self._target_speed_kmh = 0.0
            self._is_paused = True
            return {"status": "stopped", "final_speed": 0.0}

        elif command_type == "PAUSE_SIMULATION":
            self._is_paused = True
            return {"status": "paused"}

        elif command_type == "RESET_SIMULATION":
            self._angle_rad = 0.0
            self._speed_kmh = 0.0
            self._is_paused = False
            return {"status": "reset", "coordinates": [self._lat_base, self._lon_base]}

        elif command_type == "CHANGE_WEATHER":
            new_weather = parameters.get("weather")
            if not new_weather:
                raise ValueError("Missing 'weather' parameter")
            self._weather = new_weather
            return {"status": "weather_updated", "weather": self._weather}

        elif command_type == "CHANGE_TIME":
            hour = parameters.get("hour")
            if hour is None:
                raise ValueError("Missing 'hour' parameter")
            self._time_of_day = float(hour)
            return {"status": "time_updated", "time_of_day": self._time_of_day}

        elif command_type == "SET_AUTONOMY_MODE":
            mode = parameters.get("mode")
            if not mode:
                raise ValueError("Missing 'mode' parameter")
            self._autonomy_mode = mode
            if mode == "EMERGENCY_STOP":
                self._autonomy_status = "ERROR"
                self._target_speed_kmh = 0.0
            elif mode == "AUTONOMOUS":
                self._autonomy_status = "ACTIVE"
                self._target_speed_kmh = 45.0
            else:
                self._autonomy_status = "STANDBY"
            return {"status": "mode_updated", "mode": self._autonomy_mode, "autonomy_status": self._autonomy_status}

        elif command_type == "REQUEST_DIAGNOSTICS":
            return {
                "status": "healthy",
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "can_bus": "NORMAL",
                "localization": "FIXED_RTK",
                "actuators": "OK",
                "emergency_system": "ARMED"
            }

        else:
            raise ValueError(f"Unsupported command type: {command_type}")

    async def shutdown(self) -> None:
        self._running = False
