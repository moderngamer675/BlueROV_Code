import threading, queue, time, copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional
from rov_config import LOG_QUEUE_MAXLEN


@dataclass
class TelemetryUpdate:
    key:   str
    value: Any
    color: Optional[str] = None


@dataclass
class Command:
    name:   str
    args:   tuple = ()
    kwargs: dict  = field(default_factory=dict)


class SharedState:
    def __init__(self):
        self._telem_lock = threading.Lock()
        self._telem_updates: list = []

        self._raw_telem_lock = threading.Lock()
        self._raw_telem = {
            "mode": "—", "armed": False,
            "battery_v": 0.0, "battery_a": 0.0,
            "heading": 0, "throttle": 0,
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "pressure": 0.0, "temp": 0.0,
            "servo": [1500] * 4,
        }

        self._frame_lock   = threading.Lock()
        self._video_frame  = None
        self._video_fps    = 0.0
        self._yolo_loaded  = False
        self._yolo_enabled = True

        self._logs: deque = deque(maxlen=LOG_QUEUE_MAXLEN)

        self._cmd_queue: queue.Queue = queue.Queue()

        self._sensor_lock = threading.Lock()
        self._sensor_data = {"dst_front": 0.0, "dst_left": 0.0, "dst_right": 0.0, "dst_back": 0.0}
        self._sensor_timestamps = {"dst_front": 0.0, "dst_left": 0.0, "dst_right": 0.0, "dst_back": 0.0}

        self._gamepad_lock         = threading.Lock()
        self._gamepad_connected    = False
        self._gamepad_input_active = False

        self._motor_lock       = threading.Lock()
        self._motor_states     = {"mot_a": False, "mot_b": False}
        self._motor_timestamps = {"mot_a": 0.0,   "mot_b": 0.0}

        self._motor_cmd_queue: queue.Queue = queue.Queue()

        self._detections_lock     = threading.Lock()
        self._latest_detections: list = []

    def put_telemetry_update(self, key, value, color=None):
        with self._telem_lock:
            self._telem_updates.append(TelemetryUpdate(key, value, color))

    def drain_telemetry_updates(self):
        with self._telem_lock:
            batch, self._telem_updates = self._telem_updates, []
            return batch

    def update_raw_telemetry(self, **kwargs):
        with self._raw_telem_lock:
            self._raw_telem.update(kwargs)

    def get_raw_telemetry(self):
        with self._raw_telem_lock:
            return dict(self._raw_telem)

    def set_video_frame(self, frame, fps=0.0):
        with self._frame_lock:
            self._video_frame = frame
            self._video_fps   = fps

    def get_video_frame(self):
        with self._frame_lock:
            return self._video_frame, self._video_fps

    def set_video_ai_status(self, loaded, enabled):
        with self._frame_lock:
            self._yolo_loaded  = loaded
            self._yolo_enabled = enabled

    def get_video_ai_status(self):
        with self._frame_lock:
            return self._yolo_loaded, self._yolo_enabled

    def log(self, message):
        self._logs.append(message)

    def drain_logs(self):
        batch = list(self._logs)
        self._logs.clear()
        return batch

    def send_command(self, cmd):
        self._cmd_queue.put(cmd)

    def poll_command(self):
        try:
            return self._cmd_queue.get_nowait()
        except queue.Empty:
            return None

    def update_sensor(self, name, value):
        with self._sensor_lock:
            if name in self._sensor_data:
                self._sensor_data[name]       = value
                self._sensor_timestamps[name] = time.time()

    def get_sensor_data(self):
        with self._sensor_lock:
            return dict(self._sensor_data)

    def is_sensor_stale(self, name, max_age_s=2.0):
        with self._sensor_lock:
            return (time.time() - self._sensor_timestamps.get(name, 0.0)) > max_age_s

    def set_gamepad_state(self, connected, input_active=False):
        with self._gamepad_lock:
            self._gamepad_connected    = connected
            self._gamepad_input_active = input_active

    def get_gamepad_state(self):
        with self._gamepad_lock:
            return self._gamepad_connected, self._gamepad_input_active

    def update_motor_state(self, name, is_on):
        with self._motor_lock:
            if name in self._motor_states:
                self._motor_states[name]     = bool(is_on)
                self._motor_timestamps[name] = time.time()

    def get_motor_states(self):
        with self._motor_lock:
            return dict(self._motor_states)

    def is_motor_stale(self, name, max_age_s=5.0):
        with self._motor_lock:
            return (time.time() - self._motor_timestamps.get(name, 0.0)) > max_age_s

    def send_motor_command(self, motor_name, turn_on):
        self._motor_cmd_queue.put((motor_name, turn_on))

    def poll_motor_command(self, timeout=0.1):
        try:
            return self._motor_cmd_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def set_latest_detections(self, detections):
        with self._detections_lock:
            self._latest_detections = list(detections)

    def get_latest_detections(self):
        with self._detections_lock:
            return list(self._latest_detections)