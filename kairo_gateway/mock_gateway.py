"""Mock KAIRO gateway for tablet development without Apollo or Docker.

    pip install fastapi "uvicorn[standard]" pyyaml
    python -m kairo_gateway.mock_gateway            # http://0.0.0.0:8090

It serves the same endpoints as kairo_gateway.server, backed by a session
recorded from the real system (docs/validation_api_samples/, made with
kairo_gateway/tools/record_session.py):

  /ws, /api/state   replay the recorded drive in a loop at 10 Hz (car,
                    traffic, route, safety status)
  /api/map, /api/route, /api/safety/reports, /api/benchmarks
                    the recorded responses
  /api/hazards      in-memory: hazards start, expire and show up in the
                    state; a phantom obstacle appears ahead of the car
  /api/traffic      toggles the recorded traffic on and off
  /api/scenarios/run  simulates a batch, then serves the recorded benchmark
  trip, drive, body and places commands
                    accepted (body and places change the state; trips do
                    not change the replay)

Use it exactly like the real gateway: point the tablet at
http://<this-pc>:8090. Nothing here talks to Apollo.
"""

import asyncio
import copy
import gzip
import itertools
import json
import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import scenarios as scn
from .hazards import HAZARD_TYPES

SAMPLES = Path(os.getenv("KAIRO_MOCK_SAMPLES",
                         Path(__file__).resolve().parents[1] / "docs" / "validation_api_samples"))
RATE_HZ = 10.0


def _load(name: str, default: Any = None) -> Any:
    path = SAMPLES / name
    if not path.exists():
        return default
    if name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f) if name.endswith(".json.gz") else [json.loads(l) for l in f]
    return json.loads(path.read_text(encoding="utf-8"))


