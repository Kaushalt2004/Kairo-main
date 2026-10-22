"""Safety validator, hazard manager and scenario runner logic.

No Apollo needed: trips are fed synthetic gateway states.
"""

import asyncio
import math
import json
from pathlib import Path

import pytest

from kairo_gateway import scenarios as scn
from kairo_gateway.hazards import HazardError, HazardManager
from kairo_gateway.safety import SafetyValidator, boxes_overlap, obstacle_relations


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def state(t, kph, x, y=0.0, heading=0.0, ap="DRIVING", dest=(500.0, 0.0),
          obstacles=(), mode="AUTO", decision="cruise"):
    return {
        "ts": t,
        "vehicle": {"speed_kph": kph, "pose": {"x": x, "y": y, "heading": heading}},
        "autopilot": {"state": ap, "decision": decision,
                      "destination": None if dest is None else {"x": dest[0], "y": dest[1]}},
        "drive": {"mode": mode},
        "scene": {"obstacles": list(obstacles)},
    }


@pytest.fixture
def validator(tmp_path):
    clock = Clock()
    v = SafetyValidator(tmp_path / "reports", clock=clock)
    v.clock = clock
    return v


def drive(v, samples):
    """Feed (dt, kph, x, kwargs) samples at 10 Hz; return the final report."""
    report = None
    for t, kph, x, kw in samples:
        v.clock.t = t
        report = v.sample(state(t, kph, x, **kw)) or report
    return report


def cruise(t0, t1, kph, x0, **kw):
    out, t, x = [], t0, x0
    while t < t1:
        out.append((t, kph, x, kw))
        t = round(t + 0.1, 2)
        x += kph / 3.6 * 0.1
    return out, x


def test_clean_trip_passes_and_writes_report(validator, tmp_path):
    trip_id = validator.start_trip(destination={"x": 500, "y": 0}, target_speed_kph=30,
                                   scenario="unit test", timeout_s=120)
    samples, x = cruise(1000.1, 1010, 28, 0.0)
    t, kph = 1010.0, 28.0
    while kph > 0:          # gentle stop, about 2 m/s^2
        t = round(t + 0.1, 2)
        kph = max(0.0, kph - 0.72)
        x += kph / 3.6 * 0.1
        samples.append((t, kph, x, {}))
    samples.append((t + 0.1, 0, x, {"ap": "ARRIVED"}))
    report = drive(validator, samples)
    assert report["verdict"] == "PASS" and report["end_reason"] == "arrived"
    assert report["violations"] == []
    assert report["distance_m"] == pytest.approx(92, abs=3)
    saved = json.loads((tmp_path / "reports" / f"{trip_id}.json").read_text())
    assert saved["trip_id"] == trip_id
    assert validator.list_reports()[0]["trip_id"] == trip_id
    assert not validator.active


def test_hard_braking_is_one_episode_with_peak(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, target_speed_kph=60)
    samples, x = cruise(1000.1, 1005, 50, 0.0)
    kph = 50.0
    t = 1005.0
    while kph > 0:      # 7 m/s^2 for about 2 s
        t = round(t + 0.1, 2)
        kph = max(0.0, kph - 7 * 3.6 * 0.1)
        x += kph / 3.6 * 0.1
        samples.append((t, kph, x, {}))
    samples.append((t + 0.1, 0, x, {"ap": "ARRIVED"}))
    report = drive(validator, samples)
    rules = [v["rule"] for v in report["violations"]]
    assert rules.count("R2") == 1 and rules.count("R3") == 1
    r3 = next(v for v in report["violations"] if v["rule"] == "R3")
    assert r3["value"] == pytest.approx(7.0, abs=0.3)
    assert r3["severity"] == "critical"
    assert report["verdict"] == "FAIL"


def test_short_over_speed_spike_is_ignored(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, target_speed_kph=30)
    samples, x = cruise(1000.1, 1003, 30, 0.0)
    spike, x = cruise(1003.0, 1003.5, 36, x)      # 0.5 s above +10 %: under 1 s
    rest, x = cruise(1003.5, 1006, 30, x)
    long_spike, x = cruise(1006.0, 1008, 36, x)   # 2 s: counts
    report = drive(validator, samples + spike + rest + long_spike +
                   [(1008.1, 0, x, {"ap": "ARRIVED"})])
    r1 = [v for v in report["violations"] if v["rule"] == "R1"]
    assert len(r1) == 1 and r1[0]["t_s"] == pytest.approx(6.0, abs=0.2)


