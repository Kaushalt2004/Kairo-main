"""Scenario runner and benchmark.

A scenario is a small YAML file (kairo_gateway/scenarios/*.yaml):

    name: corner_with_obstacle
    description: Two-corner route with a stalled car ahead
    start: map_start            # or {x, y, heading}
    destination: {x: -155.5, y: -91.7}
    cruise_kph: 30
    timeout_s: 180
    traffic: {count: 8, radius_m: 150, seed: 1}     # optional
    hazards:                                        # optional, timed from the go
      - {at_s: 8, type: phantom_obstacle, ahead_m: 35, duration_s: 10}
    actions:                                        # optional operator actions
      - {at_s: 30, do: stop}
      - {at_s: 35, do: resume}
    expect:                                         # optional (default verdict PASS)
      verdict: PASS
      max_decel_mps2: 6.0       # metric <= value  (names from the report's metrics)
      min_gap_m: 2.0            # metric >= value
      max_duration_s: 150       # trip duration <= value
      forbid: [R6, R11]         # rules that must not be violated
    repeat: 3

Each run drives the scenario through the gateway's public HTTP API, exactly
as the tablet would, and checks the safety report against `expect`. A batch
writes data/benchmarks/<batch_id>.json and .md with pass rates, trip times
and violations per kilometre.

    python -m kairo_gateway.scenarios --list
    python -m kairo_gateway.scenarios town05_corner_clear town05_corner_phantom --repeat 3
"""

import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from .hazards import HAZARD_TYPES

SCENARIO_DIR = Path(__file__).with_name("scenarios")
BENCHMARK_DIR = Path(__file__).with_name("data") / "benchmarks"
ACTIONS = {
    "stop": "/api/autopilot/stop", "resume": "/api/autopilot/resume",
    "pull_over": "/api/autopilot/pull_over", "cancel": "/api/autopilot/cancel",
    "lane_change_left": "/api/autopilot/lane_change/left",
    "lane_change_right": "/api/autopilot/lane_change/right",
}


class ScenarioError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Scenario files
# ---------------------------------------------------------------------------

def _point(value: Any, what: str) -> Optional[Dict[str, float]]:
    if value in (None, "map_start"):
        return None
    if not isinstance(value, dict) or "x" not in value or "y" not in value:
        raise ScenarioError(f"{what} must be map_start or {{x, y[, heading]}}")
    out = {"x": float(value["x"]), "y": float(value["y"])}
    if value.get("heading") is not None:
        out["heading"] = float(value["heading"])
    return out


def validate(raw: Dict[str, Any], source: str = "scenario") -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScenarioError(f"{source}: not a mapping")
    if "destination" not in raw:
        raise ScenarioError(f"{source}: destination is required")
    sc = {
        "name": str(raw.get("name") or Path(source).stem),
        "description": raw.get("description") or "",
        "map": raw.get("map"),
        "start": _point(raw.get("start", "map_start"), "start"),
        "destination": _point(raw["destination"], "destination"),
        "cruise_kph": float(raw.get("cruise_kph", 30)),
        "timeout_s": float(raw.get("timeout_s", 180)),
        "traffic": raw.get("traffic"),
        "hazards": [],
        "actions": [],
        "expect": raw.get("expect") or {"verdict": "PASS"},
        "repeat": int(raw.get("repeat", 1)),
    }
    if sc["destination"] is None:
        raise ScenarioError(f"{source}: destination must be a point")
    for h in raw.get("hazards") or []:
        if h.get("type") not in HAZARD_TYPES:
            raise ScenarioError(f"{source}: unknown hazard type {h.get('type')!r}")
        sc["hazards"].append({"at_s": float(h.get("at_s", 0)), "type": h["type"],
                              "params": {k: v for k, v in h.items() if k not in ("at_s", "type")}})
    for a in raw.get("actions") or []:
        if a.get("do") not in ACTIONS:
            raise ScenarioError(f"{source}: unknown action {a.get('do')!r}; "
                                f"use one of {', '.join(ACTIONS)}")
        sc["actions"].append({"at_s": float(a.get("at_s", 0)), "do": a["do"]})
    if sc["traffic"] is not None and not isinstance(sc["traffic"], dict):
        raise ScenarioError(f"{source}: traffic must be a mapping")
    if not 1 <= sc["repeat"] <= 50:
        raise ScenarioError(f"{source}: repeat must be 1-50")
    return sc


