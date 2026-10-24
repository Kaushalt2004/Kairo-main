You are working in the Flutter tablet app **kairo_frontend** (https://github.com/HuNTer8272/kairo_frontend). It is the in-car tablet UI for KAIRO. The app drives Baidu Apollo through the KAIRO gateway, a FastAPI service in the separate Kairo repo (https://github.com/Kaushalt2004/Kairo-main, branch `apollo-tablet-integration`). Your task is to build the **Validation** screens under Settings > Validation: live safety status, hazard injection, simulated traffic, safety reports, and scenario batches and benchmarks.

## Setup (no Apollo or Docker needed)

1. Clone the Kairo repo next to this app. From its root, run the mock gateway:
   `pip install fastapi "uvicorn[standard]" pyyaml` and then `python -m kairo_gateway.mock_gateway`.
   It serves the real gateway API on port 8090 and replays a drive recorded on the real system: car, traffic, hazards and safety status. Hazards, traffic and scenario batches respond in memory.
2. Run the app against it:
   `flutter run -d windows --dart-define=KAIRO_GATEWAY_URL=http://127.0.0.1:8090`
   The Android emulator default (`http://10.0.2.2:8090`) also works.
3. Read `docs/validation_api.md` in the Kairo repo. It is the API contract. Real responses are in `docs/validation_api_samples/`.

## What already exists (do not modify; another developer owns these files)

- `lib/services/apollo/apollo_service.dart`: `ApolloService` (a `ChangeNotifier`). `apollo.state` (`ApolloState?`) and `apollo.gatewayUrl`. It notifies on every state message, up to 10 per second.
- `lib/models/apollo_state.dart`: the typed state. `state.raw` is the full decoded JSON message. Read `raw['safety']`, `raw['hazards']` and `raw['traffic']` from it.
- `lib/widgets/apollo/apollo_selector.dart`: `ApolloSelector<T>` rebuilds only when the selected value changes. Use it for live data.
- `lib/widgets/apollo/*`: the map, trip card and manual driving. The map already draws `scene.obstacles`, which includes simulated traffic and hazard obstacles.
- Settings > Validation is already wired. `lib/widgets/settings_panel.dart` opens `ValidationSettings(apollo: apollo)` from `lib/features/validation/validation_settings.dart`, which is a placeholder. Replace the placeholder's body; keep the class name and constructor.

## Rules

- Put all code under `lib/features/validation/` and all tests under `test/validation/` (fixtures in `test/fixtures/validation/`). Do not edit files outside these folders. If you need a change elsewhere, stop and describe it instead of making it.
- Add no new packages unless unavoidable. `http` is already a dependency. Draw charts with `CustomPainter`.
- Match the existing look: `Theme.of(context).colorScheme`, the tiles in `lib/widgets/common/control_tile.dart`, and the layout of `lib/widgets/apollo/autopilot_settings.dart`. Target a landscape tablet, with touch targets of at least 48 px.
- Write typed models with `fromJson` in `lib/features/validation/models/`. Parse defensively: many fields can be null. For example, `metrics.min_gap_m` is null when no obstacle was ever ahead.
- Use one small API client, `lib/features/validation/validation_api.dart`, built on `package:http` with `apollo.gatewayUrl` and 10 s timeouts. Show gateway errors (the `detail` field of 4xx/5xx responses) in a SnackBar.

## Screens (tabs or a segmented control inside ValidationSettings)

1. **Live**
   - The current trip from `raw['safety']`: trip id or scenario, elapsed time, and critical and warning counts.
   - Ongoing violations as red (critical) or amber (warning) chips, plus the last violation.
   - Active hazards from `raw['hazards']`, each with a countdown and a Stop button (`DELETE /api/hazards/{id}`).
   - Traffic status from `raw['traffic']`.
   - A lost-link banner when no state update has arrived for more than 1.5 s while connected. The `telemetry_dropout` hazard tests this: track the time of the last `ApolloService` notification.
   - When no trip is active, show `last_report` with a link to its detail page.
2. **Hazards**
   - One card per type from `GET /api/hazards` → `types`, with its parameters pre-filled from `defaults`. Numbers use steppers or sliders; `side` and `object` use segmented choices.
   - An Inject button that calls `POST /api/hazards {type, ...params}`.
   - Lists of active and recent hazards, and a Clear all button (`POST /api/hazards/clear`).
3. **Traffic**
   - Inputs for count (1–40), radius (20–500 m) and an optional seed.
   - Start (`POST /api/traffic/start`) and Stop (`POST /api/traffic/stop`) buttons, and the current vehicle count.
   - Show the 409 message clearly, for example when Apollo's Prediction module is running.
4. **Reports**
   - A list from `GET /api/safety/reports`, showing the verdict badge (PASS green, FAIL red, INCOMPLETE grey), scenario or name, time, duration, distance and counts.
   - A detail page with:
     - the verdict and end reason, and a metrics grid;
     - a violations table: rule, name, severity, time, duration, and value against threshold;
     - the hazard windows;
     - a speed-against-time chart from `timeline`, with hazard windows shaded and violations marked.
   - A path plot of the timeline's x and y is optional.
5. **Scenarios and benchmarks**
   - A list from `GET /api/scenarios`, showing each description, traffic and hazard tags, and repeat count. Allow multi-select and an optional repeat override.
   - Run with `POST /api/scenarios/run {names, repeat}`. While it runs, poll `GET /api/scenarios/batch` every second and show a progress bar, the current scenario and run, the log lines and a Stop button (`POST /api/scenarios/stop`).
   - While a batch runs, show a banner saying the car is being driven by the scenario runner.
   - Benchmarks: a list from `GET /api/benchmarks` and a detail view for `GET /api/benchmarks/{id}`. Show a per-scenario table (runs, pass rate, mean ± sd trip time, violations per km, counts by rule) and the per-run results.

## Tests and checks

- `test/validation/`:
  - model parsing tests using the real JSON from `docs/validation_api_samples/` (copy what you need into `test/fixtures/validation/`);
  - a widget test of the Live panel. Construct `ApolloService(client: <fake http.Client>, prefs: <mock SharedPreferences>)` without calling `init()`, then feed it a recorded message with `debugReceive(jsonString)` or `debugSetLive(ApolloState.fromJson(json))`. `test/apollo_test.dart` shows the pattern;
  - a widget test of the hazard form.
- Before every commit, run `flutter analyze` (no issues) and `flutter test`. All existing tests must still pass.

## Git

Work on the branch `feature/validation-screens`, created from `apollo-integration`. Make small commits that touch only your folders, then open a pull request when done.
