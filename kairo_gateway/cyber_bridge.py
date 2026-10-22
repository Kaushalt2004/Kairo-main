"""Host side of the Cyber daemon pipe.

Copies cyber_daemon.py into the Apollo container and keeps one
`docker exec -i ... python3 cyber_daemon.py` process alive, exchanging JSON
lines over its stdin/stdout. Plain threads (not asyncio subprocesses) so it
works under any event loop policy uvicorn picks on Windows.
"""

import asyncio
import concurrent.futures
import itertools
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("kairo.cyber")

DAEMON_SRC = Path(__file__).with_name("cyber_daemon.py")
DAEMON_DST = "/tmp/kairo_cyber_daemon.py"
# Modules the daemon imports, copied next to it.
DAEMON_MODULES = [Path(__file__).with_name("kairo_traffic.py")]

HEARTBEAT_S = 5.0
STALL_RESTART_S = 20.0  # parked telemetry still arrives twice a second

_LAUNCH = (
    # A daemon whose gateway was killed can outlive it; never run two.
    "pkill -f '^python3 -u " + DAEMON_DST + "' >/dev/null 2>&1; "
    "source /apollo/cyber/setup.bash >/dev/null 2>&1; "
    # setup.bash hardcodes the docker0 gateway; Cyber must bind to this
    # container's own IP to see the other processes.
    'export CYBER_IP=$(hostname -I | awk "{print \\$1}"); '
    "export PYTHONPATH=/apollo/bazel-bin/cyber/python/internal:"
    "/apollo/bazel-bin:/apollo:$PYTHONPATH; "
    "cd /tmp; exec python3 -u " + DAEMON_DST + " 2>>/tmp/kairo_cyber_daemon.err"
)


class CyberBridge:
    def __init__(self, container: str):
        self.container = container
        self.telemetry: Optional[Dict[str, Any]] = None
        self.telemetry_at = 0.0
        self.last_error: Optional[str] = None
        self.on_telemetry: List[Callable[[Dict[str, Any]], None]] = []

        self._proc: Optional[subprocess.Popen] = None
        self._write_lock = threading.Lock()
        self._pending: Dict[int, concurrent.futures.Future] = {}
        self._ids = itertools.count(1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle -------------------------------------------------------

    @property
    def connected(self) -> bool:
        return (
            self._proc is not None
            and self._proc.poll() is None
            and time.time() - self.telemetry_at < 3.0
        )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _heartbeat(self) -> None:
        """Lets the daemon notice when this gateway is gone (see
        HEARTBEAT_TIMEOUT_S in cyber_daemon.py)."""
        while not self._stop.wait(HEARTBEAT_S):
            proc = self._proc
            if proc is None or proc.poll() is not None:
                continue
            if self.telemetry_at and time.time() - self.telemetry_at > STALL_RESTART_S:
                # Alive but silent (stuck): kill it; _run_forever restarts it.
                log.warning("Cyber daemon sent no telemetry for %.0f s; restarting it",
                            time.time() - self.telemetry_at)
                self.telemetry_at = 0.0
                proc.kill()
                continue
            try:
                with self._write_lock:
                    proc.stdin.write(b'{"cmd":"heartbeat"}\n')
                    proc.stdin.flush()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                proc.kill()

    def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            started = time.time()
            try:
                self._run_once()
                self.last_error = "Cyber daemon exited"
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                log.warning("Cyber bridge error: %s", e)
            self._fail_pending(self.last_error or "Cyber daemon disconnected")
            if self._stop.is_set():
                break
            # Reset the backoff after a run that stayed up for a while.
            backoff = 1.0 if time.time() - started > 30 else min(backoff * 2, 15)
            log.info("Restarting Cyber daemon in %.0fs", backoff)
            self._stop.wait(backoff)

    def _run_once(self) -> None:
        for src, dst in [(DAEMON_SRC, DAEMON_DST)] + [
                (m, "/tmp/" + m.name) for m in DAEMON_MODULES]:
            subprocess.run(
                ["docker", "cp", str(src), f"{self.container}:{dst}"],
                check=True, capture_output=True, timeout=30,
            )
        log.info("Starting Cyber daemon in container %s", self.container)
        self._proc = subprocess.Popen(
            ["docker", "exec", "-i", self.container, "bash", "-c", _LAUNCH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        for raw in self._proc.stdout:
            if self._stop.is_set():
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("{"):
                continue  # Cyber/glog noise
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            self._dispatch(msg)
        self._proc.wait()

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "telemetry":
            # The daemon leaves out slow fields (hmi, route) when unchanged.
            if self.telemetry:
                for key in ("hmi", "route"):
                    if key not in msg and key in self.telemetry:
                        msg[key] = self.telemetry[key]
            self.telemetry = msg
            self.telemetry_at = time.time()
            self.last_error = None
            for cb in list(self.on_telemetry):
                try:
                    cb(msg)
                except Exception:  # noqa: BLE001
                    log.exception("telemetry callback failed")
        elif kind == "reply":
            fut = self._pending.pop(msg.get("id"), None)
            if fut and not fut.done():
                if msg.get("ok"):
                    fut.set_result(msg.get("data"))
                else:
                    fut.set_exception(RuntimeError(msg.get("error") or "failed"))
        elif kind == "ready":
            log.info("Cyber daemon ready (map %s)", msg.get("map_dir"))

    def _fail_pending(self, reason: str) -> None:
        pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(reason))

    # ---- requests --------------------------------------------------------

    def send_nowait(self, cmd: str, **args: Any) -> bool:
        """Fire-and-forget (no reply), for high-rate inputs like pedals."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        payload = json.dumps({"cmd": cmd, **args}, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(payload.encode("utf-8"))
                proc.stdin.flush()
            return True
        except OSError:
            return False

    async def request(self, cmd: str, timeout: float = 10.0, **args: Any) -> Any:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise RuntimeError(
                self.last_error or "Apollo container is not reachable")
        req_id = next(self._ids)
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._pending[req_id] = fut
        payload = json.dumps({"id": req_id, "cmd": cmd, **args}) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(payload.encode("utf-8"))
                proc.stdin.flush()
        except OSError as e:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"Cyber daemon pipe closed: {e}") from e
        try:
            return await asyncio.wait_for(asyncio.wrap_future(fut), timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"Apollo did not answer '{cmd}' in {timeout:.0f}s")
