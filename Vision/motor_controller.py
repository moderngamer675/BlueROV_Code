from shared_state import SharedState, Command
from rov_config import MAX_SPEED_SURFACE, MAX_SPEED_UNDERWATER, MAX_SPEED_BENCH, THRUSTER_COUNT

NEUTRAL = {"x": 0, "y": 0, "z": 500, "r": 0}

MOVEMENT_VECTORS = {
    "forward": {"x": +1.0}, "backward": {"x": -1.0},
    "strafe_right": {"y": +1.0}, "strafe_left": {"y": -1.0},
    "yaw_cw": {"r": +1.0}, "yaw_ccw": {"r": -1.0},
}

KEY_TO_DIRECTION = {
    "w": "forward", "s": "backward", "d": "strafe_right", "a": "strafe_left",
    "e": "yaw_cw", "q": "yaw_ccw",
}

SPEED_PROFILES = {
    "bench": MAX_SPEED_BENCH, "pool": 150, "surface": MAX_SPEED_SURFACE,
    "underwater": MAX_SPEED_UNDERWATER, "crawl": 50, "custom": 300,
}

class MotionController:
    def __init__(self, state: SharedState):
        self._state = state
        self._speed, self._profile_name = SPEED_PROFILES["custom"], "custom"

    @property
    def speed(self) -> int: return self._speed
    @property
    def speed_percent(self) -> float: return self._speed / 10.0
    @property
    def profile(self) -> str: return self._profile_name

    def set_speed_profile(self, name: str):
        if name in SPEED_PROFILES:
            self._speed, self._profile_name = SPEED_PROFILES[name], name
            self._state.log(f"Speed profile → {name.upper()} ({self.speed_percent:.0f}%)")

    def set_speed(self, value: int):
        self._speed, self._profile_name = max(0, min(1000, int(value))), "custom"

    def move(self, *directions: str):
        axes = dict(NEUTRAL)
        for direction in directions:
            vector = MOVEMENT_VECTORS.get(direction)
            if not vector: continue
            for axis, scale in vector.items():
                axes[axis] += int(scale * self._speed)
        
        axes["x"] = max(-1000, min(1000, axes["x"]))
        axes["y"] = max(-1000, min(1000, axes["y"]))
        axes["r"] = max(-1000, min(1000, axes["r"]))
        self._send(axes)

    def move_from_keys(self, key_states: dict) -> bool:
        active_directions = [KEY_TO_DIRECTION[k] for k, pressed in key_states.items() if pressed and k in KEY_TO_DIRECTION]
        if not active_directions: return False
        self.move(*active_directions)
        return True

    def stop(self): self._send(NEUTRAL)

    def _send(self, axes: dict):
        self._state.send_command(Command(name="set_motion", kwargs={
            "forward": axes["x"] / 1000.0, "lateral": axes["y"] / 1000.0,
            "throttle": (axes["z"] - 500) / 500.0, "yaw": axes["r"] / 1000.0,
        }))

    def get_status(self) -> dict:
        return {"speed": self._speed, "speed_percent": self.speed_percent, "profile": self._profile_name, "thruster_count": THRUSTER_COUNT}