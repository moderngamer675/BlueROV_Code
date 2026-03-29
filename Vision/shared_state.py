# shared_state.py
# Thread-safe bridge between background threads and the tkinter main loop.
#
# DESIGN:
#   - Background threads WRITE individual fields (with lock).
#   - The GUI main loop READS a frozen snapshot every ~16ms (with lock).
#   - A dirty flag lets the GUI skip widget updates when nothing changed.
#   - Log messages are buffered in a lock-free deque (thread-safe by design).
#   - Commands from the GUI are enqueued for the telemetry thread to dequeue.

import threading
import queue
import copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from rov_config import LOG_QUEUE_MAXLEN


# ─── Telemetry display update ────────────────────────────────────────────────
# Each update the telemetry thread wants to push to the GUI is stored here.
# The GUI reads and clears the pending list each poll cycle.

@dataclass
class TelemetryUpdate:
    """A single telemetry display update destined for the GUI."""
    key: str
    value: Any
    color: Optional[str] = None


# ─── Command sent from GUI → telemetry thread ────────────────────────────────

@dataclass
class Command:
    """A command from the GUI to be executed on the telemetry thread."""
    name: str                       # e.g. "arm", "disarm", "set_motion", "set_mode", "stop_motors"
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


class SharedState:
    """
    Centralised, lock-protected state shared between threads.

    Write side  (background threads):
        state.put_telemetry_update("BATTERY", "16.2", "#00E676")
        state.set_video_frame(frame)
        state.log("message")

    Read side  (GUI main loop, every ~16ms):
        updates = state.drain_telemetry_updates()
        frame   = state.get_video_frame()
        logs    = state.drain_logs()

    Command channel (GUI → telemetry):
        state.send_command(Command("arm"))
        cmd = state.poll_command()       # non-blocking
    """

    def __init__(self):
        # ── Telemetry display updates (Telemetry thread → GUI) ───────────
        self._telem_lock = threading.Lock()
        self._telem_updates: list[TelemetryUpdate] = []

        # ── Raw telemetry dict (for get_telemetry() snapshots) ───────────
        self._raw_telem_lock = threading.Lock()
        self._raw_telem: dict = {
            "mode": "—", "armed": False,
            "battery_v": 0.0, "battery_a": 0.0,
            "depth": 0.0, "heading": 0, "throttle": 0,
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "pressure": 0.0, "temp": 0.0,
            # In SharedState.__init__, change:
            "servo": [1500] * 4,    # was [1500] * 6
        }

        # ── Video frame (Video thread → GUI) ────────────────────────────
        self._frame_lock = threading.Lock()
        self._video_frame = None          # latest numpy frame (BGR)
        self._video_fps: float = 0.0
        self._yolo_loaded: bool = False
        self._yolo_enabled: bool = True

        # ── Log messages (any thread → GUI) ─────────────────────────────
        #    collections.deque is thread-safe for append/popleft in CPython.
        self._logs: deque = deque(maxlen=LOG_QUEUE_MAXLEN)

        # ── Command queue (GUI → Telemetry thread) ──────────────────────
        self._cmd_queue: queue.Queue = queue.Queue()

    # =====================================================================
    #  TELEMETRY DISPLAY UPDATES  (write: telemetry thread, read: GUI)
    # =====================================================================

    def put_telemetry_update(self, key: str, value: Any,
                             color: Optional[str] = None):
        """Enqueue a display update. Called from the telemetry thread."""
        with self._telem_lock:
            self._telem_updates.append(
                TelemetryUpdate(key=key, value=value, color=color))

    def drain_telemetry_updates(self) -> list[TelemetryUpdate]:
        """Return and clear all pending updates. Called from the GUI thread."""
        with self._telem_lock:
            batch = self._telem_updates
            self._telem_updates = []
        return batch

    # =====================================================================
    #  RAW TELEMETRY DICT  (write: telemetry thread, read: anyone)
    # =====================================================================

    def update_raw_telemetry(self, **kwargs):
        """Merge fields into the raw telemetry dict."""
        with self._raw_telem_lock:
            self._raw_telem.update(kwargs)

    def get_raw_telemetry(self) -> dict:
        """Return a shallow copy of the raw telemetry dict."""
        with self._raw_telem_lock:
            return dict(self._raw_telem)

    # =====================================================================
    #  VIDEO FRAME  (write: video thread, read: GUI)
    # =====================================================================

    def set_video_frame(self, frame, fps: float = 0.0):
        """Store the latest decoded video frame."""
        with self._frame_lock:
            self._video_frame = frame
            self._video_fps = fps

    def get_video_frame(self):
        """Return (frame_or_None, fps). GUI thread only."""
        with self._frame_lock:
            return self._video_frame, self._video_fps

    def set_video_ai_status(self, loaded: bool, enabled: bool):
        """Update AI/YOLO status flags from the video thread."""
        with self._frame_lock:
            self._yolo_loaded = loaded
            self._yolo_enabled = enabled

    def get_video_ai_status(self) -> tuple[bool, bool]:
        """Return (yolo_loaded, yolo_enabled). GUI thread only."""
        with self._frame_lock:
            return self._yolo_loaded, self._yolo_enabled

    # =====================================================================
    #  LOG MESSAGES  (write: any thread, read: GUI)
    # =====================================================================

    def log(self, message: str):
        """Append a log message from any thread."""
        self._logs.append(message)

    def drain_logs(self) -> list[str]:
        """Return and clear all pending log messages. GUI thread only."""
        batch = []
        try:
            while True:
                batch.append(self._logs.popleft())
        except IndexError:
            pass
        return batch

    # =====================================================================
    #  COMMAND QUEUE  (write: GUI, read: telemetry thread)
    # =====================================================================

    def send_command(self, cmd: Command):
        """Enqueue a command for the telemetry thread."""
        self._cmd_queue.put(cmd)

    def poll_command(self) -> Optional[Command]:
        """Non-blocking dequeue. Returns None if empty."""
        try:
            return self._cmd_queue.get_nowait()
        except queue.Empty:
            return None