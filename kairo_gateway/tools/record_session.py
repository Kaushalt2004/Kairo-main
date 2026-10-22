"""Records a live gateway session as fixtures for the mock gateway and for
tablet tests (docs/validation_api_samples/).

With Apollo and the gateway running:

    python -m kairo_gateway.tools.record_session --seconds 90 --scenario town05_corner_traffic

It records the /ws state stream while the given scenario drives (traffic,
hazards and the safety status included), plus one copy of every other
endpoint's response.
"""

import argparse
import asyncio
import gzip
import json
import shutil
import threading
import time
import urllib.request
from pathlib import Path

import websockets

from kairo_gateway import scenarios as scn

OUT = Path(__file__).resolve().parents[2] / "docs" / "validation_api_samples"


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.loads(r.read())


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=1), encoding="utf-8")


async def record_ws(base, seconds, out):
    url = base.replace("http", "ws", 1) + "/ws"
    async with websockets.connect(url, max_size=None) as ws:
        end = time.time() + seconds
        while time.time() < end:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
            except asyncio.TimeoutError:
                break
            out.append(json.loads(msg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:8090")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--scenario", default="town05_corner_traffic")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    base = args.gateway.rstrip("/")

    states = []
    sc = scn.find(args.scenario)
    sc["repeat"] = 1
    runner = scn.ScenarioRunner(scn.GatewayClient(base), out_dir=OUT / "_tmp")
    driver = threading.Thread(target=runner.run_batch, args=([sc],), daemon=True)
    driver.start()
    asyncio.run(record_ws(base, args.seconds, states))
    driver.join(timeout=300)
    shutil.rmtree(OUT / "_tmp", ignore_errors=True)

    with gzip.open(OUT / "session.jsonl.gz", "wt", encoding="utf-8") as f:
        for s in states:
            f.write(json.dumps(s, separators=(",", ":")) + "\n")
    with gzip.open(OUT / "map.json.gz", "wt", encoding="utf-8") as f:
        json.dump(get(base, "/api/map"), f, separators=(",", ":"))
    for name, path in [("state.json", "/api/state"), ("route.json", "/api/route"),
                       ("safety.json", "/api/safety"), ("hazards.json", "/api/hazards"),
                       ("traffic.json", "/api/traffic"), ("scenarios.json", "/api/scenarios"),
                       ("benchmarks.json", "/api/benchmarks"),
                       ("safety_reports.json", "/api/safety/reports?limit=20")]:
        save(name, get(base, path))
    reports = get(base, "/api/safety/reports?limit=20")["reports"]
    (OUT / "reports").mkdir(exist_ok=True)
    for r in reports:
        save(f"reports/{r['trip_id']}.json", get(base, f"/api/safety/reports/{r['trip_id']}"))
    benches = get(base, "/api/benchmarks")["benchmarks"]
    if benches:
        save("benchmark.json", get(base, f"/api/benchmarks/{benches[0]['batch_id']}"))
    print(f"recorded {len(states)} states, {len(reports)} reports into {OUT}")


if __name__ == "__main__":
    main()
