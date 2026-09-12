import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from kairo_agent.adapters.base import BaseVehicleAdapter

logger = logging.getLogger(__name__)


class CarlaAdapter(BaseVehicleAdapter):
    """Adapter bridging CARLA Simulator ego vehicle telemetry and world controls into Kairo Cloud."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2000,
        vehicle_filter: str = "vehicle.lincoln.mkz*",
        vehicle_id: str = "KAIRO-001"
    ):
        self.host = host
        self.port = port
        self.vehicle_filter = vehicle_filter
        self.vehicle_id = vehicle_id

        self._client = None
        self._world = None
        self._ego_vehicle = None
        self._seq = 0
        self._connected = False

    async def initialize(self) -> bool:
        """Connects to CARLA server and locates the ego vehicle actor."""
        try:
            import carla
        except ImportError:
            logger.error("carla Python package not found. Please install the CARLA Python API wheel.")
            return False

        try:
            logger.info("Connecting to CARLA simulator at %s:%d...", self.host, self.port)
            self._client = carla.Client(self.host, self.port)
            self._client.set_timeout(5.0)
            self._world = self._client.get_world()

            # Find ego vehicle
            actors = self._world.get_actors().filter(self.vehicle_filter)
            if not actors:
                # Try finding any hero/ego role vehicle
                for a in self._world.get_actors().filter("vehicle.*"):
                    if a.attributes.get("role_name") in ["ego_vehicle", "hero"]:
                        self._ego_vehicle = a
                        break
            else:
                self._ego_vehicle = actors[0]

            if self._ego_vehicle:
                logger.info("Found CARLA ego vehicle actor: id=%d, type=%s", self._ego_vehicle.id, self._ego_vehicle.type_id)
                self._connected = True
                return True
            else:
                logger.warning("No ego vehicle matching '%s' found in CARLA world. Will retry upon polling.", self.vehicle_filter)
                self._connected = True
                return True
        except Exception as e:
            logger.error("Failed to connect to CARLA simulator: %s", e)
            return False

    async def poll_telemetry(self) -> Optional[Dict[str, Any]]:
        """Extracts live pose, velocity, controls, and weather from CARLA."""
        if not self._connected or not self._world:
            return None

        self._seq += 1

        # Re-query ego vehicle if lost
        if not self._ego_vehicle:
            for a in self._world.get_actors().filter("vehicle.*"):
                if a.attributes.get("role_name") in ["ego_vehicle", "hero"]:
                    self._ego_vehicle = a
                    break
            if not self._ego_vehicle:
                return None

        try:
            transform = self._ego_vehicle.get_transform()
            velocity = self._ego_vehicle.get_velocity()
            acceleration = self._ego_vehicle.get_acceleration()
            control = self._ego_vehicle.get_control()
            weather = self._world.get_weather()

            # Speed calculation in m/s and km/h
            speed_ms = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
            speed_kmh = speed_ms * 3.6
            accel_ms2 = math.sqrt(acceleration.x**2 + acceleration.y**2 + acceleration.z**2)

            # CARLA coordinates to approximate WGS84 (Town01 reference origin)
            lat = 37.4220 + (transform.location.y / 111320.0)
            lon = -122.0841 + (transform.location.x / (111320.0 * math.cos(math.radians(37.4220))))

            gear_str = "D"
            if control.reverse:
                gear_str = "R"
            elif control.gear == 0:
                gear_str = "N"

            map_name = self._world.get_map().name.split("/")[-1] if self._world.get_map() else "Town01"

            return {
                "vehicle_id": self.vehicle_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "seq": self._seq,
                "location": {
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                    "altitude": round(transform.location.z, 2),
                    "heading": round(transform.rotation.yaw % 360.0, 2)
                },
                "kinematics": {
                    "speed": round(speed_ms, 2),
                    "speed_kmh": round(speed_kmh, 1),
                    "acceleration": round(accel_ms2, 2),
                    "yaw_rate": 0.0,
                    "roll": round(transform.rotation.roll, 2),
                    "pitch": round(transform.rotation.pitch, 2)
                },
                "controls": {
                    "steering": round(control.steer, 3),
                    "throttle": round(control.throttle, 3),
                    "brake": round(control.brake, 3),
                    "gear": gear_str,
                    "handbrake": control.hand_brake,
                    "turn_indicator": "OFF"
                },
                "compute": {
                    "cpu_usage": 45.0,
                    "gpu_usage": 72.0,
                    "memory_usage": 48.0,
                    "temperature_c": 56.0
                },
                "autonomy": {
                    "mode": "AUTONOMOUS",
                    "status": "ACTIVE",
                    "disengagement_reason": None,
                    "target_speed_kmh": 40.0,
                    "cte_meters": 0.0
                },
                "sensors": [
                    {"name": "carla_rgb_camera", "sensor_type": "CAMERA", "status": "ONLINE", "fps": 30.0, "latency_ms": 12.0},
                    {"name": "carla_lidar", "sensor_type": "LIDAR", "status": "ONLINE", "fps": 10.0, "latency_ms": 18.0},
                    {"name": "carla_gnss", "sensor_type": "GPS", "status": "ONLINE", "fps": 10.0, "latency_ms": 4.0}
                ],
                "simulation": {
                    "is_simulated": True,
                    "simulator": "CARLA",
                    "scenario": map_name,
                    "weather": "CARLA_Active",
                    "time_of_day": round(weather.sun_altitude_angle / 90.0 * 12.0, 1),
                    "simulation_fps": 30.0
                }
            }
        except Exception as e:
            logger.error("Error polling CARLA telemetry: %s", e)
            return None

    async def execute_command(self, command_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Translates Kairo Cloud commands into CARLA simulator controls."""
        import carla

        if not self._world:
            raise RuntimeError("CARLA world is not connected")

        if command_type == "CHANGE_WEATHER":
            weather_name = parameters.get("weather")
            weather_presets = {
                "ClearNoon": carla.WeatherParameters.ClearNoon,
                "CloudyNoon": carla.WeatherParameters.CloudyNoon,
                "WetNoon": carla.WeatherParameters.WetNoon,
                "WetCloudyNoon": carla.WeatherParameters.WetCloudyNoon,
                "SoftRainNoon": carla.WeatherParameters.SoftRainNoon,
                "MidRainyNoon": carla.WeatherParameters.MidRainyNoon,
                "HardRainNoon": carla.WeatherParameters.HardRainNoon,
                "ClearSunset": carla.WeatherParameters.ClearSunset,
                "CloudySunset": carla.WeatherParameters.CloudySunset,
                "WetSunset": carla.WeatherParameters.WetSunset,
                "WetCloudySunset": carla.WeatherParameters.WetCloudySunset
            }
            preset = weather_presets.get(weather_name)
            if not preset:
                raise ValueError(f"Weather '{weather_name}' not recognized in CARLA presets")
            self._world.set_weather(preset)
            return {"status": "weather_changed", "weather": weather_name}

        elif command_type == "CHANGE_TIME":
            hour = float(parameters.get("hour", 12.0))
            current_weather = self._world.get_weather()
            current_weather.sun_altitude_angle = (hour / 24.0) * 180.0 - 90.0
            self._world.set_weather(current_weather)
            return {"status": "time_changed", "hour": hour}

        elif command_type == "RESET_SIMULATION":
            if self._ego_vehicle:
                spawn_points = self._world.get_map().get_spawn_points()
                if spawn_points:
                    self._ego_vehicle.set_transform(spawn_points[0])
                    self._ego_vehicle.set_target_velocity(carla.Vector3D(0, 0, 0))
            return {"status": "simulation_reset"}

        elif command_type == "SET_AUTONOMY_MODE":
            mode = parameters.get("mode")
            if mode == "EMERGENCY_STOP" and self._ego_vehicle:
                self._ego_vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, hand_brake=True))
            return {"status": "mode_set", "mode": mode}

        else:
            return {"status": "acknowledged", "command": command_type}

    async def shutdown(self) -> None:
        self._connected = False
        self._world = None
        self._client = None
