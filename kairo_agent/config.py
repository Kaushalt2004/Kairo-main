import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    cloud_ws_url: str = os.getenv("KAIRO_CLOUD_WS_URL", "ws://localhost:8000")
    vehicle_id: str = os.getenv("KAIRO_VEHICLE_ID", "KAIRO-001")
    api_key: str = os.getenv("KAIRO_API_KEY", "kairo_live_vehicle_kairo_001_key_secret_123")
    adapter_type: str = os.getenv("KAIRO_ADAPTER_TYPE", "mock").lower()
    telemetry_rate_hz: float = float(os.getenv("KAIRO_TELEMETRY_RATE_HZ", "10.0"))
    
    # CARLA settings
    carla_host: str = os.getenv("CARLA_HOST", "127.0.0.1")
    carla_port: int = int(os.getenv("CARLA_PORT", "2000"))
    carla_filter: str = os.getenv("CARLA_FILTER", "vehicle.lincoln.mkz*")

    # Apollo settings
    apollo_bridge_host: str = os.getenv("APOLLO_BRIDGE_HOST", "127.0.0.1")
    apollo_bridge_port: int = int(os.getenv("APOLLO_BRIDGE_PORT", "9090"))

    # Offline Queue
    offline_queue_path: str = os.getenv("OFFLINE_QUEUE_PATH", "kairo_offline_queue.db")


config = AgentConfig()
