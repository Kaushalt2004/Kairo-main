# KAIRO validation API (traffic, hazards, safety, scenarios)

All endpoints are on the KAIRO gateway (`http://<host>:8090`). Use `127.0.0.1` on the
same machine; `localhost` adds a long name-resolution delay on Windows.

Real responses captured from the running system are in
[`docs/validation_api_samples/`](validation_api_samples/). Use them as fixtures for tests or a
mock mode. They are the contract: field names and types there are what the gateway sends.

## 1. Live state additions (`GET /api/state` and the `/ws` stream)

The state object streamed on `/ws` (10 per second while moving) has three new top-level keys:

```jsonc
"safety": {
  "active": true,                       // a trip is being validated
  "trip_id": "20261022-220001-town05-corner-clear-r1",
  "scenario": "town05_corner_clear",    // null for trips started from the tablet
  "elapsed_s": 12.4,
  "counts": {"critical": 0, "warning": 1},
  "ongoing": [{"rule": "R7", "name": "Time to collision", "severity": "critical"}],
  "last_violation": { /* same shape as report.violations[i], or null */ },
  "last_report": {                      // summary of the most recent finished trip
    "trip_id": "...", "scenario": "...", "run": 1, "name": "...", "map": "Carla Town05",
    "verdict": "PASS",                  // PASS | FAIL | INCOMPLETE
    "end_reason": "arrived",            // arrived | error | timeout | cancelled | takeover | offline | replaced
    "started_at": 1792686601.322, "started_at_iso": "2026-10-22T22:00:01",
    "duration_s": 71.17, "distance_m": 327.5,
    "counts": {"critical": 0, "warning": 0}
  }
},
"hazards": {"active": [{"id": "hz-3", "type": "phantom_obstacle", "remaining_s": 7.5}]},
"traffic": {"on": true, "vehicles": 8, "hazard_obstacles": 1, "dropout": false}   // null if Apollo offline
```

When `safety.active` is false, only `active` and `last_report` are present.

Simulated vehicles and hazard obstacles appear in the existing `scene.obstacles` list
(the map already draws it). Their ids tell them apart: `10001+` traffic, `20001+` phantom
obstacle, `30001+` cut-in vehicle.

## 2. Traffic

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/traffic` | | `{traffic: {count, radius, seed, speed_factor} or null, counts: {traffic: 8, phantom: 1}, dropout, vehicles: [{id, kind, x, y, speed}]}` |
| POST | `/api/traffic/start` | `{count: 1-40 = 8, radius_m: 20-500 = 150, seed?: int, speed_factor: 0.3-1.5 = 1.0}` | `{ok, result: <traffic status>, state}` |
| POST | `/api/traffic/stop` | | `{ok, result, state}` |

Returns 409 if Apollo's Prediction module is running (traffic publishes predictions itself).

## 3. Hazards

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/hazards` | | `{types: {<type>: {where, description, defaults}}, active: [Hazard], recent: [Hazard]}` |
| POST | `/api/hazards` | `{type, ...params}` (params override `defaults`) | `{ok, hazard: Hazard}`; 422 bad type/params, 409 Apollo refused (e.g. no neighbour lane for a cut-in) |
| DELETE | `/api/hazards/{id}` | | `{ok, hazard}` (404 if not active) |
| POST | `/api/hazards/clear` | | `{ok, stopped: [ids]}` |

Hazard types and parameters:

| type | where | parameters (defaults) | effect |
|---|---|---|---|
| `phantom_obstacle` | world | `ahead_m` 25, `duration_s` 10, `object` `vehicle`\|`debris` | static object on the car's route ahead |
| `cut_in` | world | `ahead_m` 25, `side` `auto`\|`left`\|`right`, `speed_factor` 0.6, `delay_s` 1, `change_s` 3, `duration_s` 15 | slower car in the neighbouring lane merges in front |
| `perception_dropout` | world | `duration_s` 2 | all obstacles vanish, then return |
| `telemetry_dropout` | gateway | `duration_s` 3 | `/ws` stops sending (the tablet should show a lost-link state) |
| `command_latency` | gateway | `delay_ms` 800, `duration_s` 30 | trip commands are delayed |

```jsonc
// Hazard
{"id": "hz-1", "type": "cut_in", "where": "world",
 "params": {"ahead_m": 28, "side": "auto", "speed_factor": 0.4, "delay_s": 1, "change_s": 2.5, "duration_s": 25},
 "started_at": 1792687000.1, "ends_at": 1792687025.1, "ended_at": null,
 "status": "active",                    // active | expired | stopped
 "result": {"obstacle_id": 30001, "x": -60.1, "y": 4.2, "heading": -3.139}}  // world hazards only
```

## 4. Safety reports

