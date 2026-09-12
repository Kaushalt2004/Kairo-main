import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSockets for both Vehicle Agents and Client Dashboards/HMIs."""

    def __init__(self):
        # vehicle_id -> WebSocket
        self.active_vehicles: Dict[str, WebSocket] = {}
        # Set of all client websockets
        self.active_clients: Set[WebSocket] = set()
        # vehicle_id -> Set of subscribed client WebSockets
        self.vehicle_subscribers: Dict[str, Set[WebSocket]] = {}
        # Lock for thread safety during socket operations
        self._lock = asyncio.Lock()

    async def connect_vehicle(self, vehicle_id: str, websocket: WebSocket) -> None:
        """Registers an active vehicle WebSocket connection."""
        async with self._lock:
            # If an existing connection exists for this vehicle, close it gracefully
            if vehicle_id in self.active_vehicles:
                try:
                    await self.active_vehicles[vehicle_id].close(code=1000, reason="Superseded by new connection")
                except Exception:
                    pass
            self.active_vehicles[vehicle_id] = websocket
        logger.info("Vehicle connected: %s (Total vehicles: %d)", vehicle_id, len(self.active_vehicles))

    async def disconnect_vehicle(self, vehicle_id: str) -> None:
        """Removes a vehicle connection."""
        async with self._lock:
            self.active_vehicles.pop(vehicle_id, None)
        logger.info("Vehicle disconnected: %s (Total vehicles: %d)", vehicle_id, len(self.active_vehicles))

    def is_vehicle_connected(self, vehicle_id: str) -> bool:
        """Returns True if the vehicle has an active WebSocket."""
        return vehicle_id in self.active_vehicles

    async def connect_client(self, websocket: WebSocket, vehicle_id: Optional[str] = None) -> None:
        """Registers a client (Dashboard or Tablet HMI) connection."""
        async with self._lock:
            self.active_clients.add(websocket)
            if vehicle_id:
                if vehicle_id not in self.vehicle_subscribers:
                    self.vehicle_subscribers[vehicle_id] = set()
                self.vehicle_subscribers[vehicle_id].add(websocket)
        logger.info(
            "Client connected (Subscribed vehicle: %s, Total clients: %d)",
            vehicle_id or "FLEET",
            len(self.active_clients),
        )

    async def disconnect_client(self, websocket: WebSocket) -> None:
        """Removes a client connection and cleans up all subscriptions."""
        async with self._lock:
            self.active_clients.discard(websocket)
            for subscribers in self.vehicle_subscribers.values():
                subscribers.discard(websocket)
        logger.info("Client disconnected (Total clients: %d)", len(self.active_clients))

    async def broadcast_telemetry(self, vehicle_id: str, payload: Dict[str, Any]) -> None:
        """Broadcasts telemetry to clients subscribed to this vehicle and fleet listeners."""
        targets: Set[WebSocket] = set()

        async with self._lock:
            # Vehicle-specific listeners
            if vehicle_id in self.vehicle_subscribers:
                targets.update(self.vehicle_subscribers[vehicle_id])
            # All clients who didn't specify a vehicle (fleet listeners)
            for client in self.active_clients:
                is_specific = any(client in subs for subs in self.vehicle_subscribers.values())
                if not is_specific:
                    targets.add(client)

        if not targets:
            return

        message = {
            "type": "telemetry",
            "vehicle_id": vehicle_id,
            "data": payload
        }
        dead_sockets = set()
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug("Failed sending telemetry to client: %s", e)
                dead_sockets.add(ws)

        if dead_sockets:
            async with self._lock:
                for ws in dead_sockets:
                    self.active_clients.discard(ws)
                    for subs in self.vehicle_subscribers.values():
                        subs.discard(ws)

    async def send_vehicle_command(self, vehicle_id: str, command_payload: Dict[str, Any]) -> bool:
        """Sends a command packet directly down to the vehicle over its active WebSocket."""
        ws = self.active_vehicles.get(vehicle_id)
        if not ws:
            logger.warning("Attempted to send command to offline vehicle %s", vehicle_id)
            return False

        message = {
            "type": "command",
            "data": command_payload
        }
        try:
            await ws.send_json(message)
            logger.info("Dispatched command %s to vehicle %s", command_payload.get("command_id"), vehicle_id)
            return True
        except Exception as e:
            logger.error("Failed to send command to vehicle %s: %s", vehicle_id, e)
            await self.disconnect_vehicle(vehicle_id)
            return False

    async def broadcast_command_update(self, vehicle_id: str, update_payload: Dict[str, Any]) -> None:
        """Notifies clients regarding command lifecycle changes (DELIVERED, EXECUTING, COMPLETED, FAILED)."""
        message = {
            "type": "command_update",
            "vehicle_id": vehicle_id,
            "data": update_payload
        }
        targets = self.vehicle_subscribers.get(vehicle_id, set()) | self.active_clients
        for ws in list(targets):
            try:
                await ws.send_json(message)
            except Exception:
                pass


# Global singleton connection manager
connection_manager = ConnectionManager()
