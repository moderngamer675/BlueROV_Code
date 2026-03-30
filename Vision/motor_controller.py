# motor_controller.py
# Clean motion controller for BlueROV2 4-thruster vectored ROV.
#
# IMPORTANT — HOW THIS WORKS:
#   This module does NOT replicate the Pixhawk mixing matrix.
#   The Pixhawk firmware handles all per-motor PWM computation internally.
#   We send MANUAL_CONTROL messages with axis INTENTIONS (forward, strafe, yaw)
#   and the firmware applies the verified mixing matrix:
#
#   Effective matrix (after direction flags):
#                 FWD   LAT   YAW
#   Port 1 (BR):  +1    -1    -1    (DIR=-1)
#   Port 2 (BL):  +1    +1    +1    (DIR=-1)
#   Port 3 (FR):  +1    +1    -1    (DIR=+1)
#   Port 4 (FL):  +1    -1    +1    (DIR=+1)
#
#   Verified by thrust_direction_test.py on 2025-03-29 — Score 22/24 (optimal).
#
# USAGE:
#   controller = MotionController(shared_state)
#   controller.set_speed_profile("bench")     # 10% thrust
#   controller.move("forward")                 # single axis
#   controller.move("forward", "strafe_right") # combined
#   controller.stop()                          # instant neutral

from shared_state import SharedState, Command
from rov_config import (
    MAX_SPEED_SURFACE, MAX_SPEED_UNDERWATER, MAX_SPEED_BENCH,
    THRUSTER_COUNT
)


# ─── MANUAL_CONTROL Axis Limits ──────────────────────────────────────
# x (forward/back):  -1000 to +1000   neutral: 0
# y (lateral/strafe): -1000 to +1000   neutral: 0
# z (vertical):       0 to 1000        neutral: 500
# r (yaw/rotation):  -1000 to +1000   neutral: 0

# Neutral state — no movement on any axis
NEUTRAL = {"x": 0, "y": 0, "z": 500, "r": 0}

# ─── Movement Vector Table ───────────────────────────────────────────
# Each direction maps to the MANUAL_CONTROL axis and sign.
# The Pixhawk firmware handles all per-motor mixing internally.
# These values are at unit scale (1.0) — multiplied by speed at send time.
#
# Verified against thrust_direction_test.py output (2025-03-29):
#   FORWARD  (+x) → BR↑ BL↑ FR· FL· (rear pair responds, front clipped) ✅
#   BACKWARD (-x) → BR· BL· FR↓ FL↓ (front pair responds, rear clipped) ✅
#   STRAFE_R (+y) → BR↓ BL↑ FR↑ FL↓ (perfect differential)              ✅
#   STRAFE_L (-y) → BR↑ BL↓ FR↓ FL↑ (perfect differential)              ✅
#   YAW_CW   (+r) → BR↓ BL↑ FR↓ FL↑ (perfect rotational)               ✅
#   YAW_CCW  (-r) → BR↑ BL↓ FR↑ FL↓ (perfect rotational)               ✅

MOVEMENT_VECTORS = {
    # Translation
    "forward":      {"x": +1.0},
    "backward":     {"x": -1.0},
    "strafe_right": {"y": +1.0},
    "strafe_left":  {"y": -1.0},

    # Rotation
    "yaw_cw":       {"r": +1.0},   # turn right
    "yaw_ccw":      {"r": -1.0},   # turn left

    # Vertical (no physical thrusters — commands sent but no response)
    "ascend":       {"z": +1.0},   # z above 500
    "descend":      {"z": -1.0},   # z below 500
}

# ─── Keyboard Mapping ────────────────────────────────────────────────
# Maps physical keys to movement direction names.
# Each key-pair is (positive_key, negative_key) → direction names.
KEY_TO_DIRECTION = {
    "w": "forward",
    "s": "backward",
    "d": "strafe_right",
    "a": "strafe_left",
    "e": "yaw_cw",
    "q": "yaw_ccw",
    "r": "ascend",
    "f": "descend",
}

# ─── Speed Profiles ─────────────────────────────────────────────────
# Values are in MANUAL_CONTROL units (0–1000 scale).
# The Pixhawk maps these to PWM range (1100–1900).
SPEED_PROFILES = {
    "bench":      MAX_SPEED_BENCH,       # 100 = 10% — dry testing only
    "pool":       150,                    # 15% — initial water test
    "surface":    MAX_SPEED_SURFACE,      # 700 = 70% — surface operations
    "underwater": MAX_SPEED_UNDERWATER,   # 500 = 50% — underwater operations
    "crawl":      50,                     # 5% — ultra-slow precision
    "custom":     300,                    # 30% — default
}


