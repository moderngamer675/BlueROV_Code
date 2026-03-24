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


class RobotLogic:

    def __init__(self, log_callback):
        self._log          = log_callback
        self.running       = False
        self.latest_frame  = None
        self._thread       = None
        self._stop         = threading.Event()
        self._frame_count  = 0
        self._fps          = 0.0
        self._last_fps_t   = time.time()

        # YOLO
        self._yolo         = None
        self._yolo_enabled = YOLO_ENABLED
        self._yolo_loaded  = False

    # =========================================================================
    #  START / STOP
    # =========================================================================
    def start(self):
        self._stop.clear()
        self.running = True

        # Load YOLO in background so GUI doesn't freeze
        if self._yolo_enabled:
            threading.Thread(
                target=self._load_yolo,
                daemon=True,
                name="YOLOLoader"
            ).start()

        self._thread = threading.Thread(
            target=self._video_loop,
            daemon=True,
            name="VideoThread"
        )
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
            self._log(f"✅ YOLO model loaded.")
        except ImportError:
            self._log("⚠️  ultralytics not installed — YOLO disabled")
            self._log("    pip install ultralytics")
            self._yolo_enabled = False
        except Exception as e:
            self._log(f"⚠️  YOLO load failed: {e}")
            self._yolo_enabled = False

    # =========================================================================
    #  VIDEO RECEIVE LOOP
    # =========================================================================
    def _video_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_RCVBUF, 131072
        )
        try:
            sock.bind(('0.0.0.0', VIDEO_PORT))
            self._log(f"Video socket bound on port {VIDEO_PORT}")
        except OSError as e:
            self._log(f"❌ Cannot bind video port {VIDEO_PORT}: {e}")
            self._log("    Is another app using this port?")
            self.running = False
            return

        sock.settimeout(2.0)
        self._log(f"Waiting for video stream from Pi...")

        stream_started = False

        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(131072)

                if not stream_started:
                    self._log(f"✅ Video stream received from {addr[0]}")
                    stream_started = True

                # Decode JPEG
                frame = cv2.imdecode(
                    np.frombuffer(data, np.uint8),
                    cv2.IMREAD_COLOR
                )

                if frame is None:
                    continue

                # Resize to standard dimensions
                frame = cv2.resize(
                    frame,
                    (FRAME_WIDTH, FRAME_HEIGHT),
                    interpolation=cv2.INTER_LINEAR
                )

                # Run YOLO if loaded
                if self._yolo_enabled and self._yolo_loaded:
                    frame = self._run_yolo(frame)
                elif self._yolo_enabled and not self._yolo_loaded:
                    # Show loading overlay
                    cv2.putText(
                        frame, "AI: Loading...",
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 200, 255), 2
                    )

                # Add HUD overlay
                frame = self._draw_hud(frame)

                # Update latest frame
                self.latest_frame = frame
                self._frame_count += 1

                # Calculate FPS
                now = time.time()
                if now - self._last_fps_t >= 1.0:
                    self._fps = self._frame_count / (
                        now - self._last_fps_t
                    )
                    self._frame_count = 0
                    self._last_fps_t  = now

            except socket.timeout:
                if stream_started:
                    self._log("⚠️  Video stream timeout — waiting...")
                    stream_started = False
                continue
            except Exception as e:
                if not self._stop.is_set():
                    self._log(f"Video error: {e}")
                continue

        sock.close()
        self._log("Video socket closed.")

    # =========================================================================
    #  YOLO INFERENCE
    # =========================================================================
    def _run_yolo(self, frame: np.ndarray) -> np.ndarray:
        """
        Run YOLOv8 inference and draw bounding boxes.
        Returns frame with detections drawn.
        """
        try:
            results = self._yolo(
                frame,
                conf=YOLO_CONFIDENCE,
                verbose=False
            )

            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue

                for box in boxes:
                    # Bounding box coords
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    x1, y1 = int(x1), int(y1)
                    x2, y2 = int(x2), int(y2)

                    conf  = float(box.conf[0])
                    cls   = int(box.cls[0])
                    label = result.names.get(cls, str(cls))

                    # Draw box
                    cv2.rectangle(
                        frame, (x1, y1), (x2, y2),
                        (0, 200, 255), 2
                    )

                    # Label background
                    label_txt = f"{label} {conf:.2f}"
                    (tw, th), _ = cv2.getTextSize(
                        label_txt,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, 1
                    )
                    cv2.rectangle(
                        frame,
                        (x1, y1 - th - 8),
                        (x1 + tw + 4, y1),
                        (0, 200, 255), -1
                    )
                    cv2.putText(
                        frame, label_txt,
                        (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 0), 1
                    )

        except Exception as e:
            # Don't crash on YOLO errors
            cv2.putText(
                frame, f"AI ERR: {str(e)[:30]}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4, (0, 0, 255), 1
            )

        return frame

    # =========================================================================
    #  HUD OVERLAY
    # =========================================================================
    def _draw_hud(self, frame: np.ndarray) -> np.ndarray:
        """Draw minimal HUD info on the video frame."""
        h, w = frame.shape[:2]

        # FPS counter top-right
        fps_txt = f"FPS: {self._fps:.1f}"
        cv2.putText(
            frame, fps_txt,
            (w - 100, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5, (0, 255, 200), 1
        )

        # AI status top-left
        if self._yolo_enabled and self._yolo_loaded:
            ai_txt = "AI: ON"
            ai_col = (0, 200, 255)
        elif self._yolo_enabled:
            ai_txt = "AI: LOADING"
            ai_col = (0, 200, 100)
        else:
            ai_txt = "AI: OFF"
            ai_col = (100, 100, 100)

        cv2.putText(
            frame, ai_txt,
            (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5, ai_col, 1
        )

        # Timestamp bottom-left
        ts = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, ts,
            (10, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4, (150, 150, 150), 1
        )

        return frame