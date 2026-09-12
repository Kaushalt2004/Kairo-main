import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.services.connection_manager import connection_manager
from app.services.telemetry_service import telemetry_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/v1/stream/telemetry")
async def client_telemetry_stream(
    websocket: WebSocket,
    vehicle_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Real-time downstream WebSocket stream for Tablet HMI and Web Dashboards."""
    await websocket.accept()

    # Optional JWT validation
    if token:
        payload = decode_access_token(token)
        if not payload:
            await websocket.send_json({"error": "Invalid or expired JWT token"})
            await websocket.close(code=1008)
            return

    await connection_manager.connect_client(websocket, vehicle_id=vehicle_id)

    # If vehicle_id is requested, immediately transmit the latest known state so UI renders instantly
    if vehicle_id:
        latest = await telemetry_service.get_latest_telemetry(vehicle_id, db)
        if latest:
            await websocket.send_json({
                "type": "telemetry",
                "vehicle_id": vehicle_id,
                "data": latest
            })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                # Client heartbeat
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "time": datetime.now(timezone.utc).isoformat()})
            except Exception:
                pass
    except WebSocketDisconnect:
        logger.info("Client stream disconnected.")
    except Exception as e:
        logger.debug("Client stream exception: %s", e)
    finally:
        await connection_manager.disconnect_client(websocket)
