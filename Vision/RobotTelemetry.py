import threading
import time
from pymavlink import mavutil

class TelemetryHandler:
    def __init__(self, update_callback, log_callback):
        self.running = False
        self.update_ui = update_callback  
        self.log = log_callback           
        self.port = 14551  
        self.master = None

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self.running = False

    def arm_disarm(self, arm_command=True):
        if self.master:
            action = 1 if arm_command else 0
            self.log(f"MAVLink: {'ARMING' if arm_command else 'DISARMING'}...")
            self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0, action, 0, 0, 0, 0, 0, 0
            )

    def run(self):
        self.log("Telemetry: Listening on Port 14551...")
        try:
            self.master = mavutil.mavlink_connection(f'udp:0.0.0.0:{self.port}')
            self.master.wait_heartbeat(timeout=10)
            self.log("Telemetry: Heartbeat Detected!")
            
            while self.running:
                msg = self.master.recv_match(blocking=False)
                if msg:
                    msg_type = msg.get_type()
                    
                    if msg_type == 'HEARTBEAT':
                        mode = mavutil.mode_string_v10(msg)
                        self.update_ui("MODE", mode, "#FFC107")
                        is_armed = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                        self.update_ui("STATUS", "ARMED" if is_armed else "DISARMED", "#28A745" if is_armed else "#DC3545")

                    elif msg_type == 'SYS_STATUS':
                        volts = msg.voltage_battery / 1000.0
                        amps = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
                        self.update_ui("BATTERY", f"{volts:.2f} V", "#28A745" if volts > 13.5 else "#DC3545")
                        self.update_ui("CURRENT", f"{amps:.1f} A", "#E0E0E0")

                    elif msg_type == 'VFR_HUD':
                        self.update_ui("DEPTH", f"{abs(msg.alt):.2f} m", "#007ACC")
                        self.update_ui("HEADING", f"{msg.heading}°", "#E0E0E0")

                    # Inside the run loop of TelemetryHandler in RobotTelemetry.py:

                    elif msg_type == 'ATTITUDE':
                        # Convert radians to degrees
                        roll = msg.roll * 57.2958
                        pitch = msg.pitch * 57.2958
                        # Updated color to #00FFFF (Cyan)
                        self.update_ui("ATTITUDE", f"R:{roll:.1f}°  P:{pitch:.1f}°", "#00FFFF")

                time.sleep(0.01)
        except Exception as e:
            self.log(f"Telemetry Error: {e}")