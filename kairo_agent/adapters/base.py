from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseVehicleAdapter(ABC):
    """Abstract Base Class for all Kairo vehicle and simulation adapters.
    
    Decouples the Kairo Agent and Cloud from CARLA, Apollo, ROS 2, or real vehicle CAN bus.
    """

    @abstractmethod
    async def initialize(self) -> bool:
        """Initializes connection to the underlying vehicle system or simulator."""
        pass

    @abstractmethod
    async def poll_telemetry(self) -> Optional[Dict[str, Any]]:
        """Polls current vehicle dynamics, sensors, compute, and autonomy states.
        
        Must return a dictionary compatible with standard Kairo TelemetryPayload.
        """
        pass

    @abstractmethod
    async def execute_command(self, command_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a cloud-issued command on the underlying system.
        
        Returns result dict to be sent back in CommandAck.
        Raises Exception if command execution fails.
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleans up resources and disconnects from vehicle/simulator."""
        pass