| Method | Path | Returns |
|---|---|---|
| GET | `/api/safety` | live block (as in the state) plus `rules: [Rule]` |
| GET | `/api/safety/reports?limit=50` | `{reports: [ReportSummary]}`, newest first |
| GET | `/api/safety/reports/{trip_id}` | full Report |

```jsonc
// Rule
{"id": "R7", "name": "Time to collision", "severity": "critical", "threshold": 1.5, "unit": "s",
 "min_duration_s": 0.3, "description": "Time to collision with an obstacle ahead below 1.5 s"}

// Report (abbreviated)
{"trip_id": "...", "scenario": "...", "run": 1, "name": "...", "map": "Carla Town05",
 "verdict": "PASS", "end_reason": "arrived",
 "started_at": 1792686601.3, "started_at_iso": "2026-10-22T22:00:01",
 "duration_s": 71.17, "distance_m": 327.5,
 "destination": {"x": -155.5, "y": -91.39, "heading": -0.0011, "name": "..."},
 "target_speed_kph": 30.0, "timeout_s": 180.0, "arrival_error_m": 3.76,
 "metrics": {"max_speed_kph": 29.0, "max_accel_mps2": 1.2, "max_decel_mps2": 0.74,
             "max_lat_accel_mps2": 0.88, "min_gap_m": null, "min_ttc_s": null,
             "max_obstacles": 0, "estop_count": 0},
 "counts": {"critical": 0, "warning": 0},
 "violations": [{"rule": "R2", "name": "Harsh braking", "severity": "warning", "t_s": 34.19,
                 "duration_s": 0.0, "value": 4.09, "threshold": 4.0, "x": -182.6, "y": -0.9,
                 "note": "optional"}],
 "hazards": [{"id": "hz-1", "type": "phantom_obstacle", "params": {...},
              "start_s": 8.23, "end_s": 20.23, "status": "expired"}],   // times relative to trip start
 "anomalies": [{"type": "position_jump", "t_s": 60.3, "distance_m": 40.1,
                "from": [x, y], "to": [x, y]}],                       // simulator moved the car
 "timeline": [[t_s, speed_kph, x, y], ...],                            // 1 per second, for charts
 "samples": 659, "rules_version": "1.0"}
```

Rules: R1 over-speed, R2 harsh braking, R3 emergency braking, R4 harsh acceleration,
R5 lateral acceleration, R6 obstacle proximity, R7 time to collision, R8 planner e-stop,
R9 stall, R10 route completion, R11 collision. `min_gap_m` is null when no stopped or
same-direction obstacle was ever in the car's path, and `min_ttc_s` is null when no obstacle was ever on
a collision course. `anomalies` lists simulator artefacts (Dreamview's Sim Control sometimes
jumps the car along its route); show them, but they are not safety violations.

## 5. Scenarios and benchmarks

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/scenarios` | | `{scenarios: [{id, name, description, repeat, traffic: bool, hazards: [types], actions: [names]}]}` |
| POST | `/api/scenarios/run` | `{names: [ids] (empty = all), repeat?: 1-50}` | batch status; 409 if one is running |
| GET | `/api/scenarios/batch` | | `{running, stop_requested, progress: {batch_id, total_runs, done_runs, current: {scenario, run} or null, results: [{scenario, run, trip_id, verdict, passed}]}, error, log: [lines], last_summary: Benchmark or null}` |
| POST | `/api/scenarios/stop` | | batch status (the current run is cancelled) |
| GET | `/api/benchmarks` | | `{benchmarks: [{batch_id, finished_at, stopped, scenarios: [{scenario, runs, passed, pass_rate}]}]}` |
| GET | `/api/benchmarks/{batch_id}` | | Benchmark |

```jsonc
// Benchmark
{"batch_id": "20261022-221600", "finished_at": "2026-10-22T22:45:10", "stopped": false,
 "scenarios": [{"scenario": "town05_corner_phantom", "runs": 3, "passed": 3, "pass_rate": 1.0,
                "verdicts": {"PASS": 3}, "mean_trip_s": 75.1, "sd_trip_s": 0.4,
                "distance_km": 0.983, "violations": 0, "violations_per_km": 0.0, "by_rule": {}}],
 "runs": [{"scenario": "...", "run": 1, "trip_id": "...", "verdict": "PASS", "end_reason": "arrived",
           "passed": true, "failures": [], "duration_s": 75.31, "distance_m": 327.9,
           "violations": [], "counts": {...}, "metrics": {...},
           "events": [{"t_s": 8.2, "hazard": "phantom_obstacle", "id": "hz-1"}]}]}
```

A batch drives the car: while `running` is true, the tablet should not send trip commands.

## 6. Scenario files

YAML files in `kairo_gateway/scenarios/`. See the docstring of `kairo_gateway/scenarios.py`
for the format. From the command line:

```
python -m kairo_gateway.scenarios --list
python -m kairo_gateway.scenarios town05_corner_phantom --repeat 3
```
