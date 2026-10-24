"""Vehicle body state: locks, closures, lights, signals, comfort.

Apollo models only the driving side of a car. Its chassis command covers
turn signals, hazards, beams and the horn (forwarded as a real
ChassisCommand by the gateway); everything else a Tesla-style screen
controls - locks, frunk/trunk, mirrors, climate, ... - lives here as the
car's body-controller state: one authoritative copy shared by every
connected tablet, persisted across gateway restarts, with the same rules a
car would enforce.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

LIGHT_MODES = ("OFF", "PARKING", "ON", "AUTO")
TURN_SIGNALS = ("NONE", "LEFT", "RIGHT")

DEFAULTS: Dict[str, Any] = {
    "locked": True,
    "frunk_open": False,
    "trunk_open": False,
    "charge_port_open": False,
    "glovebox_open": False,
    "lights": "AUTO",
    "high_beam": False,
    "hazards": False,
    "turn_signal": "NONE",
    "horn": False,
    "mirrors_folded": False,
    "child_lock": False,
    "window_lock": False,
    "sentry": True,
    "dashcam": True,
    "car_wash": False,
    "neutral_tow": False,
    "climate_on": True,
    "cabin_temp_c": 22.0,
}

# Closures that a car refuses to open while moving.
_CLOSURES = ("frunk_open", "trunk_open", "charge_port_open")
_MOVING_KPH = 3.0
_DRIVE_AWAY_LOCK_KPH = 8.0
# Fields that change what Apollo's chassis command carries.
SIGNAL_FIELDS = ("lights", "high_beam", "hazards", "turn_signal", "horn")


class BodyError(ValueError):
    pass


class VehicleBody:
    def __init__(self, path: Path):
        self._path = path
        self.state: Dict[str, Any] = dict(DEFAULTS)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.state.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
        self.state["horn"] = False  # never resume honking after a restart

    def apply(self, patch: Dict[str, Any], speed_kph: float) -> Dict[str, Any]:
        """Validates and applies a partial update. Returns the changed keys."""
        changes: Dict[str, Any] = {}
        for key, value in patch.items():
            if key not in DEFAULTS:
                raise BodyError(f"Unknown control '{key}'")
            changes[key] = self._coerce(key, value)

        for key in _CLOSURES:
            if changes.get(key) and not self.state[key] and speed_kph > _MOVING_KPH:
                raise BodyError("Can't open that while the car is moving")
        if changes.get("neutral_tow") and speed_kph > _MOVING_KPH:
            raise BodyError("Stop the car before enabling tow mode")

        # Mode side effects, as on the real thing.
        if "car_wash" in changes:
            changes.setdefault("mirrors_folded", changes["car_wash"])
            if changes["car_wash"]:
                changes.setdefault("charge_port_open", False)
                changes.setdefault("sentry", False)
        if changes.get("hazards"):
            changes.setdefault("turn_signal", "NONE")
        if changes.get("turn_signal", "NONE") != "NONE":
            changes.setdefault("hazards", False)
        if changes.get("high_beam") and self._merged(changes)["lights"] in ("OFF", "PARKING"):
            changes["lights"] = "ON"

        changed = {k: v for k, v in changes.items() if self.state[k] != v}
        self.state.update(changed)
        if set(changed) - {"horn"}:
            self._save()
        return changed

    def on_speed(self, speed_kph: float) -> bool:
        """Drive-away locking. Returns True when it changed the state."""
        if speed_kph > _DRIVE_AWAY_LOCK_KPH and not self.state["locked"]:
            self.state["locked"] = True
            self._save()
            return True
        return False

    def apollo_signal(self) -> Dict[str, Any]:
        """The body state as Apollo's VehicleSignal fields."""
        s = self.state
        if s["hazards"]:
            turn = "TURN_HAZARD_WARNING"
        else:
            turn = {"LEFT": "TURN_LEFT", "RIGHT": "TURN_RIGHT"}.get(
                s["turn_signal"], "TURN_NONE")
        low = s["lights"] in ("ON", "AUTO")
        return {
            "turn": turn,
            "low_beam": low,
            "high_beam": low and s["high_beam"],
            "horn": s["horn"],
            "emergency_light": s["hazards"],
        }

    def _merged(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        return {**self.state, **changes}

    @staticmethod
    def _coerce(key: str, value: Any) -> Any:
        default = DEFAULTS[key]
        if key == "lights":
            value = str(value).upper()
            if value not in LIGHT_MODES:
                raise BodyError(f"lights must be one of {', '.join(LIGHT_MODES)}")
            return value
        if key == "turn_signal":
            value = str(value).upper()
            if value not in TURN_SIGNALS:
                raise BodyError(f"turn_signal must be one of {', '.join(TURN_SIGNALS)}")
            return value
        if key == "cabin_temp_c":
            try:
                temp = round(float(value) * 2) / 2
            except (TypeError, ValueError) as e:
                raise BodyError("cabin_temp_c must be a number") from e
            if not 15.0 <= temp <= 28.0:
                raise BodyError("Cabin temperature must be between 15 and 28 °C")
            return temp
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise BodyError(f"{key} must be true or false")
            return value
        return value

    def _save(self) -> None:
        state: Optional[Dict[str, Any]] = {k: v for k, v in self.state.items() if k != "horn"}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state, indent=2), encoding="utf-8")
