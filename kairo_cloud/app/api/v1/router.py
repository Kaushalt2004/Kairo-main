from fastapi import APIRouter

from app.api.v1.endpoints import auth, commands, events, sensors, simulation, telemetry, vehicles
from app.websockets import client_ws, vehicle_ws

api_router = APIRouter()

# Authentication & Users
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Fleet & Vehicle Management
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["Vehicles"])

# Telemetry
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["Telemetry"])

# Sensors
api_router.include_router(sensors.router, prefix="/sensors", tags=["Sensors"])

# Remote Commands
api_router.include_router(commands.router, prefix="/commands", tags=["Commands"])

# Simulation Control
api_router.include_router(simulation.router, prefix="/simulation", tags=["Simulation"])

# Events & Safety Alerts
api_router.include_router(events.router, prefix="/events", tags=["Events"])

# WebSocket Routers
ws_router = APIRouter()
ws_router.include_router(vehicle_ws.router, tags=["Vehicle WebSockets"])
ws_router.include_router(client_ws.router, tags=["Client WebSockets"])
