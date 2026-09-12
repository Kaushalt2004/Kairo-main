-- Kairo Cloud PostgreSQL Initialization Schema

CREATE TABLE IF NOT EXISTS organizations (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) REFERENCES organizations(id) ON DELETE SET NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(32) DEFAULT 'VIEWER' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    vin VARCHAR(64) UNIQUE,
    model VARCHAR(128) DEFAULT 'Lincoln MKZ' NOT NULL,
    simulator_type VARCHAR(64) DEFAULT 'CARLA' NOT NULL,
    api_key_hash VARCHAR(64) NOT NULL,
    status VARCHAR(32) DEFAULT 'OFFLINE' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_history (
    id VARCHAR(64) PRIMARY KEY,
    vehicle_id VARCHAR(64) REFERENCES vehicles(id) ON DELETE CASCADE NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    speed FLOAT DEFAULT 0.0 NOT NULL,
    steering FLOAT DEFAULT 0.0 NOT NULL,
    throttle FLOAT DEFAULT 0.0 NOT NULL,
    brake FLOAT DEFAULT 0.0 NOT NULL,
    gear VARCHAR(8) DEFAULT 'D' NOT NULL,
    autonomy_mode VARCHAR(32) DEFAULT 'MANUAL' NOT NULL,
    system_status VARCHAR(32) DEFAULT 'STANDBY' NOT NULL,
    latitude FLOAT,
    longitude FLOAT,
    heading FLOAT,
    cpu_usage FLOAT,
    gpu_usage FLOAT,
    memory_usage FLOAT,
    raw_payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_telemetry_vehicle_time ON telemetry_history(vehicle_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS commands (
    id VARCHAR(64) PRIMARY KEY,
    vehicle_id VARCHAR(64) REFERENCES vehicles(id) ON DELETE CASCADE NOT NULL,
    command_type VARCHAR(64) NOT NULL,
    parameters JSONB NOT NULL,
    status VARCHAR(32) DEFAULT 'PENDING' NOT NULL,
    issued_by_user_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    delivered_at TIMESTAMP WITH TIME ZONE,
    executed_at TIMESTAMP WITH TIME ZONE,
    result JSONB,
    error_message VARCHAR(512)
);

CREATE INDEX IF NOT EXISTS ix_command_vehicle_status ON commands(vehicle_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS sensor_status (
    id VARCHAR(64) PRIMARY KEY,
    vehicle_id VARCHAR(64) REFERENCES vehicles(id) ON DELETE CASCADE NOT NULL,
    sensor_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) DEFAULT 'ONLINE' NOT NULL,
    message VARCHAR(255),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_sensor_vehicle_time ON sensor_status(vehicle_id, sensor_type, timestamp DESC);

CREATE TABLE IF NOT EXISTS simulation_sessions (
    id VARCHAR(64) PRIMARY KEY,
    vehicle_id VARCHAR(64) REFERENCES vehicles(id) ON DELETE CASCADE NOT NULL,
    scenario_name VARCHAR(128) DEFAULT 'Town01_Standard' NOT NULL,
    map_name VARCHAR(128) DEFAULT 'Town01' NOT NULL,
    weather VARCHAR(64) DEFAULT 'ClearNoon' NOT NULL,
    time_of_day FLOAT DEFAULT 12.0 NOT NULL,
    state VARCHAR(32) DEFAULT 'STOPPED' NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    total_distance_m FLOAT DEFAULT 0.0 NOT NULL,
    total_frames INTEGER DEFAULT 0 NOT NULL,
    metrics JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_sim_vehicle_time ON simulation_sessions(vehicle_id, started_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id VARCHAR(64) PRIMARY KEY,
    vehicle_id VARCHAR(64) REFERENCES vehicles(id) ON DELETE CASCADE NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    severity VARCHAR(32) DEFAULT 'INFO' NOT NULL,
    description VARCHAR(512) NOT NULL,
    details JSONB NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_vehicle_severity_time ON events(vehicle_id, severity, timestamp DESC);

CREATE TABLE IF NOT EXISTS vehicle_connections (
    id VARCHAR(64) PRIMARY KEY,
    vehicle_id VARCHAR(64) REFERENCES vehicles(id) ON DELETE CASCADE NOT NULL,
    connected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    disconnected_at TIMESTAMP WITH TIME ZONE,
    client_ip VARCHAR(64),
    protocol VARCHAR(32) DEFAULT 'WebSocket' NOT NULL,
    close_reason VARCHAR(255)
);