class MotionController:
    """
    Translates high-level movement commands into MANUAL_CONTROL messages.

    This class does NOT do per-motor mixing — the Pixhawk firmware handles
    that internally using the FRAME_CONFIG=1 mixing matrix with verified
    direction flags (MOT_1=-1, MOT_2=-1, MOT_3=+1, MOT_4=+1).

    All commands are sent via the SharedState command queue, which the
    TelemetryHandler dequeues and executes on its own thread — ensuring
    thread-safe MAVLink access.

    Usage:
        controller = MotionController(shared_state)
        controller.set_speed_profile("bench")

        # Single direction
        controller.move("forward")

        # Combined (forward + strafe)
        controller.move("forward", "strafe_right")

        # From keyboard state dict
        controller.move_from_keys({"w": True, "d": True, "q": False, ...})

        # Immediate stop
        controller.stop()
    """

    def __init__(self, state: SharedState):
        self._state = state
        self._speed = SPEED_PROFILES["custom"]  # default 30%
        self._profile_name = "custom"

    # =================================================================
    #  SPEED CONTROL
    # =================================================================

    @property
    def speed(self) -> int:
        """Current speed in MANUAL_CONTROL units (0–1000)."""
        return self._speed

    @property
    def speed_percent(self) -> float:
        """Current speed as a percentage (0–100)."""
        return self._speed / 10.0

    @property
    def profile(self) -> str:
        """Name of the active speed profile."""
        return self._profile_name

    def set_speed_profile(self, name: str):
        """Set speed from a named profile. Logs the change."""
        if name not in SPEED_PROFILES:
            self._state.log(f"⚠️  Unknown speed profile: {name}")
            return
        self._speed = SPEED_PROFILES[name]
        self._profile_name = name
        self._state.log(
            f"Speed profile → {name.upper()} ({self.speed_percent:.0f}%)")

    def set_speed(self, value: int):
        """Set speed directly in MANUAL_CONTROL units (0–1000)."""
        self._speed = max(0, min(1000, int(value)))
        self._profile_name = "custom"

    # =================================================================
    #  MOVEMENT COMMANDS
    # =================================================================

    def move(self, *directions: str):
        """
        Send a movement command combining one or more directions.

        Examples:
            controller.move("forward")
            controller.move("forward", "strafe_right")
            controller.move("forward", "strafe_right", "yaw_cw")
        """
        axes = dict(NEUTRAL)  # start from neutral

        for direction in directions:
            vector = MOVEMENT_VECTORS.get(direction)
            if vector is None:
                self._state.log(f"⚠️  Unknown direction: {direction}")
                continue
            for axis, scale in vector.items():
                if axis == "z":
                    # z is 0–1000 with 500 neutral — offset from center
                    axes["z"] += int(scale * self._speed * 0.5)
                else:
                    # x, y, r are -1000 to +1000 with 0 neutral
                    axes[axis] += int(scale * self._speed)

        # Clamp to valid ranges
        axes["x"] = max(-1000, min(1000, axes["x"]))
        axes["y"] = max(-1000, min(1000, axes["y"]))
        axes["z"] = max(0, min(1000, axes["z"]))
        axes["r"] = max(-1000, min(1000, axes["r"]))

        self._send(axes)

    def move_from_keys(self, key_states: dict) -> bool:
        """
        Translate a key state dictionary into a movement command.

        Args:
            key_states: dict mapping key chars to bool
                        e.g. {"w": True, "s": False, "d": True, ...}

        Returns:
            True if any movement was sent, False if all keys released.
        """
        active_directions = [
            KEY_TO_DIRECTION[key]
            for key, pressed in key_states.items()
            if pressed and key in KEY_TO_DIRECTION
        ]

        if not active_directions:
            return False

        self.move(*active_directions)
        return True

    def stop(self):
        """Immediate neutral on all axes. No delay."""
        self._send(NEUTRAL)

    # =================================================================
    #  INTERNAL
    # =================================================================

    def _send(self, axes: dict):
        """Enqueue a set_motion command for the telemetry thread."""
        self._state.send_command(Command(
            name="set_motion",
            kwargs={
                "forward":  axes["x"] / 1000.0,
                "lateral":  axes["y"] / 1000.0,
                "throttle": (axes["z"] - 500) / 500.0,
                "yaw":      axes["r"] / 1000.0,
            }
        ))

    # =================================================================
    #  STATUS / DEBUG
    # =================================================================

    def get_status(self) -> dict:
        """Return current controller state for display/debug."""
        return {
            "speed": self._speed,
            "speed_percent": self.speed_percent,
            "profile": self._profile_name,
            "thruster_count": THRUSTER_COUNT,
        }

    def __repr__(self):
        return (f"MotionController(profile={self._profile_name!r}, "
                f"speed={self._speed}, "
                f"{self.speed_percent:.0f}%)")