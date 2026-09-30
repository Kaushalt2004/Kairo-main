import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import urllib.request
import urllib.error

from kairo_agent.adapters.base import BaseVehicleAdapter

logger = logging.getLogger(__name__)


class ApolloAdapter(BaseVehicleAdapter):
    """
    Adapter connecting Kairo Cloud (AWS) with Baidu Apollo 9 Cyber RT.
    Translates Cloud / UI actions (AUTONOMOUS, MANUAL, EMERGENCY STOP, ROUTE)
    into Apollo Cyber RT PadMessages and RoutingRequests.
    """

    def __init__(
        self,
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 9090,
        vehicle_id: str = "KAIRO-001",
        container_name: str = "apollo_dev_kairo_it37",
        apollo_api_url: str = "http://127.0.0.1:8000"
    ):
        self.bridge_host = bridge_host
        self.bridge_port = bridge_port
        self.vehicle_id = vehicle_id
        self.container_name = os.getenv("APOLLO_CONTAINER_NAME", container_name)
        self.apollo_api_url = os.getenv("APOLLO_API_URL", apollo_api_url)

        self._seq = 0
        self._connected = False
        self._current_mode = "MANUAL"  # MANUAL | AUTONOMOUS | EMERGENCY_STOP
        self._last_chassis: Dict[str, Any] = {}
        self._last_pose: Dict[str, Any] = {}
        self._docker_available = False

    async def initialize(self) -> bool:
        """Initializes connection checks to Apollo container and local bridge API."""
        logger.info("Initializing Apollo Cyber RT Adapter for vehicle %s...", self.vehicle_id)
        logger.info("Target Apollo Container: %s | Local API: %s", self.container_name, self.apollo_api_url)

        # Check docker availability
        self._docker_available = bool(shutil.which("docker"))
        if self._docker_available:
            logger.info("Docker CLI detected. Will use 'docker exec %s' for Cyber RT dispatch.", self.container_name)
        else:
            logger.warning("Docker CLI not found in PATH. Will use HTTP Bridge dispatch fallback.")

        self._connected = True
        return True

    async def poll_telemetry(self) -> Optional[Dict[str, Any]]:
        """Polls live telemetry from Apollo / Carla-Apollo Bridge."""
        if not self._connected:
            return None

        self._seq += 1

        # Attempt to pull live telemetry from local Kairo API (pushed by run_bridge.py)
        live_telemetry = await self._fetch_live_bridge_telemetry()

        if live_telemetry:
            speed_mps = float(live_telemetry.get("speed", 0.0))
            speed_kmh = speed_mps * 3.6
            throttle_pct = float(live_telemetry.get("throttle", 0.0))
            brake_pct = float(live_telemetry.get("brake", 0.0))
            steering_pct = float(live_telemetry.get("steering", 0.0))
            objects_count = int(live_telemetry.get("objects", 0))
            monitors_map = live_telemetry.get("monitors", {})
            lane_detected = bool(live_telemetry.get("lane_detected", True))
        else:
            # Fallback simulated dynamic telemetry based on current autonomy mode
            speed_mps = 11.2 if self._current_mode == "AUTONOMOUS" else 0.0
            speed_kmh = speed_mps * 3.6
            throttle_pct = 0.25 if self._current_mode == "AUTONOMOUS" else 0.0
            brake_pct = 1.0 if self._current_mode == "EMERGENCY_STOP" else 0.0
            steering_pct = 0.0
            objects_count = 3
            monitors_map = {"Routing": "OK", "Planning": "OK", "Control": "OK", "Monitor": "OK"}
            lane_detected = True

        lat = float(self._last_pose.get("latitude", 37.4220))
        lon = float(self._last_pose.get("longitude", -122.0841))
        heading = float(self._last_pose.get("heading", 90.0))

        gear_char = "D" if self._current_mode == "AUTONOMOUS" else ("P" if self._current_mode == "EMERGENCY_STOP" else "N")

        return {
            "vehicle_id": self.vehicle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seq": self._seq,
            "location": {
                "latitude": round(lat, 7),
                "longitude": round(lon, 7),
                "altitude": 14.5,
                "heading": round(heading, 2)
            },
            "kinematics": {
                "speed": round(speed_mps, 2),
                "speed_kmh": round(speed_kmh, 1),
                "acceleration": 0.2 if self._current_mode == "AUTONOMOUS" else 0.0,
                "yaw_rate": 0.0,
                "roll": 0.0,
                "pitch": 0.0
            },
            "controls": {
                "steering": round(steering_pct, 3),
                "throttle": round(throttle_pct, 3),
                "brake": round(brake_pct, 3),
                "gear": gear_char,
                "handbrake": self._current_mode == "EMERGENCY_STOP",
                "turn_indicator": "OFF"
            },
            "compute": {
                "cpu_usage": 45.0,
                "gpu_usage": 60.0,
                "memory_usage": 52.0,
                "temperature_c": 54.0
            },
            "autonomy": {
                "mode": self._current_mode,
                "status": "ACTIVE" if self._current_mode == "AUTONOMOUS" else ("ESTOPPED" if self._current_mode == "EMERGENCY_STOP" else "STANDBY"),
                "disengagement_reason": "Cloud E-Stop Command" if self._current_mode == "EMERGENCY_STOP" else None,
                "target_speed_kmh": 40.0 if self._current_mode == "AUTONOMOUS" else 0.0,
                "cte_meters": 0.02
            },
            "sensors": [
                {"name": "apollo_lidar128", "sensor_type": "LIDAR", "status": "ONLINE", "fps": 10.0, "latency_ms": 24.0},
                {"name": "apollo_camera_front", "sensor_type": "CAMERA", "status": "ONLINE", "fps": 30.0, "latency_ms": 15.0},
                {"name": "apollo_radar_front", "sensor_type": "RADAR", "status": "ONLINE", "fps": 20.0, "latency_ms": 10.0},
                {"name": "apollo_novatel_imu", "sensor_type": "GPS", "status": "ONLINE", "fps": 10.0, "latency_ms": 3.0}
            ],
            "simulation": {
                "is_simulated": True,
                "simulator": "Apollo",
                "scenario": "Town03_Standard",
                "weather": "Sunny",
                "time_of_day": 12.0,
                "simulation_fps": 30.0
            }
        }

    async def execute_command(self, command_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Translates Kairo Cloud commands into Apollo Cyber RT actions:
        - SET_AUTONOMY_MODE (AUTONOMOUS / MANUAL / EMERGENCY_STOP)
        - START_SIMULATION / ENGAGE_AUTONOMOUS -> START
        - STOP_SIMULATION / RESET_SIMULATION / DISENGAGE_AUTONOMOUS -> RESET
        - EMERGENCY_STOP -> STOP
        - SEND_ROUTE -> ROUTE
        """
        cmd_upper = command_type.upper()
        logger.info("ApolloAdapter received cloud command: %s (params: %s)", cmd_upper, parameters)

        action_to_dispatch = "RESET"

        if cmd_upper in ("SET_AUTONOMY_MODE", "CHANGE_AUTONOMY_MODE"):
            mode = parameters.get("mode", "").upper()
            if mode in ("AUTONOMOUS", "START", "AUTO"):
                action_to_dispatch = "START"
                self._current_mode = "AUTONOMOUS"
            elif mode in ("EMERGENCY_STOP", "STOP", "E_STOP"):
                action_to_dispatch = "STOP"
                self._current_mode = "EMERGENCY_STOP"
            else:
                action_to_dispatch = "RESET"
                self._current_mode = "MANUAL"

        elif cmd_upper in ("START_SIMULATION", "ENGAGE_AUTONOMOUS", "START", "AUTO_DRIVE"):
            action_to_dispatch = "START"
            self._current_mode = "AUTONOMOUS"

        elif cmd_upper in ("STOP_SIMULATION", "RESET_SIMULATION", "DISENGAGE_AUTONOMOUS", "RESET", "MANUAL"):
            action_to_dispatch = "RESET"
            self._current_mode = "MANUAL"

        elif cmd_upper in ("EMERGENCY_STOP", "E_STOP", "STOP"):
            action_to_dispatch = "STOP"
            self._current_mode = "EMERGENCY_STOP"

        elif cmd_upper in ("SEND_ROUTE", "ROUTING_REQUEST"):
            action_to_dispatch = "ROUTE"
            self._current_mode = "AUTONOMOUS"

        elif cmd_upper == "REQUEST_DIAGNOSTICS":
            return {
                "status": "healthy",
                "cyber_rt": "RUNNING",
                "routing": "SUCCESS",
                "planning": "OK",
                "control": "ENGAGED" if self._current_mode == "AUTONOMOUS" else "STANDBY",
                "current_mode": self._current_mode
            }
        else:
            logger.info("Unrecognized command type '%s', acknowledging default.", cmd_upper)
            return {"status": "acknowledged", "command": command_type}

        # 1. Dispatch action to Apollo container via Cyber RT
        cyber_result = await self._dispatch_to_apollo_container(action_to_dispatch, parameters)

        # 2. Dispatch action to local Kairo Bridge API
        api_result = await self._dispatch_to_kairo_api(action_to_dispatch)

        logger.info(
            "Apollo action '%s' dispatched. Mode updated to: %s. Cyber RT: %s | API: %s",
            action_to_dispatch, self._current_mode, cyber_result.get("status"), api_result.get("status")
        )

        return {
            "status": "success",
            "action_executed": action_to_dispatch,
            "apollo_mode": self._current_mode,
            "cyber_dispatch": cyber_result,
            "bridge_dispatch": api_result,
            "executed_at": datetime.now(timezone.utc).isoformat()
        }

    async def _dispatch_to_apollo_container(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Runs cloud_action_executor.py inside Apollo docker container."""
        if not self._docker_available:
            return {"status": "skipped", "reason": "Docker CLI not available"}

        cmd = [
            "docker", "exec", self.container_name,
            "python3", "/apollo/cloud_action_executor.py",
            "--action", action
        ]

        if "distance" in parameters:
            cmd.extend(["--distance", str(parameters["distance"])])
        if "x" in parameters and "y" in parameters:
            cmd.extend(["--x", str(parameters["x"]), "--y", str(parameters["y"])])

        try:
            loop = asyncio.get_event_loop()
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8.0, text=True)
            )
            if proc.returncode == 0:
                try:
                    return json.loads(proc.stdout.strip())
                except json.JSONDecodeError:
                    return {"status": "success", "stdout": proc.stdout.strip()}
            else:
                logger.warning("Docker exec returned non-zero (%d): %s", proc.returncode, proc.stderr.strip())
                return {"status": "failed", "stderr": proc.stderr.strip()}
        except Exception as e:
            logger.warning("Failed to dispatch Cyber RT command via docker exec: %s", e)
            return {"status": "error", "error": str(e)}

    async def _dispatch_to_kairo_api(self, action: str) -> Dict[str, Any]:
        """Sends action to local Kairo sim_control API for Carla Apollo Bridge."""
        url = f"{self.apollo_api_url}/api/sim_control"
        payload = json.dumps({"action": action}).encode("utf-8")

        def _do_post():
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                return {"status": "unreachable", "error": str(e)}

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _do_post)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _fetch_live_bridge_telemetry(self) -> Optional[Dict[str, Any]]:
        """Queries local Kairo vehicle API for live telemetry from Carla-Apollo bridge."""
        url = f"{self.apollo_api_url}/api/telemetry"

        def _do_get():
            req = urllib.request.Request(url, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=0.1) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception:
                return None

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _do_get)
        except Exception:
            return None

    async def shutdown(self) -> None:
        self._connected = False
        logger.info("ApolloAdapter shut down.")
