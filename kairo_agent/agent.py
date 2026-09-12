import asyncio
import logging
import signal
import sys
from typing import Any, Dict

from kairo_agent.adapters import ApolloAdapter, BaseVehicleAdapter, CarlaAdapter, MockAdapter, Ros2Adapter
from kairo_agent.client.offline_queue import OfflineQueue
from kairo_agent.client.ws_client import KairoWsClient
from kairo_agent.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [KairoAgent] %(message)s"
)
logger = logging.getLogger("kairo_agent")


class KairoVehicleAgent:
    """Edge daemon running onboard autonomous vehicle or simulation host."""

    def __init__(self):
        self.config = config
        self.adapter: BaseVehicleAdapter = self._select_adapter()
        self.offline_queue = OfflineQueue(db_path=self.config.offline_queue_path)
        self.ws_client = KairoWsClient(
            base_ws_url=self.config.cloud_ws_url,
            vehicle_id=self.config.vehicle_id,
            api_key=self.config.api_key,
            on_command_callback=self.handle_command
        )
        self._running = False

    def _select_adapter(self) -> BaseVehicleAdapter:
        adapter_type = self.config.adapter_type
        logger.info("Configured vehicle adapter: %s", adapter_type.upper())
        if adapter_type == "carla":
            return CarlaAdapter(
                host=self.config.carla_host,
                port=self.config.carla_port,
                vehicle_filter=self.config.carla_filter,
                vehicle_id=self.config.vehicle_id
            )
        elif adapter_type == "apollo":
            return ApolloAdapter(
                bridge_host=self.config.apollo_bridge_host,
                bridge_port=self.config.apollo_bridge_port,
                vehicle_id=self.config.vehicle_id
            )
        elif adapter_type == "ros2":
            return Ros2Adapter(vehicle_id=self.config.vehicle_id)
        else:
            return MockAdapter(vehicle_id=self.config.vehicle_id)

    async def handle_command(self, cmd_data: Dict[str, Any]) -> None:
        """Executes cloud command on adapter and returns execution acknowledgment."""
        command_id = cmd_data.get("command_id", "unknown")
        command_type = cmd_data.get("command_type", "")
        parameters = cmd_data.get("parameters", {})

        logger.info("Executing command [%s]: %s with parameters: %s", command_id, command_type, parameters)

        # Notify Cloud that command is currently executing
        await self.ws_client.send_ack(command_id=command_id, status="EXECUTING")

        try:
            result = await self.adapter.execute_command(command_type, parameters)
            logger.info("Command [%s] completed successfully: %s", command_id, result)
            await self.ws_client.send_ack(command_id=command_id, status="COMPLETED", result=result)
        except Exception as e:
            logger.error("Command [%s] failed: %s", command_id, e)
            await self.ws_client.send_ack(command_id=command_id, status="FAILED", error_message=str(e))

    async def _drain_offline_queue(self) -> None:
        """Transmits buffered offline packets to Cloud once reconnected."""
        batch = self.offline_queue.peek_batch(limit=25)
        if not batch:
            return

        sent_ids = []
        for row_id, payload in batch:
            if not self.ws_client.is_connected:
                break
            ok = await self.ws_client.send_telemetry(payload)
            if ok:
                sent_ids.append(row_id)

        if sent_ids:
            self.offline_queue.delete_batch(sent_ids)
            logger.info("Drained %d buffered packets from offline storage", len(sent_ids))

    async def start(self) -> None:
        """Main agent run loop."""
        logger.info("Starting Kairo Vehicle Agent for %s...", self.config.vehicle_id)
        self._running = True

        # Initialize adapter
        await self.adapter.initialize()

        # Start WebSocket client
        await self.ws_client.start()

        dt = 1.0 / max(1.0, self.config.telemetry_rate_hz)

        try:
            while self._running:
                # 1. Drain offline queue if connected
                if self.ws_client.is_connected:
                    await self._drain_offline_queue()

                # 2. Poll live telemetry from vehicle/simulator
                telemetry = await self.adapter.poll_telemetry()
                if telemetry:
                    if self.ws_client.is_connected:
                        sent = await self.ws_client.send_telemetry(telemetry)
                        if not sent:
                            self.offline_queue.enqueue(telemetry)
                    else:
                        # Offline: buffer locally to SQLite
                        self.offline_queue.enqueue(telemetry)

                await asyncio.sleep(dt)

        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Shutting down Kairo Vehicle Agent...")
        self._running = False
        await self.ws_client.stop()
        await self.adapter.shutdown()
        logger.info("Kairo Vehicle Agent shutdown complete.")


def main():
    agent = KairoVehicleAgent()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def signal_handler():
        logger.info("Received termination signal.")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows signal handler fallback
            pass

    try:
        loop.run_until_complete(agent.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(agent.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
