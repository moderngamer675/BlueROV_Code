import threading, socket, time, numpy as np, cv2
from rov_config import VIDEO_PORT, YOLO_MODEL, YOLO_CONFIDENCE, YOLO_ENABLED, FRAME_WIDTH, FRAME_HEIGHT
from shared_state import SharedState

RECV_BUF_SIZE   = 131072
FONT            = cv2.FONT_HERSHEY_SIMPLEX
DETECTION_COLOR = (0, 200, 255)
TARGET_W, TARGET_H = 720, 480


class RobotLogic:
    def __init__(self, state: SharedState):
        self._state  = state
        self.running = False
        self._stop   = threading.Event()
        self._thread = None
        self._frame_count = 0
        self._fps         = 0.0
        self._last_fps_t  = time.time()
        self._yolo         = None
        self._yolo_loaded  = False
        self._yolo_enabled = YOLO_ENABLED
        self._latest_frame_for_ai = None
        self._latest_boxes        = []
        self._ai_lock             = threading.Lock()

    def start(self):
        self._stop.clear()
        self.running = True
        self._state.set_video_ai_status(loaded=False, enabled=self._yolo_enabled)
        if self._yolo_enabled:
            threading.Thread(target=self._load_yolo, daemon=True).start()
        self._thread = threading.Thread(target=self._video_loop, daemon=True)
        self._thread.start()
        self._state.log("Video backend started.")

    def stop(self):
        self._stop.set()
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _load_yolo(self):
        try:
            from ultralytics import YOLO
            self._yolo        = YOLO(YOLO_MODEL)
            self._yolo_loaded = True
            self._state.set_video_ai_status(loaded=True, enabled=True)
            self._state.log("✅ YOLO model loaded.")
            threading.Thread(target=self._ai_worker, daemon=True).start()
        except Exception as e:
            self._state.log(f"⚠️ YOLO load failed: {e}")
            self._yolo_enabled = False
            self._state.set_video_ai_status(loaded=False, enabled=False)

    def _ai_worker(self):
        while not self._stop.is_set():
            if self._latest_frame_for_ai is None:
                time.sleep(0.01)
                continue
            frame = self._latest_frame_for_ai.copy()
            try:
                results   = self._yolo(frame, conf=YOLO_CONFIDENCE, verbose=False)
                new_boxes = []
                det_dicts = []
                for result in results:
                    if result.boxes:
                        for box in result.boxes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                            name = result.names.get(int(box.cls[0]), str(int(box.cls[0])))
                            conf = float(box.conf[0])
                            new_boxes.append((x1, y1, x2, y2, name, conf))
                            det_dicts.append({"bbox": (x1, y1, x2, y2), "label": name, "conf": conf})
                with self._ai_lock:
                    self._latest_boxes = new_boxes
                self._state.set_latest_detections(det_dicts)
            except Exception:
                pass
            time.sleep(0.01)

    def _video_loop(self):
        sock = self._create_socket()
        if not sock:
            return
        stream_started = False
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(RECV_BUF_SIZE)
                if not stream_started:
                    self._state.log(f"✅ Video stream from {addr[0]}")
                    stream_started = True

                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                frame = cv2.resize(frame, (TARGET_W, TARGET_H), interpolation=cv2.INTER_LINEAR)

                if self._yolo_enabled and self._yolo_loaded:
                    self._latest_frame_for_ai = frame

                frame = self._draw_detections(frame)
                frame = self._draw_hud(frame)
                self._update_fps()
                self._state.set_video_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), self._fps)

            except socket.timeout:
                if stream_started:
                    self._state.log("⚠️ Video stream timeout...")
                stream_started = False
            except Exception as e:
                if not self._stop.is_set():
                    self._state.log(f"Video error: {e}")
        sock.close()

    def _draw_detections(self, frame):
        if not self._yolo_enabled:
            return frame
        if not self._yolo_loaded:
            cv2.putText(frame, "AI: Loading...", (10, 30), FONT, 0.6, DETECTION_COLOR, 2)
            return frame
        with self._ai_lock:
            boxes = list(self._latest_boxes)
        for x1, y1, x2, y2, name, conf in boxes:
            label = f"{name} {conf:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), DETECTION_COLOR, 2)
            (tw, th), _ = cv2.getTextSize(label, FONT, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), DETECTION_COLOR, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4), FONT, 0.5, (0, 0, 0), 1)
        return frame

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        cv2.putText(frame, f"FPS: {self._fps:.1f}", (w - 100, 20), FONT, 0.5, (0, 255, 200), 1)
        if self._yolo_enabled and self._yolo_loaded:
            ai_txt, ai_col = "AI: ON", (0, 200, 255)
        elif self._yolo_enabled:
            ai_txt, ai_col = "AI: LOADING", (0, 200, 100)
        else:
            ai_txt, ai_col = "AI: OFF", (100, 100, 100)
        cv2.putText(frame, ai_txt, (10, 20), FONT, 0.5, ai_col, 1)
        cv2.putText(frame, time.strftime("%H:%M:%S"), (10, h - 10), FONT, 0.4, (150, 150, 150), 1)
        return frame

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUF_SIZE)
        try:
            sock.bind(('0.0.0.0', VIDEO_PORT))
            sock.settimeout(2.0)
            return sock
        except OSError as e:
            self._state.log(f"❌ Cannot bind video port {VIDEO_PORT}: {e}")
            self.running = False
            return None

    def _update_fps(self):
        self._frame_count += 1
        now = time.time()
        if now - self._last_fps_t >= 1.0:
            self._fps         = self._frame_count / (now - self._last_fps_t)
            self._frame_count = 0
            self._last_fps_t  = now