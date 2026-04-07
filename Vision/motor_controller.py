from shared_state import SharedState, Command
from rov_config import MAX_SPEED_SURFACE, MAX_SPEED_UNDERWATER, MAX_SPEED_BENCH, THRUSTER_COUNT

NEUTRAL = {"x": 0, "y": 0, "z": 500, "r": 0}

MOVEMENT_VECTORS = {
    "forward":      {"x": +1.0},
    "backward":     {"x": -1.0},
    "strafe_right": {"y": +1.0},
    "strafe_left":  {"y": -1.0},
    "yaw_cw":       {"r": +1.0},
    "yaw_ccw":      {"r": -1.0},
}

KEY_TO_DIRECTION = {
    "w": "forward", "s": "backward",
    "d": "strafe_right", "a": "strafe_left",
    "e": "yaw_cw", "q": "yaw_ccw",
}

SPEED_PROFILES = {
    "bench": MAX_SPEED_BENCH, "crawl": 50, "pool": 150,
    "underwater": MAX_SPEED_UNDERWATER, "surface": MAX_SPEED_SURFACE, "custom": 300,
}


class MotionController:
    def __init__(self, state: SharedState):
        self._state        = state
        self._speed        = SPEED_PROFILES["custom"]
        self._profile_name = "custom"
        self._auto_ctrl    = None

    def set_auto_controller(self, auto_ctrl):
        self._auto_ctrl = auto_ctrl

    @property
    def speed(self):
        return self._speed

    @property
    def speed_percent(self):
        return self._speed / 10.0

    @property
    def profile(self):
        return self._profile_name

    def set_speed_profile(self, name):
        if name in SPEED_PROFILES:
            self._speed        = SPEED_PROFILES[name]
            self._profile_name = name
            self._state.log(f"Speed profile → {name.upper()} ({self.speed_percent:.0f}%)")

    def set_speed(self, value):
        self._speed        = max(0, min(1000, int(value)))
        self._profile_name = "custom"

    def move(self, *directions):
        axes = dict(NEUTRAL)
        for d in directions:
            for axis, scale in (MOVEMENT_VECTORS.get(d) or {}).items():
                axes[axis] += int(scale * self._speed)
        axes["x"] = max(-1000, min(1000, axes["x"]))
        axes["y"] = max(-1000, min(1000, axes["y"]))
        axes["r"] = max(-1000, min(1000, axes["r"]))
        self._send(axes)

    def move_from_keys(self, key_states):
        active = [KEY_TO_DIRECTION[k] for k, v in key_states.items() if v and k in KEY_TO_DIRECTION]
        if not active:
            return False
        self.move(*active)
        return True

    def move_from_gamepad(self, left_x, left_y, right_x, lt=0.0, rt=0.0):
        if not (abs(left_x) > 0.01 or abs(left_y) > 0.01 or abs(right_x) > 0.01 or lt > 0.01 or rt > 0.01):
            return False
        self._send({
            "x": max(-1000, min(1000, int(left_y  * self._speed))),
            "y": max(-1000, min(1000, int(left_x  * self._speed))),
            "z": max(0,     min(1000, 500 + int((rt - lt) * 500))),
            "r": max(-1000, min(1000, int(right_x * self._speed))),
        })
        return True

    def stop(self):
        self._send(NEUTRAL)

    def _send(self, axes):
        self._state.send_command(Command(name="set_motion", kwargs={
            "forward":  axes["x"] / 1000.0,
            "lateral":  axes["y"] / 1000.0,
            "throttle": (axes["z"] - 500) / 500.0,
            "yaw":      axes["r"] / 1000.0,
        }))

    def toggle_motor_a(self):
        new = not self._state.get_motor_states().get("mot_a", False)
        self._state.send_motor_command("mot_a", new)
        self._state.log(f"🔧 Motor A → {'ON' if new else 'OFF'}")

    def toggle_motor_b(self):
        new = not self._state.get_motor_states().get("mot_b", False)
        self._state.send_motor_command("mot_b", new)
        self._state.log(f"🔧 Motor B → {'ON' if new else 'OFF'}")

    def all_motors_off(self):
        self._state.send_motor_command("mot_all", False)
        self._state.log("🔧 All DC motors → OFF")

    def get_status(self):
        return {"speed": self._speed, "speed_percent": self.speed_percent,
                "profile": self._profile_name, "thruster_count": THRUSTER_COUNT}