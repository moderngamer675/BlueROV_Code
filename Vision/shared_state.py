import threading, queue, time, copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional
from rov_config import LOG_QUEUE_MAXLEN

@dataclass
class TelemetryUpdate:
    key: str; value: Any; color: Optional[str] = None

@dataclass
class Command:
    name: str; args: tuple = (); kwargs: dict = field(default_factory=dict)

class SharedState:
    def __init__(self):
        self._telem_lock, self._raw_telem_lock, self._frame_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self._telem_updates: list[TelemetryUpdate] = []
        self._raw_telem: dict = {"mode": "—", "armed": False, "battery_v": 0.0, "battery_a": 0.0, 
                                 "heading": 0, "throttle": 0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0, 
                                 "pressure": 0.0, "temp": 0.0, "servo": [1500] * 4}
        self._video_frame, self._video_fps = None, 0.0
        self._yolo_loaded, self._yolo_enabled = False, True
        self._logs: deque = deque(maxlen=LOG_QUEUE_MAXLEN)
        self._cmd_queue: queue.Queue = queue.Queue()

        # ── Sensor data storage (all 4 sensors) ──
        self._sensor_lock = threading.Lock()
        self._sensor_data = {
            "dst_front": 0.0, "dst_left": 0.0, 
            "dst_right": 0.0, "dst_back": 0.0
        }
        self._sensor_timestamps = {
            "dst_front": 0.0, "dst_left": 0.0, 
            "dst_right": 0.0, "dst_back": 0.0
        }

        # ── Gamepad state ──
        self._gamepad_lock = threading.Lock()
        self._gamepad_connected = False
        self._gamepad_input_active = False

        # ── DC Motor states (from Arduino feedback) ──
        self._motor_lock = threading.Lock()
        self._motor_states = {"mot_a": False, "mot_b": False}
        self._motor_timestamps = {"mot_a": 0.0, "mot_b": 0.0}

        # ── DC Motor command queue (topside → Pi) ──
        self._motor_cmd_queue: queue.Queue = queue.Queue()

    # ── Telemetry methods (unchanged) ──

    def put_telemetry_update(self, key: str, value: Any, color: Optional[str] = None):
        with self._telem_lock: self._telem_updates.append(TelemetryUpdate(key, value, color))

    def drain_telemetry_updates(self) -> list[TelemetryUpdate]:
        with self._telem_lock:
            batch, self._telem_updates = self._telem_updates, []
            return batch

    def update_raw_telemetry(self, **kwargs):
        with self._raw_telem_lock: self._raw_telem.update(kwargs)

    def get_raw_telemetry(self) -> dict:
        with self._raw_telem_lock: return dict(self._raw_telem)

    # ── Video methods (unchanged) ──

    def set_video_frame(self, frame, fps: float = 0.0):
        with self._frame_lock: self._video_frame, self._video_fps = frame, fps

    def get_video_frame(self):
        with self._frame_lock: return self._video_frame, self._video_fps

    def set_video_ai_status(self, loaded: bool, enabled: bool):
        with self._frame_lock: self._yolo_loaded, self._yolo_enabled = loaded, enabled

    def get_video_ai_status(self) -> tuple[bool, bool]:
        with self._frame_lock: return self._yolo_loaded, self._yolo_enabled

    # ── Log methods (unchanged) ──

    def log(self, message: str):
        self._logs.append(message)

    def drain_logs(self) -> list[str]:
        batch = list(self._logs)
        self._logs.clear()
        return batch

    # ── MAVLink command queue (unchanged) ──

    def send_command(self, cmd: Command):
        self._cmd_queue.put(cmd)

    def poll_command(self) -> Optional[Command]:
        try: return self._cmd_queue.get_nowait()
        except queue.Empty: return None

    # ── Sensor methods (now includes dst_back) ──

    def update_sensor(self, name: str, value: float):
        """Called by sensor listener thread when new reading arrives."""
        with self._sensor_lock:
            if name in self._sensor_data:
                self._sensor_data[name] = value
                self._sensor_timestamps[name] = time.time()

    def get_sensor_data(self) -> dict:
        """Returns snapshot of all sensor readings."""
        with self._sensor_lock:
            return dict(self._sensor_data)

    def is_sensor_stale(self, name: str, max_age_s: float = 2.0) -> bool:
        """Check if a sensor reading is too old to trust."""
        with self._sensor_lock:
            age = time.time() - self._sensor_timestamps.get(name, 0)
            return age > max_age_s

    # ── Gamepad state methods (unchanged) ──

    def set_gamepad_state(self, connected: bool, input_active: bool = False):
        with self._gamepad_lock:
            self._gamepad_connected = connected
            self._gamepad_input_active = input_active

    def get_gamepad_state(self) -> tuple:
        with self._gamepad_lock:
            return self._gamepad_connected, self._gamepad_input_active

    # ── DC Motor state methods (NEW) ──

    def update_motor_state(self, name: str, is_on: bool):
        """Called by SensorListenerThread when mot_a/mot_b status arrives."""
        with self._motor_lock:
            if name in self._motor_states:
                self._motor_states[name] = bool(is_on)
                self._motor_timestamps[name] = time.time()

    def get_motor_states(self) -> dict:
        """Returns snapshot {mot_a: True/False, mot_b: True/False}."""
        with self._motor_lock:
            return dict(self._motor_states)

    def is_motor_stale(self, name: str, max_age_s: float = 5.0) -> bool:
        """Check if motor status feedback is stale."""
        with self._motor_lock:
            ts = self._motor_timestamps.get(name, 0.0)
            return (time.time() - ts) > max_age_s

    # ── DC Motor command methods (NEW) ──

    def send_motor_command(self, motor_name: str, turn_on: bool):
        """
        Enqueue a motor command for MotorCommandThread.
        motor_name: 'mot_a', 'mot_b', or 'mot_all'
        turn_on: True=ON, False=OFF
        """
        self._motor_cmd_queue.put((motor_name, turn_on))

    def poll_motor_command(self, timeout: float = 0.1):
        """Dequeue a motor command. Returns (name, turn_on) or None."""
        try:
            return self._motor_cmd_queue.get(timeout=timeout)
        except queue.Empty:
            return None