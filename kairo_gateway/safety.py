"""Safety validation of autonomous trips.

The gateway feeds every new state sample (about 10 per second while the car
moves) into SafetyValidator.sample(). Each rule in RULES is checked on every
sample; a violation is recorded as one *episode* - from the first sample
where the rule fails to the last - with its peak value, so a two-second
hard brake is one violation, not twenty. A rule with min_duration_s only
counts once it has failed for that long.

When the trip ends (arrived, error, cancelled, takeover, timeout) a JSON
report is written to data/reports/<trip_id>.json:

  verdict  PASS        arrived, no critical violation
           FAIL        a critical violation, an error or a timeout
           INCOMPLETE  cancelled or taken over without a critical violation
"""

import json
import math
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

RULES_VERSION = "1.0"

RULES: List[Dict[str, Any]] = [
    {"id": "R1", "name": "Over-speed", "severity": "warning", "threshold": 1.10, "unit": "x cruise",
     "min_duration_s": 1.0, "description": "Speed above the cruise setting by more than 10 %"},
    {"id": "R2", "name": "Harsh braking", "severity": "warning", "threshold": 4.0, "unit": "m/s²",
     "min_duration_s": 0.0, "description": "Deceleration above 4 m/s²"},
    {"id": "R3", "name": "Emergency braking", "severity": "critical", "threshold": 6.0, "unit": "m/s²",
     "min_duration_s": 0.0, "description": "Deceleration above 6 m/s²"},
    {"id": "R4", "name": "Harsh acceleration", "severity": "warning", "threshold": 3.0, "unit": "m/s²",
     "min_duration_s": 0.0, "description": "Acceleration above 3 m/s²"},
    {"id": "R5", "name": "Lateral acceleration", "severity": "warning", "threshold": 3.0, "unit": "m/s²",
     "min_duration_s": 0.5, "description": "Lateral acceleration above 3 m/s²"},
    {"id": "R6", "name": "Obstacle proximity", "severity": "critical", "threshold": 2.0, "unit": "m",
     "min_duration_s": 0.3, "description": "Gap to an obstacle in the car's path below 2 m"},
    {"id": "R7", "name": "Time to collision", "severity": "critical", "threshold": 1.5, "unit": "s",
     "min_duration_s": 0.3, "description": "Time to collision with an obstacle ahead below 1.5 s"},
    {"id": "R8", "name": "Planner emergency stop", "severity": "warning", "threshold": None, "unit": None,
     "min_duration_s": 0.0, "description": "The planner reported an emergency stop"},
    {"id": "R9", "name": "Stall", "severity": "critical", "threshold": 10.0, "unit": "s",
     "min_duration_s": 10.0, "description": "Not moving for over 10 s while driving, with no deliberate "
                                            "stop and nothing close ahead, or trip ended in ERROR"},
    {"id": "R10", "name": "Route completion", "severity": "critical", "threshold": None, "unit": "s",
     "min_duration_s": 0.0, "description": "Not arrived within the trip's time limit"},
    {"id": "R11", "name": "Collision", "severity": "critical", "threshold": 0.0, "unit": "m",
     "min_duration_s": 0.0, "description": "The car's footprint overlaps an obstacle"},
]
RULE_BY_ID = {r["id"]: r for r in RULES}

# Ego vehicle geometry (Apollo's default Lincoln MKZ). Apollo's pose is the
# rear-axle centre; the footprint runs 0.995 m behind and 3.89 m ahead of it.
EGO_LENGTH, EGO_WIDTH = 4.93, 2.11
EGO_REAR_TO_CENTER = 1.45
IN_PATH_LATERAL_M = 1.8      # obstacle centre within this of the car's axis
CPA_MARGIN_M = 0.3           # extra clearance for "would pass too close"
ACCEL_WINDOW_S = 0.4         # accelerations from speed this far apart
DEFAULT_TIMEOUT_S = 300.0
START_GRACE_S = 2.0
# Dreamview's Sim Control can freeze the car (it keeps reporting a speed) and
# later jump it along the route. Stalls are judged by movement, and a jump
# is recorded as a simulator anomaly instead of an acceleration.
STILL_RADIUS_M = 1.0
STILL_AFTER_S = 2.0
WAITING_GAP_M = 15.0         # an obstacle this close ahead explains a stop
JUMP_SETTLE_S = 1.0          # no accelerations this long after a jump
TIMELINE_PERIOD_S = 1.0


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def _corners(cx: float, cy: float, h: float, length: float, width: float):
    c, s = math.cos(h), math.sin(h)
    return [(cx + fx * length / 2 * c - fy * width / 2 * s,
             cy + fx * length / 2 * s + fy * width / 2 * c)
            for fx, fy in ((1, 1), (1, -1), (-1, -1), (-1, 1))]


