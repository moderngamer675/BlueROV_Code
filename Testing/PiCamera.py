import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk
import threading
import cv2
import socket
import struct
import math
import paramiko
import numpy as np
import time
from ultralytics import YOLO

class RobotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BlueROV Autonomous Control")
        self.root.geometry("1000x700")
        self.root.configure(bg="#2c3e50")

        # --- VARIABLES ---
        self.running = False
        self.socket = None
        self.ssh = None
        
        # --- GUI LAYOUT ---
        
        # 1. Video Display Area (Top Left)
        self.video_label = tk.Label(root, text="Camera Offline", bg="black", fg="white", font=("Arial", 14))
        self.video_label.place(x=20, y=20, width=800, height=500)

        # 2. Terminal Log Area (Bottom Left)
        self.log_box = scrolledtext.ScrolledText(root, height=8, font=("Consolas", 10), bg="black", fg="#00ff00")
        self.log_box.place(x=20, y=540, width=800, height=130)
        self.log("System Initialized. Ready to Connect.")

        # 3. Control Panel (Right Side)
        self.btn_connect = tk.Button(root, text="CONNECT", bg="#27ae60", fg="white", font=("Arial", 12, "bold"), command=self.start_thread)
        self.btn_connect.place(x=840, y=50, width=140, height=50)

        self.btn_disconnect = tk.Button(root, text="DISCONNECT", bg="#f39c12", fg="white", font=("Arial", 12, "bold"), command=self.stop_stream)
        self.btn_disconnect.place(x=840, y=120, width=140, height=50)

        self.btn_close = tk.Button(root, text="CLOSE APP", bg="#c0392b", fg="white", font=("Arial", 12, "bold"), command=self.close_app)
        self.btn_close.place(x=840, y=620, width=140, height=50)

    # --- LOGGING HELPER ---
    def log(self, message):
        self.log_box.insert(tk.END, f">> {message}\n")
        self.log_box.see(tk.END) # Auto-scroll to bottom

    # --- MAIN LOGIC ---
    def start_thread(self):
        # Run connection in a separate thread to keep GUI responsive
        if not self.running:
            self.running = True
            threading.Thread(target=self.connect_and_stream, daemon=True).start()

    def connect_and_stream(self):
        ROBOT_IP = '192.168.4.85'
        PORT = 9999
        
        # 1. SSH Connection
        try:
            self.log(f"Connecting to Pi via SSH at {ROBOT_IP}...")
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(ROBOT_IP, username='pi', password='pi')
            
            self.log("Starting remote camera script...")
            self.ssh.exec_command("pkill -9 python3; nohup python3 /home/pi/sender.py > /dev/null 2>&1 &")
            
            self.log("Waiting 5s for camera warmup...")
            time.sleep(5)
            self.ssh.close()
            
        except Exception as e:
            self.log(f"SSH Error: {e}")
            self.running = False
            return

        # 2. Socket Connection
        try:
            self.log("Connecting to Video Stream...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ROBOT_IP, PORT))
            self.log("Success! Loading AI Model...")
            
            model = YOLO('../YOLO_Weights/yolov8n.pt').to('cuda')
            self.log("AI Loaded. Streaming Started.")
            
            data = b""
            payload_size = struct.calcsize("Q")

            while self.running:
                # Receive Data
                while len(data) < payload_size:
                    packet = self.socket.recv(4096)
                    if not packet: break
                    data += packet
                
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("Q", packed_msg_size)[0]
                
                while len(data) < msg_size:
                    data += self.socket.recv(4096)
                
                frame_data = data[:msg_size]
                data = data[msg_size:]
                
                # Decode
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                
                if frame is not None:
                    # Run YOLO
                    results = model(frame, stream=True, verbose=False)
                    for r in results:
                        for box in r.boxes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            conf, cls = math.ceil(box.conf[0] * 100) / 100, int(box.cls[0])
                            
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
                            cv2.putText(frame, f'{model.names[cls]} {conf}', (x1, y1 - 10), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

                    # Convert to Tkinter Image
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img_pil = Image.fromarray(img_rgb)
                    img_tk = ImageTk.PhotoImage(image=img_pil)
                    
                    # Update GUI
                    self.video_label.configure(image=img_tk)
                    self.video_label.image = img_tk
        
        except Exception as e:
            self.log(f"Stream Error: {e}")
        finally:
            self.stop_stream()

    def stop_stream(self):
        self.log("Disconnecting...")
        self.running = False
        if self.socket:
            self.socket.close()
        self.video_label.configure(image='', text="Camera Offline")
        self.log("Disconnected.")

    def close_app(self):
        self.stop_stream()
        self.root.destroy()

# --- ENTRY POINT ---
if __name__ == "__main__":
    root = tk.Tk()
    app = RobotApp(root)
    root.mainloop()