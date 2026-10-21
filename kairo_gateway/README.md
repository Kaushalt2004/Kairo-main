# KAIRO vehicle gateway

Lets the Flutter tablet UI (`vehicle_tablet_ui_segregated`) control the car the way a Tesla's centre screen does: send it somewhere on autopilot, drive it by hand, shift gears, and work the locks, lights and other body controls. Every driving command shows up in Dreamview Plus as well.

```
tablet (Flutter) ── HTTP + WS :8090 ──▶ kairo_gateway (host PC)
                                          ├─ ws://127.0.0.1:8888/websocket ─▶ Dreamview Plus HMI
                                          └─ docker exec -i ───────────────▶ cyber_daemon.py (Cyber RT, in the Apollo container)
```

You don't need to publish any extra container ports. The gateway copies `cyber_daemon.py` into the container and talks to it over a persistent `docker exec` pipe.

## Run

1. Start Apollo and Dreamview Plus (from the repo root, inside the container):
   ```
   docker start apollo_dev_kairo_it37
   docker exec apollo_dev_kairo_it37 bash /apollo/start_dreamview_monitor.sh
   ```
2. Start the gateway on the host:
   ```
   pip install -r kairo_gateway/requirements.txt
   python -m kairo_gateway          # or: powershell kairo_gateway/start_gateway.ps1
   ```
3. Run the tablet app and point it at the gateway:
   ```
   flutter run --dart-define=KAIRO_GATEWAY_URL=http://<this-pc-ip>:8090
   ```
   The default is `http://10.0.2.2:8090`, which is the host as seen from the Android emulator. You can change the URL at runtime in **Settings → Autopilot**.
   For a real tablet, add the PC's IP to `android/app/src/main/res/xml/network_security_config.xml`. Android blocks plain HTTP otherwise.

Without CARLA, the gateway turns on Dreamview's **Sim Control** the first time you send a destination, so the car has a pose and drives in simulation. To drive with CARLA, start the bridge and switch Sim Control off in Settings → Autopilot.

## What the tablet controls

| Tablet | Apollo |
|---|---|
| Tap the map → *Go here*, Home/Work | `LaneFollowCommand` (routing and driving, with cruise speed as `target_speed`) |
| Stop / Pull over / Resume / End trip | `ActionCommand` STOP / PULL_OVER / START / CLEAR_PLANNING |
| Lane left / right | `ActionCommand` CHANGE_LEFT / CHANGE_RIGHT |
| Sim Control, HD map, mode, modules | Dreamview HMI actions (CHANGE_OPERATION, CHANGE_MAP, START/STOP_MODULE, ...) |
| *Move car* / *Reset car* | Dreamview `SetStartPoint` (Sim Control only) |
| *Drive manually*, pedals, steering, P R N D | KAIRO virtual vehicle (below): publishes `/apollo/localization/pose` and `/apollo/canbus/chassis` |
| Hazards, turn signals, low/high beam, horn | `ChassisCommand` on `/apollo/external_command/chassis` (goes to canbus on a real vehicle), and shown on the virtual vehicle's chassis |
| Locks, frunk, trunk, charge port, mirrors, climate, sentry, ... | Body controller state in the gateway (`vehicle_body.py`) |
| Speed, gear, route, trajectory, obstacles | `/apollo/canbus/chassis`, `/localization/pose`, `/planning`, `/perception/obstacles`, `/planning/command` |

### Manual driving

Dreamview's Sim Control only does "perfect control": it follows Apollo's plan and ignores throttle and steering, so manual driving can't go through it. When you take over, the gateway switches Sim Control off and the daemon's **virtual vehicle** takes over. It's a kinematic bicycle model that publishes the car's pose and chassis at 50 Hz, driven by the tablet's pedals, wheel and gear. Apollo and Dreamview see a car moving normally, with the gear, speed and signals you set.

- **Take over:** press *Drive manually*, or shift out of D from the top bar (below 4 km/h).
- **Hand back:** press *Hand back*, or send a destination. Sim Control resumes from exactly where you left the car.
- **Inputs:** the tablet streams `{"type":"drive","throttle","brake","steer"}` over `/ws` at 20 Hz.
- **Dead-man stop:** if inputs stop for 0.8 s (app closed, Wi-Fi drop), the car brakes on its own.
- **Gear changes:** shifting between P, R and D is refused above 4 km/h.

### Body controls

There's one authoritative copy in the gateway, shared by every connected tablet and saved to `data/body.json`. It enforces the same rules a car would:

- The frunk, trunk and charge port won't open while the car is moving.
- The car locks itself when it drives away (above 8 km/h).
- Car-wash mode folds the mirrors.
- Hazards cancel any turn signal.

Lights, signals and the horn are also sent to Apollo as a `ChassisCommand`. This needs `ChassisCommandProcessor` in `/apollo/modules/external_command/process_component/conf/config.pb.txt`. It has been added there; the original is kept as `config.pb.txt.bak_kairo`.