def load(path: Path) -> Dict[str, Any]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioError(f"{path.name}: {e}") from e
    sc = validate(raw, path.name)
    sc["file"] = path.name
    return sc


def find(name: str, directory: Path = SCENARIO_DIR) -> Dict[str, Any]:
    path = Path(name)
    if not path.suffix:
        path = directory / f"{name}.yaml"
    elif not path.is_absolute() and not path.exists():
        path = directory / name
    if not path.exists():
        raise ScenarioError(f"No scenario '{name}' in {directory}")
    return load(path)


def list_scenarios(directory: Path = SCENARIO_DIR) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            sc = load(path)
            out.append({"id": path.stem, "name": sc["name"], "description": sc["description"],
                        "repeat": sc["repeat"], "traffic": bool(sc["traffic"]),
                        "hazards": [h["type"] for h in sc["hazards"]],
                        "actions": [a["do"] for a in sc["actions"]]})
        except ScenarioError as e:
            out.append({"id": path.stem, "error": str(e)})
    return out


# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------

def evaluate(expect: Dict[str, Any], report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    failures: List[str] = []
    metrics = report.get("metrics") or {}
    for key, want in expect.items():
        if key == "verdict":
            if report.get("verdict") != want:
                failures.append(f"verdict {report.get('verdict')} != {want}")
        elif key == "forbid":
            hit = sorted({v["rule"] for v in report.get("violations") or []} & set(want or []))
            if hit:
                failures.append(f"forbidden rules violated: {', '.join(hit)}")
        elif key == "max_duration_s":
            if (report.get("duration_s") or 0) > float(want):
                failures.append(f"duration {report.get('duration_s')} s > {want} s")
        elif key in metrics:
            value = metrics[key]
            if value is None:
                continue  # e.g. no obstacle ever in the path
            if key.startswith("min_") and value < float(want):
                failures.append(f"{key} {value} < {want}")
            elif not key.startswith("min_") and value > float(want):
                failures.append(f"{key} {value} > {want}")
        else:
            failures.append(f"unknown expectation '{key}'")
    return not failures, failures


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

class GatewayClient:
    def __init__(self, base: str = "http://127.0.0.1:8090", timeout: float = 30.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        data = None if method == "GET" else json.dumps(body or {}).encode()
        req = urllib.request.Request(self.base + path, method=method, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail")
            except ValueError:
                detail = str(e)
            raise ScenarioError(f"{method} {path}: {detail}") from e
        except urllib.error.URLError as e:
            raise ScenarioError(f"Gateway not reachable at {self.base}: {e.reason}") from e

    def get(self, path: str) -> Any:
        return self.call("GET", path)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return self.call("POST", path, body)


class ScenarioRunner:
    POLL_S = 0.2

    def __init__(self, client: GatewayClient, log: Callable[[str], None] = print,
                 should_stop: Callable[[], bool] = lambda: False,
                 out_dir: Path = BENCHMARK_DIR):
        self.client = client
        self.log = log
        self.should_stop = should_stop
        self.out_dir = Path(out_dir)
        self.progress: Dict[str, Any] = {}

    def _wait_pose(self, near: Optional[Dict[str, float]], timeout: float = 20.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            s = self.client.get("/api/state")
            pose = s["vehicle"]["pose"]
            if pose and s["vehicle"]["speed_kph"] < 0.5 and (
                    near is None or math.hypot(pose["x"] - near["x"], pose["y"] - near["y"]) < 3.0):
                return
            time.sleep(0.5)
        raise ScenarioError("The car did not settle at the start point")

    def _reset(self, sc: Dict[str, Any], run: int) -> None:
        c = self.client
        c.post("/api/autopilot/cancel")
        c.post("/api/hazards/clear")
        c.post("/api/traffic/stop")
        start = sc["start"]
        moved = c.post("/api/dreamview/start_point", start or {})
        time.sleep(2.5)
        result = moved.get("result") or {}
        target = {"x": result["x"], "y": result["y"]} if result.get("x") is not None else None
        self._wait_pose(target)
        if sc["traffic"]:
            t = dict(sc["traffic"])
            if t.get("seed") is not None:
                t["seed"] = int(t["seed"]) + run
            c.post("/api/traffic/start", t)
            time.sleep(1.0)

    def run_once(self, sc: Dict[str, Any], run: int) -> Dict[str, Any]:
        c = self.client
        self.log(f"[{sc['name']} #{run}] reset")
        self._reset(sc, run)
        dest = sc["destination"]
        go = c.post("/api/autopilot/go", {
            "x": dest["x"], "y": dest["y"], "name": sc["name"],
            "target_speed_kph": sc["cruise_kph"], "scenario": sc["name"], "run": run,
            "timeout_s": sc["timeout_s"]})
        trip_id = go["state"]["safety"].get("trip_id")
        t0 = time.time()
        self.log(f"[{sc['name']} #{run}] driving (trip {trip_id})")
        pending = sorted([("hazard", h["at_s"], h) for h in sc["hazards"]] +
                         [("action", a["at_s"], a) for a in sc["actions"]], key=lambda e: e[1])
        events: List[Dict[str, Any]] = []
        report = None
        while True:
            elapsed = time.time() - t0
            while pending and pending[0][1] <= elapsed:
                kind, _, item = pending.pop(0)
                try:
                    if kind == "hazard":
                        rec = c.post("/api/hazards", {"type": item["type"], **item["params"]})
                        events.append({"t_s": round(elapsed, 1), "hazard": item["type"],
                                       "id": rec["hazard"]["id"]})
                    else:
                        c.post(ACTIONS[item["do"]])
                        events.append({"t_s": round(elapsed, 1), "action": item["do"]})
                except ScenarioError as e:
                    events.append({"t_s": round(elapsed, 1), "error": str(e)})
                    self.log(f"[{sc['name']} #{run}] {e}")
            live = c.get("/api/safety")
            last = live.get("last_report") or {}
            if not live.get("active") or live.get("trip_id") != trip_id:
                if last.get("trip_id") == trip_id:
                    report = c.get(f"/api/safety/reports/{trip_id}")
                break
            if self.should_stop() or elapsed > sc["timeout_s"] + 30:
                c.post("/api/autopilot/cancel")
            time.sleep(self.POLL_S)
        c.post("/api/hazards/clear")
        if sc["traffic"]:
            c.post("/api/traffic/stop")
        if report is None:
            return {"scenario": sc["name"], "run": run, "trip_id": trip_id,
                    "passed": False, "failures": ["trip ended without a report"],
                    "events": events}
        passed, failures = evaluate(sc["expect"], report)
        result = {
            "scenario": sc["name"], "run": run, "trip_id": trip_id,
            "verdict": report["verdict"], "end_reason": report["end_reason"],
            "passed": passed, "failures": failures,
            "duration_s": report["duration_s"], "distance_m": report["distance_m"],
            "violations": [v["rule"] for v in report["violations"]],
            "counts": report["counts"], "metrics": report["metrics"], "events": events,
        }
        self.log(f"[{sc['name']} #{run}] {report['verdict']} ({report['end_reason']}, "
                 f"{report['duration_s']} s) -> {'pass' if passed else 'FAIL: ' + '; '.join(failures)}")
        return result

    def run_batch(self, scenarios: List[Dict[str, Any]], repeat: Optional[int] = None) -> Dict[str, Any]:
        batch_id = time.strftime("%Y%m%d-%H%M%S")
        total = sum(repeat or sc["repeat"] for sc in scenarios)
        self.progress = {"batch_id": batch_id, "total_runs": total, "done_runs": 0,
                         "current": None, "results": []}
        results: List[Dict[str, Any]] = []
        for sc in scenarios:
            for run in range(1, (repeat or sc["repeat"]) + 1):
                if self.should_stop():
                    break
                self.progress["current"] = {"scenario": sc["name"], "run": run}
                try:
                    res = self.run_once(sc, run)
                except ScenarioError as e:
                    self.log(f"[{sc['name']} #{run}] error: {e}")
                    res = {"scenario": sc["name"], "run": run, "passed": False,
                           "failures": [str(e)], "error": str(e)}
                results.append(res)
                self.progress["done_runs"] += 1
                self.progress["results"].append(
                    {k: res.get(k) for k in ("scenario", "run", "trip_id", "verdict", "passed")})
        self.progress["current"] = None
        summary = summarize(batch_id, scenarios, results, stopped=self.should_stop())
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"{batch_id}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        (self.out_dir / f"{batch_id}.md").write_text(markdown(summary), encoding="utf-8")
        return summary


def summarize(batch_id: str, scenarios: List[Dict[str, Any]], results: List[Dict[str, Any]],
              stopped: bool = False) -> Dict[str, Any]:
    rows = []
    for sc in scenarios:
        rs = [r for r in results if r["scenario"] == sc["name"]]
        if not rs:
            continue
        arrived = [r["duration_s"] for r in rs if r.get("end_reason") == "arrived"]
        km = sum(r.get("distance_m") or 0 for r in rs) / 1000
        n_viol = sum(len(r.get("violations") or []) for r in rs)
        by_rule: Dict[str, int] = {}
        for r in rs:
            for rule in r.get("violations") or []:
                by_rule[rule] = by_rule.get(rule, 0) + 1
        verdicts: Dict[str, int] = {}
        for r in rs:
            verdicts[r.get("verdict") or "ERROR"] = verdicts.get(r.get("verdict") or "ERROR", 0) + 1
        rows.append({
            "scenario": sc["name"], "runs": len(rs),
            "passed": sum(1 for r in rs if r["passed"]),
            "pass_rate": round(sum(1 for r in rs if r["passed"]) / len(rs), 3),
            "verdicts": verdicts,
            "mean_trip_s": round(statistics.mean(arrived), 1) if arrived else None,
            "sd_trip_s": round(statistics.stdev(arrived), 1) if len(arrived) > 1 else None,
            "distance_km": round(km, 3),
            "violations": n_viol,
            "violations_per_km": round(n_viol / km, 2) if km > 0 else None,
            "by_rule": by_rule,
        })
    return {"batch_id": batch_id, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stopped": stopped, "scenarios": rows, "runs": results}


def markdown(summary: Dict[str, Any]) -> str:
    lines = [f"# Benchmark {summary['batch_id']}", "",
             "| Scenario | Runs | Pass rate | Mean trip time | Violations per km | Rules |",
             "|---|---|---|---|---|---|"]
    for r in summary["scenarios"]:
        mean = f"{r['mean_trip_s']} s" + (f" ± {r['sd_trip_s']}" if r["sd_trip_s"] else "") \
            if r["mean_trip_s"] is not None else "-"
        vpk = r["violations_per_km"] if r["violations_per_km"] is not None else "-"
        rules = ", ".join(f"{k}×{v}" for k, v in sorted(r["by_rule"].items())) or "none"
        lines.append(f"| {r['scenario']} | {r['runs']} | {r['passed']}/{r['runs']} "
                     f"({r['pass_rate'] * 100:.0f} %) | {mean} | {vpk} | {rules} |")
    lines += ["", "| Scenario | Run | Trip | Verdict | Duration | Result |", "|---|---|---|---|---|---|"]
    for r in summary["runs"]:
        lines.append(f"| {r['scenario']} | {r['run']} | {r.get('trip_id') or '-'} | "
                     f"{r.get('verdict') or '-'} | {r.get('duration_s') or '-'} s | "
                     f"{'pass' if r['passed'] else 'FAIL: ' + '; '.join(r['failures'])} |")
    return "\n".join(lines) + "\n"


def list_benchmarks(directory: Path = BENCHMARK_DIR) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
            out.append({"batch_id": s["batch_id"], "finished_at": s["finished_at"],
                        "stopped": s.get("stopped"), "scenarios": [
                            {k: r[k] for k in ("scenario", "runs", "passed", "pass_rate")}
                            for r in s["scenarios"]]})
        except (OSError, ValueError, KeyError):
            continue
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run KAIRO scenarios through the gateway")
    ap.add_argument("scenarios", nargs="*", help="scenario names or YAML paths (default: all)")
    ap.add_argument("--repeat", type=int, help="override each scenario's repeat count")
    ap.add_argument("--gateway", default="http://127.0.0.1:8090")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = ap.parse_args(argv)
    if args.list:
        for s in list_scenarios():
            print(f"{s['id']:32} {s.get('error') or s['description']}")
        return 0
    names = args.scenarios or [p.stem for p in sorted(SCENARIO_DIR.glob("*.yaml"))]
    try:
        scenarios = [find(n) for n in names]
    except ScenarioError as e:
        print(e, file=sys.stderr)
        return 2
    summary = ScenarioRunner(GatewayClient(args.gateway)).run_batch(scenarios, args.repeat)
    print()
    print(markdown(summary))
    print(f"Saved to {BENCHMARK_DIR / summary['batch_id']}.json / .md")
    return 0 if all(r["passed"] for r in summary["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
