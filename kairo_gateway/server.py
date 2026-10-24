"""KAIRO vehicle gateway - the tablet's single entry point into Apollo.

    tablet (Flutter)  --HTTP/WS :8090-->  gateway (this, on the host)
                                              |-- ws :8888/websocket --> Dreamview Plus (HMI)
                                              '-- docker exec -i ------> cyber_daemon.py (Cyber RT)

REST commands answer with the new state; /ws pushes the state (10x/second
while the car moves, otherwise only on change) and accepts pedal/steering
input while driving manually:  {"type": "drive", "throttle", "brake", "steer"}

Validation services (see docs/validation_api.md):
  /api/traffic    simulated vehicles around the car (kairo_traffic.py)
  /api/hazards    hazard injection (hazards.py)
  /api/safety     live safety status and per-trip reports (safety.py)
  /api/scenarios  YAML scenario batches and benchmarks (scenarios.py)
"""

import asyncio
import json
import logging
import math
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from . import scenarios as scn
from .cyber_bridge import CyberBridge
from .dreamview import DreamviewClient, DreamviewError
from .hazards import HazardError, HazardManager
from .safety import RULES, SafetyValidator
from .v2v import V2VChannel
from .vehicle_body import SIGNAL_FIELDS, BodyError, VehicleBody

log = logging.getLogger("kairo.gateway")

CONTAINER = os.getenv("KAIRO_APOLLO_CONTAINER", "apollo_dev_kairo_it37")
DREAMVIEW_WS = os.getenv("KAIRO_DREAMVIEW_WS", "ws://127.0.0.1:8888/websocket")
DREAMVIEW_PORT = int(os.getenv("KAIRO_DREAMVIEW_PORT", "8888"))
DATA_DIR = Path(__file__).with_name("data")
PLACES_FILE = Path(os.getenv("KAIRO_PLACES_FILE", DATA_DIR / "places.json"))
BODY_FILE = Path(os.getenv("KAIRO_BODY_FILE", DATA_DIR / "body.json"))
STATE_PUSH_PERIOD_S = 0.1       # while moving / driving manually
IDLE_PUSH_PERIOD_S = 0.5        # parked: only changes are sent anyway
STALE_S = 3.0

_GEARS = {"GEAR_PARKING": "P", "GEAR_REVERSE": "R",
          "GEAR_NEUTRAL": "N", "GEAR_DRIVE": "D", "GEAR_LOW": "D"}


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class GoRequest(BaseModel):
    x: float
    y: float
    heading: Optional[float] = None
    name: Optional[str] = None
    target_speed_kph: Optional[float] = Field(None, gt=0, le=120)
    # Set by the scenario runner; recorded in the trip's safety report.
    scenario: Optional[str] = None
    run: Optional[int] = None
    timeout_s: Optional[float] = Field(None, gt=0, le=3600)


class TrafficRequest(BaseModel):
    count: int = Field(8, ge=1, le=40)
    radius_m: float = Field(150.0, ge=20, le=500)
    seed: Optional[int] = None
    speed_factor: float = Field(1.0, ge=0.3, le=1.5)


class ScenarioRunRequest(BaseModel):
    names: List[str] = []           # empty: every scenario
    repeat: Optional[int] = Field(None, ge=1, le=50)


class NameRequest(BaseModel):
    name: str


class EnabledRequest(BaseModel):
    enabled: bool


class ModuleRequest(BaseModel):
    running: bool


