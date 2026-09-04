from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
import uvicorn
from typing import List, Dict

app = FastAPI(title="Kairo Vehicle API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Telemetry(BaseModel):
    speed: float = 0.0
    steering: float = 0.0
    brake: float = 0.0
    throttle: float = 0.0
    objects: int = 0
    pedestrians: int = 0
    lane_detected: bool = False
    camera_status: str = "offline"
    apollo_status: str = "offline"
    monitors: Dict[str, str] = {}

class SimControlReq(BaseModel):
    action: str  # "START", "RESET"

# Global state
current_telemetry = Telemetry()
# Queue for commands intended for run_bridge.py
pending_commands = []

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.get("/")
def read_root():
    return {"status": "Kairo Core API is running"}

@app.get("/api/telemetry", response_model=Telemetry)
def get_telemetry():
    return current_telemetry

@app.post("/api/telemetry")
async def update_telemetry(data: Telemetry):
    global current_telemetry
    current_telemetry = data
    await manager.broadcast(current_telemetry.dict())
    return {"status": "success"}

@app.post("/api/sim_control")
def sim_control(req: SimControlReq):
    global pending_commands
    pending_commands.append(req.action)
    return {"status": "success", "action_sent": req.action}

@app.get("/api/poll_commands")
def poll_commands():
    """Endpoint for run_bridge.py to fetch pending commands."""
    global pending_commands
    cmds = list(pending_commands)
    pending_commands.clear()
    return {"commands": cmds}

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