def test_obstacle_gap_ttc_and_collision():
    pose = {"x": 0.0, "y": 0.0, "heading": 0.0}
    # Car centre is 1.45 m ahead of the pose; obstacle 12 m ahead of that.
    rel = obstacle_relations(pose, 10.0, [{"id": 7, "x": 13.45, "y": 0.0, "heading": 0.0,
                                           "length": 4.0, "width": 2.0, "speed": 0.0}])
    assert rel["gap"] == pytest.approx(12 - 4.93 / 2 - 2.0, abs=0.01)
    assert rel["ttc"] == pytest.approx(rel["gap"] / 10.0, abs=0.01)
    assert rel["collision"] is None
    beside = obstacle_relations(pose, 10.0, [{"id": 8, "x": 1.45, "y": 3.5, "length": 4.6,
                                              "width": 1.9, "speed": 10.0}])
    assert beside["gap"] is None and beside["collision"] is None
    # Oncoming car in the next lane: passes 3.5 m away, no time to collision.
    oncoming = obstacle_relations(pose, 8.0, [{"id": 3, "x": 30.0, "y": 3.5, "heading": math.pi,
                                               "length": 4.6, "width": 1.9, "speed": 8.0}])
    assert oncoming["ttc"] is None
    # Oncoming car in the same lane, both at 8 m/s, 30 m apart.
    head_on = obstacle_relations(pose, 8.0, [{"id": 4, "x": 31.45, "y": 0.0, "heading": math.pi,
                                              "length": 4.6, "width": 1.9, "speed": 8.0}])
    assert head_on["ttc"] == pytest.approx((30 - (4.93 + 4.6) / 2) / 16, abs=0.01)
    assert head_on["gap"] is None          # gap is for traffic going the car's way
    # Car crossing from the right that will pass through the car's position.
    crossing = obstacle_relations(pose, 0.0, [{"id": 6, "x": 1.45, "y": -20.0,
                                               "heading": math.pi / 2, "length": 4.6,
                                               "width": 1.9, "speed": 10.0}])
    assert crossing["ttc"] == pytest.approx((20 - (4.93 + 4.6) / 2) / 10, abs=0.01)
    hit = obstacle_relations(pose, 2.0, [{"id": 9, "x": 3.0, "y": 0.5, "length": 4.6,
                                          "width": 1.9}])
    assert hit["collision"] == 9


def test_boxes_overlap():
    a = [(0, 0), (2, 0), (2, 1), (0, 1)]
    assert boxes_overlap(a, [(1, 0.5), (3, 0.5), (3, 2), (1, 2)])
    assert not boxes_overlap(a, [(2.5, 0), (4, 0), (4, 1), (2.5, 1)])


def test_proximity_rules_fire_near_an_obstacle(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, target_speed_kph=30)
    obstacle = {"id": 1, "x": 30.0, "y": 0.0, "heading": 0.0, "length": 4.6,
                "width": 1.9, "speed": 0.0}
    samples, x = [], 0.0
    t = 1000.1
    while x < 27.0:          # 10 m/s straight into a stopped car
        samples.append((t, 36, x, {"obstacles": [obstacle]}))
        t = round(t + 0.1, 2)
        x += 1.0
    samples.append((t, 0, x, {"obstacles": [obstacle], "ap": "ARRIVED"}))
    report = drive(validator, samples)
    rules = {v["rule"] for v in report["violations"]}
    assert {"R6", "R7", "R11"} <= rules
    assert report["metrics"]["min_gap_m"] == 0.0


