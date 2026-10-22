"""Hazard injection.

Two kinds of hazard:
  in-world  (phantom_obstacle, cut_in, perception_dropout) run inside the
            Apollo container, in kairo_traffic.py, so Apollo's planning sees
            them exactly like real objects;
  gateway   (telemetry_dropout, command_latency) act on the link between
            the tablet and the gateway.

Every hazard gets an id and a record with its start and end time, so safety
reports can list the hazards that were active during a trip.
"""

import itertools
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

HAZARD_TYPES: Dict[str, Dict[str, Any]] = {
    "phantom_obstacle": {
        "where": "world",
        "description": "Static object placed ahead of the car on its route",
        "defaults": {"ahead_m": 25.0, "duration_s": 10.0, "object": "vehicle"},
    },
    "cut_in": {
        "where": "world",
        "description": "Vehicle in the neighbouring lane merges in front of the car",
        "defaults": {"ahead_m": 25.0, "side": "auto", "speed_factor": 0.6,
                     "delay_s": 1.0, "change_s": 3.0, "duration_s": 15.0},
    },
    "perception_dropout": {
        "where": "world",
        "description": "All obstacles disappear for a while, then come back",
        "defaults": {"duration_s": 2.0},
    },
    "telemetry_dropout": {
        "where": "gateway",
        "description": "State stream to the tablets pauses",
        "defaults": {"duration_s": 3.0},
    },
    "command_latency": {
        "where": "gateway",
        "description": "Trip commands are delayed before they reach Apollo",
        "defaults": {"delay_ms": 800.0, "duration_s": 30.0},
    },
}


class HazardError(ValueError):
    pass


class HazardManager:
    def __init__(self, request: Callable[..., Any], clock: Callable[[], float] = time.time):
        """request: async callable (cmd, **args) into the Cyber daemon."""
        self._request = request
        self._clock = clock
        self._ids = itertools.count(1)
        self.active: Dict[str, Dict[str, Any]] = {}
        self.history: deque = deque(maxlen=200)

    # ---- control -------------------------------------------------------------

    def _record(self, kind: str, params: Dict[str, Any]) -> Dict[str, Any]:
        spec = HAZARD_TYPES.get(kind)
        if spec is None:
            raise HazardError(f"Unknown hazard type '{kind}'. "
                              f"Known: {', '.join(sorted(HAZARD_TYPES))}")
        merged = {**spec["defaults"], **{k: v for k, v in params.items() if v is not None}}
        duration = float(merged.get("duration_s") or 0)
        if not 0 < duration <= 600:
            raise HazardError("duration_s must be between 0 and 600 seconds")
        now = self._clock()
        return {
            "id": f"hz-{next(self._ids)}",
            "type": kind,
            "where": spec["where"],
            "params": merged,
            "started_at": round(now, 3),
            "ends_at": round(now + duration, 3),
            "ended_at": None,
            "status": "active",
            "result": None,
        }

    async def start(self, kind: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rec = self._record(kind, dict(params or {}))
        if rec["where"] == "world":
            rec["result"] = await self._request(
                "hazard_start", timeout=10, hazard_id=rec["id"], kind=kind,
                params=rec["params"])
        self.active[rec["id"]] = rec
        self.history.append(rec)
        return rec

    async def stop(self, hazard_id: str) -> Dict[str, Any]:
        rec = self.active.get(hazard_id)
        if rec is None:
            raise HazardError(f"No active hazard '{hazard_id}'")
        if rec["where"] == "world":
            try:
                await self._request("hazard_stop", timeout=10, hazard_id=hazard_id)
            except RuntimeError:
                pass  # the daemon restarted: the hazard is gone anyway
        self._end(rec, "stopped")
        return rec

    async def clear(self) -> List[Dict[str, Any]]:
        stopped = []
        for hazard_id in list(self.active):
            stopped.append(await self.stop(hazard_id))
        return stopped

    def _end(self, rec: Dict[str, Any], status: str, at: Optional[float] = None) -> None:
        rec["status"] = status
        rec["ended_at"] = round(at if at is not None else self._clock(), 3)
        self.active.pop(rec["id"], None)

    def tick(self) -> None:
        """Expire hazards whose time is up (in-world ones expire in the
        daemon on their own; this keeps the records in step)."""
        now = self._clock()
        for rec in list(self.active.values()):
            if now >= rec["ends_at"]:
                self._end(rec, "expired", rec["ends_at"])

    # ---- effects on the gateway ------------------------------------------------

    def telemetry_paused(self) -> bool:
        return any(r["type"] == "telemetry_dropout" for r in self.active.values())

    def command_delay_s(self) -> float:
        delays = [float(r["params"].get("delay_ms") or 0) / 1000.0
                  for r in self.active.values() if r["type"] == "command_latency"]
        return max(delays, default=0.0)

    # ---- queries ---------------------------------------------------------------

    def overlapping(self, t0: float, t1: float) -> List[Dict[str, Any]]:
        """Hazards active at any time between t0 and t1, times relative to t0."""
        out = []
        for rec in self.history:
            end = rec["ended_at"] if rec["ended_at"] is not None else rec["ends_at"]
            if rec["started_at"] <= t1 and end >= t0:
                out.append({
                    "id": rec["id"], "type": rec["type"], "params": rec["params"],
                    "start_s": round(rec["started_at"] - t0, 2),
                    "end_s": round(min(end, t1) - t0, 2),
                    "status": rec["status"],
                })
        return out

    def summary(self) -> Dict[str, Any]:
        now = self._clock()
        return {"active": [
            {"id": r["id"], "type": r["type"],
             "remaining_s": round(max(0.0, r["ends_at"] - now), 1)}
            for r in self.active.values()
        ]}

    def listing(self) -> Dict[str, Any]:
        return {
            "types": {k: {"where": v["where"], "description": v["description"],
                          "defaults": v["defaults"]} for k, v in HAZARD_TYPES.items()},
            "active": list(self.active.values()),
            "recent": list(reversed(self.history))[:50],
        }
