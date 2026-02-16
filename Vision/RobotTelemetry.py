import threading
import time
from pymavlink import mavutil

class TelemetryHandler:
    def __init__(self, update_callback, log_callback):
        self.running = False
        self.connection = None
        self.update_ui = update_callback  
        self.log = log_callback           
        self.port = 14550                 

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self.running = False

    def run(self):
        self.log("Telemetry: Waiting for stream...")
        try:
            # Matches your working script: Listen on all interfaces
            connection_string = f'udp:0.0.0.0:{self.port}'
            self.connection = mavutil.mavlink_connection(connection_string)
            
            # Wait for heartbeat
            self.connection.wait_heartbeat()
            self.log("Telemetry: Connected!")

            while self.running:
                # Matches your working script: Non-blocking receive
                msg = self.connection.recv_match(blocking=False)
                
                if msg:
                    msg_type = msg.get_type()

                    # --- EXACT PARSING LOGIC FROM YOUR WORKING SCRIPT ---
                    
                    if msg_type == 'SYS_STATUS':
                        volts = msg.voltage_battery / 1000.0
                        color = "#28A745" if volts > 14.0 else "#DC3545"
                        self.update_ui("BATTERY", f"{volts:.2f} V", color)

                    elif msg_type == 'VFR_HUD':
                        heading = msg.heading
                        depth = abs(msg.alt)
                        self.update_ui("HEADING", f"{heading}°", "#E0E0E0")
                        self.update_ui("DEPTH", f"{depth:.2f} m", "#007ACC")

                    elif msg_type == 'HEARTBEAT':
                        mode = mavutil.mode_string_v10(msg)
                        self.update_ui("MODE", mode, "#FFC107")

                    elif msg_type == 'ATTITUDE':
                        r = msg.roll * 57.3
                        p = msg.pitch * 57.3
                        self.update_ui("ATTITUDE", f"R:{r:.0f} P:{p:.0f}", "#888888")

                    elif msg_type == 'GPS_RAW_INT':
                        lat = msg.lat / 1e7
                        lon = msg.lon / 1e7
                        self.update_ui("GPS", f"{lat:.4f}, {lon:.4f}", "#E0E0E0")

                time.sleep(0.01)

        except Exception as e:
            self.log(f"Telemetry Error: {e}")