import threading, time, random
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from rov_config import (
    AVOID_FRONT_CRITICAL_CM, AVOID_FRONT_WARNING_CM, AVOID_SIDE_CRITICAL_CM,
    WANDER_FORWARD_SECS, WANDER_TURN_SECS, WANDER_REVERSE_SECS,
    WALL_TARGET_CM, WALL_MIN_CM, WALL_MAX_CM,
    CORRIDOR_TARGET_CM, CORRIDOR_TOLERANCE_CM, CORRIDOR_MAX_YAW,
    AUTO_DEFAULT_SPEED, AUTO_LOOP_HZ, AUTO_SENSOR_STALE_S, AUTO_SLOWDOWN_SPEED,
    FRAME_WIDTH, FRAME_HEIGHT,
)
from shared_state import SharedState, Command
from motor_controller import MotionController, SPEED_PROFILES


class AutonomousMode(Enum):
    OFF               = "OFF"
    WANDER            = "WANDER"
    WALL_FOLLOW_LEFT  = "WALL LEFT"
    WALL_FOLLOW_RIGHT = "WALL RIGHT"
    CORRIDOR          = "CORRIDOR"
    OBJECT_TRACK      = "OBJ TRACK"


AUTO_MODE_LABELS = [m.value for m in AutonomousMode]


@dataclass
class _Motion:
    x: float = 0.0
    y: float = 0.0
    r: float = 0.0

    def clamp(self):
        self.x = max(-1.0, min(1.0, self.x))
        self.y = max(-1.0, min(1.0, self.y))
        self.r = max(-1.0, min(1.0, self.r))
        return self


@dataclass
class AutoStatus:
    mode:        str  = "OFF"
    active:      bool = False
    speed:       str  = AUTO_DEFAULT_SPEED
    state_label: str  = "IDLE"
    warning:     str  = ""
    sensors_ok:  bool = True


