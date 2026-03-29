# RobotTelemetry.py
# MAVLink communication handler for BlueROV2
# Background thread with thread-safe callbacks

import threading
import time
from pymavlink import mavutil
from rov_config import MAV_PORT, SOURCE_SYSTEM

RAD2DEG = 57.2958

# Battery voltage thresholds: (min_voltage, color)
BATTERY_THRESHOLDS = [
    (15.5, "#00E676"),  # Green — good
    (14.5, "#FFD600"),  # Yellow — OK
    (13.5, "#FF9100"),  # Orange — low
    (0.0,  "#FF1744"),  # Red — critical
]


class TelemetryHandler:

    def __init__(self, update_callback, log_callback):
        self._update = update_callback
        self._log = log_callback
        self._thread = None
        self._stop = threading.Event()
        self.running = False
        self.mav = None
        self.armed = False

        self._telem = {
            "mode": "—", "armed": False,
            "battery_v": 0.0, "battery_a": 0.0,
            "depth": 0.0, "heading": 0, "throttle": 0,
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "pressure": 0.0, "temp": 0.0,
            "servo": [1500] * 6,
        }

        self._last_hb = 0.0
        self._last_ctrl = 0.0
        self._ctrl_hz = 10

    # =========================================================================
    #  START / STOP
    # =========================================================================

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="TelemetryThread")
        self._thread.start()
        self.running = True
        self._log("Telemetry thread started.")

    def stop(self):
        self._log("Stopping telemetry...")
        self._stop.set()
        self.running = False
        if self.mav:
            try:
                self._send_neutral()
                time.sleep(0.2)
                self.arm_disarm(False)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)
        self._log("Telemetry stopped.")

    # =========================================================================
    #  MAIN THREAD
    # =========================================================================

    def _run(self):
        if not self._connect():
            return

        # Message dispatch table
        self._dispatch = {
            'HEARTBEAT':         self._on_heartbeat,
            'SYS_STATUS':        self._on_sys_status,
            'VFR_HUD':           self._on_vfr_hud,
            'ATTITUDE':          self._on_attitude,
            'SCALED_PRESSURE':   self._on_pressure,
            'SERVO_OUTPUT_RAW':  self._on_servo,
            'NAMED_VALUE_FLOAT': self._on_named_value,
        }

        while not self._stop.is_set():
            now = time.time()

            if now - self._last_hb >= 1.0:
                self._send_heartbeat()
                self._last_hb = now

            if now - self._last_ctrl >= (1.0 / self._ctrl_hz):
                self._send_neutral()
                self._last_ctrl = now

            msg = self.mav.recv_match(blocking=True, timeout=0.05)
            if msg is None:
                continue

            mt = msg.get_type()
            if mt != 'BAD_DATA' and mt in self._dispatch:
                self._dispatch[mt](msg)

        self._log("Telemetry loop ended.")

    def _connect(self) -> bool:
        self._log(f"Connecting to MAVLink on UDP:{MAV_PORT}...")
        try:
            self.mav = mavutil.mavlink_connection(
                f'udp:0.0.0.0:{MAV_PORT}', source_system=SOURCE_SYSTEM)
        except Exception as e:
            self._log(f"❌ MAVLink connection failed: {e}")
            self.running = False
            return False

        self._log("Waiting for heartbeat from Pixhawk...")
        hb = self.mav.wait_heartbeat(timeout=15)
        if hb is None:
            self._log("❌ No heartbeat — check MAVProxy on Pi")
            self.running = False
            return False

        self._log(f"✅ MAVLink connected — System {self.mav.target_system}")
        self._log(f"   Mode: {mavutil.mode_string_v10(hb)}")

        self._update("STATUS", "ONLINE", "#00E676")
        self._update("LINK", "ACTIVE", "#00E676")
        self._set_manual_mode()
        return True

    # =========================================================================
    #  MESSAGE HANDLERS
    # =========================================================================

    def _on_heartbeat(self, msg):
        mode = mavutil.mode_string_v10(msg)
        armed = bool(msg.base_mode &
                     mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        self._telem.update(mode=mode, armed=armed)
        self.armed = armed

        self._update("STATUS", mode)
        self._update("ARMED_STATE",
                     "⚠ ARMED" if armed else "SAFE",
                     "#FF1744" if armed else "#00E676")

    def _on_sys_status(self, msg):
        v = msg.voltage_battery / 1000.0
        a = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
        self._telem.update(battery_v=v, battery_a=a)

        bat_col = next(c for thresh, c in BATTERY_THRESHOLDS if v > thresh)
        self._update("BATTERY", f"{v:.2f}", bat_col)
        self._update("CURRENT", f"{a:.1f}")

    def _on_vfr_hud(self, msg):
        depth = abs(msg.alt)
        self._telem.update(depth=depth, heading=msg.heading,
                           throttle=msg.throttle)
        self._update("DEPTH", f"{depth:.2f}")
        self._update("HEADING", f"{msg.heading}")

    def _on_attitude(self, msg):
        roll, pitch, yaw = (msg.roll * RAD2DEG, msg.pitch * RAD2DEG,
                            msg.yaw * RAD2DEG)
        self._telem.update(roll=roll, pitch=pitch, yaw=yaw)
        self._update("ROLL", f"{roll:+.1f}")
        self._update("PITCH", f"{pitch:+.1f}")

    def _on_pressure(self, msg):
        self._telem.update(pressure=msg.press_abs,
                           temp=msg.temperature / 100.0)

    def _on_servo(self, msg):
        servos = [getattr(msg, f'servo{i}_raw', 1500) for i in range(1, 7)]
        self._telem["servo"] = servos

        thrust = [max(-1.0, min(1.0, (pwm - 1500) / 400.0))
                  for pwm in servos]
        self._update("THRUSTERS", thrust)

    def _on_named_value(self, msg):
        name = msg.name.strip('\x00').strip()
        self._update(f"SENSOR_{name}", f"{msg.value:.3f}")

    # =========================================================================
    #  MOTOR CONTROL
    # =========================================================================

    def set_motion(self, forward=0.0, lateral=0.0, throttle=0.0, yaw=0.0):
        """Send MANUAL_CONTROL. All values -1.0 to +1.0."""
        if not (self.mav and self.running):
            return
        x = max(-1000, min(1000, int(forward * 1000)))
        y = max(-1000, min(1000, int(lateral * 1000)))
        z = max(0, min(1000, int(500 + throttle * 500)))
        r = max(-1000, min(1000, int(yaw * 1000)))
        self.mav.mav.manual_control_send(
            self.mav.target_system, x, y, z, r, 0)

    def stop_motors(self):
        self._send_neutral()

    def _send_neutral(self):
        if self.mav and self.running:
            self.mav.mav.manual_control_send(
                self.mav.target_system, 0, 0, 500, 0, 0)

    # =========================================================================
    #  ARM / MODE
    # =========================================================================

    def arm_disarm(self, arm: bool):
        if not self.mav:
            return
        self.mav.mav.command_long_send(
            self.mav.target_system, self.mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, int(arm), 21196, 0, 0, 0, 0, 0)
        self._log(f"Sent {'ARM' if arm else 'DISARM'} command to vehicle.")
        if not arm:
            self._send_neutral()

    def _set_manual_mode(self):
        self._set_mode("MANUAL")
        self._log("MANUAL mode set.")

    def _set_mode(self, mode_name: str):
        if not self.mav:
            return
        mode_id = self.mav.mode_mapping().get(mode_name)
        if mode_id is None:
            self._log(f"⚠️  {mode_name} mode not found in mode map")
            return
        self.mav.mav.set_mode_send(
            self.mav.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_id)

    def set_mode(self, mode_name: str):
        self._set_mode(mode_name)
        self._log(f"Mode → {mode_name}")

    # =========================================================================
    #  HELPERS
    # =========================================================================

    def _send_heartbeat(self):
        if self.mav:
            self.mav.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)

    def get_telemetry(self) -> dict:
        return dict(self._telem)