class Mock:
    def __init__(self) -> None:
        self.session: List[Dict[str, Any]] = _load("session.jsonl.gz", []) or [_load("state.json")]
        if not self.session or self.session[0] is None:
            raise SystemExit(f"No recorded session in {SAMPLES}")
        self.map = _load("map.json.gz", {"lanes": [], "bounds": {}})
        self.route = _load("route.json", {"rev": None, "route": []})
        self.reports = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                        for p in sorted((SAMPLES / "reports").glob("*.json"))}
        self.benchmark = _load("benchmark.json")
        self.index = 0
        self.body: Optional[Dict[str, Any]] = None
        self.places: Dict[str, Any] = copy.deepcopy(self.session[0].get("places") or {})
        self.traffic_on = True
        self.hazards: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)
        self.batch: Dict[str, Any] = {"running": False, "stop_requested": False,
                                      "progress": None, "error": None, "log": [],
                                      "last_summary": None}
        self.clients: set = set()

    # ---- state ------------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        s = copy.deepcopy(self.session[self.index % len(self.session)])
        s["ts"] = time.time()
        if self.body is not None:
            s["body"] = self.body
        s["places"] = self.places
        scene = s.setdefault("scene", {})
        obstacles = scene.get("obstacles") or []
        if not self.traffic_on:
            obstacles = [o for o in obstacles if not 10001 <= int(o.get("id", 0)) < 20000]
        now = time.time()
        for h in self.hazards.values():
            if h["type"] == "phantom_obstacle" and h.get("pose"):
                obstacles.append({"id": h["result"]["obstacle_id"], "type": "VEHICLE",
                                  **h["pose"], "length": 4.6, "width": 1.9, "speed": 0.0})
            if h["type"] == "perception_dropout":
                obstacles = []
        scene["obstacles"] = obstacles
        s["hazards"] = {"active": [{"id": h["id"], "type": h["type"],
                                    "remaining_s": round(max(0, h["ends_at"] - now), 1)}
                                   for h in self.hazards.values()]}
        traffic = s.get("traffic") or {}
        s["traffic"] = {**traffic, "on": self.traffic_on,
                        "vehicles": traffic.get("vehicles", 0) if self.traffic_on else 0}
        return s

    def tick(self) -> None:
        self.index += 1
        now = time.time()
        for h in list(self.hazards.values()):
            if now >= h["ends_at"]:
                h["status"], h["ended_at"] = "expired", h["ends_at"]
                del self.hazards[h["id"]]

    def paused(self) -> bool:
        return any(h["type"] == "telemetry_dropout" for h in self.hazards.values())

    def reply(self, result: Any = None) -> Dict[str, Any]:
        return {"ok": True, "result": result, "state": self.state()}

    # ---- hazards ------------------------------------------------------------

    def start_hazard(self, body: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(body)
        kind = params.pop("type", None)
        spec = HAZARD_TYPES.get(str(kind))
        if spec is None:
            raise HTTPException(422, f"Unknown hazard type '{kind}'")
        merged = {**spec["defaults"], **params}
        now = time.time()
        rec = {"id": f"hz-{next(self._ids)}", "type": kind, "where": spec["where"],
               "params": merged, "started_at": round(now, 3),
               "ends_at": round(now + float(merged.get("duration_s") or 10), 3),
               "ended_at": None, "status": "active", "result": None}
        if kind in ("phantom_obstacle", "cut_in"):
            pose = (self.state()["vehicle"] or {}).get("pose") or {"x": 0, "y": 0, "heading": 0}
            ahead = float(merged.get("ahead_m") or 25)
            x = pose["x"] + ahead * math.cos(pose["heading"])
            y = pose["y"] + ahead * math.sin(pose["heading"])
            oid = 20000 + next(self._ids) if kind == "phantom_obstacle" else 30000 + next(self._ids)
            rec["result"] = {"obstacle_id": oid, "x": round(x, 2), "y": round(y, 2),
                             "heading": pose["heading"]}
            if kind == "phantom_obstacle":
                rec["pose"] = {"x": x, "y": y, "heading": pose["heading"]}
        self.hazards[rec["id"]] = rec
        self.history.append(rec)
        return rec

    def public(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in rec.items() if k != "pose"}

    # ---- scenario batches ------------------------------------------------------

    async def run_batch(self, names: List[str], repeat: Optional[int]) -> None:
        bench = self.benchmark or {"batch_id": "mock", "scenarios": [], "runs": []}
        runs = [r for r in bench["runs"] if not names or r["scenario"] in names] or bench["runs"]
        total = len(runs)
        self.batch.update({"running": True, "stop_requested": False, "error": None, "log": [],
                           "progress": {"batch_id": time.strftime("%Y%m%d-%H%M%S"),
                                        "total_runs": total, "done_runs": 0, "current": None,
                                        "results": []}})
        for r in runs:
            if self.batch["stop_requested"]:
                break
            p = self.batch["progress"]
            p["current"] = {"scenario": r["scenario"], "run": r["run"]}
            self.batch["log"].append(f"{time.strftime('%H:%M:%S')} [{r['scenario']} #{r['run']}] driving")
            await asyncio.sleep(4.0)
            p["done_runs"] += 1
            p["results"].append({k: r.get(k) for k in ("scenario", "run", "trip_id", "verdict", "passed")})
            self.batch["log"].append(f"{time.strftime('%H:%M:%S')} [{r['scenario']} #{r['run']}] "
                                     f"{r.get('verdict')} -> {'pass' if r['passed'] else 'FAIL'}")
        self.batch["progress"]["current"] = None
        self.batch["last_summary"] = bench
        self.batch["running"] = False


mock: Mock


async def replay() -> None:
    last_sent = None
    while True:
        await asyncio.sleep(1.0 / RATE_HZ)
        mock.tick()
        if not mock.clients or mock.paused():
            continue
        body = json.dumps(mock.state(), separators=(",", ":"))
        if body == last_sent:
            continue
        last_sent = body
        for ws in list(mock.clients):
            try:
                await asyncio.wait_for(ws.send_text(body), 2.0)
            except Exception:  # noqa: BLE001
                mock.clients.discard(ws)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global mock
    mock = Mock()
    task = asyncio.create_task(replay())
    print(f"KAIRO mock gateway: {len(mock.session)} recorded states, "
          f"{len(mock.reports)} reports, samples from {SAMPLES}")
    yield
    task.cancel()


app = FastAPI(title="KAIRO Mock Gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=4096)


@app.get("/api/health")
def health():
    return {"ok": True, "mock": True, **mock.state()["gateway"]}


@app.get("/api/state")
def get_state():
    return mock.state()


@app.get("/api/route")
def get_route():
    return mock.route


@app.get("/api/map")
def get_map():
    return mock.map


@app.get("/api/snap")
def snap(x: float, y: float):
    return {"x": x, "y": y, "heading": 0.0, "lane_id": "mock", "distance": 0.0}


# Trip, Dreamview and drive commands: accepted, replay unchanged.
for path in ("/api/autopilot/go", "/api/autopilot/stop", "/api/autopilot/pull_over",
             "/api/autopilot/resume", "/api/autopilot/cancel",
             "/api/autopilot/lane_change/{direction}", "/api/dreamview/sim_control",
             "/api/dreamview/map", "/api/dreamview/mode", "/api/dreamview/modules/{name}",
             "/api/dreamview/setup", "/api/dreamview/reset_mode", "/api/dreamview/start_point",
             "/api/drive/manual", "/api/drive/gear", "/api/body/horn"):
    app.add_api_route(path, lambda: mock.reply(), methods=["POST"])


@app.post("/api/body")
def set_body(patch: Dict[str, Any]):
    mock.body = {**(mock.body or mock.state().get("body") or {}), **patch}
    return mock.reply(patch)


@app.put("/api/places/{place_id}")
def put_place(place_id: str, req: Dict[str, Any]):
    mock.places[place_id] = req
    return {"ok": True, "places": mock.places}


@app.delete("/api/places/{place_id}")
def delete_place(place_id: str):
    mock.places.pop(place_id, None)
    return {"ok": True, "places": mock.places}


@app.get("/api/traffic")
def traffic_status():
    recorded = _load("traffic.json", {}) or {}
    return {**recorded, "traffic": recorded.get("traffic") if mock.traffic_on else None}


@app.post("/api/traffic/start")
def traffic_start(_req: Dict[str, Any] = None):
    mock.traffic_on = True
    return mock.reply(traffic_status())


@app.post("/api/traffic/stop")
def traffic_stop():
    mock.traffic_on = False
    return mock.reply(traffic_status())


@app.get("/api/hazards")
def hazards_list():
    return {"types": {k: {"where": v["where"], "description": v["description"],
                          "defaults": v["defaults"]} for k, v in HAZARD_TYPES.items()},
            "active": [mock.public(h) for h in mock.hazards.values()],
            "recent": [mock.public(h) for h in reversed(mock.history[-50:])]}


@app.post("/api/hazards")
def hazard_start(body: Dict[str, Any]):
    return {"ok": True, "hazard": mock.public(mock.start_hazard(body))}


@app.delete("/api/hazards/{hazard_id}")
def hazard_stop(hazard_id: str):
    rec = mock.hazards.pop(hazard_id, None)
    if rec is None:
        raise HTTPException(404, f"No active hazard '{hazard_id}'")
    rec["status"], rec["ended_at"] = "stopped", round(time.time(), 3)
    return {"ok": True, "hazard": mock.public(rec)}


@app.post("/api/hazards/clear")
def hazards_clear():
    ids = list(mock.hazards)
    for hid in ids:
        hazard_stop(hid)
    return {"ok": True, "stopped": ids}


@app.get("/api/safety")
def safety_live():
    recorded = _load("safety.json", {}) or {}
    return {**mock.state().get("safety", {}), "rules": recorded.get("rules", [])}


@app.get("/api/safety/reports")
def safety_reports(limit: int = 50):
    keys = ("trip_id", "scenario", "run", "name", "map", "verdict", "end_reason",
            "started_at", "started_at_iso", "duration_s", "distance_m", "counts")
    rows = sorted(({k: r.get(k) for k in keys} for r in mock.reports.values()),
                  key=lambda r: r["started_at"], reverse=True)
    return {"reports": rows[:limit]}


@app.get("/api/safety/reports/{trip_id}")
def safety_report(trip_id: str):
    if trip_id not in mock.reports:
        raise HTTPException(404, f"No report '{trip_id}'")
    return mock.reports[trip_id]


@app.get("/api/scenarios")
def scenarios_list():
    return {"scenarios": scn.list_scenarios()}


@app.post("/api/scenarios/run")
async def scenarios_run(req: Dict[str, Any]):
    if mock.batch["running"]:
        raise HTTPException(409, "A scenario batch is already running")
    asyncio.create_task(mock.run_batch(req.get("names") or [], req.get("repeat")))
    await asyncio.sleep(0)
    return {"ok": True, **mock.batch}


@app.get("/api/scenarios/batch")
def scenarios_batch():
    return mock.batch


@app.post("/api/scenarios/stop")
def scenarios_stop():
    mock.batch["stop_requested"] = True
    return {"ok": True, **mock.batch}


@app.get("/api/benchmarks")
def benchmarks_list():
    return _load("benchmarks.json", {"benchmarks": []})


@app.get("/api/benchmarks/{batch_id}")
def benchmark_get(batch_id: str):
    if not mock.benchmark:
        raise HTTPException(404, f"No benchmark '{batch_id}'")
    return mock.benchmark


@app.websocket("/ws")
async def ws_state(ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_text(json.dumps(mock.state(), separators=(",", ":")))
        mock.clients.add(ws)
        while True:
            await ws.receive_text()  # manual drive inputs are ignored
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        mock.clients.discard(ws)


@app.get("/")
def root():
    return {"service": "KAIRO Mock Gateway", "samples": str(SAMPLES)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("KAIRO_GATEWAY_HOST", "0.0.0.0"),
                port=int(os.getenv("KAIRO_GATEWAY_PORT", "8090")))
