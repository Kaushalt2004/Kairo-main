# Kairo Cloud REST API Documentation

The **Kairo Cloud Backend** provides enterprise-grade REST APIs for managing autonomous vehicle fleets, querying real-time and historical telemetry, executing remote commands, and monitoring sensor perception health.

- **Base URL**: `http://<host>:8000/api/v1`
- **Interactive Swagger / OpenAPI UI**: `http://<host>:8000/docs`
- **ReDoc UI**: `http://<host>:8000/redoc`

---

## Standard Response Format

All REST responses follow the standard Kairo envelope:

```json
{
  "success": true,
  "data": { ... },
  "message": "Optional human-readable status message",
  "timestamp": "2026-09-12T04:15:30.000Z"
}
```

---

## 1. Authentication (`/auth`)

### Register User
- **Method**: `POST /auth/register`
- **Body**:
  ```json
  {
    "email": "operator@kairo.ai",
    "password": "SecurePassword123!",
    "full_name": "Mission Control Operator",
    "role": "OPERATOR"
  }
  ```
- **Roles**: `ADMIN`, `OPERATOR`, `VIEWER`

### User Login
- **Method**: `POST /auth/login`
- **Body**:
  ```json
  {
    "email": "admin@kairo.ai",
    "password": "AdminPass123!"
  }
  ```
- **Response**:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5c...",
    "token_type": "bearer",
    "expires_in": 86400,
    "user_id": "usr_...",
    "email": "admin@kairo.ai",
    "role": "ADMIN"
  }
  ```

---

## 2. Fleet & Vehicle Management (`/vehicles`)

### Register Vehicle
- **Method**: `POST /vehicles/register`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>` (Requires `ADMIN` or `OPERATOR`)
- **Body**:
  ```json
  {
    "id": "KAIRO-001",
    "name": "Apollo Lincoln MKZ",
    "vin": "1FA6P8CF5H5000001",
    "model": "Lincoln MKZ Hybrid",
    "simulator_type": "CARLA"
  }
  ```
- **Response**: Returns the plaintext API key once.

### List Fleet Vehicles
- **Method**: `GET /vehicles`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **Response**: Returns list of all vehicles with live connectivity status and latest telemetry summary.

### Get Single Vehicle
- **Method**: `GET /vehicles/{vehicle_id}`

### Update Vehicle Status
- **Method**: `PUT /vehicles/{vehicle_id}/status`
- **Body**:
  ```json
  {
    "status": "MAINTENANCE"
  }
  ```

---

## 3. Telemetry (`/telemetry`)

### Get Latest Telemetry Snapshot
- **Method**: `GET /telemetry/{vehicle_id}/latest`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **Response**: Complete canonical Kairo telemetry packet directly from Redis cache.

### Query Historical Telemetry
- **Method**: `GET /telemetry/{vehicle_id}/history`
- **Query Parameters**:
  - `start_time`: ISO-8601 timestamp
  - `end_time`: ISO-8601 timestamp
  - `limit`: Integer (1 to 1000, default 100)

### REST Telemetry Ingestion (Fallback)
- **Method**: `POST /telemetry/{vehicle_id}/ingest`
- **Headers**: `X-API-Key: <VEHICLE_API_KEY>`
- **Body**: Standard Kairo `TelemetryPayload` JSON.

---

## 4. Onboard Sensors (`/sensors`)

### Get Current Sensor Statuses
- **Method**: `GET /sensors/{vehicle_id}`
- **Response**: Latest health status of all cameras, LiDAR, radar, and GNSS/IMU units.

### Ingest Sensor Status Change
- **Method**: `POST /sensors/{vehicle_id}/status`
- **Headers**: `X-API-Key: <VEHICLE_API_KEY>`
- **Body**:
  ```json
  {
    "sensor_type": "LIDAR",
    "status": "DEGRADED",
    "message": "Point cloud density below threshold"
  }
  ```

---

## 5. Remote Commands (`/commands`)

### Issue Whitelisted Command
- **Method**: `POST /commands/{vehicle_id}`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>` (Requires `OPERATOR` or `ADMIN`)
- **Body**:
  ```json
  {
    "command_type": "START_SIMULATION",
    "parameters": {
      "scenario": "Town01_Standard",
      "weather": "ClearNoon"
    }
  }
  ```
- **Supported Commands**:
  - `START_SIMULATION`: `{"scenario": "...", "weather": "..."}`
  - `STOP_SIMULATION`: `{}`
  - `PAUSE_SIMULATION`: `{}`
  - `RESET_SIMULATION`: `{}`
  - `CHANGE_WEATHER`: `{"weather": "ClearNoon" | "WetNoon" | "HardRainNoon" | ...}`
  - `CHANGE_TIME`: `{"hour": 16.5}`
  - `SET_AUTONOMY_MODE`: `{"mode": "MANUAL" | "ASSISTED" | "AUTONOMOUS" | "EMERGENCY_STOP"}`
  - `REQUEST_DIAGNOSTICS`: `{}`

### List Vehicle Commands Audit Log
- **Method**: `GET /commands/{vehicle_id}`

---

## 6. Simulation Sessions (`/simulation`)

- `GET /simulation/{vehicle_id}/status`: Active simulation session details and runtime metrics.
- `POST /simulation/{vehicle_id}/start`: Starts a new simulation run.
- `POST /simulation/{vehicle_id}/stop`: Ends the active simulation run.
- `POST /simulation/{vehicle_id}/weather`: Dynamically modifies simulation weather.
- `POST /simulation/{vehicle_id}/time`: Modifies simulated sun altitude and hour.

---

## 7. Safety Events & Alerts (`/events`)

- `GET /events/{vehicle_id}`: Query mission events, takeovers, emergency braking triggers.
- `POST /events/{vehicle_id}`: Edge agent records safety disengagement or alert.