## API

- `GET /api/state` returns the full snapshot.
- `WS /ws` pushes the snapshot without the route: 10 times a second while the car moves or is driven manually, otherwise only when something changes. It also accepts the manual `drive` inputs.
- `GET /api/route` returns the route polyline. Fetch it when `scene.route_rev` changes.
- `GET /api/map` returns the lane centrelines of the loaded HD map (gzipped).
- `POST /api/drive/manual {enabled}` and `POST /api/drive/gear {gear}` hand control over and shift.
- `POST /api/body {field: value, ...}` sets body controls, and `POST /api/body/horn` sounds the horn.
- `POST /api/autopilot/{go,stop,pull_over,resume,cancel}` and `POST /api/autopilot/lane_change/{left,right}`
- `POST /api/dreamview/{sim_control,map,mode,setup,reset_mode,start_point}` and `POST /api/dreamview/modules/{name}`
- `PUT|DELETE /api/places/{id}` saves places per HD map, in `kairo_gateway/data/places.json`.

Environment variables: `KAIRO_APOLLO_CONTAINER` (default `apollo_dev_kairo_it37`), `KAIRO_DREAMVIEW_WS`, `KAIRO_GATEWAY_PORT` (default `8090`).

## Performance

Measured on this setup (12 cores, 16 GB):

| Piece | Cost |
|---|---|
| `cyber_daemon.py` | 10% of one core parked, 13% while driving manually (under 1% of the machine) |
| Apollo itself | control 17–27%, Dreamview 17–22%, planning 11–27%, monitor and routing about 10% each (all of one core) |

How the daemon keeps its cost down:

- Chassis and pose arrive at about 90 Hz each, and planning at 9 Hz × 24 KB. The daemon keeps only the newest raw bytes and decodes them once per update.
- It sends HMI status and the route only when they change.
- It updates 10 times a second while the car moves and twice a second when parked.
- Each gateway restart kills any leftover daemon, and a daemon exits by itself if its gateway's heartbeat stops.

The real cause of lag on this PC was memory. WSL (Docker) takes half the RAM by default and keeps Linux file cache that Windows never gets back. With Apollo, the emulator, Chrome and VS Code all running, Windows had under 2 GB free and was paging. `%USERPROFILE%/.wslconfig` caps WSL at 6 GB and returns unused cache to Windows. Apply it with `wsl --shutdown`, then restart Docker Desktop and Apollo.

## Apollo and map fixes for the CARLA maps

Autopilot used to freeze in turns, never change lanes, and fail to appear after a cold start. These are the causes and the fixes. Every edited file inside the container keeps its original next to it (`*.bak_kairo` or `*.orig_kairo`).

| Problem | Cause | Fix |
|---|---|---|
| Car freezes in curves | The path optimizer hugs the inside of the curve; the car ends up a few millimetres outside its own corridor and every later plan is infeasible | `l_weight` 1 → 10 in `planning/tasks/{lane_follow_path,fallback_path}/conf/default_conf.pb.txt`; `extend_buffer` 0.2 → 0.5 |
| Lane changes never happen | The converted maps record each road as one lane wide (`left/right_road_sample` = lane width), so the corridor can't include the car's current lane | `tools/fix_carla_road_width.py` widens the road samples to cover same-direction neighbour lanes (applied to Town02–05) |
| Planning slow, solver time-outs | Debug curve dumps on every cycle, 200-knot problems, 90 ms solver budget | In `planning.conf`: `enable_print_curve` / `export_chart` off, `path_bounds_decider_resolution=1.0`, `path_speed_osqp_setting_time_limit=0.4` |
| No car after a cold start | Dreamview Plus' Sim Control only runs once a vehicle *dynamic model* is selected | The gateway selects "Simulation Perfect Control" whenever it turns Sim Control on (startup, first trip, the switch, hand-back) |
| *Move car* / taps not driving | Points off the lane centre, and *Move car* always faced east | Every tap is snapped to the nearest lane and the lane's direction (`/api/snap`); pins more than 8 m from a road are refused |
| Hand-back facing the wrong way | Snapping chose the opposite-direction lane | Hand-back snaps to lanes running the car's way |

The gateway also notices when the car is stuck: Sim Control keeps reporting the last speed while frozen, so it watches the position instead. When stuck, it re-routes from where the car is (up to twice) before reporting an error.

## Known Apollo behaviour

- The CARLA maps' routing graph has malformed lane links at some junctions (for example north of x = −47 on Town05), and lots of zero-length junction lanes. A route through those can lose the car. The automatic re-route usually recovers; when it can't, the tablet says so. Pick a destination elsewhere.
- Apollo's emergency pull-over brakes gently and eases to the curb, so it takes a while. Resume works during and after it.
- A destination on the opposite-direction lane makes Apollo route around the block. That is correct routing, not a bug.
