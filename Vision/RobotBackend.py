import cv2
import socket
import numpy as np
import threading
import paramiko
import time
# REMOVED: from ultralytics import YOLO (We moved this down!)

class RobotLogic:
    def __init__(self, log_callback):
        # --- Connection Config ---
        self.pi_ip = '192.168.4.101'
        self.username = 'pi'
        self.password = 'raspberry'
        self.port = 5000
        
        # --- App State ---
        self.running = False
        self.latest_frame = None
        self.log = log_callback 
        
        # --- AI Settings ---
        self.confidence_threshold = 0.4

    def start(self):
        if not self.running:
            self.running = True
            thread = threading.Thread(target=self.run_process, daemon=True)
            thread.start()

    def stop(self):
        self.running = False
        self.log("System shutdown initiated.")

    def _trigger_remote_camera(self):
        try:
            self.log("Connecting to Pi via SSH...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.pi_ip, username=self.username, password=self.password)
            
            cmd = "nohup /home/pi/rov-env/bin/python3 /home/pi/camera_stream.py > /dev/null 2>&1 &"
            ssh.exec_command(cmd)
            ssh.close()
            self.log("Pi camera triggered.")
        except Exception as e:
            self.log(f"SSH Error: {e}")

    def run_process(self):
        # --- LAZY LOAD: IMPORT YOLO HERE ---
        # This prevents the GUI from lagging at startup.
        # The AI will only load when you actually click "Connect".
        self.log("Initializing AI Engine (this may take a moment)...")
        from ultralytics import YOLO  
        
        self._trigger_remote_camera()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576) 
        sock.bind(('0.0.0.0', self.port))
        sock.settimeout(2.0)

        self.log("Loading YOLOv8 Model...")
        model = YOLO('yolov8n.pt') 
        self.log("AI Ready. Waiting for Video...")

        frame_count = 0
        ai_frequency = 5 
        results = None

        while self.running:
            try:
                try:
                    data, _ = sock.recvfrom(65536)
                except ConnectionResetError:
                    time.sleep(0.1)
                    continue

                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

                if frame is not None:
                    try:
                        frame_count += 1
                        if frame_count % ai_frequency == 0:
                            small_frame = cv2.resize(frame, (320, 240))
                            results = model(small_frame, verbose=False)
                            frame_count = 0

                        if results:
                            for r in results:
                                for box in r.boxes:
                                    if float(box.conf[0]) > self.confidence_threshold:
                                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                                        x1, x2 = x1 * 2, x2 * 2
                                        y1, y2 = y1 * 2, y2 * 2
                                        
                                        cls = int(box.cls[0])
                                        label = f"{model.names[cls]} {float(box.conf[0]):.2f}"

                                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                        
                                        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                                        cv2.rectangle(frame, (x1, y1 - 20), (x1 + w, y1), (0, 255, 0), -1)
                                        cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                    except Exception as ai_err:
                        print(f"AI Error: {ai_err}")

                    self.latest_frame = frame

            except socket.timeout:
                sock.sendto(b"START_STREAM", (self.pi_ip, self.port))
                continue