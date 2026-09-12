import asyncio
import os
import tempfile
import pytest

from kairo_agent.adapters.mock_adapter import MockAdapter
from kairo_agent.client.offline_queue import OfflineQueue


@pytest.mark.asyncio
async def test_mock_adapter_telemetry_and_commands():
    adapter = MockAdapter(vehicle_id="KAIRO-TEST-001")
    init_ok = await adapter.initialize()
    assert init_ok is True

    # Poll telemetry
    telemetry = await adapter.poll_telemetry()
    assert telemetry is not None
    assert telemetry["vehicle_id"] == "KAIRO-TEST-001"
    assert "location" in telemetry
    assert "kinematics" in telemetry
    assert "controls" in telemetry
    assert "sensors" in telemetry
    assert len(telemetry["sensors"]) >= 3

    # Execute weather change command
    weather_res = await adapter.execute_command("CHANGE_WEATHER", {"weather": "HardRainNoon"})
    assert weather_res["status"] == "weather_updated"
    assert weather_res["weather"] == "HardRainNoon"

    # Execute autonomy mode change
    mode_res = await adapter.execute_command("SET_AUTONOMY_MODE", {"mode": "EMERGENCY_STOP"})
    assert mode_res["status"] == "mode_updated"
    assert mode_res["mode"] == "EMERGENCY_STOP"

    # Verify brake engaged upon emergency stop
    telemetry_estop = await adapter.poll_telemetry()
    assert telemetry_estop["controls"]["brake"] == 1.0

    # Execute diagnostics command
    diag_res = await adapter.execute_command("REQUEST_DIAGNOSTICS", {})
    assert diag_res["status"] == "healthy"

    await adapter.shutdown()


def test_offline_queue_buffering_and_draining():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_queue.db")
        queue = OfflineQueue(db_path=db_path)

        assert queue.count() == 0

        # Enqueue 3 packets
        queue.enqueue({"seq": 1, "speed": 10.0})
        queue.enqueue({"seq": 2, "speed": 12.0})
        queue.enqueue({"seq": 3, "speed": 14.0})

        assert queue.count() == 3

        # Peek batch of 2
        batch = queue.peek_batch(limit=2)
        assert len(batch) == 2
        assert batch[0][1]["seq"] == 1
        assert batch[1][1]["seq"] == 2

        # Delete drained records
        ids_to_del = [batch[0][0], batch[1][0]]
        queue.delete_batch(ids_to_del)
        assert queue.count() == 1

        # Peek remaining
        remaining = queue.peek_batch(limit=10)
        assert len(remaining) == 1
        assert remaining[0][1]["seq"] == 3
