import tkinter as tk
from tkinter import scrolledtext, font, messagebox
from PIL import Image, ImageTk
import cv2
import socket
import numpy as np
import threading
import paramiko
import time
from pymavlink import mavutil

# --- 1. CONFIGURATION (MATCHES YOUR WORKING SCRIPT) ---
PI_IP = '192.168.4.101'
PI_USER = 'pi'
PI_PASS = 'raspberry'
LAPTOP_IP = '192.168.4.60'
MAV_PORT = 14550
VIDEO_PORT = 5000

# --- 2. PROFESSIONAL THEME ---
COLOR_BG        = "#121212"
COLOR_PANEL     = "#1E1E1E"
COLOR_TEXT      = "#E0E0E0"
COLOR_ACCENT    = "#007ACC"
COLOR_SUCCESS   = "#28A745"
COLOR_WARNING   = "#FFC107"
COLOR_DANGER    = "#DC3545"
COLOR_LOG_BG    = "#000000"
COLOR_LOG_TEXT  = "#00FF00"
COLOR_CARD_BG   = "#252525"

class ProfessionalROV:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.latest_frame = None
        self.telemetry_labels = {}  # Dictionary to store UI labels
        
        self.setup_window()
        self.create_layout()
        self.log("System Ready. Click 'START MISSION'.")

    def setup_window(self):
        self.root.title("BlueROV Command Station")
        self.root.geometry("1100x750")
        self.root.configure(bg=COLOR_BG)
        # Fonts
        self.font_header = font.Font(family="Segoe UI", size=16, weight="bold")
        self.font_val = font.Font(family="Consolas", size=14, weight="bold")
        self.font_lbl = font.Font(family="Segoe UI", size=8)

    def create_layout(self):
        # Header
        header = tk.Frame(self.root, bg=COLOR_PANEL, height=50)
        header.pack(fill=tk.X, pady=10, padx=10)
        tk.Label(header, text="MISSION CONTROL", font=self.font_header, bg=COLOR_PANEL, fg=COLOR_ACCENT).pack(side=tk.LEFT, padx=15)
        self.lbl_status = tk.Label(header, text="STANDBY", font=("Segoe UI", 11, "bold"), bg=COLOR_PANEL, fg="#888")
        self.lbl_status.pack(side=tk.RIGHT, padx=15)

        # Content Area
        content = tk.Frame(self.root, bg=COLOR_BG)
        content.pack(fill=tk.BOTH, expand=True, padx=10)

        # LEFT: Video
        vid_wrap = tk.Frame(content, bg=COLOR_PANEL)
        vid_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.video_label = tk.Label(vid_wrap, text="NO SIGNAL", bg="black", fg="#444", font=("Segoe UI", 14))
        self.video_label.pack(expand=True)

        # RIGHT: Sidebar
        sidebar = tk.Frame(content, bg=COLOR_PANEL, width=260)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="TELEMETRY DATA", font=("Segoe UI", 10, "bold"), bg=COLOR_PANEL, fg="#888").pack(pady=(20, 10))
        
        # Data Grid - KEYS NOW MATCH YOUR WORKING SCRIPT EXACTLY (Title Case)
        grid = tk.Frame(sidebar, bg=COLOR_PANEL)
        grid.pack(fill=tk.X, padx=10)
        
        self.create_card(grid, "Mode", "STABILIZE", 0, 0, 2)
        self.create_card(grid, "Battery", "--- V", 1, 0)
        self.create_card(grid, "Depth", "--- m", 1, 1)
        self.create_card(grid, "Heading", "---°", 2, 0)
        self.create_card(grid, "Attitude", "R:0 P:0", 2, 1)
        self.create_card(grid, "GPS", "NO FIX", 3, 0, 2)

        # Buttons
        tk.Label(sidebar, text="OPERATIONS", font=("Segoe UI", 10, "bold"), bg=COLOR_PANEL, fg="#888").pack(pady=(20, 10))
        self.btn_connect = tk.Button(sidebar, text="START MISSION", bg=COLOR_SUCCESS, fg="white", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=self.toggle_connection)
        self.btn_connect.pack(fill=tk.X, padx=15, pady=5, ipady=8)
        
        tk.Button(sidebar, text="EXIT", bg=COLOR_DANGER, fg="white", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, command=self.close_app).pack(fill=tk.X, padx=15, pady=5, ipady=8)

        # Log
        self.log_box = scrolledtext.ScrolledText(self.root, height=8, bg="black", fg="#0f0", font=("Consolas", 9))
        self.log_box.pack(fill=tk.X, padx=10, pady=10)

    def create_card(self, parent, key, val, r, c, sp=1):
        card = tk.Frame(parent, bg=COLOR_CARD_BG, highlightthickness=1, highlightbackground="#333")
        card.grid(row=r, column=c, columnspan=sp, sticky="nsew", padx=4, pady=4)
        parent.grid_columnconfigure(c, weight=1)
        tk.Label(card, text=key, font=self.font_lbl, bg=COLOR_CARD_BG, fg="#888").pack(anchor="w", padx=5)
        lbl = tk.Label(card, text=val, font=self.font_val, bg=COLOR_CARD_BG, fg=COLOR_TEXT)
        lbl.pack()
        # Store the label using the exact key (e.g., "Battery")
        self.telemetry_labels[key] = lbl

    def log(self, msg):
        self.log_box.insert(tk.END, f">> {msg}\n")
        self.log_box.see(tk.END)

    # --- 3. THE LOGIC (COPIED EXACTLY FROM YOUR WORKING SCRIPT) ---

    def toggle_connection(self):
        if not self.running:
            self.running = True
            self.btn_connect.config(text="STOP MISSION", bg=COLOR_WARNING)
            self.lbl_status.config(text="CONNECTING...", fg=COLOR_WARNING)
            
            # Start the threads
            threading.Thread(target=self.telemetry_loop, daemon=True).start()
            threading.Thread(target=self.video_loop, daemon=True).start()
        else:
            self.running = False
            self.btn_connect.config(text="START MISSION", bg=COLOR_SUCCESS)
            self.lbl_status.config(text="DISCONNECTED", fg=COLOR_DANGER)
            self.video_label.config(image='')
            self.log("Mission Stopped.")

    def start_mavproxy_remote(self):
        """EXACT SSH LOGIC from your working script."""
        try:
            self.log(f"SSH: Connecting to {PI_IP}...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(PI_IP, username=PI_USER, password=PI_PASS)
            
            # 1. Kill old processes
            ssh.exec_command("pkill -f mavproxy; pkill -f python3")
            time.sleep(0.5) # Matches your working script

            # 2. Start Camera
            cam_cmd = "nohup /home/pi/rov-env/bin/python3 /home/pi/camera_stream.py > /dev/null 2>&1 &"

            # 3. Start MAVProxy (Exact command string from your working script)
            mav_cmd = (f"cd /home/pi && nohup /home/pi/rov-env/bin/python3 /home/pi/rov-env/bin/mavproxy.py "
                       f"--master=/dev/ttyACM0 --baudrate=115200 "
                       f"--out=udp:{LAPTOP_IP}:{MAV_PORT} --daemon > /dev/null 2>&1 &")
            
            ssh.exec_command(f"{cam_cmd} && {mav_cmd}")
            ssh.close()
            self.log("SSH: Services Triggered.")
            return True
        except Exception as e:
            self.log(f"SSH Error: {e}")
            return False

    def telemetry_loop(self):
        # 1. Trigger SSH first
        if not self.start_mavproxy_remote():
            self.running = False
            return

        # 2. Start Listener
        self.log(f"Telemetry: Listening on {MAV_PORT}...")
        try:
            connection_string = f'udp:0.0.0.0:{MAV_PORT}'
            master = mavutil.mavlink_connection(connection_string)
            self.log("Telemetry: Connected!")
            self.root.after(0, lambda: self.lbl_status.config(text="ONLINE", fg=COLOR_SUCCESS))

            while self.running:
                msg = master.recv_match(blocking=False)
                if msg:
                    msg_type = msg.get_type()
                    
                    # KEYS MATCH EXACTLY NOW (Title Case)
                    if msg_type == 'HEARTBEAT':
                        mode = mavutil.mode_string_v10(msg)
                        self.update_ui("Mode", mode, COLOR_WARNING)
                    
                    elif msg_type == 'SYS_STATUS':
                        v = msg.voltage_battery / 1000.0
                        c = COLOR_SUCCESS if v > 14.0 else COLOR_DANGER
                        self.update_ui("Battery", f"{v:.2f} V", c)
                    
                    elif msg_type == 'VFR_HUD':
                        self.update_ui("Heading", f"{msg.heading}°")
                        self.update_ui("Depth", f"{abs(msg.alt):.2f} m", COLOR_ACCENT)
                    
                    elif msg_type == 'ATTITUDE':
                        r, p = msg.roll * 57.3, msg.pitch * 57.3
                        self.update_ui("Attitude", f"R:{r:.0f} P:{p:.0f}")
                    
                    elif msg_type == 'GPS_RAW_INT':
                        lat, lon = msg.lat/1e7, msg.lon/1e7
                        self.update_ui("GPS", f"{lat:.4f}, {lon:.4f}")

                time.sleep(0.01) # Matches your working script
        except Exception as e:
            self.log(f"Telemetry Error: {e}")

    def video_loop(self):
        self.log("Video: Starting AI...")
        from ultralytics import YOLO
        model = YOLO('yolov8n.pt')
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
        sock.bind(('0.0.0.0', VIDEO_PORT))
        sock.settimeout(2.0)

        frame_cnt = 0
        while self.running:
            try:
                try:
                    data, _ = sock.recvfrom(65536)
                except ConnectionResetError:
                    time.sleep(0.1); continue
                
                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    # AI Logic
                    frame_cnt += 1
                    if frame_cnt % 5 == 0:
                        small = cv2.resize(frame, (320, 240))
                        results = model(small, verbose=False)
                        frame_cnt = 0
                        if results:
                            for r in results:
                                for box in r.boxes:
                                    if float(box.conf[0]) > 0.4:
                                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                                        x1, x2, y1, y2 = x1*2, x2*2, y1*2, y2*2
                                        cls = int(box.cls[0])
                                        label = f"{model.names[cls]}"
                                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                        cv2.putText(frame, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                    
                    # Update Video Label
                    img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                    self.root.after(0, lambda: self.video_label.config(image=img))
                    self.video_label.image = img # Keep ref

            except socket.timeout:
                sock.sendto(b"START_STREAM", (PI_IP, VIDEO_PORT))

    def update_ui(self, key, val, color=COLOR_TEXT):
        if key in self.telemetry_labels:
            self.root.after(0, lambda: self.telemetry_labels[key].config(text=val, fg=color))

    def close_app(self):
        self.running = False
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalROV(root)
    root.mainloop()