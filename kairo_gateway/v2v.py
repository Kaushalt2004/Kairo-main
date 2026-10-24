"""Simulated vehicle-to-vehicle (V2V) hazard messages.

Simulated road users broadcast hazard messages, loosely modelled on the
basic safety / cooperative awareness messages:

  STALLED_VEHICLE  phantom obstacles (ids 20001+)
  STOPPED_VEHICLE  simulated traffic standing still (ids 10001+)
  HARD_BRAKING     simulated traffic decelerating harder than 3 m/s²
  CUT_IN           the cut-in vehicle (ids 30001+)

Each sender broadcasts twice a second. The channel drops every message
independently with probability loss_p, delays the rest by latency_ms
(± 20 % jitter) and discards senders beyond range_m. The ego receiver
keeps hazards ahead of the car (within 8 m of its axis) and raises one
alert per sender with the distance and the time to reach it.
"""

import math
import random
import time
from typing import Any, Callable, Dict, List, Optional

BROADCAST_PERIOD_S = 0.5
TTL_S = 2.0
AHEAD_LATERAL_M = 8.0
HARD_BRAKE_MPS2 = 3.0


def classify(obstacle: Dict[str, Any], prev_speed: Optional[float], dt: float) -> Optional[str]:
    oid = int(obstacle.get("id") or 0)
    speed = float(obstacle.get("speed") or 0)
    if 20001 <= oid < 30000:
        return "STALLED_VEHICLE"
    if 30001 <= oid < 40000:
        return "CUT_IN"
    if 10001 <= oid < 20000:
        if prev_speed is not None and dt > 0 and (prev_speed - speed) / dt > HARD_BRAKE_MPS2:
            return "HARD_BRAKING"
        if speed < 0.5:
            return "STOPPED_VEHICLE"
    return None


class V2VChannel:
    def __init__(self, clock: Callable[[], float] = time.time, seed: Optional[int] = None):
        self.clock = clock
        self.rng = random.Random(seed)
        self.config = {"enabled": True, "loss_p": 0.0, "latency_ms": 100.0, "range_m": 300.0}
        self.in_flight: List[Dict[str, Any]] = []
        self.alerts: Dict[int, Dict[str, Any]] = {}
        self.stats = {"sent": 0, "dropped": 0, "out_of_range": 0, "delivered": 0}
        self._last_broadcast: Dict[int, float] = {}
        self._speeds: Dict[int, tuple] = {}

    def configure(self, **cfg: Any) -> Dict[str, Any]:
        for k, v in cfg.items():
            if v is None or k not in self.config:
                continue
            self.config[k] = bool(v) if k == "enabled" else float(v)
        if not 0 <= self.config["loss_p"] <= 1:
            raise ValueError("loss_p must be between 0 and 1")
        self.reset()
        return dict(self.config)

    def reset(self) -> None:
        self.in_flight.clear()
        self.alerts.clear()
        self.stats = {k: 0 for k in self.stats}

    def step(self, pose: Optional[Dict[str, float]], speed: float,
             obstacles: List[Dict[str, Any]]) -> None:
        """Broadcast from every sender that is due, deliver what has arrived."""
        now = self.clock()
        if not self.config["enabled"]:
            return
        for o in obstacles:
            oid = int(o.get("id") or 0)
            prev = self._speeds.get(oid)
            dt = now - prev[1] if prev else 0.0
            kind = classify(o, prev[0] if prev else None, dt)
            self._speeds[oid] = (float(o.get("speed") or 0), now)
            if kind is None or now - self._last_broadcast.get(oid, float("-inf")) < BROADCAST_PERIOD_S:
                continue
            self._last_broadcast[oid] = now
            self.stats["sent"] += 1
            msg = {"sender_id": oid, "type": kind, "x": o["x"], "y": o["y"],
                   "heading": o.get("heading"), "speed": o.get("speed"), "sent_at": now,
                   "ttl_s": TTL_S}
            if pose and math.hypot(o["x"] - pose["x"], o["y"] - pose["y"]) > self.config["range_m"]:
                self.stats["out_of_range"] += 1
                continue
            if self.rng.random() < self.config["loss_p"]:
                self.stats["dropped"] += 1
                continue
            latency = self.config["latency_ms"] / 1000.0 * self.rng.uniform(0.8, 1.2)
            msg["deliver_at"] = now + latency
            self.in_flight.append(msg)

        arrived = [m for m in self.in_flight if m["deliver_at"] <= now]
        self.in_flight = [m for m in self.in_flight if m["deliver_at"] > now]
        for m in arrived:
            self.stats["delivered"] += 1
            self._receive(m, pose, speed, now)
        for sid in [s for s, a in self.alerts.items() if now - a["received_at"] > TTL_S]:
            del self.alerts[sid]

    def _receive(self, m: Dict[str, Any], pose: Optional[Dict[str, float]], speed: float,
                 now: float) -> None:
        if not pose:
            return
        h = pose["heading"]
        dx, dy = m["x"] - pose["x"], m["y"] - pose["y"]
        fwd = dx * math.cos(h) + dy * math.sin(h)
        lat = -dx * math.sin(h) + dy * math.cos(h)
        if fwd <= 0 or abs(lat) > AHEAD_LATERAL_M:
            self.alerts.pop(m["sender_id"], None)
            return
        prev = self.alerts.get(m["sender_id"])
        self.alerts[m["sender_id"]] = {
            "sender_id": m["sender_id"], "type": m["type"],
            "distance_m": round(fwd, 1), "lateral_m": round(lat, 1),
            "time_to_reach_s": round(fwd / speed, 1) if speed > 0.5 else None,
            "latency_ms": round((now - m["sent_at"]) * 1000),
            "first_received_at": prev["first_received_at"] if prev else round(now, 2),
            "received_at": now,
        }

    def summary(self) -> Dict[str, Any]:
        alerts = sorted(self.alerts.values(), key=lambda a: a["distance_m"])
        return {"enabled": self.config["enabled"], "config": dict(self.config),
                "alerts": [{k: v for k, v in a.items() if k != "received_at"} for a in alerts],
                "stats": dict(self.stats)}