class StartPointRequest(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    heading: Optional[float] = None


class GearRequest(BaseModel):
    gear: str


class PlaceRequest(BaseModel):
    label: str
    x: float
    y: float
    heading: Optional[float] = None


# ---------------------------------------------------------------------------
# Gateway state
# ---------------------------------------------------------------------------

class Gateway:
    def __init__(self) -> None:
        self.cyber = CyberBridge(CONTAINER)
        self.dreamview = DreamviewClient(DREAMVIEW_WS)
        self.destination: Optional[Dict[str, Any]] = None
        self.target_speed_kph: Optional[float] = None
        self.stop_requested = False
        self.last_action: Optional[Dict[str, Any]] = None
        self._map_cache: Dict[str, Any] = {}
        self._progress_route: Optional[int] = None
        self._progress_idx = 0
        self._error_since: Optional[float] = None
        # Last pose that differed from its predecessor, to notice a car that
        # Dreamview's Sim Control froze (it keeps reporting the old speed).
        self._moved_at = time.time()
        self._last_xy: Optional[tuple] = None
        self._reroutes = 0
        self._reroute_task = None  # concurrent.futures.Future of _reroute()
        self.loop = asyncio.get_event_loop()  # created inside the app's loop
        self._map_lock = asyncio.Lock()
        # Read once; state() runs several times a second and must not hit
        # the disk. Writes go through put_place/delete_place.
        self._places = self._load_places()
        self.body = VehicleBody(BODY_FILE)
        # MANUAL: the KAIRO virtual vehicle in the daemon drives (tablet
        # pedals); AUTO: Apollo + Dreamview Sim Control (or CARLA) drive.
        self.manual = False
        self._manual_since = 0.0
        self.signal_status: Optional[Dict[str, Any]] = None
        self._mode_lock = asyncio.Lock()
        self._last_drive_input = 0.0
        self.hazards = HazardManager(self.cyber.request)
        self.safety = SafetyValidator(DATA_DIR / "reports")
        self.v2v = V2VChannel()
        self._safety_ts: Optional[float] = None  # telemetry sample last validated

    # ---- places (per HD map) ---------------------------------------------

    @staticmethod
    def _load_places() -> Dict[str, Dict[str, Any]]:
        try:
            return json.loads(PLACES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_places(self) -> None:
        PLACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        PLACES_FILE.write_text(json.dumps(self._places, indent=2), encoding="utf-8")

    def places_for(self, map_name: Optional[str]) -> Dict[str, Any]:
        return self._places.get(map_name or "", {})

    def put_place(self, map_name: str, place_id: str, place: Dict[str, Any]) -> None:
        self._places.setdefault(map_name, {})[place_id] = place
        self._save_places()

    def delete_place(self, map_name: str, place_id: str) -> None:
        self._places.get(map_name, {}).pop(place_id, None)
        self._save_places()

    # ---- derived state ---------------------------------------------------

    def _fresh(self, channel: str) -> bool:
        t = self.cyber.telemetry or {}
        age = (t.get("channel_age_s") or {}).get(channel)
        return age is not None and age < STALE_S and self.cyber.connected

    def current_map(self) -> Optional[str]:
        hmi = (self.cyber.telemetry or {}).get("hmi") or {}
        return hmi.get("current_map")

    def state(self, include_route: bool = True) -> Dict[str, Any]:
        """Full snapshot. The route polyline can run to hundreds of points
        and only changes per destination, so the /ws stream leaves it out
        (include_route=False); clients refetch /api/route when
        scene.route_rev changes."""
        t = self.cyber.telemetry or {}
        chassis = t.get("chassis") if self._fresh("chassis") else None
        pose = t.get("pose") if self._fresh("localization") else None
        planning = t.get("planning") if self._fresh("planning") else None
        hmi = t.get("hmi") or {}
        route = t.get("route") or {}
        status = t.get("command_status") or {}

        speed_mps = (chassis or {}).get("speed_mps") or 0.0
        if not chassis and pose:
            speed_mps = math.hypot(pose.get("vx") or 0.0, pose.get("vy") or 0.0)
        manual_info = t.get("manual") or {}
        if (self.manual and t and not manual_info.get("active")
                and t.get("ts", 0) > self._manual_since + 1.0):
            # Telemetry from after the switch says the virtual vehicle is
            # gone: the daemon restarted.
            self.manual = False
        self.body.on_speed(speed_mps * 3.6)

        route_line = route.get("polyline") or []
        if self.destination is None:
            route_line = []
        remaining = None
        if route_line:
            if route.get("command_id") != self._progress_route:
                self._progress_route, self._progress_idx = route.get("command_id"), 0
            remaining, self._progress_idx = _remaining_along(
                route_line, pose, self._progress_idx)
        eta_s = None
        if remaining is not None:
            cruise = max(speed_mps, (self.target_speed_kph or 30) / 3.6 * 0.6, 1.0)
            eta_s = remaining / cruise

        autopilot = self._autopilot_state(pose, planning, status, speed_mps,
                                          remaining, eta_s)
        autopilot["route_distance_m"] = (
            route.get("distance_m") if self.destination else None)

        return {
            "ts": time.time(),
            "gateway": {
                "cyber_connected": self.cyber.connected,
                "cyber_error": None if self.cyber.connected else self.cyber.last_error,
                "dreamview_connected": self.dreamview.connected,
                "dreamview_error": None if self.dreamview.connected else self.dreamview.last_error,
                "dreamview_port": DREAMVIEW_PORT,
                "channels": {
                    k: self._fresh(k)
                    for k in ("chassis", "localization", "planning", "perception", "hmi")
                },
            },
            "vehicle": {
                "speed_kph": round(speed_mps * 3.6, 1),
                "gear": _GEARS.get((chassis or {}).get("gear")),
                "battery_pct": (chassis or {}).get("battery_soc"),
                "driving_mode": (chassis or {}).get("driving_mode"),
                "throttle_pct": (chassis or {}).get("throttle"),
                "brake_pct": (chassis or {}).get("brake"),
                "steering_pct": (chassis or {}).get("steering"),
                "signal": (chassis or {}).get("signal"),
                "pose": pose,
            },
            "autopilot": autopilot,
            "drive": {
                "mode": "MANUAL" if self.manual else "AUTO",
                "gear": manual_info.get("gear") if self.manual else
                _GEARS.get((chassis or {}).get("gear")),
                "deadman": bool(manual_info.get("deadman")) if self.manual else False,
            },
            "body": self.body.state,
            "signal_status": self.signal_status,
            "safety": self.safety.live(),
            "hazards": self.hazards.summary(),
            "traffic": t.get("traffic") if self.cyber.connected else None,
            "v2v": self.v2v.summary(),
            "dreamview": {
                "mode": hmi.get("current_mode"),
                "modes": hmi.get("modes") or [],
                "map": hmi.get("current_map"),
                "maps": sorted(hmi.get("maps") or []),
                "vehicle": hmi.get("current_vehicle"),
                "operation": hmi.get("current_operation"),
                "operations": hmi.get("operations") or [],
                "sim_control": hmi.get("current_operation") == "Sim_Control",
                "modules": dict(sorted((hmi.get("modules") or {}).items())),
                "components": hmi.get("monitored_components") or {},
            },
            "scene": {
                "trajectory": (planning or {}).get("trajectory") or [],
                "route_rev": route.get("command_id") if route_line else None,
                **({"route": route_line} if include_route else {}),
                "obstacles": t.get("obstacles") if self._fresh("perception") else [],
            },
            "places": self.places_for(hmi.get("current_map")),
        }

    def _autopilot_state(self, pose, planning, status, speed_mps, remaining, eta_s):
        planning = planning or {}
        cmd_status = status.get("status")
        message = status.get("message")

        if not self.cyber.connected:
            state = "OFFLINE"
            message = self.cyber.last_error or "Apollo container not reachable"
        elif self.manual:
            state = "MANUAL"
            message = None
        elif pose is None:
            state = "UNAVAILABLE"
            message = ("No localization. Enable Sim Control or start the "
                       "CARLA bridge.")
        elif self.destination is None:
            state = "READY"
        elif self._frozen(pose) and not self.stop_requested:
            # Planning produced no trajectory for several seconds: the car
            # stands still even though Sim Control still reports its speed.
            # Usually the route lost track of the car (the CARLA maps have
            # malformed lane links), so first route again from where the
            # car actually is.
            if self._reroutes < self.MAX_REROUTES:
                state = "DRIVING"
                message = "Rerouting…"
                if self._reroute_task is None or self._reroute_task.done():
                    # state() also runs in FastAPI's worker threads (sync
                    # endpoints), so schedule on the gateway's own loop.
                    self._reroute_task = asyncio.run_coroutine_threadsafe(
                        self._reroute(), self.loop)
            else:
                state = "ERROR"
                message = ("Apollo can't find a path from here. Try Resume, "
                           "or End trip and pick a destination on a lane.")
        elif cmd_status == "ERROR" and self._error_persisted(speed_mps):
            state = "ERROR"
        elif cmd_status == "FINISHED" or (
                speed_mps < 0.3 and planning.get("main_decision") != "cruise"
                and math.hypot(pose["x"] - self.destination["x"],
                               pose["y"] - self.destination["y"]) < 10):
            # Apollo stops at (often a few metres past) the end point and can
            # keep the command RUNNING, so a stop near the pin is arrival.
            state = "ARRIVED"
        elif self.stop_requested:
            state = "STOPPING" if speed_mps > 0.2 else "STOPPED"
        elif planning.get("is_estop"):
            state = "ESTOP"
            message = planning.get("estop_reason") or message
        else:
            state = "DRIVING"
            if cmd_status == "ERROR":
                # Planning fails single cycles (e.g. optimizer time limit in
                # tight junctions) and recovers; don't alarm the driver.
                message = "Replanning…"
        if cmd_status != "ERROR":
            self._error_since = None

        return {
            "state": state,
            "engaged": state in ("DRIVING", "STOPPING", "ESTOP"),
            "message": message,
            "destination": self.destination,
            "remaining_m": None if remaining is None else round(remaining, 1),
            "eta_s": None if eta_s is None else round(eta_s),
            "target_speed_kph": self.target_speed_kph,
            "decision": planning.get("main_decision"),
            "last_action": self.last_action,
        }

    STUCK_AFTER_S = 4.0
    MAX_REROUTES = 3

    async def _reroute(self) -> None:
        """Re-sends the current destination so Apollo plans a fresh route
        starting from the car's actual position."""
        dest = self.destination
        if dest is None:
            return
        self._reroutes += 1
        log.info("Car stuck at %s: rerouting (attempt %d)", self._last_xy, self._reroutes)
        args: Dict[str, Any] = {"x": dest["x"], "y": dest["y"]}
        if dest.get("heading") is not None:
            args["heading"] = dest["heading"]
        if self.target_speed_kph:
            args["target_speed"] = self.target_speed_kph / 3.6
        try:
            if self._reroutes >= self.MAX_REROUTES and self._last_xy and not self.manual:
                # Last attempt: the car may have drifted off its lane or sit on a
                # broken lane link. Put it back on the nearest lane, facing the
                # lane's way, so planning has a valid start, then route again.
                pose = (self.cyber.telemetry or {}).get("pose") or {}
                lane = await self.cyber.request(
                    "snap", timeout=15, x=self._last_xy[0], y=self._last_xy[1],
                    radius=15, heading=pose.get("heading"))
                if self.destination is not dest:
                    return  # the trip was ended or replaced meanwhile
                if lane:
                    await self.dreamview.set_start_point(lane["x"], lane["y"], lane["heading"])
                    await asyncio.sleep(1.0)
                    log.info("Re-placed the car on lane %s before rerouting", lane.get("lane_id"))
            if self.destination is not dest:
                return
            result = await self.cyber.request("lane_follow", timeout=15, **args)
            self._record("REROUTE", result)
        except RuntimeError as e:
            log.warning("Reroute failed: %s", e)
        self._moved_at = time.time()  # give the new route time to start

    def _frozen(self, pose: Dict[str, Any]) -> bool:
        xy = (round(pose["x"], 2), round(pose["y"], 2))
        now = time.time()
        if xy != self._last_xy:
            if self._last_xy is not None and math.dist(xy, self._last_xy) > 0.5:
                self._reroutes = 0  # making progress again
            self._last_xy, self._moved_at = xy, now
            return False
        planning = (self.cyber.telemetry or {}).get("planning") or {}
        arrived = math.hypot(pose["x"] - self.destination["x"],
                             pose["y"] - self.destination["y"]) < 10
        stopping = planning.get("main_decision") in ("stop", "mission_complete")
        return (not arrived and not stopping
                and now - self._moved_at > self.STUCK_AFTER_S
                and now - (self.last_action or {}).get("at", 0) > self.STUCK_AFTER_S)

    # ---- lane snapping -----------------------------------------------------

    SNAP_MAX_M = 8.0

    async def snap(self, x: float, y: float, what: str) -> Dict[str, Any]:
        """Nearest lane centre point (with the lane's direction) for a tap
        on the map. Apollo needs points on a lane: an off-lane end point or
        a car placed across a lane leaves planning without a path."""
        snapped = await self.cyber.request("snap", timeout=15, x=x, y=y)
        if not snapped or snapped["distance"] > self.SNAP_MAX_M:
            raise HTTPException(
                409, f"That spot isn't on a road. Tap on a lane to {what}.")
        return snapped

    def _error_persisted(self, speed_mps: float) -> bool:
        """True once Apollo has reported ERROR with the car stopped for a
        few seconds; transient planner failures while moving don't count."""
        if speed_mps > 0.2:
            self._error_since = None
            return False
        if self._error_since is None:
            self._error_since = time.time()
        return time.time() - self._error_since > 4.0

    SIM_MODEL = "Simulation Perfect Control"

    async def start_sim_control(self, spawn: bool = True) -> None:
        """Turns Dreamview's Sim Control on *and* starts its vehicle model.

        Switching the operation to Sim_Control only flips a flag in
        Dreamview Plus; the simulated car comes from a "dynamic model" that
        is picked separately (Dreamview's UI does it from a dropdown). After
        a cold start, or after the operation was switched away (manual
        driving does that), no model runs and the car never appears.
        With [spawn], the car is put on the map's start point if it still
        has no pose."""
        await self.dreamview.hmi_action("CHANGE_OPERATION", "Sim_Control")
        await self.dreamview.hmi_action("LOAD_DYNAMIC_MODELS")
        await self.dreamview.hmi_action("CHANGE_DYNAMIC_MODEL", self.SIM_MODEL)
        if not spawn:
            return
        for _ in range(15):
            await asyncio.sleep(0.2)
            if self._fresh("localization"):
                return
        await self.dreamview.set_start_point()

    async def restore_vehicle(self) -> None:
        """At startup: if nothing publishes the car's pose (e.g. the gateway
        was restarted mid manual-drive, leaving Sim Control off), bring
        Dreamview's Sim Control back so the car reappears. With CARLA or a
        real vehicle the pose is fresh and nothing is touched."""
        for _ in range(40):
            await asyncio.sleep(0.5)
            if self.cyber.connected and self.dreamview.connected:
                break
        else:
            return
        await asyncio.sleep(3.0)
        if self.manual or self._fresh("localization"):
            return
        try:
            log.info("No vehicle pose at startup: enabling Dreamview Sim Control")
            await self.start_sim_control()
        except DreamviewError as e:
            log.warning("Could not enable Sim Control: %s", e)

    # ---- map -------------------------------------------------------------

    async def lanes(self) -> Dict[str, Any]:
        async with self._map_lock:
            key = self.current_map() or "?"
            cached = self._map_cache.get(key)
            if cached is None:
                cached = await self.cyber.request("map_lanes", timeout=60)
                cached["hmi_map"] = key
                self._map_cache = {key: cached}
            return cached

    # ---- commands --------------------------------------------------------

    async def ensure_localization(self) -> None:
        """Without CARLA there is no pose; Dreamview's Sim Control provides
        one, so turn it on automatically for the demo flow."""
        if self._fresh("localization"):
            return
        if not self.dreamview.connected:
            raise HTTPException(409, "No vehicle pose and Dreamview is not "
                                     "reachable to enable Sim Control.")
        await self.start_sim_control()
        for _ in range(30):
            await asyncio.sleep(0.2)
            if self._fresh("localization"):
                return
        raise HTTPException(409, "Sim Control is on but no vehicle pose "
                                 "arrived. Check Dreamview.")

    def speed_kph(self) -> float:
        t = self.cyber.telemetry or {}
        if not self._fresh("chassis"):
            return 0.0
        return ((t.get("chassis") or {}).get("speed_mps") or 0.0) * 3.6

    # ---- manual driving ----------------------------------------------------

    async def set_manual(self, enabled: bool, gear: Optional[str] = None) -> Dict[str, Any]:
        """Hands the car between Apollo (AUTO) and the tablet (MANUAL).

        To manual: cancel any route, switch Dreamview Sim Control off, and
        start the virtual vehicle where the car is. Back to auto: stop the
        virtual vehicle, switch Sim Control on, and put Sim Control's car
        where the driver left it."""
        async with self._mode_lock:
            if enabled == self.manual:
                if enabled and gear:
                    return await self.cyber.request("gear", gear=gear)
                return {"mode": "MANUAL" if enabled else "AUTO"}
            if enabled:
                await self.ensure_localization()
                t = self.cyber.telemetry or {}
                pose = t.get("pose") or {}
                speed = ((t.get("chassis") or {}).get("speed_mps") or 0.0)
                if self.destination is not None:
                    try:
                        await self.action("CLEAR_PLANNING")
                    except RuntimeError:
                        pass
                if (t.get("hmi") or {}).get("current_operation") == "Sim_Control":
                    await self.dreamview.hmi_action("CHANGE_OPERATION", "Record")
                    await asyncio.sleep(0.3)  # let Sim Control stop publishing
                result = await self.cyber.request(
                    "manual_start", x=pose["x"], y=pose["y"],
                    heading=pose["heading"], speed=speed, gear=gear)
                self.manual = True
                self._manual_since = time.time()
                self._record("MANUAL", result)
                asyncio.create_task(self.push_signals())
                return result
            final = await self.cyber.request("manual_stop")
            self.manual = False
            # The start point is set right below, at the hand-back spot.
            await self.start_sim_control(spawn=False)
            await asyncio.sleep(0.3)
            # Planning can only start from a lane: hand back on the nearest
            # one, facing its direction (the driver may have stopped across
            # a lane or off the road).
            try:
                lane = await self.cyber.request(
                    "snap", timeout=15, x=final["x"], y=final["y"], radius=40,
                    heading=final["heading"])
            except RuntimeError:
                lane = None
            if lane:
                final = {**final, "x": lane["x"], "y": lane["y"],
                         "heading": lane["heading"], "snapped_m": lane["distance"]}
            await self.dreamview.set_start_point(final["x"], final["y"], final["heading"])
            self._record("AUTO", final)
            return final

    async def set_gear(self, gear: str) -> Dict[str, Any]:
        gear = gear.upper()
        if gear not in ("P", "R", "N", "D"):
            raise HTTPException(422, "gear must be P, R, N or D")
        if self.manual:
            return await self.cyber.request("gear", gear=gear)
        # Shifting while Apollo drives is a take-over, as in a car: the
        # driver gets control in the chosen gear.
        if gear == "D":
            return {"mode": "AUTO", "gear": "D"}
        if self.speed_kph() > 4:
            raise HTTPException(409, f"Slow down below 4 km/h to shift into {gear}")
        return await self.set_manual(True, gear=gear)

    def drive_input(self, msg: Dict[str, Any]) -> None:
        if not self.manual:
            return
        now = time.time()
        if now - self._last_drive_input < 0.025:  # cap at 40 Hz
            return
        self._last_drive_input = now
        self.cyber.send_nowait(
            "drive",
            throttle=float(msg.get("throttle") or 0),
            brake=float(msg.get("brake") or 0),
            steer=float(msg.get("steer") or 0),
        )

    # ---- body ----------------------------------------------------------------

    def set_body(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        changed = self.body.apply(patch, self.speed_kph())
        if set(changed) & set(SIGNAL_FIELDS):
            asyncio.create_task(self.push_signals())
        return changed

    async def honk(self) -> None:
        self.set_body({"horn": True})
        await asyncio.sleep(0.6)
        self.set_body({"horn": False})

    async def push_signals(self) -> None:
        """Body lights/signals -> Apollo ChassisCommand (+ virtual vehicle).
        Fire-and-forget so the tablet never waits on it."""
        try:
            result = await self.cyber.request(
                "signals", timeout=8, **self.body.apollo_signal())
            self.signal_status = {"ok": True, **result, "at": time.time()}
        except RuntimeError as e:
            self.signal_status = {"ok": False, "message": str(e), "at": time.time()}

    # ---- autopilot ------------------------------------------------------------

    async def go(self, req: GoRequest) -> Dict[str, Any]:
        await self._command_latency()
        if self.manual:
            await self.set_manual(False)  # engage autopilot from manual
            await asyncio.sleep(0.5)
        await self.ensure_localization()
        first = await self.snap(req.x, req.y, "drive there")
        # Routing fails for some lanes of the converted maps (map edges,
        # broken lane links): fall back to the next-nearest lanes.
        try:
            others = await self.cyber.request("snap_candidates", timeout=15,
                                              x=req.x, y=req.y, radius=20, limit=6) or []
        except RuntimeError:
            others = []
        candidates = [first] + [c for c in others if c.get("lane_id") != first.get("lane_id")]
        result, point, last_error = None, None, None
        for cand in candidates:
            args: Dict[str, Any] = {"x": cand["x"], "y": cand["y"], "heading": cand["heading"]}
            if req.target_speed_kph:
                args["target_speed"] = req.target_speed_kph / 3.6
            try:
                result = await self.cyber.request("lane_follow", timeout=15, **args)
                point = cand
                break
            except RuntimeError as e:
                last_error = e
                log.info("No route to lane %s, trying the next one", cand.get("lane_id"))
        if point is None:
            log.warning("Routing failed for every lane near (%.1f, %.1f): %s",
                        req.x, req.y, last_error)
            raise HTTPException(409, "Apollo can't find a route to that spot. "
                                     "Pick a point in the middle of a road.")
        self.destination = {"x": point["x"], "y": point["y"],
                            "heading": point["heading"],
                            "name": req.name or "Dropped pin"}
        self._moved_at = time.time()
        self._reroutes = 0
        self.target_speed_kph = req.target_speed_kph
        self.stop_requested = False
        self._record("GO", result)
        self._safety_ts = None
        self.safety.start_trip(
            destination=dict(self.destination), name=self.destination["name"],
            target_speed_kph=req.target_speed_kph, map=self.current_map(),
            scenario=req.scenario, run=req.run, timeout_s=req.timeout_s)
        return result

    async def _command_latency(self) -> None:
        """command_latency hazard: hold trip commands back."""
        delay = self.hazards.command_delay_s()
        if delay > 0:
            await asyncio.sleep(delay)

    async def action(self, command: str) -> Dict[str, Any]:
        await self._command_latency()
        result = await self.cyber.request("action", timeout=10, command=command)
        if command in ("STOP", "PULL_OVER"):
            self.stop_requested = True
        elif command == "START":
            self.stop_requested = False
        elif command == "CLEAR_PLANNING":
            self.destination = None
            self.stop_requested = False
        self._record(command, result)
        return result

    def _record(self, name: str, result: Any) -> None:
        self.last_action = {"name": name, "at": time.time(),
                            "result": result}


def _remaining_along(line: List[List[float]], pose: Optional[Dict[str, Any]],
                     start: int = 0, window: int = 80):
    """(distance to the end of the route, index of the closest vertex).

    Only vertices from `start` onward are considered, so a route that loops
    back past itself never makes the progress jump ahead."""
    if not pose or len(line) < 2:
        return None, start
    px, py = pose["x"], pose["y"]
    lo = max(0, start - 2)
    hi = min(len(line), start + window)
    best_i, best_d = lo, float("inf")
    for i in range(lo, hi):
        x, y = line[i]
        d = (x - px) ** 2 + (y - py) ** 2
        if d < best_d:
            best_i, best_d = i, d
    total = math.sqrt(best_d)
    for i in range(best_i, len(line) - 1):
        total += math.dist(line[i], line[i + 1])
    return total, best_i


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class StateBroadcaster:
    """Builds and serializes the state once per tick for every /ws client,
    and skips ticks where nothing changed (a parked car sends only a
    keepalive every KEEPALIVE_S)."""

    KEEPALIVE_S = 2.0

    def __init__(self) -> None:
        self.clients: set = set()
        self._task: Optional[asyncio.Task] = None
        self._kick: Optional[asyncio.Event] = None

    def kick(self) -> None:
        """Push the next state right away (after a command)."""
        if self._kick is not None:
            self._kick.set()

    def start(self) -> None:
        self._kick = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        last_body, last_sent = None, 0.0
        period = IDLE_PUSH_PERIOD_S
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), period)
            except asyncio.TimeoutError:
                pass
            self._kick.clear()
            if not self.clients:
                last_body = None
                continue
            snapshot = gw.state(include_route=False)
            moving = snapshot["vehicle"]["speed_kph"] > 0.3 or gw.manual
            period = STATE_PUSH_PERIOD_S if moving else IDLE_PUSH_PERIOD_S
            del snapshot["ts"]
            if gw.hazards.telemetry_paused():
                continue  # telemetry_dropout hazard: tablets get nothing
            body = json.dumps(snapshot, separators=(",", ":"))
            now = time.time()
            if body == last_body and now - last_sent < self.KEEPALIVE_S:
                continue
            last_body, last_sent = body, now
            message = '{"ts":%.3f,%s' % (now, body[1:])
            await asyncio.gather(*(self._send(ws, message)
                                   for ws in list(self.clients)))

    async def _send(self, ws: WebSocket, message: str) -> None:
        try:
            await asyncio.wait_for(ws.send_text(message), 2.0)
        except Exception:  # noqa: BLE001 - slow or closed client
            self.clients.discard(ws)


gw: Gateway
broadcaster = StateBroadcaster()


async def safety_loop() -> None:
    """Feeds each new telemetry sample of an active trip to the validator
    and expires hazards."""
    while True:
        await asyncio.sleep(0.1)
        try:
            gw.hazards.tick()
            t = gw.cyber.telemetry or {}
            speed = ((t.get("chassis") or {}).get("speed_mps") or 0.0)
            gw.v2v.step(t.get("pose") if gw._fresh("localization") else None, speed,
                        (t.get("obstacles") or []) if gw._fresh("perception") else [])
            if not gw.safety.active:
                continue
            ts = (gw.cyber.telemetry or {}).get("ts")
            if ts == gw._safety_ts and gw.cyber.connected:
                continue  # nothing new from Apollo
            gw._safety_ts = ts
            report = gw.safety.sample(gw.state(include_route=False), gw.hazards)
            if report is not None:
                log.info("Trip %s: %s (%s), %d critical / %d warning", report["trip_id"],
                         report["verdict"], report["end_reason"], report["counts"]["critical"],
                         report["counts"]["warning"])
                broadcaster.kick()
        except Exception:  # noqa: BLE001 - never let validation kill the loop
            log.exception("safety loop failed")


class BatchManager:
    """Runs one scenario batch at a time in a background thread. The runner
    drives the gateway through its own HTTP API, like any other client."""

    def __init__(self) -> None:
        self.thread: Optional[threading.Thread] = None
        self.runner: Optional[scn.ScenarioRunner] = None
        self.stop_requested = False
        self.log: deque = deque(maxlen=300)
        self.last_summary: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def _log(self, line: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {line}")
        log.info("scenario: %s", line)

    def start(self, scenarios: List[Dict[str, Any]], repeat: Optional[int]) -> None:
        if self.running:
            raise HTTPException(409, "A scenario batch is already running")
        port = int(os.getenv("KAIRO_GATEWAY_PORT", "8090"))
        self.stop_requested = False
        self.error = None
        self.log.clear()
        self.runner = scn.ScenarioRunner(scn.GatewayClient(f"http://127.0.0.1:{port}"),
                                         log=self._log, should_stop=lambda: self.stop_requested)

        def work() -> None:
            try:
                self.last_summary = self.runner.run_batch(scenarios, repeat)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                self._log(f"batch failed: {e}")

        self.thread = threading.Thread(target=work, daemon=True, name="scenario-batch")
        self.thread.start()

    def status(self) -> Dict[str, Any]:
        return {"running": self.running, "stop_requested": self.stop_requested,
                "progress": self.runner.progress if self.runner else None,
                "error": self.error, "log": list(self.log)[-40:],
                "last_summary": self.last_summary}


batches = BatchManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global gw
    gw = Gateway()
    gw.cyber.start()
    gw.dreamview.start()
    broadcaster.start()
    asyncio.create_task(gw.restore_vehicle())
    asyncio.create_task(safety_loop())
    log.info("KAIRO gateway up (container=%s, dreamview=%s)", CONTAINER, DREAMVIEW_WS)
    yield
    broadcaster.stop()
    gw.cyber.stop()
    await gw.dreamview.stop()


app = FastAPI(title="KAIRO Vehicle Gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=4096)  # /api/map is ~250 KB


async def _run(coro) -> Dict[str, Any]:
    try:
        result = await coro
    except HTTPException:
        raise
    except DreamviewError as e:
        raise HTTPException(502, f"Dreamview: {e}") from e
    except RuntimeError as e:
        raise HTTPException(409 if "Slow down" in str(e) or "manually" in str(e)
                            else 502, f"Apollo: {e}") from e
    broadcaster.kick()
    return {"ok": True, "result": result, "state": gw.state()}


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, **gw.state()["gateway"]}


@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    return gw.state()


@app.get("/api/route")
def get_route() -> Dict[str, Any]:
    scene = gw.state()["scene"]
    return {"rev": scene["route_rev"], "route": scene["route"]}


@app.get("/api/map")
async def get_map() -> Dict[str, Any]:
    try:
        return await gw.lanes()
    except RuntimeError as e:
        raise HTTPException(502, f"Apollo: {e}") from e


# ---- autopilot -------------------------------------------------------------

@app.post("/api/autopilot/go")
async def autopilot_go(req: GoRequest):
    return await _run(gw.go(req))


@app.post("/api/autopilot/stop")
async def autopilot_stop():
    return await _run(gw.action("STOP"))


@app.post("/api/autopilot/pull_over")
async def autopilot_pull_over():
    return await _run(gw.action("PULL_OVER"))


@app.post("/api/autopilot/resume")
async def autopilot_resume():
    return await _run(gw.action("START"))


@app.post("/api/autopilot/cancel")
async def autopilot_cancel():
    return await _run(gw.action("CLEAR_PLANNING"))


@app.post("/api/autopilot/lane_change/{direction}")
async def autopilot_lane_change(direction: str):
    command = {"left": "CHANGE_LEFT", "right": "CHANGE_RIGHT"}.get(direction)
    if command is None:
        raise HTTPException(404, "direction must be left or right")
    return await _run(gw.action(command))


# ---- dreamview HMI -----------------------------------------------------------

@app.post("/api/dreamview/sim_control")
async def dv_sim_control(req: EnabledRequest):
    if req.enabled and gw.manual:
        return await _run(gw.set_manual(False))
    if req.enabled:
        return await _run(gw.start_sim_control())
    return await _run(gw.dreamview.hmi_action("CHANGE_OPERATION", "Record"))


@app.post("/api/dreamview/map")
async def dv_map(req: NameRequest):
    gw.destination = None
    return await _run(gw.dreamview.hmi_action("CHANGE_MAP", req.name))


@app.post("/api/dreamview/mode")
async def dv_mode(req: NameRequest):
    return await _run(gw.dreamview.hmi_action("CHANGE_MODE", req.name))


@app.post("/api/dreamview/modules/{name}")
async def dv_module(name: str, req: ModuleRequest):
    return await _run(gw.dreamview.hmi_action(
        "START_MODULE" if req.running else "STOP_MODULE", name))


@app.post("/api/dreamview/setup")
async def dv_setup():
    return await _run(gw.dreamview.hmi_action("SETUP_MODE"))


@app.post("/api/dreamview/reset_mode")
async def dv_reset_mode():
    return await _run(gw.dreamview.hmi_action("RESET_MODE"))


@app.post("/api/dreamview/start_point")
async def dv_start_point(req: StartPointRequest):
    async def move():
        x, y, heading = req.x, req.y, req.heading
        if x is not None and y is not None:
            # Place the car on the lane, pointing the way the lane runs.
            lane = await gw.snap(x, y, "place the car")
            x, y, heading = lane["x"], lane["y"], lane["heading"]
        result = await gw.dreamview.set_start_point(x, y, heading)
        gw.destination = None
        return {**result, "x": x, "y": y, "heading": heading}
    return await _run(move())


@app.get("/api/snap")
async def snap(x: float, y: float):
    try:
        return await gw.cyber.request("snap", timeout=15, x=x, y=y) or {}
    except RuntimeError as e:
        raise HTTPException(502, f"Apollo: {e}") from e


# ---- manual driving -----------------------------------------------------------

@app.post("/api/drive/manual")
async def drive_manual(req: EnabledRequest):
    return await _run(gw.set_manual(req.enabled))


@app.post("/api/drive/gear")
async def drive_gear(req: GearRequest):
    return await _run(gw.set_gear(req.gear))


# ---- body controls ---------------------------------------------------------------

@app.post("/api/body")
async def set_body(patch: Dict[str, Any]):
    try:
        changed = gw.set_body(patch)
    except BodyError as e:
        raise HTTPException(409, str(e)) from e
    broadcaster.kick()
    return {"ok": True, "result": changed, "state": gw.state()}


@app.post("/api/body/horn")
async def honk():
    asyncio.create_task(gw.honk())
    broadcaster.kick()
    return {"ok": True, "result": None, "state": gw.state()}


# ---- places on the current HD map --------------------------------------------

@app.put("/api/places/{place_id}")
async def put_place(place_id: str, req: PlaceRequest):
    map_name = gw.current_map()
    if not map_name:
        raise HTTPException(409, "No HD map loaded in Dreamview")
    try:
        lane = await gw.snap(req.x, req.y, "save it")
    except RuntimeError as e:
        raise HTTPException(502, f"Apollo: {e}") from e
    gw.put_place(map_name, place_id, {**req.model_dump(), "x": lane["x"],
                                      "y": lane["y"], "heading": lane["heading"]})
    return {"ok": True, "places": gw.places_for(map_name)}


@app.delete("/api/places/{place_id}")
def delete_place(place_id: str):
    map_name = gw.current_map()
    if map_name:
        gw.delete_place(map_name, place_id)
    return {"ok": True, "places": gw.places_for(map_name)}


# ---- simulated traffic ------------------------------------------------------------

@app.get("/api/traffic")
async def traffic_status():
    try:
        return await gw.cyber.request("traffic_status", timeout=10)
    except RuntimeError as e:
        raise HTTPException(502, f"Apollo: {e}") from e


@app.post("/api/traffic/start")
async def traffic_start(req: TrafficRequest):
    modules = ((gw.cyber.telemetry or {}).get("hmi") or {}).get("modules") or {}
    if modules.get("Prediction"):
        raise HTTPException(409, "Stop Apollo's Prediction module first: simulated "
                                 "traffic publishes the predictions itself.")
    return await _run(gw.cyber.request("traffic_start", timeout=30, **req.model_dump()))


@app.post("/api/traffic/stop")
async def traffic_stop():
    return await _run(gw.cyber.request("traffic_stop", timeout=10))


# ---- hazard injection ---------------------------------------------------------------

@app.get("/api/hazards")
def hazards_list():
    gw.hazards.tick()
    return gw.hazards.listing()


@app.post("/api/hazards")
async def hazard_start(body: Dict[str, Any]):
    params = dict(body)
    kind = params.pop("type", None)
    try:
        rec = await gw.hazards.start(str(kind), params)
    except HazardError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, f"Apollo: {e}") from e
    broadcaster.kick()
    return {"ok": True, "hazard": rec}


@app.delete("/api/hazards/{hazard_id}")
async def hazard_stop(hazard_id: str):
    try:
        rec = await gw.hazards.stop(hazard_id)
    except HazardError as e:
        raise HTTPException(404, str(e)) from e
    broadcaster.kick()
    return {"ok": True, "hazard": rec}


@app.post("/api/hazards/clear")
async def hazards_clear():
    stopped = await gw.hazards.clear()
    broadcaster.kick()
    return {"ok": True, "stopped": [r["id"] for r in stopped]}


# ---- simulated V2V -----------------------------------------------------------------------

class V2VConfig(BaseModel):
    enabled: Optional[bool] = None
    loss_p: Optional[float] = Field(None, ge=0, le=1)
    latency_ms: Optional[float] = Field(None, ge=0, le=5000)
    range_m: Optional[float] = Field(None, gt=0, le=2000)


@app.get("/api/v2v")
def v2v_status():
    return gw.v2v.summary()


@app.post("/api/v2v/config")
def v2v_config(cfg: V2VConfig):
    gw.v2v.configure(**cfg.model_dump())
    broadcaster.kick()
    return gw.v2v.summary()


# ---- safety validation ----------------------------------------------------------------

@app.get("/api/safety")
def safety_live():
    return {**gw.safety.live(), "rules": RULES}


@app.get("/api/safety/reports")
def safety_reports(limit: int = 50):
    return {"reports": gw.safety.list_reports(min(max(limit, 1), 500))}


@app.get("/api/safety/reports/{trip_id}")
def safety_report(trip_id: str):
    report = gw.safety.get_report(trip_id)
    if report is None:
        raise HTTPException(404, f"No report '{trip_id}'")
    return report


# ---- scenarios and benchmarks -----------------------------------------------------------

@app.get("/api/scenarios")
def scenarios_list():
    return {"scenarios": scn.list_scenarios()}


@app.post("/api/scenarios/run")
def scenarios_run(req: ScenarioRunRequest):
    names = req.names or [s["id"] for s in scn.list_scenarios() if "error" not in s]
    try:
        scenarios = [scn.find(n) for n in names]
    except scn.ScenarioError as e:
        raise HTTPException(422, str(e)) from e
    batches.start(scenarios, req.repeat)
    return {"ok": True, **batches.status()}


@app.get("/api/scenarios/batch")
def scenarios_batch():
    return batches.status()


@app.post("/api/scenarios/stop")
def scenarios_stop():
    batches.stop_requested = True
    return {"ok": True, **batches.status()}


@app.get("/api/benchmarks")
def benchmarks_list():
    return {"benchmarks": scn.list_benchmarks()}


@app.get("/api/benchmarks/{batch_id}")
def benchmark_get(batch_id: str):
    path = scn.BENCHMARK_DIR / f"{batch_id}.json"
    if "/" in batch_id or "\\" in batch_id or not path.exists():
        raise HTTPException(404, f"No benchmark '{batch_id}'")
    return json.loads(path.read_text(encoding="utf-8"))


# ---- live state stream ---------------------------------------------------------

@app.websocket("/ws")
async def ws_state(ws: WebSocket):
    await ws.accept()
    try:
        # Current state right away; then the shared broadcaster takes over.
        await ws.send_text(json.dumps(gw.state(include_route=False),
                                      separators=(",", ":")))
        broadcaster.clients.add(ws)
        while True:
            raw = await ws.receive_text()
            if raw.startswith('{"type":"drive"'):
                try:
                    gw.drive_input(json.loads(raw))
                except (ValueError, TypeError):
                    pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        broadcaster.clients.discard(ws)


@app.get("/")
def root(request: Request):
    host = request.url.hostname
    return {
        "service": "KAIRO Vehicle Gateway",
        "dreamview": f"http://{host}:{DREAMVIEW_PORT}",
        "state": "/api/state",
        "stream": "/ws",
    }
