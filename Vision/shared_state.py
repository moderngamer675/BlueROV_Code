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

        # ── NEW: Sensor data storage ──
        self._sensor_lock = threading.Lock()
        self._sensor_data = {"dst_front": 0.0, "dst_left": 0.0, "dst_right": 0.0}
        self._sensor_timestamps = {"dst_front": 0.0, "dst_left": 0.0, "dst_right": 0.0}

        # ── NEW: Gamepad state ──
        self._gamepad_lock = threading.Lock()
        self._gamepad_connected = False
        self._gamepad_input_active = False

    # ── Existing methods (unchanged) ──

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

    def set_video_frame(self, frame, fps: float = 0.0):
        with self._frame_lock: self._video_frame, self._video_fps = frame, fps

    def get_video_frame(self):
        with self._frame_lock: return self._video_frame, self._video_fps

    def set_video_ai_status(self, loaded: bool, enabled: bool):
        with self._frame_lock: self._yolo_loaded, self._yolo_enabled = loaded, enabled

    def get_video_ai_status(self) -> tuple[bool, bool]:
        with self._frame_lock: return self._yolo_loaded, self._yolo_enabled

    def log(self, message: str):
        self._logs.append(message)

    def drain_logs(self) -> list[str]:
        batch = list(self._logs)
        self._logs.clear()
        return batch

    def send_command(self, cmd: Command):
        self._cmd_queue.put(cmd)

    def poll_command(self) -> Optional[Command]:
        try: return self._cmd_queue.get_nowait()
        except queue.Empty: return None

    # ── NEW: Sensor methods ──

    def update_sensor(self, name: str, value: float):
        """Called by sensor listener thread when new reading arrives."""
        with self._sensor_lock:
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

    # ── NEW: Gamepad state methods ──

    def set_gamepad_state(self, connected: bool, input_active: bool = False):
        with self._gamepad_lock:
            self._gamepad_connected = connected
            self._gamepad_input_active = input_active

    def get_gamepad_state(self) -> tuple:
        with self._gamepad_lock:
            return self._gamepad_connected, self._gamepad_input_active