import tkinter as tk
from tkinter import messagebox
import threading
import time
from pymavlink import mavutil
import paramiko

# --- CONFIGURATION ---
PI_IP = '192.168.4.101'
PI_USER = 'pi'
PI_PASS = 'raspberry'
LAPTOP_IP = '192.168.4.60'
PORT = 14550

class ROVDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("BlueROV2 Telemetry Dashboard")
        self.root.geometry("500x600")
        self.root.configure(bg="#1e1e1e") # Dark theme

        self.running = False
        self.setup_ui()

    def setup_ui(self):
        # Title
        tk.Label(self.root, text="ROV TELEMETRY", font=("Arial", 18, "bold"), bg="#1e1e1e", fg="white").pack(pady=10)

        # Status Button
        self.btn_connect = tk.Button(self.root, text="START MISSION", command=self.toggle_connection, bg="#28a745", fg="white", font=("Arial", 12, "bold"))
        self.btn_connect.pack(pady=10)

        # Telemetry Display Frames
        self.data_fields = {
            "Mode": self.create_data_box("Flight Mode"),
            "Battery": self.create_data_box("Battery Voltage"),
            "Heading": self.create_data_box("Heading (Compass)"),
            "Depth": self.create_data_box("Depth (Meters)"),
            "Attitude": self.create_data_box("Roll / Pitch"),
            "GPS": self.create_data_box("GPS Coordinates")
        }

        self.status_bar = tk.Label(self.root, text="Disconnected", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_data_box(self, label_text):
        frame = tk.Frame(self.root, bg="#1e1e1e")
        frame.pack(fill=tk.X, padx=20, pady=5)
        
        lbl = tk.Label(frame, text=label_text, font=("Arial", 10), bg="#1e1e1e", fg="#aaaaaa")
        lbl.pack(side=tk.LEFT)
        
        txt = tk.Entry(frame, font=("Consolas", 12, "bold"), bg="#333333", fg="#00ff00", borderwidth=0)
        txt.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=10)
        txt.insert(0, "---")
        return txt

    def update_field(self, field, value):
        self.data_fields[field].delete(0, tk.END)
        self.data_fields[field].insert(0, value)

    def start_mavproxy_remote(self):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(PI_IP, username=PI_USER, password=PI_PASS)
            ssh.exec_command("pkill -f mavproxy")
            time.sleep(0.5)
            cmd = (f"cd /home/pi && nohup /home/pi/rov-env/bin/python3 /home/pi/rov-env/bin/mavproxy.py "
                   f"--master=/dev/ttyACM0 --baudrate=115200 "
                   f"--out=udp:{LAPTOP_IP}:{PORT} --daemon > /dev/null 2>&1 &")
            ssh.exec_command(cmd)
            ssh.close()
            return True
        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not reach Pi: {e}")
            return False

    def telemetry_loop(self):
        if not self.start_mavproxy_remote():
            self.running = False
            return

        connection_string = f'udp:0.0.0.0:{PORT}'
        master = mavutil.mavlink_connection(connection_string)
        self.status_bar.config(text=f"Connected to {PI_IP}", fg="green")

        while self.running:
            msg = master.recv_match(blocking=False)
            if msg:
                msg_type = msg.get_type()
                
                if msg_type == 'HEARTBEAT':
                    mode = mavutil.mode_string_v10(msg)
                    self.update_field("Mode", mode)
                
                elif msg_type == 'SYS_STATUS':
                    v = msg.voltage_battery / 1000.0
                    self.update_field("Battery", f"{v:.2f} V")
                
                elif msg_type == 'VFR_HUD':
                    self.update_field("Heading", f"{msg.heading}°")
                    self.update_field("Depth", f"{abs(msg.alt):.2f} m")
                
                elif msg_type == 'ATTITUDE':
                    r, p = msg.roll * 57.3, msg.pitch * 57.3
                    self.update_field("Attitude", f"R: {r:.1f}° P: {p:.1f}°")
                
                elif msg_type == 'GPS_RAW_INT':
                    lat, lon = msg.lat/1e7, msg.lon/1e7
                    self.update_field("GPS", f"{lat:.4f}, {lon:.4f}")

            time.sleep(0.01)

    def toggle_connection(self):
        if not self.running:
            self.running = True
            self.btn_connect.config(text="STOP MISSION", bg="#dc3545")
            threading.Thread(target=self.telemetry_loop, daemon=True).start()
        else:
            self.running = False
            self.btn_connect.config(text="START MISSION", bg="#28a745")
            self.status_bar.config(text="Disconnected", fg="black")

if __name__ == "__main__":
    root = tk.Tk()
    app = ROVDashboard(root)
    root.mainloop()