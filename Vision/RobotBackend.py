# RobotBackend.py
# Handles video stream reception and YOLOv8 AI overlay
# Receives JPEG frames via UDP from camera_stream.py on Pi

import threading
import socket
import time
import numpy as np
import cv2

from rov_config import (
    LAPTOP_IP, VIDEO_PORT,
    FRAME_WIDTH, FRAME_HEIGHT,
    YOLO_MODEL, YOLO_CONFIDENCE, YOLO_ENABLED
)

RECV_BUF_SIZE = 131072
FONT = cv2.FONT_HERSHEY_SIMPLEX
DETECTION_COLOR = (0, 200, 255)


class RobotLogic:

    def __init__(self, log_callback):
        self._log = log_callback
        self.running = False
        self.latest_frame = None
        self._thread = None
        self._stop = threading.Event()
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_t = time.time()

        self._yolo = None
        self._yolo_enabled = YOLO_ENABLED
        self._yolo_loaded = False

    # =========================================================================
    #  START / STOP
    # =========================================================================

    def start(self):
        self._stop.clear()
        self.running = True

        if self._yolo_enabled:
            threading.Thread(target=self._load_yolo, daemon=True,
                             name="YOLOLoader").start()

        self._thread = threading.Thread(target=self._video_loop, daemon=True,
                                        name="VideoThread")
        self._thread.start()
        self._log("Video backend started.")

    def stop(self):
        self._log("Stopping video backend...")
        self._stop.set()
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)
        self._log("Video backend stopped.")

    # =========================================================================
    #  YOLO LOADER
    # =========================================================================

    def _load_yolo(self):
        try:
            self._log(f"Loading YOLO model: {YOLO_MODEL}...")
            from ultralytics import YOLO
            self._yolo = YOLO(YOLO_MODEL)
            self._yolo_loaded = True
            self._log("✅ YOLO model loaded.")
        except ImportError:
            self._log("⚠️  ultralytics not installed — YOLO disabled")
            self._yolo_enabled = False
        except Exception as e:
            self._log(f"⚠️  YOLO load failed: {e}")
            self._yolo_enabled = False

    # =========================================================================
    #  VIDEO RECEIVE LOOP
    # =========================================================================

    def _video_loop(self):
        sock = self._create_socket()
        if sock is None:
            return

        self._log("Waiting for video stream from Pi...")
        stream_started = False

        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(RECV_BUF_SIZE)

                if not stream_started:
                    self._log(f"✅ Video stream received from {addr[0]}")
                    stream_started = True

                frame = cv2.imdecode(
                    np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT),
                                   interpolation=cv2.INTER_LINEAR)
                frame = self._process_ai(frame)
                frame = self._draw_hud(frame)

                self.latest_frame = frame
                self._update_fps()

            except socket.timeout:
                if stream_started:
                    self._log("⚠️  Video stream timeout — waiting...")
                    stream_started = False
            except Exception as e:
                if not self._stop.is_set():
                    self._log(f"Video error: {e}")

        sock.close()
        self._log("Video socket closed.")

    def _create_socket(self):
        """Create and bind the UDP receive socket."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUF_SIZE)
        try:
            sock.bind(('0.0.0.0', VIDEO_PORT))
            self._log(f"Video socket bound on port {VIDEO_PORT}")
        except OSError as e:
            self._log(f"❌ Cannot bind video port {VIDEO_PORT}: {e}")
            self._log("    Is another app using this port?")
            self.running = False
            return None
        sock.settimeout(2.0)
        return sock

    def _update_fps(self):
        """Increment frame count and recalculate FPS each second."""
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._last_fps_t
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._last_fps_t = now

    # =========================================================================
    #  AI PROCESSING
    # =========================================================================

    def _process_ai(self, frame):
        """Run YOLO or show loading overlay if still initializing."""
        if not self._yolo_enabled:
            return frame
        if self._yolo_loaded:
            return self._run_yolo(frame)
        self._overlay_text(frame, "AI: Loading...", (10, 30),
                           0.6, DETECTION_COLOR, 2)
        return frame

    def _run_yolo(self, frame):
        """Run YOLOv8 inference and draw bounding boxes."""
        try:
            results = self._yolo(frame, conf=YOLO_CONFIDENCE, verbose=False)
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    self._draw_detection(frame, box, result.names)
        except Exception as e:
            self._overlay_text(frame, f"AI ERR: {str(e)[:30]}",
                               (10, 60), 0.4, (0, 0, 255), 1)
        return frame

    def _draw_detection(self, frame, box, names):
        """Draw a single detection box with label."""
        x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
        conf = float(box.conf[0])
        label = names.get(int(box.cls[0]), str(int(box.cls[0])))
        label_txt = f"{label} {conf:.2f}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), DETECTION_COLOR, 2)

        (tw, th), _ = cv2.getTextSize(label_txt, FONT, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8),
                      (x1 + tw + 4, y1), DETECTION_COLOR, -1)
        cv2.putText(frame, label_txt, (x1 + 2, y1 - 4),
                    FONT, 0.5, (0, 0, 0), 1)

    # =========================================================================
    #  HUD OVERLAY
    # =========================================================================

    def _draw_hud(self, frame):
        """Draw minimal HUD info on the video frame."""
        h, w = frame.shape[:2]

        # FPS — top right
        self._overlay_text(frame, f"FPS: {self._fps:.1f}",
                           (w - 100, 20), 0.5, (0, 255, 200))

        # AI status — top left
        if self._yolo_enabled and self._yolo_loaded:
            txt, col = "AI: ON", (0, 200, 255)
        elif self._yolo_enabled:
            txt, col = "AI: LOADING", (0, 200, 100)
        else:
            txt, col = "AI: OFF", (100, 100, 100)
        self._overlay_text(frame, txt, (10, 20), 0.5, col)

        # Timestamp — bottom left
        self._overlay_text(frame, time.strftime("%H:%M:%S"),
                           (10, h - 10), 0.4, (150, 150, 150))

        return frame

    @staticmethod
    def _overlay_text(frame, text, pos, scale, color, thickness=1):
        """Shorthand for cv2.putText with consistent font."""
        cv2.putText(frame, text, pos, FONT, scale, color, thickness)