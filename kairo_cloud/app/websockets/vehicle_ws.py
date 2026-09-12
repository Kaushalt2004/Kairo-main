import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import redis_manager
from app.models.vehicle import VehicleConnection, VehicleStatus
from app.services.auth_service import auth_service
from app.services.command_service import command_service
from app.services.connection_manager import connection_manager
from app.services.telemetry_service import telemetry_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/v1/vehicles/{vehicle_id}/telemetry")
async def vehicle_telemetry_websocket(
    websocket: WebSocket,
    vehicle_id: str,
    api_key: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Real-time bidirectional WebSocket connection for Vehicle Agent."""
    await websocket.accept()

    # If api_key not in query param, check header
    if not api_key:
        api_key = websocket.headers.get("x-api-key")

    # Authenticate vehicle
    vehicle = await auth_service.verify_vehicle_api_key(vehicle_id, api_key or "", db)
    if not vehicle:
        logger.warning("Unauthorized WebSocket connection attempt for vehicle: %s", vehicle_id)
        await websocket.send_json({"error": "Unauthorized: Invalid or missing API key"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Update state & register
    client_ip = websocket.client.host if websocket.client else "unknown"
    conn_record = VehicleConnection(
        vehicle_id=vehicle_id,
        connected_at=datetime.now(timezone.utc),
        client_ip=client_ip,
        protocol="WebSocket"
    )
    db.add(conn_record)
    vehicle.status = VehicleStatus.ONLINE
    await db.commit()

    await connection_manager.connect_vehicle(vehicle_id, websocket)
    await redis_manager.set_vehicle_online(vehicle_id, ttl_seconds=20)

    # Send Welcome / Config handshake
    await websocket.send_json({
        "type": "welcome",
        "vehicle_id": vehicle_id,
        "message": f"Connected to Kairo Cloud. Vehicle {vehicle_id} registered.",
        "server_time": datetime.now(timezone.utc).isoformat()
    })

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                msg = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received from vehicle %s", vehicle_id)
                continue

            msg_type = msg.get("type", "telemetry")

            if msg_type == "telemetry":
                payload_data = msg.get("data", msg)
                await telemetry_service.ingest_telemetry(vehicle_id, payload_data, db)

            elif msg_type == "ack":
                ack_data = msg.get("data", {})
                await command_service.handle_vehicle_ack(ack_data, db)

            elif msg_type == "heartbeat":
                await redis_manager.set_vehicle_online(vehicle_id, ttl_seconds=20)
                await websocket.send_json({"type": "heartbeat_ack", "timestamp": datetime.now(timezone.utc).isoformat()})

    except WebSocketDisconnect:
        logger.info("Vehicle %s WebSocket disconnected cleanly.", vehicle_id)
    except Exception as e:
        logger.error("Error on vehicle %s WebSocket: %s", vehicle_id, e)
    finally:
        await connection_manager.disconnect_vehicle(vehicle_id)
        await redis_manager.set_vehicle_offline(vehicle_id)

        # Update DB records
        conn_record.disconnected_at = datetime.now(timezone.utc)
        vehicle.status = VehicleStatus.OFFLINE
        try:
            await db.commit()
        except Exception:
            pass
