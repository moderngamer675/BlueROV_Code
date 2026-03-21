import cv2
import socket
import numpy as np
import threading
import paramiko
import time

class RobotLogic:
    def __init__(self, log_callback):
        # --- Connection Config (WIRED TETHER) ---
        self.pi_ip = '192.168.2.2'      # The Fathom-X IP
        self.username = 'pi'
        self.password = 'raspberry'
        self.laptop_ip = '192.168.2.1'  # Your Laptop's Wired IP
        self.video_port = 5000          # Port for Camera
        self.mav_port = 14550           # Port for Telemetry
        
        # --- App State ---
        self.running = False
        self.latest_frame = None
        self.log = log_callback 
        self.stream_active = False      # Track if we have video or not
        
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

    def _trigger_remote_services(self):
        """
        Starts both the Camera and MAVProxy on the Pi via SSH.
        """
        try:
            self.log(f"Connecting to Pi ({self.pi_ip}) via SSH...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.pi_ip, username=self.username, password=self.password, timeout=5)
            
            # 1. KILL OLD PROCESSES
            self.log("Cleaning up old background services...")
            ssh.exec_command("pkill -f mavproxy; pkill -f python3")
            time.sleep(1.0) 

            # 2. START CAMERA
            self.log("Starting Remote Camera Stream...")
            cam_cmd = f"nohup /home/pi/rov-env/bin/python3 /home/pi/camera_stream.py > /dev/null 2>&1 &"
            ssh.exec_command(cam_cmd)
            
            # 3. START TELEMETRY (Dual Stream)
            self.log("Starting Telemetry Bridge (Dual Output)...")
            # Output 1 -> Port 14550 (Standard, for QGroundControl)
            # Output 2 -> Port 14551 (Custom, for this Python App)
            mav_cmd = (f"cd /home/pi && nohup /home/pi/rov-env/bin/python3 /home/pi/rov-env/bin/mavproxy.py "
                       f"--master=/dev/ttyACM0 --baudrate=115200 "
                       f"--out=udp:{self.laptop_ip}:14550 "
                       f"--out=udp:{self.laptop_ip}:14551 "
                       f"--daemon > /dev/null 2>&1 &")
            ssh.exec_command(mav_cmd)
            
            ssh.close()
            self.log("Remote Services Started Successfully.")
            return True
        except Exception as e:
            self.log(f"SSH Connection Failed: {e}")
            return False

    def run_process(self):
        # --- LAZY LOAD YOLO ---
        self.log("Initializing AI Engine (this may take 5s)...")
        try:
            from ultralytics import YOLO
            self.log("YOLO Library Loaded.")
        except ImportError:
            self.log("Error: Ultralytics not found. AI features disabled.")
            return
        
        # Trigger the Pi
        if not self._trigger_remote_services():
            self.log("Critical Error: Could not start Pi services.")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576) 
        sock.bind(('0.0.0.0', self.video_port))
        sock.settimeout(2.0)

        self.log(f"Loading Neural Network Model...")
        model = YOLO('yolov8n.pt') 
        self.log("AI Ready. Waiting for Video Feed...")

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
                
                # --- LOGGING: Confirm Video Connection ---
                if not self.stream_active:
                    self.stream_active = True
                    self.log("Video Stream ESTABLISHED (Connection Good).")

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
                        # Log error to GUI instead of crashing
                        self.log(f"AI Error: {ai_err}")

                    self.latest_frame = frame

            except socket.timeout:
                # --- LOGGING: Alert if stream dies ---
                if self.stream_active:
                    self.log("Warning: Video Stream LOST. Attempting to reconnect...")
                    self.stream_active = False
                
                # If video drops, nudge the Pi again
                sock.sendto(b"START_STREAM", (self.pi_ip, self.video_port))
                continue