def boxes_overlap(a, b) -> bool:
    """Separating-axis test for two rectangles given as 4 corners each."""
    for poly in (a, b):
        for i in range(4):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % 4]
            nx, ny = y2 - y1, x1 - x2
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def obstacle_relations(pose: Dict[str, float], speed: float,
                       obstacles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Gap to the closest obstacle in the car's path, time to collision,
    and whether any obstacle overlaps the car's footprint.

    The gap only counts stopped obstacles and ones travelling the car's
    way (the car's heading is a poor guide to oncoming traffic in a turn).
    Time to collision uses the closest point of approach of the two
    vehicles' straight-line motion: it counts only when they would pass
    within a car width of each other, and is the time until the bumpers
    meet."""
    h = pose["heading"]
    cx = pose["x"] + EGO_REAR_TO_CENTER * math.cos(h)
    cy = pose["y"] + EGO_REAR_TO_CENTER * math.sin(h)
    ego_box = _corners(cx, cy, h, EGO_LENGTH, EGO_WIDTH)
    c, s = math.cos(h), math.sin(h)
    evx, evy = speed * c, speed * s
    best_gap: Optional[float] = None
    best_ttc: Optional[float] = None
    gap_obstacle = None
    collision = None
    for o in obstacles:
        ox, oy = float(o.get("x") or 0), float(o.get("y") or 0)
        oh = float(o.get("heading") or 0)
        ol, ow = float(o.get("length") or 4.0), float(o.get("width") or 2.0)
        ov = float(o.get("speed") or 0)
        dx, dy = ox - cx, oy - cy
        fwd, lat = dx * c + dy * s, -dx * s + dy * c
        if abs(fwd) > 60 or abs(lat) > 30:
            continue
        if collision is None and boxes_overlap(ego_box, _corners(ox, oy, oh, ol, ow)):
            collision = o.get("id")
        dh = _wrap(oh - h)
        if (fwd > 0 and abs(lat) <= IN_PATH_LATERAL_M
                and (ov < 0.5 or math.cos(dh) > 0.5)):
            extent = abs(math.cos(dh)) * ol / 2 + abs(math.sin(dh)) * ow / 2
            gap = max(0.0, fwd - EGO_LENGTH / 2 - extent)
            if best_gap is None or gap < best_gap:
                best_gap, gap_obstacle = gap, o.get("id")
        # Closest point of approach, relative to the car.
        rvx, rvy = ov * math.cos(oh) - evx, ov * math.sin(oh) - evy
        rv2 = rvx * rvx + rvy * rvy
        if rv2 < 0.01:
            continue
        t_cpa = -(dx * rvx + dy * rvy) / rv2
        if t_cpa <= 0:
            continue  # moving apart
        miss = math.hypot(dx + rvx * t_cpa, dy + rvy * t_cpa)
        if miss < (EGO_WIDTH + ow) / 2 + CPA_MARGIN_M:
            ttc = max(0.0, t_cpa - (EGO_LENGTH + ol) / 2 / math.sqrt(rv2))
            if best_ttc is None or ttc < best_ttc:
                best_ttc = ttc
    return {"gap": best_gap, "ttc": best_ttc, "gap_obstacle": gap_obstacle,
            "collision": collision}


class Trip:
    def __init__(self, trip_id: str, started_at: float, info: Dict[str, Any]):
        self.id = trip_id
        self.started_at = started_at
        self.info = info
        self.timeout_s = float(info.get("timeout_s") or DEFAULT_TIMEOUT_S)
        self.target_mps = (info.get("target_speed_kph") or 0) / 3.6 or None
        self.last_t: Optional[float] = None
        self.last_xy: Optional[Tuple[float, float]] = None
        self.history: deque = deque()      # (t, speed, heading)
        self.distance = 0.0
        self.samples = 0
        self.metrics: Dict[str, Optional[float]] = {
            "max_speed_kph": 0.0, "max_accel_mps2": 0.0, "max_decel_mps2": 0.0,
            "max_lat_accel_mps2": 0.0, "min_gap_m": None, "min_ttc_s": None,
            "max_obstacles": 0, "estop_count": 0,
        }
        self.episodes: Dict[str, Dict[str, Any]] = {}
        self.violations: List[Dict[str, Any]] = []
        self.timeline: List[List[float]] = []
        self.final_pose: Optional[Dict[str, float]] = None
        self.last_state: Optional[str] = None
        self.anomalies: List[Dict[str, Any]] = []
        self.settle_until = 0.0
        # Where and when the car last moved more than STILL_RADIUS_M.
        self.anchor: Optional[Tuple[float, float]] = None
        self.anchor_t = 0.0


class SafetyValidator:
    def __init__(self, reports_dir: Path, clock: Callable[[], float] = time.time):
        self.dir = Path(reports_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self.trip: Optional[Trip] = None
        self._index: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self.dir.glob("*.json")):
            try:
                self._index[path.stem] = self._summary(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError):
                continue
        self.last_summary: Optional[Dict[str, Any]] = (
            max(self._index.values(), key=lambda r: r["started_at"]) if self._index else None)

    # ---- trip lifecycle ----------------------------------------------------

    @property
    def active(self) -> bool:
        return self.trip is not None

    def start_trip(self, **info: Any) -> str:
        """info: destination, target_speed_kph, map, scenario, run, timeout_s."""
        if self.trip is not None:
            self.finish("replaced")
        now = self._clock()
        label = info.get("scenario") or info.get("name") or "trip"
        slug = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")[:40] or "trip"
        trip_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{slug}"
        if info.get("run") is not None:
            trip_id += f"-r{info['run']}"
        while trip_id in self._index:
            trip_id += "x"
        self.trip = Trip(trip_id, now, info)
        return trip_id

    def sample(self, state: Dict[str, Any], hazards=None) -> Optional[Dict[str, Any]]:
        """Feed one gateway state snapshot. Returns the report if the trip
        ended with this sample."""
        trip = self.trip
        if trip is None:
            return None
        t = float(state.get("ts") or self._clock())
        vehicle = state.get("vehicle") or {}
        auto = state.get("autopilot") or {}
        pose = vehicle.get("pose")
        speed = float(vehicle.get("speed_kph") or 0) / 3.6
        ap_state = auto.get("state")
        trip.last_state = ap_state
        elapsed = t - trip.started_at

        # A sample built just before the new command can still carry the
        # previous trip's end state; ignore end states for a moment.
        settled = elapsed > START_GRACE_S
        if (state.get("drive") or {}).get("mode") == "MANUAL":
            return self.finish("takeover", hazards, t)
        if settled and auto.get("destination") is None and ap_state in ("READY", "UNAVAILABLE"):
            return self.finish("cancelled", hazards, t)
        if settled and ap_state == "OFFLINE":
            return self.finish("offline", hazards, t)

        if pose is not None:
            trip.samples += 1
            trip.final_pose = pose
            self._kinematics(trip, t, speed, pose)
            obstacles = (state.get("scene") or {}).get("obstacles") or []
            trip.metrics["max_obstacles"] = max(trip.metrics["max_obstacles"], len(obstacles))
            rel = obstacle_relations(pose, speed, obstacles)
            m = trip.metrics
            if rel["gap"] is not None:
                m["min_gap_m"] = rel["gap"] if m["min_gap_m"] is None else min(m["min_gap_m"], rel["gap"])
            if rel["ttc"] is not None:
                m["min_ttc_s"] = rel["ttc"] if m["min_ttc_s"] is None else min(m["min_ttc_s"], rel["ttc"])

            accel, lat = self._accelerations(trip, t, speed, pose)
            xy = (pose["x"], pose["y"])
            if trip.anchor is None or math.dist(xy, trip.anchor) > STILL_RADIUS_M:
                trip.anchor, trip.anchor_t = xy, t
            stalled = (t - trip.anchor_t >= STILL_AFTER_S and ap_state == "DRIVING"
                       and auto.get("decision") not in ("stop", "mission_complete")
                       and (rel["gap"] is None or rel["gap"] > WAITING_GAP_M))
            checks = {
                "R1": (trip.target_mps is not None and speed > trip.target_mps * 1.10,
                       speed / trip.target_mps if trip.target_mps else 0.0),
                "R2": (accel is not None and -accel > 4.0, -(accel or 0.0)),
                "R3": (accel is not None and -accel > 6.0, -(accel or 0.0)),
                "R4": (accel is not None and accel > 3.0, accel or 0.0),
                "R5": (lat is not None and abs(lat) > 3.0, abs(lat or 0.0)),
                "R6": (rel["gap"] is not None and rel["gap"] < 2.0, rel["gap"]),
                "R7": (rel["ttc"] is not None and rel["ttc"] < 1.5, rel["ttc"]),
                "R8": (ap_state == "ESTOP", None),
                "R9": (stalled, None),
                "R11": (rel["collision"] is not None, rel["collision"]),
            }
            for rule_id, (failing, value) in checks.items():
                self._episode(trip, rule_id, failing, value, t, pose)
            if ap_state == "ESTOP" and trip.episodes.get("R8", {}).get("start") == t:
                m["estop_count"] += 1

        if settled and ap_state == "ARRIVED":
            return self.finish("arrived", hazards, t)
        if settled and ap_state == "ERROR":
            self._violation(trip, "R9", t, t, None, trip.final_pose, note="trip ended in ERROR")
            return self.finish("error", hazards, t)
        if elapsed > trip.timeout_s:
            self._violation(trip, "R10", t, t, round(elapsed, 1), trip.final_pose,
                            note=f"time limit {trip.timeout_s:.0f} s")
            return self.finish("timeout", hazards, t)
        return None

    def finish(self, reason: str, hazards=None, t: Optional[float] = None) -> Optional[Dict[str, Any]]:
        trip = self.trip
        if trip is None:
            return None
        self.trip = None
        end = t if t is not None else self._clock()
        for rule_id in list(trip.episodes):
            self._close_episode(trip, rule_id)
        critical = sum(1 for v in trip.violations if v["severity"] == "critical")
        warning = len(trip.violations) - critical
        if reason == "arrived" and not critical:
            verdict = "PASS"
        elif critical or reason in ("error", "timeout"):
            verdict = "FAIL"
        else:
            verdict = "INCOMPLETE"
        dest = trip.info.get("destination") or {}
        arrival_error = None
        if trip.final_pose and dest.get("x") is not None:
            arrival_error = round(math.hypot(trip.final_pose["x"] - dest["x"],
                                             trip.final_pose["y"] - dest["y"]), 2)
        metrics = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in trip.metrics.items()}
        report = {
            "trip_id": trip.id,
            "scenario": trip.info.get("scenario"),
            "run": trip.info.get("run"),
            "name": trip.info.get("name"),
            "map": trip.info.get("map"),
            "verdict": verdict,
            "end_reason": reason,
            "started_at": round(trip.started_at, 3),
            "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(trip.started_at)),
            "duration_s": round(end - trip.started_at, 2),
            "distance_m": round(trip.distance, 1),
            "destination": dest or None,
            "target_speed_kph": trip.info.get("target_speed_kph"),
            "timeout_s": trip.timeout_s,
            "arrival_error_m": arrival_error,
            "metrics": metrics,
            "counts": {"critical": critical, "warning": warning},
            "violations": trip.violations,
            "hazards": hazards.overlapping(trip.started_at, end) if hazards else [],
            "anomalies": trip.anomalies,
            "timeline": trip.timeline,
            "samples": trip.samples,
            "rules_version": RULES_VERSION,
        }
        path = self.dir / f"{trip.id}.json"
        path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        self._index[trip.id] = self._summary(report)
        self.last_summary = self._index[trip.id]
        return report

    # ---- internals ------------------------------------------------------------

    @staticmethod
    def _kinematics(trip: Trip, t: float, speed: float, pose: Dict[str, float]) -> None:
        xy = (pose["x"], pose["y"])
        if trip.last_xy is not None:
            step = math.dist(xy, trip.last_xy)
            dt = max(t - (trip.last_t or t), 0.05)
            prev_speed = trip.history[-1][1] if trip.history else speed
            if step > max(8.0, 3 * max(speed, prev_speed) * dt + 3.0):
                # The simulator moved the car: not driving, and accelerations
                # across the jump are meaningless.
                trip.anomalies.append({
                    "type": "position_jump", "t_s": round(t - trip.started_at, 2),
                    "distance_m": round(step, 1),
                    "from": [round(trip.last_xy[0], 1), round(trip.last_xy[1], 1)],
                    "to": [round(xy[0], 1), round(xy[1], 1)]})
                trip.history.clear()
                trip.settle_until = t + JUMP_SETTLE_S  # speed jumps with it
            else:
                trip.distance += step
        trip.last_xy = xy
        trip.last_t = t
        trip.metrics["max_speed_kph"] = max(trip.metrics["max_speed_kph"], speed * 3.6)
        if not trip.timeline or t - trip.started_at - trip.timeline[-1][0] >= TIMELINE_PERIOD_S:
            trip.timeline.append([round(t - trip.started_at, 1), round(speed * 3.6, 1),
                                  round(pose["x"], 1), round(pose["y"], 1)])

    @staticmethod
    def _accelerations(trip: Trip, t: float, speed: float, pose: Dict[str, float]):
        if t < trip.settle_until:
            trip.history.clear()
        trip.history.append((t, speed, pose["heading"]))
        while trip.history and t - trip.history[0][0] > 2.0:
            trip.history.popleft()
        ref = None
        for sample in reversed(trip.history):
            if t - sample[0] >= ACCEL_WINDOW_S:
                ref = sample
                break
        if ref is None:
            return None, None
        dt = t - ref[0]
        accel = (speed - ref[1]) / dt
        lat = (speed + ref[1]) / 2 * _wrap(pose["heading"] - ref[2]) / dt
        m = trip.metrics
        m["max_accel_mps2"] = max(m["max_accel_mps2"], accel)
        m["max_decel_mps2"] = max(m["max_decel_mps2"], -accel)
        m["max_lat_accel_mps2"] = max(m["max_lat_accel_mps2"], abs(lat))
        return accel, lat

    def _episode(self, trip: Trip, rule_id: str, failing: bool, value, t: float,
                 pose: Dict[str, float]) -> None:
        ep = trip.episodes.get(rule_id)
        if failing:
            if ep is None:
                trip.episodes[rule_id] = {"start": t, "last": t, "peak": value,
                                          "x": pose["x"], "y": pose["y"]}
            else:
                ep["last"] = t
                ep["peak"] = self._worse(rule_id, ep["peak"], value)
        elif ep is not None:
            self._close_episode(trip, rule_id)

    @staticmethod
    def _worse(rule_id: str, a, b):
        if a is None or not isinstance(a, (int, float)):
            return b
        if b is None or not isinstance(b, (int, float)):
            return a
        # Smaller is worse for gaps and times to collision.
        return min(a, b) if rule_id in ("R6", "R7") else max(a, b)

    def _close_episode(self, trip: Trip, rule_id: str) -> None:
        ep = trip.episodes.pop(rule_id, None)
        if ep is None:
            return
        rule = RULE_BY_ID[rule_id]
        if ep["last"] - ep["start"] >= rule["min_duration_s"] - 1e-6:
            self._violation(trip, rule_id, ep["start"], ep["last"], ep["peak"],
                            {"x": ep["x"], "y": ep["y"]})

    @staticmethod
    def _violation(trip: Trip, rule_id: str, start: float, end: float, value, pose,
                   note: Optional[str] = None) -> None:
        rule = RULE_BY_ID[rule_id]
        v = {
            "rule": rule_id,
            "name": rule["name"],
            "severity": rule["severity"],
            "t_s": round(start - trip.started_at, 2),
            "duration_s": round(end - start, 2),
            "value": round(value, 2) if isinstance(value, float) else value,
            "threshold": rule["threshold"],
            "x": round(pose["x"], 1) if pose else None,
            "y": round(pose["y"], 1) if pose else None,
        }
        if note:
            v["note"] = note
        trip.violations.append(v)

    @staticmethod
    def _summary(report: Dict[str, Any]) -> Dict[str, Any]:
        return {k: report.get(k) for k in (
            "trip_id", "scenario", "run", "name", "map", "verdict", "end_reason",
            "started_at", "started_at_iso", "duration_s", "distance_m", "counts")}

    # ---- queries ---------------------------------------------------------------

    def live(self) -> Dict[str, Any]:
        trip = self.trip
        out: Dict[str, Any] = {"active": trip is not None, "last_report": self.last_summary}
        if trip is not None:
            now = self._clock()
            ongoing = []
            for rule_id, ep in trip.episodes.items():
                rule = RULE_BY_ID[rule_id]
                if ep["last"] - ep["start"] >= rule["min_duration_s"]:
                    ongoing.append({"rule": rule_id, "name": rule["name"],
                                    "severity": rule["severity"]})
            critical = sum(1 for v in trip.violations if v["severity"] == "critical")
            out.update({
                "trip_id": trip.id,
                "scenario": trip.info.get("scenario"),
                "elapsed_s": round(now - trip.started_at, 1),
                "counts": {"critical": critical, "warning": len(trip.violations) - critical},
                "ongoing": ongoing,
                "last_violation": trip.violations[-1] if trip.violations else None,
            })
        return out

    def list_reports(self, limit: int = 50) -> List[Dict[str, Any]]:
        return sorted(self._index.values(), key=lambda r: r["started_at"], reverse=True)[:limit]

    def get_report(self, trip_id: str) -> Optional[Dict[str, Any]]:
        if trip_id not in self._index or "/" in trip_id or "\\" in trip_id:
            return None
        try:
            return json.loads((self.dir / f"{trip_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