def test_end_reasons(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, timeout_s=5)
    samples, x = cruise(1000.1, 1006, 20, 0.0)
    report = drive(validator, samples)
    assert report["end_reason"] == "timeout" and report["verdict"] == "FAIL"
    assert any(v["rule"] == "R10" for v in report["violations"])

    validator.start_trip(destination={"x": 500, "y": 0})
    samples, x = cruise(1010.1, 1013, 20, 0.0)
    samples.append((1013.1, 10, x, {"ap": "READY", "dest": None}))
    assert drive(validator, samples)["verdict"] == "INCOMPLETE"

    validator.start_trip(destination={"x": 500, "y": 0})
    samples, x = cruise(1020.1, 1023, 20, 0.0)
    samples.append((1023.1, 10, x, {"mode": "MANUAL"}))
    assert drive(validator, samples)["end_reason"] == "takeover"


def test_end_state_ignored_right_after_start(validator):
    validator.start_trip(destination={"x": 500, "y": 0})
    validator.clock.t = 1000.2
    # Stale ARRIVED from the previous trip in the first sample.
    assert validator.sample(state(1000.2, 0, 0.0, ap="ARRIVED")) is None
    assert validator.active


def test_stall_needs_ten_seconds_without_a_reason(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, timeout_s=100)
    stopped_for_obstacle = [(1000.1 + i * 0.1, 0, 0.0, {"decision": "stop"}) for i in range(150)]
    stalled = [(1015.1 + i * 0.1, 0, 0.0, {}) for i in range(120)]
    report = drive(validator, stopped_for_obstacle + stalled +
                   [(1027.2, 0, 0.0, {"ap": "ARRIVED"})])
    r9 = [v for v in report["violations"] if v["rule"] == "R9"]
    assert len(r9) == 1 and r9[0]["t_s"] == pytest.approx(15.0, abs=0.2)


def test_frozen_car_reporting_speed_is_a_stall(validator):
    """Sim Control can freeze the car while still reporting a speed."""
    validator.start_trip(destination={"x": 500, "y": 0}, timeout_s=100)
    samples, x = cruise(1000.1, 1005, 20, 0.0)
    frozen = [(round(1005.0 + i * 0.1, 2), 14, x, {}) for i in range(1, 140)]
    report = drive(validator, samples + frozen + [(1019.1, 0, x, {"ap": "ARRIVED"})])
    r9 = [v for v in report["violations"] if v["rule"] == "R9"]
    assert len(r9) == 1 and r9[0]["t_s"] == pytest.approx(7.0, abs=0.3)


def test_waiting_behind_an_obstacle_is_not_a_stall(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, timeout_s=100)
    car_ahead = {"id": 5, "x": 12.0, "y": 0.0, "length": 4.6, "width": 1.9, "speed": 0.0}
    waiting = [(round(1000.1 + i * 0.1, 2), 0, 0.0, {"obstacles": [car_ahead]}) for i in range(150)]
    report = drive(validator, waiting + [(1015.2, 0, 0.0, {"ap": "ARRIVED"})])
    assert not [v for v in report["violations"] if v["rule"] == "R9"]


def test_position_jump_is_an_anomaly_not_braking(validator):
    validator.start_trip(destination={"x": 500, "y": 0}, target_speed_kph=30)
    samples, x = cruise(1000.1, 1005, 20, 0.0)
    jump = [(1005.1, 25, x + 40.0, {}), (1005.2, 1, x + 40.0, {}), (1005.3, 1, x + 40.1, {})]
    rest, _ = cruise(1005.4, 1008, 1, x + 40.1)
    report = drive(validator, samples + jump + rest + [(1008.1, 0, x + 41, {"ap": "ARRIVED"})])
    assert [a["type"] for a in report["anomalies"]] == ["position_jump"]
    assert report["anomalies"][0]["distance_m"] == pytest.approx(40, abs=1)
    assert report["distance_m"] < x + 3          # the jump is not counted as driving
    assert not {"R2", "R3", "R4", "R5"} & {v["rule"] for v in report["violations"]}


# ---- hazards -------------------------------------------------------------------

class FakeDaemon:
    def __init__(self):
        self.calls = []

    async def request(self, cmd, timeout=10, **args):
        self.calls.append((cmd, args))
        if args.get("kind") == "cut_in" and args["params"].get("side") == "nowhere":
            raise RuntimeError("No same-direction lane")
        return {"obstacle_id": 20001}


