"""Import the gateway's safety reports (kairo_gateway/data/reports/*.json) into PostgreSQL.

Each report becomes one simulation_sessions row; each violation becomes one events row.
Writes an SQL file that is loaded with psql, so it needs no Python database driver:

    python kairo_cloud/db/import_reports.py
    docker cp kairo_cloud/db/import_reports.sql kairo_postgres:/tmp/
    docker exec kairo_postgres psql -U postgres -d kairo -f /tmp/import_reports.sql
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "kairo_gateway" / "data" / "reports"
OUT = Path(__file__).with_name("import_reports.sql")
VEHICLE_ID = sys.argv[1] if len(sys.argv) > 1 else "KAIRO-001"


def lit(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def ts(epoch):
    return lit(datetime.fromtimestamp(epoch, timezone.utc).isoformat()) if epoch else "NULL"


def main():
    lines = ["BEGIN;"]
    sessions = events = 0
    for path in sorted(REPORTS.glob("*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        trip = r["trip_id"]
        start = r.get("started_at")
        end = start + r.get("duration_s", 0) if start else None
        metrics = {k: r.get(k) for k in ("verdict", "end_reason", "duration_s", "arrival_error_m",
                                          "target_speed_kph", "counts", "destination")}
        metrics.update(r.get("metrics") or {})
        lines.append(
            "INSERT INTO simulation_sessions (id, vehicle_id, scenario_name, map_name, weather, time_of_day, "
            "state, started_at, ended_at, total_distance_m, total_frames, metrics) VALUES ("
            f"{lit(trip)}, {lit(VEHICLE_ID)}, {lit(r.get('scenario') or r.get('name') or 'manual')}, "
            f"{lit(r.get('map'))}, 'ClearNoon', 12.0, {lit(r.get('verdict', 'UNKNOWN'))}, "
            f"{ts(start)}, {ts(end)}, {r.get('distance_m') or 0}, {r['samples'] if isinstance(r.get('samples'), int) else len(r.get('samples') or [])}, "
            f"{lit(json.dumps(metrics))}::jsonb) ON CONFLICT (id) DO NOTHING;")
        sessions += 1
        for i, v in enumerate(r.get("violations") or []):
            t = start + v["t_s"] if start and v.get("t_s") is not None else start
            desc = f"{v.get('rule')} {v.get('name', '')} value={v.get('value')} threshold={v.get('threshold')}"
            lines.append(
                "INSERT INTO events (id, vehicle_id, event_type, severity, description, details, timestamp) VALUES ("
                f"{lit(f'{trip}-v{i}')}, {lit(VEHICLE_ID)}, {lit('SAFETY_' + str(v.get('rule')))}, "
                f"{lit(str(v.get('severity', 'warning')).upper())}, {lit(desc.strip()[:500])}, "
                f"{lit(json.dumps({**v, 'trip_id': trip}))}::jsonb, {ts(t)}) ON CONFLICT (id) DO NOTHING;")
            events += 1
    lines.append("COMMIT;")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{sessions} sessions, {events} events -> {OUT}")


if __name__ == "__main__":
    main()
