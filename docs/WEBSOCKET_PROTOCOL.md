# Kairo Real-Time WebSocket Protocol Specification

This document specifies the bidirectional WebSocket protocol connecting **Kairo Vehicle Agents** and **Kairo Client Dashboards / Tablet HMIs** with the **Kairo Cloud Backend**.

---

## 1. Connection Endpoints

| Purpose | Endpoint | Protocol | Authentication |
| :--- | :--- | :--- | :--- |
| **Vehicle Ingestion & Commands** | `/ws/v1/vehicles/{vehicle_id}/telemetry` | `ws://` or `wss://` | `?api_key=<KEY>` or `X-API-Key` header |
| **Client Telemetry Stream** | `/ws/v1/stream/telemetry` | `ws://` or `wss://` | `?token=<JWT>` (optional) |

---

## 2. Vehicle Agent Stream (`/ws/v1/vehicles/{vehicle_id}/telemetry`)

### A. Handshake & Authentication
Upon connection, the vehicle passes its API key in the query parameters:
```
GET /ws/v1/vehicles/KAIRO-001/telemetry?api_key=kairo_live_vehicle_kairo_001_key_secret_123
```
- If valid, the server accepts and emits a `welcome` frame:
```json
{
  "type": "welcome",
  "vehicle_id": "KAIRO-001",
  "message": "Connected to Kairo Cloud. Vehicle KAIRO-001 registered.",
  "server_time": "2026-09-12T04:15:30.000Z"
}
```
- If invalid or inactive, the server responds with an error JSON and closes with code `1008 (Policy Violation)`.

### B. Upstream Telemetry Frame (Agent -> Cloud)
The Vehicle Agent transmits telemetry at 10–20 Hz formatted as:
```json
{
  "type": "telemetry",
  "data": {
    "vehicle_id": "KAIRO-001",
    "timestamp": "2026-09-12T04:15:30.120Z",
    "seq": 10452,
    "location": {
      "latitude": 37.42201,
      "longitude": -122.08412,
      "altitude": 14.8,
      "heading": 89.5
    },
    "kinematics": {
      "speed": 11.2,
      "speed_kmh": 40.3,
      "acceleration": 0.45,
      "yaw_rate": 0.02,
      "roll": 0.1,
      "pitch": -0.2
    },
    "controls": {
      "steering": -0.04,
      "throttle": 0.28,
      "brake": 0.0,
      "gear": "D",
      "handbrake": false,
      "turn_indicator": "OFF"
    },
    "compute": {
      "cpu_usage": 38.5,
      "gpu_usage": 62.0,
      "memory_usage": 44.1,
      "temperature_c": 52.4
    },
    "autonomy": {
      "mode": "AUTONOMOUS",
      "status": "ACTIVE",
      "disengagement_reason": null,
      "target_speed_kmh": 45.0,
      "cte_meters": 0.012
    },
    "sensors": [
      {"name": "front_camera", "sensor_type": "CAMERA", "status": "ONLINE", "fps": 30.0, "latency_ms": 14.2},
      {"name": "hesai_lidar", "sensor_type": "LIDAR", "status": "ONLINE", "fps": 10.0, "latency_ms": 22.0},
      {"name": "front_radar", "sensor_type": "RADAR", "status": "ONLINE", "fps": 20.0, "latency_ms": 8.5},
      {"name": "novatel_gnss", "sensor_type": "GPS", "status": "ONLINE", "fps": 10.0, "latency_ms": 4.0}
    ],
    "simulation": {
      "is_simulated": true,
      "simulator": "CARLA",
      "scenario": "Town01_Standard",
      "weather": "ClearNoon",
      "time_of_day": 14.5,
      "simulation_fps": 30.0
    }
  }
}
```

### C. Downstream Command Frame (Cloud -> Agent)
When an operator issues a command, the Cloud routes it down to the vehicle:
```json
{
  "type": "command",
  "data": {
    "command_id": "cmd_4a9b2c3d4e5f",
    "command_type": "CHANGE_WEATHER",
    "parameters": {
      "weather": "HardRainNoon"
    },
    "timestamp": "2026-09-12T04:15:32.000Z"
  }
}
```

### D. Upstream Command Acknowledgment (Agent -> Cloud)
Upon execution, the Agent returns an `ack` frame:
```json
{
  "type": "ack",
  "data": {
    "command_id": "cmd_4a9b2c3d4e5f",
    "status": "COMPLETED",
    "result": {
      "status": "weather_updated",
      "weather": "HardRainNoon"
    },
    "error_message": null
  }
}
```

---

## 3. Client Telemetry Stream (`/ws/v1/stream/telemetry`)

Used by the **Flutter Tablet HMI** and Web Dashboards.
- Query Parameter: `?vehicle_id=KAIRO-001` (subscribes to single vehicle) or omit for entire fleet stream.
- The server pushes:
  1. Instant latest telemetry packet upon connection so the UI populates immediately.
  2. Live real-time frames (`type: "telemetry"`).
  3. Live command execution updates (`type: "command_update"`).
