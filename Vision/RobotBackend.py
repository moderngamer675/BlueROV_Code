# Handles UDP video stream reception and YOLOv8 AI overlay
import threading, socket, time, numpy as np, cv2
from rov_config import LAPTOP_IP, VIDEO_PORT, FRAME_WIDTH, FRAME_HEIGHT, YOLO_MODEL, YOLO_CONFIDENCE, YOLO_ENABLED
from shared_state import SharedState

RECV_BUF_SIZE = 131072
FONT, DETECTION_COLOR = cv2.FONT_HERSHEY_SIMPLEX, (0, 200, 255)

class RobotLogic:
    def __init__(self, state: SharedState):
        self._state, self.running, self._thread = state, False, None
        self._stop = threading.Event()
        self._frame_count, self._fps, self._last_fps_t = 0, 0.0, time.time()
        self._yolo, self._yolo_loaded, self._yolo_enabled = None, False, YOLO_ENABLED

    def start(self):
        self._stop.clear()
        self.running = True
        self._state.set_video_ai_status(loaded=False, enabled=self._yolo_enabled)
        if self._yolo_enabled: threading.Thread(target=self._load_yolo, daemon=True).start()
        self._thread = threading.Thread(target=self._video_loop, daemon=True)
        self._thread.start()
        self._state.log("Video backend started.")

    def stop(self):
        self._state.log("Stopping video backend...")
        self._stop.set()
        self.running = False
        if self._thread: self._thread.join(timeout=3)

    def _load_yolo(self):
        try:
            from ultralytics import YOLO
            self._yolo, self._yolo_loaded = YOLO(YOLO_MODEL), True
            self._state.set_video_ai_status(loaded=True, enabled=True)
            self._state.log(" ✅ YOLO model loaded.")
        except Exception as e:
            self._state.log(f" ⚠️ YOLO load failed/disabled: {e}")
            self._yolo_enabled = False
            self._state.set_video_ai_status(loaded=False, enabled=False)

    def _video_loop(self):
        sock = self._create_socket()
        if not sock: return
        stream_started = False
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(RECV_BUF_SIZE)
                if not stream_started:
                    self._state.log(f" ✅ Video stream received from {addr[0]}")
                    stream_started = True
                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None: continue
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT), interpolation=cv2.INTER_LINEAR)
                frame = self._draw_hud(self._process_ai(frame))
                self._update_fps()
                self._state.set_video_frame(frame, self._fps)
            except socket.timeout:
                if stream_started: self._state.log(" ⚠️ Video stream timeout...")
                stream_started = False
            except Exception as e:
                if not self._stop.is_set(): self._state.log(f"Video error: {e}")
        sock.close()

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUF_SIZE)
        try:
            sock.bind(('0.0.0.0', VIDEO_PORT))
            sock.settimeout(2.0)
            return sock
        except OSError as e:
            self._state.log(f" ❌ Cannot bind video port {VIDEO_PORT}: {e}")
            self.running = False
            return None

    def _update_fps(self):
        self._frame_count += 1
        now = time.time()
        if now - self._last_fps_t >= 1.0:
            self._fps = self._frame_count / (now - self._last_fps_t)
            self._frame_count, self._last_fps_t = 0, now

    def _process_ai(self, frame):
        if not self._yolo_enabled: return frame
        if self._yolo_loaded: return self._run_yolo(frame)
        self._overlay_text(frame, "AI: Loading...", (10, 30), 0.6, DETECTION_COLOR, 2)
        return frame

    def _run_yolo(self, frame):
        try:
            for result in self._yolo(frame, conf=YOLO_CONFIDENCE, verbose=False):
                if result.boxes:
                    for box in result.boxes: self._draw_detection(frame, box, result.names)
        except Exception as e: self._overlay_text(frame, f"AI ERR: {str(e)[:30]}", (10, 60), 0.4, (0, 0, 255), 1)
        return frame

    def _draw_detection(self, frame, box, names):
        x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
        label_txt = f"{names.get(int(box.cls[0]), str(int(box.cls[0])))} {float(box.conf[0]):.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), DETECTION_COLOR, 2)
        (tw, th), _ = cv2.getTextSize(label_txt, FONT, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), DETECTION_COLOR, -1)
        cv2.putText(frame, label_txt, (x1 + 2, y1 - 4), FONT, 0.5, (0, 0, 0), 1)

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        self._overlay_text(frame, f"FPS: {self._fps:.1f}", (w - 100, 20), 0.5, (0, 255, 200))
        ai_txt, ai_col = ("AI: ON", (0, 200, 255)) if self._yolo_enabled and self._yolo_loaded else ("AI: LOADING", (0, 200, 100)) if self._yolo_enabled else ("AI: OFF", (100, 100, 100))
        self._overlay_text(frame, ai_txt, (10, 20), 0.5, ai_col)
        self._overlay_text(frame, time.strftime("%H:%M:%S"), (10, h - 10), 0.4, (150, 150, 150))
        return frame

    @staticmethod
    def _overlay_text(frame, text, pos, scale, color, thickness=1):
        cv2.putText(frame, text, pos, FONT, scale, color, thickness)