class AutonomousController(threading.Thread):
    _OVERRIDE_HOLDOFF_S = 2.0

    def __init__(self, shared_state: SharedState, motion_controller: MotionController):
        super().__init__(daemon=True, name="AutonomousController")
        self._state  = shared_state
        self._motion = motion_controller
        self._mode      = AutonomousMode.OFF
        self._mode_lock = threading.Lock()
        self._auto_speed = AUTO_DEFAULT_SPEED
        self._last_active_mode = AutonomousMode.WANDER
        self._status      = AutoStatus()
        self._status_lock = threading.Lock()
        self._stop_event  = threading.Event()
        self._mode_state: dict = {}
        self._last_override_t  = 0.0

    def set_mode(self, mode: AutonomousMode):
        with self._mode_lock:
            if mode == self._mode:
                return
            old        = self._mode
            self._mode = mode
            self._mode_state = {}
        if mode == AutonomousMode.OFF:
            self._send_stop()
            self._state.log(f"[AUTO] Mode OFF (was {old.value})")
        else:
            self._last_active_mode = mode
            self._state.log(f"[AUTO] Mode → {mode.value}")
        self._update_status(
            mode=mode.value,
            active=(mode != AutonomousMode.OFF),
            state_label="STARTING" if mode != AutonomousMode.OFF else "IDLE",
            warning="",
        )

    def get_mode(self):
        with self._mode_lock:
            return self._mode

    def set_speed(self, profile_name):
        if profile_name in SPEED_PROFILES:
            self._auto_speed = profile_name
            self._update_status(speed=profile_name)

    def get_status(self):
        with self._status_lock:
            return AutoStatus(
                mode=self._status.mode, active=self._status.active,
                speed=self._status.speed, state_label=self._status.state_label,
                warning=self._status.warning, sensors_ok=self._status.sensors_ok,
            )

    def notify_user_override(self):
        self._last_override_t = time.time()

    def stop(self):
        self._stop_event.set()

    def run(self):
        self._state.log("[AUTO] Controller thread started")
        interval = 1.0 / AUTO_LOOP_HZ
        while not self._stop_event.is_set():
            t_start = time.time()
            with self._mode_lock:
                current_mode = self._mode
            if current_mode != AutonomousMode.OFF:
                if (time.time() - self._last_override_t) < self._OVERRIDE_HOLDOFF_S:
                    self._update_status(state_label="USER OVERRIDE")
                else:
                    self._tick(current_mode)
            time.sleep(max(0.0, interval - (time.time() - t_start)))
        self._send_stop()
        self._state.log("[AUTO] Controller thread stopped")

    def _tick(self, mode):
        sensors = self._state.get_sensor_data()
        stale   = self._check_sensor_health(sensors)
        self._motion.set_speed_profile(AUTO_SLOWDOWN_SPEED if stale else self._auto_speed)

        dispatch = {
            AutonomousMode.WANDER:            lambda: self._run_wander(sensors),
            AutonomousMode.WALL_FOLLOW_LEFT:  lambda: self._run_wall_follow(sensors, "left"),
            AutonomousMode.WALL_FOLLOW_RIGHT: lambda: self._run_wall_follow(sensors, "right"),
            AutonomousMode.CORRIDOR:          lambda: self._run_corridor(sensors),
            AutonomousMode.OBJECT_TRACK:      lambda: self._run_object_track(sensors),
        }
        intention = dispatch.get(mode, lambda: _Motion())()
        intention = self._apply_emergency_avoid(intention, sensors)
        self._send_motion(intention)

    def _check_sensor_health(self, sensors):
        stale = [
            n.replace("dst_", "").upper()
            for n in ("dst_front", "dst_left", "dst_right", "dst_back")
            if self._state.is_sensor_stale(n, AUTO_SENSOR_STALE_S) or sensors.get(n, 0.0) <= 0.0
        ]
        if stale:
            self._update_status(warning=f"⚠ NO DATA: {', '.join(stale)}", sensors_ok=False)
            return True
        self._update_status(warning="", sensors_ok=True)
        return False

    def _apply_emergency_avoid(self, intention, sensors):
        def _safe(k):
            v = sensors.get(k, 0.0)
            return 9999.0 if v <= 0 else v

        front = _safe("dst_front")
        left  = _safe("dst_left")
        right = _safe("dst_right")
        back  = _safe("dst_back")
        m = _Motion(x=intention.x, y=intention.y, r=intention.r)

        if left < AVOID_SIDE_CRITICAL_CM:
            m.r = 0.7; m.x *= 0.2
        if right < AVOID_SIDE_CRITICAL_CM:
            m.r = -0.7; m.x *= 0.2

        if front < AVOID_FRONT_CRITICAL_CM and m.x > 0:
            m.x = -0.4; m.y = 0.0; m.r = 0.0
            self._update_status(state_label="AVOID: REVERSE")
        elif front < AVOID_FRONT_WARNING_CM and m.x > 0:
            scale = (front - AVOID_FRONT_CRITICAL_CM) / (AVOID_FRONT_WARNING_CM - AVOID_FRONT_CRITICAL_CM)
            m.x *= max(0.1, scale)
            self._update_status(state_label=f"AVOID: SLOW ({front:.0f}cm)")

        if back < AVOID_SIDE_CRITICAL_CM and m.x < 0:
            m.x = 0.0

        return m.clamp()

    def _run_wander(self, sensors):
        ms = self._mode_state
        if not ms:
            ms.update({"phase": "FORWARD", "phase_end": time.time() + WANDER_FORWARD_SECS,
                       "turn_dir": random.choice([-1.0, 1.0])})

        now   = time.time()
        front = sensors.get("dst_front", 0.0) or 9999.0
        phase = ms["phase"]

        if phase == "FORWARD":
            if 0 < front < AVOID_FRONT_WARNING_CM:
                ms.update({"phase": "REVERSE", "phase_end": now + WANDER_REVERSE_SECS,
                           "turn_dir": random.choice([-1.0, 1.0])})
                self._update_status(state_label="WANDER: REVERSE")
                return _Motion(x=-0.5)
            if now >= ms["phase_end"]:
                ms.update({"phase": "TURN", "phase_end": now + WANDER_TURN_SECS,
                           "turn_dir": random.choice([-1.0, 1.0])})
                self._update_status(state_label="WANDER: TURNING")
                return _Motion(r=ms["turn_dir"] * 0.6)
            self._update_status(state_label=f"WANDER: FWD ({front:.0f}cm)")
            return _Motion(x=0.6)

        elif phase == "TURN":
            if now >= ms["phase_end"]:
                ms.update({"phase": "FORWARD", "phase_end": now + WANDER_FORWARD_SECS})
                self._update_status(state_label="WANDER: FORWARD")
                return _Motion(x=0.6)
            return _Motion(r=ms["turn_dir"] * 0.6)

        elif phase == "REVERSE":
            if now >= ms["phase_end"]:
                ms.update({"phase": "TURN", "phase_end": now + WANDER_TURN_SECS})
                self._update_status(state_label="WANDER: TURNING")
                return _Motion(r=ms["turn_dir"] * 0.6)
            return _Motion(x=-0.5)

        return _Motion()

    def _run_wall_follow(self, sensors, side):
        dist = sensors.get(f"dst_{side}", 0.0)
        if dist <= 0:
            self._update_status(state_label=f"WALL {side.upper()}: NO SENSOR")
            return _Motion(x=0.4)

        error  = dist - WALL_TARGET_CM
        p_gain = 1.0 / max(1.0, WALL_MAX_CM - WALL_MIN_CM)
        yaw    = max(-CORRIDOR_MAX_YAW, min(CORRIDOR_MAX_YAW, error * p_gain))
        yaw_out = -yaw if side == "left" else yaw
        proximity = "CLOSE" if dist < WALL_MIN_CM else "FAR" if dist > WALL_MAX_CM else "OK"
        self._update_status(state_label=f"WALL {side.upper()}: {dist:.0f}cm [{proximity}]")
        return _Motion(x=0.5, r=yaw_out).clamp()

    def _run_corridor(self, sensors):
        left  = sensors.get("dst_left",  0.0)
        right = sensors.get("dst_right", 0.0)

        if left <= 0 and right <= 0:
            self._update_status(state_label="CORRIDOR: NO SENSORS", warning="⚠ Both sensors missing")
            return _Motion(x=0.3)
        if left <= 0:
            self._update_status(state_label="CORRIDOR: LEFT MISSING")
            return _Motion(x=0.3, r=-0.3)
        if right <= 0:
            self._update_status(state_label="CORRIDOR: RIGHT MISSING")
            return _Motion(x=0.3, r=0.3)

        error = right - left
        if abs(error) < CORRIDOR_TOLERANCE_CM:
            self._update_status(state_label=f"CORRIDOR: CENTRED  L{left:.0f} R{right:.0f}")
            return _Motion(x=0.5)

        p_gain  = CORRIDOR_MAX_YAW / max(1.0, CORRIDOR_TARGET_CM + CORRIDOR_TOLERANCE_CM)
        yaw_out = max(-CORRIDOR_MAX_YAW, min(CORRIDOR_MAX_YAW, error * p_gain))
        self._update_status(state_label=f"CORRIDOR: {'→R' if error > 0 else '←L'}  L{left:.0f} R{right:.0f}")
        return _Motion(x=0.5, r=yaw_out).clamp()

    def _run_object_track(self, sensors):
        detections = self._state.get_latest_detections()
        if not detections:
            self._update_status(state_label="OBJ TRACK: SEARCHING")
            return _Motion()

        def _area(d):
            x1, y1, x2, y2 = d["bbox"]
            return (x2 - x1) * (y2 - y1)

        target = max(detections, key=_area)
        x1, y1, x2, y2 = target["bbox"]
        h_error   = ((x1 + x2) / 2.0 - FRAME_WIDTH / 2.0) / (FRAME_WIDTH / 2.0)
        area_frac = _area(target) / (FRAME_WIDTH * FRAME_HEIGHT)
        fwd = max(0.0, 1.0 - (area_frac / 0.25)) * 0.5
        yaw = max(-0.8, min(0.8, h_error * 0.7))
        self._update_status(state_label=f"OBJ: {target.get('label','?')}({target.get('conf',0):.0%}) yaw={yaw:+.2f}")
        return _Motion(x=fwd, r=yaw).clamp()

    def _send_motion(self, m):
        self._state.send_command(Command(name="set_motion", kwargs={
            "forward": m.x, "lateral": m.y, "throttle": 0.0, "yaw": m.r,
        }))

    def _send_stop(self):
        self._state.send_command(Command(name="stop_motors"))

    def _update_status(self, **kwargs):
        with self._status_lock:
            for k, v in kwargs.items():
                if hasattr(self._status, k):
                    setattr(self._status, k, v)
            with self._mode_lock:
                self._status.mode   = self._mode.value
                self._status.active = (self._mode != AutonomousMode.OFF)