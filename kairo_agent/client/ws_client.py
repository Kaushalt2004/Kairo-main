import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional
import websockets

logger = logging.getLogger(__name__)


class KairoWsClient:
    """Resilient WebSocket client for communicating with Kairo Cloud backend."""

    def __init__(
        self,
        base_ws_url: str,
        vehicle_id: str,
        api_key: str,
        on_command_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ):
        self.base_ws_url = base_ws_url.rstrip("/")
        self.vehicle_id = vehicle_id
        self.api_key = api_key
        self.on_command = on_command_callback

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._running = False
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)

        # Reconnect parameters
        self._min_backoff = 1.0
        self._max_backoff = 16.0
        self._current_backoff = self._min_backoff

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def start(self) -> None:
        """Starts background tasks for connection management, sending, and receiving."""
        self._running = True
        asyncio.create_task(self._connection_loop())
        asyncio.create_task(self._send_loop())

    async def stop(self) -> None:
        """Gracefully shuts down connection."""
        self._running = False
        self._connected = False
        if self._ws:
            await self._ws.close()

    async def send_telemetry(self, payload: Dict[str, Any]) -> bool:
        """Enqueues telemetry payload to be transmitted."""
        if not self.is_connected:
            return False
        try:
            self._send_queue.put_nowait({
                "type": "telemetry",
                "data": payload
            })
            return True
        except asyncio.QueueFull:
            logger.warning("Telemetry send queue is full; dropping frame.")
            return False

    async def send_ack(
        self,
        command_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Sends command execution acknowledgment back to Cloud."""
        msg = {
            "type": "ack",
            "data": {
                "command_id": command_id,
                "status": status,
                "result": result,
                "error_message": error_message
            }
        }
        await self._send_queue.put(msg)

    async def _connection_loop(self) -> None:
        """Maintains persistent connection with automatic reconnection and backoff."""
        ws_url = f"{self.base_ws_url}/ws/v1/vehicles/{self.vehicle_id}/telemetry?api_key={self.api_key}"

        while self._running:
            try:
                logger.info("Connecting to Kairo Cloud at %s...", self.base_ws_url)
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._current_backoff = self._min_backoff
                    logger.info("Connected and authenticated with Kairo Cloud!")

                    # Receiver loop
                    async for message in ws:
                        try:
                            msg_obj = json.loads(message)
                            msg_type = msg_obj.get("type")

                            if msg_type == "command":
                                cmd_data = msg_obj.get("data", {})
                                if self.on_command:
                                    asyncio.create_task(self._safe_handle_command(cmd_data))

                            elif msg_type == "welcome":
                                logger.info("Server welcome: %s", msg_obj.get("message"))

                        except Exception as e:
                            logger.error("Error parsing message from cloud: %s", e)

            except Exception as e:
                self._connected = False
                self._ws = None
                if self._running:
                    logger.warning("Cloud WebSocket connection lost: %s. Retrying in %.1fs...", e, self._current_backoff)
                    await asyncio.sleep(self._current_backoff)
                    self._current_backoff = min(self._max_backoff, self._current_backoff * 2)

    async def _safe_handle_command(self, cmd_data: Dict[str, Any]) -> None:
        """Invokes user command handler with exception safety."""
        try:
            if self.on_command:
                await self.on_command(cmd_data)
        except Exception as e:
            logger.error("Unhandled error in command callback: %s", e)

    async def _send_loop(self) -> None:
        """Drains send queue and writes frames to the active socket."""
        while self._running:
            msg = await self._send_queue.get()
            if self._connected and self._ws:
                try:
                    await self._ws.send(json.dumps(msg))
                except Exception as e:
                    logger.debug("Failed sending over websocket: %s", e)
                    # Re-enqueue if it was a critical ack
                    if msg.get("type") == "ack":
                        await self._send_queue.put(msg)
            self._send_queue.task_done()
