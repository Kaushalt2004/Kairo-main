"""Client for Dreamview Plus' own websocket (ws://<host>:8888/websocket).

This is the same channel the Dreamview web UI uses for HMI actions, so
anything done here (sim control, map/mode switch, module start/stop, start
point) shows up in Dreamview exactly as if it was clicked there.

Message shape (see modules/dreamview_plus/backend/hmi/hmi.cc):
  -> {"type": "HMIAction", "action": "request",
      "data": {"name": "", "requestId": "...", "info": {"action": ..., "value": ...}}}
  <- {"action": "response", "data": {"requestId": "...", "info": {"code": 0, ...}}}
"""

import asyncio
import itertools
import json
import logging
from typing import Any, Dict, Optional

import websockets

log = logging.getLogger("kairo.dreamview")

# Dreamview only replies to these HMI actions; the rest are fire-and-forget.
_HMI_ACTIONS_WITH_REPLY = {"CHANGE_MAP", "CHANGE_OPERATION", "CHANGE_MODE"}


class DreamviewError(RuntimeError):
    pass


class DreamviewClient:
    def __init__(self, url: str):
        self.url = url
        self.connected = False
        self.last_error: Optional[str] = None
        self._ws = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._ws:
            await self._ws.close()

    async def _run_forever(self) -> None:
        backoff = 1.0
        while True:
            try:
                # Dreamview Plus never answers websocket pings, so keepalive
                # pings would drop the connection every ~40s.
                async with websockets.connect(
                    self.url, max_size=None, ping_interval=None, open_timeout=5,
                ) as ws:
                    self._ws = ws
                    self.connected = True
                    self.last_error = None
                    backoff = 1.0
                    log.info("Connected to Dreamview at %s", self.url)
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        self._on_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                if self.connected:
                    log.warning("Dreamview connection lost: %s", self.last_error)
            finally:
                self._ws = None
                self.connected = False
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(DreamviewError("Dreamview disconnected"))
                self._pending.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

    def _on_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("action") != "response":
            return
        data = msg.get("data") or {}
        fut = self._pending.pop(str(data.get("requestId")), None)
        if fut and not fut.done():
            fut.set_result(data.get("info") or {})

    async def request(self, msg_type: str, info: Dict[str, Any],
                      expect_reply: bool = True, timeout: float = 10.0) -> Dict[str, Any]:
        ws = self._ws
        if ws is None:
            raise DreamviewError(
                f"Dreamview is not reachable at {self.url}"
                + (f" ({self.last_error})" if self.last_error else ""))
        request_id = f"kairo-{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        if expect_reply:
            self._pending[request_id] = fut
        await ws.send(json.dumps({
            "type": msg_type,
            "action": "request",
            "data": {"name": "", "requestId": request_id, "info": info},
        }))
        if not expect_reply:
            return {"code": 0, "message": "Sent"}
        try:
            reply = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise DreamviewError(f"Dreamview did not answer {msg_type} in {timeout:.0f}s")
        if reply.get("code", 0) != 0:
            raise DreamviewError(reply.get("message") or f"{msg_type} failed")
        return reply

    async def hmi_action(self, action: str, value: Optional[str] = None) -> Dict[str, Any]:
        info: Dict[str, Any] = {"action": action}
        if value is not None:
            info["value"] = value
        return await self.request(
            "HMIAction", info, expect_reply=action in _HMI_ACTIONS_WITH_REPLY)

    async def set_start_point(self, x: Optional[float] = None, y: Optional[float] = None,
                              heading: Optional[float] = None) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        if x is not None and y is not None:
            info["point"] = {"x": x, "y": y, "heading": heading or 0.0}
        return await self.request("SetStartPoint", info)

    async def reset_sim(self) -> Dict[str, Any]:
        return await self.request("Reset", {})
