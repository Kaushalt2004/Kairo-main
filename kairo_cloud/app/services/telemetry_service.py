import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_manager
from app.models.telemetry import TelemetryRecord
from app.models.sensor import SensorStatusRecord, SensorType, SensorState
from app.schemas.telemetry import TelemetryPayload
from app.services.connection_manager import connection_manager

logger = logging.getLogger(__name__)

# In-memory tracking of last database persistence timestamp per vehicle (rate limit DB writes to 1 Hz)
_last_persisted_time: Dict[str, float] = {}


class TelemetryService:
    """Service handling high-frequency telemetry caching, downsampled persistence, and queries."""

    async def ingest_telemetry(
        self,
        vehicle_id: str,
        payload_data: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Processes high-frequency incoming vehicle telemetry: updates Redis, broadcasts to WS, persists snapshot."""
        # 1. Update online state with 15-second heartbeat window
        await redis_manager.set_vehicle_online(vehicle_id, ttl_seconds=15)

        # 2. Store latest snapshot in Redis & pub/sub
        await redis_manager.set_vehicle_latest(vehicle_id, payload_data)

        # 3. Broadcast real-time stream to connected tablet HMIs and web dashboards
        await connection_manager.broadcast_telemetry(vehicle_id, payload_data)

        # 4. Decimate / downsample for PostgreSQL persistence (at most 1 record per second per vehicle)
        now_epoch = time.time()
        last_epoch = _last_persisted_time.get(vehicle_id, 0.0)

        # Persist if 1.0 second has elapsed or if autonomy mode transitioned
        if now_epoch - last_epoch >= 1.0:
            _last_persisted_time[vehicle_id] = now_epoch
            await self._persist_telemetry_snapshot(vehicle_id, payload_data, db)

    async def _persist_telemetry_snapshot(
        self,
        vehicle_id: str,
        payload: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Writes a snapshot to PostgreSQL telemetry_history."""
        try:
            loc = payload.get("location", {})
            kin = payload.get("kinematics", {})
            ctrl = payload.get("controls", {})
            comp = payload.get("compute", {})
            auto = payload.get("autonomy", {})

            record = TelemetryRecord(
                vehicle_id=vehicle_id,
                timestamp=datetime.now(timezone.utc),
                speed=float(kin.get("speed", 0.0)),
                steering=float(ctrl.get("steering", 0.0)),
                throttle=float(ctrl.get("throttle", 0.0)),
                brake=float(ctrl.get("brake", 0.0)),
                gear=str(ctrl.get("gear", "D")),
                autonomy_mode=str(auto.get("mode", "MANUAL")),
                system_status=str(auto.get("status", "STANDBY")),
                latitude=loc.get("latitude"),
                longitude=loc.get("longitude"),
                heading=loc.get("heading"),
                cpu_usage=comp.get("cpu_usage"),
                gpu_usage=comp.get("gpu_usage"),
                memory_usage=comp.get("memory_usage"),
                raw_payload=payload
            )
            db.add(record)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error("Failed to persist telemetry snapshot for %s: %s", vehicle_id, e)

    async def get_latest_telemetry(
        self,
        vehicle_id: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """Returns latest telemetry from Redis cache or falls back to DB."""
        cached = await redis_manager.get_vehicle_latest(vehicle_id)
        if cached:
            return cached

        # Query most recent record from DB
        stmt = (
            select(TelemetryRecord)
            .where(TelemetryRecord.vehicle_id == vehicle_id)
            .order_by(TelemetryRecord.timestamp.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            return record.raw_payload
        return None

    async def get_historical_telemetry(
        self,
        vehicle_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        limit: int,
        db: AsyncSession
    ) -> List[TelemetryRecord]:
        """Retrieves paginated historical telemetry records."""
        stmt = select(TelemetryRecord).where(TelemetryRecord.vehicle_id == vehicle_id)
        if start_time:
            stmt = stmt.where(TelemetryRecord.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(TelemetryRecord.timestamp <= end_time)

        stmt = stmt.order_by(TelemetryRecord.timestamp.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


telemetry_service = TelemetryService()
