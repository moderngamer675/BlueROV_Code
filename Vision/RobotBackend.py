import threading, socket, time, numpy as np, cv2
from rov_config import LAPTOP_IP, VIDEO_PORT, FRAME_WIDTH, FRAME_HEIGHT, YOLO_MODEL, YOLO_CONFIDENCE, YOLO_ENABLED
from shared_state import SharedState

RECV_BUF_SIZE = 131072
FONT, DETECTION_COLOR = cv2.FONT_HERSHEY_SIMPLEX, (0, 200, 255)
# Set target size to match GUI panel exactly to avoid double resizing
TARGET_W, TARGET_H = 720, 480 

class RobotLogic:
    def __init__(self, state: SharedState):
        self._state, self.running, self._thread = state, False, None
        self._stop = threading.Event()
        self._frame_count, self._fps, self._last_fps_t = 0, 0.0, time.time()
        self._yolo, self._yolo_loaded, self._yolo_enabled = None, False, YOLO_ENABLED
        
        # --- NEW: Asynchronous AI State ---
        self._ai_thread = None
        self._latest_frame_for_ai = None
        self._latest_boxes = []
        self._ai_lock = threading.Lock()

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
            self._state.log("  ✅  YOLO model loaded.")
            
            # Start the background AI worker only after YOLO loads
            self._ai_thread = threading.Thread(target=self._ai_worker, daemon=True)
            self._ai_thread.start()
        except Exception as e:
            self._state.log(f"  ⚠️  YOLO load failed/disabled: {e}")
            self._yolo_enabled = False
            self._state.set_video_ai_status(loaded=False, enabled=False)

    def _ai_worker(self):
        """Runs YOLO inference in the background without slowing down the video."""
        while not self._stop.is_set():
            if self._latest_frame_for_ai is None:
                time.sleep(0.01)
                continue
            
            # Process a copy of the most recent frame
            frame_to_process = self._latest_frame_for_ai.copy()
            try:
                results = self._yolo(frame_to_process, conf=YOLO_CONFIDENCE, verbose=False)
                new_boxes = []
                for result in results:
                    if result.boxes:
                        for box in result.boxes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                            name = result.names.get(int(box.cls[0]), str(int(box.cls[0])))
                            new_boxes.append((x1, y1, x2, y2, name, float(box.conf[0])))
                
                # Safely update the boxes for the video loop to draw
                with self._ai_lock:
                    self._latest_boxes = new_boxes
            except Exception:
                pass
            time.sleep(0.01) # Yield to prevent maxing out CPU

    def _video_loop(self):
        sock = self._create_socket()
        if not sock: return
        stream_started = False
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(RECV_BUF_SIZE)
                if not stream_started:
                    self._state.log(f"  ✅  Video stream received from {addr[0]}")
                    stream_started = True
                
                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None: continue
                
                # 1. Resize ONCE to the final GUI dimensions
                frame = cv2.resize(frame, (TARGET_W, TARGET_H), interpolation=cv2.INTER_LINEAR)
                
                # 2. Silently pass the frame to the AI thread
                if self._yolo_enabled and self._yolo_loaded:
                    self._latest_frame_for_ai = frame
                
                # 3. Draw the latest known AI boxes & HUD
                frame = self._draw_hud(self._draw_latest_ai(frame))
                self._update_fps()
                
                # 4. Convert BGR to RGB off the main UI thread
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._state.set_video_frame(frame_rgb, self._fps)
                
            except socket.timeout:
                if stream_started: self._state.log("  ⚠️  Video stream timeout...")
                stream_started = False
            except Exception as e:
                if not self._stop.is_set(): self._state.log(f"Video error: {e}")
        sock.close()

    def _draw_latest_ai(self, frame):
        if not self._yolo_enabled: return frame
        if not self._yolo_loaded:
            self._overlay_text(frame, "AI: Loading...", (10, 30), 0.6, DETECTION_COLOR, 2)
            return frame
            
        # Quickly draw the boxes generated by the background thread
        with self._ai_lock:
            for x1, y1, x2, y2, name, conf in self._latest_boxes:
                label_txt = f"{name} {conf:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), DETECTION_COLOR, 2)
                (tw, th), _ = cv2.getTextSize(label_txt, FONT, 0.5, 1)
                cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), DETECTION_COLOR, -1)
                cv2.putText(frame, label_txt, (x1 + 2, y1 - 4), FONT, 0.5, (0, 0, 0), 1)
        return frame

    def _draw_hud(self, frame):
        h, w = frame.shape[:2]
        self._overlay_text(frame, f"FPS: {self._fps:.1f}", (w - 100, 20), 0.5, (0, 255, 200))
        ai_txt, ai_col = ("AI: ON", (0, 200, 255)) if self._yolo_enabled and self._yolo_loaded else ("AI: LOADING", (0, 200, 100)) if self._yolo_enabled else ("AI: OFF", (100, 100, 100))
        self._overlay_text(frame, ai_txt, (10, 20), 0.5, ai_col)
        self._overlay_text(frame, time.strftime("%H:%M:%S"), (10, h - 10), 0.4, (150, 150, 150))
        return frame

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUF_SIZE)
        try:
            sock.bind(('0.0.0.0', VIDEO_PORT))
            sock.settimeout(2.0)
            return sock
        except OSError as e:
            self._state.log(f"  ❌  Cannot bind video port {VIDEO_PORT}: {e}")
            self.running = False
            return None

    def _update_fps(self):
        self._frame_count += 1
        now = time.time()
        if now - self._last_fps_t >= 1.0:
            self._fps = self._frame_count / (now - self._last_fps_t)
            self._frame_count, self._last_fps_t = 0, now

    @staticmethod
    def _overlay_text(frame, text, pos, scale, color, thickness=1):
        cv2.putText(frame, text, pos, FONT, scale, color, thickness)