import json
import logging
from typing import Any, Dict, List, Optional
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisManager:
    """Manages Redis connection, caching, pub/sub, and vehicle state tracking."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._memory_cache: Dict[str, Any] = {}
        self._memory_online: Dict[str, float] = {}

    async def connect(self) -> None:
        """Initializes Redis connection pool."""
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=2.0
            )
            await self._redis.ping()
            logger.info("Successfully connected to Redis at %s", settings.REDIS_URL)
        except Exception as e:
            logger.warning("Redis unavailable (%s). Falling back to in-memory state manager.", e)
            self._redis = None

    async def close(self) -> None:
        """Closes Redis connections."""
        if self._redis:
            await self._redis.close()
            logger.info("Closed Redis connection pool.")

    @property
    def is_connected(self) -> bool:
        return self._redis is not None

    async def set_vehicle_latest(self, vehicle_id: str, payload: Dict[str, Any]) -> None:
        """Stores the latest high-frequency telemetry snapshot for a vehicle."""
        key = f"vehicle:{vehicle_id}:latest"
        json_str = json.dumps(payload, default=str)
        if self._redis:
            try:
                await self._redis.set(key, json_str, ex=86400)
                # Publish to real-time pub/sub channel for horizontal scaling
                await self._redis.publish(f"channel:vehicle:{vehicle_id}:telemetry", json_str)
                await self._redis.publish("channel:fleet:telemetry", json_str)
                return
            except Exception as e:
                logger.error("Redis write failed: %s", e)
        # Fallback to memory
        self._memory_cache[key] = payload

    async def get_vehicle_latest(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the latest telemetry snapshot for a vehicle."""
        key = f"vehicle:{vehicle_id}:latest"
        if self._redis:
            try:
                val = await self._redis.get(key)
                if val:
                    return json.loads(val)
            except Exception as e:
                logger.error("Redis read failed: %s", e)
        return self._memory_cache.get(key)

    async def set_vehicle_online(self, vehicle_id: str, ttl_seconds: int = 15) -> None:
        """Sets vehicle online status with a TTL heartbeat expiration."""
        key = f"vehicle:{vehicle_id}:online"
        import time
        if self._redis:
            try:
                await self._redis.set(key, "1", ex=ttl_seconds)
                await self._redis.sadd("fleet:active_vehicles", vehicle_id)
                return
            except Exception as e:
                logger.error("Redis set_online failed: %s", e)
        self._memory_online[vehicle_id] = time.time() + ttl_seconds

    async def set_vehicle_offline(self, vehicle_id: str) -> None:
        """Explicitly marks a vehicle as offline."""
        key = f"vehicle:{vehicle_id}:online"
        if self._redis:
            try:
                await self._redis.delete(key)
                await self._redis.srem("fleet:active_vehicles", vehicle_id)
                return
            except Exception as e:
                logger.error("Redis set_offline failed: %s", e)
        self._memory_online.pop(vehicle_id, None)

    async def is_vehicle_online(self, vehicle_id: str) -> bool:
        """Checks if vehicle heartbeat is currently active."""
        key = f"vehicle:{vehicle_id}:online"
        import time
        if self._redis:
            try:
                exists = await self._redis.exists(key)
                return bool(exists)
            except Exception as e:
                logger.error("Redis check online failed: %s", e)
        expiry = self._memory_online.get(vehicle_id)
        return bool(expiry and expiry > time.time())

    async def get_active_vehicle_ids(self) -> List[str]:
        """Returns list of currently online vehicle IDs."""
        import time
        if self._redis:
            try:
                members = await self._redis.smembers("fleet:active_vehicles")
                active = []
                for vid in members:
                    if await self.is_vehicle_online(vid):
                        active.append(vid)
                    else:
                        await self._redis.srem("fleet:active_vehicles", vid)
                return active
            except Exception as e:
                logger.error("Redis get_active_vehicles failed: %s", e)
        now = time.time()
        return [vid for vid, exp in self._memory_online.items() if exp > now]

    async def publish_command(self, vehicle_id: str, command_payload: Dict[str, Any]) -> None:
        """Publishes a command to the vehicle command channel."""
        channel = f"channel:vehicle:{vehicle_id}:commands"
        payload_str = json.dumps(command_payload)
        if self._redis:
            try:
                await self._redis.publish(channel, payload_str)
                return
            except Exception as e:
                logger.error("Redis publish_command failed: %s", e)


redis_manager = RedisManager()