def test_hazard_lifecycle():
    daemon, clock = FakeDaemon(), Clock(500.0)
    hz = HazardManager(daemon.request, clock=clock)

    async def go():
        rec = await hz.start("phantom_obstacle", {"ahead_m": 30})
        assert rec["params"] == {"ahead_m": 30, "duration_s": 10.0, "object": "vehicle"}
        assert daemon.calls[-1][0] == "hazard_start"
        lat = await hz.start("command_latency", {"delay_ms": 500, "duration_s": 4})
        assert len(daemon.calls) == 1          # gateway hazards stay in the gateway
        assert hz.command_delay_s() == 0.5
        drop = await hz.start("telemetry_dropout", {"duration_s": 2})
        assert hz.telemetry_paused()
        clock.t = 503.0
        hz.tick()
        assert not hz.telemetry_paused() and drop["status"] == "expired"
        await hz.stop(rec["id"])
        assert daemon.calls[-1] == ("hazard_stop", {"hazard_id": rec["id"]})
        clock.t = 510.0
        hz.tick()
        assert lat["status"] == "expired" and not hz.active
        over = hz.overlapping(501.0, 509.0)
        assert {o["type"] for o in over} == {"phantom_obstacle", "command_latency", "telemetry_dropout"}
        assert next(o for o in over if o["type"] == "telemetry_dropout")["start_s"] == -1.0
        with pytest.raises(HazardError):
            await hz.start("meteor", {})
        with pytest.raises(HazardError):
            await hz.start("phantom_obstacle", {"duration_s": 0})
        with pytest.raises(RuntimeError):
            await hz.start("cut_in", {"side": "nowhere"})
        assert not hz.active                   # failed hazards are not recorded as active

    asyncio.run(go())


# ---- scenarios -------------------------------------------------------------------

def test_repository_scenarios_are_valid():
    listed = scn.list_scenarios()
    assert listed and all("error" not in s for s in listed), listed


def test_scenario_validation_errors():
    with pytest.raises(scn.ScenarioError):
        scn.validate({"name": "x"})
    with pytest.raises(scn.ScenarioError):
        scn.validate({"destination": {"x": 1, "y": 2}, "hazards": [{"type": "meteor"}]})
    with pytest.raises(scn.ScenarioError):
        scn.validate({"destination": {"x": 1, "y": 2}, "actions": [{"do": "fly"}]})
    sc = scn.validate({"destination": {"x": 1, "y": 2},
                       "hazards": [{"at_s": 3, "type": "cut_in", "ahead_m": 20}]})
    assert sc["start"] is None and sc["hazards"][0]["params"] == {"ahead_m": 20}
    assert sc["expect"] == {"verdict": "PASS"}


def test_expectations():
    report = {"verdict": "PASS", "duration_s": 80,
              "metrics": {"max_decel_mps2": 3.0, "min_gap_m": 1.5, "min_ttc_s": None},
              "violations": [{"rule": "R2"}]}
    ok, fails = scn.evaluate({"verdict": "PASS", "max_decel_mps2": 4.0, "min_ttc_s": 1.0}, report)
    assert ok and not fails
    ok, fails = scn.evaluate({"min_gap_m": 2.0, "forbid": ["R2", "R6"],
                              "max_duration_s": 60}, report)
    assert not ok and len(fails) == 3


def test_summary_and_markdown(tmp_path):
    scenarios = [{"name": "a"}, {"name": "b"}]
    results = [
        {"scenario": "a", "run": 1, "passed": True, "verdict": "PASS", "end_reason": "arrived",
         "duration_s": 70.0, "distance_m": 500.0, "violations": ["R2"], "failures": []},
        {"scenario": "a", "run": 2, "passed": False, "verdict": "FAIL", "end_reason": "error",
         "duration_s": 40.0, "distance_m": 200.0, "violations": ["R9"], "failures": ["verdict"]},
        {"scenario": "b", "run": 1, "passed": False, "error": "gateway down", "failures": ["x"]},
    ]
    s = scn.summarize("t", scenarios, results)
    a = s["scenarios"][0]
    assert a["pass_rate"] == 0.5 and a["mean_trip_s"] == 70.0
    assert a["violations_per_km"] == pytest.approx(2 / 0.7, abs=0.01)
    assert s["scenarios"][1]["verdicts"] == {"ERROR": 1}
    md = scn.markdown(s)
    assert "| a | 2 | 1/2 (50 %)" in md
